# STACK.md — Technology Stack

## Language & Runtime

- **Python 3.11+** — system/global Python (no venv per project rules)
- **Windows 10** primary development environment; bash shell used via MSYS2/Git Bash
- All modules are executable as `python -m src.<module>`

## Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `tushare` | >=1.4.0 | TuShare Pro SDK for A-share financial data |
| `pandas` | >=2.0.0 | EAV→wide-table transforms, SQLite I/O, CSV exports |
| `requests` | >=2.31 | cninfo HTTP API, PDF download, direct LLM calls |
| `pymupdf` | >=1.24 | PDF text extraction to Markdown |
| `pyyaml` | >=6.0 | YAML2 defaults.yaml read/write |

## Python Standard Library Used Heavily

- `sqlite3` — per-company database storage
- `pathlib` — filesystem paths
- `argparse` — CLI for every module
- `logging` — structured logging
- `subprocess` — `init.py` orchestrates `report_downloader.py`/`clean.py`
- `concurrent.futures.ThreadPoolExecutor` — concurrent PDF downloads / cninfo category queries
- `dataclasses` — small value objects (`FieldMapping`, `Failure`, `Report`, `CompanyInfo`)
- `json` / `re` / `datetime` — data parsing and validation

## Data Stores

- **SQLite** (`companies/{name}_{code}/data.db`) — primary persistence
  - `raw_tushare` — official TuShare EAV mirror
  - `meta` — company metadata
  - `clean_annual` / `clean_quarterly` — validated wide tables (332 columns)
  - `clean_adjustments` / `clean_warnings` — audit trail
- **CSV** — debug exports next to `data.db`
- **YAML** — `defaults.yaml` DCF parameter sets
- **JSON** — reconciliation evidence and overrides in `recon/`

## External Services

- **TuShare Pro API** via proxy `https://fastapic.stockai888.top`
- **巨潮资讯网 cninfo** — annual/quarterly report PDFs
- **GLM / Kimi LLM APIs** — annual report reconciliation and extraction (optional but default)

## Vendored Code

- `vendor/use_cninfo/` — MIT-licensed fork of `rollysys/use_cninfo`; wraps cninfo API, orgId lookup, PDF fetch, and Markdown extraction
