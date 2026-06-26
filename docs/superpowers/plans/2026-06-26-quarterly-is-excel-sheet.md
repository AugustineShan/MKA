# 季度利润表 Excel 输出页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `export_company_excel` 输出的工作簿里新增 `季度利润表` sheet，把前端 `QuarterlyTable` 的季度利润表追踪用三表一致的视觉风格画进 Excel。

**Architecture:** 新增一个渲染函数 `_fill_quarterly_is_sheet`，直接调 `src.quarterly_tracker.compute_quarterly_view`（与前端 API 同源）拿到 `{periods, rows, annual, quarter_states, year}`，复用三表现有样式函数（`_style_report_sheet`/`_data_style`/`_label_style`/`_number_format`/`_header_style`/`_auto_widths`）渲染。单元格按年份两色（历史年白底 / 选定年浅蓝底），4 态信息集中在选定年上方一行徽章。在 `export_company_excel` 主体 `_fill_full_statement_sheets` 之后注册一行。

**Tech Stack:** Python 3.11、openpyxl、sqlite3；复用 `src/quarterly_tracker.py`、`src/company_excel_export.py`、`src/field_registry.yaml`（间接，经 compute_quarterly_view）。

**Spec:** `docs/superpowers/specs/2026-06-26-quarterly-is-excel-sheet-design.md`

---

## File Structure

- **Modify** `src/company_excel_export.py`
  - 新增常量 `QUARTERLY_IS_SHEET`、`QUARTERLY_STATE_BADGE`（靠近 `SEMIANNUAL_IS_SHEET`，约 `:64`）
  - 新增 `_ticker_from_db`（靠近 `_quarterly_statement_records`，约 `:1710`）
  - 新增 `_emphasize_quarterly_row`（靠近 `_emphasize_row`，约 `:727`）
  - 新增 `_fill_quarterly_is_sheet`（靠近 `_fill_semiannual_sheets`，约 `:1621`）
  - 在 `export_company_excel` 主体 `:2431` 后注册一行
- **Modify** `tests/test_forecast_pipeline.py`
  - 新增 `test_quarterly_is_sheet_in_company_excel`
  - 更新 `test_run_company_forecast_hides_intermediates_and_rebuilds_forecast` 的 `len(workbook.worksheets) == 8` → `== 9`，sheetnames subset 加 `"季度利润表"`
- **Modify** `docs/数据流水线.md`、`docs/CHANGELOG.md`（记录新 sheet）

---

## Task 1: 写失败测试

**Files:**
- Modify: `tests/test_forecast_pipeline.py`（末尾追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_forecast_pipeline.py` 末尾追加：

```python
def test_quarterly_is_sheet_in_company_excel(tmp_path, monkeypatch):
    company_dir = _copy_new_hope_dairy(tmp_path)
    monkeypatch.delenv(app_config.RESEARCHER_NAME_KEY, raising=False)
    monkeypatch.setattr(app_config, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(yaml1_cleaner, "COMPANIES_DIR", tmp_path / "companies")

    run = run_company_forecast(ticker="002946.SZ")
    manifest = json.loads((forecast_dir(company_dir) / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["company_excel_export_status"] == "written"
    output_path = Path(manifest["company_excel_output_path"])
    workbook = load_workbook(output_path, data_only=False)

    assert "季度利润表" in workbook.sheetnames
    ws = workbook["季度利润表"]
    assert ws["A1"].value == "季度利润表"
    assert ws["A2"].value == "单位：百万元"
    # 表头：A3=科目，第4行季度标签，末列=年度
    assert ws.cell(3, 1).value == "科目"
    assert ws.cell(4, 2).value == "1Q"
    max_col = ws.max_column
    assert ws.cell(3, max_col).value == "年度"
    # 冻结 B6（A 列 + 表头 5 行）
    assert ws.freeze_panes == "B6"
    # 数据行含营业收入 / 净利润（n_income 在 rows 里被 relabel 为"净利润"）
    labels = [ws.cell(r, 1).value for r in range(6, ws.max_row + 1)]
    assert any("营业收入" in (lbl or "") for lbl in labels)
    assert any("净利润" in (lbl or "") for lbl in labels)
    # 选定年 4 列在第 5 行有状态徽章（实/继/人/Q4 之一）
    badges = [ws.cell(5, c).value for c in range(max_col - 4, max_col)]
    assert any(b in {"实", "继", "人", "Q4"} for b in badges)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `py -m pytest tests/test_forecast_pipeline.py::test_quarterly_is_sheet_in_company_excel -v`
Expected: FAIL —— `"季度利润表" in workbook.sheetnames` 断言失败（sheet 尚未生成）。

> 该测试跑完整 `run_company_forecast`（含 DCF），较慢（约 30-60s）。这是现有测试模式（见 `test_run_company_forecast_hides_intermediates_and_rebuilds_forecast`），可接受。

- [ ] **Step 3: 暂不提交**（实现后一起提交）

---

## Task 2: 实现 `_fill_quarterly_is_sheet` 并注册

**Files:**
- Modify: `src/company_excel_export.py`

- [ ] **Step 1: 加常量**

在 `SEMIANNUAL_IS_SHEET = "半年度利润表"`（`:64`）下方加：

```python
QUARTERLY_IS_SHEET = "季度利润表"
QUARTERLY_STATE_BADGE: dict[str, tuple[str, str]] = {
    "actual": ("实", MODEL_GREY),
    "inherit": ("继", MODEL_GREY),
    "manual": ("人", "8B1E2D"),
    "q4": ("Q4", "D6A100"),
}
```

- [ ] **Step 2: 加 `_emphasize_quarterly_row`**

在 `_emphasize_row`（`:727-735`）之后加。关键行加粗：选定年列保留蓝字+浅蓝底，历史年列与年度列改浅灰底黑字，整行加顶 thin/底 medium 边框。

```python
def _emphasize_quarterly_row(
    ws: Any, row: int, periods: list[str], annual_col: int, selected_year: int
) -> None:
    """Bold a key row on the quarterly sheet (3-segment coloring)."""
    border = Border(top=Side(style="thin", color=MODEL_GRID), bottom=Side(style="medium", color=MODEL_GRID))
    ws.cell(row, 1).border = border
    for idx, period in enumerate(periods):
        col = 2 + idx
        forecast = int(period[:4]) == selected_year
        cell = ws.cell(row, col)
        cell.font = Font(name=MODEL_FONT, bold=True, color=MODEL_BLUE_FONT if forecast else "000000", size=9)
        if not forecast:
            cell.fill = PatternFill("solid", fgColor=MODEL_SUBTLE_FILL)
        cell.border = border
    annual_cell = ws.cell(row, annual_col)
    annual_cell.font = Font(name=MODEL_FONT, bold=True, color="000000", size=9)
    annual_cell.fill = PatternFill("solid", fgColor=MODEL_SUBTLE_FILL)
    annual_cell.border = border
```

- [ ] **Step 3: 加 `_ticker_from_db`**

在 `_quarterly_statement_records`（`:1710`）之后加。`compute_quarterly_view` 的 `ticker` 仅用于 `load_overrides`；当 `metrics` 无 ticker 时从 meta 表兜底。

```python
def _ticker_from_db(db_path: Path) -> str:
    """Read ticker from meta table (fallback when metrics omits it)."""
    if not db_path.exists():
        return ""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='ticker'").fetchone()
        return str(row[0]) if row else ""
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
```

- [ ] **Step 4: 加 `_fill_quarterly_is_sheet`**

在 `_fill_semiannual_sheets`（`:1621-1624`）之后加。核心渲染函数：调 `compute_quarterly_view` → 3 行表头（年份分组 / 季度 / 状态徽章）→ 数据行（金额行 + 衍生行，按 `rows` 顺序）→ 年度列。

```python
def _fill_quarterly_is_sheet(workbook: Any, company_dir: Path, metrics: dict[str, Any]) -> None:
    """Quarterly IS tracking sheet — mirrors frontend QuarterlyTable in three-statement style."""
    from .quarterly_tracker import compute_quarterly_view

    db_path = company_db_path(company_dir)
    ticker = metrics.get("ticker") or _ticker_from_db(db_path)
    try:
        view = compute_quarterly_view(db=db_path, ticker=ticker, company_dir=company_dir, year=None)
    except Exception:
        return  # non-blocking: skip sheet if quarterly view unavailable (e.g. no forecast_is.csv)

    periods = view["periods"]              # 12 "YYYYQq"
    rows = view["rows"]                    # amount + metric rows, in field_order
    annual = view["annual"]                # {field: value} (incl. metric fields via annual_out)
    quarter_states = view["quarter_states"]  # {"1":..,"2":..,"3":..,"4":..}
    selected_year = int(view["year"])

    if not periods or not rows:
        return

    annual_col = 1 + len(periods) + 1      # 科目 + 12 季 + 年度
    max_col = annual_col
    ws = _fresh_sheet(workbook, QUARTERLY_IS_SHEET)
    _style_report_sheet(ws, title=QUARTERLY_IS_SHEET, subtitle="单位：百万元", max_col=max_col)
    ws.freeze_panes = "B6"                 # override _style_report_sheet's B4 (header is 5 rows)

    # --- 3-row header ---
    ws.merge_cells(start_row=3, start_column=1, end_row=5, end_column=1)
    _header_style(ws.cell(3, 1, "科目"))
    for group_idx, year in enumerate([selected_year - 2, selected_year - 1, selected_year]):
        start = 2 + group_idx * 4
        end = start + 3
        ws.merge_cells(start_row=3, start_column=start, end_row=3, end_column=end)
        label = f"{year}(选定)" if year == selected_year else str(year)
        _header_style(ws.cell(3, start, label))
    for idx, period in enumerate(periods):
        _header_style(ws.cell(4, 2 + idx, f"{int(period[-1])}Q"))
    ws.merge_cells(start_row=3, start_column=annual_col, end_row=5, end_column=annual_col)
    _header_style(ws.cell(3, annual_col, "年度"))
    # state badge row (row 5, selected-year 4 cols only)
    for idx, period in enumerate(periods):
        if int(period[:4]) != selected_year:
            continue
        q = int(period[-1])
        state = quarter_states.get(str(q), "inherit")
        badge, color = QUARTERLY_STATE_BADGE.get(state, ("", MODEL_GREY))
        cell = ws.cell(5, 2 + idx, badge)
        cell.font = Font(name=MODEL_FONT, color=color, size=9)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = PatternFill("solid", fgColor=MODEL_FORECAST_FILL)
    ws.row_dimensions[3].height = 20
    ws.row_dimensions[4].height = 18
    ws.row_dimensions[5].height = 16

    # --- data rows from row 6 ---
    row_index = 6
    for row in rows:
        role = row.get("role")
        fmt = row.get("format", "number")
        is_metric = role == "metric"
        is_key = role == "total" or bool(row.get("highlight"))
        _label_style(ws.cell(row_index, 1, row.get("label", "")), muted=is_metric, bold=is_key)
        for idx, period in enumerate(periods):
            col = 2 + idx
            forecast = int(period[:4]) == selected_year
            value = row.get("values", {}).get(period)
            _data_style(ws.cell(row_index, col, value), forecast=forecast, number_format=_number_format(fmt))
        annual_value = annual.get(row.get("field"))
        annual_cell = ws.cell(row_index, annual_col, annual_value)
        _data_style(annual_cell, forecast=False, number_format=_number_format(fmt))
        annual_cell.fill = PatternFill("solid", fgColor=MODEL_SUBTLE_FILL)
        if is_key:
            _emphasize_quarterly_row(ws, row_index, periods, annual_col, selected_year)
        row_index += 1

    _auto_widths(ws, max_col)
    for col in range(2, max_col + 1):
        ws.column_dimensions[get_column_letter(col)].width = 11
```

- [ ] **Step 5: 注册到 `export_company_excel`**

在 `export_company_excel`（`:2431`）的 `_fill_full_statement_sheets(workbook, company_path, metrics)` 之后、`_fill_semiannual_sheets(...)` 之前加一行：

```python
    _fill_full_statement_sheets(workbook, company_path, metrics)
    _fill_quarterly_is_sheet(workbook, company_path, metrics)   # ← 新增
    _fill_semiannual_sheets(workbook, company_path, metrics)
```

- [ ] **Step 6: 语法检查**

Run: `py -m py_compile src/company_excel_export.py`
Expected: 无输出（编译通过）。

- [ ] **Step 7: 跑 Task 1 测试确认通过**

Run: `py -m pytest tests/test_forecast_pipeline.py::test_quarterly_is_sheet_in_company_excel -v`
Expected: PASS。

- [ ] **Step 8: 提交**

```bash
git add src/company_excel_export.py tests/test_forecast_pipeline.py
git commit -m "feat(excel): add 季度利润表 sheet mirroring frontend QuarterlyTable

Reuses compute_quarterly_view (same source as frontend API) and the
three-statement style helpers. Cells use two-tone year coloring
(historical white / selected-year forecast blue); 4-state info
(actual/inherit/manual/q4) is concentrated in a badge row above the
selected year. Scope: IS-only, 3y/12q + annual column.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 更新现有测试断言（sheet 数 8 → 9）

**Files:**
- Modify: `tests/test_forecast_pipeline.py`

新增 sheet 后，`test_run_company_forecast_hides_intermediates_and_rebuilds_forecast` 的两个断言会变红，需同步。

- [ ] **Step 1: 更新断言**

`tests/test_forecast_pipeline.py:95`：
```python
    assert len(workbook.worksheets) == 8
```
改为：
```python
    assert len(workbook.worksheets) == 9
```

`tests/test_forecast_pipeline.py:98-100`：
```python
    assert {"核心假设", "完整利润表", "完整资产负债表", "完整现金流量表", "半年度利润表"}.issubset(
        set(workbook.sheetnames)
    )
```
改为：
```python
    assert {"核心假设", "完整利润表", "完整资产负债表", "完整现金流量表", "季度利润表", "半年度利润表"}.issubset(
        set(workbook.sheetnames)
    )
```

- [ ] **Step 2: 跑完整测试确认通过**

Run: `py -m pytest tests/test_forecast_pipeline.py -v`
Expected: 两个测试均 PASS。

- [ ] **Step 3: 提交**

```bash
git add tests/test_forecast_pipeline.py
git commit -m "test(excel): update workbook sheet count to 9 with 季度利润表

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 同步文档

**Files:**
- Modify: `docs/数据流水线.md`、`docs/CHANGELOG.md`

- [ ] **Step 1: 更新 `docs/数据流水线.md`**

在 Excel 输出（`export_company_excel`）相关段落，把 sheet 清单补上 `季度利润表`，注明：数据源 `compute_quarterly_view`（与前端同源），风格对齐三表，IS-only / 3y12q + 年度列 + 状态徽章行。具体措辞跟该文件现有 Excel 输出描述风格走。

- [ ] **Step 2: 更新 `docs/CHANGELOG.md`**

在文件首（最新日期条目）追加一行：
```
- 2026-06-26: Excel 输出新增"季度利润表"sheet（对齐前端 QuarterlyTable，compute_quarterly_view 同源，三表风格 + 状态徽章行，IS-only/3y12q）
```

- [ ] **Step 3: 提交**

```bash
git add docs/数据流水线.md docs/CHANGELOG.md
git commit -m "docs: record 季度利润表 Excel sheet in pipeline + changelog

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 风险与注意事项

- **`_style_report_sheet` 冻结写死 `B4`**：季度页表头占 5 行，调用后必须 `ws.freeze_panes = "B6"` 覆盖（同半年度页 `:1588` 的 `B5` 覆盖模式）。
- **`compute_quarterly_view` 依赖 `forecast_is.csv`**：缺失时 `raise ValueError`（`quarterly_tracker.py:622`），用 `try/except` 包裹跳过 sheet，不阻断导出。
- **ticker 来源**：`metrics.get("ticker")` 优先，缺失时 `_ticker_from_db` 从 meta 表读；ticker 仅用于 `load_overrides`，无 override 的公司不受影响。
- **`quarter_states` key 是字符串** `"1".."4"`（`quarterly_tracker.py:908`），访问用 `quarter_states.get(str(q))`。
- **`n_income` 在 rows 里被 relabel 为"净利润"**（`quarterly_tracker.py:827`）；关键行加粗用 `role == "total"` 或 `highlight` flag 判定，不硬编码字段名。
- **`_emphasize_row` 不能直接复用**：其 `forecast_start_col` 假设预测列在右侧连续，季度页"选定年"在中间 4 列、年度列在最右，故新写 `_emphasize_quarterly_row` 做三段着色。
- **测试较慢**：`test_quarterly_is_sheet_in_company_excel` 跑完整 `run_company_forecast`（含 DCF），约 30-60s，与现有测试模式一致。
