# YAML1 Formula/DAG 开发文档

状态：**实验性 · 受限可执行**。代码闭环已达成（`src/yaml1_formula.py` 求值器 + cleaner 接入 + 8 个 formula 单元测试绿），但**仅在合成 fixture 上验证过，尚无真实异构公司跑通**。在第二家异构公司（如茅台基酒链/产能滞后类）实跑通过前，不应视为"稳定/生产可用"。  
日期：2026-06-16  
拥有者：`src/yaml1_cleaner.py`  
相关契约：`docs/yaml1算法模板契约.md`、`skills/yaml1compiler_v4 (2).md`

> **收口标准（升"稳定"的硬条件）**：① 全套测试绿（已达成，83 passed）；② 至少一家真实异构公司从 compiler 生成 `formulas` → cleaner 求值 → calc 跑通 → 回测过（**未达成**）。达成 ② 之前，本文与 ARCHITECTURE/设计文档一律以"实验性·受限"口径记录。

## 一句话定位

Formula/DAG 不是新的财务引擎，也不是把 Excel 原样塞进 Python。

它是 `yaml1_cleaner.py` 里的受限公式求值层：把复杂业务算法先求成逐年序列，再压平成 `calc.py` 已经认识的标准参数。`calc.py` 继续只吃 `.modelking/forecast_params.yaml`，永远不直接读取 yaml1、formula、DAG、业务 driver 或中间变量。

```text
核心假设.md
  -> yaml1*.yaml
  -> yaml1_cleaner.py
       1. evaluate formula/DAG
       2. fold revenue decomposition
       3. derive margin fold
       4. collect knob/formula overlay
       5. expand terminal fade
       6. resolve onto defaults.yaml
  -> .modelking/forecast_params.yaml
  -> calc.py
```

这条边界不许破。Formula 可以增加 cleaner 的表达力，但不能扩大 calc 的职责。

## 为什么要一次做完整

Formula/DAG 的危险不在表达式难写，而在半成品会制造新的契约漂移：

- compiler 以为能生成，cleaner 其实只能吃一半。
- cleaner 只算收入公式，但 overlay / report / backtest 没跟上。
- 支持了当前年引用，却没按年份建图，滞后链被误判成循环或漏判循环。
- 报错不硬，缺引用静默变成 0 或平推。

因此上线口径是一次闭环，而不是先开一个“看起来能用”的小口子。可以分模块实现，但同一轮必须同时完成 schema、求值器、revenue leaf 接入、标准路径输出、审计 report、测试、skill 和契约文档同步。

## 核心概念

**Formula node**：一个逐年序列节点。它可以是外生输入，也可以由表达式派生。

**DAG**：formula node 之间的依赖图。图必须无环。真正建图单位不是节点名，而是 `(node_id, year)`，因为 `stores[2027]` 依赖 `stores[2026]` 是合法滞后，`stores[2027]` 依赖 `stores[2027]` 才是循环。

**Input node**：直接给定逐年值的节点，例如开店数、关店数、单店收入。

**Expression node**：由表达式计算的节点，例如 `stores = lag(stores, 1) + openings - closures`。

**Target**：formula 的输出去哪里。第一类是 revenue decomposition 里的 formula leaf，第二类是已经存在于 `defaults.yaml` 的标准 YAML2 路径。

**Seed**：滞后递推需要的历史起点。例如 `stores[2025]` 要算 `stores[2026]`，必须有 `stores` 的 2025 种子。

## YAML1 Schema 草案

### 公式节点区

`formulas.nodes` 是全局公式节点表。节点 id 只能使用 `[A-Za-z_][A-Za-z0-9_]*`，不允许点号，避免和 YAML2 路径混淆。

```yaml
formulas:
  version: 1
  nodes:
    openings:
      kind: input
      unit: store
      values: [80, 90, 95, 100, 100]
      history:
        2023: 60
        2024: 70
      src: "#门店计划"

    closures:
      kind: input
      unit: store
      values: [10, 12, 12, 12, 12]
      history:
        2023: 8
        2024: 9
      src: "#门店计划"

    stores:
      kind: formula
      unit: store
      expr: "lag(stores, 1) + openings - closures"
      inputs: [stores, openings, closures]
      seeds:
        2024: 1200
      history:
        2023: 1138
        2024: 1200
      src: "#门店数 = 期初 + 开店 - 关店"

    revenue_per_store:
      kind: input
      unit: million_cny_per_store
      values: [2.10, 2.16, 2.22, 2.28, 2.35]
      history:
        2023: 1.98
        2024: 2.05
      src: "#单店收入假设"

    retail_revenue:
      kind: formula
      unit: million_cny
      expr: "stores * revenue_per_store"
      inputs: [stores, revenue_per_store]
      history:
        2023: 2253.24
        2024: 2460.00
      src: "#门店数 × 单店收入"
```

规则：

- `kind: input` 必须有 `values`，长度等于 `meta.horizon`。
- `kind: formula` 必须有 `expr` 和 `inputs`。
- 所有节点必须有 `unit`。
- 使用 `lag(node, n)` 时，必须有足够的 `seeds` 或 `history` 覆盖最早依赖年。
- `history` 用于回测，不参与未来预测，除非它同时承担 lag seed。
- `src` 必须指向核心假设或材料来源，不能空白。

### Revenue formula leaf

收入树仍然以 `decomposition` 为结构层。Formula 只是一种 leaf 算法，不改变 sum rollup。

```yaml
income.revenue:
  kind: decomposition
  fold_direction: sum
  segments:
    retail:
      kind: formula
      formula_ref: retail_revenue
      base:
        base_year: 2024
        revenue: 2460.0
        unit_factor_to_million_cny: 1
      history:
        revenue:
          2023: 2253.24
          2024: 2460.00
      src: "#零售线收入 = 门店数 × 单店收入"
```

规则：

- `formula_ref` 必须引用 `formulas.nodes` 中存在的节点。
- 该节点求值后的单位必须能通过 `base.unit_factor_to_million_cny` 转成百万元收入。
- formula leaf 不得同时写 `revenue_family`、`factors`、`knobs.revenue_yoy` 或 `knobs.revenue_abs`。
- base revenue 是历史原子，必须来自材料或核心假设，不允许为了和总收入配平而改。

### 标准路径 formula overlay

除了收入 leaf，formula 也可以直接覆盖一个 YAML2 标准路径，但路径必须已经存在于 `defaults.yaml`。

```yaml
income.cost_rates.sell_exp:
  kind: formula
  formula_ref: sell_exp_rate
  src: "#销售费用率 = 固定费用 / 收入 + 变动费用率"
```

规则：

- path 必须能在 `defaults.yaml` 中找到。
- 该 path 不得同时出现 `kind: knob`。
- formula 输出长度必须等于 `meta.horizon`。
- 后续 terminal fade 可以继续对该 path 做 hold/fade，逻辑与 knob 相同。
- 不允许 formula 输出到 calc 不认识的新路径。运费、吨成本、门店数等中间变量只能留在 `formulas.nodes`，除非有已存在 YAML2 path 承接。

## 表达式安全子集

表达式必须用安全 AST 解析，不允许 `eval` 任意 Python。

允许：

- 数字常量：`1`、`0.15`、`-3.2`
- 节点引用：`stores`、`revenue_per_store`
- 四则运算：`+ - * /`
- 括号
- 比较：`< <= > >= == !=`
- 白名单函数：
  - `lag(node, n)`
  - `min(a, b, ...)`
  - `max(a, b, ...)`
  - `abs(x)`
  - `clip(x, low, high)`
  - `if_else(condition, a, b)`

禁止：

- Python 属性访问、下标访问、lambda、list/dict/set、字符串拼接。
- 未在 `inputs` 声明的节点引用。
- `inputs` 声明了但表达式没用到的节点。
- 任意非白名单函数。
- 除 `lag(node, n)` 外的跨期访问写法。

分段函数统一用 `if_else` 表达，不引入 Python `if`：

```text
if_else(stores > 1500, stores * 2.4, stores * 2.1)
```

## DAG 求值规则

求值器以 `meta.horizon` 为未来显式期，例如 `[2026, 2027, 2028, 2029, 2030]`。

对每个 formula node、每个 year 建立依赖：

- 普通引用 `x` 在 year `t` 依赖 `(x, t)`。
- `lag(x, 1)` 在 year `t` 依赖 `(x, t - 1)`。
- 如果 `t - n` 早于显式期首年，则必须从 `seeds` 或 `history` 取值。

然后对 `(node, year)` 做拓扑排序。

合法：

```text
stores[2027] -> stores[2026]
stores[2026] -> stores[2025 seed]
```

非法：

```text
a[2026] -> b[2026] -> a[2026]
stores[2026] -> stores[2026]
```

缺失引用、缺 seed、当前年循环、跨节点循环都必须硬失败，不能 warning 后继续。

## Cleaner 接入点

`clean_yaml1()` 当前顺序是：

```text
read defaults
read clean_annual
load yaml1
fold_revenue
collect overlay
expand terminal
resolve YAML2
backtest
validate
```

上线后顺序改为：

```text
read defaults
read clean_annual
load yaml1
evaluate_formula_graph
fold_revenue(formula_values)
collect overlay(formula_values)
expand terminal
resolve YAML2
backtest revenue + formula
validate
```

建议新增模块 `src/yaml1_formula.py`，让 `yaml1_cleaner.py` 只负责调度：

```text
src/yaml1_formula.py
  FormulaError
  FormulaNode
  FormulaResult
  parse_formula_nodes(yaml1, horizon)
  evaluate_formula_graph(nodes, horizon)
  build_formula_report(result)
```

`yaml1_cleaner.py` 改动点：

- `clean_yaml1()` 在 `fold_revenue()` 前调用 `evaluate_formula_graph()`。
- `_fold_revenue_leaf()` 支持 `kind: formula`，从 `formula_values[formula_ref]` 取收入序列。
- `_collect_explicit_overlay()` 支持 path-level `kind: formula`，从 `formula_values[formula_ref]` 取 values。
- `_initial_report()` 增加 `formula` 区块。
- `_run_backtests()` 增加 formula node 历史回测结果。
- 顶层 skip keys 增加 `formulas`。

## 回测和审计输出

Formula report 必须写入 `.modelking/yaml1_clean_report.json`。

建议结构：

```json
{
  "formula": {
    "status": "ok",
    "nodes": {
      "stores": {
        "kind": "formula",
        "unit": "store",
        "expr": "lag(stores, 1) + openings - closures",
        "inputs": ["stores", "openings", "closures"],
        "values": {"2026": 1270, "2027": 1348},
        "dependencies": {
          "2026": ["stores[2025]", "openings[2026]", "closures[2026]"]
        },
        "backtest": {
          "status": "ok",
          "max_abs_error": 0.0
        }
      }
    },
    "targets": {
      "income.revenue.segments.retail": "retail_revenue",
      "income.cost_rates.sell_exp": "sell_exp_rate"
    }
  }
}
```

历史回测规则：

- 如果 formula node 提供了 `history`，且其 inputs 也能从 `history` / `seeds` 得到同年值，则重算历史并对比。
- 默认容差按单位决定。金额类 `million_cny` 默认 1.0；比率默认 0.001；其他单位默认 1e-6 或由 node 显式 `tolerance` 指定。
- 回测失败硬失败，除非 node 显式 `backtest: warn_only`，但第一版不建议开放 warn_only。
- 缺历史不硬失败，但 report 必须标 `backtest.status = "skipped"` 和原因。

## Over-determined 守则

Formula 上线后必须继续遵守“一个事实只能有一个来源”：

- formula revenue leaf 不能同时写 `revenue_family`。
- path-level formula 不能同时是 `knob`。
- formula 派生 `income.gpm` 时，不能同时有 leaf margin 或顶层 `income.gpm` knob。
- formula 输出到某标准 path 后，terminal fade 可以处理它，但不能另有同 path knob 覆盖。
- 同一 node 可被多个 target 引用，但单位必须一致，且每个 target 的换算因子必须显式。
- 中间变量不是标准 path，不得被悄悄塞进 forecast params。

## 错误等级

硬失败：

- 表达式解析失败。
- 使用非白名单语法或函数。
- 引用未声明、声明未使用。
- 引用不存在的 node。
- 缺少 lag seed。
- 当前年循环或跨节点循环。
- formula output path 不存在于 `defaults.yaml`。
- formula 与 knob / revenue_family / gpm / leaf margin over-determined。
- formula node 回测失败。

Warning：

- formula node 没有 history，无法回测。
- history 年份不连续，但不影响 required lag seed。
- unit 只做字符串记录，未能做强语义校验。

禁止静默行为：

- 缺值补 0。
- 缺 seed 用 base_year 猜。
- 循环时退成上一年。
- 回测失败后继续生成 forecast params。

## 测试矩阵

必须补齐以下测试后才能把 compiler/core skill 改成“允许生成 formula”。

### `tests/test_yaml1_formula.py`

- input node values 长度必须等于 horizon。
- 安全表达式支持四则运算、括号、`min/max/abs/clip/if_else`。
- 非白名单语法被拒绝，例如 `__import__`、属性访问、下标访问、字符串。
- `inputs` 与表达式引用必须双向一致。
- 普通 DAG 拓扑排序正确。
- 当前年循环硬失败。
- `lag()` 自递推合法。
- `lag()` 缺 seed 硬失败。
- 跨节点滞后链正确。
- 分段函数 `if_else` 正确。
- history 回测通过 / 失败分别覆盖。

### `tests/test_yaml1_cleaner.py`

- revenue formula leaf 折成 `model.revenue_yoy`。
- formula revenue leaf 与 `revenue_family` 混用硬失败。
- formula leaf 参与嵌套 decomposition sum。
- formula leaf 与 leaf margin 共同折出 `income.gpm`。
- path-level formula 覆盖已存在 YAML2 路径。
- path-level formula 指向不存在路径硬失败。
- path-level formula 与 knob over-determined 硬失败。
- `formulas` 顶层不会被当成普通 knob path。
- clean report 包含 formula values、dependencies、targets、backtest。
- 从 `clean_yaml1()` 跑到 `calc.build_forecast_statements()`。

### 回归用例

至少准备两个合成 fixture：

- 零售：门店数递推 + 单店收入 -> revenue leaf。
- 酒/产能类：历史滞后 seed + 分段释放 -> revenue leaf。

可选第三个：

- 标准路径 formula：固定费用 / 收入 + 变动费率 -> `income.cost_rates.sell_exp`。

## 已同步修改的文件

代码：

- `src/yaml1_formula.py`：安全表达式和 DAG 求值器。
- `src/yaml1_cleaner.py`：接入 formula result、revenue leaf、path overlay、report、backtest。
- `src/workbench.py`：当前保持 read-only YAML1 展示，formula report 已进入 `.modelking/yaml1_clean_report.json`。

测试：

- `tests/test_yaml1_formula.py`
- `tests/test_yaml1_cleaner.py`
- 必要时更新 `tests/test_forecast_pipeline.py`

文档和 skill：

- `docs/yaml1算法模板契约.md`：formula 从“禁止生成”改为“可执行，但受限”。
- `docs/数据流水线.md`：第六层 yaml1 cleaner 增加 formula 求值步骤。
- `docs/ARCHITECTURE.md`：状态记为"实验性/受限"，变更日志记录代码闭环。
- `skills/yaml1compiler_v4 (2).md`：允许 compiler 在触发条件下生成 `formulas`，并写清优先级：模板优先，formula 只接长尾。
- `skills/核心假设生成修改器_skill_v17.md`：formula 可用但需停下与分析师共探算法，不能把能用模板表达的线升级成 formula。

## compiler 触发纪律

Formula 上线后也不是默认选择。

优先级：

1. `decomposition_sum`
2. `factor_product`
3. `growth`
4. `abs`
5. leaf margin -> `income.gpm`
6. formula/DAG

只有出现以下情况，才允许进入 formula：

- 跨期递推：`stores[t] = stores[t-1] + openings[t] - closures[t]`。
- 中间变量复用：一个 driver 被多条线或多个标准路径引用。
- 分段函数：达到某阈值后算法改变。
- 滞后关系：今年收入依赖 N 年前产能、基酒、装机或项目。
- 无法无损表达为 `factor_product/growth/abs` 的公司特有算法。

即便触发 formula，compiler 也必须先在输出报告里回读算法：

```text
该线未使用模板，因为存在跨期递推 / 中间变量复用 / 分段规则。
formula 节点如下：...
请分析师确认该算法关系是否正确。
```

## 上线判定

**代码闭环已满足（≠ 生产稳定）：**

- `tests/test_yaml1_formula.py` 与新增 formula cleaner 路径测试通过。
- `docs/yaml1算法模板契约.md` 已改为允许受限 formula。
- compiler skill 已同步为受限 formula 可执行口径。
- 核心假设 skill 已同步为 formula 可用但需停下共探算法。
- `docs/数据流水线.md` 已同步。
- synthetic yaml1 已从 formula -> cleaner -> calc 跑通。
- clean report 能展示 formula 求值、依赖、targets 和回测状态。

**尚未满足"稳定"判定（明确未达成）：**

- 真实异构公司（非合成 fixture）从 compiler 生成 `formulas` → cleaner → calc → 回测过：**未做**。formula 的泛化能力（lag 链、分段、跨线 driver 复用在真实口径下是否成立）仍未被现实检验。在此之前 formula 维持"实验性·受限"，compiler 触发它时必须举旗共探、人工确认。

仍需长期遵守：模板能表达时禁止升级 formula；formula 只能通过 `formulas.nodes` + `formula_ref` 进入 cleaner，不得自创族名。
