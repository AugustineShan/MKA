# calc.py cost_abs 符号 bug 诊断与修复方案报告

> 状态：只读诊断，未修改任何代码或原始 defaults.yaml。
> 数据现状：当前工作区 `companies/` 下**仅 1 家公司**（新乳业_002946）存在 `defaults.yaml` + `data.db`；用户提到的“5 家公司”在当前 tree 中无法复现，下文先给出该 1 家的完整量化，并说明若后续补充其他公司可同样套用本方法。

---

## 1. 字段分类与真实符号约定

### 1.1 calc.py 里 cost 的汇总链路（原句 + 行号）

`src/calc.py:118-151` 中，`build_income_statement` 对 cost 的处理如下：

```python
# src/calc.py:124-127
revenue_items = value_map(income.get("revenue_items_abs") if isinstance(income, dict) else None)
cost_rates = value_map(income.get("cost_rates") if isinstance(income, dict) else None)
cost_abs = value_map(income.get("cost_abs") if isinstance(income, dict) else None)
op_adj = value_map(income.get("operating_adjustments_abs") if isinstance(income, dict) else None)
```

```python
# src/calc.py:136-140
row["oper_cost"] = revenue * (1.0 - gpm)
for field, rate in cost_rates.items():
    row[field] = revenue * rate
for field, value in cost_abs.items():
    row[field] = value
```

```python
# src/calc.py:145-146
cost_fields = set(["oper_cost", "fin_exp"]) | set(cost_rates) | set(cost_abs)
row["total_cogs"] = sum(row.get(field, 0.0) for field in cost_fields)
```

```python
# src/calc.py:151
row["operate_profit"] = row["total_revenue"] - row["total_cogs"] + sum(op_adj.values())
```

**结论**：`cost_abs` 里的每个字段都被原样 `sum` 进 `total_cogs`，**无 `abs()`、无符号翻转、无按字段单独处理**。因此 `cost_abs` 内部字段的符号约定必须一致：正值 = 成本（侵蚀利润），负值 = 抵减成本（增厚利润）。

### 1.2 defaults_gen 把哪些字段放进 cost_abs

`src/defaults_gen.py:166-170`：

```python
cost_abs_fields = [
    field
    for field, category in IS_FIELD_CATEGORIES.items()
    if category == "cost_item" and field not in COST_ABS_EXCLUDE | {"fin_exp"}
]
```

其中 `COST_ABS_EXCLUDE = {"oper_cost", *REVENUE_RATE_FIELDS}`（`src/defaults_gen.py:46`），`REVENUE_RATE_FIELDS` 为 `biz_tax_surchg/sell_exp/admin_exp/rd_exp/other_bus_cost`（`src/defaults_gen.py:38-44`）。

因此进入 `cost_abs` 的字段是 `IS_FIELD_CATEGORIES` 中全部 `cost_item`，排除 `oper_cost` 和 5 个 rate 字段，再加回排除后剩下的 16 个字段。完整列表见 `src/clean.py:68-93`：

| 字段 | clean 分类 | 中文名 | 新乳业 2025 实际值 |
|---|---|---|---|
| `oper_cost` | cost_item | 减:营业成本 | 7955.46 |
| `biz_tax_surchg` | cost_item | 减:营业税金及附加 | 59.51 |
| `sell_exp` | cost_item | 减:销售费用 | 1809.52 |
| `admin_exp` | cost_item | 减:管理费用 | 356.81 |
| `fin_exp` | cost_item | 减:财务费用 | 77.77 |
| `rd_exp` | cost_item | 研发费用 | 50.37 |
| `assets_impair_loss` | cost_item | 减:资产减值损失 | **-62.82** |
| `credit_impa_loss` | cost_item | 信用减值损失 | **+1.96**（`income.credit_impa_loss`） |
| `other_bus_cost` | cost_item | 其他业务成本 | 0.00 |
| `oth_impair_loss_assets` | cost_item | 其他资产减值损失 | 0.00 |
| `int_exp` / `comm_exp` / `prem_refund` / `compens_payout` / `reser_insur_liab` / `div_payt` / `reins_exp` / `oper_exp` / `insurance_exp` / `out_prem` / `une_prem_reser` / `compens_payout_refu` / `insur_reser_refu` / `reins_cost_refund` | cost_item | 保险/金融类费用 | 0.00 |

### 1.3 真实符号约定判定

以**新乳业 2025 年 clean_annual** 实测值为证据：

| 类别 | 字段 | clean_annual 值 | 符号含义 | 是否被 calc.py 正确处理 |
|---|---|---|---|---|
| 营业成本 | `oper_cost` | 7955.46 | **正 = 成本** | ✅ 是 |
| 费率类成本 | `biz_tax_surchg` / `sell_exp` / `admin_exp` / `rd_exp` / `other_bus_cost` | 59.51 / 1809.52 / 356.81 / 50.37 / 0.00 | **正 = 成本** | ✅ 是（作为 revenue × rate） |
| 财务费用 | `fin_exp` | 77.77 | **正 = 成本** | ✅ 是 |
| 资产减值损失 | `assets_impair_loss` | **-62.82** | **负 = 侵蚀利润**（利润表口径） | ❌ **反了** |
| 信用减值损失 | `income.credit_impa_loss` | **+1.96** | **正 = 成本**（TuShare 口径） | ✅ 是 |
| 其他资产减值 | `oth_impair_loss_assets` | 0.00 | 无法判定 | — |

关键证据：

```
period  assets_impair_loss  income.credit_impa_loss  biz_tax_surchg    sell_exp    admin_exp    fin_exp
  2025          -62.823619                 1.955919       59.506713 1809.515621 356.813793  77.773929
  2024          -97.653334                 8.567480       53.053285 1659.289818 380.815923 100.962864
  2023          -17.011555                -9.038921       51.738922 1678.497179 469.880957 161.976357
  2022           -0.275754               -36.020883       45.860294 1356.645575 469.577065 147.667077
  2021           -0.566064                 7.163967       44.380493 1247.600504 492.356164 116.431462
  2020           -2.910998                -5.748540       32.888699  921.283080 369.175398  82.091671
  2019           -0.171484                -8.939262       30.421673 1250.179295 319.794271  63.876419
  2018           10.490838                 0.000000       30.285423 1069.280316 284.222722  68.687044
  2017           14.923093                 0.000000       30.961132  939.038670 268.671519  75.229386
  2016            2.239197                 0.000000       27.960563  856.509174 260.149959  36.296012
```

**额外发现**：
1. `assets_impair_loss` 在 2019-2025 年为负，2016-2018 年为正，说明 TuShare 对同一字段的符号口径在不同年份可能发生变化（或数据源新旧准则差异）。
2. `income.credit_impa_loss` 在 2022-2023、2019-2020 年也为负，说明信用减值损失的符号同样不稳定。
3. 因此 `cost_abs` 桶内**不能简单按“全部正成本”处理**，必须有字段级符号约定或按“经济含义”归一化。

### 1.4 文档层面的误导

`docs/yaml2_calc关系说明.md:24` 写：

```markdown
impairment = 直接用绝对值                        ← 读 YAML2 的 assets_impair_loss + credit_impa_loss
```

但 `src/calc.py:145-146` 实际是 `sum(row.get(field, 0.0) for field in cost_fields)`，**没有 `abs()`**。文档与代码不一致。

---

## 2. 修复方案候选

### 方案 A：把损益类减值项从 total_cogs 桶剥离，按真实符号单独并入 operate_profit

**做法**：
- 在 `src/calc.py` 中，将 `assets_impair_loss` / `credit_impa_loss` / `oth_impair_loss_assets` 从 `cost_fields` 中移除。
- 改为：`operate_profit = total_revenue - total_cogs + sum(op_adj.values()) + sum(impairment_adj.values())`。
- 其中 `impairment_adj` 直接取 YAML2 值，按其经济含义代数相加：
  - 若值表示“负 = 侵蚀利润”（如 assets_impair_loss），则 -62.82 直接加进 operate_profit，利润减少 62.82。
  - 若值表示“正 = 成本”（如 credit_impa_loss），则 +1.96 直接加进 operate_profit，利润减少 1.96。

**优点**：
- 尊重不同 TuShare 字段的符号习惯，无需在 defaults_gen 端统一符号。
- 与利润表原始披露逻辑一致：减值损失是营业利润的**调节项**，不是“成本”本身。

**缺点 / 影响面**：
- 需要改动 `src/calc.py` 的 `build_income_statement`；`total_cogs` 不再包含减值项，但 `total_opcost` 也应同步调整，否则 `total_cogs` 与 `total_opcost` 的语义会分叉。
- 会改变所有已生成 defaults.yaml 的公司的历史结果（包括 新乳业）。
- 需要同步更新 `docs/yaml2_calc关系说明.md` 和 `docs/ARCHITECTURE.md` 中 `cost_item` 示例。

### 方案 B：在 defaults_gen 入库时统一符号，全部转为“正 = 成本”

**做法**：
- 在 `src/defaults_gen.py:246` 生成 `cost_abs` 时，对已知“负 = 侵蚀利润”的字段（`assets_impair_loss` 等）取 `-value` 后再写入 YAML2。
- `src/calc.py` 保持不变，继续直接 `sum`。

**优点**：
- 改动面最小，只改 defaults_gen；calc.py 逻辑保持简单。
- 下游所有使用 YAML2 的地方无需知道符号约定。

**缺点 / 影响面**：
- 需要明确知道哪些字段是“负 = 侵蚀利润”。从 新乳业 历史数据看，`assets_impair_loss` 并非每年都负（2016-2018 为正），`credit_impa_loss` 也有正有负。若 TuShare 符号口径不稳定，统一翻转可能导致某些年份反而翻错。
- 已生成的 `defaults.yaml` 需要重新生成；历史已验证公司结果会变化。
- 掩盖了 `cost_abs` 桶内符号不一致的本质问题。

### 方案 C：给每个 cost_abs 字段标注符号方向，calc.py 按方向代数加

**做法**：
- 在 YAML2 schema 中新增 `cost_abs_signs`（或在每个字段加 `sign` 元数据），例如：
  ```yaml
  cost_abs:
    assets_impair_loss:
      value: -62.82361899
      sign: negative_means_cost   # 负值表示成本/侵蚀利润
    credit_impa_loss:
      value: 1.95591934
      sign: positive_means_cost   # 正值表示成本
  ```
- `src/calc.py` 读取 sign 后，统一转换为“正 = 成本”再加进 `total_cogs`。

**优点**：
- 最灵活、最显式；未来遇到符号混合字段可直接配置，不硬编码字段名。
- 保留原始 YAML2 值，便于审计。

**缺点 / 影响面**：
- 改动面最大：需要改 `yaml2_schema.py`、defaults_gen、calc.py，以及所有已有 defaults.yaml。
- 5 家已验证公司（或当前 1 家）的结果都会变化。

### 推荐方案

**推荐方案 A**，理由：
1. `assets_impair_loss` / `credit_impa_loss` 在会计准则里本就是营业利润的**调节项**，不是营业成本的组成部分；把它们从 `total_cogs` 桶里拆出来更符合报表结构。
2. 不需要在 defaults_gen 里猜测 TuShare 的符号口径；直接按 YAML2 值的代数符号进入 `operate_profit`，最不容易翻错。
3. 对现有 `cost_rates` / `oper_cost` / `fin_exp` 等“正 = 成本”字段零影响，只调整减值类字段的处理位置。
4. 代码改动集中在 `src/calc.py:145-151`，范围小且意图清晰。

**若追求最小改动且确信 TuShare 符号稳定**，可选方案 B，但需先对 `assets_impair_loss` / `credit_impa_loss` / `oth_impair_loss_assets` 的历年符号做批量统计验证。

---

## 3. 量化影响（当前工作区仅 1 家公司）

### 3.1 现状运行结果

运行命令：

```bash
python -m src.calc --defaults companies/新乳业_002946/defaults.yaml --output-dir companies/新乳业_002946/forecast_current
```

输出：

```
Per-share value: 14.21837394939914
```

`companies/新乳业_002946/forecast_current/forecast_is.csv` 中 2026 年关键行：

| 指标 | 当前值 |
|---|---|
| `total_revenue` | 11233.45771285 |
| `oper_cost` | 7955.45785249 |
| `total_cogs` | 10244.17032235 |
| `assets_impair_loss` | -62.82361899 |
| `credit_impa_loss` | 1.95591934 |
| `fin_exp` | 73.37802193 |
| `operate_profit` | **978.68179091** |
| `n_income` | 866.40772389 |

### 3.2 修正符号后的对照运行

为量化影响，临时生成一份仅把 `assets_impair_loss` 从 `-62.82361899` 改为 `+62.82361899` 的 defaults.yaml（未改动原文件），运行后删除：

```bash
sed 's/value: -62.82361899/value: 62.82361899/' companies/新乳业_002946/defaults.yaml > defaults_corrected_temp.yaml
python -m src.calc --defaults defaults_corrected_temp.yaml --output-dir forecast_corrected_temp
```

输出：

```
Per-share value: 12.169321454798961
```

`forecast_corrected_temp/forecast_is.csv` 中 2026 年关键行：

| 指标 | 修正后值 |
|---|---|
| `total_cogs` | 10370.53603714 |
| `fin_exp` | 74.09649874 |
| `operate_profit` | **852.31607612** |
| `n_income` | 754.25943232 |

### 3.3 注水量化

| 指标 | 当前值 | 修正后值 | 注水（当前 - 修正） | 注水比例 |
|---|---|---|---|---|
| 2026 `operate_profit` | 978.68179091 | 852.31607612 | **+126.36571478** | +14.83% |
| 2026 `n_income` | 866.40772389 | 754.25943232 | **+112.14829158** | +14.87% |
| `per_share_value` | 14.21837395 | 12.16932145 | **+2.04905249** | **+16.84%** |

**注**：
- operate_profit 注水 126.37 ≈ 2 × 62.82（把 -62.82 当成成本减去，相当于成本少计 62.82；同时利润又多出 62.82，双向差异 125.65），再加上循环利息/plug 收敛的微小反馈，最终为 126.37。
- 由于 `solve_forecast_year` 中财务费用与资产负债表 cash plug 是循环迭代求解的（`src/calc.py:282-297`），减值符号错误会通过 retained earnings → total_equity → required_cash → interest_income → fin_exp 产生二次放大，因此 DCF 每股价值的注水比例（16.84%）高于单期 operate_profit 注水比例（14.83%）。

### 3.4 关于“5 家公司”的说明

当前工作区 `companies/` 下仅找到 **1 家** 含 `defaults.yaml` + `data.db` 的公司：

```
companies/新乳业_002946/data.db
companies/新乳业_002946/defaults.yaml
```

因此上述量化只针对 新乳业_002946。若用户手头有其他 4 家公司的 `defaults.yaml`，可把本报告第 3 节的 sed 对照跑法批量套用：

```bash
for y in company1 company2 company3 company4; do
  sed 's/assets_impair_loss:/XXX/' "$y/defaults.yaml" ...  # 按具体字段值替换符号
  python -m src.calc --defaults "$y/defaults_corrected.yaml" --output-dir "$y/forecast_corrected"
done
```

或选择修复方案后统一重跑全部公司。

---

## 4. 下一步建议（待用户确认）

1. **确认符号口径**：建议先批量检查所有目标公司的 `clean_annual.assets_impair_loss`、`income.credit_impa_loss`、`oth_impair_loss_assets` 历年符号，确认是否所有公司都呈现“负 = 侵蚀利润”或存在混合。
2. **选择修复方案**：
   - 若同意方案 A，可在 `src/calc.py:145-151` 将减值类字段从 `total_cogs` 拆出，直接并入 `operate_profit`。
   - 若同意方案 B，可在 `src/defaults_gen.py` 对特定字段做符号归一化。
   - 若同意方案 C，需同步扩展 YAML2 schema。
3. **回归验证**：修复后重跑 新乳业_002946 及后续公司，确认 `forecast_is.csv` 第一年的 `operate_profit` 与 `clean_annual.operate_profit` 基本一致（当前 bug 下 forecast 第一年 978.68 已偏离 clean_annual 852.55）。

---

*报告生成时间：2026-06-14；仅读取代码与数据，未修改任何源文件。*
