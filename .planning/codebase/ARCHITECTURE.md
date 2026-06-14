# ARCHITECTURE.md — System Design & Patterns

## System Purpose

MKA is a two-stage pipeline for A-share (non-financial) company financial data:

1. **Fetch** raw statements from TuShare Pro, normalize units, and mirror them into SQLite.
2. **Clean** the raw EAV data into validated wide tables with strict accounting identity checks.

Additional capabilities:
- Download annual/quarterly report PDFs + Markdown from cninfo.
- Use LLM-aided annual report reconciliation to fill TuShare disclosure gaps.
- Generate default DCF forecast parameters (YAML2) and run a deterministic DCF model.

## High-Level Data Flow

```
TuShare Pro API
      ↓ data_fetcher.py (stage 1)
   SQLite raw_tushare + meta
      ↓ clean.py (stage 2)
   SQLite clean_annual / clean_quarterly + debug CSV
      ↓ defaults_gen.py
   defaults.yaml
      ↓ calc.py
   forecast CSVs + DCF summary

cninfo (annual/quarterly reports)
      ↓ report_downloader.py
   companies/{name}_{code}/annuals/*.pdf|.md
      ↓ annual_report_reconciler.py (when clean fails)
   recon/annual_report_overrides.json
      ↓ clean.py (rerun)
   approved adjustments applied to clean_annual
```

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `src/init.py` | Single orchestration entry: ticker resolution → fetch → report download → clean with auto-reconcile |
| `src/data_fetcher.py` | TuShare API client, unit conversion, EAV mirror, health checks |
| `src/clean.py` | EAV→wide pivot, accounting validation, override application, audit tables |
| `src/report_downloader.py` | cninfo report discovery, PDF/Markdown download |
| `src/annual_report_reconciler.py` | Diagnose clean failures against annual-report Markdown; LLM evidence; generate overrides |
| `src/annual_report_extractor.py` | LLM-based extraction of annual report into research archive |
| `src/yaml2_schema.py` | YAML2 parameter schema validation and I/O helpers |
| `src/defaults_gen.py` | Build `defaults.yaml` from latest `clean_annual` row |
| `src/calc.py` | Deterministic IS→BS→CF→DCF forecast engine |

## Key Design Patterns

### EAV Mirror Pattern
`raw_tushare` stores every official TuShare field as rows:
`(ticker, endpoint, report_type, end_date, field, value, ...)`.
This preserves upstream data verbatim and makes downstream pivots/reconciliation possible.

### Validation-First Cleaning
`clean.py` does not silently fix data. It runs hard checks and stops on failure:
- 25+ hard checks on annual data
- Quarterly data uses explicit QA plug fields to absorb incomplete disclosure
- Annual `target_gt_calc` failures trigger LLM reconciliation rather than plugs

### Reconciliation-Over-Plug Philosophy
From `docs/CLAUDE.md`: **TuShare data gaps are fixed by reading the annual report, not by artificial plugs.**
- `raw_tushare` is never modified.
- Approved overrides apply only to `clean_annual` and are audited in `clean_adjustments`.

### Accounting-First Forecast Engine
`calc.py` builds forecasts in order:
1. Income statement from revenue and ratios
2. Balance sheet driven by IS + turnover assumptions + explicit cash/st_borr plug
3. Cash flow derived from IS + BS changes
4. FCFF DCF valuation

It iterates each forecast year until financial expense and plug converge.

### Deterministic Defaults
`defaults_gen.py` generates a complete YAML2 parameter set from the latest clean annual row with **zero analyst judgment** (e.g., revenue_yoy = 0). This proves the model mechanics are sound before any forecasting overlays are applied.

## Data Integrity Mechanisms

- **Primary key** on `raw_tushare` prevents duplicate ingestion.
- **UPSERT** semantics allow incremental refreshes.
- **Health checks** before write verify field coverage, ticker consistency, and basic balance-sheet/cashflow identities.
- **Audit tables** (`clean_adjustments`, `clean_warnings`) preserve every non-TuShare fix and soft warning.
- **Override approval policy** only accepts high-confidence LLM evidence (`source=glm|kimi`).

## Cross-Endpoint Field Disambiguation

The field `credit_impa_loss` exists in both `income` and `cashflow` with potentially different values. `clean.py` prefixes colliding columns as `income.credit_impa_loss` and `cashflow.credit_impa_loss` so both can coexist in the wide table.

## Quarter Handling

- Income: uses `report_type=2` (single-quarter) when available; falls back to `report_type=1` cumulative.
- Balance sheet: point-in-time, no split.
- Cash flow: `report_type=1` cumulative values are split locally into single-quarter values (Q2=H1−Q1, Q3=Q3cum−H1, Q4=Annual−Q3cum).
- Only the most recent 48 quarters are kept by default to avoid early-disclosure inconsistencies.
