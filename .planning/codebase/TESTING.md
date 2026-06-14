# TESTING.md — Test Structure & Practices

## Test Framework

- **pytest** (installed globally alongside project dependencies)
- Test directory: `tests/`
- `tests/conftest.py` ensures `D:/MKA` is on `sys.path` so `import src.*` works regardless of invocation directory.

## Test Files

| File | Focus | Approximate Cases |
|------|-------|-------------------|
| `tests/test_clean.py` | `clean.py` helpers and validation logic | 10+ |
| `tests/test_data_fetcher.py` | Unit conversion and error classification | 14+ |
| `tests/test_report_downloader.py` | Report title parsing and rate-limit helpers | 8+ |

## What Is Tested

### `test_clean.py`

- `resolve()` combo-field logic:
  - all split fields present → sum splits
  - missing splits → use combo
  - both missing → zero
  - `oth_pay_total` preferred over split sum
  - split sum zero but combo non-zero → use combo
- `period_label()` quarter suffix mapping
- `check_is()` on a balanced income-statement row
- `check_is()` failure detection when `total_profit` mismatches
- `check_bs()` on a balanced balance-sheet row
- `check_bs()` failure when assets ≠ liabilities + equity
- `treasury_share` anomaly treated as warning, not error
- `check_cf()` on a balanced cash-flow row
- `check_cf()` failure when CFO mismatches
- Quarterly pivot behavior:
  - income `report_type=2` missing still keeps BS/CF data
  - `max_quarters` drops early periods correctly

### `test_data_fetcher.py`

- `convert_value()` for all unit types (`amount_cny`, `percent`, `share`, `daily_basic_share_10k`, `daily_basic_mv_10k_cny`, `turnover_rate`, `ratio`, `price`)
- `None` / `NaN` handling in conversion
- Unknown unit raises `ValueError`
- `is_auth_or_permission_error()` classification
- `is_permanent_error()` classification (parameter errors vs. rate limits/timeouts)

### `test_report_downloader.py`

- `parse_report()` matches annual reports, revisions
- Excludes summaries, English versions, audit reports
- Matches Q1/H1/Q3 reports
- Missing `adjunctUrl` / `announcementId` returns `None`
- `sleep_between_requests()` is a no-op when `max_interval <= 0`

## What Is Not Currently Unit-Tested

- Live TuShare API calls (require token and network).
- Live cninfo downloads (network-dependent).
- Full SQLite pipeline end-to-end (tested via manual sample companies).
- LLM reconciliation/extraction paths (require API keys).
- `init.py` orchestration (integration-level, CLI-tested manually).
- `defaults_gen.py` and `calc.py` DCF engine (validated by running on sample companies).

## Running Tests

```bash
# From repository root
python -m pytest tests/

# Verbose
python -m pytest tests/ -v

# Specific file
python -m pytest tests/test_clean.py -v
```

## Validation Outside Tests

The project relies on sample company validation as an integration check. Verified samples documented in `docs/ARCHITECTURE.md` include:

- 安克创新 (300866.SZ)
- 新乳业 (002946.SZ)
- 伊利股份 (600887.SH)
- 美的集团 (000333.SZ)
- 比亚迪 (002594.SZ)

These are run with:

```bash
python -m src.init 000333.SZ
python -m src.clean --ticker 000333.SZ --mode annual
python -m src.defaults_gen --ticker 300866.SZ
python -m src.calc --ticker 300866.SZ
```
