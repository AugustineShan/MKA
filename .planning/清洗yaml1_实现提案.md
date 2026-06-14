# 清洗yaml1.py 实现提案

> 本文是只读现状后的实现提案。未写实现代码，未改 `src/calc.py`，未 commit。
>
> 依据：`docs/清洗yaml1_设计文档_v1.md`、`src/calc.py`、`src/yaml2_schema.py`、`src/defaults_gen.py`、`src/clean.py`、新乳业 `yaml1_002946 (3).yaml` / `defaults.yaml` / `clean_annual_002946.csv`。

---

## 0. 现状核对

### 0.1 calc.py 取参点

设计文档 §3.3 的取参点与当前代码方向一致，但行号已有漂移，且我额外发现了两个严格逐年化时必须处理的取参点。

| 位置 | 当前代码 | 逐年化影响 |
|---|---|---|
| `src/calc.py:75` `value_map()` | 把 mapping 叶子统一 `as_float()` 成标量 dict | 改成按年取值的 mapping helper |
| `src/calc.py:95-113` `financial_expense_from_balances()` | 利率、其他财务费用读标量 | 若 resolve 广播所有循环内消费参数，这里也要按 `idx` 取 |
| `src/calc.py:126-136` `build_income_statement()` | `gpm/tax/minority` 与各 income map 读标量 | 加 `idx`，所有 income 参数按 `idx-1` 取数组 |
| `src/calc.py:198-213` `build_balance_sheet()` | `revenue_pct/cogs_days/capex_pct/depr_rate/dividend_payout` 读标量 | 加 `idx`，BS 驱动按年取数组 |
| `src/calc.py:269-312` `solve_forecast_year()` | 调用 IS/BS/finance 时无年份索引 | 仅传递 `idx`，循环求解链不改 |
| `src/calc.py:324-326` `build_cash_flow()` | 三个摊销参数读标量 | 若这些叶子被广播，也要加 `idx` |
| `src/calc.py:369-408` `run_forecast()` | `revenue_yoy/tax_rate` 循环外读标量 | `revenue_yoy` 和 DCF NOPAT 税率在循环内按年读 |

跨年状态滚动链实际形态如下，提案要求这些行保持代数含义不动：

- `run_forecast()` 主循环 `for idx in range(1, years + 1)`，见 `src/calc.py:390`
- `revenue` 每年滚存，见 `src/calc.py:392`
- `solve_forecast_year(yaml2, period, prev_bs, revenue, review_flags)` 依赖 `prev_bs`，见 `src/calc.py:393-399`
- `solve_forecast_year()` 内部财务费用循环：`IS -> BS plug -> average cash/debt -> financial_expense`，见 `src/calc.py:298-312`
- `build_cash_flow()` 依赖 `prev_bs/prev_nwc/metrics`，见 `src/calc.py:316-352`
- `validate_accounting()` BS/CF hard check，见 `src/calc.py:355-366`
- 年末状态滚动 `prev_bs = bs_row`、`prev_nwc = metrics["nwc"]`，见 `src/calc.py:434-435`

结论：`calc.py` 逐年化应该只改“取参口”和参数传递，不改预测引擎的状态机。

### 0.2 yaml2_schema.py 行为

- `plain_value(item)`：若 dict 含 `value`，返回 `item["value"]`；否则原样返回。见 `src/yaml2_schema.py:59-62`。
- `get_path(data, path, default=None)`：按点路径下钻，最终返回 `plain_value(cur)`；中间缺失返回 default。见 `src/yaml2_schema.py:65-71`。
- `read_yaml2(path)`：读 YAML/JSON 后调用 `validate_yaml2()`。见 `src/yaml2_schema.py:96-108`。
- `validate_yaml2()` 只检查必填路径、版本、`wacc > terminal_growth`、`forecast_years > 0`。它不关心叶子是标量还是 list，所以 `yaml2_yearly` 可以继续复用现有读写函数，但需要清洗层自己补一个“逐年叶子等长”校验。

### 0.3 新乳 yaml1 / yaml2 实际结构

新乳公司目录内的权威样例是 `companies/新乳业_002946/yaml1_002946 (3).yaml`。

- yaml1 顶层是稀疏点路径：`income.revenue`、`income.gpm`、`income.cost_rates.sell_exp` 等，不是 yaml2 嵌套树。
- `income.revenue.kind = decomposition`，四条线：低温鲜奶、低温酸奶、常温、边缘业务。
- knob 已按 `meta.horizon = [2025..2031]` 摊成满数组。
- `terminal.fade.to_year = 2036`，显式 7 年 + fade 5 年。
- `terminal.fade.fade_paths` 在公司目录样例里是 `[revenue]`；根目录另一个 yaml1 草稿是 `[income.revenue]`。需要 alias 归一。
- `stash` 是 B 类收纳区，包含分线历史收入/销量/吨价、分线毛利率、地区拆分等。

新乳 `defaults.yaml` 已按测试口径锚在 2024：

- `base_period: '2024'`
- `income.revenue.value: 10665.42345785`
- `model.forecast_years.value: 8`

### 0.4 clean_annual 事实锚

新乳 `clean_annual_002946.csv` 当前是 as-of 2024 的测试口径。关键值：

- 2024 revenue = `10665.42345785`
- yaml1 四线 base 按 `万吨 * 元/吨 / 100` 算出的 2024 加总 = `10665.56888`
- 四线 base 与 2024 clean revenue 差异约 `0.1454` 百万元，在当前 clean 容差 1 百万元内

yaml1 折叠出的显式预测收入序列为：

| 年份 | 折叠收入 | 用上一年倒推 yoy |
|---|---:|---:|
| 2025 | 10856.4643 | 1.7912% |
| 2026 | 11011.6432 | 1.4294% |
| 2027 | 11216.0967 | 1.8567% |
| 2028 | 11460.3525 | 2.1777% |
| 2029 | 11736.7649 | 2.4119% |
| 2030 | 12039.5595 | 2.5799% |
| 2031 | 12327.9652 | 2.3955% |

这说明 yaml1 是“从 2024 出发的预测口径”，当前 defaults 基线与它已经对齐。

### 0.5 resolve_is_signs 可复用接口

`clean.resolve_is_signs(row, present, year, tolerance=TOLERANCE)` 返回 `(sign_map, warnings)`，见 `src/clean.py:1068-1156`。

- 2019 年前返回 warning，跳过动态符号验证。
- 2019+ 对 `assets_impair_loss`、`credit_impa_loss`、`oth_impair_loss_assets` 穷举符号，使 `operate_profit` 恒等式闭合。
- 不塞 plug；不可判或歧义只返回 warning。

回测层可以直接复用这个函数，对 clean_annual 每个历史 row 生成符号 map，确保 yaml1 中资产减值等符号与当前 clean 口径一致。

---

## A. 模块拆分提案

我建议概念名仍叫“清洗yaml1.py”，但实现文件用仓库既有英文模块风格：

- 新增 `src/yaml1_cleaner.py`：主实现与 CLI，入口 `python -m src.yaml1_cleaner --yaml1 ... --defaults ... --db ...`
- 新增 `tests/test_yaml1_cleaner.py`：fold / expand / resolve / backtest 的纯函数单测
- 不新增中文 Python 文件名，避免 Windows 编码、import、CI 路径问题
- 输出默认写到公司目录：
  - `yaml2_yearly.yaml`：给逐年化后的 `calc.py` 消费
  - `yaml1_clean_report.json`：清洗、回测、fade、resolve 的审计报告
  - `stash.json` 或 `yaml1_stash.yaml`：可选，前端旁路读；也可以只在 report 中记录 stash 原路径

### 1. 输入与装载层

职责：定位并读取 yaml1、yaml2、clean_annual。

建议函数：

- `load_yaml1(path) -> dict`
- `load_yaml2_baseline(path) -> dict`，内部复用 `read_yaml2`
- `load_clean_annual(db_path or csv_path) -> DataFrame`
- `infer_company_paths(ticker)`：按 `companies/*_{code}` 定位
- `detect_base_year(yaml1, clean_annual) -> int`

`detect_base_year` 不能直接相信 `defaults.yaml.base_period`。应优先取：

1. `income.revenue.segments.*.base.base_year` 的一致值；
2. 若缺失，则取 `min(meta.horizon) - 1`；
3. 与 clean_annual 是否存在该 period 做 hard check。

### 2. fold：非标 revenue decomposition 折叠

职责：只把非标收入树消费成标准 `model.revenue_yoy`，不把 decomposition 传给 calc。

建议函数：

- `fold_revenue_decomposition(node, horizon, clean_annual, unit_policy) -> FoldResult`
- `fold_segment(segment, horizon, unit_policy) -> list[float]`
- `derive_revenue_yoy(revenue_series, base_revenue) -> list[float]`

当前支持：

- `revenue_family: vol_price`
- `revenue_family: growth`
- `rollup: sum`

预留：

- `kind: formula` 分支只举旗：`formula evaluator not implemented`
- decomposition 深度限制先按设计文档 ≤2；超过即 hard fail

`FoldResult` 至少包含：

- `revenue_by_year`
- `revenue_yoy`
- `segment_revenue_by_year`
- `source_paths`
- `warnings`

### 3. expand：knob 与 terminal fade 展开

职责：把显式 7 年数组扩展为完整 horizon 12 年数组。

建议函数：

- `collect_knob_overrides(yaml1, explicit_horizon) -> dict[path, list]`
- `expand_terminal_tail(overrides, terminal, explicit_horizon) -> ExpandedOverlay`
- `normalize_fade_path(path) -> canonical_path`

核心策略：

- 所有 `kind: knob` 的 `values` 必须长度等于显式 horizon
- `income.revenue` decomposition 不输出 `income.revenue` 覆盖，而输出 `model.revenue_yoy`
- `terminal.fade_paths` 中的 `revenue` / `income.revenue` 都归一到 `model.revenue_yoy`
- `hold_paths` 使用显式期末值填充 fade 期
- 未声明项默认 hold 在显式期末值
- `model.forecast_years = len(full_horizon)`
- `meta.horizon = [2025..2036]`

### 4. resolve：yaml1 overlay ⊕ yaml2 baseline

职责：把稀疏点路径 overlay 合并进 yaml2 嵌套树。

建议函数：

- `build_yearly_overlay(fold_result, expanded_knobs) -> dict[path, list]`
- `merge_overlay(baseline, overlay, yearly_paths, horizon_len) -> dict`
- `set_path(tree, path, value)`
- `validate_overlay_paths(overlay, baseline)`
- `validate_yaml2_yearly(yaml2_yearly, yearly_paths, horizon_len)`

重点：yaml1 overlay 只负责覆盖显式假设，缺席路径使用 2024 baseline 的 yaml2 平推值。

### 5. backtest：历史闸

职责：证明 fold/resolve 没把 yaml1 翻错。

建议函数：

- `backtest_segment_base(yaml1, clean_annual) -> list[Finding]`
- `backtest_historical_revenue_stash(yaml1, clean_annual) -> list[Finding]`
- `backtest_income_signs(clean_annual) -> list[Finding]`
- `run_backtests(...) -> BacktestReport`

硬闸：

- 2024 四线 base 加总 ≈ clean_annual 2024 revenue
- 每条 vol_price segment 的 base 计算值 ≈ stash 中对应 2024 收入
- edge base revenue ≈ stash 边缘业务 2024 收入
- `resolve_is_signs` 2019+ 不得出现 hard inconsistency；2019 前 warning 不阻断

历史多年分线回测：

- 使用 stash 的 `分线历史_收入销量吨价.*.收入` 加总与 clean_annual revenue 对齐
- 对常温 2018-2019 缺失这类已声明空洞，不能硬凑；应输出 `skipped_due_to_declared_gap`
- 对所有四线完整年份做 hard check

### 6. calc.py 逐年化

职责：只让 calc 从“标量取参”变成“逐年取参”，不改变状态滚动链。

建议函数/改造见 B。

---

## B. calc.py 逐年化的最小改法

### 总原则

`calc.py` 内部不理解 yaml1，不折叠、不 fade、不 resolve。它只消费已经清洗好的 `yaml2_yearly`。

我建议把 calc 消费的参数分成三类：

1. 基准状态：标量或 mapping 标量，仅在循环前读取。包括 `base_period`、`income.revenue`、`balance_sheet.base`、`cashflow.base_nwc`。
2. 年度驱动：长度 = forecast_years 的数组，每年按 `idx-1` 读取。包括 `model.revenue_yoy`、income 参数、BS driver、CF 摊销参数、financial_expense 数值参数。
3. 估值/身份常量：标量。包括 `ticker/name`、`market.*`、`model.wacc`、`model.terminal_growth`、`model.plug`、`income.financial_expense.interest_mode`。

这样 `calc.py` 不需要在同一个取参点判断“标量还是数组”。它只在该取数组的地方取数组，该取标量的地方取标量。

### 建议新增小 helper

在 `src/calc.py:75` 附近替换/扩展 `value_map()`：

- `year_value(value, idx, path)`：要求 `value` 是 list，返回 `plain_value(value[idx - 1])`；长度不足直接 `CalcError`
- `get_year_float(yaml2, path, idx, default=0.0)`：`get_path()` 后用 `year_value()`
- `value_map_at(section, idx, section_path)`：section 是 `{field: list/value-record-list}`，返回 `{field: float}`

这不是业务逻辑，只是取参口。

### 逐点改法草图

1. `build_income_statement()`，见 `src/calc.py:126`

当前签名：

- `build_income_statement(yaml2, revenue, financial_expense)`

改为：

- `build_income_statement(yaml2, revenue, financial_expense, idx)`

内部：

- `gpm` 从 `income.gpm[idx-1]` 取
- `tax_rate` 从 `income.effective_tax_rate[idx-1]` 取
- `minority_ratio` 从 `income.minority_ratio[idx-1]` 取
- `revenue_items_abs/cost_rates/cost_abs/operating_adjustments_abs/below_line_abs` 用 `value_map_at(..., idx)`

不改行 `row["oper_cost"] = revenue * (1.0 - gpm)`，不改后续利润表公式。

2. `financial_expense_from_balances()`，见 `src/calc.py:95`

当前签名：

- `financial_expense_from_balances(yaml2, prev_bs, bs_row)`

改为：

- `financial_expense_from_balances(yaml2, prev_bs, bs_row, idx)`

内部：

- `interest_mode` 仍标量
- `base_fin_exp/base_interest_expense/base_interest_income/interest_expense_rate/cash_interest_rate/other_fin_exp_abs` 若作为年度驱动数组，则按 `idx` 取

理由：这些参数虽然 yaml1 当前不覆盖，但它们在预测循环内被消费。广播成数组后，未来也能支持分析师逐年调融资利率，而无需再动 calc。

3. `build_balance_sheet()`，见 `src/calc.py:198`

当前签名：

- `build_balance_sheet(yaml2, prev_bs, income_row, review_flags=None)`

改为：

- `build_balance_sheet(yaml2, prev_bs, income_row, idx, review_flags=None)`

内部：

- `revenue_pct`、`cogs_days` 用 `value_map_at`
- `capex_pct`、`depr_rate`、`dividend_payout` 用 `get_year_float`
- `plug` 仍标量

不改 plug 配平逻辑，不改 `recompute_bs_totals()`。

4. `solve_forecast_year()`，见 `src/calc.py:269`

当前签名：

- `solve_forecast_year(yaml2, period, prev_bs, revenue, review_flags)`

改为：

- `solve_forecast_year(yaml2, period, prev_bs, revenue, review_flags, idx)`

内部只做参数传递：

- 两次 `build_income_statement(...)` 都传 `idx`
- 两次 `build_balance_sheet(...)` 都传 `idx`
- `financial_expense_from_balances(...)` 传 `idx`

循环收敛逻辑不动。

5. `build_cash_flow()`，见 `src/calc.py:316`

当前签名：

- `build_cash_flow(yaml2, prev_bs, bs_row, income_row, metrics, prev_nwc)`

改为：

- `build_cash_flow(yaml2, prev_bs, bs_row, income_row, metrics, prev_nwc, idx)`

内部：

- `balance_sheet.amort_intang_assets`
- `balance_sheet.lt_amort_deferred_exp`
- `balance_sheet.use_right_asset_dep`

这三项若按年度驱动广播，则按 `idx` 取。

6. `run_forecast()`，见 `src/calc.py:369`

循环外保留：

- `base_period`
- `years`
- `wacc`
- `terminal_growth`
- `net_debt`
- `total_shares`
- `prev_bs`
- `prev_nwc`
- `revenue` 初始值

循环内改：

- `revenue_yoy_i = model.revenue_yoy[idx-1]`
- `revenue *= 1.0 + revenue_yoy_i`
- `tax_rate_i = income.effective_tax_rate[idx-1]`，用于 `nopat`
- `solve_forecast_year(..., idx)`
- `build_cash_flow(..., idx)`

不改：

- `prev_bs = bs_row`
- `prev_nwc = metrics["nwc"]`
- FCFF 公式
- terminal value 公式
- summary 输出结构

### 回归证明方式

逐年化改完后，用一个测试 helper 把现有 5 家 defaults.yaml 的年度驱动标量广播成数组，喂给新 calc。

验收：

- 广播后的结果与当前 calc 对同一 defaults 的输出数值一致，误差只允许浮点级
- 这证明改动只改变取参形态，没有改变引擎状态链

---

## C. yaml2_yearly 数据结构

### 总体结构

保持 yaml2 嵌套同构，不做扁平表。示意：

- `version`: 2
- `ticker/name/generated_at/unit`: 标量
- `base_period`: 标量，必须是 yaml1 forecast 首年前一年；新乳应为 `2024`
- `meta.horizon`: 完整预测年数组；新乳应为 `[2025..2036]`
- `model.forecast_years`: 标量；新乳应为 `12`
- `model.revenue_yoy`: 数组，长度 12
- `income.*`: calc 循环内消费的叶子为数组
- `balance_sheet.base`: 基准状态 mapping，叶子仍为标量
- `balance_sheet.revenue_pct/cogs_days/capex_pct/depr_rate/...`: 数组
- `cashflow.base_nwc`: 基准状态标量
- `market.*`: 标量
- `review_flags`: 原样 list

### 未逐年化叶子的处理

我不建议“所有叶子无脑广播”，也不建议“yaml1 没碰就标量透传”。这两头都会制造问题：

- 全量广播会把 `ticker/name/source/note/market/base` 这类非年度输入弄复杂。
- yaml1 没碰就标量透传，会让 calc 的循环内取参点不得不判断标量/list，违背“进料口永远确定”的原则。

建议规则：

1. 凡是 calc 循环内每年消费的数值参数，全部数组化；即使来自 yaml2 平推，也广播成长度 = forecast_years 的数组。
2. 凡是 calc 循环前只消费一次的基准状态，保持标量或标量 mapping。
3. 凡是身份/估值常量，保持标量。
4. 非数值配置如 `model.plug`、`income.financial_expense.interest_mode` 保持标量。

这条规则比设计文档里“未被触及的叶子原样透传”和“标量来自 yaml2 就广播”两句话更精确，也更贴合真实 `calc.py`。

### 新乳关键输出预期

新乳 `yaml2_yearly` 应保持 2024 baseline，并把预测参数展开到完整 horizon：

- `base_period: '2024'`
- `income.revenue: 10665.42345785`
- `balance_sheet.base`: 2024 baseline
- `cashflow.base_nwc`: 2024 baseline 推导
- `model.forecast_years: 12`
- `model.revenue_yoy`: 7 年折叠 yoy + 5 年 fade yoy
- `income.gpm`: 7 年 knob + 5 年 hold
- `income.effective_tax_rate`: 7 年 knob + 5 年 hold
- `income.minority_ratio`: 7 年 knob + 5 年 hold
---

## D. fade 展开方案

### horizon 扩展

输入：

- explicit horizon: `[2025..2031]`
- `terminal.explicit_end = 2031`
- `terminal.fade.to_year = 2036`

输出：

- full horizon: `[2025..2036]`
- fade years: `[2032, 2033, 2034, 2035, 2036]`
- `model.forecast_years = 12`

硬校验：

- `explicit_end == explicit_horizon[-1]`
- `to_year > explicit_end`
- `full_horizon` 必须连续

### fade_paths

规范化路径：

- `revenue` -> `model.revenue_yoy`
- `income.revenue` -> `model.revenue_yoy`
- `model.revenue_yoy` -> `model.revenue_yoy`

线性插值：

- 起点：显式期末值，即 2031 revenue_yoy
- 终点：`terminal.perpetual_growth`
- 步数：`to_year - explicit_end`
- 新乳 2031 yoy 约 `0.0239548358`，终点 `0.025`
- 2032-2036 追加值约为 `[0.0241638686, 0.0243729015, 0.0245819343, 0.0247909672, 0.025]`

### hold_paths

对 `hold_paths` 中路径，fade 期全部填显式期末值。

新乳：

- `income.gpm` 2031 是 `0.305`
- 2032-2036 全部填 `0.305`

### 未声明项默认 hold

已按你的要求拍板：未出现在 `fade_paths` 或 `hold_paths` 的逐年路径，默认 hold 在显式期末值。

这包括：

- 费用率
- 税率
- 少数股东率
- 资产减值常态值
- below-line 绝对值
- yaml2 fallback 广播出的 BS driver 等

实现上，先把所有显式数组扩成完整数组：

1. 如果路径在 fade set：线性插值。
2. 否则：尾部复制最后一个显式值。

### 引用校验

`fade_paths/hold_paths` 引用必须能落到清洗后的标准路径。

- `revenue` alias 可以接受。
- `income.revenue` alias 可以接受。
- 其他未知路径 hard fail。

这样能兼容当前两个 yaml1 草稿的不一致，同时推动 compiler 以后输出 canonical path。

---

## E. 回测闸方案

### E1. 历史收入轨

目标：证明 yaml1 的收入 fold 口径与历史事实一致。

分三层：

1. Segment base check

- 对每个 `vol_price` leaf，用 `base.volume * base.price / unit_factor` 算 2024 收入。
- 与 stash 中对应业务线 2024 收入比较。
- 对 `growth` leaf，`base.revenue` 与 stash 2024 收入比较。

2. 2024 clean anchor check

- 四线 base 加总与 `clean_annual.revenue[2024]` 比较。
- 新乳当前差异约 `0.1454` 百万元，应通过 1 百万元容差。

3. 多年历史 headline check

- 从 stash 的 `分线历史_收入销量吨价` 取每年各线收入。
- 只对四线均有值的年份 hard check。
- 已声明缺口如常温 2018-2019：记录 skipped，不 hard fail。
- 加总与 clean_annual 同年 revenue 比较。

失败动作：

- 报 path、year、expected、actual、residual、tolerance。
- 不 plug、不调用 LLM、不猜单位。

### E2. 单位系数闸

新乳 `yaml1_002946 (3).yaml` 的结构化字段里没有 `unit_factor_to_million_cny`，只有注释和 stash caveat 写了“÷100”。根目录 `yaml1_002946 (2).yaml` 的 note 写得更明确。

我建议实现时支持两层：

1. 优先读取结构化字段，例如 segment 或 revenue node 上的 `unit_factor_to_million_cny: 100`。
2. 临时兼容当前样例：从 `income.revenue.note` 或 stash caveats 中用严格 regex 提取 `÷100` / `/100`。

如果提取不到，hard fail。不要默认 `/100`。

更优做法是让 compiler 以后输出结构化单位系数字段，见 §F。

### E3. 符号轨

复用 `clean.resolve_is_signs()`：

- 读取 clean_annual row 为 dict。
- `present` 用非空/非零字段集合；或者如果后续需要更严谨，可复用 `clean.py` 的 raw pivot 过程拿原始 present_by_period。
- 对 2019+，若 `resolve_is_signs()` 返回 sign_map，则记录到 report。
- 对 2019 前 warning，不阻断。
- 对 `assets_impair_loss` 等 yaml1 覆盖项，确认 yaml1 值的符号与 calc 公式口径一致。

这里不重新做 clean.py 的 hard check，只把“易翻符号”的事实口径带入 yaml1 回测报告。

### E4. 预测轨

预测轨只做软检查：

- yaml1 折叠出的收入序列与来源模型/券商模型预测值如果在 stash 中存在，就对比并记录。
- 主动覆盖线，如 gpm、税率、营业外支出，不要求贴合券商模型。

没有来源模型预测值时，不阻断。

### E5. 举旗格式

建议所有失败统一进 `Yaml1CleanError`，并输出 JSON report：

- `severity`: error/warning
- `stage`: fold/expand/resolve/backtest
- `path`
- `year`
- `expected`
- `actual`
- `residual`
- `message`
- `suggested_owner`: human / compiler / yaml1

清洗层不做自动补救。

---

## F. 挑刺与更优实现

### F1. 设计文档对“未逐年化叶子”的描述有冲突

文档一处说“标量来自 yaml2 平推，在 resolve 时广播成等长数组”，另一处示例又说 `market.*`、`balance_sheet.*` 多数原样透传。

真实 calc.py 需要更精确的规则：循环内消费的年度驱动数组化；基准状态和估值常量保持标量。

这能同时满足：

- calc 取参点不做标量/list 兼容判断；
- 不把 `balance_sheet.base`、`market.*` 这种天然标量弄复杂；
- 未来逐年调 BS driver / financial rate 时无需再改 calc。

### F2. 单位系数不应靠自然语言 note

设计文档说从 `income.revenue.note` / stash caveat 读 `÷100`，但清洗层是纯确定性 Python，靠中文文本解析会脆。

当前两个 yaml1 草稿也不一致：

- 根目录草稿 note 明确写了公式。
- 公司目录样例只有 base 注释和 stash caveat。

更优契约：compiler 在 `income.revenue` 或每个 segment 上输出结构化字段：

- `unit_factor_to_million_cny: 100`
- 或 `unit: { volume: "10k_ton", price: "cny_per_ton", revenue: "million_cny", factor: 100 }`

清洗层可以临时支持 regex fallback，但应该在 report 里 warning：`unit_factor inferred from text`。

### F3. fade path 需要 canonical alias

当前公司目录 yaml1 用 `fade_paths: [revenue]`，根目录草稿用 `fade_paths: [income.revenue]`。最终 calc 接受的是 `model.revenue_yoy`。

更优契约：compiler 以后直接输出 `model.revenue_yoy`，或者明确 `income.revenue` 是 decomposition alias。清洗层短期支持 alias，长期推动 canonical。

### F4. yaml2_schema 可复用，但不够表达 yearly 契约

`validate_yaml2()` 不会检查数组长度，也不会知道哪些路径该数组化。这不是 bug，因为它本来服务 YAML2 标量 defaults。

提案：不要急着改 `yaml2_schema.py`，先在 `yaml1_cleaner.py` 里做 `validate_yaml2_yearly()`。等 yearly 成为稳定输入后，再考虑把 schema 拆成：

- `validate_yaml2_defaults`
- `validate_yaml2_yearly`

### F5. financial_expense “原样透传”建议解释为“值来自 yaml2，但形态按 calc 年度输入广播”

设计文档说 financial_expense 永远走 yaml2。这个方向对，但若 calc 取参口全面数组化，financial_expense 的数值叶子也应广播。

建议定义为：

- 来源：yaml2，不由 yaml1 覆盖。
- 形态：循环内数值参数广播为年度数组。
- 非数值配置 `interest_mode` 保持标量。

这样更贴合真实 calc。

---

## 建议实施顺序

这不是本轮要执行的代码，只是后续实现建议：

1. 写 `tests/test_yaml1_cleaner.py`，先覆盖新乳 fold 收入、2024 anchor、fade 展开、path alias。
2. 实现 `src/yaml1_cleaner.py` 的 fold/expand/backtest/resolve，不接 calc。
3. 生成新乳 `yaml2_yearly.yaml`，人工审阅 report。
4. 再做 `calc.py` 逐年化，只改取参口。
5. 用 5 家 defaults 广播回归证明 calc 没破状态链。
6. 最后跑新乳 yaml1 -> yaml2_yearly -> calc 端到端。

---

## 结论

这套实现的核心不是写一个“更聪明的 calc”，而是在 calc 前面加一个确定性适配层：

- yaml1 的非标收入结构在 fold 阶段消费掉，落成 `model.revenue_yoy`。
- 所有显式 knob 和 terminal fade 在 expand 阶段展开到完整 horizon。
- resolve 阶段把 sparse overlay 合并进 2024 baseline 的 yaml2。
- backtest 阶段用 clean_annual 和 stash 证明折叠没有错。
- calc.py 只把取参口升级为按年索引，跨年滚动链一行不动。
