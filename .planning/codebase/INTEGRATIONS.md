# INTEGRATIONS.md — External Services & APIs

## TuShare Pro API

**Provider:** TuShare Pro (proxied through `fastapic.stockai888.top`)

**Used endpoints in `src/data_fetcher.py`:**

| Endpoint | Purpose | Source doc |
|----------|---------|------------|
| `income` | 利润表 (86 float fields) | `.refs/tushare-docs/33.md` |
| `balancesheet` | 资产负债表 (150 float fields) | `.refs/tushare-docs/36.md` |
| `cashflow` | 现金流量表 (89 float fields) | `.refs/tushare-docs/44.md` |
| `daily_basic` | 最新市值/股本/价格/PE/PB | `.refs/tushare-docs/32.md` |
| `stock_basic` | 公司名称解析 | — |
| `trade_cal` | 最新交易日 | — |

**Authentication:** `TUSHARE_TOKEN` in `.env`.

**Rate limiting:** `TUSHARE_MIN_INTERVAL_SECONDS=0.8` between requests (≈75/min, below proxy 100/min limit). `data_fetcher.py` retries on rate-limit errors with 60s backoff.

## 巨潮资讯网 (cninfo)

**Integration file:** `src/report_downloader.py`

**Vendored wrapper:** `vendor/use_cninfo/src/cninfo/`

**APIs used:**

| API | Purpose | File |
|-----|---------|------|
| `topSearch/query` | Resolve stock code → `orgId` | `report_downloader.py:fetch_company_info()` |
| `hisAnnouncement/query` | List annual/quarterly reports | `cninfo.api.query_page()` |
| Static PDF URL | Download report PDFs | `cninfo.api.adjunct_to_url()` / `fetch_pdf_bytes()` |

**Report categories queried:**

- `category_ndbg_szsh` — 年度报告
- `category_yjdbg_szsh` — 第一季度报告
- `category_bndbg_szsh` — 半年度报告
- `category_sjdbg_szsh` — 第三季度报告

**Rate limiting:** Random 1–2s sleep between cninfo requests/PDF downloads; configurable via `--min-interval`/`--max-interval`.

**Output:** PDF + Markdown under `companies/{name}_{code}/annuals/` and `quarterlyreports/{year}/`.

## LLM Providers

**Used by:** `src/annual_report_reconciler.py` and `src/annual_report_extractor.py`

**Configured via `.env`:**

| Variable | Default | Usage |
|----------|---------|-------|
| `LLM_PROVIDER` | `glm` | Primary provider selection |
| `GLM_API_KEY` | — | GLM API key |
| `GLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | GLM endpoint |
| `GLM_MODEL` | `glm-5-turbo` | Reconciler/extractor model |
| `KIMI_API_KEY` | — | Kimi fallback |
| `KIMI_BASE_URL` | `https://api.moonshot.cn/v1` | Kimi endpoint |
| `KIMI_MODEL` | `kimi-k2.6` | Kimi model |
| `KIMI_THINKING` | `disabled` | Instant mode for extractor |
| `LLM_MAX_TOKENS` | `32768` | Max response tokens |

**Reconciler prompt strategy:**
- Sends failure context + candidate TuShare fields + annual-report Markdown snippets
- Asks for JSON with suspected issue, root cause, missing items, and recommended action
- High-confidence exact-residual suggestions can become approved overrides

**Extractor prompt strategy:**
- Sends full annual report Markdown + `skills/annual_report_extractor_v2.md` skill contract
- Produces a structured company fact archive markdown file

## SQLite Internal Interfaces

Downstream modules (`defaults_gen.py`, `calc.py`, `init.py`) read from `data.db` tables:

- `clean_annual` — latest audited annual row as DCF base
- `meta` — total shares, market cap, closing price
- `clean_adjustments` / `clean_warnings` — audit trail for human review
