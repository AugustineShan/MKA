# cost_abs 符号修复 · 第一段设计报告

> 状态：只读盘点 + 方案设计，未修改任何代码，未 commit。

---

## 1. cost_abs 全部字段盘点与分类

### 1.1 字段来源

`src/defaults_gen.py:166-170` 决定哪些字段进入 YAML2 的 `income.cost_abs`：

```python
cost_abs_fields = [
    field
    for field, category in IS_FIELD_CATEGORIES.items()
    if category == "cost_item" and field not in COST_ABS_EXCLUDE | {"fin_exp"}
]
```

- `COST_ABS_EXCLUDE = {"oper_cost", *REVENUE_RATE_FIELDS}`（`src/defaults_gen.py:46`）
- `REVENUE_RATE_FIELDS = ["biz_tax_surchg", "sell_exp", "admin_exp", "rd_exp", "other_bus_cost"]`（`src/defaults_gen.py:38-44`）

因此 `cost_abs` 实际包含 **17 个字段**（24 个 cost_item 减去 `oper_cost`、5 个 rate 字段、`fin_exp`）。

### 1.2 按现代报表口径分类

| # | 字段 | 中文名 | 现代报表归属 | 处理方案 |
|---|---|---|---|---|
| 1 | `assets_impair_loss` | 减:资产减值损失 | **带符号损益·营业利润调节项** | 从 total_cogs 剥离，代数并入 operate_profit |
| 2 | `credit_impa_loss` | 信用减值损失 | **带符号损益·营业利润调节项** | 从 total_cogs 剥离，代数并入 operate_profit |
| 3 | `oth_impair_loss_assets` | 其他资产减值损失 | **带符号损益·营业利润调节项** | 从 total_cogs 剥离，代数并入 operate_profit |
| 4 | `int_exp` | 减:利息支出 | 正成本（含于财务费用） | 留 total_cogs |
| 5 | `comm_exp` | 减:手续费及佣金支出 | 正成本 | 留 total_cogs |
| 6 | `prem_refund` | 退保金 | 正成本（保险专用，一般工商企业为 0） | 留 total_cogs |
| 7 | `compens_payout` | 赔付总支出 | 正成本（保险专用） | 留 total_cogs |
| 8 | `reser_insur_liab` | 提取保险责任准备金 | 正成本（保险专用） | 留 total_cogs |
| 9 | `div_payt` | 保户红利支出 | 正成本（保险专用） | 留 total_cogs |
| 10 | `reins_exp` | 分保费用 | 正成本（保险专用） | 留 total_cogs |
| 11 | `oper_exp` | 营业支出 | 正成本 | 留 total_cogs |
| 12 | `insurance_exp` | 保险业务支出 | 正成本（保险专用） | 留 total_cogs |
| 13 | `out_prem` | 减:分出保费 | 正成本（保险专用） | 留 total_cogs |
| 14 | `une_prem_reser` | 提取未到期责任准备金 | 正成本（保险专用） | 留 total_cogs |
| 15 | `compens_payout_refu` | 减:摊回赔付支出 | 正成本（保险专用） | 留 total_cogs |
| 16 | `insur_reser_refu` | 减:摊回保险责任准备金 | 正成本（保险专用） | 留 total_cogs |
| 17 | `reins_cost_refund` | 减:摊回分保费用 | 正成本（保险专用） | 留 total_cogs |

**说明**：
- 保险/金融类字段（6-17）对 `comp_type=1` 的一般工商业企业通常全为 0，但按现代报表口径它们属于成本段，不归入“损益调节项”，因此留在 `total_cogs`。
- `fin_exp` 已单独在 `financial_expense` 中处理，不在 `cost_abs` 中。

### 1.3 2019 前后口径翻转历史包袱

以 **新乳业_002946 clean_annual** 实测为例（单位：百万元）：

```
period  assets_impair_loss  income.credit_impa_loss
  2025          -62.823619                 1.955919
  2024          -97.653334                 8.567480
  2023          -17.011555                -9.038921
  2022           -0.275754               -36.020883
  2021           -0.566064                 7.163967
  2020           -2.910998                -5.748540
  2019           -0.171484                -8.939262
  2018           10.490838                 0.000000
  2017           14.923093                 0.000000
  2016            2.239197                 0.000000
```

- **`assets_impair_loss`**: 2016-2018 为正，2019-2025 为负。原因：2019 年报表格式变更，资产减值损失从“营业成本段”移到“营业利润调节项段”，数值改以负号表示损失。
- **`credit_impa_loss`**: 2019 年后才从资产减值损失中拆出独立列示，符号同样不稳定（2022/2023/2019/2020 为负，其余为正或 0）。
- **`oth_impair_loss_assets`**: 新乳业历年为 0，无法从该公司判断，但同属减值类，一并纳入动态验证。

**结论**：符号无法静态断言，必须按年动态判定。

---

## 2. 方案 A 在 calc.py 的确切 diff

### 2.1 修改思路

在 `src/calc.py:build_income_statement` 中：
1. 把 `assets_impair_loss` / `credit_impa_loss` / `oth_impair_loss_assets` 从 `cost_fields` 中移除；
2. 新增 `impact_adjustment` 项，等于这三个字段在 YAML2 中给出的原值（代数相加）；
3. `operate_profit = total_revenue - total_cogs + op_adj + impact_adjustment`。

这样：
- `-62.82` 直接加进 operate_profit → 利润减少 62.82（正确，负=损失）。
- `+1.96` 直接加进 operate_profit → 利润减少 1.96（正确，正=成本）。

### 2.2 确切代码 diff（只贴出不落盘）

在 `src/calc.py` 模块级新增常量（建议放在 `TOLERANCE` 等常量附近）：

```python
# src/calc.py（模块顶部，与其他常量并列）
IMPACT_ADJUSTMENT_FIELDS = {
    "assets_impair_loss",
    "credit_impa_loss",
    "oth_impair_loss_assets",
}
```

在 `build_income_statement` 中修改 `cost_fields` 与 `operate_profit` 两行：

```python
# src/calc.py:145-151（当前代码）
    cost_fields = set(["oper_cost", "fin_exp"]) | set(cost_rates) | set(cost_abs)
    row["total_cogs"] = sum(row.get(field, 0.0) for field in cost_fields)
    row["total_opcost"] = row["total_cogs"]

    for field, value in op_adj.items():
        row[field] = value
    row["operate_profit"] = row["total_revenue"] - row["total_cogs"] + sum(op_adj.values())
```

改为：

```python
# src/calc.py:145-151（建议修改后）
    impact_fields = set(cost_abs) & IMPACT_ADJUSTMENT_FIELDS
    cost_fields = (
        set(["oper_cost", "fin_exp"])
        | set(cost_rates)
        | (set(cost_abs) - IMPACT_ADJUSTMENT_FIELDS)
    )
    row["total_cogs"] = sum(row.get(field, 0.0) for field in cost_fields)
    row["total_opcost"] = row["total_cogs"]

    for field, value in op_adj.items():
        row[field] = value
    impact_adjustment = sum(row.get(field, 0.0) for field in impact_fields)
    row["operate_profit"] = (
        row["total_revenue"] - row["total_cogs"] + sum(op_adj.values()) + impact_adjustment
    )
```

### 2.3 为什么不在 defaults_gen.py 端移动字段

可选做法是把这三个字段从 YAML2 的 `cost_abs` 移到 `operating_adjustments_abs`，这样 calc.py 一行不改。但本次选择 **只在 calc.py 做判断**，理由：
- 不破坏现有 YAML2 schema；
- 新乳业现有 `defaults.yaml` 无需重跑即可被修复后的 calc.py 正确解释；
- 未来补出的 4 家公司用当前 `defaults_gen.py` 生成 YAML2 后，calc.py 同样能正确处理。

（如果用户更偏好 schema 清晰，可第二段顺带把 `defaults_gen.py` 也改到 `operating_adjustments_abs`，但这不是方案 A 的必要条件。）

---

## 3. clean.py 动态符号验证设计

### 3.1 设计目标

- **不预先断言**任何易翻字段的符号；
- 用利润表自身恒等式反推（**注意循环风险**，见 3.2 节）；
- 仅当某一符号组合能让恒等式残差 **精确归零（< 现有容差 1 百万元）** 时才采用；
- 两种符号都平不了，或出现歧义 → 写 `clean_warnings` 标“口径断点/符号不可判”，该年 IS 符号校验**软降级为 warning，不阻断**；
- **只有“判出唯一符号但仍不平”才算真异常**，进入 hard check 报错；
- **绝不允许把残差塞进任何 plug 字段**；
- 只判定离散符号方向，不制造连续残差。

### 3.2 适用域与循环风险声明

**适用域**：动态符号验证只在 **2019 年及以后**启用，作为现代报表口径下的 sanity check。2016-2018 年直接标为“口径断点”并跳过，不参与符号反推。

理由：
- 2019 年财政部报表格式变更后，资产减值损失、信用减值损失的列报位置与符号约定才趋于稳定；
- 2016-2018 年 `assets_impair_loss` 可能表示成本额（正数）或损失/ reversal，历史口径不统一，无法靠同一张利润表反推。

**循环风险**：
- 锚等式左右两边（`operate_profit`、`revenue`、各 cost/adjustment 字段）均来自 TuShare 同一张 income 表；
- 该等式本质上是“用表内合计项与明细项自洽”做校验，不是独立数据源交叉验证；
- 若 TuShare 在某一年把减值损失与 operate_profit 同时按同一错误口径录入，等式仍可能“自洽地错”；
- 因此动态验证只能作为**口径一致性 sanity check**，不能替代对原始报表格式的外部确认。

### 3.3 存疑字段集

```python
# src/clean.py（模块级常量）
SIGN_QUESTIONABLE_IS_FIELDS = {
    "assets_impair_loss",
    "credit_impa_loss",
    "oth_impair_loss_assets",
}
```

### 3.4 锚定恒等式

采用利润表明细字段 identity，**不使用**可能含未归属成本的 `total_cogs` subtotal 作为锚（同时注意 3.2 节所述循环风险）：

```
operate_profit(TuShare)
  = revenue_base
    − Σ(cost_item 中“符号稳定的正成本”)
    + Σ(operating_adjustment 字段)
    + Σ(sign_f × value_f for f in 存疑集)
```

其中：
- `revenue_base` 复用 `check_is` 现有逻辑：当 `total_revenue − revenue` 可被 `int_income + comm_income + n_oth_b_income` 解释时，取 `total_revenue`，否则取 `revenue`。
- “符号稳定的正成本” = `IS_FIELD_CATEGORIES["cost_item"]` 中排除 `SIGN_QUESTIONABLE_IS_FIELDS` 的字段。
- `operating_adjustment` 字段 = `IS_FIELD_CATEGORIES["operating_adjustment"]` 中现有 6 个字段。
- `sign_f ∈ {+1, −1}`，对存疑字段的两种代数取法。

### 3.5 搜索与判定算法

对每一年：

1. 从 `period` 提取年份；若年份 **< 2019**，返回 `sign_map=None` 并写 warning `口径断点：2019年前跳过动态符号验证`。
2. 若年份 **≥ 2019**，收集该年实际出现且非零的存疑字段列表 `Q_present`。
3. 若 `Q_present` 为空，返回空 sign_map，无 warning。
4. 否则枚举全部 `2^|Q_present|` 种符号组合。
5. 对每种组合计算恒等式残差 `residual`。
6. 筛选出 `|residual| < TOLERANCE`（默认 1.0 百万元）的组合。
7. **结果裁决**：
   - 恰好 1 个组合通过 → 采用该组合，返回 `{field: sign}`，可写 `clean_warnings` 审计记录。
   - 0 个组合通过 → 写 warning `口径断点/符号不可判：...`，返回 `sign_map=None`，该年 IS 符号校验软降级。
   - ≥2 个组合通过 → 写 warning `口径断点/符号歧义：...`，返回 `sign_map=None`，该年 IS 符号校验软降级。

### 3.6 与现有 check_is 的衔接

- 在 `src/clean.py:validate_wide()` 中，每年调用 `check_is()` 之前先调用 `resolve_is_signs(row, present, year)`。
- `resolve_is_signs` 返回 `(sign_map, warnings)`：
  - `sign_map` 为 `None` 或字典；
  - `warnings` 为字符串列表，直接追加到 `period_warnings`。
- 当 `sign_map` 为 `None` 或空时，`check_is` 回退到现有行为（把存疑字段当作 cost_item 处理），**不因此产生新 hard error**。
- 当 `sign_map` 非空时，`check_is` 内部：
  - IS 1.1 `cogs_calc` 改用“符号稳定的正成本”之和（即排除存疑字段后的 cost_item 和），原有 total_opcost / operate_profit 回退逻辑保持不变；
  - IS 1.2 `oper_profit_calc` 改用上述恒等式（`revenue_base − signed_cost_sum + signed_adjustment_sum`）；
  - 若判出唯一符号后仍不平，才按现有 IS 1.2 逻辑报 hard error。
  - 其余检查（IS 1.3-1.6）不变。

### 3.7 报告格式示例

**口径断点（2019 年前）**：

```
IS sign 2018 skipped: 口径断点，2019年前不启用动态符号验证
```

**符号判不出**：

```
IS sign 2025 口径断点/符号不可判: fields=['assets_impair_loss', 'credit_impa_loss'],
values=[-62.8236, 1.9559], best_residual=15.4321, tolerance=1.0000
```

**符号歧义**：

```
IS sign 2025 口径断点/符号歧义: fields=['assets_impair_loss', 'credit_impa_loss'],
acceptable_signs=[(+1,+1), (-1,-1)], residuals=[0.32, 0.78]
```

**符号确定**（可写入 `clean_warnings` 作为审计记录，不修改任何数据值）：

```
IS sign 2025 resolved: assets_impair_loss=-1, credit_impa_loss=+1
```

### 3.8 关键纪律

- **不使用任何 qa_*_plug 字段**：动态验证只判定符号，不吸收残差。
- **不修改 row 中的原始值**：sign_map 仅用于校验计算，不改写 `clean_annual` 宽表。
- **容差只用于判定“精确归零”**：不是允许连续误差，而是考虑 TuShare 四舍五入到百万元后的正常残差。
- **软降级不阻断**：符号判不出/歧义只写 warning，该年继续 downstream；只有判出唯一符号后仍不平才 hard error。

---

## 4. 第二段实施清单（已确认开工）

1. **calc.py**：按 2.2 节 diff 实现 `IMPACT_ADJUSTMENT_FIELDS` 与 `impact_adjustment`。
2. **clean.py**：
   - 新增 `SIGN_QUESTIONABLE_IS_FIELDS`；
   - 新增 `resolve_is_signs(row, present, year)`，返回 `(sign_map, warnings)`；
   - 2019 年前返回 `sign_map=None` 并写“口径断点”warning；
   - 2019 年起按 3.5 节算法枚举符号；判不出/歧义时写“口径断点/符号不可判”warning，不阻断；
   - 新增 `signed_is_cost_sum()` / `signed_is_adjustment_sum()`；
   - 修改 `check_is()` 接收 `sign_map`：非空时使用符号化和，空/None 时回退现有行为；
   - 修改 `validate_wide()`：把 `resolve_is_signs` 的 warnings 追加到 `period_warnings`。
3. **五家公司回归（硬验收）**：
   - 当前已有：新乳业_002946（data.db + defaults.yaml 已存在）。
   - 需补出：安克创新_300866、伊利_600887、美的_000333、比亚迪_002594 的 data.db + defaults.yaml。
   - 每家执行 `python -m src.init <ticker>`；若网络/鉴权失败，该公司列为“未验证”，如实报告，绝不只验新乳就当影响面验过。
4. **对照跑数**：对 5 家（或实际可用的家数）分别跑修复前后 calc.py，列 `operate_profit` / `n_income` / `per_share_value` 对照表。
5. **配平复核**：确认每家 `validate_accounting` 全过；任一失败停止报告。
6. **文档更新**：`docs/yaml2_calc关系说明.md:24` 中“impairment = 直接用绝对值”与代码不符，需同步修正。

---

*设计报告更新时间：2026-06-14；按用户反馈修订为软降级 + 2019+ 适用域 + 循环风险声明。*
