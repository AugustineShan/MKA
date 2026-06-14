# CONVENTIONS.md — Code Style & Patterns

## Python Version & Environment

- Python 3.11+ required.
- Use **system/global Python**; no virtual environments.
- Verify `which python` does not point to `WindowsApps`; use `~/.bashrc` alias or absolute path under `C:/Users/Sheld/AppData/Local/Programs/Python/Python*/python.exe` if needed.
- Batch files must use absolute Python path (per CLAUDE.md).

## Formatting & Typing

- Type hints encouraged for function signatures and dataclasses.
- `from __future__ import annotations` at the top of most modules.
- Docstrings explain module purpose, public APIs, and CLI usage.
- Logging via module-level `logging.getLogger(__name__)` rather than print-debugging.

## Naming Conventions

| Kind | Style | Example |
|------|-------|---------|
| Module | `snake_case.py` | `data_fetcher.py` |
| Function/variable | `snake_case` | `fetch_company` |
| Class | `PascalCase` | `TushareDataFetcher` |
| Constant | `UPPER_SNAKE_CASE` | `TOLERANCE` |
| Private helper | `_leading_underscore` | `_call_api` |

## Module Organization Pattern

Each `src/*.py` module typically follows this order:

1. Module docstring with public API and CLI examples
2. Imports
3. Module constants
4. Dataclasses / small value types
5. Public API functions
6. Core class and methods
7. Helper functions
8. CLI `main()`

## Error Handling

- Hard data problems raise custom exceptions (`DataHealthError`, `CheckError`, `CalcError`, `YAML2Error`).
- CLI modules return explicit exit codes:
  - `0` — success
  - `1` — API/network/permission/unknown exception
  - `2` — ticker resolution failure
  - `3` — clean failed even after approved overrides
- Retries are explicit and time-bounded (e.g., 3 attempts with exponential backoff).
- TuShare errors are classified as auth/permission, permanent, or transient in `data_fetcher.py`.

## Units

All stored numeric values use consistent units:

| Concept | Unit | Conversion |
|---------|------|------------|
| CNY amounts | 百万元 | 元 ÷ 1,000,000 |
| Percentages | decimal | % ÷ 100 |
| Shares | 百万股 | 股 ÷ 1,000,000 |
| Daily basic shares | 百万股 | 万股 ÷ 100 |
| Daily basic market cap | 百万元 | 万元 ÷ 100 |
| Turnover rate | days | 365 ÷ rate |
| Ratios / prices | raw | no conversion |

## Field Naming Discipline

- **Only TuShare official field names** in `raw_tushare` and clean tables.
- No internal aliases; no `field_terms.csv`-style mappings.
- The only non-official fields are the six `qa_*_plug` audit columns.

## Data Integrity Conventions

- `raw_tushare` is immutable once written; corrections flow through `clean_adjustments`.
- Every applied override records old value, new value, source, evidence, and reason.
- Quarterly disclosures use explicit QA plug fields rather than silent fixes.
- Missing values in clean tables are filled with `0.0` (columns are never dropped).

## Logging Conventions

- INFO level for normal progress (fetch, clean, download stages).
- WARNING for soft-check failures and plug usage.
- ERROR for hard-check failures.
- Progress messages in Chinese where user-facing; internal logs mixed English/Chinese.

## CLI Conventions

- `--ticker` accepts `000333.SZ`, `600519.SH`, `430047.BJ`.
- `init.py` also accepts Chinese names and bare 6-digit codes.
- `--force` means clear and re-fetch/re-extract.
- `--verbose` enables DEBUG logging.
- Output directories are auto-created; existing files are skipped unless `--force-*` is used.

## Git Conventions

- `.env`, `companies/`, `__pycache__/`, logs, IDE dirs, and worktrees are ignored.
- Feature branches for changes; no direct commits to `main`.
- Incremental commits with descriptive messages.
- `docs/ARCHITECTURE.md` must be updated after any architecture/validation change.
