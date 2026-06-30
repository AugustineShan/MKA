# TuShare 官方源财务 Schema

> 生成日期：2026-06-16
> 作用：锁定官方 TuShare 财务接口的输入参数和输出 schema，作为 `raw_tushare` 与 clean 层之间的官方字段参考。
> 注意：本文档不替代 `docs/数据格式参考.md`；后者仍是 `clean_annual` / `clean_quarterly` 的稳定交付契约。

## 来源与约束

- 主来源：官方 skill 仓库 `waditu-tushare/skills` 导出的本地 Markdown：`D:\MKA\TushareOfficialAPIMD\`。
- 线上对应文档：
  - `income` / doc_id=33: https://tushare.pro/wctapi/documents/33.md
  - `balancesheet` / doc_id=36: https://tushare.pro/wctapi/documents/36.md
  - `cashflow` / doc_id=44: https://tushare.pro/wctapi/documents/44.md
- `raw_tushare` 必须保持为官方返回的原始镜像；任何补齐、符号调整、口径映射都应在 clean/reconciler 层完成。
- 不允许为单一公司、单一股票代码或单一年度做 hardcode 适配。
- 本文档将“输入参数”和“输出字段”分开；只有输出字段应出现在 `raw_tushare` 记录的 payload 中。

## 总览

| endpoint | 官方文件 | doc_id | 输入参数 | 输出字段 | 报表字段 | 元数据字段 |
|---|---|---:|---:|---:|---:|---:|
| `income` | `income.md` | 33 | 8 | 94 | 86 | 8 |
| `balancesheet` | `balancesheet.md` | 36 | 7 | 158 | 150 | 8 |
| `cashflow` | `cashflow.md` | 44 | 9 | 97 | 89 | 8 |

## 字段分类规则

- 元数据字段：`ts_code`、`ann_date`、`f_ann_date`、`end_date`、`report_type`、`comp_type`、`end_type`、`update_flag`。
- 其余输出字段视为报表字段，但不等于 clean 层必须原样采用的科目。
- `start_date`、`period`、`is_calc` 等在“输入参数”中出现的名称，不应被当作输出字段校验。

## 利润表 `income`

- 本地官方文件: `D:\MKA\TushareOfficialAPIMD\income.md`
- 线上官方文档: https://tushare.pro/wctapi/documents/33.md
- 输入参数: 8
- 输出字段: 94

### 输入参数（取数参数，非 raw 输出字段）

| 名称 | 类型 | 必选 | 描述 |
|---|---|---|---|
| `ts_code` | `str` | Y | 股票代码 |
| `ann_date` | `str` | N | 公告日期（YYYYMMDD格式，下同） |
| `f_ann_date` | `str` | N | 实际公告日期 |
| `start_date` | `str` | N | 公告日开始日期 |
| `end_date` | `str` | N | 公告日结束日期 |
| `period` | `str` | N | 报告期(每个季度最后一天的日期，比如20171231表示年报，20170630半年报，20170930三季报) |
| `report_type` | `str` | N | 报告类型，参考文档最下方说明 |
| `comp_type` | `str` | N | 公司类型（1一般工商业2银行3保险4证券） |

### 输出字段（raw_tushare payload schema）

| 名称 | 类型 | 默认显示 | 分类 | 描述 |
|---|---|---|---|---|
| `ts_code` | `str` | Y | 元数据 | TS代码 |
| `ann_date` | `str` | Y | 元数据 | 公告日期 |
| `f_ann_date` | `str` | Y | 元数据 | 实际公告日期 |
| `end_date` | `str` | Y | 元数据 | 报告期 |
| `report_type` | `str` | Y | 元数据 | 报告类型 见底部表 |
| `comp_type` | `str` | Y | 元数据 | 公司类型(1一般工商业2银行3保险4证券) |
| `end_type` | `str` | Y | 元数据 | 报告期类型 |
| `basic_eps` | `float` | Y | 报表字段 | 基本每股收益 |
| `diluted_eps` | `float` | Y | 报表字段 | 稀释每股收益 |
| `total_revenue` | `float` | Y | 报表字段 | 营业总收入 |
| `revenue` | `float` | Y | 报表字段 | 营业收入 |
| `int_income` | `float` | Y | 报表字段 | 利息收入 |
| `prem_earned` | `float` | Y | 报表字段 | 已赚保费 |
| `comm_income` | `float` | Y | 报表字段 | 手续费及佣金收入 |
| `n_commis_income` | `float` | Y | 报表字段 | 手续费及佣金净收入 |
| `n_oth_income` | `float` | Y | 报表字段 | 其他经营净收益 |
| `n_oth_b_income` | `float` | Y | 报表字段 | 加:其他业务净收益 |
| `prem_income` | `float` | Y | 报表字段 | 保险业务收入 |
| `out_prem` | `float` | Y | 报表字段 | 减:分出保费 |
| `une_prem_reser` | `float` | Y | 报表字段 | 提取未到期责任准备金 |
| `reins_income` | `float` | Y | 报表字段 | 其中:分保费收入 |
| `n_sec_tb_income` | `float` | Y | 报表字段 | 代理买卖证券业务净收入 |
| `n_sec_uw_income` | `float` | Y | 报表字段 | 证券承销业务净收入 |
| `n_asset_mg_income` | `float` | Y | 报表字段 | 受托客户资产管理业务净收入 |
| `oth_b_income` | `float` | Y | 报表字段 | 其他业务收入 |
| `fv_value_chg_gain` | `float` | Y | 报表字段 | 加:公允价值变动净收益 |
| `invest_income` | `float` | Y | 报表字段 | 加:投资净收益 |
| `ass_invest_income` | `float` | Y | 报表字段 | 其中:对联营企业和合营企业的投资收益 |
| `forex_gain` | `float` | Y | 报表字段 | 加:汇兑净收益 |
| `total_cogs` | `float` | Y | 报表字段 | 营业总成本 |
| `oper_cost` | `float` | Y | 报表字段 | 减:营业成本 |
| `int_exp` | `float` | Y | 报表字段 | 减:利息支出 |
| `comm_exp` | `float` | Y | 报表字段 | 减:手续费及佣金支出 |
| `biz_tax_surchg` | `float` | Y | 报表字段 | 减:营业税金及附加 |
| `sell_exp` | `float` | Y | 报表字段 | 减:销售费用 |
| `admin_exp` | `float` | Y | 报表字段 | 减:管理费用 |
| `fin_exp` | `float` | Y | 报表字段 | 减:财务费用 |
| `assets_impair_loss` | `float` | Y | 报表字段 | 减:资产减值损失 |
| `prem_refund` | `float` | Y | 报表字段 | 退保金 |
| `compens_payout` | `float` | Y | 报表字段 | 赔付总支出 |
| `reser_insur_liab` | `float` | Y | 报表字段 | 提取保险责任准备金 |
| `div_payt` | `float` | Y | 报表字段 | 保户红利支出 |
| `reins_exp` | `float` | Y | 报表字段 | 分保费用 |
| `oper_exp` | `float` | Y | 报表字段 | 营业支出 |
| `compens_payout_refu` | `float` | Y | 报表字段 | 减:摊回赔付支出 |
| `insur_reser_refu` | `float` | Y | 报表字段 | 减:摊回保险责任准备金 |
| `reins_cost_refund` | `float` | Y | 报表字段 | 减:摊回分保费用 |
| `other_bus_cost` | `float` | Y | 报表字段 | 其他业务成本 |
| `operate_profit` | `float` | Y | 报表字段 | 营业利润 |
| `non_oper_income` | `float` | Y | 报表字段 | 加:营业外收入 |
| `non_oper_exp` | `float` | Y | 报表字段 | 减:营业外支出 |
| `nca_disploss` | `float` | Y | 报表字段 | 其中:减:非流动资产处置净损失 |
| `total_profit` | `float` | Y | 报表字段 | 利润总额 |
| `income_tax` | `float` | Y | 报表字段 | 所得税费用 |
| `n_income` | `float` | Y | 报表字段 | 净利润(含少数股东损益) |
| `n_income_attr_p` | `float` | Y | 报表字段 | 净利润(不含少数股东损益) |
| `minority_gain` | `float` | Y | 报表字段 | 少数股东损益 |
| `oth_compr_income` | `float` | Y | 报表字段 | 其他综合收益 |
| `t_compr_income` | `float` | Y | 报表字段 | 综合收益总额 |
| `compr_inc_attr_p` | `float` | Y | 报表字段 | 归属于母公司(或股东)的综合收益总额 |
| `compr_inc_attr_m_s` | `float` | Y | 报表字段 | 归属于少数股东的综合收益总额 |
| `ebit` | `float` | Y | 报表字段 | 息税前利润 |
| `ebitda` | `float` | Y | 报表字段 | 息税折旧摊销前利润 |
| `insurance_exp` | `float` | Y | 报表字段 | 保险业务支出 |
| `undist_profit` | `float` | Y | 报表字段 | 年初未分配利润 |
| `distable_profit` | `float` | Y | 报表字段 | 可分配利润 |
| `rd_exp` | `float` | Y | 报表字段 | 研发费用 |
| `fin_exp_int_exp` | `float` | Y | 报表字段 | 财务费用:利息费用 |
| `fin_exp_int_inc` | `float` | Y | 报表字段 | 财务费用:利息收入 |
| `transfer_surplus_rese` | `float` | Y | 报表字段 | 盈余公积转入 |
| `transfer_housing_imprest` | `float` | Y | 报表字段 | 住房周转金转入 |
| `transfer_oth` | `float` | Y | 报表字段 | 其他转入 |
| `adj_lossgain` | `float` | Y | 报表字段 | 调整以前年度损益 |
| `withdra_legal_surplus` | `float` | Y | 报表字段 | 提取法定盈余公积 |
| `withdra_legal_pubfund` | `float` | Y | 报表字段 | 提取法定公益金 |
| `withdra_biz_devfund` | `float` | Y | 报表字段 | 提取企业发展基金 |
| `withdra_rese_fund` | `float` | Y | 报表字段 | 提取储备基金 |
| `withdra_oth_ersu` | `float` | Y | 报表字段 | 提取任意盈余公积金 |
| `workers_welfare` | `float` | Y | 报表字段 | 职工奖金福利 |
| `distr_profit_shrhder` | `float` | Y | 报表字段 | 可供股东分配的利润 |
| `prfshare_payable_dvd` | `float` | Y | 报表字段 | 应付优先股股利 |
| `comshare_payable_dvd` | `float` | Y | 报表字段 | 应付普通股股利 |
| `capit_comstock_div` | `float` | Y | 报表字段 | 转作股本的普通股股利 |
| `net_after_nr_lp_correct` | `float` | N | 报表字段 | 扣除非经常性损益后的净利润（更正前） |
| `credit_impa_loss` | `float` | N | 报表字段 | 信用减值损失 |
| `net_expo_hedging_benefits` | `float` | N | 报表字段 | 净敞口套期收益 |
| `oth_impair_loss_assets` | `float` | N | 报表字段 | 其他资产减值损失 |
| `total_opcost` | `float` | N | 报表字段 | 营业总成本（二） |
| `amodcost_fin_assets` | `float` | N | 报表字段 | 以摊余成本计量的金融资产终止确认收益 |
| `oth_income` | `float` | N | 报表字段 | 其他收益 |
| `asset_disp_income` | `float` | N | 报表字段 | 资产处置收益 |
| `continued_net_profit` | `float` | N | 报表字段 | 持续经营净利润 |
| `end_net_profit` | `float` | N | 报表字段 | 终止经营净利润 |
| `update_flag` | `str` | Y | 元数据 | 更新标识 |

## 资产负债表 `balancesheet`

- 本地官方文件: `D:\MKA\TushareOfficialAPIMD\balancesheet.md`
- 线上官方文档: https://tushare.pro/wctapi/documents/36.md
- 输入参数: 7
- 输出字段: 158

### 输入参数（取数参数，非 raw 输出字段）

| 名称 | 类型 | 必选 | 描述 |
|---|---|---|---|
| `ts_code` | `str` | Y | 股票代码 |
| `ann_date` | `str` | N | 公告日期(YYYYMMDD格式，下同) |
| `start_date` | `str` | N | 公告日开始日期 |
| `end_date` | `str` | N | 公告日结束日期 |
| `period` | `str` | N | 报告期(每个季度最后一天的日期，比如20171231表示年报，20170630半年报，20170930三季报) |
| `report_type` | `str` | N | 报告类型：见下方详细说明 |
| `comp_type` | `str` | N | 公司类型：1一般工商业 2银行 3保险 4证券 |

### 输出字段（raw_tushare payload schema）

| 名称 | 类型 | 默认显示 | 分类 | 描述 |
|---|---|---|---|---|
| `ts_code` | `str` | Y | 元数据 | TS股票代码 |
| `ann_date` | `str` | Y | 元数据 | 公告日期 |
| `f_ann_date` | `str` | Y | 元数据 | 实际公告日期 |
| `end_date` | `str` | Y | 元数据 | 报告期 |
| `report_type` | `str` | Y | 元数据 | 报表类型 |
| `comp_type` | `str` | Y | 元数据 | 公司类型(1一般工商业2银行3保险4证券) |
| `end_type` | `str` | Y | 元数据 | 报告期类型 |
| `total_share` | `float` | Y | 报表字段 | 期末总股本 |
| `cap_rese` | `float` | Y | 报表字段 | 资本公积金 |
| `undistr_porfit` | `float` | Y | 报表字段 | 未分配利润 |
| `surplus_rese` | `float` | Y | 报表字段 | 盈余公积金 |
| `special_rese` | `float` | Y | 报表字段 | 专项储备 |
| `money_cap` | `float` | Y | 报表字段 | 货币资金 |
| `trad_asset` | `float` | Y | 报表字段 | 交易性金融资产 |
| `notes_receiv` | `float` | Y | 报表字段 | 应收票据 |
| `accounts_receiv` | `float` | Y | 报表字段 | 应收账款 |
| `oth_receiv` | `float` | Y | 报表字段 | 其他应收款 |
| `prepayment` | `float` | Y | 报表字段 | 预付款项 |
| `div_receiv` | `float` | Y | 报表字段 | 应收股利 |
| `int_receiv` | `float` | Y | 报表字段 | 应收利息 |
| `inventories` | `float` | Y | 报表字段 | 存货 |
| `amor_exp` | `float` | Y | 报表字段 | 待摊费用 |
| `nca_within_1y` | `float` | Y | 报表字段 | 一年内到期的非流动资产 |
| `sett_rsrv` | `float` | Y | 报表字段 | 结算备付金 |
| `loanto_oth_bank_fi` | `float` | Y | 报表字段 | 拆出资金 |
| `premium_receiv` | `float` | Y | 报表字段 | 应收保费 |
| `reinsur_receiv` | `float` | Y | 报表字段 | 应收分保账款 |
| `reinsur_res_receiv` | `float` | Y | 报表字段 | 应收分保合同准备金 |
| `pur_resale_fa` | `float` | Y | 报表字段 | 买入返售金融资产 |
| `oth_cur_assets` | `float` | Y | 报表字段 | 其他流动资产 |
| `total_cur_assets` | `float` | Y | 报表字段 | 流动资产合计 |
| `fa_avail_for_sale` | `float` | Y | 报表字段 | 可供出售金融资产 |
| `htm_invest` | `float` | Y | 报表字段 | 持有至到期投资 |
| `lt_eqt_invest` | `float` | Y | 报表字段 | 长期股权投资 |
| `invest_real_estate` | `float` | Y | 报表字段 | 投资性房地产 |
| `time_deposits` | `float` | Y | 报表字段 | 定期存款 |
| `oth_assets` | `float` | Y | 报表字段 | 其他资产 |
| `lt_rec` | `float` | Y | 报表字段 | 长期应收款 |
| `fix_assets` | `float` | Y | 报表字段 | 固定资产 |
| `cip` | `float` | Y | 报表字段 | 在建工程 |
| `const_materials` | `float` | Y | 报表字段 | 工程物资 |
| `fixed_assets_disp` | `float` | Y | 报表字段 | 固定资产清理 |
| `produc_bio_assets` | `float` | Y | 报表字段 | 生产性生物资产 |
| `oil_and_gas_assets` | `float` | Y | 报表字段 | 油气资产 |
| `intan_assets` | `float` | Y | 报表字段 | 无形资产 |
| `r_and_d` | `float` | Y | 报表字段 | 研发支出 |
| `goodwill` | `float` | Y | 报表字段 | 商誉 |
| `lt_amor_exp` | `float` | Y | 报表字段 | 长期待摊费用 |
| `defer_tax_assets` | `float` | Y | 报表字段 | 递延所得税资产 |
| `decr_in_disbur` | `float` | Y | 报表字段 | 发放贷款及垫款 |
| `oth_nca` | `float` | Y | 报表字段 | 其他非流动资产 |
| `total_nca` | `float` | Y | 报表字段 | 非流动资产合计 |
| `cash_reser_cb` | `float` | Y | 报表字段 | 现金及存放中央银行款项 |
| `depos_in_oth_bfi` | `float` | Y | 报表字段 | 存放同业和其它金融机构款项 |
| `prec_metals` | `float` | Y | 报表字段 | 贵金属 |
| `deriv_assets` | `float` | Y | 报表字段 | 衍生金融资产 |
| `rr_reins_une_prem` | `float` | Y | 报表字段 | 应收分保未到期责任准备金 |
| `rr_reins_outstd_cla` | `float` | Y | 报表字段 | 应收分保未决赔款准备金 |
| `rr_reins_lins_liab` | `float` | Y | 报表字段 | 应收分保寿险责任准备金 |
| `rr_reins_lthins_liab` | `float` | Y | 报表字段 | 应收分保长期健康险责任准备金 |
| `refund_depos` | `float` | Y | 报表字段 | 存出保证金 |
| `ph_pledge_loans` | `float` | Y | 报表字段 | 保户质押贷款 |
| `refund_cap_depos` | `float` | Y | 报表字段 | 存出资本保证金 |
| `indep_acct_assets` | `float` | Y | 报表字段 | 独立账户资产 |
| `client_depos` | `float` | Y | 报表字段 | 其中：客户资金存款 |
| `client_prov` | `float` | Y | 报表字段 | 其中：客户备付金 |
| `transac_seat_fee` | `float` | Y | 报表字段 | 其中:交易席位费 |
| `invest_as_receiv` | `float` | Y | 报表字段 | 应收款项类投资 |
| `total_assets` | `float` | Y | 报表字段 | 资产总计 |
| `lt_borr` | `float` | Y | 报表字段 | 长期借款 |
| `st_borr` | `float` | Y | 报表字段 | 短期借款 |
| `cb_borr` | `float` | Y | 报表字段 | 向中央银行借款 |
| `depos_ib_deposits` | `float` | Y | 报表字段 | 吸收存款及同业存放 |
| `loan_oth_bank` | `float` | Y | 报表字段 | 拆入资金 |
| `trading_fl` | `float` | Y | 报表字段 | 交易性金融负债 |
| `notes_payable` | `float` | Y | 报表字段 | 应付票据 |
| `acct_payable` | `float` | Y | 报表字段 | 应付账款 |
| `adv_receipts` | `float` | Y | 报表字段 | 预收款项 |
| `sold_for_repur_fa` | `float` | Y | 报表字段 | 卖出回购金融资产款 |
| `comm_payable` | `float` | Y | 报表字段 | 应付手续费及佣金 |
| `payroll_payable` | `float` | Y | 报表字段 | 应付职工薪酬 |
| `taxes_payable` | `float` | Y | 报表字段 | 应交税费 |
| `int_payable` | `float` | Y | 报表字段 | 应付利息 |
| `div_payable` | `float` | Y | 报表字段 | 应付股利 |
| `oth_payable` | `float` | Y | 报表字段 | 其他应付款 |
| `acc_exp` | `float` | Y | 报表字段 | 预提费用 |
| `deferred_inc` | `float` | Y | 报表字段 | 递延收益 |
| `st_bonds_payable` | `float` | Y | 报表字段 | 应付短期债券 |
| `payable_to_reinsurer` | `float` | Y | 报表字段 | 应付分保账款 |
| `rsrv_insur_cont` | `float` | Y | 报表字段 | 保险合同准备金 |
| `acting_trading_sec` | `float` | Y | 报表字段 | 代理买卖证券款 |
| `acting_uw_sec` | `float` | Y | 报表字段 | 代理承销证券款 |
| `non_cur_liab_due_1y` | `float` | Y | 报表字段 | 一年内到期的非流动负债 |
| `oth_cur_liab` | `float` | Y | 报表字段 | 其他流动负债 |
| `total_cur_liab` | `float` | Y | 报表字段 | 流动负债合计 |
| `bond_payable` | `float` | Y | 报表字段 | 应付债券 |
| `lt_payable` | `float` | Y | 报表字段 | 长期应付款 |
| `specific_payables` | `float` | Y | 报表字段 | 专项应付款 |
| `estimated_liab` | `float` | Y | 报表字段 | 预计负债 |
| `defer_tax_liab` | `float` | Y | 报表字段 | 递延所得税负债 |
| `defer_inc_non_cur_liab` | `float` | Y | 报表字段 | 递延收益-非流动负债 |
| `oth_ncl` | `float` | Y | 报表字段 | 其他非流动负债 |
| `total_ncl` | `float` | Y | 报表字段 | 非流动负债合计 |
| `depos_oth_bfi` | `float` | Y | 报表字段 | 同业和其它金融机构存放款项 |
| `deriv_liab` | `float` | Y | 报表字段 | 衍生金融负债 |
| `depos` | `float` | Y | 报表字段 | 吸收存款 |
| `agency_bus_liab` | `float` | Y | 报表字段 | 代理业务负债 |
| `oth_liab` | `float` | Y | 报表字段 | 其他负债 |
| `prem_receiv_adva` | `float` | Y | 报表字段 | 预收保费 |
| `depos_received` | `float` | Y | 报表字段 | 存入保证金 |
| `ph_invest` | `float` | Y | 报表字段 | 保户储金及投资款 |
| `reser_une_prem` | `float` | Y | 报表字段 | 未到期责任准备金 |
| `reser_outstd_claims` | `float` | Y | 报表字段 | 未决赔款准备金 |
| `reser_lins_liab` | `float` | Y | 报表字段 | 寿险责任准备金 |
| `reser_lthins_liab` | `float` | Y | 报表字段 | 长期健康险责任准备金 |
| `indept_acc_liab` | `float` | Y | 报表字段 | 独立账户负债 |
| `pledge_borr` | `float` | Y | 报表字段 | 其中:质押借款 |
| `indem_payable` | `float` | Y | 报表字段 | 应付赔付款 |
| `policy_div_payable` | `float` | Y | 报表字段 | 应付保单红利 |
| `total_liab` | `float` | Y | 报表字段 | 负债合计 |
| `treasury_share` | `float` | Y | 报表字段 | 减:库存股 |
| `ordin_risk_reser` | `float` | Y | 报表字段 | 一般风险准备 |
| `forex_differ` | `float` | Y | 报表字段 | 外币报表折算差额 |
| `invest_loss_unconf` | `float` | Y | 报表字段 | 未确认的投资损失 |
| `minority_int` | `float` | Y | 报表字段 | 少数股东权益 |
| `total_hldr_eqy_exc_min_int` | `float` | Y | 报表字段 | 股东权益合计(不含少数股东权益) |
| `total_hldr_eqy_inc_min_int` | `float` | Y | 报表字段 | 股东权益合计(含少数股东权益) |
| `total_liab_hldr_eqy` | `float` | Y | 报表字段 | 负债及股东权益总计 |
| `lt_payroll_payable` | `float` | Y | 报表字段 | 长期应付职工薪酬 |
| `oth_comp_income` | `float` | Y | 报表字段 | 其他综合收益 |
| `oth_eqt_tools` | `float` | Y | 报表字段 | 其他权益工具 |
| `oth_eqt_tools_p_shr` | `float` | Y | 报表字段 | 其他权益工具(优先股) |
| `lending_funds` | `float` | Y | 报表字段 | 融出资金 |
| `acc_receivable` | `float` | Y | 报表字段 | 应收款项 |
| `st_fin_payable` | `float` | Y | 报表字段 | 应付短期融资款 |
| `payables` | `float` | Y | 报表字段 | 应付款项 |
| `hfs_assets` | `float` | Y | 报表字段 | 持有待售的资产 |
| `hfs_sales` | `float` | Y | 报表字段 | 持有待售的负债 |
| `cost_fin_assets` | `float` | Y | 报表字段 | 以摊余成本计量的金融资产 |
| `fair_value_fin_assets` | `float` | Y | 报表字段 | 以公允价值计量且其变动计入其他综合收益的金融资产 |
| `cip_total` | `float` | Y | 报表字段 | 在建工程(合计)(元) |
| `oth_pay_total` | `float` | Y | 报表字段 | 其他应付款(合计)(元) |
| `long_pay_total` | `float` | Y | 报表字段 | 长期应付款(合计)(元) |
| `debt_invest` | `float` | Y | 报表字段 | 债权投资(元) |
| `oth_debt_invest` | `float` | Y | 报表字段 | 其他债权投资(元) |
| `oth_eq_invest` | `float` | N | 报表字段 | 其他权益工具投资(元) |
| `oth_illiq_fin_assets` | `float` | N | 报表字段 | 其他非流动金融资产(元) |
| `oth_eq_ppbond` | `float` | N | 报表字段 | 其他权益工具:永续债(元) |
| `receiv_financing` | `float` | N | 报表字段 | 应收款项融资 |
| `use_right_assets` | `float` | N | 报表字段 | 使用权资产 |
| `lease_liab` | `float` | N | 报表字段 | 租赁负债 |
| `contract_assets` | `float` | Y | 报表字段 | 合同资产 |
| `contract_liab` | `float` | Y | 报表字段 | 合同负债 |
| `accounts_receiv_bill` | `float` | Y | 报表字段 | 应收票据及应收账款 |
| `accounts_pay` | `float` | Y | 报表字段 | 应付票据及应付账款 |
| `oth_rcv_total` | `float` | Y | 报表字段 | 其他应收款(合计)（元） |
| `fix_assets_total` | `float` | Y | 报表字段 | 固定资产(合计)(元) |
| `update_flag` | `str` | Y | 元数据 | 更新标识 |

## 现金流量表 `cashflow`

- 本地官方文件: `D:\MKA\TushareOfficialAPIMD\cashflow.md`
- 线上官方文档: https://tushare.pro/wctapi/documents/44.md
- 输入参数: 9
- 输出字段: 97

### 输入参数（取数参数，非 raw 输出字段）

| 名称 | 类型 | 必选 | 描述 |
|---|---|---|---|
| `ts_code` | `str` | Y | 股票代码 |
| `ann_date` | `str` | N | 公告日期（YYYYMMDD格式，下同） |
| `f_ann_date` | `str` | N | 实际公告日期 |
| `start_date` | `str` | N | 公告日开始日期 |
| `end_date` | `str` | N | 公告日结束日期 |
| `period` | `str` | N | 报告期(每个季度最后一天的日期，比如20171231表示年报，20170630半年报，20170930三季报) |
| `report_type` | `str` | N | 报告类型：见下方详细说明 |
| `comp_type` | `str` | N | 公司类型：1一般工商业 2银行 3保险 4证券 |
| `is_calc` | `int` | N | 是否计算报表 |

### 输出字段（raw_tushare payload schema）

| 名称 | 类型 | 默认显示 | 分类 | 描述 |
|---|---|---|---|---|
| `ts_code` | `str` | Y | 元数据 | TS股票代码 |
| `ann_date` | `str` | Y | 元数据 | 公告日期 |
| `f_ann_date` | `str` | Y | 元数据 | 实际公告日期 |
| `end_date` | `str` | Y | 元数据 | 报告期 |
| `comp_type` | `str` | Y | 元数据 | 公司类型(1一般工商业2银行3保险4证券) |
| `report_type` | `str` | Y | 元数据 | 报表类型 |
| `end_type` | `str` | Y | 元数据 | 报告期类型 |
| `net_profit` | `float` | Y | 报表字段 | 净利润 |
| `finan_exp` | `float` | Y | 报表字段 | 财务费用 |
| `c_fr_sale_sg` | `float` | Y | 报表字段 | 销售商品、提供劳务收到的现金 |
| `recp_tax_rends` | `float` | Y | 报表字段 | 收到的税费返还 |
| `n_depos_incr_fi` | `float` | Y | 报表字段 | 客户存款和同业存放款项净增加额 |
| `n_incr_loans_cb` | `float` | Y | 报表字段 | 向中央银行借款净增加额 |
| `n_inc_borr_oth_fi` | `float` | Y | 报表字段 | 向其他金融机构拆入资金净增加额 |
| `prem_fr_orig_contr` | `float` | Y | 报表字段 | 收到原保险合同保费取得的现金 |
| `n_incr_insured_dep` | `float` | Y | 报表字段 | 保户储金净增加额 |
| `n_reinsur_prem` | `float` | Y | 报表字段 | 收到再保业务现金净额 |
| `n_incr_disp_tfa` | `float` | Y | 报表字段 | 处置交易性金融资产净增加额 |
| `ifc_cash_incr` | `float` | Y | 报表字段 | 收取利息和手续费净增加额 |
| `n_incr_disp_faas` | `float` | Y | 报表字段 | 处置可供出售金融资产净增加额 |
| `n_incr_loans_oth_bank` | `float` | Y | 报表字段 | 拆入资金净增加额 |
| `n_cap_incr_repur` | `float` | Y | 报表字段 | 回购业务资金净增加额 |
| `c_fr_oth_operate_a` | `float` | Y | 报表字段 | 收到其他与经营活动有关的现金 |
| `c_inf_fr_operate_a` | `float` | Y | 报表字段 | 经营活动现金流入小计 |
| `c_paid_goods_s` | `float` | Y | 报表字段 | 购买商品、接受劳务支付的现金 |
| `c_paid_to_for_empl` | `float` | Y | 报表字段 | 支付给职工以及为职工支付的现金 |
| `c_paid_for_taxes` | `float` | Y | 报表字段 | 支付的各项税费 |
| `n_incr_clt_loan_adv` | `float` | Y | 报表字段 | 客户贷款及垫款净增加额 |
| `n_incr_dep_cbob` | `float` | Y | 报表字段 | 存放央行和同业款项净增加额 |
| `c_pay_claims_orig_inco` | `float` | Y | 报表字段 | 支付原保险合同赔付款项的现金 |
| `pay_handling_chrg` | `float` | Y | 报表字段 | 支付手续费的现金 |
| `pay_comm_insur_plcy` | `float` | Y | 报表字段 | 支付保单红利的现金 |
| `oth_cash_pay_oper_act` | `float` | Y | 报表字段 | 支付其他与经营活动有关的现金 |
| `st_cash_out_act` | `float` | Y | 报表字段 | 经营活动现金流出小计 |
| `n_cashflow_act` | `float` | Y | 报表字段 | 经营活动产生的现金流量净额 |
| `oth_recp_ral_inv_act` | `float` | Y | 报表字段 | 收到其他与投资活动有关的现金 |
| `c_disp_withdrwl_invest` | `float` | Y | 报表字段 | 收回投资收到的现金 |
| `c_recp_return_invest` | `float` | Y | 报表字段 | 取得投资收益收到的现金 |
| `n_recp_disp_fiolta` | `float` | Y | 报表字段 | 处置固定资产、无形资产和其他长期资产收回的现金净额 |
| `n_recp_disp_sobu` | `float` | Y | 报表字段 | 处置子公司及其他营业单位收到的现金净额 |
| `stot_inflows_inv_act` | `float` | Y | 报表字段 | 投资活动现金流入小计 |
| `c_pay_acq_const_fiolta` | `float` | Y | 报表字段 | 购建固定资产、无形资产和其他长期资产支付的现金 |
| `c_paid_invest` | `float` | Y | 报表字段 | 投资支付的现金 |
| `n_disp_subs_oth_biz` | `float` | Y | 报表字段 | 取得子公司及其他营业单位支付的现金净额 |
| `oth_pay_ral_inv_act` | `float` | Y | 报表字段 | 支付其他与投资活动有关的现金 |
| `n_incr_pledge_loan` | `float` | Y | 报表字段 | 质押贷款净增加额 |
| `stot_out_inv_act` | `float` | Y | 报表字段 | 投资活动现金流出小计 |
| `n_cashflow_inv_act` | `float` | Y | 报表字段 | 投资活动产生的现金流量净额 |
| `c_recp_borrow` | `float` | Y | 报表字段 | 取得借款收到的现金 |
| `proc_issue_bonds` | `float` | Y | 报表字段 | 发行债券收到的现金 |
| `oth_cash_recp_ral_fnc_act` | `float` | Y | 报表字段 | 收到其他与筹资活动有关的现金 |
| `stot_cash_in_fnc_act` | `float` | Y | 报表字段 | 筹资活动现金流入小计 |
| `free_cashflow` | `float` | Y | 报表字段 | 企业自由现金流量 |
| `c_prepay_amt_borr` | `float` | Y | 报表字段 | 偿还债务支付的现金 |
| `c_pay_dist_dpcp_int_exp` | `float` | Y | 报表字段 | 分配股利、利润或偿付利息支付的现金 |
| `incl_dvd_profit_paid_sc_ms` | `float` | Y | 报表字段 | 其中:子公司支付给少数股东的股利、利润 |
| `oth_cashpay_ral_fnc_act` | `float` | Y | 报表字段 | 支付其他与筹资活动有关的现金 |
| `stot_cashout_fnc_act` | `float` | Y | 报表字段 | 筹资活动现金流出小计 |
| `n_cash_flows_fnc_act` | `float` | Y | 报表字段 | 筹资活动产生的现金流量净额 |
| `eff_fx_flu_cash` | `float` | Y | 报表字段 | 汇率变动对现金的影响 |
| `n_incr_cash_cash_equ` | `float` | Y | 报表字段 | 现金及现金等价物净增加额 |
| `c_cash_equ_beg_period` | `float` | Y | 报表字段 | 期初现金及现金等价物余额 |
| `c_cash_equ_end_period` | `float` | Y | 报表字段 | 期末现金及现金等价物余额 |
| `c_recp_cap_contrib` | `float` | Y | 报表字段 | 吸收投资收到的现金 |
| `incl_cash_rec_saims` | `float` | Y | 报表字段 | 其中:子公司吸收少数股东投资收到的现金 |
| `uncon_invest_loss` | `float` | Y | 报表字段 | 未确认投资损失 |
| `prov_depr_assets` | `float` | Y | 报表字段 | 加:资产减值准备 |
| `depr_fa_coga_dpba` | `float` | Y | 报表字段 | 固定资产折旧、油气资产折耗、生产性生物资产折旧 |
| `amort_intang_assets` | `float` | Y | 报表字段 | 无形资产摊销 |
| `lt_amort_deferred_exp` | `float` | Y | 报表字段 | 长期待摊费用摊销 |
| `decr_deferred_exp` | `float` | Y | 报表字段 | 待摊费用减少 |
| `incr_acc_exp` | `float` | Y | 报表字段 | 预提费用增加 |
| `loss_disp_fiolta` | `float` | Y | 报表字段 | 处置固定、无形资产和其他长期资产的损失 |
| `loss_scr_fa` | `float` | Y | 报表字段 | 固定资产报废损失 |
| `loss_fv_chg` | `float` | Y | 报表字段 | 公允价值变动损失 |
| `invest_loss` | `float` | Y | 报表字段 | 投资损失 |
| `decr_def_inc_tax_assets` | `float` | Y | 报表字段 | 递延所得税资产减少 |
| `incr_def_inc_tax_liab` | `float` | Y | 报表字段 | 递延所得税负债增加 |
| `decr_inventories` | `float` | Y | 报表字段 | 存货的减少 |
| `decr_oper_payable` | `float` | Y | 报表字段 | 经营性应收项目的减少 |
| `incr_oper_payable` | `float` | Y | 报表字段 | 经营性应付项目的增加 |
| `others` | `float` | Y | 报表字段 | 其他 |
| `im_net_cashflow_oper_act` | `float` | Y | 报表字段 | 经营活动产生的现金流量净额(间接法) |
| `conv_debt_into_cap` | `float` | Y | 报表字段 | 债务转为资本 |
| `conv_copbonds_due_within_1y` | `float` | Y | 报表字段 | 一年内到期的可转换公司债券 |
| `fa_fnc_leases` | `float` | Y | 报表字段 | 融资租入固定资产 |
| `im_n_incr_cash_equ` | `float` | Y | 报表字段 | 现金及现金等价物净增加额(间接法) |
| `net_dism_capital_add` | `float` | Y | 报表字段 | 拆出资金净增加额 |
| `net_cash_rece_sec` | `float` | Y | 报表字段 | 代理买卖证券收到的现金净额(元) |
| `credit_impa_loss` | `float` | Y | 报表字段 | 信用减值损失 |
| `use_right_asset_dep` | `float` | Y | 报表字段 | 使用权资产折旧 |
| `oth_loss_asset` | `float` | Y | 报表字段 | 其他资产减值损失 |
| `end_bal_cash` | `float` | Y | 报表字段 | 现金的期末余额 |
| `beg_bal_cash` | `float` | Y | 报表字段 | 减:现金的期初余额 |
| `end_bal_cash_equ` | `float` | Y | 报表字段 | 加:现金等价物的期末余额 |
| `beg_bal_cash_equ` | `float` | Y | 报表字段 | 减:现金等价物的期初余额 |
| `update_flag` | `str` | Y | 元数据 | 更新标志(1最新） |

## 后续开发含义

1. 取数层应使用官方接口及官方 token，固定走官方 TuShare 源。
2. 清洗层不能假设官方输出已经按我们的 clean 科目做过归一化；所有差异都应由通用适配规则解释。
3. 跨表硬校验失败时，先区分“官方 raw 缺字段”、“clean 科目组合漏项”、“报表只披露合计而未披露明细”三类情况。
4. 任何修复都必须通过官方 schema 测试和多公司回归样本，不能只依赖安克创新一个样本。
