# 季度利润表 Excel 输出页 — 设计

- 日期：2026-06-26
- 状态：已确认，待实现
- 相关模块：`src/company_excel_export.py`、`src/quarterly_tracker.py`

## 背景与动机

`/comp` 的 Excel 输出（`export_company_excel`）现有三个年度 sheet：`完整利润表` / `完整资产负债表` / `完整现金流量表`。前端工作台有"季度展示" tab（`App.tsx:QuarterlyTable`），只展示**季度利润表追踪**——12 个季度列（选定年 + 前 2 年）+ 1 个年度列，行内夹衍生行（同比/毛利率/费用率/净利率），核心是 4 态状态机（actual / inherit / manual / q4）。当前 Excel 缺季度视角。

目标：把前端季度展示用三表一致的视觉风格输出到 Excel，新增 `季度利润表` sheet。

## 目标 / 非目标

**目标**
- 新增 `季度利润表` sheet，内容对齐前端 `QuarterlyTable`
- 风格（标题栏 / 字体 / 数字格式 / 关键行加粗 / 衍生行 / 冻结窗格）与三表一致
- 数据与前端同源（`compute_quarterly_view`），口径零漂移

**非目标**
- 不做 BS / CF 季度页（v1 仅利润表）
- 不做可编辑（Excel 是静态输出，override 值已烘进数据）
- 不改前端、不改 `compute_quarterly_view`、不改 `clean_quarterly`

## 已确认决策

1. **范围**：仅利润表（对齐前端）。BS 季度明细披露稀疏、CF 季度需累计拆分，v1 不碰。
2. **状态呈现**：三表风格 + 状态徽章行。单元格只用三表两色（历史年白底 / 选定年浅蓝底），4 态信息集中在选定年上方一行徽章（实/继/人/Q4）。
3. **时间范围**：3 年 / 12 季（选定年 + 前 2 年）+ 末尾年度列，对齐前端。

## 设计

### 数据流

新增 `_fill_quarterly_is_sheet(workbook, company_dir, metrics)`：

- `db = company_dir / "Agent" / "data.db"`；`ticker` 从 `metrics` 或目录名取
- 调 `compute_quarterly_view(db=db, ticker=ticker, company_dir=company_dir, year=None)`
  - keyword-only 参数；`year=None` 时默认取 `forecast_is.csv` 最小年（`quarterly_tracker.py:624`），与前端默认一致
  - 返回 `{periods, rows, annual, quarter_states, period_states}`
- `rows` 已含金额科目 + 衍生行（`role="metric"`、`format="percent"`），直接按序渲染，不重算
- 不读 `clean_quarterly`，不依赖 `metrics["quarterly"]`（后者是 `metrics_by_period` 形状，不适合本 sheet）

### Sheet 结构

- **标题栏 A1**：`季度利润表`，深蓝底白字 13pt（复用 `_style_report_sheet`）
- **副标题 A2**：`单位：百万元`，灰字斜体 9pt
- **表头 3 行**（参考半年度页 `_write_multilevel_period_header` 多级表头）：
  - 第 3 行：年份分组——`2023`(跨 4 列) `2024`(跨 4 列) `2025(选定)`(跨 4 列，浅蓝底) `年度`(1 列)
  - 第 4 行：季度——`1Q 2Q 3Q 4Q` × 3 + `年度`
  - 第 5 行：状态徽章——仅选定年 4 列标 `实/继/人/Q4`，其余列空
- **数据行**（第 6 行起，行序 = `rows`）：
  - 金额行 → `_data_style`，数字格式 `#,##0.0;[Red](#,##0.0);"-"`
  - 衍生行(percent) → `_number_format("percent")`，斜体灰字（同三表 `INCOME_DERIVED_ROWS` 衍生行风格）
  - 关键行加粗：优先用 row 自带的 `highlight` flag 与 `role == "total"` 判定（`n_income` 在 rows 里被 relabel 为"净利润"，`operate_profit`/`total_profit` 是 `role="total"` 行），调 `_emphasize_row` 加粗 + 浅灰底；不硬编码字段名，避免漏掉 relabel 行
  - 着色：历史年 8 季白底；选定年 4 季浅蓝底（`MODEL_FORECAST_FILL`）；年度列浅灰底加粗
- **冻结窗格**：`B6`（冻结 A 列 + 表头 5 行）
- **列宽**：A 列 ≥ 34，其余 11（12 季度 + 年度列较多，略窄于三表的 12）

### 状态徽章

从 `quarter_states`（当年 4 季状态，key 为字符串 `"1".."4"`，访问用 `quarter_states[str(q)]`）取，在选定年 4 列的第 5 行写单字徽章：

| state | 字 | 字色 |
|---|---|---|
| actual | 实 | 灰 `#666666` |
| inherit | 继 | 灰 `#666666` |
| manual | 人 | 红 `#8b1e2d` |
| q4 | Q4 | 金 `#d6a100` |

9pt 居中。单元格本身仍按年份两色（白/浅蓝），徽章只标状态、不改单元格底色。

### 集成点

`export_company_excel`（`company_excel_export.py:2431`）在 `_fill_full_statement_sheets(...)` 之后加一行：

```python
_fill_quarterly_is_sheet(workbook, company_path, metrics)
```

落在三表之后、`_fill_semiannual_sheets` 之前（年度利润表 → 季度利润表 → 半年度利润表，视角递进）。

### 边界 / 错误处理

- `compute_quarterly_view` 抛错（如 `forecast_is.csv` 缺失，`quarterly_tracker.py:622` raise `ValueError`）→ 用 try/except 包裹跳过该 sheet，不阻断导出（Excel 导出本就非阻塞；三表用 early-return guard，本 sheet 因调用外部函数改用 try/except）
- null 单元格留空；0.0 按格式显示 `-`
- 行级全零不跳过（要对齐前端行结构）；整表无数据则不建 sheet

## 复用的现成资产

- **样式函数**：`_style_report_sheet` / `_data_style` / `_label_style` / `_emphasize_row` / `_number_format` / `_write_multilevel_period_header`
- **样式常量**：`MODEL_FORECAST_FILL` / `MODEL_GREY` / `MODEL_FONT` 等（`company_excel_export.py:46-58`）
- **数据源**：`compute_quarterly_view`（`quarterly_tracker.py:609`）
- **字段/排序**：`rows` 已携带 label，无需再查 `field_registry`

## 测试

用 `tests/fixtures/company_002946` 夹具跑 `export_company_excel`，断言：

- `季度利润表` sheet 存在
- 表头年份分组 / 季度 / 状态徽章正确（选定年 4 列徽章与 `quarter_states` 一致）
- `rows` 顺序正确，关键行 `revenue/operate_profit/total_profit/n_income` 加粗
- 年度列值 = `annual[field]`
- 选定年 4 列浅蓝底，历史年 8 季白底
- 肉眼对比 `完整利润表` 与 `季度利润表`：标题栏 / 字体 / 数字格式 / 衍生行风格一致

## 风险

- `compute_quarterly_view` 依赖 `forecast_is.csv`；缺失时静默跳过 sheet（不阻断导出，但该 sheet 不生成）
- 表头占 5 行（三表是 3 行），冻结点 `B6`；需确认多级表头 + 徽章行视觉整洁，不拥挤
- 选定年的"浅蓝底"沿用三表预测色 `MODEL_FORECAST_FILL`，但选定年季度可能含 actual（已披露实际值）——按已确认决策，着色按年份不按状态，actual 也落浅蓝底；状态由徽章区分
