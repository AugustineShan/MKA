# /da 重资产折旧摊销排程 Skill 设计

> 状态:设计稿(brainstorming 产出,待 spec-review + 用户复核)
> 日期:2026-06-24
> 关联:calc.py / forecast.py / defaults_gen.py / yaml1_cleaner.py / annual_report_reconciler.py

## 0. 背景与定位

### 0.1 问题
现有 calc.py 对所有公司用**单一折旧率机械滚动**:`depreciation = prev_fix × depr_rate`,`capex = revenue × capex_pct`。对轻资产/稳态公司够用,但对重资产公司(产能爬坡、在建工程占比高、capex 项目制、资产类别年限差异大)失真:一台机器(8-12 年)和一栋厂房(10-40 年)用同一个 depr_rate 滚,扩张 capex 投下去要等转固才起跳折旧——这些都被单一比率抹平了。

### 0.2 机会
年报里**客观存在且权威**的折旧摊销细节(固定资产明细表分大类的原值/累计折旧/本期增减、会计政策的折旧年限残值率、在建工程明细、无形资产明细),对人类分析师是噩梦(几十行跨多个附注、单位混乱、口径要交叉核对),但恰恰是 LLM 的绝对强项。

### 0.3 定位
`/da` 是**人机交互的"事实抽取 + 假设商议"编排器**,不是计算器。计算永远归 Python(`da_roll.py`)。skill 全部内容围绕"怎么把年报里人啃不动的东西读干净,再怎么和分析师商议出未来假设"展开。

**是什么**:重资产公司的 DA+capex 专用通道。
**不是**:不生成折旧数字(da_roll 的事)、不替代 /ka 的收入判断、不碰 raw 数据。
**该用**:重资产、产能爬坡、在建工程占比高、capex 项目制的公司。
**不该用**:轻资产、稳态、defaults 的 capex_pct+depr_rate 已够用的公司(否则把简单问题复杂化)。

### 0.4 与项目第一原则的同构
TuShare 缺口用 reconciler 拉年报补全;DA 细节也用 LLM 从年报扒。LLM 当 pipeline 一环,可观测、确定性、不静默失败。声明式驱动(结构由公司年报声明,不焊死任何公司形状),换任何公司只要年报披露了就能跑。

## 1. 模式与开关

- **轻资产(默认)**:`da_schedule.yaml` 不存在 → calc 走现有 `prev_fix × depr_rate` + `capex = revenue × capex_pct` 路径,**完全不动**。
- **重资产**:`da_schedule.yaml` 存在且顶层 `enabled: true` → forecast.py 编排 da_roll 注入。
- **base 对齐**:`da_schedule.base_year` 必须 = `defaults.base_period`。错位 → 报错停止,**不在错位数据上滚**(DA 存量快照和 clean_annual base 期必须同一年)。
- **回退保证**:`enabled: false`、da_schedule 缺失、或 da_roll 失败 → 回退轻资产路径,**不阻塞现有公司**。

## 2. 前置依赖检查

开工前确认:
1. 年报 Markdown 在不在(缺则 `python -m src.report_downloader --ticker {t} --force-markdown`)
2. clean_annual 配平没有(exit 3 未闭合就停,**不在脏数据上建 DA**)
3. `公司判断和最新观点.md` 读了没(thesis 锚点,先读不覆写,缺失报错停止——平移 ka 的开工纪律)
4. `defaults.yaml` + `base_period` 确定

## 3. 第一阶段:并行事实抽取 → `da_facts.json`

LLM 强项区。复用 reconciler 那套基础设施。

### 3.1 并行编排
按"**附注类型 × 年份**"铺 subagent,每个窄上下文单一目标:
- 固定资产明细表 × 近 5 年
- 在建工程明细表 × 近 5 年
- 无形资产明细表 × 近 5 年
- 生产性生物资产明细表 × 近 5 年(乳业/农业公司)
- 会计政策年限残值率表 × 最新年

### 3.2 每个 subagent 的抽取契约
- 给定 schema,**只填表不推算**。
- 抽不到 → 留 `null` 标 `missing`,**绝不补零**(补零 = 静默造假)。
- 每个数字带 `source_year` + 附注锚点(md 行号/章节)。

### 3.3 自校验恒等式
roll-forward 闭合检查,逐类逐年验真:
```
期初净值 + 本期增加(购建/转入) − 本期折旧 − 本期减少(处置/转出) − 减值 = 期末净值
```
不闭合 → flag(写进 `da_facts.json.roll_forward_checks`),不静默放行。

### 3.4 产物纯净
`da_facts.json` **只装事实,不装假设**。年限/残值率/原值/累计折旧/本期增减都是年报披露的客观值。任何"未来"的东西(扩张计划、转固节奏)不进 da_facts。

### 3.5 复用基础设施
- `call_llm`(annual_report_utils.py) + GLM glm-5.2 `thinking:disabled`(防烧 reasoning token 截断)
- `parallel_map`(并发,fallback 降 3,429 退避 30/60/90s)
- `find_line` / `compact_window`(年报 md 切片定位)
- `annual_markdown_path`(年报路径查找)
- 防脏守卫:候选字段集 + 残差闭合闸门 + add_override 拒绝非0(借鉴 reconciler 三层防脏)

### 3.6 evidence 落盘
`da_facts.json` + 时间戳副本落 `Agent/recon/da_facts_YYYYMMDD_HHMMSS.json` + `da_facts_latest.json`。可追溯。

## 4. 第二阶段:商议协议 → `da_schedule.yaml`(灵魂)

### 4.1 先押再问
LLM 读 `da_facts.json` 后,**先基于历史结构提一版完整默认假设**,再逐项征求分析师确认。不是空问"你想怎么设",而是"我看历史是这样,我建议这样,你改不改"。

### 4.2 拍板才落盘
分析师确认前**不写** `da_schedule.yaml`。

### 4.3 capex 商议六点(按序)
1. **摆事实定基线**:LLM 先报客观情况——过去 5 年 capex 多少、capex/收入比区间、capex/D&A 比区间、在建工程余额趋势、capex 是平滑还是阶梯状。这是共同事实基础。
2. **维持性 capex,确认而非商议**:LLM 说"维持性 capex 我建议取 da_roll 的存量稳态折旧(base 水平),约 X 亿/年"。派生项,分析师点头即可,不纠结。
3. **扩张性 capex,真商议焦点**:把分析师脑里的产能 thesis 翻译成排程。
   - 有没有管理层指引?LLM 先报从年报/纪要读到的管理层 capex 计划数(若有),问信不信、用不用。有指引时最强先验。
   - 未来扩张的实物计划?"未来三年新增多少产能?建几个牧场/几条产线/多少万吨?"——人话,分析师回答核心。
   - 单位投资额?LLM 从历史在建工程单位成本估,分析师校准。
   - 节奏?分几年投、哪年多。决定 `capex_plan` 逐年形状。
4. **转固时滞(capex→未来折旧的桥)**:"这些扩张投资哪年完工转固、开始计提折旧?"LLM 明确确认 `cip_to_fixed` 节奏。今天投的 growth_capex 趴在 cip 不折旧,转固那年才起跳。**漏了这一问 capex 和 DA 脱钩,重资产模型白做**。
5. **终值稳态假设**:"长期看稳态时 capex 大概是 D&A 的几倍?"通常成熟期回到 ratio≈1(只维持)。决定显式期后终值怎么接,交接点 FCFF 不跳变。
6. **不确定性处理**:凡说不准的(管理层没指引、产能规划模糊),LLM 主动标"待校准",提示这是模型最大敏感点,**不假装确定**。只有"声明式估算·待校准"或"待补旗"两条合法出路。

### 4.4 诚实于不确定
贯穿全程。拿不到的值只有两条合法出路,不准 LLM 编。

## 5. 第三阶段:落盘与收口

### 5.1 产物位置
`companies/{公司}_{代码}/Agent/da_schedule.yaml`(和 `defaults.yaml` / `yaml1*.yaml` 并列在 Agent/)。单公司单文件,覆盖式更新;旧版归档 `Agent/DAhistory/`(加时间戳后缀防覆盖,平移 ka 的归档纪律)。

### 5.2 和 yaml1 的关系
**正交,但 capex 这一个交接点锁定**:
- yaml1 管:收入/毛利/费用/三类摊销(无形/使用权/长摊)绝对值。
- da_schedule 管:PP&E 的 DA(分类别年限滚动)+ capex(维持+扩张排程)。
- **capex 单一来源**:重资产模式下 capex 唯一来自 da_roll(见 §8)。yaml1 的 `capex_pct` 在重资产模式下**显式禁用并告警**(两套 capex 来源不能并存)。
- 其余字段互不覆盖。

### 5.3 收口报告
汇报:哪些假设是历史延续、哪些是分析师拍的、哪些标了待校准;roll-forward 闭合情况;末年扩张归一化断言(见 §9)。

## 6. `da_roll.py` 确定性滚动

纯 Python 确定性执行器,独立可测。输入 `da_schedule.yaml`(结构)+ base_bs(base 年末各类原值/累计折旧,从 da_facts),输出逐年 da_series。

### 6.1 折旧算法:分类别 cohort 年限平均法(直线法)
符合会计政策(新乳业年报:"年限平均法")。

- **每类维护 cohort**:存量 cohort(base 年末原值/累计折旧/残值率/年限)+ 各年新增 cohort(转固的扩张 capex,按该类年限)。
- **每 cohort 年折旧额 = 原值 × (1 − 残值率) / 年限**,直线衰减到残值,折尽停。
- **类折旧 = 各 cohort 折旧之和**;PP&E 总折旧 = 各类之和。

### 6.2 存量永续更新(关键设计——解决熔化+折尽悬崖)
**存量 PP&E 按永续更新建模,不走折尽停**:
- 存量折旧维持在 **base 年水平不熔**(going concern 持续替换:每年退役=每年补充,净折旧稳定)。
- **不追踪存量 vintage**(已知近似,见 §11)——存量 vintage 异质被永续更新假设吸收,不制造"折尽悬崖"。
- **维持性 capex = 存量稳态折旧**(base 水平),FCFF 里与存量折旧**对冲净 0**,不新增 cohort、不进基数记账(省掉维持 cohort 簿记)。

**为什么必须这样**:若维持性 capex 不进基数、存量 cohort 折到残值就停,则存量资产池只减不补,在显式期内逐年熔掉。长年限资产(房屋 20-40 年)影响有限,但**短年限资产(奶牛 5-8 年)会在 5 年内熔到零**——产奶产能凭空消失,和 yaml1 收入假设打架(收入还在涨,产能资产在化掉),BS 资产基数萎缩、模型逻辑不自洽。永续更新让存量基数走平、折旧稳定,这才是 going concern 的正确形态。FCFF 数学不变(稳态下维持 capex 与其自身折旧对冲):

```
FCFF 维持部分净效果 = +存量稳态折旧(da 加回) − 维持性 capex(=存量稳态折旧) = 0
```

> **注**:存量熔化是否"经 depreciation→EBIT→NOPAT 泄漏进终值、系统性高估估值",取决于 depreciation 是否进 IS(见 §9.2 open question)。当前 calc.py 里 depreciation 不进 IS(只在 CF/FCFF 加回),故熔化的主要危害是 BS 基数萎缩 + 与收入假设不自洽;若重资产模式让 ppe_depreciation 显式进 IS(gpm loaded),则另有经由 nopat 的终值泄漏路径。

### 6.3 扩张性 capex:进 cip → 转固 → 显式 cohort
- 扩张 capex 进 `cip_balance`(在建工程,不折旧)。
- 按 `cip_to_fixed` 节奏转入该类 cohort,**转固年起折旧**。
- 扩张 cohort 是显式 vintage,按类别年限直线折旧,折尽停合理(扩张项目到期退役是真实的)。

### 6.4 存量净增率 override(问题④语义定死)
默认存量净增率 = 0(永续更新,存量净值/折旧维持 base 水平)。若分析师给存量逐年净增率 `g`:
> **net 增率同时作用于存量净值与存量折旧**——存量净值与存量折旧都按 `g` 逐年增长。

这建模存量有机增长(产能随时间缓慢扩张,非项目制)。**不允许只涨基数不涨折旧**(基数与折旧脱钩 = 又一个静默不一致)。

### 6.5 总折旧装配
```
总 PP&E 折旧 = 存量稳态折旧(base 水平 × (1+g)^t) + 扩张新增折旧(逐年扩张 cohort 之和)
```
注意:da_roll 只产出 **`ppe_depreciation`**(PP&E 折旧,**不含三类摊销**)。总 DA 的装配(`ppe_depreciation` + 三类摊销)留在 calc 一处显式做(见 §8),**不用 `da_total` 这种误导命名**(谁加三类、加没加极易出错)。

### 6.6 输出字段
```
ppe_depreciation          # 存量稳态 + 扩张新增 cohort 折旧之和,不含三类
ppe_depreciation_by_cat   # 分类别(审计/展示)
fix_assets_net            # 存量稳态净值 + 扩张 cohort 累计净值
fix_assets_gross          # 审计
accumulated_dep           # 审计
cip_balance               # 在建工程余额(扩张 capex 趴此至转固)
ppe_capex                 # 维持+扩张合计(给 FCFF)
ppe_capex_split           # {maintenance, expansion}(审计/展示)
```

## 7. calc.py 接入(forecast.py 编排注入)

### 7.1 编排层(forecast.py)
```
clean_yaml1(yaml1, defaults, clean_annual)
  → 检测 da_schedule.yaml 存在且 enabled:true
    → da_roll(schedule, base_bs) 产出 da_series
    → 注入 forecast_params(新增 da 字段)
  → build_forecast_statements(forecast_params)
  → value_from_statements(...)
```
forecast.py 是唯一编排入口(符合现有设计)。da_roll 作为编排步骤,在 calc 之前跑。

### 7.2 calc 分支(build_balance_sheet / build_cash_flow / FCFF)
calc 检测 forecast_params 里有无 da_series:
- **有 da_series(重资产)**:
  - BS:`fix_assets` 取 `da_series.fix_assets_net`(不滚 `prev_fix × depr_rate`)
  - CF 的 da 加回:`ppe_depreciation` + 三类摊销
  - FCFF 的 capex:`da_series.ppe_capex` + 三类 reinvest(**不再 `revenue × capex_pct`**)
  - FCFF 的 da:`ppe_depreciation` + 三类摊销
- **无 da_series(轻资产)**:现有路径,完全不动。

calc 其他(营运资本/现金 plug/留存/三类摊销绝对值)两个模式都照旧。**calc 仍是纯算账核,不感知 `da_schedule.yaml`,只消费 forecast_params 里的 da 注入**。

## 8. 轻重模式 capex/DA 装配对照表

> 最容易出静默 bug 的地方。BS 和 CF 的 capex 必须同源,否则静默出错。

| 维度 | 轻资产(无 da_schedule) | 重资产(da_schedule.enabled=true) |
|---|---|---|
| **capex 来源** | `revenue × capex_pct`(yaml1 可 override) | `da_roll.ppe_capex`(维持+扩张)+ 三类 reinvest |
| **yaml1 capex_pct** | 有效 | **禁用并告警** |
| **BS fix_assets 滚动** | `prev_fix + capex_ppe − depreciation`(`depreciation=prev_fix×depr_rate`) | 取 `da_roll.fix_assets_net`(da_roll 内部滚动) |
| **PP&E 折旧** | `prev_fix × depr_rate`(单一比率) | `da_roll.ppe_depreciation`(存量稳态+扩张 cohort) |
| **三类摊销** | defaults 绝对值(yaml1 可 override) | 同左(不变) |
| **总 DA 装配** | `depreciation + 三类`(calc) | `ppe_depreciation + 三类`(calc 一处显式) |
| **CF: CFO 加回 da** | `n_income + da − Δnwc` | 同左(da 来源不同,公式同) |
| **CF: cfi(投资活动)** | `−capex`(= `−revenue×capex_pct`) | `−(da_roll.ppe_capex + 三类 reinvest)` |
| **FCFF: capex** | `revenue × capex_pct`(合并) | `da_roll.ppe_capex + 三类 reinvest` |
| **FCFF: da** | `depreciation + 三类` | `ppe_depreciation + 三类` |
| **终值 da** | 末年 `depreciation + 三类` | 末年 `ppe_depreciation + 三类`(须归一化,见 §9) |
| **终值 capex** | `da × ratio` | `da × ratio`(同) |

**不变量**:重资产模式下,BS 的 fix_assets 滚动与 CF/FCFF 的 capex **同源**(都从 da_roll),不出现"BS 用 da_series、FCFF 还按 capex_pct"的静默打架。

## 9. 终值交接规格(含瞬态归一化)

### 9.1 终值公式
```
终值 da = da_roll 末年总 DA = 末年 ppe_depreciation + 末年三类摊销
terminal_fcff = last_nopat + last_da × (1 − terminal_capex_da_ratio)
terminal_value = terminal_fcff × (1 + g) / (wacc − g)
```

### 9.2 "da 在终值抵消"是错觉(关键,依赖 gpm loaded 假设)
ratio=1 时 `terminal_fcff = nopat`,da 表面消失。但 `nopat = ebit × (1−tax)`,ebit 已扣 da——**末年 da 的水平经由 nopat 全额流进终值**。da 没抵消,只是换了通道。

**前提声明(重要)**:此论证依赖 **gpm 是含折旧的 loaded margin** 这一隐含语义。calc.py 里 `oper_cost = revenue × (1−gpm)`,`depreciation` 不进 IS(不扣 oper_cost/ebit/nopat),只在 CF/FCFF 加回。这只有在 gpm 已含折旧时才自洽(折旧进成本压低毛利,+da 在 CF 是非现金加回)。defaults_gen 的 gpm = 1 − oper_cost/revenue(历史毛利含历史折旧),符合 loaded 语义。

**若 gpm 视作折旧前毛利**(分析师显式设 ex-depreciation):ratio=1 时 `last_da` 在 `terminal_fcff` 中精确归零,`last_da` 水平对 terminal_value 无关,§9.3 的扭曲机制退化为仅 ratio<1 情形(`last_da×(1−ratio)` 直接进终值),且方向与 loaded 相反。

**🔴 重资产模式 open question(留 planning,需用户定)**:da_roll 产出的 `ppe_depreciation`(分类别真实滚动)与 gpm(loaded,含历史折旧)里的折旧部分如何对齐——base 年应一致(都=历史折旧),预测年 da_roll 随 cohort 变化而 gpm 折旧部分不变,存在脱钩/双重计算风险。需在 planning 定:重资产模式是否让 `ppe_depreciation` 显式进 IS(gpm 改 ex-depreciation,IS 新增折旧行),还是保持 gpm loaded、接受 da_roll 与 gpm 折旧部分的小不一致。这决定 §9.3 机制是否成立、归一化门(§9.4)的保护范围。

### 9.3 末年 da 必须是稳态 da(真正脆弱点)
① 修的是"末年 da 不萎缩"(存量永续更新保证)。但终值真正脆弱点是**末年 da 是不是稳态 da**——显式期在扩张半途结束时,末年 da 是爬坡瞬态值,会扭曲终值。扭曲的具体机制和方向取决于 IS 语义(见 §9.2):
- **gpm loaded(ppe_depreciation 进 IS)**:末年 da 经由 nopat 流进终值。末年 da 偏低(cohort 未成熟)→ nopat 偏高 → 终值高估;末年 da 偏高(扩张峰值)→ nopat 偏低 → 终值低估。
- **gpm ex-depreciation(当前 calc.py 语义,depreciation 不进 IS)**:ratio=1 时 last_da 在 terminal_fcff 精确归零,末年 da 水平不影响终值;仅 ratio<1 时 `last_da×(1−ratio)` 进终值,末年 da 偏低 → 该正项偏小 → 终值偏低(方向与 loaded 相反)。

两种语义下末年 da 非稳态都会扭曲终值(方向不同),归一化门(§9.4)在两种语义下都有价值——保证末年 da 是稳态 da,消除瞬态扭曲。

### 9.4 归一化收口检查
解法不是改终值公式,是**保证末年 da 是稳态 da**:
- 显式期跑到 **cip 清空 + 最近一批扩张 cohort 过爬坡**(转固后折旧进入稳态段)再接终值。
- 收口报告显式断言"**末年扩张已归一化**"。
- 不满足 → flag(不静默放行)。

### 9.5 残留风险
若显式期怎么都不够长(扩张周期超长,cip 永远转不完)→ 终值 da 是瞬态,flag 给分析师决定:拉长显式期,或接受瞬态偏差并在收口报告标注方向(高估/低估)。

## 10. 全程纪律

1. **事实↔假设分离**:`da_facts.json`(事实,LLM 扒,只填表不推算,抽不到留 null)vs `da_schedule.yaml`(假设,先押再问拍板才落盘)。
2. **口径对齐**:字段名和 clean_annual 一致(用 TuShare 官方字段名 + da_roll 内部字段)。
3. **capex 不走 revenue×pct**(重资产模式 capex 是项目制绝对值排程)。
4. **capex 单一来源**:重资产模式下 BS 与 CF/FCFF 的 capex 同源(da_roll),yaml1 capex_pct 禁用。
5. **终值交接平滑**:capex/D&A ratio→1,末年 da 归一化。
6. **回退保证**:enabled=false/da_roll 失败→回退轻资产,不阻塞现有公司。
7. **审计**:da_facts/da_schedule/da_roll 产物落 `Agent/recon`+`.modelking`,可追溯。
8. **诚实于找不到**:exit 3 不改判、找不到证据不凑数、拿不到的值标"待校准/待补旗"。

## 11. 已知近似

写明,不静默:

1. **存量 vintage 异质被永续更新吸收**:base 年只有各类期末原值/累计折旧总数,无 vintage 分布。存量走永续更新(折旧维持 base 水平不折尽),所以单 cohort 近似无害——存量不折尽,就没有"折尽悬崖"。显式期不太长时可接受。
2. **存量永续 vs 扩张折尽的不对称**:存量永不退役(永续更新)、扩张 cohort 折尽退役——长期看不自洽(扩张资产到期也该被替换变成新存量)。被**显式期长度兜住**(扩张期内到不了 EOL)+ **终值重锚消化**。写一行当已知近似。
3. **末年 da 瞬态**:见 §9.3-9.5。显式期在扩张半途结束时末年 da 非稳态,靠归一化收口检查兜,残留风险 flag。

## 12. 文件契约

### 12.1 `da_facts.json`(事实,LLM 产出)
```json
{
  "company": "新乳业_002946",
  "base_year": 2024,
  "extracted_at": "...",
  "policy": {
    "ppe_categories": [
      {"name":"房屋及建筑物","life_years":[10,40],"salvage_rate":[0.03,0.05],"annual_dep_rate":[0.0238,0.0970]},
      {"name":"机器设备","life_years":[8,12],"salvage_rate":[0.03,0.05],"annual_dep_rate":[0.0792,0.1213]}
    ],
    "biological_categories": [{"name":"奶牛","life_years":[4,5],"salvage_rate":[0.20,0.35]}],
    "intangible_categories": [{"name":"土地使用权","life_years":[30,50]},{"name":"软件及其他","life_years":[5,10]}],
    "source_year": 2024
  },
  "ppe_detail": {"2024":{"房屋及建筑物":{"gross":..,"accum_dep":..,"impairment":..,"net":..,"period_increase":..,"period_decrease":..,"period_dep":..}}, "2023":{...}},
  "cip_detail": {"2024":{...}, ...},
  "intangible_detail": {"2024":{...}, ...},
  "biological_detail": {"2024":{...}, ...},
  "roll_forward_checks": [{"year":2024,"category":"房屋及建筑物","opening_net":..,"increase":..,"dep":..,"decrease":..,"impairment":..,"closing_net":..,"residual":..,"closed":true}],
  "missing_flags": [{"year":2023,"category":"..","field":"period_dep","reason":"not found in md"}],
  "evidence_anchors": [{"year":2024,"category":"房屋及建筑物","md_line":16108,"note":"会计政策17"}]
}
```

### 12.2 `da_schedule.yaml`(假设,商议后落盘)
```yaml
enabled: true
base_year: 2024          # 必须 = defaults.base_period
generated_at: ...

ppe:
  存量策略:
    mode: perpetual_renewal       # 默认永续更新
    net_growth_rate: 0.0          # 存量逐年净增率,默认0(稳态);net增率同时作用于存量净值与存量折旧
  categories:
    - {name: 房屋及建筑物, life_years: 20, salvage_rate: 0.05, base_gross: .., base_accum_dep: ..}
    - {name: 机器设备, life_years: 10, salvage_rate: 0.05, base_gross: .., base_accum_dep: ..}

expansion_plan:                   # 分析师商议的扩张 capex 排程
  2025:
    capex_by_cat: {机器设备: 50000, 房屋及建筑物: 200000}
    cip_to_fixed: {机器设备: 30000}      # 当年转固
  2026:
    capex_by_cat: {房屋及建筑物: 300000}
    cip_to_fixed: {房屋及建筑物: 200000, 机器设备: 20000}
  # 不变量:任一年任一类 累计 cip_to_fixed ≤ 累计 capex_by_cat(cip 余额非负,da_roll 强制校验)

terminal:
  capex_da_ratio: 1.0             # 稳态 capex/D&A
  perpetual_growth: 0.03

# 三类摊销(无形/使用权/长摊)不在此文件,仍由 yaml1/defaults 管
```

### 12.3 da_roll 产物(注入 forecast_params)
逐年 list,每元素含 §6.6 全部字段。

## 13. 审计与回退

- `da_facts.json` + 时间戳副本 → `Agent/recon/`
- `da_schedule.yaml` → `Agent/`,旧版 → `Agent/DAhistory/`
- da_roll 产物 → `Agent/.modelking/da_series.json`(内部,可审计)
- 回退:enabled=false / da_schedule 缺失 / da_roll 异常 → forecast.py 捕获,回退轻资产路径,写 warning,不阻塞

## 14. 测试策略

1. **da_roll 单元测试**(独立可测):
   - 存量永续更新:base 水平折旧恒定,净值不熔
   - 扩张 cohort:转固年起折旧,折尽停
   - 存量净增率 g:净值与折旧同比例涨
   - roll-forward 闭合:期初+增加−折旧−减少−减值=期末
2. **calc 重资产分支**:fix_assets/depreciation/capex 同源 da_roll,BS 配平,CF 桥接平
3. **回退保证**:无 da_schedule 时 calc 输出 = 现有路径输出(bit-exact)
4. **终值归一化**:末年 cip 未清空 → flag
5. **base 对齐**:base_year ≠ base_period → 报错
6. **yaml1 capex_pct 禁用**:重资产模式下 yaml1 给 capex_pct → 告警
7. **乳业主用例**:奶牛(短年限)不熔化,产能资产不消失

## 15. 不做什么(边界)

- 不升级三类非 PP&E 摊销(无形/使用权/长摊保持现有绝对值外推,YAGNI;某公司某类特别大后续再扩)
- 不做资产组 vintage 全追踪(存量走永续更新吸收)
- 不替代 /ka 收入判断
- 不碰 raw_tushare
- 不自动判定轻重模式(分析师决定是否跑 /da)
- 不在 2010 前年报上跑(披露稀疏,对得不偿失——平移 reconciler 2010 闸门)
