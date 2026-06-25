# YAML1 算法模板契约

这份文档定义 `yaml1` 里**允许生成、允许清洗、允许进入 DCF 的算法模板**。它的读者是后续接手项目的大模型和人类开发者。

请把它当成三方契约：

- `核心假设源语言` 与 `核心假设编辑器` 负责把公司真实骨架讲清楚，但不直接产 YAML。
- `yaml1compiler` 负责把 markdown 翻成 `yaml1`，只能使用本文列出的可执行模板。
- `yaml1_cleaner.py` 负责把 `yaml1` 折成 `calc.py` 能吃的标准参数。

`calc.py` 不直接理解 `yaml1`。所有业务线、driver、分线毛利率、历史拆分、收纳区信息，都必须先在 cleaner 层折成标准 YAML2 参数。

## 一句话原则

```text
公司骨架可以千变万化，算法模板必须有限、无状态、可审计。
```

行名和 driver 名可以随公司变化：

- 门店数 × 单店收入
- 用户数 × ARPU
- 生息资产 × 净息差
- 装机量 × 利用小时 × 电价
- 产能 × 开工率 × 价差

但它们不应该生成新族名。它们都应优先投影到 `factor_product`。

## 分层

YAML1 收入侧分三层。

```text
结构层:
  decomposition_sum

叶子算法层:
  factor_product
  growth
  abs
  vol_price / vol_price_margin 兼容旧名

折叠层:
  revenue leaves -> model.revenue_yoy
  leaf margins   -> income.gpm

formula/DAG 层:
  formulas.nodes -> formula leaf / YAML2 标准路径 overlay
```

formula/DAG 已有受限执行器，详见 `docs/formula_DAG开发文档.md`。它只在 `yaml1_cleaner.py` 内求值，最终仍必须压平成 `model.revenue_yoy`、`income.gpm` 或 `defaults.yaml` 中已经存在的标准路径。`calc.py` 不直接理解 formula。

## 结构层：decomposition_sum

`decomposition` 是一棵树，默认语义是子节点求和。

```yaml
income.revenue:
  kind: decomposition
  fold_direction: sum
  segments:
    business_a:
      revenue_family: growth
      base: ...
      knobs: ...
    business_b:
      kind: decomposition
      fold_direction: sum
      segments:
        product_1:
          revenue_family: factor_product
          base: ...
          factors: ...
        product_2:
          revenue_family: abs
          base: ...
          knobs: ...
```

当前支持深度：

```text
income.revenue
-> segments.<line>
-> segments.<line>.segments.<subline>
```

也就是收入到产品线，再到产品号，最多两级业务拆分。第三层裸 decomposition 必须举旗，不允许静默生成。

结构层硬规则：

- 一个节点要么是 decomposition（带 `segments`），要么是 leaf，不能既有 `segments` 又自己挂 leaf 旋钮。
- 当前只支持 `fold_direction: sum` / `fold_direction: decomposition_sum`（默认 sum；cleaner 只读 `fold_direction`，不读 `rollup`）。
- `mix_allocation` 还未实现。父定子与子定父不能混在同一节点。
- 遇到 mix / allocation 需求，先举旗，不得伪装成 sum。

## 叶子模板一：factor_product

`factor_product` 是主力收入模板，语义是 n 个因子连乘。

```text
revenue_t = product(factor_i_t) / unit_factor_to_million_cny
```

示例：

```yaml
store_retail:
  revenue_family: factor_product
  base:
    base_year: 2024
    unit_factor_to_million_cny: 1
  factors:
    - key: stores
      label: 门店数
      base: 1000
      projection:
        kind: yoy
        values: [0.10, 0.08, 0.06]
    - key: sales_per_store
      label: 单店收入
      base: 2.5
      projection:
        kind: abs
        values: [2.7, 2.9, 3.0]
```

可用 projection：

| kind | 含义 | 字段 |
|---|---|---|
| `yoy` | 从 base 开始按增速递推 | `values` 满数组 |
| `abs` | 逐年直接给因子绝对值 | `values` 满数组 |
| `constant`（亦可写 `hold`） | 显式期内保持 base 不变 | 不需要 `values` |

适用场景：

- 量 × 价
- 门店数 × 单店收入
- 生息资产 × 净息差
- 装机量 × 利用小时 × 电价
- 产能 × 开工率 × 价格或价差

注意：`factor_product` 不引用别的 leaf，不做跨期递推，不做 DAG。

`driver_rate` 是 `factor_product` 的等价别名（生息资产 × 息差等费率型 driver 场景），cleaner 同样按连乘处理。

## 叶子模板二：growth

`growth` 是收入增速模板。

```yaml
service:
  revenue_family: growth
  base:
    base_year: 2024
    revenue: 1000
    unit_factor_to_million_cny: 1
  knobs:
    revenue_yoy: [0.08, 0.07, 0.06]
```

语义：

```text
revenue_t = revenue_{t-1} * (1 + revenue_yoy_t)
```

它在数学上可以视为单因子退化，但为了审计可读性保留。分析师直接给“这条业务收入增速”时，用 `growth` 最清楚。

## 叶子模板三：abs

`abs` 是逐年绝对收入模板。

```yaml
small_business:
  revenue_family: abs
  base:
    base_year: 2024
    revenue: 100
    unit_factor_to_million_cny: 1
  knobs:
    revenue_abs: [110, 118, 120]
```

语义：

```text
revenue_t = revenue_abs_t / unit_factor_to_million_cny
```

适用场景：

- 小业务线直接拍金额。
- 增速没有业务含义。
- 管理层或材料直接给逐年收入。

## 兼容旧名：vol_price / vol_price_margin

`vol_price` 是旧样本兼容名，等价于二因子 `factor_product`。

```yaml
milk:
  revenue_family: vol_price
  base:
    base_year: 2024
    volume: 100
    price: 5000
    unit_factor_to_million_cny: 100
  knobs:
    volume_yoy: [0.02, 0.02, 0.01]
    price_yoy: [0.01, 0.01, 0.01]
```

`vol_price_margin` 是旧样本兼容名，等价于 `vol_price` 加 leaf margin。

新写法优先使用 `factor_product`，不要为了非乳业公司硬造 `volume` / `price` 字段。门店、客流、息差、电价都应使用真实 driver 名和 `factors[]`。

## 折叠一：收入折成 model.revenue_yoy

cleaner 先算出每个 leaf 的逐年收入，再递归加总到总收入。

```text
total_revenue_t = sum(leaf_revenue_t)
model.revenue_yoy_t = total_revenue_t / previous_total_revenue - 1
```

第一年 yoy 的前一年锚点不是手工分线加总，而是 `clean_annual` 的基年收入。分线 base 加总与 `clean_annual.revenue` 的差异进入 backtest。

最终给 `calc.py` 的只有：

```text
model.revenue_yoy
```

`calc.py` 不知道公司有几条收入线，也不知道 driver 名。

## 折叠二：leaf margin 折成 income.gpm

如果每个 revenue leaf 都带 `margin`，cleaner 会折成整体毛利率。

```yaml
business_a:
  revenue_family: growth
  base: ...
  knobs:
    revenue_yoy: [...]
    margin: [0.35, 0.36, 0.37]
```

折叠公式：

```text
income.gpm_t = sum(leaf_revenue_t * leaf_margin_t) / sum(leaf_revenue_t)
```

最终给 `calc.py` 的只有：

```text
income.gpm
```

`calc.py` 仍然只做：

```text
oper_cost = revenue * (1 - gpm)
```

它不看分线 margin，也不看分线成本。

## margin 与整体 gpm 的二选一规则

这是硬契约。

```text
如果没有任何 revenue leaf 带 margin:
  可以使用顶层 income.gpm knob

如果任何 revenue leaf 带 margin:
  禁止顶层 income.gpm knob
  且所有 revenue leaf 都必须带 margin

如果部分 leaf 有 margin、部分没有:
  清洗失败

如果 leaf margin 与顶层 income.gpm 同时出现:
  清洗失败
```

原因：部分分线毛利 + 整体毛利率手拍是两个口径混用，无法审计。

## formula/DAG 层：受限公式节点

formula 只接模板装不下的长尾，不是默认模板。优先级永远是：

```text
decomposition_sum -> factor_product -> growth -> abs -> leaf margin -> formula/DAG
```

只有出现跨期递推、中间变量复用、分段函数、滞后关系，且无法无损表达为 `factor_product/growth/abs` 时，才允许使用 formula。

全局公式节点写在 `formulas.nodes`：

```yaml
formulas:
  version: 1
  nodes:
    openings:
      kind: input
      unit: store
      values: [80, 90, 95]
      src: "#开店计划"

    stores:
      kind: formula
      unit: store
      expr: "lag(stores, 1) + openings - closures"
      inputs: [stores, openings, closures]
      seeds:
        2024: 1200
      src: "#门店数递推"
```

收入 formula leaf 写在收入树里：

```yaml
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

标准路径 formula overlay 写在对应 YAML2 路径：

```yaml
income.cost_rates.sell_exp:
  kind: formula
  formula_ref: sell_exp_rate
  src: "#固定费用/收入 + 变动费率"
```

安全子集：

- 只允许四则运算、括号、比较、`lag(node, n)`、`min/max/abs/clip/if_else`。
- `inputs` 必须和表达式引用双向一致。
- `lag()` 必须有 `seeds` 或 `history` 支撑。
- DAG 按 `(node, year)` 检测循环；当前年互相引用硬失败，合法滞后允许。
- formula 输出的标准路径必须存在于 `defaults.yaml`。
- formula 收入叶子不得同时写 `revenue_family`、`factors`，或 `knobs.revenue_yoy/revenue_abs/volume_yoy/price_yoy`，否则按 over-determined 硬失败。
- 回测失败、引用缺失、循环、缺 seed 都硬失败（无 `history` 的 formula 节点回测跳过并 warning，不算硬失败；有 `history` 且残差超容差才硬失败）。

以下形态仍不得以自创族名或裸结构进入 yaml1：

- 自创 `revenue_family`
- `mix_allocation`
- `ref` / `lag_ref`
- `bridge`
- `ratio_to_driver`
- 任意 Python / Excel 原生公式

如果确实需要 bridge、ratio_to_driver、跨期递推、分段函数、中间变量复用，必须投影成受限 `formulas.nodes` + `formula_ref`，不得发明新 `kind` 或新 `revenue_family`。

`mix_allocation` 仍未实现，遇到父定子/占比分配需求仍需举旗。

## 模板层与 formula 层的边界

模板层必须同时满足：

- 无状态：不依赖上一期自己之外的状态递推。
- 无引用：不引用其他 leaf 或中间变量。
- 无 DAG：没有拓扑求值。
- 产物直达现有 calc 入口：只折成 `model.revenue_yoy` 或 `income.gpm`。

只要某个算法需要跨期状态、引用别的节点、或产出要被别处复用的中间变量，它就不属于模板层，而属于 formula/DAG 层。

formula/DAG 层必须同时满足：

- 明确的求值边界：只允许在 cleaner 内求值，`calc.py` 仍然只吃标准 YAML2 参数。
- 明确的安全子集：不执行任意 Python。
- 明确的 DAG 规则：循环检测、缺失引用报错。
- 明确的审计输出：每个公式节点的输入、输出、单位、来源和回测结果必须进 clean report。
- 明确的降级规则：回测不过或引用缺失时硬失败，不静默退成 0 或平推。

## compiler 生成检查清单

生成 yaml1 前必须逐项自查：

- 收入树是否只有 `decomposition` + leaf。
- 每个 decomposition 节点是否只做 sum。
- 是否超过两级业务拆分。
- 每个 leaf 的 `revenue_family` 是否属于可执行集合。
- `factor_product` 的每个 factor 是否有 `key`、`label`、`base`、`projection.kind`。
- `projection.kind` 是否只使用 `yoy`、`abs`、`constant`(`hold`)。
- `growth` 是否有 `knobs.revenue_yoy` 满数组。
- `abs` 是否有 `knobs.revenue_abs` 满数组。
- `unit_factor_to_million_cny` 是否结构化写在 leaf base 中。
- 是否出现 leaf margin 与顶层 `income.gpm` 混用。
- 是否出现 partial leaf margin。
- 如出现 formula/DAG，是否严格使用 `formulas.nodes` + `formula_ref`，且没有自创族名。
- 是否出现 mix_allocation。

任一项不满足，举旗，不要生成一个“看起来能跑”的 YAML。

> 自查之外另有一道自动闸：`src/yaml1_fidelity_check.py`（`/comp` 编译后必跑）对照 `核心假设.md` 做忠实度初步核对——抓数组长度/路径嵌套/值抄错/符号反等**形变层低级错误**，不碰语义级判断。详见 `docs/yaml1忠实度校验.md`。它补的是下游 cleaner 的盲区：cleaner 不读 .md，预测旋钮抄错会静默进 DCF。

## cleaner 执行检查清单

修改 `src/yaml1_cleaner.py` 时，必须同步检查：

- `tests/test_yaml1_cleaner.py` 是否覆盖新模板。
- 新模板最终是否只落到 YAML2 已有路径。
- 是否需要更新 `docs/数据流水线.md`。
- 是否需要更新本文件。
- 是否需要更新 `skills/yaml1compiler_v5.md`、`skills/核心假设源语言_skill_v1.md` 和 `skills/核心假设编辑器_skill_v1.md`。
- 是否需要更新 `src/workbench.py` 的 YAML1 breakdown 展示。

## 变更纪律

凡是修改本文定义的契约，必须同步修改：

- `src/yaml1_cleaner.py`
- `tests/test_yaml1_cleaner.py`
- `skills/yaml1compiler_v5.md`
- `skills/核心假设源语言_skill_v1.md`
- `skills/核心假设编辑器_skill_v1.md`
- `docs/数据流水线.md`
- `src/workbench.py`，如果前端展示会受影响

契约漂移比代码缺功能更危险。缺功能可以举旗，契约漂移会让 Agent 生成下游不认的东西。
