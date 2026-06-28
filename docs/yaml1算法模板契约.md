# YAML1 算法模板契约

这份文档定义 `yaml1` 里**允许生成、允许清洗、允许进入 DCF 的算法模板**。它的读者是后续接手项目的大模型和人类开发者。

请把它当成三方契约：

- `核心假设源语言` 与 `核心假设编辑器` 负责把公司真实骨架讲清楚，但不直接产 YAML。
- `yaml1compiler` 负责把 markdown 翻成 `yaml1`，只能使用本文列出的可执行模板。
- `yaml1_cleaner.py` 负责把 `yaml1` 折成 `calc.py` 能吃的标准参数。

`calc.py` 不直接理解 `yaml1`。所有业务线、driver、分线毛利率、历史拆分、收纳区信息，都必须先在 cleaner 层折成标准 YAML2 参数。

## 术语：`revenue_family` 是什么

> **`revenue_family` = 一条收入 leaf 的算法模板字段名**，声明这条线的未来收入用什么数学方法折叠，只能从下面这个有限枚举里选：

```text
factor_product  / driver_rate  / growth  / abs
vol_price / vol_price_margin   （旧样本兼容名）
formula                         （走 formulas.nodes + formula_ref，不是普通 family）
```

- **算法模板**是抽象概念（"量×价连乘""增速递推""逐年绝对值"…）；`revenue_family` 是它在 yaml1 里落地成 leaf 字段的那个枚举值。两者一一对应，文档里常混称"族/family/模板"。
- `yaml1_cleaner.py` 按 `revenue_family` 选折叠分支；`calc.py` 不认 `revenue_family`，只认折出来的 `model.revenue_yoy` / `income.gpm`。
- 可执行集合由 `src/yaml1_fidelity_check.py` 的 `ALLOWED_FAMILY` 守门，自创族名硬失败。

> ⚠️ **同名陷阱：另一个 `family`。** 核心假设.md 末尾 `knobs` 块里也有一个字段叫 `family`，那是**正文旋钮的语义族**（`factor_yoy / growth / abs / gpm / cost_rate / bs_revenue_pct / …`），由 `docs/knobs块契约.md §7` 定义，**与本文的 `revenue_family` 是两个不同枚举**。两者共用 `growth`/`abs` 之名但含义不同：`revenue_family: growth` 是"收入按增速递推的算法模板"，`knobs` 块 `family: growth` 是"这格旋钮是收入增速类输入"。见到 `family` 先确认它在 yaml1 leaf 上还是 knobs 块里。

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
  driver_rate           # factor_product 的等价别名，费率型 driver 场景
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

## terminal fade：交接增速与永续增速

`terminal.fade` 支持在线性衰减里把中期经营交接增速和 Gordon 永续增速拆开：

```yaml
terminal:
  explicit_end: 2030
  fade:
    kind: linear
    to_year: 2037
    target_growth: 0.055
    target_basis: auto_stable_brand
    fade_paths: [model.revenue_yoy]
    hold_paths: [income.cost_rates.sell_exp]
    path_targets:
      income.gpm: 0.32
  perpetual_growth: 0.02
```

语义：

- `target_growth` 是 fade 末年 `fade_paths` 收敛到的交接增速。
- `perpetual_growth` 是 `calc.py` Gordon terminal value 使用的永续增速，并会覆盖 `model.terminal_growth`。
- 缺少 `target_growth` 时，清洗层兼容旧语义：fade 直接收敛到 `perpetual_growth`。
- 若写了 `target_growth`，它必须大于或等于 `perpetual_growth`，否则硬失败。
- `target_basis` 只用于审计和解释，清洗层不执行。允许取值（照抄 `/ka` 的自动档位理由，与 `skills/核心假设编辑器_skill_v1.md` 一致）：`auto_mature`（成熟稳态）/ `auto_stable_brand`（品牌稳态）/ `auto_long_runway`（长坡厚雪）/ `auto_cycle_repair`（周期修复）。写哪个不影响 cleaner 计算，只留给读者解释"凭什么 fade 到这个交接增速"。
- `path_targets` 是可选路径级目标值映射：路径必须已经在 yaml1 overlay 中存在，cleaner 会把该路径从显式期末值线性延伸到 `to_year` 目标值。它用于 `income.gpm: 31.1% -> 32.0%`、`income.operating_adjustments_abs.asset_disp_income: -60 -> -40` 这类非收入增速的中期目标。
- `path_targets` 使用 yaml1 标准单位：比率写小数，金额写百万；同一路径不得同时出现在 `fade_paths` 或 `hold_paths`。

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
- 当前只支持 `fold_direction: sum` / `fold_direction: decomposition_sum`（默认 sum；cleaner 只读 `fold_direction`，不读 `rollup`）。**两者当前行为完全等价**：cleaner 都走 `_sum_revenue_folds` 递归求和子节点（`yaml1_cleaner.py` 里没有按 `decomposition_sum` 分叉的分支）。`decomposition_sum` 只是显式语义名，`sum` 是默认值；保留两个名是为未来 `mix_allocation`（父定子/占比分配）占位区分。见到任一都按"子节点求和"理解，不要期待不同行为。
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

### `unit_factor_to_million_cny` 结构化规则（硬约束）

cleaner 是纯确定性 Python，**绝不解析中文 note 拿系数**，所以换算系数必须结构化写在 leaf `base.unit_factor_to_million_cny`。按 family 给，不全局拍一个：

| family | base 已是百万元？ | 典型 unit_factor | 例子 |
|---|---|---|---|
| `factor_product` / `driver_rate` | 否（因子连乘后才是收入） | 按连乘后的单位给 | 万吨 × 元/吨 → `100`；装机量 × 利用小时 × 元/度 → 视连乘结果定；连乘后已是百万元 → `1` |
| `vol_price` / `vol_price_margin` | 否（量 × 价） | 通常 `100` | 万吨 × 元/吨 → `100` |
| `growth` / `abs` | 是（base 直接是 revenue） | `1` | base 已是百万元 |
| `formula` | 视 formula 输出单位 | 同上判断 | formula 输出已是百万元 → `1` |

增速线最常见的错：base 已是百万元却写 `100`，收入被缩小 100 倍。**按 leaf 自己的族判，不是按公司判。**

`driver_rate` 是 `factor_product` 的等价别名，**cleaner 走同一个分支**（`yaml1_cleaner.py:410` `elif family in {"factor_product", "driver_rate"}`），结构完全相同：用 `factors[]`、按 n 因子连乘、`unit_factor_to_million_cny` 同规则。两者行为零差异，只是语义标签：

- `factor_product`：因子是"量"类实体（门店数、用户数、装机量、产能）。
- `driver_rate`：因子里有"费率/率"类 driver（生息资产 × 净息差、贷款余额 × 收益率 × 减值率）。"率"作因子时用 `driver_rate` 比 `factor_product` 更达意。

选哪个都不影响计算；新写法默认用 `factor_product`，"率型 driver"语义明显时用 `driver_rate`。不要两者混用，一条 leaf 只声明一个。

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

## family × 前端行可编辑性矩阵（单一真源）

核心假设展示页把每条业务线渲染成四类行：**收入行 / 同比行 / 销量行 / driver 行**。哪些可编辑、哪些派生只读，由该 leaf 的 `revenue_family` 唯一决定。本表是 `family` → 行可编辑性的权威定义，`app/src/App.tsx`（`VOLUME_FAMILIES`、`revenue_yoy`/`revenue_abs` 拎出逻辑）按此实现。

本节只定义 **A 类可执行收入 leaf 在前端里的可编辑性**，不决定 `stash` / B 类信息应放在主表、副拆分还是 Reference。B 类展示去向由 `docs/yaml1前端展示契约.md` 的 `display` 契约定义；没有显式 `display` 的旧 yaml1 由 `workbench.py` 保守推断，宁可留在 Reference，也不得把参考材料伪装成主表。

| family | 收入行 | 同比行 | 销量行 | driver 行 |
|---|---|---|---|---|
| `growth` | 派生·只读 | `revenue_yoy` 可编辑 | 无 | 无 |
| `abs` | `revenue_abs` 可编辑 | 派生·只读 | 无 | 无 |
| `factor_product` / `driver_rate` / `vol_price` / `vol_price_margin` | 派生·只读 | 派生·只读 | 有（单位从 `base.unit.volume` 通用映射） | 因子 driver 可编辑（`factors[].projection.values`） |
| `formula` | 派生·只读 | 派生·只读 | 无 | 无（输入走 `formulas.nodes` 另处编辑） |

设计约束（与模板层一致）：

- **每个 family 恰好露一个真输入为可编辑行，其余全部派生只读**——避免收入行与同比行同时对偶可改的过度决定。`growth` 露同比，`abs` 露收入，量价族露因子 driver。
- **销量行只给量价族**（`VOLUME_FAMILIES = {factor_product, vol_price, vol_price_margin, driver_rate}`）。`growth`/`abs`/`formula` 没有"量"的概念，强行画销量行就是把公司特征焊进模板（铁律 2）。销量单位从 `base.unit.volume` 通用映射，不硬编码"万吨"。
- **`formula` 不占销量/driver 行**：它已升级到 DAG 层，输入是 `formulas.nodes` 的 `inputs`/`seeds`，不走 `factors[]`，不套用本行矩阵。
- 派生行的展示值由 `assumption-preview` 内存重算；改一个可编辑格，同线派生格实时跟随。落盘走 `/frontend-edit` 定点 patch yaml1 + 跑 forecast。

## history series × family 映射

每个 revenue leaf 的 `history.series` 存什么序列，由 `revenue_family` 决定（法定归宿，详见 `yaml1compiler_v5 §5.3`）：

| family | history.series 存什么 | 说明 |
|---|---|---|
| `factor_product` / `driver_rate` | `revenue` + 各 factor 序列 + `cost` | 量价/因子线存 driver 序列（如 `volume`/`price` 或各 factor key），收入由连乘派生 |
| `vol_price` / `vol_price_margin` | `revenue` + `volume` + `price` + `cost` | 量价旧写法固定存 volume/price 两序列 |
| `growth` / `abs` | `revenue` + `cost` | 增速/绝对值线只存收入与成本两序列，无 driver |
| `formula` | `revenue` + `cost` + formula 节点的 `history`/`seeds` | formula 节点自身的滞后序列写在 `formulas.nodes.<node>.history` |

规则：history 是**过去**的完整记录（占位/异常/断点年在 `note` 标，不进计算）；knobs 是**未来**的旋钮。两者不可混写同一年。history 不参与 cleaner 折叠未来收入，只用于 backtest（分线 base 加总 vs `clean_annual.revenue` 的差异）。

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

## 端到端 worked example

把一棵 decomposition 树从头折到 `calc.py` 入口，看每个 family 怎么落地。假设一家简化的乳企，基年 2024，预测期 2025-2027：

```yaml
income.revenue:
  kind: decomposition
  fold_direction: sum
  segments:
    liquid_milk:                    # 主业：量×价，因子连乘
      revenue_family: factor_product
      base: { base_year: 2024, unit_factor_to_million_cny: 100 }   # 万吨×元/吨→百万元
      factors:
        - { key: volume,  label: 销量(万吨), base: 50, projection: { kind: yoy, values: [0.05, 0.04, 0.03] } }
        - { key: price,   label: 吨价(元),   base: 8000, projection: { kind: yoy, values: [0.02, 0.02, 0.02] } }
      knobs:
        margin: [0.30, 0.31, 0.32]   # 分线毛利率 → 折 income.gpm
    other_business:                  # 小业务：老板直接拍金额
      revenue_family: abs
      base: { base_year: 2024, revenue: 200, unit_factor_to_million_cny: 1 }
      knobs:
        revenue_abs: [210, 220, 230]
        margin: [0.15, 0.15, 0.15]
```

**Step 1 — 折每个 leaf 的逐年收入**（cleaner `_fold_revenue_leaf`）：

- `liquid_milk`（factor_product，unit_factor=100）：
  - base_revenue = 50 × 8000 / 100 = 4000（百万元）
  - 2025 = 50×1.05 × 8000×1.02 / 100 = 4284
  - 2026、2027 同理连乘递推。
- `other_business`（abs，unit_factor=1）：
  - base_revenue = 200 / 1 = 200
  - 2025 = 210 / 1 = 210；2026 = 220；2027 = 230。

**Step 2 — 结构层求和**（`_sum_revenue_folds`，`fold_direction: sum`）：

```
total_revenue_2025 = 4284 + 210 = 4494
```

**Step 3 — 折成 `model.revenue_yoy`**（折叠一）：

```
model.revenue_yoy_2025 = total_2025 / clean_annual.revenue_2024 - 1
```

第一年前一年锚点用 `clean_annual` 基年收入，不是手工分线加总；分线 base 加总与 clean_annual 的差异进 backtest。

**Step 4 — 折成 `income.gpm`**（折叠二，每个 leaf 都带 margin）：

```
income.gpm_2025 = (4284×0.30 + 210×0.15) / (4284 + 210)
```

因每个 revenue leaf 都带了 `margin`，cleaner 折成整体 `income.gpm`；此时**禁止**再写顶层 `income.gpm` knob（margin 互斥硬规则）。

**Step 5 — 交给 calc.py**：calc 只看到 `model.revenue_yoy` 和 `income.gpm` 两条序列，不知道公司有几条线、不知道 driver 名，做 `oper_cost = revenue × (1 − gpm)` 推下去。

这五步就是把"人话判断"压平成"机器参数"的全过程：family 决定折法 → 求和 → 折 yoy → 折 gpm → calc 算账。任何一步对不上，就是契约违规，cleaner 硬失败举旗。

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
