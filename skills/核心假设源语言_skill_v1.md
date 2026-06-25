# 核心假设源语言 - Skill v1

这份文件是 `核心假设.md` 的共享语法单一真源。`/brkd`、`/load`、`/ka` 产出同构半成品或正式稿，`/adj` 和 `/annual-update` 编辑同一套语言，`/comp` 读取这套语言并翻译成 `yaml1`。

本文件是 library/include，不是可独立调用的 operation skill。不要把它当成 `/核心假设源语言` 命令执行。

纪律见 `skills/核心纪律_skill_v1.md`。本文件只管“写成什么形状”。

## B0. 源语言定位

`核心假设.md` 是人话判断稿，不是 YAML1，也不是 `model_assumption_schema.json`。

它必须让人能复盘，也让 `/comp` 能无损翻译：

- 人读：知道谁定、为什么、哪来的、还有什么没进模型。
- 机器读：知道上挂科目、compiler family、逐年旋钮、horizon、terminal。

## B1. 标准过表顺序

所有正式或半成品核心假设源文按这个顺序组织：

```text
时间轴/本轮判断锚点 -> 收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 中期/terminal -> 收纳区 -> knobs
```

这不是纯纪律，而是源语言章节顺序。`/ka`、`/load`、`/annual-update`、`/adj incremental` 在需要逐段讨论时，也按这个顺序走。

## B2. 抬头

正式稿或可编译稿必须包含：

```text
模式: ka / load / annual-update / adj
状态: official / reference / draft / model-extracted
历史数据至: YYYY
显式预测期: [YYYY, ...]
衰减期至: YYYY 或 none
永续增长: x%
门槛来源: BRKD / LOAD / BRKD+LOAD / old official draft / annual-update
```

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

## B4. compiler family

常用 family：

- `factor_product`：量 x 价、门店 x 单店、用户 x ARPU、产能 x 利用率 x 价格等。
- `growth`：收入或标准科目的增速。
- `abs`：绝对值。
- `income.gpm knob`：整体毛利率手拍。
- `leaf margin -> income.gpm`：分线毛利折叠。
- `cost_rate`：税金及附加、销售、管理、研发费用率。
- `abs below-OP`：减值、投资收益、其他收益、公允、资产处置、营业外收支等绝对值项。
- `other_fin_exp_abs`：其他财务费用外生项。
- `formula`：受限长尾，不是默认选择。

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
谁定: 分析师 / 最高权重材料 / LOAD原模型 / BRKD草稿 / 年报查证
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

- 副拆分：地区、渠道、产品号、子公司。
- 口径差和加总差。
- 管理层定性表述。
- load-vintage 风险。
- brkd 线索但未拍板项。
- 年报查证但不入模项。

收纳区不能只留死引用；能誊数就誊数，誊不动就写精确待办。

## B9. knobs 块

末尾必须有 `knobs` 块。它是正文旋钮的同源回声，不是 YAML1。

基本形态：

````markdown
```knobs
horizon: [2025, 2026, 2027]
terminal:
  explicit_end: 2027
  fade:
    to_year: 2032
  perpetual_growth: 0.025
knobs:
  - anchor: "#业务线A"
    family: growth
    unit: pct
    values: [0.05, 0.04, 0.03]
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

## B10. 状态标签

- `draft`：草稿，待 `/ka` 拍板。
- `model-extracted`：来自 `/load` 的原模型 vintage。
- `official`：`/ka` 或正式更新流程拍板。
- `reference`：有悬项，不可直接 `/comp`。
- `estimated·待校准`：年度更新声明式估算的实际值，不能冒充真实披露。

状态必须跟随块，而不是只写在文件开头。
