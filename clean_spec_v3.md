# clean.py 规格书 v3

## 目标

从 Tushare 原始数据生成历史三表宽表，**严格配平：每一条校验的残差 < 1（百万元）**。

配平 = 每一个小计精确等于其全部明细项之和。残差非零就是 bug，必须定位，不接受 carry forward。

## 输入

- `data.db`（SQLite），表 `raw_tushare`（EAV 格式：source_endpoint, field, value 等）
- 过滤条件：
  - `report_type = '1'`（合并报表年报）
  - `comp_type = '1'`（一般工商业企业）← 本 spec 不适用于银行/保险/证券
  - 同一 `end_date` 多条记录时取 `f_ann_date` 最大者（最终修订版）

## 输出

- `clean_{ticker}.csv`：宽表，行 = 年份，列 = Tushare 返回的**全部字段**（不裁剪）
- 控制台逐年打印每条校验结果。任何一条 fail 则报错停止，打印该公式各项原始值，辅助定位。

## 核心原则

1. **不手动选字段**。Tushare 返回多少字段就用多少。
2. **区分"字段不存在"和"字段值为 0"**。在 EAV pivot 时，如果某 field 在 raw_tushare 中该年根本没有 row，标记为 NOT_PRESENT（而非填 0）。只有 value = NULL 或 value = 0 的才填 0。这个区分影响合并科目处理逻辑（见下文 resolve）。

---

## 一、利润表（IS）校验

### 1.1 营业总成本

```python
total_cogs_calc = (
    oper_cost              # 营业成本
    + biz_tax_surchg       # 税金及附加
    + sell_exp             # 销售费用
    + admin_exp            # 管理费用
    + rd_exp               # 研发费用
    + fin_exp              # 财务费用
    + assets_impair_loss   # 资产减值损失
    + credit_impa_loss     # 信用减值损失
)
assert abs(total_cogs - total_cogs_calc) < 1
```

注：2018及之前年份，`credit_impa_loss` 尚未从 `assets_impair_loss` 中拆出，Tushare 对旧年份 `credit_impa_loss` 可能为 NULL→0，而 `assets_impair_loss` 包含全部减值。此时公式仍成立（0 + 全部 = 全部），无需特殊处理。

### 1.2 营业利润

```python
operate_profit_calc = (
    revenue                       # 营业收入
    - total_cogs                  # 营业总成本（用1.1已验证的值）
    + oth_income                  # 其他收益
    + invest_income               # 投资收益（已含ass_invest_income和amodcost_fin_assets，不重复加）
    + net_expo_hedging_benefits   # 净敞口套期收益
    + fv_value_chg_gain           # 公允价值变动收益
    + asset_disp_income           # 资产处置收益
)
assert abs(operate_profit - operate_profit_calc) < 1
```

### 1.3 利润总额

```python
assert abs(total_profit - (operate_profit + non_oper_income - non_oper_exp)) < 1
```

### 1.4 净利润

```python
assert abs(n_income - (total_profit - income_tax)) < 1
```

### 1.5 净利润归属

```python
assert abs(n_income - (n_income_attr_p + minority_gain)) < 1
```

### 1.6 营业总收入 = 营业收入（一般工商业验证）

```python
assert abs(total_revenue - revenue) < 1
# 如果不等，说明混入了金融企业数据（利息收入/保费收入等），报错
```

### IS 符号约定

- 收入类（revenue, oth_income, invest_income 等）：正 = 收入
- 费用/成本类（oper_cost, sell_exp 等）：**正 = 费用**
- 损失类（assets_impair_loss, credit_impa_loss）：**正 = 损失**
- 收益/损失类（fv_value_chg_gain, asset_disp_income）：正 = 收益，负 = 损失

---

## 二、资产负债表（BS）— 资产端

### 2.1 流动资产

```python
cur_asset_items = [
    'money_cap',           # 货币资金
    'trad_asset',          # 交易性金融资产
    'notes_receiv',        # 应收票据        ← 与 accounts_receiv 可能合并
    'accounts_receiv',     # 应收账款        ← 与 notes_receiv 可能合并
    'receiv_financing',    # 应收款项融资
    'prepayment',          # 预付款项
    'oth_receiv',          # 其他应收款      ← 可能只有 oth_rcv_total
    'inventories',         # 存货
    'contract_assets',     # 合同资产
    'hfs_assets',          # 持有待售资产
    'nca_within_1y',       # 一年内到期的非流动资产
    'oth_cur_assets',      # 其他流动资产
    # 金融业（一般企业为0）：
    'sett_rsrv',           # 结算备付金
    'loanto_oth_bank_fi',  # 拆出资金
    'premium_receiv',      # 应收保费
    'reinsur_receiv',      # 应收分保账款
    'reinsur_res_receiv',  # 应收分保合同准备金
    'pur_resale_fa',       # 买入返售金融资产
    'amor_exp',            # 待摊费用
    'div_receiv',          # 应收股利
    'int_receiv',          # 应收利息
]

# 合并科目处理
notes_plus_ar = resolve(['notes_receiv', 'accounts_receiv'], 'accounts_receiv_bill')
oth_receiv_val = resolve(['oth_receiv'], 'oth_rcv_total')

assert abs(total_cur_assets - sum_with_resolve(cur_asset_items)) < 1
```

### 2.2 非流动资产

```python
noncur_asset_items = [
    'fa_avail_for_sale',    # 可供出售金融资产（旧准则）
    'htm_invest',           # 持有至到期投资（旧准则）
    'debt_invest',          # 债权投资（新准则）
    'oth_debt_invest',      # 其他债权投资（新准则）
    'lt_rec',               # 长期应收款
    'lt_eqt_invest',        # 长期股权投资
    'oth_eq_invest',        # 其他权益工具投资
    'oth_illiq_fin_assets', # 其他非流动金融资产
    'invest_real_estate',   # 投资性房地产
    'fix_assets',           # 固定资产       ← 可能只有 fix_assets_total
    'cip',                  # 在建工程       ← 可能只有 cip_total
    'produc_bio_assets',    # 生产性生物资产
    'oil_and_gas_assets',   # 油气资产
    'use_right_assets',     # 使用权资产
    'intan_assets',         # 无形资产
    'r_and_d',              # 开发支出
    'goodwill',             # 商誉
    'lt_amor_exp',          # 长期待摊费用
    'defer_tax_assets',     # 递延所得税资产
    'oth_nca',              # 其他非流动资产
    # 金融业：
    'cost_fin_assets',      # 以摊余成本计量的金融资产
    'fair_value_fin_assets',# 以公允价值计量且变动计入其他综合收益的金融资产
    'decr_in_disbur',       # 发放贷款及垫款
    'time_deposits',        # 定期存款
    'oth_assets',           # 其他资产
]

# 合并科目处理
fix_assets_val = resolve(['fix_assets'], 'fix_assets_total')
cip_val = resolve(['cip'], 'cip_total')

assert abs(total_nca - sum_with_resolve(noncur_asset_items)) < 1
```

### 2.3 资产合计

```python
assert abs(total_assets - (total_cur_assets + total_nca)) < 1
```

---

## 三、资产负债表（BS）— 负债端

### 3.1 流动负债

```python
cur_liab_items = [
    'st_borr',              # 短期借款
    'trading_fl',           # 交易性金融负债
    'notes_payable',        # 应付票据       ← 可能合并
    'acct_payable',         # 应付账款       ← 可能合并
    'adv_receipts',         # 预收款项
    'contract_liab',        # 合同负债
    'payroll_payable',      # 应付职工薪酬
    'taxes_payable',        # 应交税费
    'oth_payable',          # 其他应付款     ← 可能只有 oth_pay_total
    'int_payable',          # 应付利息
    'div_payable',          # 应付股利
    'acc_exp',              # 预提费用
    'deferred_inc',         # 递延收益（流动）
    'st_bonds_payable',     # 应付短期债券
    'st_fin_payable',       # 应付短期融资款
    'hfs_sales',            # 持有待售负债
    'non_cur_liab_due_1y',  # 一年内到期的非流动负债
    'oth_cur_liab',         # 其他流动负债
    # 金融业：
    'cb_borr',              # 向中央银行借款
    'depos_ib_deposits',    # 吸收存款及同业存放
    'loan_oth_bank',        # 拆入资金
    'sold_for_repur_fa',    # 卖出回购金融资产款
    'comm_payable',         # 应付手续费及佣金
]

# 合并科目
notes_plus_ap = resolve(['notes_payable', 'acct_payable'], 'accounts_pay')
oth_payable_val = resolve(['oth_payable'], 'oth_pay_total')

assert abs(total_cur_liab - sum_with_resolve(cur_liab_items)) < 1
```

### 3.2 非流动负债

```python
noncur_liab_items = [
    'lt_borr',                 # 长期借款
    'bond_payable',            # 应付债券
    'lease_liab',              # 租赁负债
    'lt_payable',              # 长期应付款    ← 可能只有 long_pay_total
    'lt_payroll_payable',      # 长期应付职工薪酬
    'estimated_liab',          # 预计负债
    'defer_tax_liab',          # 递延所得税负债
    'defer_inc_non_cur_liab',  # 递延收益（非流动）
    'specific_payables',       # 专项应付款
    'oth_ncl',                 # 其他非流动负债
    # 金融业：
    'payable_to_reinsurer',    # 应付分保账款
    'rsrv_insur_cont',         # 保险合同准备金
]

# 合并科目
lt_payable_val = resolve(['lt_payable'], 'long_pay_total')

assert abs(total_ncl - sum_with_resolve(noncur_liab_items)) < 1
```

注意 `deferred_inc`（流动负债下的递延收益）和 `defer_inc_non_cur_liab`（非流动负债下的递延收益）：如果 Tushare 对某公司只返回其中一个字段，需要通过残差定位到底归属哪层。先按上面的分类跑，如果某层残差非零且约等于另一层的递延收益值，则调整归属。

### 3.3 负债合计

```python
assert abs(total_liab - (total_cur_liab + total_ncl)) < 1
```

---

## 四、资产负债表（BS）— 权益端

### 4.1 权益明细加总

```python
equity_calc = (
    total_share            # 股本
    + cap_rese             # 资本公积
    - treasury_share       # 减：库存股（Tushare存正数，公式中减去）
    + oth_comp_income      # 其他综合收益
    + special_rese         # 专项储备
    + surplus_rese         # 盈余公积
    + ordin_risk_reser     # 一般风险准备
    + undistr_porfit       # 未分配利润（Tushare拼写 porfit）
    + forex_differ         # 外币报表折算差额
    + oth_eqt_tools        # 其他权益工具
    + minority_int         # 少数股东权益
)
assert abs(total_hldr_eqy_inc_min_int - equity_calc) < 1
```

treasury_share 安全检查：
```python
if treasury_share != 0 and abs(residual - 2 * treasury_share) < 1:
    raise ValueError("treasury_share 符号异常，疑似存为负数")
```

### 4.2 归母 + 少数 = 合计

```python
assert abs(total_hldr_eqy_inc_min_int - (total_hldr_eqy_exc_min_int + minority_int)) < 1
```

### 4.3 终极配平

```python
assert abs(total_assets - total_liab - total_hldr_eqy_inc_min_int) < 1
assert abs(total_assets - total_liab_hldr_eqy) < 1
```

---

## 五、现金流量表（CF）

### 5.1 经营活动内部配平

```python
assert abs(n_cashflow_act - (c_inf_fr_operate_a - st_cash_out_act)) < 1
```

### 5.2 投资活动内部配平

```python
assert abs(n_cashflow_inv_act - (stot_inflows_inv_act - stot_out_inv_act)) < 1
```

### 5.3 筹资活动内部配平

```python
assert abs(n_cash_flows_fnc_act - (stot_cash_in_fnc_act - stot_cashout_fnc_act)) < 1
```

### 5.4 三大活动汇总

```python
assert abs(n_incr_cash_cash_equ - (
    n_cashflow_act + n_cashflow_inv_act + n_cash_flows_fnc_act + eff_fx_flu_cash
)) < 1
```

### 5.5 期初期末

```python
assert abs(c_cash_equ_end_period - (c_cash_equ_beg_period + n_incr_cash_cash_equ)) < 1
```

---

## 六、IS 补充校验

### 6.1 综合收益

```python
assert abs(t_compr_income - (n_income + oth_compr_income)) < 1
```

### 6.2 综合收益归属

```python
assert abs(t_compr_income - (compr_inc_attr_p + compr_inc_attr_m_s)) < 1
```

### 6.3 持续/终止经营（如果字段存在）

```python
if 'continued_net_profit' in present_fields:
    assert abs(n_income - (continued_net_profit + end_net_profit)) < 1
```

---

## 七、跨表一致性校验

### 7.1 IS 净利润 = CF 附注净利润

```python
# CF 间接法附注中的 net_profit 应等于 IS 中的 n_income
assert abs(cf_net_profit - is_n_income) < 1
```

注：CF 附注的字段名是 `net_profit`（在 cashflow 接口中），IS 的字段名是 `n_income`（在 income 接口中）。值应完全相等。

### 7.2 IS 财务费用 = CF 附注财务费用

```python
assert abs(cf_finan_exp - is_fin_exp) < 1
```

CF 附注的 `finan_exp` 应等于 IS 的 `fin_exp`。

### 7.3 CF 期末现金 vs BS 货币资金（soft check，仅 warning）

```python
diff = abs(c_cash_equ_end_period - money_cap)
if diff > 1:
    warn(f"CF期末现金 {c_cash_equ_end_period} ≠ BS货币资金 {money_cap}, 差 {diff}")
    # 这个差异是正常的：货币资金可能含受限资金，现金等价物口径不同
    # 仅警告，不报错
```

### 7.4 逐年连续性：上年 CF 期末 = 本年 CF 期初

```python
for y in years[1:]:
    prev_end = data[y-1]['c_cash_equ_end_period']
    curr_beg = data[y]['c_cash_equ_beg_period']
    assert abs(prev_end - curr_beg) < 1
```

---

## 八、字段分类声明

Tushare 返回的字段中混有三类，agent 必须区分：

### 8.1 不参与任何加总校验的衍生字段

以下字段是 Tushare 自行计算或非报表原始科目，**不得出现在任何 assert 公式的求和项中**（但保留在 CSV 输出里）：

**income 接口：**
- `basic_eps` — 基本每股收益（衍生）
- `diluted_eps` — 稀释每股收益（衍生）
- `ebit` — 息税前利润（Tushare 自算）
- `ebitda` — 息税折旧摊销前利润（Tushare 自算）
- `undist_profit` — 年初未分配利润（属于 BS，出现在 IS 接口中是历史遗留）
- `distable_profit` — 可分配利润（衍生）
- `insurance_exp` — 保险业务支出（金融企业专用，comp_type=1 已过滤掉）
- `update_flag` — 更新标志（元数据）

**balancesheet 接口：**
- `update_flag` — 元数据
- `invest_loss_unconf` — 未确认的投资损失（几乎已废弃）

**cashflow 接口：**
- `free_cashflow` — 企业自由现金流（Tushare 自算）
- `update_flag` — 元数据

### 8.2 子项（已包含在父项中，不重复加）

| 子项 | 父项 | 说明 |
|------|------|------|
| `ass_invest_income` | `invest_income` | 对联营/合营投资收益 |
| `amodcost_fin_assets` | `invest_income` | 摊余成本金融资产终止确认收益 |
| `fin_exp_int_exp` | `fin_exp` | 财务费用中的利息费用 |
| `fin_exp_int_inc` | `fin_exp` | 财务费用中的利息收入 |
| `nca_disploss` | `non_oper_exp` | 非流动资产处置净损失（旧准则列示方式） |
| `incl_dvd_profit_paid_sc_ms` | `c_pay_dist_dpcp_int_exp` | 子公司付少数股东股利 |
| `incl_cash_rec_saims` | `c_recp_cap_contrib` | 子公司吸收少数股东投资 |

### 8.3 合并科目（与拆分科目二选一，不同时加）

见第九节 resolve 逻辑。

---

## 九、合并/拆分科目处理

### 核心逻辑

```python
def resolve(split_fields: list[str], combo_field: str, row: dict, present_fields: set) -> float:
    """
    split_fields: 拆分科目列表，如 ['notes_receiv', 'accounts_receiv']
    combo_field:  合并科目，如 'accounts_receiv_bill'
    row:          当年全部字段值 dict
    present_fields: 该公司该年在 raw_tushare 中实际出现过的字段名集合
    
    逻辑：
    1. 如果全部 split_fields 都在 present_fields 中 → 用拆分项求和
    2. 否则如果 combo_field 在 present_fields 中 → 用合并项
    3. 否则 → 0
    
    关键：区分"字段存在但值为0"和"字段根本不存在"。
    """
```

### 已知合并/拆分对

| 合并科目 | 拆分科目 | 所在位置 |
|---|---|---|
| `accounts_receiv_bill` | `notes_receiv` + `accounts_receiv` | 流动资产 |
| `accounts_pay` | `notes_payable` + `acct_payable` | 流动负债 |
| `oth_rcv_total` | `oth_receiv` | 流动资产 |
| `oth_pay_total` | `oth_payable` | 流动负债 |
| `fix_assets_total` | `fix_assets` | 非流动资产 |
| `cip_total` | `cip` | 非流动资产 |
| `long_pay_total` | `lt_payable` | 非流动负债 |

### present_fields 的构建

```python
# 在 EAV → 宽表 pivot 之前，先记录每年实际出现了哪些字段
present = df_raw.groupby('year')['field'].apply(set).to_dict()
# present[2024] = {'revenue', 'oper_cost', 'accounts_receiv_bill', ...}
```

---

## 十、Sanity Checks（软校验，仅 warning，不报错）

这些不影响配平，但能抓住数据异常：

```python
# 10.1 方向合理性
if revenue < 0: warn("营业收入为负")
if total_assets < 0: warn("总资产为负")
if n_income_attr_p != 0 and basic_eps != 0:
    # EPS 方向应与归母净利润一致
    if (n_income_attr_p > 0) != (basic_eps > 0):
        warn("EPS 与归母净利润方向不一致")

# 10.2 量级合理性（单位：百万元）
if total_assets > 10_000_000: warn(f"总资产 {total_assets}M > 10万亿，请确认")
if abs(operate_profit) > total_revenue and total_revenue > 0:
    warn("营业利润绝对值大于营业收入")

# 10.3 BS 附注：固定资产折旧 ≤ 期初固定资产
if depr_fa_coga_dpba > fix_assets * 1.5:
    warn("折旧额超过固定资产净值的150%")

# 10.4 毛利率范围
if revenue > 0:
    gpm = (revenue - oper_cost) / revenue
    if gpm < -0.5 or gpm > 1.0:
        warn(f"毛利率 {gpm:.1%} 超出合理范围")
```

---

## 十一、校验公式汇总

### Hard checks（残差 < 1，fail 则报错）

| 编号 | 报表 | 校验内容 |
|------|------|----------|
| 1.1 | IS | 营业总成本 = Σ费用项 |
| 1.2 | IS | 营业利润 = revenue - total_cogs + Σ收益项 |
| 1.3 | IS | 利润总额 = 营业利润 + 营业外净 |
| 1.4 | IS | 净利润 = 利润总额 - 所得税 |
| 1.5 | IS | 净利润 = 归母 + 少数 |
| 1.6 | IS | 营业总收入 = 营业收入（一般工商业） |
| 2.1 | BS | 流动资产合计 = Σ流动资产明细 |
| 2.2 | BS | 非流动资产合计 = Σ非流动资产明细 |
| 2.3 | BS | 总资产 = 流动 + 非流动 |
| 3.1 | BS | 流动负债合计 = Σ流动负债明细 |
| 3.2 | BS | 非流动负债合计 = Σ非流动负债明细 |
| 3.3 | BS | 总负债 = 流动 + 非流动 |
| 4.1 | BS | 权益合计 = Σ权益明细 |
| 4.2 | BS | 权益合计 = 归母 + 少数 |
| 4.3 | BS | **总资产 = 总负债 + 权益合计** |
| 5.1 | CF | CFO = 流入小计 - 流出小计 |
| 5.2 | CF | CFI = 流入小计 - 流出小计 |
| 5.3 | CF | CFF = 流入小计 - 流出小计 |
| 5.4 | CF | 现金净增 = CFO + CFI + CFF + FX |
| 5.5 | CF | 期末 = 期初 + 净增 |
| 6.1 | IS | 综合收益 = 净利润 + 其他综合收益 |
| 6.2 | IS | 综合收益 = 归母综合 + 少数综合 |
| 6.3 | IS | 净利润 = 持续经营 + 终止经营（如有） |
| 7.1 | 跨表 | IS 净利润 = CF 附注净利润 |
| 7.2 | 跨表 | IS 财务费用 = CF 附注财务费用 |
| 7.4 | 跨表 | 上年 CF 期末现金 = 本年 CF 期初现金 |

### Soft checks（仅 warning）

| 编号 | 内容 |
|------|------|
| 7.3 | CF 期末现金 vs BS 货币资金（口径差异正常） |
| 10.1 | 收入/资产方向合理性 |
| 10.2 | 量级合理性 |
| 10.3 | 折旧 vs 固定资产 |
| 10.4 | 毛利率范围 |

共 **26 条 hard + 5 条 soft = 31 条**校验。

---

## 十二、实现要求

```python
def clean(db_path: str, ticker: str) -> pd.DataFrame:
    """
    1. 从 raw_tushare 读全部字段（income + balancesheet + cashflow）
    2. 过滤 report_type='1', comp_type='1'
       同 end_date 取 f_ann_date 最大者
    3. 构建 present_fields（每年实际出现了哪些字段名）
    4. Pivot 为宽表，缺失值填 0
    5. 处理合并/拆分科目（resolve 逻辑）
    6. 逐年运行 26 条 hard check
       - 任何 fail → 打印该公式各项原始值和残差，报错停止
    7. 逐年运行 5 条 soft check
       - 仅 warning，不阻止输出
    8. 全部 hard check pass → 输出 CSV（全部字段，不裁剪）
    """
```

## 验收标准

安克创新 300866.SZ，全部有数据的年份：
- 26 条 hard check 全部 pass（残差 < 1）
- soft check 的 warning 逐条确认合理
- CSV 包含 Tushare 返回的全部字段，不裁剪
