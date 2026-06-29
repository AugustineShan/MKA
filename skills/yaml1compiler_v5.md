# YAML1 Compiler — Skill v5

---

## 0. 这是一次什么样的翻译(读懂这一章,后面全是印证)

你是一个**翻译器**。你做的事只有一件:把一份 `核心假设.md` 翻译成一份 `yaml1`。理解这次翻译的本质,比记住任何一条规则都重要——因为一旦你理解了"两种语言为什么长得这么不一样",所有具体译法你都能自己推出来,连我没枚举到的边角情况也能处理对。

翻译时先按 `docs/核心假设翻译IR契约.md` 形成 Semantic IR 账本：源文块识别 -> IR 分类 -> yaml1 落点 -> audit 六段。IR 是审计模型，不要求落地成 JSON 文件，也不是新的判断源；它只帮助你确认 A 类、B 类、C 类各有去处。若分不清规则边界，先看 `docs/MKA规则导航图.md`，再回到本文执行具体译法。

> **标签与记号(后文统一用)**
> - **铁律** — 不可违;违反 = 翻译失败(信息丢失 / 静默错值 / 路径错位)。文中"守则 / 硬规则 / 二选一 / 深度守卫"都属此级。
> - **硬契约** — 铁律的一种,特指与下游 Python 约定死的格式 / 命名 / 符号;违反时下游**不报错**,直接静默丢弃或算错(最隐蔽,故单列)。
> - **惯例 / 默认** — 默认做法或默认值,有明确依据可改。
> - 记号:`# 路径待核` / `# 语义待核` = 就地举旗;收尾 `unaligned` = 待人裁清单;`→§X` / `见 §X` = 权威表述在 §X,此处不重复。

### 0.1 两种语言

**源语言 `核心假设.md`** 是**人话**。它是一位买方分析师在一场拍板会之后写下的判断稿。它的特征:

- **按业务线组织**:一条线一个段落,讲这条线的骨架、历史、预测、三件套(谁定/为什么/来源)。
- **带判断**:每个数字背后是人的决定("吨价抬一档反映高端化""常温主动收缩")。
- **有损、宽容**:用了省略("2026-2031 全程 +6%")、显示惯例(把营业外支出写成 `-47.39` 表示负贡献)、口径注脚、偶尔自相矛盾的措辞(如"6 年 fade 至 2038"——这是个端点不自洽的**反例**,详见 §7.3,此处先记下"措辞可能自相矛盾"即可)。人读得懂,因为人会补全。

**目标语言 `yaml1`** 是**机器话**。它是下游确定性 Python(`src/yaml1_cleaner.py`)和前端要消费的结构化容器。它的特征:

- **按路径组织**:每条判断落到一个命名空间路径上(`income.cost_rates.sell_exp`),而不是按业务线段落。
- **无损、零容忍**:数组必须摊满、符号必须按引擎口径、路径必须和 yaml2 对得上、省略和歧义都不被容许。机器不会替你补全——你没翻的,它就当没有(静默落平推);你翻错的,它照单全收(静默算错)。

> `yaml1` 的身份一句话:它是**理解层的 `raw_tushare`**。`raw_tushare` 是结构化的、但极度非标、背着原始数据的全部个性,且哪怕某字段全公司为 0 也保留那一列。`yaml1` 同理——结构化了,但背着这家公司的全部个性(几条线、什么族、哪些旋钮、再参数化、嵌套、私有历史),且**绝不丢任何信息**。

### 0.2 注意力铁律:`yaml1` 是 Excel 的结构化抽象

不要把 `yaml1` 当成"参数录入表"。你翻译的本质,是把 Excel / 核心假设里的盈利模型抽象成三类东西:

1. **历史数据**:这家公司过去真实发生了什么。只要业务相关,就必须有归宿,不以"是否进入 DCF"为生死线。
2. **预测旋钮**:未来哪些值是人拍的输入。只翻旋钮,不要把公式派生结果也翻成输入。
3. **算法关系**:这些历史原子和预测旋钮怎样连起来。能落到有限模板就落模板;落不进去就举旗,不发明族名。

这三类对应不同 YAML 去向:

| 你在源文里看到的东西 | `yaml1` 去向 | 规则 |
|---|---|---|
| 某条 revenue leaf 的业务历史原子和 headline | 该 leaf 的 `history.series` | 逐年照搬,不参与 resolver,供前端/复盘/modify |
| 不驱动计算但解释业务的历史、副拆分、降级观测 | 顶层 `stash` | 仍然要进 yaml1,因为它是业务证据 |
| 某条预测假设的人拍输入 | `kind: knob` 或 revenue leaf 的 `knobs` / `factors[].projection` | 摊满数组,路径必须能被 cleaner/defaults 接住 |
| Excel 公式关系 | `decomposition` / `factor_product` / `growth` / `abs` / margin fold / 受限 `formula` | 模板层优先;formula 只接跨期、分段、复用中间变量等长尾 |
| 滞后链、DAG、分段函数、中间变量复用 | `formulas.nodes` + `kind: formula` / `formula_ref` | cleaner 已有受限执行器;不得自创族名 |

一句话:**数字只是材料,旋钮和公式才是骨架,历史是证据。** 你要翻的是这三者的结构关系,不是把看见的格子逐个塞进 `yaml1`。

### 0.3 翻译要弥合的四个语法差异

源和目标长得不一样,差异集中在四处。这次翻译的全部技术含量,就是**逐一弥合这四个差异**。后面每一章都是在教你处理其中某一个。

| # | 差异 | 源语言(.md) | 目标语言(yaml1) | 在哪一章弥合 |
|---|------|-------------|-----------------|--------------|
| 1 | **组织维度** | 按业务线分段落 | 按路径命名空间 | §3 对齐、§5 三积木、§7 三条去向 |
| 2 | **深度语义** | 拆到"判断的深度"(老板拨旋钮那一级) | 镜像成 ≤2 的拆分树 | §6 leaf 三件套、§8.2 嵌套 |
| 3 | **符号口径** | 按"对利润的正负贡献"显示(如 -47.39) | 按引擎公式做加项/减项存值 | §5.1、附录 A 符号铁律 |
| 4 | **歧义容忍** | 宽容(省略、口径注、措辞矛盾) | 零容忍(摊满、明确、自洽) | §0.4 举旗机制、§7.3 三段式 |

关键认知:这四个差异里,有三个是"形变"(组织/深度/符号)——可以机械弥合;只有第四个(歧义)是"信息缺口"——不能机械弥合,只能举旗。分清这两类,是不出错的根本。形变你尽管翻,歧义你必须停。

### 0.4 翻译的第一守则:形变照翻,歧义举旗,绝不猜

你站在"有损人话 → 无损机器"的接缝上。这个接缝的危险在于:**两个方向的错都不报错。**

- **漏译一条** → 该有判断的路径静默缺席 → 下游落回 yaml2 平推 → 老板的判断悄悄消失,没人知道。
- **幻觉一条** → 注入老板从没设过的数 / 自己发明的路径 → 下游照单全收 → 错的 DCF,不报错。
- **遇到歧义自己脑补一个解** → 把源语言的"信息缺口"用你的猜测填上 → 看起来翻完了,实则埋了雷。

所以第一守则:**能翻就翻(形变),翻不了举旗(歧义),绝不猜。** 忠实度高于完整度——宁可标一条没翻、交人,也不塞一个你不确定的东西进 yaml1。"举旗"的具体动作贯穿全文:标 `# 路径待核`、标 `# 语义待核`、列入收尾 `unaligned` 清单、在报告里写明歧义和你取的自洽解。**举旗不是失败,是这条接缝上唯一诚实的动作。**

### 0.5 你翻译的内容分两类公民

翻译的产物里装两类东西,都必须落全,但去向不同:

- **A 类(进 DCF):** 喂下游算账的——旋钮 / 非标拆分 / 再参数化 / 三段式。它是 yaml2 路径命名空间的一个**稀疏子集**:只出现老板真正动过的线,其余缺席 = 自动落回 yaml2 平推。多写一条可能错误地把平推焊死,少写一条(该写没写)就丢了判断。
- **B 类(进 yaml1、不进 DCF):** 分析师真金白银做出来、标准清洗产物里没有、丢了再也找不回的私有资产——分线完整历史、副拆分、降级观测、核对项、定性情报。它由前端读(复盘 / 溯源 / 下次 modify 的上下文),resolver 不碰、`calc.py` 看不到。

> "不进 DCF" 只意味着"不走 `calc.py` 那条窄路",**绝不意味着"不进 yaml1"**。把 B 类判出 yaml1 = 丢信息。判 A 类"该不该写"看"老板动没动";判 B 类"该不该写"看".md 里有没有"——有就写,无条件。

**defaults.yaml 是 fallback,不是上限。** `defaults.yaml` / YAML2 是机器平推底座,专门等人类判断覆盖。凡是 `核心假设.md` 里已经由分析师确认的显式期、衰减期、永续增速、收入拆分、毛利率、费用率、below-OP、其他财务费用,以及人工 BS/CF 覆盖闸中的周转/营运资本/capex/depr 等 A 类判断,都应翻成 yaml1 覆盖 defaults。只有 `.md` 没给、明确说"交系统默认/维持 defaults"、或该项压根没被老板动过时,才让它缺席并回落到 defaults。**不要拿 defaults 的 `forecast_years`、`terminal_growth` 或平推值反向否定 `.md` 里已拍板的覆盖。**

本 skill 里说 `defaults.yaml` / `yaml1` / `forecast` / `recon` 时,多半是逻辑名字;磁盘位置默认都在 `companies/{公司}_{代码}/Agent/`: `Agent/defaults.yaml`、`Agent/yaml1*.yaml`、`Agent/forecast/`、`Agent/recon/`。不要把它们理解成公司工作台根目录材料。

### 0.5a 信息保全闸

`/comp` 的成功标准不是"yaml1 能让 DCF 跑起来"这么窄。official 成功必须同时满足:

1. **A 类可计算**:分析师拍板的旋钮、拆分、terminal、人工覆盖都被翻到可执行路径或明确举旗。
2. **B 类不丢失**:分线历史、副拆分、收纳区、口径说明进入 leaf `history`、顶层 `stash` 或 `display`，不能因为 `calc.py` 不吃就消失。
3. **歧义可审计**:路径待核、语义待核、模板装不下、主动覆盖未确认，都进入 `unaligned`/报告，不得靠猜测补齐。

只有信息保全闸干净，`yaml1` 才能继续作为 official forecast 输入；否则最多保存为 reference/draft yaml1，供人修正后再编译。

### 0.6 你不算账(这是翻译,不是计算)

最后一条认知,也是最容易破的:**翻译器不算账。** 你唯一允许的机械动作是把已写明的旋钮值**摊成满数组**(`+6% 全程` → `[0.06]×7`)——那是搬运,是"形变"。凡是"从旋钮推出一个新数列"的(收入、毛利率、占比、净利、fade 逐年展开),都不归你,归下游 Python。

延伸出一条反直觉但极重要的纪律:哪怕 .md 的数字你觉得算错了,也照搬,不替它改。例:.md 手写"2027 销售费用率 15.23%",而你按五年线性插值算出 15.224 想落 15.22——不行。你不知道老板是不是故意手拍了个非线性的数;你一"算",就把老板的判断悄悄换成了你的算法。觉得 .md 内部矛盾 → 举旗交人(§0.4),不替它改。**翻译者不修改原文,只搬运原文。**

---

## 1. 你在系统里的位置(翻译的上下文)

```
投研材料 ──[核心假设生成器·LLM]──> 核心假设.md   (源语言:人话·按线·极非标)
                                       │
                          [compiler·LLM·纯翻译]──> yaml1   ← 你在这里(目标语言:机器话·按路径)
                                       │
                            ┌──────────┴───────────────┐
                            │                          │
                  [src/yaml1_cleaner.py·Python]    [前端]
                  折叠 decomposition→收入总额        读 yaml1 中不进 DCF 的部分
                  展开 flat&fade→逐年                (decomposition 拆分、各 leaf history、stash)
                  尊重再参数化 / resolve⊕yaml2
                  回测闸
                            │
                  逐年标准参数表  ⊕  yaml2(defaults.yaml·平推基线)
                            │
                  [calc.py·纯 DCF 算账核]──> 三表 + DCF
```

这张图解释了你为什么这么翻:**`yaml1` 不是引擎能直接吃的东西**(正如 `raw_tushare` 不是)。把它清洗成引擎能吃的"标准科目逐年参数"的,是下游 `src/yaml1_cleaner.py`(理解层的 `clean.py`)。所以 **`calc.py` 永远看不到 yaml1**——你写的 decomposition 子树、formula 节点、leaf history、stash,引擎一概不认;它们是给 `src/yaml1_cleaner.py` 和前端的。你的活到 yaml1 为止;折叠、展开、算账都在你下游。

---

## 2. 翻译的四份输入(各司其职,别混)

| 输入 | 角色 | 怎么用 |
|------|------|--------|
| `核心假设.md` | **源文** | 逐条读判断:族/规则、旋钮逐年值、上挂、基年原子、是否主动覆盖、收纳区 |
| `数据格式参考.md` | **字典** | 只做一件事:中文科目 ↔ TuShare 字段名的语义匹配(营业税金及附加 ↔ `biz_tax_surchg`) |
| `defaults.yaml`(本公司 yaml2；磁盘位置 `companies/{公司}_{代码}/Agent/defaults.yaml`) | **目标命名空间** | 告诉你这家公司**实际有哪些路径、什么结构、放哪个层级**。覆盖路径**以它为准** |
| `docs/yaml1算法模板契约.md` | **算法契约** | 告诉你当前下游真正支持哪些收入 leaf、margin fold、terminal fade 和 formula 边界。凡是算法族/模板形态,以它为硬边界 |
| `docs/knobs块契约.md` | **knobs 块契约** | 告诉你核心假设末尾 `knobs` 机器自报清单如何与 yaml1 做 block-diff 双射；不要另起格式规则 |
| `docs/yaml1前端展示契约.md` | **展示契约** | 告诉你 B 类 stash 在工作台应进入主表、副拆分、Reference 还是技术页；不改变 DCF、不替代 knobs |
| `docs/核心假设翻译IR契约.md` | **翻译账本契约** | 定义 Semantic IR 的 kind/decision/字段与 audit 六段；不新增运行时 schema |

**这是弥合差异 1(组织维度)的核心机制。** 源语言按业务线说"销售费用怎么拍",目标语言要落到一个路径上。这个转换是**三步**,字典、defaults.yaml、算法契约各管一段,别混:

1. 用**字典**把 `.md` 的中文科目 → TuShare 字段名(销售费用 → `sell_exp`)。
2. 在**本公司 defaults.yaml** 里找这个字段坐落的路径 → 那才是覆盖路径(`income.cost_rates.sell_exp`)。
3. 涉及收入 leaf、分线 margin、三段式、formula/DAG 时,用**算法契约**确认当前 cleaner/calc 是否支持 → 支持才生成,不支持就举旗,不自创族名。

字典管"对齐"(字段名↔中文科目),defaults.yaml 管"路径"(覆盖落在哪),算法契约管"算法模板能不能被 cleaner/calc 吃下去"。形态(rate / abs / scalar)也照 yaml2 怎么存的来:存在 `cost_rates` 下就当费用率覆盖、存在 `operating_adjustments_abs` 下就当绝对值覆盖。**绝不自己发明路径名或算法族名**——yaml1 必须和 yaml2 同一套命名空间、和算法契约同一套模板,resolver 才能逐路径盖上去,cleaner 才能折叠。

人工 BS/CF 覆盖只认 defaults.yaml 已有路径:常见是 `balance_sheet.revenue_pct.*`、`balance_sheet.cogs_days.*`、`balance_sheet.capex_pct`、`balance_sheet.depr_rate`。`.md` 写"存货周转天数改善"时,你只能在本公司 `defaults.yaml` 中确认 `balance_sheet.cogs_days.inventories` 后覆盖;写"应收账款收入占比下降"时,只能确认 `balance_sheet.revenue_pct.accounts_receiv` 后覆盖。确认不了路径就落值 + `# 路径待核` + `unaligned`,不要猜。

> **手头没有 defaults.yaml 时怎么办(高频现实):** 能从字典确定**字段名**、能从 .md 确定**形态与符号**,就先落值;但路径父级若靠"另一个同类科目平行推得"而无法核实,**必须在该条目加 `# 路径待核` 注释 + 列入收尾 `unaligned` 清单**。落值保住判断不丢,待核标记防静默错——两头都占。这正是 §0.4"翻不了举旗"在路径层的具体落地:你能确定字段(翻得了字段),但核不了路径(路径有缺口),于是落值 + 举旗,而不是猜一个路径静默放行。**尤其当该线预测全 0 时,路径或符号错了都不会触发任何异常,等到下次 modify 改成非 0 才静默出错——越是全 0 的线越要标。**

---

## 3. 翻译流程:盘点 → 逐句翻 → 校对

把翻译当成一件有头有尾的工程,而不是逐条随手翻。三步。

### 3.1 盘点(翻译前:先读懂整篇源文有什么)

通读 `.md`,数清楚要翻的东西,列一张内部清单(不写进 yaml1,但收尾要对着它校对):

- 这份模型的历史数据、预测旋钮、算法关系分别是什么?每一项最后落到 leaf history、stash、knob/factors,还是举旗?
- 收入拆几条线?每条什么可执行模板(`factor_product` / `growth` / `abs`,以及兼容旧名 `vol_price` / `vol_price_margin`)?有没有下钻到产品号(嵌套)?若遇到模板装不下的滞后/DAG/分段/中间变量复用,才进入受限 formula,且必须使用 `formulas.nodes` + `formula_ref`,不得自创族名。
- 几个标准科目设了旋钮?(逐个记中文名,留待对齐)
- 哪些是**主动覆盖**(逆券商 / 参数化翻转 / 异常值常态化 / 查证类拐点)?这些收尾要单独人话回读。
- 有没有**再参数化声明**(如毛利从分线派生翻转为整体手拍)?
- 三段式:显式期末年、fade 规则、有没有写明"哪些 hold / 哪些 fade"、永续点?
- **收纳区有几块?**(逐块记小标题)——最容易漏,数字写下来,收尾对数。
- 每条线的**历史表有几行几年?**(收入/销量/吨价/吨成本,或增速族的收入/成本)

盘点的意义:翻译前先在脑子里建立源文全貌,后面逐句翻时就是"逐条认领并划掉",而不是边翻边发现"还有一块没翻"。

### 3.2 逐句翻(把每类源句翻成对应译法)

按 §5–§8 把每一条认领到正确路径、正确 `kind`、正确符号。摊数组是搬运;遇到要算的、要猜的,停下举旗(§0.4, §0.6)。

### 3.3 校对(翻译后:自审 + 报告,详见 §9)

对着 3.1 的清单做双射,出一份简短报告。这是翻译这层唯一的质量闸(计算忠实度的回测在下游 `src/yaml1_cleaner.py`,这层只能靠自审)。

---

## 4. 三种译法积木(`kind`)

源语言里每条 A 类判断,翻成目标语言时是一个带 `kind` 标签的多态积木。`kind` 告诉下游"这条该怎么用"。三种:

### 4.1 `knob`(旋钮:费用率 / 绝对值 / 毛利率 / 税率 / 少数股东率)

最常见的译法。源句"销售费用率五年从 15.56% 降到 15.00% 后持平",翻成一个满数组:

```yaml
income.cost_rates.sell_exp:
  kind: knob
  values: [0.1545, 0.1534, 0.1523, 0.1511, 0.1500, 0.1500, 0.1500]   # 满数组,长度 = meta.horizon
  src: "#销售费用"
```

`values` 永远是满数组(摊满是搬运,§0.6)。覆盖标准路径,resolver 逐年顶掉 yaml2 的平推标量。

> **符号要按引擎口径,不照搬 .md 显示符号(弥合差异 3)。** 逐路径核对引擎怎么用这个值,再定符号——完整规则与各科目符号见**附录 A**。

### 4.2 `decomposition`(非标拆分:弥合差异 1+2)

非标分部(各产品线/业务线)在字典里**根本没有标准科目**——它们是几条 roll up 到某个标准科目(通常营业收入)的子线。源语言按线分段讲它们;目标语言把它们 mint 成该标准科目底下的一棵子树。这是差异 1(组织维度)和差异 2(深度)同时发生的地方。

```yaml
income.revenue:
  kind: decomposition
  rollup: sum
  src: "#收入"
  segments:
    <line_a>:                         # 老板在产品线级拨 → 直接 leaf;在产品号级拨 → 再嵌一层
      revenue_family: factor_product
      base:   { ... }                 # 见 §5
      factors: { ... }
      history:{ ... }
      src: "#<line_a 标题>"
    <line_b>:                         # 嵌套示例:自己又是一层 decomposition
      kind: decomposition
      rollup: sum
      segments:
        <sku_1>: { revenue_family: factor_product, base: {...}, factors: {...}, history: {...} }
```

这棵子树只有 `src/yaml1_cleaner.py`(折叠成总额)和前端(breakdown)消费,`calc.py` 看不到。**你写的是结构;折叠成 `revenue_yoy` 是下游的活——你不产 `revenue_yoy`,不手算收入序列**(§0.6)。

**结构级自洽:一个节点要么 rollup、要么 leaf,不能既是又是。** 旋钮、base、history 只挂 leaf,绝不挂 rollup。撞到一个节点既有聚合历史又有子块 → 不猜,举旗。

### 4.3 `formula`(算法模式:受限可执行,只接长尾)

下游 `src/yaml1_cleaner.py` 已有受限 formula/DAG 求值器,但它不是默认选择。绝大多数常见收入线仍要先尝试模板:`factor_product`(n 因子连乘)、`growth`、`abs`、leaf margin。只有模板装不下的跨期递推、分段函数、滞后关系、中间变量复用,才进入 formula。

formula 的唯一合法形态是顶层 `formulas.nodes` 定义节点,再在 revenue leaf 或标准 YAML2 path 上用 `formula_ref` 引用。不要把 bridge、ratio_to_driver、lag_ref 写成新 `kind`,也不要发明新的 `revenue_family`。

```yaml
formulas:
  version: 1
  nodes:
    stores:
      kind: formula
      unit: store
      expr: "lag(stores, 1) + openings - closures"
      inputs: [stores, openings, closures]
      seeds:
        2024: 1200
      src: "#门店数递推"

    retail_revenue:
      kind: formula
      unit: million_cny
      expr: "stores * sales_per_store"
      inputs: [stores, sales_per_store]
      src: "#门店数 × 单店收入"

income.revenue:
  kind: decomposition
  segments:
    retail:
      kind: formula
      formula_ref: retail_revenue
      base:
        base_year: 2024
        revenue: 2460
        unit_factor_to_million_cny: 1
```

铁律:

- `formula` 只能引用 `formulas.nodes` 中的节点。
- 表达式只允许四则运算、比较、`lag(node,n)`、`min/max/abs/clip/if_else`。
- `inputs` 必须和表达式引用双向一致。
- 用 `lag()` 必须给足 `seeds` 或 `history`。
- formula 输出到标准 path 时,该 path 必须存在于本公司 `defaults.yaml`。
- formula revenue leaf 不得同时写 `revenue_family` / `factors` / `knobs.revenue_yoy` / `knobs.revenue_abs`。
- formula 失败不是 warning:引用缺失、循环、缺 seed、回测失败都会让 cleaner 硬失败。

---

## 5. leaf 的三件套:`base` / `knobs` / `history`

每条 decomposition leaf 由三个并列字段构成,分别对应这条线的**起点、未来、过去**。三者职责不同,缺一不可。

### 5.1 `base`(折叠用的单年锚 = 起点)

```yaml
base:
  base_year: 2024              # 必填:折叠第一年用 base ×(1+首年 yoy);算法模式滞后链种子也要它
  volume: <vol_base>           # 量价族:基年量
  price:  <price_base>         # 量价族:基年价
  unit: { volume: "10k_ton", price: "cny_per_ton", revenue: "million_cny" }   # 人类可读单位
  unit_factor_to_million_cny: <100|1>
```

**`unit_factor_to_million_cny` 必须结构化输出,按族给,不全局拍一个。** 这是因为下游 `src/yaml1_cleaner.py` 是纯确定性 Python,折叠时用它把 base 换算成百万元——**它绝不解析中文 note 拿系数**(把"读人话"塞给最不可靠的一侧,数错就静默差 100 倍)。所以系数必须结构化:

- `factor_product` 族按因子连乘后的单位给:如 万吨×元/吨 → `100`;若因子连乘已经是百万元 → `1`。
- `vol_price` / `vol_price_margin` 是 `factor_product` 的旧兼容写法(量×价,如 万吨×元/吨):`100`。
- `growth` / `abs` 族(base 已是百万元):`1`。
- 增速线最容易错成 100——base 已是百万元,系数必须 `1`;按 leaf 自己的族判。

### 5.2 `knobs`(旋钮 = 未来)

照 `.md` 骨架声明的模板给对应旋钮,满数组。`revenue_family` 是这条 leaf 的算法声明,**只能从当前 cleaner 支持的有限集合里选**:`factor_product` / `driver_rate` / `growth` / `abs`,以及旧样本兼容名 `vol_price` / `vol_price_margin`。不要自创族名;模板装不下的跨期/DAG/分段/中间变量复用,用 §4.3 的受限 `formulas.nodes` + `formula_ref`,而不是写新的 `revenue_family`。

> `driver_rate` 是 `factor_product` 的等价别名(生息资产 × 息差等费率型 driver 场景),cleaner 同样按 n 因子连乘处理;新写法优先用 `factor_product`,`driver_rate` 留给费率型 driver 语义更清楚时使用。

- **`factor_product`**(n 因子连乘):用于门店数×单店收入、用户数×ARPU、生息资产×净息差、装机量×利用小时×电价、产能×开工率×价差等。每个 factor 自带 `label`、`base`、`projection`;下游先逐因子算序列,再 `product(factors) / unit_factor_to_million_cny` 折收入。

```yaml
revenue_family: factor_product
base: { base_year: 2024, unit_factor_to_million_cny: <1|100|...> }
factors:
  - key: stores
    label: 门店数
    base: <2024门店数>
    projection: { kind: yoy, values: [<×7>] }       # yoy / abs / constant
  - key: sales_per_store
    label: 单店收入
    base: <2024单店收入>
    projection: { kind: abs, values: [<×7>] }       # abs = 逐年直接值
```

- **`vol_price`**(旧兼容名):等价于二因子 `factor_product` 的量×价特例。旧样本可继续用 `volume_yoy` + `price_yoy`;新写法优先用 `factor_product`。
- **`vol_price_margin`**(旧兼容名):等价于 `vol_price` + leaf `margin`;新写法优先用 `factor_product` 并在 `knobs.margin` 写线级毛利率。
- **`growth`**(增速族):旋钮 `revenue_yoy`;base 直接是 `revenue`(已百万元),`unit_factor_to_million_cny: 1`;history 存 revenue/cost 两序列。
- **`abs`**(绝对值族):旋钮 `revenue_abs`——**逐年绝对收入值的满数组**(不是 yoy,而是直接给每年的收入金额),用于"增速无意义、老板直接拍逐年金额"的线;base 给 `revenue`(基年金额、百万元),`unit_factor_to_million_cny: 1`;history 存 revenue/cost 两序列。

> `factor_product` 是主力模板;`growth`/`abs` 是审计快速通道;`vol_price`/`vol_price_margin` 只为兼容旧产物。模板层无状态、无引用、无 DAG,产物只折到 `model.revenue_yoy` 和可选的 `income.gpm`。

### 5.3 `history`(完整历史 = 过去,分线历史的唯一法定归宿)

```yaml
history:
  note: "口径说明:占位/异常/断点年照标(纯人类注释,不供清洗层计算)"
  series:                      # factor_product/vol_price 量价线存 driver 序列;growth/abs 族存 revenue/cost 两序列
    revenue: { <year>: <v>, ... }
    volume:  { <year>: <v>, ... }   # 仅量价族
    price:   { <year>: <v>, ... }   # 仅量价族
    cost:    { <year>: <v>, ... }
```

`base` 只取折叠用的**单年锚**;leaf 的**完整多年历史**落在**同一个 leaf 的 `history.series` 下**,逐年照搬、一个不丢。占位/异常/断点年照标进 `note`,值照搬不删。

**为什么历史必须挂 leaf、不能另起一个顶层平行块?** 这是上一版踩过的坑,值得把因果讲透:历史与这条线的 `base`/`knobs` 是同一条线的三段,它们靠**同一个 segment slug** 锚定。若把历史另起一个 `stash.分线历史_X` 平行块,就和 leaf 的 slug 脱钩了——(a) 下次 `modify` 改这条线,slug 一变,平行块对不上,历史漂移;(b) 前端按路径 `…segments.<slug>.history` 取数,平行块取不到。所以历史与 base/knobs **共用同一个 slug**,这是 modify 不崩、前端能取的前提。`history` 本身不参与折叠——`src/yaml1_cleaner.py` 与 resolver **显式跳过它**,它只供前端 breakdown 与溯源。

> 三件套各管一段:`base` = 起点(单年),`knobs` = 未来(数组),`history` = 过去(完整序列)。缺 base 折叠没起点;缺 knobs 落平推;缺 history 丢信息。

---

## 6. `stash`(B 类收纳区)与"三条去向"

### 6.1 三条去向(一个信息原子该往哪放,只问三句)

弥合差异 1(组织维度)时,B 类信息最容易放错地方。判定法则:

1. **它是某条 leaf 的原始历史吗?**(分线收入/销量/吨价/吨成本逐年)→ 进**该 leaf 的 `history`**(§5.3)。
2. **它是不挂任何一条 leaf 的东西吗?**(地区/子公司副拆分、降级观测视图、核对项、口径断点说明、定性情报、溯源附注)→ 进**顶层 `stash`**,按 .md 收纳区小标题分组。
3. **它只是某个具体条目本身的口径提示吗?**(这条旋钮为什么这么拍的一句话)→ 进**该条目的 `note`**。

三者互斥。最常见的放错(上一版真实发生过):把本该独立成块的 B 类收纳项(核对项、口径断点、税收附注)塞进相关 A 类条目的 `note` 里。信息看着没丢,但前端按收纳区溯源时捞不到、B 类完整性校对也对不上数。`note` 只放"这条本身"的注释,不当 B 类的家。

### 6.2 `stash` 形态

放顶层 `stash` 块下,按 .md 收纳区小标题分组,**多年序列照搬,不是单年比例**。

```yaml
stash:
  分线毛利率:                                  # 降级观测视图(预测已改整体手拍,不再驱动)
    note: "历史观测,降级仅参考;来源 …。多年序列可由各 leaf history 的 price/cost 还原,compiler 不代算"
    unit: "ratio"
    series:                                    # 有几年落几年
      <line_a>: { <year>: <v>, ... }
  副拆分_按地区:
    note: "来源 …;不参与营收计算"
    unit: "百万元"
    series: { <region>: { <year>: <v>, ... } }            # 收入（必需）
    毛利率:                                                 # 可选；与 series 同结构的平级子块，前端按 region label 关联收入行渲染"· 毛利率"行
      series: { <region>: { <year>: <ratio>, ... } }      # 比率写小数，0.4623=46.23%；某 region 年报未披露则该 region 不写、前端自动缺
    同比:                                                   # 可选；同上，前端渲染"· 同比"行（带符号）
      series: { <region>: { <year>: <ratio>, ... } }      # 比率写小数，0.15=+15.0%、-0.12=-12.0%
  # ── 副拆分毛利率/同比自动提取（不要从 .md 手抄）──
  # 跑 `py scripts/dump_secondary_metrics.py "companies/{公司}_{代码}"`，它从 /init 产物
  # OfficialBreakdowns/business_revenue_breakdown.csv 直接提取各 dimension（地区/渠道/产品/行业）
  # 的收入+毛利率(major_business_profitability)+同比(revenue_composition)，输出 yaml 片段。
  # comp 把脚本输出里与 .md 收纳区副拆分块同 dimension 的 毛利率/同比 series 注入 yaml1 stash
  # 对应块（保留 .md 的 note/caveat，只补 毛利率/同比 子块）；与主拆分 leaf 重叠的 dimension
  # （如"按产品"=主拆分）不进 stash。无 breakdown CSV 的公司该项缺，前端自动不渲染。
  副拆分_按子公司:
    note: "来源 …;单位 亿元"
    members: [<sub_1>, <sub_2>, ...]
    caveat: "<参股未并表 / 收购年 / 预测值起点 等口径外说明>"
    series: { <sub_1>: { <year>: <v>, ... } }
  核对项:           { <校验名>: "<.md 里的核对算式或结论原话>" }
  口径与降级说明:   { <断点名>: "<原话>" }
  溯源附注:         { <附注名>: "<原话>" }      # 主动覆盖判断的凭证出处
  定性情报:         ["<情报 1>", "<情报 2>", "..."]   # .md 有几条落几条,别缩水
```

### 6.3 `display` 展示契约（B 类去向必须声明）

`stash` 负责保全 B 类信息，`display` 负责告诉工作台怎么摆放这些信息。新产物应在顶层写 `display`，遵守 `docs/yaml1前端展示契约.md`：

```yaml
display:
  schema_version: 1
  primary_dimension: business_line
  blocks:
    - {path: income.revenue, role: primary_model, placement: model_table, dimension: business_line, status: active}
    - {path: stash.分线毛利率, role: primary_attachment, attach_to: income.revenue.segments, placement: model_table, dimension: business_line, metric: gross_margin, status: reference, duplicate_policy: prefer_derived_and_warn}
    - {path: stash.副拆分_按地区, role: secondary_split, placement: secondary_table, dimension: region, metrics: [revenue, gross_margin, yoy], status: reference}
    - {path: stash.LOAD分线销量吨价原子_弃用, role: deprecated, placement: reference_tab, status: deprecated}
```

纪律：
- `display` 不改变 DCF，不替代 `knobs`，不允许把 B 类变成 A 类。
- 副拆分默认独立成 `secondary_split`，不要因为局部行名撞上主业务线就挂回主表。
- 弃用、核对、风险、溯源材料必须进 Reference，且用 `deprecated` / `check_only` / `technical` 标清。
- 行名匹配默认只允许精确匹配或显式 alias；`其他` 不得自动匹配 `其他业务`。
- 如果副拆分的毛利率/同比只披露了部分项目，缺失项不补数，只让前端提示“部分未披露”。

> **关于"多年退化成单年":** 若 .md 收纳区某块只显式给了单年(如分线毛利率只给 2024),落单年 **+ note 写明"多年序列可由各 leaf history 的 price/cost 还原,compiler 不代算"**。这不是偷懒——是诚实地指出"多年信息其实在 leaf history 里,这里不重复也不替算"。只落单年而不指路,等于把这条线索藏了,算半丢。

---

## 7. 三个让翻译走样的高级机制(再参数化 / 嵌套 / 三段式)

### 7.1 尊重再参数化(买方自由下传,不许 hardcode)

**你不能 hardcode"收入永远量×价驱动"或"毛利永远分线派生"。** 源语言里老板可能**重新接线**——典型例:把毛利从"分线派生"翻转成"整体毛利率总旋钮手拍"(分线吨成本降级进收纳区)。那么:

- 收入侧仍是 decomposition(各线量×价),折叠出收入总额;
- 毛利侧**不是**分线派生,而是 `income.gpm` 一个 knob 数组(整体毛利率逐年),下游用它派生营业成本。

```yaml
income.gpm:
  kind: knob
  values: [<逐年整体毛利率×7>]
  src: "#整体毛利率(主动覆盖·参数化翻转)"
```

换一家公司,老板可能在产品线级拨毛利率。此时不要写顶层 `income.gpm`;把每个 revenue leaf 的 `knobs.margin` 写满数组,由 cleaner 做 `sum(leaf_revenue × margin) / sum(leaf_revenue)` 折成整体 `income.gpm`。**二选一铁律:**没有任何 leaf margin → 才允许顶层 `income.gpm` 手拍;只要任何 leaf 有 margin → 禁止顶层 `income.gpm`,且所有收入 leaf 都必须有 margin。部分 leaf margin、或 leaf margin + 顶层 `income.gpm` 同时出现,都是 over-determined,必须举旗。

### 7.2 嵌套拆分:封顶两级(镜像差异 2,不判断)

**你不决定拆几层——`.md` 已经替你决定了**(纪律是"树的深度 = 判断的深度":只拆到老板真正拨旋钮那一级,更细的进收纳区)。你拿到的是一棵已判断好、深度受控的干净树,**忠实镜像它**。

- 读 .md 块层级认 leaf vs rollup:产品线下挂带骨架/历史/预测的子块 → rollup;没子块、自己直接有族+原子+旋钮 → leaf。
- 两级 mint 子路径:`income.revenue.segments.<产品线>.segments.<产品号>`。两条线都有"其他"子项时靠父级隔开,不全局去重。
- **深度守卫 ≤ 2**:裸的第三层 decomposition = 畸形输入 → 举旗停下,绝不静默建第三层。第三层只会以两种形态到你手上:已归并到产品号的 ≤2 树,或穿了拆分外衣的 `formula` 节点。撞到裸第三层就停。

### 7.3 中期三段式(模型级;弥合差异 4 的典型场景)

源语言给显式期末年 + fade 规则 + 永续点。你照转,**fade 不展开**(展开是下游的活)。

```yaml
terminal:
  explicit_end: <显式期末年>
  fade:
    to_year: <fade_end_year>          # to_year 语义是与清洗层的契约
    kind: linear
    target_growth: <衰减交接增速>      # 可选；有则 fade 到交接增速,无则兼容旧语义 fade 到 perpetual_growth
    target_basis: <auto_profile>      # 可选；照抄 /ka 的自动档位理由,清洗层忽略
    fade_paths: [model.revenue_yoy]   # 衰减期里"滑"的:增速类序列 fade 到 target_growth
    hold_paths: [income.cost_rates.sell_exp, ...]  # 衰减期里"钉"的:显式维持稳态的路径
    path_targets:                     # 可选；非收入增速路径若有明确衰减期目标值,在这里逐路径写终点
      income.gpm: 0.32                # 例: 31.1% -> 32.0%; 比率写小数
  perpetual_growth: <永续点>          # Gordon 终值 g,一个点,不是区间
  src: "#往后几年"
```

**`target_growth` 与 `perpetual_growth` 是两个数。** `/ka` 若写了“衰减交接增速/中期交接增速/fade target”，必须照转到 `terminal.fade.target_growth`；`perpetual_growth` 仍只表示 Gordon 终值长期经济锚。你不重新计算 target，不把 target 误写成 perpetual，也不把 perpetual 误拿来覆盖 target。若源文没写 target，字段可省略，下游兼容旧语义，fade 到 `perpetual_growth`。

**`.md` 常明示"衰减期里哪些序列 hold、哪些 fade、哪些到具体目标值",这条信息必须落进 `terminal`。** 否则下游展开衰减期时会把路径钉错、滑错或漏掉目标值。.md 写了 hold/fade/目标值分组就必须落;没写清 → 举旗,别默认全 fade。

**`terminal.fade` 三个去向不要混。** 判据一句:增速类统一用 `fade_paths` 收敛到 `target_growth`;有自己终点的非增速路径用 `path_targets`;明确稳态不变的路径用 `hold_paths`。同一路径只能出现一次。三类路径各自去向:

| 路径类型 | 去向 |
|---|---|
| 增速类序列 | → 进 `fade_paths`(典型 `model.revenue_yoy`),收敛到 `target_growth`;未写 target 时兼容旧语义到 `perpetual_growth` |
| 非增速类 + .md 给了衰减期终点 | → 进 `path_targets`(如 `income.gpm: 0.32`;金额用百万,如 `income.operating_adjustments_abs.asset_disp_income: -40`) |
| 非增速类 + .md 明示维持稳态/封顶 | → 进 `hold_paths`(典型 `income.cost_rates.*`、税率、少数股东率;若 GPM 是 31.1% 持平才进 hold) |
| 显式期末年已归零的绝对值(below-OP 已归零项) | → 不进(已是 0,留 0 自然成立) |
| 非增速类绝对值/比率(税率、少数股东率、未归零稳定项) | → 不进(fade 碰不到,hold 是答非所问) |

> 落地写法:新乳业这类"整体毛利率 31.1%(2029) -> 32.0%(2034)"应写 `path_targets: {income.gpm: 0.32}`,而不是把 `income.gpm` 放进 `hold_paths`。拿不准某条 knob 在衰减期是"持平"还是"到目标值",宁可在收尾报告举旗,不要为保险重复塞进多个桶。

> **这是差异 4(歧义)的教科书场景。** .md 的措辞常自相矛盾,例:"2032 起 6 年 fade 至 2038"——"6 年"(2032–2037)与"至 2038 / 2038 起永续"在端点上不自洽(含端 2032–2038 是 7 年)。**处理四步:(1) 识别出这是源语言的信息缺口,不是你能机械翻的形变;(2) 取一个内部自洽解(如:让"6 年"成立 → fade 2032–2037、2038 首个永续年);(3) 在该字段加 `# to_year 语义待核` 注释;(4) 在收尾报告里写明歧义本身 + 你取的解,交人裁定。** 绝不静默选一个字面值放行——因为你选的可能恰好是 .md 写错的那一半,而机器不会报错。

**特例:.md 没铺三段式 / terminal 某字段没拍时,照填这组固定默认,不必判断。** 三段式与 to_year 歧义不同——歧义是 .md 给了相互矛盾的信息要你举旗;"没铺"是 .md 压根没给这块判断。终值这几个参数是终值敏感性系列,真正的取值在下游敏感性工作台扫,yaml1 这里只需保证**字段齐全、DCF 能跑通**。所以直接抄下面这组默认,不区分字段类型、不加任何待定标记:

```yaml
terminal:
  explicit_end: <显式期末年>
  fade:
    to_year: <显式期末年 + 5>
    kind: linear
    fade_paths: [model.revenue_yoy]
    hold_paths: [income.gpm]
  perpetual_growth: 0.025       # 体系纪律默认值,固定 0.025,不要随意换数
```

唯一固定的一点:`perpetual_growth` 默认 **`0.025`**(本体系锚长期通胀的纪律值,与 defaults.yaml 的 `model.terminal_growth` 保持一致),别填别的数。若 .md 没铺三段式，默认不写 `target_growth` 或 `path_targets`，保持旧语义；默认 `hold_paths: [income.gpm]` 只是为了防止整体毛利率被旧语义误推到永续增速,若 .md 明示 GPM 到某个目标值,必须改用 `path_targets`。`.md` 里"本轮未铺/待定"的痕迹保留在 `src`/`note` 里即可,无需额外标记。

---

## 8. 边界:你不干什么(逐条记牢)

这些都是"看起来该帮忙、实则越界"的动作。每条都对应前面某个权威章节——详细论证回该章,这里只列禁止动作 + 回指。

| 禁止动作 | 权威章节 |
|---|---|
| 折叠 / 量×价 / 算收入总额(你写 decomposition 结构 + 每个量价 leaf 的 `unit_factor_to_million_cny`,不产 `revenue_yoy`) | §0.6, §4.2 |
| 任何派生序列(收入 / 毛利率 / 占比 / 净利 / 各净利率)手算填入 | §0.6 |
| 重算 / "算准" .md 的数(.md 写什么搬什么,觉得错 → 举旗,不替它改) | §0.6 |
| 展开 fade 成逐年列 | §7.3 |
| 决定拆几层 / 逆向编公式(skill + 老板已定,你只转写) | §4.3, §7.2 |
| 发明路径名 / 因"没背过"乱标 unaligned(对齐目标是 defaults.yaml 真实路径) | §2 |
| 丢弃 B 类 / 分线历史塞脱锚平行块 / 收纳项塞 A 类 note | §5.3, §6.1 |

**唯一允许的机械动作:把已写明的旋钮值摊成满数组**(flat/区间 → 重复)。搬运,不是计算。

**财务费用的边界(硬契约,详细版留此处,别处只回指):** 财务费用不是铁板一块。**利息净额**引擎按现金/负债余额倒算,`#VALUE!` 是设计如此,**一个字不写**。但**其他财务费用(外生、非利息项,如手续费等)是 .md 可能拍的外生绝对值,必须写**——它在字典/cleaner 里叫 `other_fin_exp_abs`,落成 knob:

```yaml
income.financial_expense.other_fin_exp_abs:
  kind: knob
  values: [<×7>]
  src: "#其他财务费用(外生·非利息)"
```

**命名空间硬契约:必须嵌在 `income.financial_expense` 下。** cleaner 用 `income.get("financial_expense")` 取——写到顶层 `financial_expense.*` 或别处会被**静默丢弃**,该外生项落 0,没有任何报错。这正是"利息净额不写"被误读成"整个财务费用都不写"会丢掉的判断:**拆开记——利息净额不写,其他财务费用外生项必写、且必须嵌 `income.financial_expense` 下。**

---

## 9. 翻译后:校对 + 固定报告

对着 §3.1 的盘点清单逐项勾,出一份简短报告。这是翻译这层唯一的质量闸。

报告结构固定为六段，顺序不能改；没有事项也写 `无`：

1. **A 类覆盖:** .md 每条可计算旋钮/结构判断 ↔ yaml1 一个条目,没漏没多。遍历 decomposition 树到每个 leaf,逐年值都有对应。漏→静默落平推;多→幻觉。
2. **B 类保全:** 逐块对照——(a) 每条 leaf 的 `history` 落全 .md 该线历史表的全部年份与全部行(量价族:收入/销量/吨价/吨成本;增速族:收入/成本),含占位/异常/断点年;(b) .md 收纳区每一块进 `stash` 落全(多年序列、口径、出处);(c) 顶层 `display` 给出主表、副拆分、Reference 的展示去向。任一 leaf 缺 history、历史塞进脱锚平行块、B 类塞进 A 类 note、或多年退化成单年 = 校对失败,不放行。
3. **路径待核:** 没落地到任何 defaults.yaml 路径、又非可 mint 非标拆分的判断,以及所有 `# 路径待核` / `unaligned` 项,列出来交人。绝不为凑齐硬塞路径。
4. **语义待核:** 深度超 2、节点 rollup-leaf 不分、某级加总声明对不上、formula 不可执行、.md 写了 hold/fade 分组但 terminal 没承载、to_year 等语义歧义,列出歧义本身、你取的自洽解和需谁确认。绝不静默放行。
5. **主动覆盖回读:** 把**主动覆盖线**(参数化翻转、逆券商、异常值常态化、查证类拐点这类——历史回测够不着、又故意不照搬券商,下游没有客观闸接得住)单独渲染成一张紧凑人话表,摆给老板扫一眼。这是那条窄缝唯一的真值裁判。
6. **Forecast 状态:** compiler 阶段先写 `pending_comp_step`；`/comp` launcher 跑完 forecast 后在用户回执里更新为 `not_run`、`skipped_missing_data`、`ran_ok` 或 `failed_after_audit_clean`，并说明 `Agent/forecast/` 是否被覆盖。

**official 门禁:** 只有同时满足以下条件,才允许 `/comp` 把本次 yaml1 当作 official forecast 输入继续跑 DCF:

- `audit_clean = true`:覆盖双射 ok + B 类完整性 ok + `unaligned`/路径待核为空 + 语义待核为空或已被分析师显式确认 + 主动覆盖回读完成。
- 若存在 `unaligned`、路径待核、未确认语义待核、B 类缺失、结构异常、主动覆盖未回读,本次 yaml1 最多保存为 reference/draft 产物,**不得**继续跑 official forecast。
- `/load` 不再编译 yaml1、不跑 DCF（止于核心假设参考 markdown）；yaml1 编译与 DCF 一律走 `/comp`。

> 报告骨架示例:
> ```
> A 类覆盖: ✅ N 条旋钮/结构判断全部认领,无漏无多
> B 类保全: ✅ M 条 leaf history 齐全;stash 落 K 块;display 去向已声明
> 路径待核: 无 / <逐条列 + 原因>
> 语义待核: 无 / <说明歧义本身 + 你取的自洽解,交人裁定>
> 主动覆盖回读: ✅ <紧凑人话表:逐条 谁定 / 数值 / 为什么>
> Forecast 状态: pending_comp_step
> verdict: audit_clean / reference_only
> ```

你的可信不建立在"你没出错",而建立在**可审计**:双射防漏译/幻觉,B 类完整性防信息丢失,unaligned/待核兜路径与歧义,人话回读兜主动覆盖线,结构异常硬停。

---

## 10. 两种进场(init / modify)

- **init(从零):** 整份 .md → 整份 yaml1。先盘点(§3.1),再认所有标准线路径、mint 所有非标子树、落每条 leaf 的 base/knobs/history、摊所有旋钮、写 terminal,最后走校对。
- **modify(改已有):** .md 变了 → 只重译受影响的路径,**保住已 mint 的 segment slug 不变**(否则 resolver 覆盖错位、leaf history 脱锚)。给一份"改动清单"(哪条路径、从什么改到什么、src)。

**slug 命名必须确定且稳定:** 同一段 .md 标题 → 同一个 slug,每次都一样(取标题的稳定规范化 slug)。这是 modify 不崩、leaf history 与 base/knobs 同 slug 锚定的前提。

**segment key 的用途与命名建议:** decomposition `segments.<key>` 的 `<key>` 是后端 path / JSON pointer 的组成部分(`income.revenue.<key>.<driver>`,编辑回写也按它定位),前端工作台按 `seg.key` 匹配 driver path 来定位可编辑单元格——所以 key 用中文显示名还是英文 slug **都能工作**(不要为"代码整洁"反向把中文 key 改成英文)。**建议用中文显示名,且与该 leaf `src` 去掉 `#` 一致**(如 `服饰配饰`、`低温鲜奶`),原因:(1) 与 src/anchor 同名,path 与正文小节标题直接对得上,审计最省眼;(2) 与前端 `seg.name`(=src 去#)一致,人眼对照 path 和显示名不跳戏。这不是硬约束(前端已按 key 匹配,英文 slug 也能调),但用中文显示名最不易出错;若写英文 slug,前端仍可调,只是 path 与显示名对不上、审计略费眼。

---

## 附录 A. 形态速查表(逐句翻译时对着查)

| .md 这条是… | `kind` | 路径来源 | 关键字段 | 符号规则 |
|---|---|---|---|---|
| 费用率(销售/管理/研发/税金及附加) | `knob` | 字典→defaults.yaml `cost_rates.*` | `values` 满数组(比率) | 正值比率 |
| 整体毛利率(再参数化翻转) | `knob` | defaults.yaml `gpm` | `values` 满数组(比率) | 正值比率 |
| 有效税率 / 少数股东率 | `knob` | defaults.yaml `effective_tax_rate` / `minority_ratio` | `values` 满数组(比率) | 正值比率 |
| operate_profit **加项**(资产处置、其他收益、投资、公允) | `knob` | defaults.yaml `operating_adjustments_abs.*`(汇兑 `forex_gain`、资产处置 `asset_disp_income`、其他收益 `oth_income`、投资 `invest_income`、公允 `fv_value_chg_gain`) | `values` 满数组(绝对值) | 亏损存**负**(与 .md 同号) |
| operate_profit **减项**(资产减值 `assets_impair_loss` / 信用减值 `credit_impa_loss`) | `knob` | defaults.yaml `cost_abs.*` | `values` 满数组(绝对值) | **存负值(与 .md 同号);引擎按同号做减项。** 本体系已核实结论(见下"减值符号结论") |
| total_profit 减项(营业外支出 `non_oper_exp`) | `knob` | defaults.yaml `below_line_abs.non_oper_exp` | `values` 满数组(绝对值) | 引擎做减项 → 存**正值**(常与 .md 显示的负号相反) |
| total_profit 加项(营业外收入 `non_oper_income`) | `knob` | defaults.yaml `below_line_abs.non_oper_income` | `values` 满数组(绝对值) | 正值 |
| 非标业务线(n 因子连乘) | `decomposition` leaf | mint `income.revenue.segments.<slug>` | `revenue_family: factor_product` + `factors[].{key,label,base,projection}` + `base.unit_factor_to_million_cny` | 因子为正;projection 仅 `yoy`/`abs`/`constant` |
| 非标产品/业务线(量×价) | `decomposition` leaf | mint `income.revenue.segments.<slug>` | 优先 `revenue_family: factor_product` + `factors[]`, `unit_factor=100` | 量价为正;`vol_price` 仅旧样本兼容 |
| 非标业务线(线级毛利率) | `decomposition` leaf | mint 同上 | 任一收入族 + `knobs.margin` 满数组;所有 revenue leaf 必须都有 margin | cleaner 折成整体 `income.gpm`;禁止再写顶层 `income.gpm` |
| 非标业务线(增速族) | `decomposition` leaf | mint 同上 | `revenue_family: growth` + base/knobs(`revenue_yoy`)/history,`unit_factor=1` | base 已是百万元 |
| 非标业务线(绝对值族) | `decomposition` leaf | mint 同上 | `revenue_family: abs` + base/knobs(`revenue_abs` 逐年绝对值)/history,`unit_factor=1` | base 已是百万元 |
| 装不进模板的算法线 | `formula` | `formulas.nodes.<node>` + `formula_ref` | 受限表达式、显式 inputs、seed/history、clean report 回测 | 只接跨期/DAG/分段/中间变量复用;模板能表达时禁止升级 |
| 分线历史(收入/量/价/成本逐年) | (不是 A 类) | **该 leaf 的 `history`** | `series.{revenue,volume,price,cost}` | 照搬,占位年标 note |
| 副拆分 / 降级观测 / 核对 / 情报 / 附注 | (不是 A 类) | **顶层 `stash`** 独立成块 | 多年 `series` + `note`/`caveat`/`unit` | 照搬 |
| 财务费用 · **利息净额** | (刻意缺席) | — | — | 引擎按现金/负债余额倒算,**一字不写** |
| 财务费用 · **其他财务费用(外生·非利息)** | `knob` | defaults.yaml `income.financial_expense.other_fin_exp_abs` | `values` 满数组(绝对值) | 照 .md 符号;**必须嵌 `income.financial_expense` 下,不可提顶层**(见 §8) |
| 人工 BS 营运资本 · 收入占比 | `knob` | defaults.yaml `balance_sheet.revenue_pct.*` | `values` 满数组(比率) | 只翻已明示核心 thesis 的覆盖;缺席 = defaults |
| 人工 BS 营运资本 · 成本天数 | `knob` | defaults.yaml `balance_sheet.cogs_days.*` | `values` 满数组(天数原值) | 例如存货/应付周转天数;不要同时手填金额 |
| 人工 CF/BS 标量 · capex/depr | `knob` | defaults.yaml `balance_sheet.capex_pct` / `balance_sheet.depr_rate` | `values` 满数组(比率) | 轻资产/稳态覆盖;重资产排程优先 `/da`,不要在 yaml1 里造 cohort |
| 营业利润/净利/各净利率 | (刻意缺席) | — | — | 派生,不写 |
| 沿用平推的标准科目 | (刻意缺席) | — | — | 缺席 = 落 yaml2 |

> **减值符号结论(把血泪结论固化,别再交给运气):** `cost_abs.*`(资产减值 `assets_impair_loss`、信用减值 `credit_impa_loss`)在本体系 **存负值,与 .md 同号**,引擎按同号做减项。这条是 calc.py 核实过的结论——曾有一次减值字段符号搞反,导致五家测试公司利润被静默虚增,修复后定为此。**照此填,不要再标"符号待核"、也不要自作主张存正值。**(注:`assets_impair_loss` 的 TuShare 原始符号惯例在 2019 年后有翻转,但那是清洗层入库前的事;到 yaml1 这一层,以 .md 写出的符号为准、存负值。)

> 符号铁律(其余未固化项):**逐路径核对引擎怎么用这个值,再定符号。** .md 的显示符号(按"对利润的正负贡献")与引擎口径(按公式做加项/减项)可能相反。下游没有客观闸接住符号错,所以这是收尾人话回读重点扫的一类。

---

## 附录 B. 完整范例(中性公司 `示例乳业 EXMP`,占位值,仅示范"形")

> 这是范例不是模板。路径名一律以**本公司 defaults.yaml** 为准;数值用占位,真值照 .md 搬。演示"四条线 + 毛利再参数化翻转 + 三段式 + stash"的完整骨架。

```yaml
meta:
  company: "<股票代码>"
  name: "示例乳业"
  src: "核心假设.md@<日期>"
  mode: init
  horizon: [2025, 2026, 2027, 2028, 2029, 2030, 2031]   # 所有 knob 数组按此年轴对位

income.revenue:
  kind: decomposition
  rollup: sum
  src: "#收入"
  segments:
    line_factor_product_a:                 # 量价族 leaf,用 factor_product 主写法
      revenue_family: factor_product
      src: "#<线 A 标题>"
      base:
        base_year: 2024
        unit: { volume: "10k_ton", price: "cny_per_ton", revenue: "million_cny" }
        unit_factor_to_million_cny: 100
      factors:
        - key: volume
          label: 销量
          base: <vol_2024>                 # 万吨
          projection: { kind: yoy, values: [<×7>] }
        - key: price
          label: 吨价
          base: <price_2024>               # 元/吨
          projection: { kind: yoy, values: [<×7>] }
      history:
        note: "<占位/异常/断点年口径>"
        series:
          revenue: { <year>: <v>, ... }    # 全部历史年,一个不丢
          volume:  { <year>: <v>, ... }
          price:   { <year>: <v>, ... }
          cost:    { <year>: <v>, ... }
    line_growth_b:                         # 增速族 leaf
      revenue_family: growth
      src: "#<线 B 标题>"
      base:
        base_year: 2024
        revenue: <rev_2024>                # 百万元
        unit: { revenue: "million_cny" }
        unit_factor_to_million_cny: 1      # 增速族:已是百万元 → 系数 1
      knobs:
        revenue_yoy: [<×7>]
      history:
        note: "增速族存 revenue/cost 两序列"
        series:
          revenue: { <year>: <v>, ... }
          cost:    { <year>: <v>, ... }

income.gpm:                                # 再参数化翻转:整体毛利率手拍
  kind: knob
  values: [<逐年×7>]
  src: "#整体毛利率(主动覆盖·参数化翻转)"

income.cost_rates.sell_exp:       { kind: knob, values: [<×7>], src: "#销售费用" }
income.cost_rates.admin_exp:      { kind: knob, values: [<×7>], src: "#管理费用" }
income.cost_rates.rd_exp:         { kind: knob, values: [<×7>], src: "#研发费用" }
income.cost_rates.biz_tax_surchg: { kind: knob, values: [<×7>], src: "#营业税金及附加" }

# below-OP 绝对值(符号按引擎口径!见附录 A)
income.operating_adjustments_abs.asset_disp_income: { kind: knob, values: [<×7>], src: "#资产处置收益(亏损存负)" }
income.operating_adjustments_abs.forex_gain:        { kind: knob, values: [<×7>], src: "#汇兑损益(亏损存负)" }
income.operating_adjustments_abs.oth_income:        { kind: knob, values: [<×7>], src: "#其他收益" }
income.operating_adjustments_abs.invest_income:     { kind: knob, values: [<×7>], src: "#投资净收益" }
income.operating_adjustments_abs.fv_value_chg_gain: { kind: knob, values: [<×7>], src: "#公允价值变动" }
income.cost_abs.assets_impair_loss:                 { kind: knob, values: [<×7>], src: "#资产减值损失(存负·与.md同号)" }
income.cost_abs.credit_impa_loss:                   { kind: knob, values: [<×7>], src: "#信用减值损失(存负·与.md同号)" }
# 若某减值项 defaults.yaml 未给坐落 → 落值 + # 路径待核 + 进 unaligned
income.below_line_abs.non_oper_income:              { kind: knob, values: [<×7>], src: "#营业外收入" }
income.below_line_abs.non_oper_exp:                 { kind: knob, values: [<×7>], src: "#营业外支出(引擎做减项,存正值)" }

# 财务费用:利息净额引擎倒算不写;其他财务费用(外生·非利息)必写,且必须嵌 income.financial_expense 下(硬契约,详见 §8)
income.financial_expense.other_fin_exp_abs:         { kind: knob, values: [<×7>], src: "#其他财务费用(外生·非利息)" }

income.effective_tax_rate: { kind: knob, values: [<×7>], src: "#有效税率" }
income.minority_ratio:     { kind: knob, values: [<×7>], src: "#少数股东损益率" }

terminal:
  explicit_end: 2031
  fade:
    to_year: <fade_end_year>      # to_year 语义是与清洗层契约;.md 措辞歧义时取自洽解 + 标待核
    kind: linear
    fade_paths: [model.revenue_yoy]
    hold_paths: [income.cost_rates.sell_exp]      # 只有 .md 明示维持稳态的路径才列入
    path_targets:
      income.gpm: <稳态毛利率>     # 若 .md 写 GPM 从显式期末爬到某目标值,用 path_targets 而非 hold_paths
  perpetual_growth: <永续点>
  src: "#往后几年"

stash:                            # B 类独立成块,不塞 A 类 note;多年序列照搬
  分线毛利率:
    note: "历史观测·降级仅参考;多年可由各 leaf history 的 price/cost 还原,compiler 不代算"
    unit: "ratio"
    series: { <line>: { <year>: <v> } }
  副拆分_按地区:   { note: "...", unit: "百万元", series: { <region>: { <year>: <v> } } }
  副拆分_按子公司: { note: "...", unit: "亿元", members: [...], caveat: "...", series: { <sub>: { <year>: <v> } } }
  核对项:          { <校验名>: "<算式/结论原话>" }
  口径与降级说明:  { <断点名>: "<原话>" }
  溯源附注:        { <附注名>: "<原话>" }
  定性情报:        ["<情报 1>", "<情报 2>", "..."]

# 刻意缺席(= 落 yaml2 平推 / 引擎倒算 / 派生):
#   财务费用利息净额(引擎倒算;其他财务费用外生项要写,见上)、营业利润及以下各净利与各净利率、所有未被老板拨动的标准科目和未触发人工覆盖闸的 BS/CF/DCF 驱动。
#   收纳区不属于"刻意缺席"——必须进 stash;分线历史不属于"刻意缺席"——必须进各 leaf history。
```

---

## 一句话

这是一次翻译:把人话的、按业务线组织的、带判断且宽容的 `核心假设.md`,翻成机器话的、按路径组织的、无损零容忍的 `yaml1`。

要弥合四个语法差异——组织维度、深度语义、符号口径、歧义容忍;前三个是形变,照翻;第四个是信息缺口,举旗。

A 类判断逐句认领到 `defaults.yaml` 的真实路径,以正确 `kind` 和正确符号落地,旋钮摊满数组;非标拆分镜像成 ≤2 子树,收入 leaf 优先用当前可执行模板(`factor_product`/`growth`/`abs`/兼容旧名),模板装不下时才用受限 `formulas.nodes` + `formula_ref`;三段式带 hold/fade 分组,每条 leaf 给齐 `base`/`knobs`/`history`。

B 类把分线历史落进各 leaf 的 `history`、收纳区独立成块进 `stash`,多年序列一个不丢。

你不算账、不重算、不折叠、不展开 fade、不发明路径、不自创公式族、不把 B 类塞进 `note`;formula 只接跨期递推、DAG、分段函数、中间变量复用等长尾。

能翻就翻、翻不了举旗、绝不猜。收尾对着盘点清单校对(双射 + B 类完整性 + unaligned/待核 + 主动覆盖人话回读 + 结构异常硬停),交下游 `src/yaml1_cleaner.py` 折叠展开 resolve、`calc.py` 纯算 DCF。
