# STRUCTURE.md — Directory Layout & Naming

## Repository Root

```
D:/MKA/
├── .claude/                  # Claude Code local config (ignored)
├── .env                      # Secrets: TUSHARE_TOKEN, GLM_API_KEY, etc. (ignored)
├── .gitignore                # Ignores .env, companies/, __pycache__, logs, IDE dirs
├── .obsidian/                # Obsidian notes (ignored)
├── .refs/                    # Cached upstream documentation
│   └── tushare-docs/         # TuShare official field docs (33.md, 36.md, 44.md, ...)
├── .serena/                  # Serena memory (ignored)
├── .worktrees/               # Git worktrees (ignored)
├── companies/                # Runtime output; one directory per company (ignored)
│   └── {公司名}_{代码}/
│       ├── data.db
│       ├── clean_annual_{code}.csv
│       ├── clean_quarterly_{code}.csv
│       ├── defaults.yaml
│       ├── forecast/
│       ├── annuals/
│       ├── quarterlyreports/
│       └── recon/
├── docs/                     # Project documentation
│   ├── ARCHITECTURE.md       # System architecture (authoritative)
│   ├── CLAUDE.md             # Project conventions and first principles
│   ├── yaml2_需求文档.md
│   ├── yaml2_calc关系说明.md
│   └── 数据格式参考.md
├── knowledge/                # Lightweight diagnostic hints
│   └── known_tushare_defects.json
├── requirements.txt          # Python dependencies
├── skills/                   # Agent skill contracts
│   └── annual_report_extractor_v2.md
├── src/                      # Core Python source
│   ├── __init__.py
│   ├── init.py
│   ├── data_fetcher.py
│   ├── clean.py
│   ├── report_downloader.py
│   ├── annual_report_reconciler.py
│   ├── annual_report_extractor.py
│   ├── yaml2_schema.py
│   ├── defaults_gen.py
│   └── calc.py
├── tests/                    # pytest suite
│   ├── conftest.py
│   ├── test_clean.py
│   ├── test_data_fetcher.py
│   └── test_report_downloader.py
└── vendor/                   # Vendored third-party code
    └── use_cninfo/           # MIT-licensed cninfo wrapper
        ├── src/cninfo/
        └── README.md
```

## Source File Naming Conventions

- Module names: `snake_case.py`
- CLI entry modules: `python -m src.<module_name>` (e.g., `python -m src.init`)
- Public functions: `snake_case`
- Private helpers: `_leading_underscore`
- Constants: `UPPER_SNAKE_CASE`
- Type aliases/classes: `PascalCase`

## Company Output Directory Naming

```
companies/{safe_company_name}_{stock_code}/
```

Examples:
- `companies/安克创新_300866/`
- `companies/美的集团_000333/`
- `companies/比亚迪_002594/`

## SQLite Table Naming

- `raw_tushare` — upstream mirror
- `meta` — key/value metadata
- `clean_annual` — validated annual wide table
- `clean_quarterly` — validated quarterly wide table
- `clean_adjustments` — approved annual-report overrides audit
- `clean_warnings` — soft warnings and plug explanations

## Field Naming

- **TuShare official field names only** in `raw_tushare` and clean tables (e.g., `total_hldr_eqy_inc_min_int`, `c_pay_acq_const_fiolta`).
- Only exception: six `qa_*_plug` audit fields added by `clean.py`.
- Cross-endpoint collisions prefixed with endpoint: `income.credit_impa_loss`, `cashflow.credit_impa_loss`.

## File Outputs

| File | Producer | Purpose |
|------|----------|---------|
| `data.db` | `data_fetcher.py` | SQLite database |
| `clean_annual_{code}.csv` | `clean.py` | Annual debug CSV |
| `clean_quarterly_{code}.csv` | `clean.py` | Quarterly debug CSV |
| `defaults.yaml` | `defaults_gen.py` | DCF default parameters |
| `forecast/*.csv`, `dcf_summary.json` | `calc.py` | Forecast outputs |
| `annuals/{year}_年度报告.pdf|.md` | `report_downloader.py` | Annual reports |
| `quarterlyreports/{year}/{year}_第一季度报告.pdf|.md` | `report_downloader.py` | Quarterly reports |
| `recon/annual_report_reconciliation_{timestamp}.json` | `annual_report_reconciler.py` | Evidence archive |
| `recon/annual_report_overrides.json` | `annual_report_reconciler.py` | Approved overrides |
| `Extraction/{name}-{year}-年报萃取.md` | `annual_report_extractor.py` | LLM-extracted fact archive |
