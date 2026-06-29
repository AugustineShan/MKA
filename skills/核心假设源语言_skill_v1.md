# 核心假设源语言 - Skill v1

这份文件是 `核心假设.md` 的共享语法单一真源。`/brkd`、`/load`、`/ka` 产出同构半成品或正式稿，`/adj` 和 `/annual-update` 编辑同一套语言，`/comp` 读取这套语言并翻译成 `yaml1`。

本文件是 library/include，不是可独立调用的 operation skill。不要把它当成 `/核心假设源语言` 命令执行。

标准块头、候选稿清单、official `reference 裁决回执`、受控词表与 B 类去向的精简语法见 `docs/核心假设源语言语法规范.md`；本文件保留 B 系列 runbook 和边界纪律，不重复展开。

纪律见 `skills/核心纪律_skill_v1.md`。本文件只管“写成什么形状”。若分不清规则归属，先看 `docs/MKA规则导航图.md`。

## B0. 源语言定位

`核心假设.md` 是人话判断稿，不是 YAML1，也不是 `model_assumption_schema.json`。

它必须让人能复盘，也让 `/comp` 能无损翻译：

- 人读：知道谁定、为什么、哪来的、还有什么没进模型。
- 机器读：知道上挂科目、compiler family、逐年旋钮、horizon、terminal。

## B0.1 范围边界：默认利润表 + 业务层盈利模型

BRKD、LOAD、KA 默认收窄为“利润表 + 业务层盈利模型”这套源语言：收入、成本/毛利、费用率、below-OP、税率、少数股东等利润表相关判断可以进入正文和 knobs；BS/CF/DCF 驱动因素默认由 defaults.yaml、引擎或专门流程平推，不主动在这层建预测旋钮。

默认不得把 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等写成 BRKD/LOAD/KA 的预测对象或待拍板项：

- `financial expense` 若来自现金、债务、利率或 BS 推导，视为引擎/专门流程派生，不进入本层旋钮；只有材料明确给出“其他财务费用”这类利润表外生项时，才可用 `other_fin_exp_abs`。
- `EBIT`、营业利润、利润总额、净利润等派生利润不作旋钮；只能作为 sanity/观察，不能倒算残差。
- `DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等默认交引擎/defaults/专门流程处理，不在 `/brkd` 或 `/ka` 中主动裁决。
- 材料中出现这些驱动因素但没有被分析师明示为核心 thesis 时，按核心纪律 A2 给明确去处：写入收纳区并标“非本层范围”，或写明丢弃原因；禁止静默删掉，也禁止包装成利润表预测。

人工注入例外：如果同权重判断材料或分析师明确说某个 BS/CF 因素是核心投资假设，例如周转率提升、库存去化、应收压降、合同负债改善、资本开支变化、折旧政策变化，则 `/ka` 可以单独开“资产负债表/营运资本/现金流人工覆盖”块。该例外必须同时满足：

1. 先确认它是核心 thesis，不是为了“模型完整”顺手补。
2. 必须落到现有 defaults.yaml/yaml1 命名空间，例如 `balance_sheet.revenue_pct.*`、`balance_sheet.cogs_days.*`、`balance_sheet.capex_pct`、`balance_sheet.depr_rate` 等；`/comp` 不得发明路径。
3. 一个经济事项只能有一个旋钮：用存货周转天数，就不要再手填未来存货金额；用应收/收入占比，就不要再手填应收周转率。
4. `DA/CAPEX` 若需要重资产排程、转固时滞或资产 cohort，优先走 `/da` 生成 `Agent/da_schedule.yaml`；`/ka` 只记录“需要 /da”或轻资产默认率覆盖，不自己造排程。
5. 模板装不下时举旗为“现有模板不足，需 formula/引擎扩展”，不要硬塞到普通费用率、收入占比或利润表旋钮。

## B1. 标准过表顺序

所有正式或半成品核心假设源文按这个顺序组织：

```text
时间轴/本轮判断锚点 -> 收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 可选 BS/营运资本/现金流人工覆盖 -> 中期/terminal -> 收纳区 -> knobs
```

这不是纯纪律，而是源语言章节顺序。`/ka`、`/load`、`/annual-update`、`/adj incremental` 在需要逐段讨论时，也按这个顺序走。

## B2. 抬头

正式稿或可编译稿必须包含：

```text
模式: ka / load / annual-update / adj
状态: official / reference / draft / model-extracted / factpack/reference / estimated·待校准
历史数据至: YYYY
显式预测期: [YYYY, ...]
衰减期至: YYYY 或 none
衰减交接增速: x% / none
永续增长: x%
门槛来源: BRKD / LOAD / BRKD+LOAD / old official draft / annual-update
来源层级: ka / brkd / load-vintage / alphapai / annual-update / adj
可被谁读取: /ka / /comp / /adj / 前端 / 人工
不可被谁读取: 例如不可直接 /comp、不可作为 official forecast
上游材料: markdown存储区 / Agent业务讨论.md / load_id / Alphapai factpack / 人工对话
```

`状态: reference`、`状态: draft`、`状态: model-extracted` 或 `状态: factpack/reference` 的文件必须包含：

```text
## 待 /ka 裁决清单
```

清单逐条写事项、候选值/方向、证据、分歧/缺口、建议处理。它是 reference 晋升为 official 的会议议程，不是正式拍板结果。

`/brkd` 草稿可不锁最终四数，但必须写：

```text
状态: draft，待 /ka 拍板
建议 horizon / 拐点年份: ...
```

## B3. 业务线块

收入和其他业务线尽量写成固定块：

```markdown
### {业务线} [上挂: 营业收入; compiler: factor_product/growth/abs/formula; status: draft/model-extracted/official]
- 这条线是什么:
- 参数化:
  - 旋钮:
  - 派生:
- 历史:
  - headline:
  - 业务原子:
  - 来源层级:
  - 单位:
- 预测:
- 三件套:
  - 谁定:
  - 为什么:
  - 来源:
- 来源与裁决:
- 风险/缺口:
```

非收入标准科目也遵守同一原则：上挂科目、compiler family、历史、预测、三件套、来源与裁决。

## B3.1 可选 BS/营运资本/现金流人工覆盖块

只有触发 B0.1 的人工注入例外时，才新增本块；没有明确核心 thesis 时不要写。

```markdown
## 资产负债表与营运资本人工覆盖

### {科目/旋钮名} [上挂: {BS/CF标准科目}; compiler: bs_revenue_pct/bs_cogs_days/bs_scalar_pct; status: official]
- 触发原因: 这是核心 thesis，因为...
- defaults/yaml1 目标路径: balance_sheet.revenue_pct.accounts_receiv / balance_sheet.cogs_days.inventories / balance_sheet.capex_pct / ...
- 历史:
  - headline:
  - 事实原子:
  - 来源层级:
  - 单位:
- 预测:
- 三件套:
  - 谁定:
  - 为什么:
  - 来源:
- 唯一旋钮声明: 本项只用 {收入占比/成本天数/capex_pct/depr_rate}，不同时手填未来金额或派生周转率。
- 来源与裁决:
- 风险/缺口:
```

示例：

```markdown
### 存货周转天数 [上挂: 存货; compiler: bs_cogs_days; status: official]
- 触发原因: 库存去化是本轮核心 thesis。
- defaults/yaml1 目标路径: balance_sheet.cogs_days.inventories
- 历史: 2022=55天，2023=51天，2024=48天；来源: /init clean_annual + 年报存货披露。
- 预测: 2025=46天，2026=44天，2027=42天，2028=40天。
- 三件套: 谁定=分析师；为什么=供应链改革 + SKU 精简；来源=同权重判断材料（公司判断和最新观点.md + 重要文件/）。
- 唯一旋钮声明: 只拍存货周转天数，不手填未来存货金额。
```

若目标路径在当前公司 `defaults.yaml` 中不存在，正文保留判断并写入缺口：`路径待核 / 需 formula 或引擎扩展`，不得硬塞。

## B4. compiler family

常用 family：

- `factor_product`：量 x 价、门店 x 单店、用户 x ARPU、产能 x 利用率 x 价格等。
- `driver_rate`：`factor_product` 的等价别名，费率型 driver 场景（生息资产 × 净息差等），cleaner 按连乘处理。
- `growth`：收入或标准科目的增速。
- `abs`：绝对值。
- `income.gpm knob`：整体毛利率手拍。
- `leaf margin -> income.gpm`：分线毛利折叠。
- `cost_rate`：税金及附加、销售、管理、研发费用率。
- `abs below-OP`：减值、投资收益、其他收益、公允、资产处置、营业外收支等绝对值项。
- `other_fin_exp_abs`：其他财务费用外生项，仅限材料明确作为利润表外生项给出；BS/现金/债务派生的 `financial expense` 不写。
- `bs_revenue_pct`：BS 科目 / 收入的人工覆盖，例如应收账款、合同资产、预付款、合同负债等，必须落到 `balance_sheet.revenue_pct.*` 现有路径。
- `bs_cogs_days`：以营业成本天数表达的营运资本人工覆盖，例如存货周转天数、应付账款天数，必须落到 `balance_sheet.cogs_days.*` 现有路径。
- `bs_scalar_pct`：轻资产/稳态下对 `balance_sheet.capex_pct`、`balance_sheet.depr_rate` 等 defaults 标量路径的人工覆盖；重资产排程优先 `/da`。
- `formula`：受限长尾，不是默认选择。

family 硬规则（`/ka` 写稿时守）：

- **不得自创族名**：只能用上面列出的 family；模板装不下的跨期/DAG/分段/中间变量复用，走 §B5 受限 formula，不发明新 family。
- **margin 互斥（二选一）**：毛利要么整体手拍（`income.gpm` knob），要么分线派生（每条 revenue leaf 都挂 `leaf margin`）。两者不可同篇混用；分线派生时**所有** revenue leaf 都必须挂 margin，部分有部分无 = 写稿失败。这是 `/ka` 骨架门"毛利是分线派生还是整体手拍"的硬约束。
- **leaf margin 的 knobs 回声**：分线毛利率在末尾 `knobs` 块**不写独立条目**（`leaf_margin` 是 Gate C 已知缺口，写独立条目会被判 block 多写）。这是 A6"正文与 knobs 同源回声"的**显式例外**：分线毛利率的回声通过该 leaf 的收入旋钮 + 正文毛利率行体现，不进 knobs 块不算违反 A6。详见 `docs/knobs块契约.md` §7。
- **family 仅是 .md 块头声明**：`/ka` 在块头写 `compiler: <family>` 即可，不写 unit_factor、fold_direction、factors[] 结构——那些是 `/comp` 翻译成 yaml1 时的事。cleaner 折叠机制、unit_factor 换算、family→前端行可编辑性等 yaml1 侧细节见 `docs/yaml1算法模板契约.md`（`/comp` 读，`/ka` 不需加载）。

## B5. 受限 formula

算法提升放在本文件，不进核心纪律。

formula 只在这些情况可建议：

- 源 Excel 公式层明确有跨期、滞后、DAG、分段或中间变量复用。
- 常规模板 `factor_product` / `growth` / `abs` / margin fold 装不下。
- 下游 `docs/yaml1算法模板契约.md` 或 `yaml1compiler_v*.md` 已支持对应受限形态。

禁止：

- 自创族名。
- 因为想显得聪明而第一轮就用 formula。
- 在 `/brkd` 中把未经验证的研究想法写成可执行 formula。

`/load` 可以逆向公式层；`/ka` 可以裁决是否采用；`/brkd` 只能给草稿建议。

公式逆向必须额外守三条：

- 举手共探：逆向出的算法本身也是假设。必须先在对话里押“公式来源 range / 变量 / seed / 跨期关系 / 采用理由 / 替代简单族”，问分析师是否采信；禁止自己闷头造公式并静默落盘。
- 待回测闭环：任何 formula 草案或 load 逆向 formula，未被下游历史复现验证前，必须标 `待回测验证`，并在风险/缺口或来源与裁决中写明交给 `/comp` 后的 cleaner/回测台验证。回测失败则退回模板族或举旗。
- fallback：问不清、公式层证据不足、下游契约不支持、或回测过不了时，退回最简单可解释族近似，并标 `⚠️ formula未采用/待补`；禁止硬编一个看似精细的公式。

## B6. 历史写法

历史只写骨架需要的绝对值原子 + 上挂 headline。

推荐格式：

```markdown
- 历史:
  - headline: 营业收入 2022=..., 2023=..., 2024=...
  - 业务原子:
    - 销量: 2022=..., 2023=...
    - 单价: 2022=..., 2023=...
  - 来源层级: /init headline / 年报分部 / LOAD load-vintage / BRKD线索
  - 单位: 百万元 / 万吨 / 元/吨 / pct
```

yoy、毛利率、占比等可推导量只能写在观察或 sanity 中，不作为历史原子。

## B7. 三件套

每个预测旋钮必须回答：

```text
谁定: 分析师 / 同权重判断材料 / LOAD原模型 / BRKD草稿 / 年报查证
为什么: 业务逻辑、趋势、管理层指引、竞争格局、会计口径
来源: 文件/段落/模型range/对话拍板
```

若有冲突，必须写“来源与裁决”：

```text
候选A: ...
候选B: ...
采用: ...
为什么:
未采用方去处: 收纳区 / 缺口 / 丢弃原因
```

这条专门防止同构 passthrough：长得像正式块，不等于可以直接抄成正式块。

## B8. 收纳区

不进计算但有复盘价值的信息进入收纳区：

- 副拆分：地区、渠道、产品号、子公司。**副拆分收入**写进收纳区；**毛利率/同比由 /comp 从 /init 产物 `OfficialBreakdowns/business_revenue_breakdown.csv` 自动提取注入 yaml1 stash，KA 不需手写**（年报未披露 major 毛利率的 item 自动缺，前端不渲染）。
- 口径差和加总差。
- 管理层定性表述。
- load-vintage 风险。
- brkd 线索但未拍板项。
- 年报查证但不入模项。

收纳区不能只留死引用；能誊数就誊数，誊不动就写精确待办。

## B9. knobs 块

末尾必须有 `knobs` 块。完整契约见 `docs/knobs块契约.md`；本节只放源语言侧最小形态。

它是正文旋钮的同源回声，不是 YAML1。

基本形态：

````markdown
```knobs
horizon: [2025, 2026, 2027]
terminal:
  explicit_end: 2027
  fade:
    to_year: 2032
    target_growth: 0.055
  perpetual_growth: 0.025
knobs:
  - anchor: "#业务线A"
    sub: 收入
    family: growth
    unit: pct
    values: [5, 4, 3]
    status: official
    source: "正文同源"
```
````

规则：

- 值与正文一字不差。
- flat 也展开逐年。
- draft 可以留空，但必须写原因。
- 不写 yaml1 path。
- 不导出完整拆分结构。
- 不做会计化路径映射。
- `unit: pct` 写百分数显示值，例如 `5` 表示 5%，不是 `0.05`。

## B10. 状态标签

- `draft`：草稿，待 `/ka` 拍板。
- `model-extracted`：来自 `/load` 的原模型 vintage。
- `official`：`/ka` 或正式更新流程拍板。
- `reference`：有悬项，不可直接 `/comp`；必须带 `待 /ka 裁决清单`。
- `factpack/reference`：只含事实抓取或网页端参考，供 `/ka` 裁决，不含正式预测拍板。
- `estimated·待校准`：年度更新声明式估算的实际值，不能冒充真实披露。

状态必须跟随块，而不是只写在文件开头。
