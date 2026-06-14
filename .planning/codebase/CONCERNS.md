# CONCERNS.md — Technical Debt, Risks & Known Issues

## Architectural Risks

### 1. Heavy Reliance on External APIs
- **TuShare proxy** (`fastapic.stockai888.top`) is a single point of failure. If it becomes unavailable, all data fetching stops.
- **LLM APIs** (GLM/Kimi) are required for automatic annual-report reconciliation and extraction. Without them, `target_gt_calc` failures require manual override creation.
- **cninfo** can change HTML/API structure or block scraping; the vendored wrapper may need updates.

### 2. Vendored Dependency Drift
- `vendor/use_cninfo/` is a static fork. If the upstream repository fixes cninfo API changes, this project will not receive those fixes automatically.
- The vendored code is relied upon for PDF download, orgId lookup, and Markdown extraction.

### 3. Windows-Centric Path and Shell Assumptions
- Several paths and subprocess calls assume Windows/Git Bash behavior (e.g., `sys.executable`, UTF-8 reconfiguration in `init.py`).
- Batch-file guidance in `docs/CLAUDE.md` is Windows-specific.

## Data Quality Risks

### 4. TuShare Disclosure Gaps
- Some companies do not report every field (e.g., 美的集团 `lending_funds`, 比亚迪 `estimated_liab`).
- The reconciliation system works but requires annual-report Markdown to be present and an LLM to confirm evidence.
- If a company has no downloaded annual report or the LLM fails, hard-check failures cannot be auto-resolved.

### 5. Quarter Data Incompleteness
- Quarterly reports disclose fewer line items than annual reports.
- `clean.py` uses explicit QA plug fields to keep quarterly tables balanced, but these plugs mask real disclosure gaps.
- Early quarterly data (pre-2013) is intentionally dropped by `max_quarters=48` to avoid口径 inconsistencies.

### 6. Financial-Company Exclusion
- The system explicitly filters `comp_type != 1` (general industrial/commercial). Banks, insurers, and securities firms are not supported.
- There is no guardrail preventing a user from requesting a financial company; it will simply produce empty/warned data.

## Code Quality Concerns

### 7. Large Monolithic Modules
- `src/clean.py` (~2,190 lines) mixes field categorization, pivot logic, validation, override application, and audit writing.
- `src/annual_report_reconciler.py` (~1,375 lines) mixes LLM prompting, rule-based suggestion, and override file construction.
- Both modules are well-documented but have grown large enough that future changes carry higher regression risk.

### 8. Global Tolerance Mutation
- `clean.py` uses a module-level `TOLERANCE` constant that is temporarily reassigned inside `clean_dataset()` via `global TOLERANCE`.
- This is functional but makes the code harder to reason about and test in parallel.

### 9. Subprocess-Based Orchestration
- `src/init.py` calls `report_downloader.py` and `clean.py` via `subprocess.run()`.
- This provides isolation but loses in-process error detail and makes the orchestrator dependent on Python path/env configuration.

### 10. Limited Test Coverage
- Unit tests cover helper functions but not the full pipeline.
- No automated integration tests for `init.py`, `defaults_gen.py`, or `calc.py`.
- LLM paths are not tested at all.

## Operational Concerns

### 11. Secrets in `.env`
- `.env` contains live API tokens (`TUSHARE_TOKEN`, `GLM_API_KEY`, `KIMI_API_KEY`).
- It is gitignored, but accidental exposure is a persistent risk.

### 12. Output Directory Pollution
- `companies/` is ignored by git but can grow very large with PDFs, Markdown, SQLite DBs, CSVs, and forecasts.
- There is no automatic cleanup or retention policy.

### 13. Concurrency and Rate Limiting
- `report_downloader.py` uses `ThreadPoolExecutor` for concurrent queries/downloads.
- The per-worker sleep is a best-effort throttle; under high concurrency, actual request rate may exceed intended limits.

## Known Open Items

### 14. LLM Override End-to-End for `estimated_liab`
- The `known_tushare_defects.json` entry for 比亚迪 `estimated_liab` includes `clean_category=current_liab`, but the codebase changelog notes that full LLM end-to-end override generation and clean rerun validation was still pending at the time of the last audit.

### 15. YAML1 / Analyst Overlay Not Implemented
- `docs/yaml2_需求文档.md` describes YAML1 as the analyst judgment layer that overlays YAML2 defaults.
- No YAML1 implementation exists; the forecast engine currently only runs flat (0% growth) defaults.

### 16. TTM Base Period
- `defaults_gen.py` uses the latest audited annual row, not TTM.
- The YAML2 spec calls for using the most recent period (could be quarterly TTM), but this is deferred.

## Security Notes

- No input sanitization beyond path-component cleaning; user-provided ticker strings are validated with regex.
- LLM prompts include raw annual-report text and financial values; ensure API keys are scoped and rotated.
- Downloaded PDFs are parsed with PyMuPDF; malformed PDFs could theoretically trigger parser vulnerabilities.
