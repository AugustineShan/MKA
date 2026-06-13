# YAML2 和 calc.py 的关系

## 一句话

**YAML2 是 calc.py 的输入配置文件。calc.py 按固定顺序算三表，每一步都从 YAML2 读一个参数。defaults_gen 的工作就是把这些参数全部算好写进 YAML2。**

## calc.py 的计算步骤 → 每一步需要 YAML2 的什么

想象 calc.py 是一个从上往下执行的计算器。它对每个预测年份（比如 2025-2032）做以下计算，每一步从 YAML2 读一个参数：

### 第一步：算利润表（IS）

```
revenue = 去年revenue × (1 + revenue_yoy)     ← 读 YAML2 的 revenue 和 revenue_yoy
cogs = revenue × (1 - gpm)                     ← 读 YAML2 的 gpm
gross_profit = revenue - cogs

tax_surcharge = revenue × biz_tax_surchg_rate   ← 读 YAML2 的 biz_tax_surchg_rate
selling = revenue × sell_exp_rate               ← 读 YAML2 的 sell_exp_rate
admin = revenue × admin_exp_rate                ← 读 YAML2 的 admin_exp_rate
rnd = revenue × rd_exp_rate                     ← 读 YAML2 的 rd_exp_rate
fin_exp = 直接用绝对值                           ← 读 YAML2 的 fin_exp

impairment = 按原值代数并入营业利润    ← 读 YAML2 的 assets_impair_loss + credit_impa_loss + oth_impair_loss_assets
                                         负值=损失（侵蚀利润），正值=收益/ reversal；不计入 total_cogs
other_income = 直接用绝对值                      ← 读 YAML2 的 oth_income
invest_income = 直接用绝对值                     ← 读 YAML2 的 invest_income
fv_change = 直接用绝对值                         ← 读 YAML2 的 fv_value_chg_gain
...（其他below-OP项同理）

operating_profit = gross_profit - 各项费用 + 各项收益
total_profit = operating_profit + non_oper_net
income_tax = total_profit × effective_tax_rate   ← 读 YAML2 的 effective_tax_rate
net_income = total_profit - income_tax
minority = net_income × minority_ratio           ← 读 YAML2 的 minority_ratio
net_income_parent = net_income - minority
```

**IS 全部算完。用到了大约 20 个 YAML2 参数。**

### 第二步：算资产负债表（BS）

IS 算完后，用 IS 的输出（revenue、cogs、net_income）驱动 BS：

```
# 资产端——用周转天数或占比从 revenue/cogs 推算
accounts_receiv = revenue × ar_days / 365        ← 读 YAML2 的 ar_days
inventories = cogs × inv_days / 365              ← 读 YAML2 的 inv_days
acct_payable = cogs × ap_days / 365              ← 读 YAML2 的 ap_days
prepayment = revenue × prepayment_pct            ← 读 YAML2 的 prepayment_pct
...（其他WC项同理）

# 固定资产——滚动
capex = revenue × capex_pct                       ← 读 YAML2 的 capex_pct
depreciation = 上年fix_assets × depr_rate         ← 读 YAML2 的 depr_rate
fix_assets = 上年fix_assets + capex - depreciation

# 其他所有BS科目——直接用绝对值（不变）
goodwill = 去年的goodwill                          ← 读 YAML2 的 bs_carryforward.goodwill
produc_bio_assets = 去年的值                       ← 读 YAML2 的 bs_carryforward.produc_bio_assets
lt_eqt_invest = 去年的值                           ← 读 YAML2 的 bs_carryforward.lt_eqt_invest
...（所有非零BS明细项都在 bs_carryforward 里）

# 权益——滚动
retained_earnings = 上年RE + net_income_parent - dividends
dividends = net_income_parent × dividend_payout    ← 读 YAML2 的 dividend_payout
minority_int = 上年minority_int + minority_gain

# 配平——用 plug 项倒挤
if plug == 'cash':                                 ← 读 YAML2 的 plug
    cash = 总负债 + 总权益 - 所有其他资产
elif plug == 'st_borr':
    st_borr = 总资产 - 总权益 - 所有其他负债
```

**BS 全部算完。用到了大约 60 个 YAML2 参数（主要是 bs_carryforward 里的各个科目绝对值）。**

### 第三步：算现金流量表（CF）

从 IS 和 BS 的变动推导，不需要额外的 YAML2 参数：

```
CFO = net_income + depreciation + amortization + Δ各WC项
CFI = -capex
CFF = Δ借款 - dividends
net_cash_change = CFO + CFI + CFF
```

### 第四步：DCF 估值

```
NOPAT = EBIT × (1 - tax_rate)
FCFF = NOPAT + DA - capex - ΔNWC
terminal_value = FCFF_last × (1+g) / (WACC-g)    ← 读 YAML2 的 wacc 和 terminal_growth
EV = Σ discounted FCFF + discounted TV
equity_value = EV - net_debt                       ← 读 YAML2 的 net_debt
per_share = equity_value / total_shares            ← 读 YAML2 的 total_shares
```

## 所以 defaults_gen 要做什么？

**defaults_gen 的工作 = 从 clean_annual 表的最新一年数据中，把上面每一步需要的参数全部算出来，写进 YAML2。**

就这么简单：
- calc.py 需要 `gpm` → defaults_gen 从 clean 数据算 `gpm = 1 - oper_cost / revenue`，写进 YAML2
- calc.py 需要 `ar_days` → defaults_gen 算 `ar_days = accounts_receiv / revenue × 365`，写进 YAML2
- calc.py 需要 `goodwill` → defaults_gen 直接读 clean 数据的 `goodwill` 值，写进 YAML2
- ...对每个参数都如此

**defaults_gen 不需要知道 calc.py 的公式是什么。它只需要知道 calc.py 要读哪些参数名、每个参数从 clean 数据的哪些字段算出来。** 这就是 defaults_gen_spec_v3.md 里那张计算规则表的全部内容。

## 验证方法

defaults_gen 生成 YAML2 后，把它喂给 calc.py：
- forecast 第一年的 revenue 应该 ≈ base_year 的 revenue（因为 yoy=0）
- forecast 第一年的 net_income 应该 ≈ base_year 的 net_income（因为所有参数 carry_forward）
- BS 必须配平：total_assets = total_liab + total_equity
- 如果不平 → 要么 defaults_gen 漏了某个 BS 参数，要么 calc.py 公式有 bug
