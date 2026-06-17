# Official TuShare Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make official TuShare the only trusted financial data source while adapting official raw output into MKA's stable clean schema without company-specific hardcoding.

**Architecture:** `raw_tushare` remains an immutable mirror of official TuShare responses. A generic clean/reconciler adapter layer handles field omissions, endpoint collisions, sign conventions, and subtotal formula differences using accounting identities plus annual-report evidence. Downstream files keep using `docs/数据格式参考.md` as the stable clean contract.

**Tech Stack:** Python 3.11, SQLite, pandas, pytest, TuShare SDK, local annual report Markdown, `annual_report_reconciler.py`, `knowledge/known_tushare_defects.json`.

---

## Source Audit

### Primary Schema Source

Use `docs/tushare官方源财务schema.md` as the project-local official-source schema reference. It was regenerated from the official TuShare skill Markdown exported under `D:\MKA\TushareOfficialAPIMD\`:

- `D:\MKA\TushareOfficialAPIMD\income.md` -> `income`
- `D:\MKA\TushareOfficialAPIMD\balancesheet.md` -> `balancesheet`
- `D:\MKA\TushareOfficialAPIMD\cashflow.md` -> `cashflow`

The official skill repository is `https://github.com/waditu-tushare/skills`; TuShare documents it with:

```bash
npx skills add https://github.com/waditu-tushare/skills --skill tushare
```

The three finance statement documents map to the stable official Markdown URLs:

- `https://tushare.pro/wctapi/documents/33.md` -> `income`
- `https://tushare.pro/wctapi/documents/36.md` -> `balancesheet`
- `https://tushare.pro/wctapi/documents/44.md` -> `cashflow`

The generated schema currently verifies:

| endpoint | output columns | statement fields | metadata fields |
|---|---:|---:|---:|
| `income` | 94 | 86 | 8 |
| `balancesheet` | 158 | 150 | 8 |
| `cashflow` | 97 | 89 | 8 |

The 325 statement fields match the existing clean contract: 86 + 150 + 89.

Important parsing rule: TuShare input parameters are not raw payload fields. `start_date`, `period`, and `is_calc` may appear in request parameter tables, but they must not be validated as output fields in `raw_tushare`.

## Design Rules

1. No company-specific logic. Never branch on company name, ticker, listing venue, or known one-off company examples.
2. Keep `raw_tushare` official and immutable. Do not write derived values, overrides, sign fixes, or normalized subtotals back into `raw_tushare`.
3. Keep `docs/数据格式参考.md` as the clean schema contract. Do not rename or reclassify its fields unless a global TuShare schema change requires it.
4. Annual adaptation must be evidence-backed. For annual clean failures, use annual-report Markdown and approved overrides.
5. Quarterly adaptation may use explicit QA plugs only where reports disclose subtotals without full detail, and must write warnings.
6. Adapter behavior must be explainable from official fields and accounting identities.

---

## Implementation Tasks

### Task 1: Lock Official TuShare Endpoint Discipline

**Files:**
- Modify: `src/data_fetcher.py`
- Modify: `.env` only if the user explicitly asks; otherwise document expected values
- Test: `tests/test_data_fetcher.py`

**Step 1: Write failing tests**

Add tests that assert:

```python
def test_default_tushare_url_is_official():
    assert data_fetcher.DEFAULT_TUSHARE_HTTP_URL == "http://api.waditu.com/dataapi"


def test_non_official_tushare_url_is_rejected(monkeypatch):
    monkeypatch.setenv("TUSHARE_HTTP_URL", "https://example.invalid")
    # Expected behavior: ValueError for any non-official TuShare endpoint.
```

**Step 2: Run tests to verify failure**

Run:

```bash
py -3 -m pytest tests/test_data_fetcher.py -q
```

Expected: the new default-source test fails before implementation.

**Step 3: Implement minimal endpoint guard**

Change `DEFAULT_TUSHARE_HTTP_URL` to official TuShare SDK endpoint:

```python
DEFAULT_TUSHARE_HTTP_URL = "http://api.waditu.com/dataapi"
ALLOWED_TUSHARE_HTTP_HOSTS = {"api.waditu.com", "api.tushare.pro"}
```

Add a helper:

```python
def validate_tushare_http_url(url: str) -> str:
    if url_host not in ALLOWED_TUSHARE_HTTP_HOSTS:
        raise ValueError("TUSHARE_HTTP_URL must use official TuShare source")
    return url
```

Use it in `create_tushare_client()`.

**Step 4: Verify**

Run:

```bash
py -3 -m pytest tests/test_data_fetcher.py -q
```

Expected: PASS.

---

### Task 2: Add Official Schema Consistency Tests

**Files:**
- Create: `tests/test_tushare_official_schema.py`
- Read: `docs/tushare官方源财务schema.md`
- Read: `D:\MKA\TushareOfficialAPIMD\income.md`
- Read: `D:\MKA\TushareOfficialAPIMD\balancesheet.md`
- Read: `D:\MKA\TushareOfficialAPIMD\cashflow.md`
- Read: `src/clean.py`

**Step 1: Write failing tests**

Add tests that parse the official-cache docs and assert:

```python
EXPECTED_STATEMENT_COUNTS = {
    "income": 86,
    "balancesheet": 150,
    "cashflow": 89,
}
```

Also assert every field in `clean.IS_FIELD_CATEGORIES`, `clean.BS_FIELD_CATEGORIES`, and `clean.CF_FIELD_CATEGORIES` exists in the corresponding official docs, excluding QA plug fields and endpoint-prefixed clean columns.

**Step 2: Run tests**

Run:

```bash
py -3 -m pytest tests/test_tushare_official_schema.py -q
```

Expected: FAIL until parser/test fixture is complete.

**Step 3: Implement parser in the test file only**

Keep the parser local to the test file. Do not add production code unless multiple modules need it.

**Step 4: Verify**

Run:

```bash
py -3 -m pytest tests/test_tushare_official_schema.py -q
```

Expected: PASS.

---

### Task 3: Make Profit Statement Validation Official-Source Aware

**Files:**
- Modify: `src/clean.py`
- Test: `tests/test_clean.py`

**Step 1: Write failing tests**

Add a test for the modern official-source pattern:

```python
def test_modern_total_cogs_can_include_impairment_losses_without_hard_fail():
    row = {
        "revenue": 1000.0,
        "total_revenue": 1000.0,
        "oper_cost": 600.0,
        "biz_tax_surchg": 10.0,
        "sell_exp": 80.0,
        "admin_exp": 50.0,
        "rd_exp": 40.0,
        "fin_exp": 20.0,
        "assets_impair_loss": -30.0,
        "income.credit_impa_loss": 5.0,
        "oth_income": 12.0,
        "asset_disp_income": 3.0,
        "invest_income": 0.0,
        "fv_value_chg_gain": 0.0,
        "total_cogs": 835.0,
        "operate_profit": 227.0,
        "total_profit": 227.0,
        "income_tax": 27.0,
        "n_income": 200.0,
        "n_income_attr_p": 200.0,
        "minority_gain": 0.0,
    }
    present = {k.replace("income.", "") for k, v in row.items() if v != 0.0}
    sign_map = {"assets_impair_loss": 1, "credit_impa_loss": 1}
    assert clean.check_is(row, present, "2024", sign_map=sign_map) == []
```

**Step 2: Run the specific test**

Run:

```bash
py -3 -m pytest tests/test_clean.py::TestIncomeStatementChecks -q
```

Expected: FAIL until validation understands the official-source subtotal pattern.

**Step 3: Implement generic formula helper**

In `src/clean.py`, add a helper that computes:

- stable report-cost sum excluding sign-questionable impairment fields
- sign-resolved impairment adjustments
- operating adjustment sum
- official `total_cogs` route
- report-main-table route

Do not branch on ticker. Use only field presence and accounting equation residuals.

**Step 4: Verify**

Run:

```bash
py -3 -m pytest tests/test_clean.py::TestIncomeStatementChecks -q
```

Expected: PASS.

---

### Task 4: Expand Generic Known-Defect Hints

**Files:**
- Modify: `knowledge/known_tushare_defects.json`
- Modify: `src/annual_report_reconciler.py`
- Test: add or extend tests if reconciler tests exist; otherwise add focused unit tests around hint selection

**Step 1: Add generic hint cards**

Add cards for:

- `income.oth_income` / `IS 1.2` / `operating_adjustment`
- `income.asset_disp_income` / `IS 1.2` / `operating_adjustment`
- `income.credit_impa_loss` / `IS 1.2` / `cost_item`
- `balancesheet.oth_illiq_fin_assets` / `BS 2.2` / `noncurrent_asset`
- `balancesheet.use_right_assets` / `BS 2.2` / `noncurrent_asset`
- `balancesheet.lease_liab` / `BS 3.2` / `noncurrent_liab`

Each card must describe trigger direction, target field, expected annual-report aliases, and the rule that hints do not approve overrides.

**Step 2: Update candidate field logic**

Ensure `annual_report_reconciler.py` surfaces hint fields even when the static bucket candidate list would omit them or when the field exists but is zero.

**Step 3: Verify hint selection**

Run:

```bash
py -3 -m pytest tests -q
```

Expected: PASS.

---

### Task 5: Reconcile Anker Official Data Without Company Hardcoding

**Files:**
- Read: `companies/安克创新_300866/data.db`
- Read: `companies/安克创新_300866/annuals/2024_年度报告.md`
- Generated: `companies/安克创新_300866/recon/annual_report_overrides.json`

**Step 1: Run clean annual**

Run:

```bash
py -3 -m src.clean --ticker 300866.SZ --db companies/安克创新_300866/data.db --mode annual
```

Expected: if no overrides exist yet, failures should point to generic official-source patterns.

**Step 2: Run reconciler**

Run:

```bash
py -3 -m src.annual_report_reconciler --ticker 300866.SZ --db companies/安克创新_300866/data.db --max-failures 30 --write-overrides --approve-high-confidence
```

Expected: approved overrides for fields justified by annual-report lines, without company-specific code.

**Step 3: Rerun clean**

Run:

```bash
py -3 -m src.clean --ticker 300866.SZ --db companies/安克创新_300866/data.db --mode annual
```

Expected: annual hard checks pass or remaining failures are reduced to clearly documented non-field issues.

---

### Task 6: Update Documentation Without Changing Clean Field Tables

**Files:**
- Modify: `docs/数据格式参考.md`
- Modify: `docs/数据流水线.md`
- Modify: `docs/ARCHITECTURE.md`

**Step 1: Add a preface to `docs/数据格式参考.md`**

Add a short section before the field tables:

```markdown
## 官方源适配说明

本文件是 clean 宽表契约，不是 raw TuShare 返回完整性的保证。`raw_tushare` 保存官方源原样字段；字段缺失、跨端点同名、减值符号和小计口径差异由 clean/reconciler 适配层处理，并写入审计记录。
```

Do not rename, remove, or reorder existing field rows.

**Step 2: Update pipeline docs**

Document:

- official TuShare only
- no proxy source
- raw immutable
- generic adapter layer
- annual override evidence path

**Step 3: Verify docs**

Run:

```bash
rg -n "官方源|raw_tushare|适配" docs CLAUDE.md
```

Expected: docs describe only the official TuShare source.

---

## Final Verification

Run:

```bash
py -3 -m pytest tests/test_clean.py tests/test_data_fetcher.py tests/test_tushare_official_schema.py -q
py -3 -m src.init 300866.SZ --force
```

Expected:

- Unit tests pass.
- `src.init` uses official TuShare source only.
- Anker annual clean either passes directly or passes after generic annual-report overrides.
- No implementation code branches on `300866`, `安克创新`, or any other company identifier.

---

## Non-Goals

- Do not install or depend on external TuShare schema snapshots.
- Do not use legacy local TuShare doc caches as the finance schema source.
- Do not add company-specific patches.
- Do not change downstream field names in `docs/数据格式参考.md`.
- Do not modify `raw_tushare` values after official fetch.
