# YAML1 前端展示契约

本文定义 `yaml1.display`：它只说明前端如何摆放和标注 `yaml1` 里的结构化信息，不改变 DCF、不改变 cleaner/calc 算法、不替代 `knobs` 块。

## 1. 定位

`yaml1` 同时承载两类信息：

- A 类：会进入 DCF 的判断，例如 revenue decomposition、knobs、terminal。
- B 类：不进 DCF 但必须保全的证据，例如副拆分、降级观测、核对项、弃用模型原子、溯源附注。

`display` 只回答一个问题：这些信息在工作台里应该放到哪里、以什么身份展示。

没有 `display` 的旧 yaml1 仍兼容；`workbench.py` 会生成 `yaml1_display_contract.mode = inferred`。新 `/comp` 产物应尽量显式写 `display`。

> **Business Fact Matrix 边界（2026-06-29）**：`display` 只管摆放和展示身份，不管指标算法、别名或 fallback。所有业务拆分事实由 `src.yaml1_business_facts` 规范化为 `yaml1_business_facts_view`；指标语义由 `src/business_metric_registry.yaml` 管理。前端优先渲染 Business Fact Matrix，旧 `yaml1_revenue_view` 只作为兼容 fallback。

## 2. 顶层结构

```yaml
display:
  schema_version: 1
  primary_dimension: business_line
  blocks:
    - path: income.revenue
      role: primary_model
      title: "主拆分 · 业务线"
      dimension: business_line
      placement: model_table
      status: active

    - path: stash.分线毛利率
      role: primary_attachment
      attach_to: income.revenue.segments
      dimension: business_line
      metric: gross_margin
      placement: model_table
      status: reference
      duplicate_policy: prefer_derived_and_warn

    - path: stash.副拆分_按地区
      role: secondary_split
      dimension: region
      placement: secondary_table
      metrics: [revenue, gross_margin, yoy]
      status: reference

    - path: stash.LOAD分线销量吨价原子_弃用
      role: deprecated
      placement: reference_tab
      status: deprecated
```

## 3. 字段枚举

| 字段 | 允许值 | 说明 |
|---|---|---|
| `role` | `primary_model` / `primary_attachment` / `secondary_split` / `reference` / `check_only` / `deprecated` / `technical` | 展示身份 |
| `placement` | `model_table` / `secondary_table` / `reference_tab` / `technical_tab` | 展示区域 |
| `dimension` | `business_line` / `product` / `region` / `channel` / `subsidiary` / `customer` / `metric` / `text` / `other` | 业务维度 |
| `metric` | `revenue` / `yoy` / `gross_margin` / `cost` / `volume` / `price` / `rate` / `amount` / `text` / `mixed` | 单指标块的指标语义 |
| `metrics` | 上述 `metric` 数组 | 多指标块，例如副拆分收入 + 毛利率 + 同比 |
| `status` | `active` / `reference` / `deprecated` / `check_only` / `missing_disclosure` / `conflict` | 可信与使用状态 |
| `duplicate_policy` | `show` / `skip_if_equal` / `prefer_derived_and_warn` / `reference_only` | 与主表派生值重复时的处理 |
| `match_policy` | `exact_or_declared_alias` / `declared_path` / `none` | 行名匹配纪律 |

默认匹配纪律是 `exact_or_declared_alias`。禁止短词自由 contains 匹配，例如 `其他` 不自动匹配 `其他业务`。

## 4. 展示规则

- `primary_model`：主收入拆分和核心假设表。
- `primary_attachment`：挂在主业务线下的派生行，例如分线毛利率、分线成本、销量、吨价。若与 leaf history 派生值冲突，必须警示，不得静默吞掉。
- `secondary_split`：独立副拆分表，例如地区、渠道、子公司；收入为主行，毛利率/同比为弱化派生行。
- `reference` / `check_only` / `deprecated`：进入 Reference，不进主表；弃用项不隐藏，统一标成复盘材料。
- `technical`：技术附注或溯源说明，默认不干扰普通读数。

未披露的数据不补。例如某个副拆分只披露境外毛利率、没有境内毛利率，前端只提示“部分未披露”，不自行计算或填平。

## 5. Fallback

旧 yaml1 没有 `display` 时，后端只做保守推断：

- `income.revenue` → `primary_model`
- 名称为 `副拆分_*` → `secondary_split`
- 名称含 `弃用` / `废弃` / `deprecated` → `deprecated`
- 名称含 `核对` / `校验` / `check` → `check_only`
- 只有 `series_table` 且块名含 `分线` / `业务线`，并且所有行名精确匹配主业务线，才推断为 `primary_attachment`
- 其他全部进入 `reference_tab`

fallback 的目标是零丢失和少误判；宁可多留 Reference，也不要把参考材料伪装成正式主表。

## 6. 与其它契约的边界

- `docs/yaml1算法模板契约.md` 管可执行算法、revenue_family、前端可编辑矩阵；不决定 stash placement。
- `docs/knobs块契约.md` 管可编辑旋钮和 `/adj quick` 边界；display 不是 knob，quick 不得改 display。
- `/comp` 负责生成或保留 `display`；前端只消费 `yaml1_display_contract`，不直接做业务判断。
