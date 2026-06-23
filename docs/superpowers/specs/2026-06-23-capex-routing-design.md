# Capex 路由修复设计（Option D · 稳态非 PP&E）

- 日期：2026-06-23
- 范围：`src/calc.py` `build_balance_sheet` 的固定资产滚存逻辑
- 影响：预测期三表（BS fix_assets / CF 折旧 / DCF 的 DA、FCFF、每股价值）
- 不影响：clean.py、defaults.yaml、yaml1、SQLite schema、backtest

## 1. 问题

`build_balance_sheet`（`src/calc.py:264-267`）当前把**全部合并 capex** 灌进固定资产滚存：

```python
capex = revenue * capex_pct              # capex_pct = c_pay_acq_const_fiolta / revenue（合并口径）
depreciation = prev_fix * depr_rate
row["fix_assets"] = max(prev_fix + capex - depreciation, 0.0)
```

`capex_pct` 标自 `c_pay_acq_const_fiolta`（购建固定资产、无形资产和其他长期资产支付的现金，A 股合并行，见 `companies/新乳业_002946/Agent/defaults.yaml:729`）。这是**合并口径**——无形资产、使用权资产、长期待摊费用的再投资已经在这条 capex 里。

但模型把这份合并 capex **全部**记入 `fix_assets`，等于让固定资产替非 PP&E 资产背了投资额。后果：

1. `fix_assets` 被高估 → `depreciation = prev_fix × depr_rate` 被高估（幻影折旧）。
2. 预测资产负债表的固定资产失真，下游资产周转率/ROA/固定资产密集度全部偏。

## 2. 关键发现：折旧不进利润表，DA 系数是 +1 不是 +t

`build_income_statement`（`src/calc.py:162-221`）的营业成本完全由毛利率派生：`oper_cost = revenue × (1 − gpm)`。利润表里**没有任何折旧/摊销字段**（grep 整个 income 段零命中 depr/amort/摊销/折旧）。`depreciation = prev_fix × depr_rate` 只用于：

- BS 的 `fix_assets` 滚存（`calc.py:267`）
- CF 的 `depr_fa_coga_dpba` 加回（`calc.py:380`）
- FCFF 的 DA 加回（`calc.py:371, 487`）

**从不进 EBIT/NOPAT。**

因此标准 FCFF 税盾推导 `−ΔDA·(1−t) + ΔDA = ΔDA·t` 对本模型不成立（该推导要求 DA 在 EBIT 内被扣）。本模型 DA 在 FCFF 里的系数是 **+1**：DA 每多 1 元，FCFF 多 1 元，没有 IS 侧扣除来对冲。

推论：

- 路由修复是**一阶**的，不是二阶税盾微调。去掉幻影折旧 → DA 加回变小 → FCFF 按"被移除的幻影折旧"全额下降。
- 方向是**去高估**：当前模型给了一笔"没在 IS 扣过却加回"的幻影折旧，高估了 FCFF。修路由就是去掉这块高估。
- 既有"平推只剩税盾误差"的安慰在本 IS 结构下不成立。t→0 的牧业情形反而更尖锐（连税盾稀释都没有）。

本修复**不处理**"DA 加回却没在 IS 扣"这个更深的不一致（用户已确认范围：只修路由）。该不一致是既有模型行为，本修复不引入也不消除它，只把显式折旧调到真实 PP&E 基数。

## 3. 方案选择（已与用户确认）

修复路由有两种相干做法，二选一（中间态——按比例拆分却不滚存——会让非 PP&E capex 凭空消失，BS 不相干，已排除）：

- **Option D（稳态非 PP&E，本设计采用）**：`capex_ppe = capex − 非 PP&E 稳态再投资`；fix_assets 只滚 `capex_ppe`；非 PP&E 资产保持平推（稳态假设：再投资 = 摊销）。零新参数，~3 行改动。honoring 用户"摊销不做 BS 滚动"的取向。
- **Option R（全滚）**：按 base 期资产结构拆 capex 四份，各自滚存（加进 − 各自摊销）。非 PP&E 资产能增长，更真实，但违背"跳过摊销滚动"，且要派生参数 + defaults_gen/yaml1 接口。

用户选 Option D。

## 4. 设计

### 4.1 改动（`src/calc.py` `build_balance_sheet`）

把 `calc.py:264-267` 改为：

```python
capex = revenue * capex_pct                              # 合并口径，不变
# 非 PP&E 长期资产的稳态再投资 == 其摊销（这些资产保持平推）。
# 只把 PP&E 份灌进 fix_assets，使折旧反映真实 PP&E 基数，
# 而不是实际买了无形/使用权/长期待摊的那部分 capex。
non_ppE_reinvest = (
    get_year_float(yaml2, "balance_sheet.amort_intang_assets", idx)
    + get_year_float(yaml2, "balance_sheet.use_right_asset_dep", idx)
    + get_year_float(yaml2, "balance_sheet.lt_amort_deferred_exp", idx)
)
capex_ppe = capex - non_ppE_reinvest
if capex_ppe < 0.0:
    capex_ppe = 0.0
    if review_flags is not None:
        review_flags.append({
            "code": REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT,
            "severity": "warning",
            "period": None,
            "message": "合并 capex 不足以覆盖非 PP&E 稳态再投资，PP&E 基数在缩，稳态假设吃紧",
            "value": capex - non_ppE_reinvest,
        })
prev_fix = max(prev_bs.get("fix_assets", 0.0), prev_bs.get("fix_assets_total", 0.0), 0.0)
depreciation = prev_fix * depr_rate
row["fix_assets"] = max(prev_fix + capex_ppe - depreciation, 0.0)
if prev_bs.get("fix_assets_total", 0.0) != 0.0:
    row["fix_assets_total"] = row["fix_assets"]
```

### 4.2 不变量

- **`metrics["capex"]` 仍是完整合并 capex**（`calc.py:303` 不动）。CFI `-capex`（`calc.py:374`）和 FCFF `-capex`（`calc.py:487`）保持完整合并口径。FCFF 的"合并 capex 覆盖再投资"正确性保留——只有 fix_assets 滚存的 capex 入量变了。
- 三个摊销旋钮（`amort_intang_assets` / `use_right_asset_dep` / `lt_amort_deferred_exp`）是现成 defaults 字段（`defaults.yaml:733/736/739`），`build_cash_flow` 已在用（`calc.py:368-370`），同一 `yaml2`/`idx`，`build_balance_sheet` 作用域可直接读。**零新参数。**

### 4.3 新增 review flag 常量

在 `src/yaml2_schema.py:28`（`REVIEW_FLAG_NEGATIVE_CASH` 旁）新增：

```python
REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT = "capex_below_non_ppE_amort"
```

并在 `src/calc.py:33` 的 import 中加入。flag 经 `forecast.py:217`（写入 build result）和 `workbench.py:2285`（前端透出）自然流向用户，无需额外接线。

### 4.4 会计核账（为什么是对的）

- **去掉幻影折旧**：fix_assets 不再吸收非 PP&E capex → 折旧基数回到真实 PP&E → `depr_fa_coga_dpba` 变小。
- **FCFF 一阶下修**：DA 加回变小（系数 +1）→ FCFF 下降"被移除的幻影折旧"全额。去高估，正确性修复。
- **IS/NOPAT 不变**：折旧不在 IS。
- **非 PP&E 账本稳态自洽**：该账本现金流中性（CFI `−reinvest` + CFO `+amort` = 0，因 reinvest = amort），资产平推（净变动 0）。与现状一致，只是不再让 fix_assets 替它背锅。
- **net_debt 桥不变**：bridge 用 base 期 `market.net_debt`（`calc.py:445`，来自 `defaults.yaml` 的 base 期快照），不读预测期现金 plug。估值影响只在 EV 一侧（FCFF↓），net_debt 不动。
- **BS 仍配平**：fix_assets↓ 与现金 plug↑ 等额对冲（非 PP&E 账本现金流中性，不偷现金），总资产/权益不变，plug 重算后配平。

### 4.5 向后兼容

资产轻公司（三个摊销旋钮全 0）→ `non_ppE_reinvest = 0` → `capex_ppe = capex`，行为与现在逐字相同。

## 5. 边界与守卫

- **capex < non_ppE_reinvest**：`capex_ppe` 落底 0，发 `REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT`。含义：合并 capex 不足以覆盖非 PP&E 稳态再投资，PP&E 基数在缩，稳态假设吃紧。落底防止 fix_assets 因 capex 负值滚存出错。
- **yaml1 把 capex_pct 覆盖成固定资产口径**：会双重扣减（capex 已不含非 PP&E，再减 non_ppE_reinvest）。defaults_gen 产合并口径，文档显式声明"capex_pct 必须合并口径"为该路由前提。**诚实标注**：`REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT` 只在 `capex < Σ摊销` 时触发，**检测不到**这种双重扣减（PP&E-only 口径下 capex 仍可能 > Σ摊销，flag 不响）。该失效模式完全依赖文档化的口径前置条件，无自动守卫。不加开关（YAGNI）。
- **逐年感知**：`non_ppE_reinvest` 用 `get_year_float` 逐年读，yaml1 若 ramp 摊销，`capex_ppe` 逐年自适应。

## 6. 输出影响

- `forecast_bs.csv`：`fix_assets`↓（现金 plug↑ 对冲，总资产不变）。
- `forecast_cf.csv`：`depr_fa_coga_dpba`↓。
- `dcf_detail.csv` / `dcf_summary.json`：DA↓、FCFF↓、`per_share_value`↓（一阶，去高估）。
- `forecast_is.csv`：不变（折旧不进 IS）。
- 无 schema 变更。重算 forecast 即生效。
- **终值 DA 通道（通用性提示）**：终值 `terminal_fcff = last_nopat + last_da × (1 − terminal_capex_da_ratio)`（`calc.py:548`）。本修复降低 `last_da`，故对 `terminal_capex_da_ratio < 1.0` 的公司，终值也会随之缩小。新乳业 `terminal_capex_da_ratio = 1.0`（`defaults.yaml:21`），终值 = `last_nopat`（与 DA 无关），故本例终值不受影响、只有显式期 FCFF 受影响。对 ratio < 1.0 的公司，EV 下修幅度 = 显式期 PV(ΔDA) + 终值 PV(ΔDA×(1−ratio))。

## 7. 文档同步（项目硬规则）

- `docs/数据流水线.md`：登记 `calc.py` 固定资产滚存逻辑变更。
- `docs/ARCHITECTURE.md` 第 10 节（设计决策）：新增"capex 路由 · 非 PP&E 稳态"条目，记录假设与 +1 系数发现。
- `src/calc.py` 内注释：固化"非 PP&E 稳态再投资 = 摊销，资产平推"假设。
- `CLAUDE.md`：DCF 运行规则段补一句 capex 路由前提（capex_pct 必须合并口径）。

## 8. 测试

### 8.1 新增单测（`tests/test_calc_capex_routing.py`）

1. **fix_assets 用 capex_ppe 滚存**：构造一组合并 capex 与三项摊销旋钮，断言 `fix_assets(t) = prev_fix + (capex − Σ摊销) − depreciation`。
2. **metrics["capex"] 仍是完整合并 capex**：断言 CFI/FCFF 用的 capex 不被路由削减。
3. **负数守卫 + flag**：构造 capex < Σ摊销 的输入，断言 `capex_ppe` 落底 0、`review_flags` 含 `REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT`。
4. **BS 仍配平**：断言每年 `total_assets − total_liab − total_hldr_eqy_inc_min_int` 残差 < 容差。
5. **资产轻公司零影响**：三项摊销旋钮全 0 时，fix_assets/折旧/FCFF 与改前逐字相同。
6. **DA 一阶下修**：路由修复后 DA ≤ 修复前 DA（幻影折旧被移除）。

### 8.2 回归

- 重跑 `py -m src.forecast --ticker 002946.SZ`，确认 `1 < per_share_value < 200`、forecast_bs 每年配平、`depr_fa_coga_dpba` 与 `fix_assets` 较改前下降。
- 现有 `tests/test_forecast_pipeline.py`：bounds-based（非金值），backtest 为收入锚定 residual（`yaml1_cleaner.py:956-982`），不碰折旧引擎，应继续绿。

## 9. 不做（YAGNI / 范围外）

- 不做三项摊销的 BS 滚动（Option R，用户已排除）。
- 不处理"DA 加回却没在 IS 扣"的更深不一致（用户已确认范围：只修路由）。
- 不把 `capex_ppe` 显式暴露进 CF/derived_metrics（效果经 `depr_fa_coga_dpba`↓ 与 `fix_assets`↓ 可见；如需审计可后补）。
- 不加 `capex_routing` 开关（YAGNI，靠文档声明口径前提 + flag 兜底）。
