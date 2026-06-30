# /audit 技能需求文档

## 一、这是什么

/audit 是 ModelKing 体系内的一个新技能。它的目的是：**对 coverage list 中的全部公司进行自动化财务健康度检测，发现财务造假 / 盈余操纵 / 财务质量恶化的早期信号。**

它不是一个"模型"，它是一个"检察官"——先用量化规则广撒网（Layer 1），再用 Agent 对可疑标的做定向深度调查（Layer 2），最后合成人类可读的审计意见（Layer 3）。

### 为什么要做这个

2026年4月五粮液"财报变脸"事件：公司以"会计差错更正"名义将2025年前三季度营收从609亿下调至306亿（腰斩），净利润从215亿下调至65亿（斩七成）。事后复盘发现，暴雷前2-3年已存在大量可观测的量化预兆信号——合同负债连降、批价长期倒挂、经销商库存深度达6个月、销售费用/收入弹性断崖式恶化、净现比恶化、Q2出现11年来首次季度利润负增长。

这些信号散落在三表数据和渠道草根信息中，以人工方式逐一追踪既慢又容易遗漏。/audit 的目标就是把这个过程自动化：让机器每个季度跑一遍全 coverage，告诉我"谁现在最危险"。

---

## 二、整体架构

```
/audit [coverage_list]
  ├─ Layer 0: 数据准备层 (audit_data_toolkit.py，统一抽象层)
  ├─ Layer 1: 量化初筛 (Python并发，确定性，零token消耗)
  ├─ Layer 2: 定向调查 (Sub-agents，仅针对Layer 1筛出的高危公司)
  └─ Layer 3: 综合研判 (单次LLM调用，将结构化证据合成为narrative)
```

### 核心设计原则

1. **LLM as translator, Python as executor。** 所有能用确定性计算解决的事情都在 Python 层完成，LLM 只处理需要语义理解的任务。
2. **O(1) repeat cost。** 规则写一次，跑 N 家公司都是同一套引擎。Playbook 写一次，复用 N 家公司 × N 年。
3. **Sub-agent 不直接调 TuShare。** Agent 调用 audit_data_toolkit.py 中的函数，toolkit 内部决定从哪个数据源取数据（TuShare / calc.py 输出 / 年报 chunk 库 / Alphapai 蒸馏结果）。Agent 不需要知道底层数据源是什么。

---

## 三、Layer 0：数据准备层

### 数据源

| 数据源 | 用途 | 接口形态 |
|--------|------|----------|
| calc.py 输出 | 标准化三表时间序列（ModelKing 已有） | 本地 CSV/DataFrame |
| TuShare Pro | 三表原始数据补充、财务指标、高管交易、质押、审计信息 | `pro.income()`, `pro.balancesheet()`, `pro.cashflow()`, `pro.fina_indicator()` 等 |
| 年报 chunk 库 | 按 section 预切好的年报文本段落 | 本地文本文件，按公司/年份/section 索引 |
| Alphapai 蒸馏结果 | 卖方分析师观点 | 本地 markdown |
| coverage_meta.yaml | 每家公司的 ts_code、行业分类、peer list | 本地 yaml |

### audit_data_toolkit.py 的函数清单

所有函数签名统一：`f(ts_code: str, **kwargs) → dict`。Sub-agent 只看到这一层。

核心函数（Layer 2 调用的）：

- `get_insider_trades(ts_code, months=12)` → 高管增减持 + 大宗交易
- `get_pledge_ratio(ts_code)` → 股权质押比例及趋势
- `get_auditor_info(ts_code)` → 审计机构名称、审计意见类型、是否更换
- `get_peer_flag_values(ts_code, flag_type, peer_list)` → 可比公司同一 flag 的值 + 行业中位数 + 该公司的 z-score
- `get_annual_report_chunk(ts_code, year, section)` → 年报特定 section 的文本
- `get_contract_liability_detail(ts_code)` → 合同负债明细时间序列

Section 定义（年报 chunk 预切的关键词）：

```python
SECTION_KEYWORDS = {
    "revenue_recognition": ["收入确认", "控制权转移", "商品控制权", "会计政策"],
    "receivables_aging": ["账龄分析", "应收账款", "坏账准备", "坏账计提"],
    "related_party": ["关联方", "关联交易", "关联方应收", "关联方往来"],
    "audit_opinion": ["审计意见", "强调事项", "保留意见", "持续经营"],
    "mda_risk": ["风险因素", "可能面临的风险", "经营风险", "市场风险"],
    "inventory_detail": ["存货", "库存商品", "在产品", "存货跌价"],
    "cip_detail": ["在建工程", "工程进度", "转固", "预算"],
    "goodwill_detail": ["商誉", "减值测试", "商誉减值"],
    "other_receivables": ["其他应收款", "往来款", "资金占用"],
    "pledge_guarantee": ["质押", "担保", "对外担保"],
}
```

注意：tushare-data 的 skills 包（https://github.com/waditu/tushare-data）包含 235+ 接口的结构化文档，已适配 Claude Code。可以直接将该 skills 包加载到工作环境中，agent 通过自然语言就能找到对应的 TuShare 接口。

---

## 四、Layer 1：量化初筛（核心会计逻辑）

### 4.0 总体原则

Layer 1 的所有规则必须满足：
- 输入只需要标准化三表数据（calc.py 输出），不需要任何年报文本
- 计算完全确定性，零 LLM 调用
- 每条规则吃进一个 DataFrame（单公司多年三表），吐出 `{rule_id, severity, value, threshold, evidence_text}`

执行方式：`ProcessPoolExecutor` 并发跑全部 coverage list，每个 worker 跑同一套规则集。

### 4.1 Beneish M-Score（盈余操纵概率综合评分）

**这是什么：** 1999年由 Messod Beneish 教授提出的八因子模型，通过财务比率组合判断公司是否在操纵盈余。学术公认最经得起时间检验的造假初筛模型——2020年后续论文证明其假阳/真阳比率优于几乎所有非机器学习方法。

**公式：**

```
M-Score = -4.84 + 0.92×DSRI + 0.528×GMI + 0.404×AQI + 0.892×SGI
          + 0.115×DEPI - 0.172×SGAI + 4.679×TATA - 0.327×LVGI
```

**八个因子的计算与会计含义：**

**① DSRI（应收天数指数）**
```
DSRI = (应收账款_t / 营业收入_t) / (应收账款_t-1 / 营业收入_t-1)
```
含义：应收账款膨胀速度是否快于收入增速。如果公司在虚增收入，最快的方式就是把虚增的部分挂在应收账款上——毕竟虚增的收入不会真的有现金流入。DSRI > 1 意味着应收膨胀快于收入，越高越可疑。

**② GMI（毛利率指数）**
```
GMI = 毛利率_t-1 / 毛利率_t
```
含义：毛利率是否在恶化。GMI > 1 说明毛利率在下降——公司基本面在变差，管理层有更强的动机通过其他手段美化利润。注意，这个因子衡量的不是"公司在造假"，而是"公司有造假的动机"。

**③ AQI（资产质量指数）**
```
非硬资产占比_t = 1 - (流动资产_t + 固定资产净额_t + 长期投资_t) / 总资产_t
非硬资产占比_t-1 = 同上，用 t-1 年数据
AQI = 非硬资产占比_t / 非硬资产占比_t-1
```
含义：非硬资产（其他资产、在建工程、无形资产、商誉等）占比是否在上升。造假者虚增利润后需要一个地方"放"虚增的资产，这些难以审计的"软"资产科目就是常见的藏匿之所。AQI > 1 说明资产质量在恶化。

注意：A股财报中"长期投资"的对应项需要用"长期股权投资 + 其他权益工具投资 + 其他非流动金融资产"等科目合计，具体映射取决于 calc.py 的字段定义。

**④ SGI（收入增长指数）**
```
SGI = 营业收入_t / 营业收入_t-1
```
含义：收入增速。统计事实表明高增长公司造假概率更高——因为它们面临维持增长 story 的市场压力。SGI 本身不是"坏事"，但它作为 M-Score 的一个输入项会提升整体得分。

**⑤ DEPI（折旧指数）**
```
折旧率_t = 折旧_t / (折旧_t + 固定资产净额_t)
折旧率_t-1 = 同上
DEPI = 折旧率_t-1 / 折旧率_t
```
含义：是否在放慢折旧速度来美化利润。DEPI > 1 说明折旧率下降了——可能是延长了资产使用年限、降低了折旧比例。这是一种合规但激进的会计估计变更，常见于利润承压时。

**⑥ SGAI（管销费用指数）**
```
SGAI = (销售费用+管理费用)_t/营业收入_t / (销售费用+管理费用)_t-1/营业收入_t-1
```
含义：管销费用率是否在上升。SGAI > 1 说明费用效率恶化，同样指向经营基本面变差、管理层有粉饰动机。

**⑦ TATA（总应计/总资产）——权重最大的因子（系数4.679）**
```
TATA = (净利润 - 经营活动现金流净额) / 总资产
```
含义：利润中有多大比例是"纸面利润"（应计项目）而非真金白银。**这是整个模型里最重要的因子。** 造假公司的核心特征就是利润远超现金流——因为虚构的交易产生的利润不会有真实的现金流入。TATA 越高，盈余质量越差。

**⑧ LVGI（杠杆指数）**
```
LVGI = 资产负债率_t / 资产负债率_t-1
```
含义：杠杆是否在加大。LVGI > 1 说明公司在加杠杆，财务压力在增大，有动机粉饰利润以维持融资能力。

**阈值与判读：**
- M-Score > -1.78 → HIGH severity（大概率存在盈余操纵）
- M-Score 在 -2.22 到 -1.78 之间 → MEDIUM severity（灰色地带，需关注）
- M-Score < -2.22 → LOW（暂无明显操纵信号）

**注意事项：**
- 需要至少连续两年的数据才能计算（因为所有因子都是 t vs t-1）
- A股的费用拆分（销售费用 vs 管理费用 vs 研发费用）需要根据 calc.py 的字段做适配
- 白酒行业因为 2012-2014 和 2023 至今两轮调整期数据波动大，阈值可以考虑行业校准

### 4.2 Altman Z-Score（财务困境概率）

**这是什么：** 不直接测造假，但测造假动机。公司越接近财务困境，造假概率越高。

**公式（修订版，适用于非上市制造业和一般企业）：**
```
Z = 0.717×(营运资本/总资产) + 0.847×(留存收益/总资产)
  + 3.107×(EBIT/总资产) + 0.420×(股东权益/总负债) + 0.998×(营业收入/总资产)
```

其中营运资本 = 流动资产 - 流动负债。

**阈值：**
- Z < 1.2 → 高困境风险（HIGH）
- 1.2 < Z < 2.9 → 灰色地带（MEDIUM）
- Z > 2.9 → 安全

**注意：** 白酒/乳制品龙头通常 Z-Score 很高（因为现金充裕、轻资产），所以这条规则对我的 coverage 可能主要用于出口型消费公司和中小盘标的。

### 4.3 净现比（Quality of Earnings Ratio）

**这是什么：** 最简单也最有效的盈余质量指标。

```
净现比 = 经营活动现金流净额 / 净利润
```

**判读：**
- 长周期（5年+）应 ≥ 1（赚到的利润都有现金支撑）
- 单年度净现比 < 0.5 → MEDIUM
- 连续两年净现比 < 0.5 → HIGH
- 净利润为正但 CFO 为负 → CRITICAL

**会计含义：** 一个公司报告了10亿利润，但经营现金流只有3亿甚至为负，意味着那些"利润"大部分存在于应收账款、存货、或其他应计项目中——要么客户没付钱，要么货没卖出去，要么根本就是纸面上的。五粮液2025年重述后经营现金流转负，正是因为此前确认的收入对应的货还压在渠道里。

### 4.4 收现比

```
收现比 = 销售商品、提供劳务收到的现金 / 营业收入
```

**判读：**
- 考虑增值税，理论值约 1.16
- < 0.8 → MEDIUM
- 连续两年 < 0.8 → HIGH

**与净现比的区别：** 净现比衡量的是利润的现金含量，收现比衡量的是收入的现金含量。一家公司可能收现比正常（收入确实收到了钱）但净现比很差（因为成本端的现金流出太大，比如存货采购激增）。两个指标配合使用可以定位问题到底出在收入端还是成本端。

### 4.5 Sloan 应计比率

```
应计比率 = (净利润 - 经营活动现金流 - 投资活动现金流) / 总资产
```

**判读：**
- -10% 到 +10% → 安全
- 超出 ±25% → HIGH（盈余主要由非现金应计项目构成）

**含义：** 这是 TATA 的扩展版——不仅考虑 CFO，还考虑 CFI。如果一家公司的利润既不来自经营现金流、也不来自投资现金流，那它到底来自哪里？

### 4.6 经营现金流 vs 净利润的趋势剪刀差

**这不是看绝对值，而是看三到五年的趋势方向是否在分裂。**

计算方法：
1. 对近5年（至少3年）的净利润做线性回归，得到斜率 slope_NI
2. 对同期的经营活动现金流做线性回归，得到斜率 slope_CFO
3. 如果 slope_NI > 0 且 slope_CFO < 0（利润在涨、现金流在跌），标记为 HIGH
4. 如果 slope_NI > 0 且 slope_CFO 趋近于 0（利润在涨、现金流走平），标记为 MEDIUM

**会计含义：** 几乎所有造假公司在暴雷前2-3年都会出现利润和现金流的趋势性背离。因为造假初期应计项目的增长还可以被增长的收入所"稀释"，但随着造假持续，累积的应计项目越来越大，现金流终究跟不上利润的节奏。

### 4.7 应收账款增速 vs 收入增速

```
AR_Revenue_Ratio = (应收账款_t / 应收账款_t-1 - 1) / (营业收入_t / 营业收入_t-1 - 1)
```

**判读：**
- > 1.3 → MEDIUM（应收膨胀速度显著快于收入）
- > 1.5 → HIGH
- 连续两年 > 1.3 → HIGH

**注意：** 当收入增速接近0时，这个比率会失真。需要加一个 guard：如果收入增速绝对值 < 3%，改用应收/收入的绝对比率变化来判断。

**会计含义：** 与 Beneish DSRI 因子同源，但这里是独立检测。应收账款膨胀快于收入，说明公司在赊账卖货（客户不愿付现金）或者干脆在虚增收入挂应收。

### 4.8 存货增速 vs 收入增速

```
INV_Revenue_Ratio = (存货_t / 存货_t-1 - 1) / (营业收入_t / 营业收入_t-1 - 1)
```

**判读：**
- > 1.5 → MEDIUM
- > 2.0 → HIGH
- 存货增速 > 20% 且收入增速 < 5% → HIGH（不管比率）

**会计含义：** 存货堆积有两种可能——产品滞销（真实问题）或虚构存货（造假）。无论哪种，都是坏消息。白酒行业尤其敏感——五粮液2025年上半年高端白酒库存同比涨了41%而整体收入在放缓，这就是一个典型的存货-收入背离。

另外，存货造假是A股"五重境界"中的第二重（第一重是应收造假）：造假者把虚增收入对应的资产从应收账款腾挪到存货中，因为存货比应收更难审计（尤其是农业、中药材等实物盘点困难的行业）。

### 4.9 存贷双高

**这是什么：** 公司账上趴着大量货币资金，同时又在借大量有息负债——这在商业逻辑上是矛盾的（你有钱为什么还要借钱付利息？），是康得新、康美药业等经典造假案的核心特征。

**检测逻辑：**
```
条件1: 货币资金 / 总资产 > 15%
条件2: 有息负债 / 总资产 > 20%
条件3: 利息支出 / 平均有息负债 > 同期贷款基准利率（或隐含利率异常高/异常低）
```
三个条件同时满足 → HIGH

**会计含义：** 如果货币资金是真实的，公司完全可以用自有资金偿还借款、节省利息。存贷双高的存在通常意味着：(a) 货币资金是虚构的（如康得新，299亿货币资金为假）；或 (b) 货币资金被限制使用/质押但未披露；或 (c) 大股东通过某种安排占用了公司资金。

### 4.10 在建工程不转固

```
CIP_Ratio = 在建工程 / 固定资产净额
```

**判读：**
- CIP_Ratio 连续3年 > 30% → MEDIUM
- CIP_Ratio 连续3年 > 30% 且在建工程增速 > 收入增速 → HIGH

**会计含义：** 在建工程是造假者的"天堂科目"——它不需要折旧（不像固定资产），不需要盘点（不像存货），而且金额可以很大。如果一个项目长期处于"在建"状态不转固，要么工程进度有问题，要么公司在利用这个科目藏匿虚增的资产。这是财务造假"五重境界"中第四重的核心手法。

### 4.11 其他应收款 / 总资产

```
其他应收占比 = 其他应收款 / 总资产
```

**判读：**
- > 5% → MEDIUM
- > 5% 且 YoY 增速 > 30% → HIGH

**会计含义：** "其他应收款"是财报里的"杂物间"——很多说不清道不明的东西都放在这里。常见的问题包括：大股东资金占用（康美药业）、未确认的关联方往来、账外资金循环的中转站。正常经营的公司其他应收款应该很小，占比过高本身就需要解释。

### 4.12 商誉 / 净资产

```
商誉占比 = 商誉 / 归属母公司股东权益
```

**判读：**
- > 30% → MEDIUM
- > 50% → HIGH
- 商誉 > 30% 且被收购标的业绩承诺期即将到期 → HIGH

**会计含义：** 商誉是并购溢价的资本化，本质上是"为未来利润预支付的价格"。如果被收购公司未来业绩达不到预期，商誉就要减值，直接吃掉利润。2018-2019年A股的商誉暴雷潮就是前几年并购狂欢的后遗症。

注意：白酒/乳制品行业的龙头通常商誉不大（有机增长为主），这条规则对消费出口类公司和有并购历史的标的更有意义。

### 4.13 预付账款异常

```
预付占比 = 预付款项 / 营业成本
```

**判读：**
- 连续上升且 > 15% → MEDIUM
- > 20% 且对手方集中度高 → HIGH

**会计含义：** 正常的预付账款应该与采购规模匹配。预付异常高有两种可能：(a) 融资性贸易——公司通过虚构的"预付采购款"把资金转移到体外，再以"销售回款"的名义转回，实现现金流闭环（这是广州浪奇、"专网通信"骗局的核心手法）；(b) 关联方资金占用——大股东通过预付款名义从上市公司抽血。

### 4.14 Q4 收入占比突变

```
Q4_Ratio = 第四季度收入 / 全年收入
Q4_Ratio_Hist_Mean = 过去3年 Q4_Ratio 的均值
Q4_Ratio_Hist_Std = 过去3年 Q4_Ratio 的标准差
Deviation = (Q4_Ratio - Q4_Ratio_Hist_Mean) / Q4_Ratio_Hist_Std
```

**判读：**
- |Deviation| > 1.5σ → MEDIUM
- |Deviation| > 2.0σ → HIGH
- 特别地：Q4_Ratio 异常高（年底突击做收入）比异常低更可疑

**会计含义：** 两种情况——(a) Q4占比异常高：年底突击确认收入冲业绩，可能是虚增收入或提前确认（"寅吃卯粮"）；(b) Q4占比异常低（如五粮液2025年重述后Q4巨亏130亿）：年底集中计提、"洗大澡"为来年做低基数。两种都需要关注。

### 4.15 合同负债连续下降

```
检测: 合同负债（或旧准则下的预收款项）连续 N 年下降
```

**判读：**
- 连续2年下降 → MEDIUM
- 连续3年下降 → HIGH
- 连续下降且收入仍在增长 → CRITICAL（收入和预收的背离）

**会计含义：** 合同负债 = 客户已经付了钱但公司还没交货/确认收入的金额。对白酒行业来说，合同负债就是经销商的提前打款——它直接反映渠道对公司产品未来销售的信心。五粮液2021→2023年合同负债从130亿降到68亿，这不是随机波动，而是经销商在用脚投票。

**特殊行业注释（白酒）：** 白酒行业的合同负债具有极强的信号意义，因为白酒的商业模式是"先打款再发货"——经销商愿意预付说明他们相信这个酒能卖出去。合同负债连降 = 渠道信心崩塌。如果同时伴随收入仍在增长，说明公司可能在强行发货确认收入，但经销商已经不愿意预付了。

### 4.16 毛利率自身历史偏离

**注意：这不是跟同行比（那是语义判断），是跟自己的历史比。**

```
当年毛利率 vs 过去5年毛利率的均值和标准差
Deviation = (毛利率_t - 毛利率_5yr_mean) / 毛利率_5yr_std
```

**判读：**
- |Deviation| > 2σ → MEDIUM
- |Deviation| > 3σ → HIGH
- 特别地：毛利率异常上升比下降更可疑（可能在少结转成本美化利润）

**会计含义：** 毛利率应该反映公司的竞争优势和行业地位，短期内不应有剧烈波动。如果波动显著超出历史范围，要么是经营出了重大变化（需要 Layer 2 去查原因），要么是会计处理出了问题。

### 4.17 销售费用 / 收入弹性

```
Elasticity = (销售费用_t / 销售费用_t-1 - 1) / (营业收入_t / 营业收入_t-1 - 1)
```

**判读：**
- > 2.0 且持续2年 → MEDIUM
- > 3.0 → HIGH

**会计含义：** 花越来越多的钱推不动收入增长——说明要么产品竞争力在下降（需要更多激励才能让渠道卖货），要么销售费用中藏着不合理的支出（如变相给关联方输送利益）。五粮液2024年销售费用暴增37%但收入只增7%，就是这个信号的典型体现。

### 4.18 跨 flag 组合模式匹配

单个 flag 可能有很多解释，但当多个 flag 同时触发且指向同一个故事时，可信度大幅提升。

**预定义模式：**

**CHANNEL_STUFFING（渠道压货型，白酒/消费品核心关注）：**
- 必须触发（至少2/3）：DSRI_HIGH, CFO_NI_DIVERGENCE, CONTRACT_LIABILITY_DECLINE
- 加分项：INVENTORY_GROWTH_EXCEEDS_REVENUE, SELLING_EXPENSE_INEFFICIENCY
- 典型案例：五粮液

**CASH_FABRICATION（现金虚构型）：**
- 必须触发：DEPOSIT_LOAN_MISMATCH（存贷双高）
- 加分项：利息收入/货币资金隐含收益率异常低
- 典型案例：康得新、康美药业

**ASSET_HOLE（资产黑洞型）：**
- 必须触发（至少1）：AQI_HIGH, CIP_NOT_TRANSFERRING
- 加分项：GOODWILL_HIGH, OTHER_RECEIVABLE_HIGH
- 典型案例：在建工程/商誉暴雷类

**RECEIVABLE_INFLATION（应收膨胀型）：**
- 必须触发：AR_REVENUE_RATIO_HIGH, LOW_CASH_INCOME_RATIO
- 加分项：收现比下降、应收账龄延长（如果有数据）
- 典型案例：欣泰电气

**BIG_BATH（财务洗澡型）：**
- 必须触发：Q4_ANOMALY（Q4巨亏或巨额减值计提）
- 加分项：新管理层上任、审计机构变更
- 典型案例：五粮液2025年报

---

## 五、Layer 2：定向调查（Agent 规划逻辑）

### 5.0 核心设计思想

Layer 2 模拟的是一个人类审计专家看到 Layer 1 的 flag 后的认知过程：

**flag → 假设空间 → 定向取证 → 交叉验证 → 判决**

Agent 不是在"自由探索"，而是在执行一个预定义的 **investigation playbook**。每种 flag type 映射到一棵假设树（hypotheses），每个假设映射到一组取证动作（tasks），每个取证动作指向 audit_data_toolkit.py 中的一个具体函数。

### 5.1 Playbook 结构

每个 playbook 文件对应一种 flag type，结构如下：

```yaml
flag_type: DSRI_HIGH
description: "应收账款膨胀速度显著快于收入增速"

hypotheses:
  - id: H1_aggressive_rev_rec
    name: "收入确认激进"
    prior_probability: "白酒行业高，因为发货确认收入是行业通行做法"
    tasks:
      - function: get_annual_report_chunk
        args: {section: "revenue_recognition"}
        question: "收入确认政策与上年是否有变更？是否出现'基于谨慎性原则调整'等措辞？"
        confirm_signal: "政策表述有实质变化"
        dismiss_signal: "政策表述无变化且与同行一致"
      - function: get_peer_flag_values
        args: {flag_type: "DSRI"}
        question: "同行业可比公司同期DSRI是否也在上升？"
        confirm_signal: "本公司DSRI显著高于行业中位数（z-score > 2）"
        dismiss_signal: "行业整体DSRI上升，属于行业共性"
      - function: get_contract_liability_detail
        question: "合同负债/预收款是否在同步下降？"
        confirm_signal: "合同负债下降且收入仍在增长——强化压货嫌疑"

  - id: H2_collection_deterioration
    name: "回款能力恶化（客户付不起钱了）"
    tasks:
      - function: get_annual_report_chunk
        args: {section: "receivables_aging"}
        question: "应收账款账龄分布是否恶化？1年以上占比是否上升？"
        confirm_signal: "1年以上占比上升超5个百分点"
      - function: get_annual_report_chunk
        args: {section: "receivables_aging"}
        question: "坏账计提政策是否有调整？实际计提比例是否下降？"
        confirm_signal: "计提比例下调或实际计提率低于政策规定"
      - function: get_insider_trades
        args: {months: 12}
        question: "内部人是否在卖？"
        confirm_signal: "高管净减持且金额显著"

  - id: H3_one_time_event
    name: "并购或年末大单导致的一次性事件"
    tasks:
      - function: "[引用Layer 1中Q4_ANOMALY flag的结果]"
        question: "Q4收入占比是否异常？"
        dismiss_signal: "Q4占比在正常范围内"
      - function: get_annual_report_chunk
        args: {section: "related_party"}
        question: "是否存在重大并购带入的应收？"
        dismiss_signal: "存在并购且并购标的应收解释了增量"

synthesis:
  rule: "H1或H2任一假设有>=2个confirm且无dismiss → 升级为WARNING"
  output: "在 investigation_{company}.yaml 中记录证据链"
```

### 5.2 需要构建 Playbook 的 flag types（优先级排序）

**P0（首批实现，覆盖五粮液型暴雷）：**
1. DSRI_HIGH（上面已给出完整示例）
2. CFO_NI_DIVERGENCE → 假设树：收入激进确认 / 成本延迟确认 / 真实回款恶化
3. CONTRACT_LIABILITY_DECLINE → 假设树：渠道信心崩塌 / 收入确认口径变更 / 行业整体下行
4. DEPOSIT_LOAN_MISMATCH → 假设树：货币资金虚构 / 资金受限未披露 / 大股东占用

**P1（第二批，覆盖康得新/商誉暴雷型）：**
5. CIP_NOT_TRANSFERRING → 假设树：工程真实延迟 / 虚增资产 / 隐藏费用
6. OTHER_RECEIVABLE_HIGH → 假设树：关联方占用 / 账外资金循环 / 正常商业往来
7. GOODWILL_HIGH → 假设树：业绩承诺到期风险 / 被投公司基本面恶化
8. Q4_ANOMALY → 假设树：突击确认收入 / 财务洗澡做低基数 / 合理季节性

### 5.3 Agent 的取证数据源优先级

1. **Layer 1 的其他 flags**（零成本——已经算好了）。flag 之间的交叉验证是最便宜的证据。
2. **calc.py 输出中的可比公司数据**。peer comparison 的数值部分可以直接从数据库拉。
3. **年报 chunk（预切好的特定 section）**。这是主要的 token 消耗区，但因为是按 section 定向提取，每次只喂几百到几千 token 的 chunk 给 agent，而不是整份年报。
4. **TuShare 辅助数据**（高管交易、质押、审计信息等）。补充性证据。
5. **Alphapai 蒸馏结果**（卖方报告摘要）。看 sell-side 有没有注意到同样的问题。

### 5.4 Synthesis（跨 flag 综合研判）

当一家公司有多个 flags 被触发，Layer 2 的最后一步是做 cross-flag synthesis：

1. 检查是否匹配预定义的组合模式（CHANNEL_STUFFING 等）
2. 对匹配到的模式，检查各个 flag 的调查结论是否一致——如果 DSRI_HIGH 的调查结论是"行业共性可dismiss"，但 CFO_NI_DIVERGENCE 的调查结论是"confirmed"，需要在 narrative 中说明这个矛盾
3. 给出 overall_risk 评级：CRITICAL / HIGH / MEDIUM / LOW
4. 给出 confidence 评分（基于 confirmed 假设数量 / 总假设数量）
5. 给出 action 建议（方向性的，不是具体买卖建议）：如"下调财务真实性信心"、"关注下一季度XXX指标变化"、"建议减仓/回避"

---

## 六、Layer 3：输出格式

### 对人看的：audit_report_{company}.md

```markdown
# {公司名} 财务健康度审计报告
## 日期：{date}
## 综合评级：{CRITICAL/HIGH/MEDIUM/LOW}
## 置信度：{0-1}

### 一句话结论
{如："多重信号指向渠道压货模式，建议高度警惕财务质量风险"}

### 触发的量化信号
{表格：flag_id | 当前值 | 阈值 | severity | 证据}

### 匹配的风险模式
{如：CHANNEL_STUFFING 模式，3/3 核心 flag 触发}

### 调查发现
{按flag分段，每段包含：假设 → 取证结果 → 判断}

### 需要持续跟踪的指标
{如："下一季度重点关注合同负债变化、批价走势、经营现金流是否转正"}
```

### 对机器看的：audit_verdict_{company}.yaml

```yaml
company: "五粮液"
ts_code: "000858.SZ"
date: "2026-06-29"
overall_risk: CRITICAL
confidence: 0.85
pattern_matched: CHANNEL_STUFFING
flags_triggered: [DSRI_HIGH, CFO_NI_DIVERGENCE, CONTRACT_LIABILITY_DECLINE, ...]
key_finding: "渠道压货模式确认，3/3核心flag verified，合同负债连降3年且收入仍在增长"
action: "下调财务真实性信心，建议减仓/回避"
next_check: ["合同负债Q2变化", "批价是否守住830", "经营现金流是否转正"]
```

---

## 七、建设顺序

1. **Phase 1**：Layer 1 engine（audit_engine.py + audit_rules.yaml）。输出 flags_matrix.yaml。这一步完成后就已经可以回答"我的 coverage 里谁现在最危险"。
2. **Phase 2**：audit_data_toolkit.py 核心函数。重点：get_annual_report_chunk（年报 chunk 预处理管线）、get_peer_flag_values（对接 ModelKing 数据库）。
3. **Phase 3**：前4个 P0 playbook（DSRI_HIGH, CFO_NI_DIVERGENCE, CONTRACT_LIABILITY_DECLINE, DEPOSIT_LOAN_MISMATCH）+ Layer 2 agent 执行框架。
4. **Phase 4**：Layer 3 synthesis + 输出格式。
5. **持续迭代**：每次真实暴雷事件发生后，回测 playbook 覆盖度，补充遗漏的假设或取证路径。
