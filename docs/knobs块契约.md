# knobs 块契约

本文件是 `核心假设.md` 末尾 `knobs` 机器自报清单的单一真源。它收敛此前散落在源语言、核心纪律、fidelity 文档、`/adj`、`/frontend-edit` 和年度更新说明里的规则。

## 1. 定位

`knobs` 块是正文预测旋钮的机器可读回声，用来让 `yaml1_fidelity_check.py` 做 `核心假设.md` 与 `yaml1` 的逐年双射校验。

它不是 YAML1：

- 不写 yaml1 path。
- 不导出 `base`、`history`、完整拆分树或 stash。
- 不做 defaults 路径映射、会计化对齐或 compiler 翻译。
- 不替代正文判断；正文仍是人话权威，`knobs` 只做同源回声。
- 不写前端展示去向。`display` 契约属于 `docs/yaml1前端展示契约.md`，只决定 yaml1 在工作台如何摆放；它不是 knob，也不能被 `/adj quick` 当成可拨旋钮。

术语区分：

- `核心假设.md` 末尾的 `knobs` 块：本文所说的机器自报清单。
- `yaml1` 里的 `kind: knob` 或 revenue leaf `knobs`：compiler 产物里的可执行输入，不是本文这个 fenced block。

## 2. 适用范围

正式或可编译核心假设源文必须带 `knobs` 块：

- `/load` 产出的 `model-extracted` 源文。
- `/brkd` 产出的 draft 或 partial 块。
- `/ka`、`/adj incremental`、`/annual-update` 产出的正式 `official` 源文。
- `/adj quick` 和 `/frontend-edit` 修改已有正式稿时，必须同步改正文预测行和 `knobs` 块。

旧 `.md` 没有块时，校验器可以走 regex 回退，但这只是兼容路径，不是新产物标准。

## 3. 语法外壳

文件末尾使用 Markdown fenced block，语言标签必须写 `knobs`，块内是普通 YAML。

规范写法要求第一行单独为三个反引号紧跟 `knobs`，不要加尾随空格。

原因：`yaml1_fidelity_check.py` 支持 ` ```knobs` 后带空格，但 `annual_update_fetcher.py` 的旧稿偏离诊断目前只匹配精确的 ` ```knobs\n`。为兼容所有消费者，不要在 `knobs` 后加尾随空格。

## 4. 顶层结构

```yaml
horizon: [2025, 2026, 2027, 2028, 2029]
terminal:
  explicit_end: 2029
  fade:
    to_year: 2034
    kind: linear
    target_growth: 0.055
    fade_paths: [model.revenue_yoy]
    hold_paths: [income.cost_rates.sell_exp]
    path_targets:
      income.gpm: 0.32
  perpetual_growth: 0.025
knobs:
  - anchor: "#整体毛利率"
    family: gpm
    unit: pct
    values: [29.2, 29.9, 30.5, 31.1, 31.6]
    status: official
    source: "正文同源"
    override: true
```

顶层字段：

| 字段 | 必须性 | 说明 |
|---|---:|---|
| `horizon` | 必须 | 显式预测期年轴。`values[0]` 对应 `horizon[0]`。 |
| `terminal` | 正式稿必须 | 末值信息的同源回声。`fade.target_growth` 是衰减交接增速，`perpetual_growth` 是 Gordon 永续增速；`fade.path_targets` 是路径级衰减期目标值；这些都不放进 `knobs` 数组。 |
| `knobs` | 必须 | 预测输入数组。正式稿不能为空；draft 可以为空但必须写原因。 |
| `reason` | draft 可选 | 当 `knobs: []` 或某 draft 条目缺值时，说明为什么没有明确数值。 |

`horizon` 必须与正文抬头和 yaml1 `meta.horizon` 的显式年轴一致。`values` 只覆盖显式期，不覆盖 fade 期。

## 5. 单条 knob 结构

```yaml
- anchor: "#低温鲜奶"
  sub: 销量
  family: factor_yoy
  unit: pct
  values: [7, 6, 6, 6, 6]
  status: official
  source: "正文同源"
  override: true
  note: "主动覆盖外部模型"
```

字段规则：

| 字段 | 必须性 | 说明 |
|---|---:|---|
| `anchor` | 必须 | 正文上挂科目锚点，通常等于小节标题核心词并带 `#`。必须用引号包住，因为 YAML 中 `#` 会开启注释。 |
| `sub` | 一节多旋钮时必须 | 区分同一 `anchor` 下多个输入，例如 `销量`、`吨价`、`收入`。单旋钮小节不写。 |
| `family` | 必须 | 语义族名，供人和未来校验器识别；当前 Gate C 主要按 `anchor/sub/unit/values` 比对。 |
| `unit` | 必须 | 只允许 `pct`、`ratio`、`abs_mn`。 |
| `values` | 正式稿必须 | 数字数组，长度必须等于 `horizon`。draft 未给数时可空，但不能进入 official `/comp`。 |
| `status` | 建议；非 official 必须 | `draft`、`model-extracted`、`official`、`reference`、`estimated·待校准`。 |
| `source` | 建议 | 说明来源，例如 `正文同源`、`LOAD原模型`、`BRKD建议`、`annual-update估算`。 |
| `override` | 可选 | `true` 表示主动覆盖外部模型或默认值。 |
| `note` / `reason` | 可选 | 只写短说明，不能替代正文三件套。 |

## 6. 单位和值

`values` 写数字，不写 `%` 字符，不写字符串，不用全角负号。

| `unit` | 写法 | yaml1 比对口径 |
|---|---|---|
| `pct` | 百分数显示值，例如 `15.4` 表示 15.4% | 校验器除以 100 后与 yaml1 小数比。 |
| `ratio` | 小数或倍率原值，例如 `0.025` | 原样比。 |
| `abs_mn` | 百万元金额，例如 `-70` | 原样比，保留正负号。 |

作者侧必须追求与正文一字不差。实现侧 `yaml1_fidelity_check.py` 对数值比较有极小容差，容差只是防浮点噪声，不是允许四舍五入漂移。

平推、全程统一、维持不变也必须展开逐年：

```yaml
- {anchor: "#销售费用", family: cost_rate, unit: pct, values: [15.4, 15.4, 15.4, 15.4, 15.4]}
```

禁止写：

```yaml
values: "全程 15.4%"
```

## 7. family 推荐表

`family` 不是 yaml1 path。它描述正文旋钮的语义族。

> ⚠️ **同名陷阱：另一组 `family` 枚举。** 这里有两个易混的同名枚举，加上本节共三层，见到 `family` 先确认它在哪一层：
>
> 1. 本节 knobs `family`： knobs 块内 `family:` 语义标签，`growth` = "这格旋钮属于收入增速类输入"。
> 2. yaml1 `revenue_family`： revenue leaf 上的**收入算法模板**（`factor_product / driver_rate / growth / abs / vol_price / formula …`），由 `docs/yaml1算法模板契约.md` 定义；`revenue_family: growth` = "这条线收入按增速递推折叠"。与本节共用 `growth`/`abs` 之名但含义不同。
> 3. 源语言 §B4 块头 `compiler: <family>`： `.md` 块头声明（`factor_product / driver_rate / growth / abs / leaf margin / bs_scalar_pct …`），与本节共用 `growth`/`abs`/`bs_*` 之名但管的是块头声明，不是 knobs 回声。
>
> 三处 `family` 各管各的层，不要互相套用。

| family | 常见 `sub` | unit | 对应输入 |
|---|---|---|---|
| `factor_yoy` | `销量`、`吨价`、`门店数`、`ARPU` 等 | `pct` | `factor_product` / `vol_price` leaf 的因子增速。 |
| `growth` | `收入` | `pct` | revenue leaf `knobs.revenue_yoy`。 |
| `abs` | `收入` 或具体科目 | `abs_mn` | revenue leaf `knobs.revenue_abs` 或明确绝对值输入。 |
| `gpm` | 省略 | `pct` | 顶层整体毛利率手拍。 |
| `leaf_margin` | `毛利率` | `pct` | 分线毛利率输入。当前 Gate C 尚未直接收集 leaf margin；official block 暂不写独立 `leaf_margin` 条目，除非先补校验器支持。 |
| `cost_rate` | 省略 | `pct` | 销售、管理、研发、税金及附加等费用率。 |
| `tax_rate` | 省略 | `pct` | 有效税率。 |
| `minor_rate` | 省略 | `pct` | 少数股东损益率。 |
| `op_adj_abs` | 省略 | `abs_mn` | 其他收益、投资收益、公允价值变动、资产处置等营业利润调节项。 |
| `cost_abs` | 省略 | `abs_mn` | 资产减值损失、信用减值损失等成本侧绝对值项。 |
| `below_line_abs` | 省略 | `abs_mn` | 营业外收入、营业外支出。 |
| `other_fin_exp_abs` | 省略 | `abs_mn` | 其他财务费用外生项。 |
| `bs_revenue_pct` | BS 科目字段名 | `pct` | 人工覆盖 `balance_sheet.revenue_pct.*`，如应收账款/收入、合同负债/收入。只在同权重判断材料或分析师明示为核心 thesis 时使用。 |
| `bs_cogs_days` | BS 科目字段名 | `ratio` | 人工覆盖 `balance_sheet.cogs_days.*`，如存货周转天数、应付账款天数。`values` 写天数原值。 |
| `bs_scalar_pct` | defaults 标量字段名 | `pct` | 人工覆盖 `balance_sheet.capex_pct`、`balance_sheet.depr_rate`、`balance_sheet.dividend_payout` 等轻资产/稳态标量路径；其中 `dividend_payout` 是 `/ka` 强制检测项，但只有需要覆盖 defaults 时才进入 `knobs`；重资产排程优先 `/da`。 |
| `formula_input` | 变量名 | `pct` / `ratio` / `abs_mn` | 受限 formula 的人工输入变量。当前 Gate C 只会校验能落成 top-level `kind: knob` 或 revenue leaf 输入的值；其他 formula input 暂不写独立条目。 |

如果现有表装不下，优先在正文里举旗说明，不要临时自创模糊族名。确需新增 family 时，先更新本文和相关校验/编辑映射。

## 8. 哪些东西进 knobs

当前 official block 必须进入：

- 所有正文中被分析师拍板、会被 `/comp` 翻译成 yaml1 预测输入的显式期旋钮。
- top-level `kind: knob` 对应的标准路径输入。
- revenue leaf 的因子预测输入，如销量 yoy、价格 yoy。
- revenue leaf 的 `revenue_yoy` 或 `revenue_abs`。
- 人工 BS/CF 覆盖闸中已拍板、且能落到 defaults.yaml 现有路径的 `balance_sheet.revenue_pct.*`、`balance_sheet.cogs_days.*`、`balance_sheet.capex_pct`、`balance_sheet.depr_rate` 等输入。
- `/ka` 分红率强制检测后决定覆盖 defaults 的 `balance_sheet.dividend_payout`，使用 `family: bs_scalar_pct`、`sub: dividend_payout`、`unit: pct`；若只是明确沿用 defaults，只在正文说明，不写入 `knobs`。

禁止进入：

- 历史值。
- 派生预测值，例如收入、毛利额、毛利率占比、费用金额、净利率等由引擎从旋钮算出的未来序列。若正文展示这些数，必须标注 `派生·引擎算·非翻译输入`。
- yaml1 path、defaults path、segment slug、base、history、stash。
- terminal fade 期展开序列。
- 未被明示为核心 thesis 的 BS/CF/DCF 驱动因素；这些维持 defaults/引擎/专门流程。`balance_sheet.dividend_payout` 是强制检测例外：可以明确沿用 defaults，也可以在需要覆盖时按 `bs_scalar_pct` 写入。

特例：

- `terminal.perpetual_growth` 放在顶层 `terminal.perpetual_growth`，不放入 `knobs` 数组。
- `terminal.explicit_end`、`terminal.fade.to_year`、`terminal.fade.target_growth`、`terminal.fade.path_targets`、`fade_paths`、`hold_paths` 是 terminal 结构，不是可 quick 拨动的 knobs。
- 分线毛利率 `leaf_margin` 与非标准 formula input 是已知覆盖缺口；当前不要写成 official block 独立条目，否则 Gate C 会把它识别为 block 多写。需要纳入双射时，先扩展 `yaml1_fidelity_check.py` 的收集逻辑和本文 family 表。

## 9. anchor 与 sub 映射

`anchor` 是连接正文、`knobs` 块和 yaml1 `src` 的公共锚点。校验器会做归一：

- 去掉开头 `#`。
- 去掉括号说明。
- 用核心词和 yaml1 `src` 对齐。

建议：

- `anchor` 尽量等于正文小节标题核心词，例如正文 `### 销售费用` 对应 `anchor: "#销售费用"`。
- 一节多旋钮时，`sub` 必须与正文预测行标签稳定一致。
- revenue `growth` / `abs` 的 segment 级输入可以用 `sub: 收入`；当前校验器也兼容 `sub: revenue_yoy` 和 `sub: revenue_abs`。

示例：

```yaml
- {anchor: "#低温鲜奶", sub: 销量, family: factor_yoy, unit: pct, values: [7, 6, 6, 6, 6]}
- {anchor: "#低温鲜奶", sub: 吨价, family: factor_yoy, unit: pct, values: [0.3, 0.3, 0.3, 0.3, 0.3]}
- {anchor: "#边缘业务", sub: 收入, family: growth, unit: pct, values: [0, -10, -10, -10, -10]}
```

## 10. 状态规则

正式稿：

- 文件抬头 `状态: official`。
- 每个已拍板预测输入在 `knobs` 中有同源回声。
- 条目可以省略 `status`，但建议写 `status: official` 以便审计。
- 不得有缺 `values` 的 draft 条目。

`/load`：

- 文件抬头 `状态: model-extracted`。
- 条目写 `status: model-extracted` 或在 source 中说明来自 LOAD 原模型。
- 只能作为 `/ka` 候选或沙箱编译输入，不能被静默当成 official。

`/brkd`：

- 文件抬头或正文声明 `draft`。
- 末尾可以是 partial knobs，只含有材料支持的建议旋钮。
- 没有明确建议值时，可以写：

```yaml
horizon: [待 /ka 锁时间轴]
reason: "材料只给方向，未给逐年数值"
knobs: []
```

`reference`：

- 有悬项或不可直接 `/comp` 的稿件，条目必须标 `status: reference` 或在 `reason` 中说明卡点。

`estimated·待校准`：

- 年度更新声明式估算的实际值或临时估算，不得冒充真实披露。

## 11. 校验器实际行为

`yaml1_fidelity_check.py` 的 block-diff 目前做这些事：

- 抓取 ` ```knobs` fenced block，并用 `yaml.safe_load` 解析。
- 读取顶层 `knobs` 数组。
- 用 `(anchor, sub)` 建索引。
- 对 yaml1 中所有 top-level `kind: knob` 逐条找同 anchor 且无 sub 的条目。
- 对 revenue leaf 的 factor projection、legacy `volume_yoy` / `price_yoy`、`revenue_yoy` / `revenue_abs` 逐条找同 anchor 且匹配 sub 的条目。
- `unit: pct` 时把 block 值除以 100 后与 yaml1 比。
- 数组长度不一致、值不一致、yaml1 有而 block 无、block 有而 yaml1 无，均 FAIL。

当前实现边界：

- `family` 主要是语义标签，当前 Gate C 未强制比对 family。
- `terminal` 当前不参与 Gate C 双射；它由源语言、compiler 和 frontend-edit 纪律约束。
- `leaf_margin` 当前 Gate C 尚未直接收集比对；official block 暂不写独立 leaf margin 条目，避免被判为 block 多写。
- 非标准 formula input 当前不进 block-diff，除非它最终落成 top-level `kind: knob` 或 revenue leaf 输入。

## 12. 编辑与年度更新

`/adj quick` 和 `/frontend-edit`：

- 只能改已有 knob 的 `values[i]` 或 `terminal.perpetual_growth` 标量。
- 不得新增或删除条目。
- 不得改 `horizon`、`terminal.explicit_end`、`terminal.fade.to_year`、`family`、`anchor`、`sub`、结构、历史、来源、stash、display。
- 写入前必须核对 old value：正文、`knobs`、yaml1 三处同源。
- 写入后必须跑 fidelity。失败时 md 赢，回 `/comp` 重编译，不手 patch yaml1 去凑一致。

`/annual-update`：

- 旧稿 `horizon` 前移 N 年，`values` 同步前移。
- 新真实年替换历史后，显式期缺口年份由第 4 步人机交互重拨。
- `annual_update_fetcher.py --forecast-md` 只读取旧稿块里能映射到标准线的条目，用于偏离诊断；收入 leaf 量价因子不在该诊断范围内。

## 13. 完整示例

````markdown
```knobs
horizon: [2025, 2026, 2027, 2028, 2029]
terminal:
  explicit_end: 2029
  fade:
    to_year: 2034
    kind: linear
    target_growth: 0.055
    fade_paths: [model.revenue_yoy]
    hold_paths: [income.cost_rates.sell_exp]
    path_targets:
      income.gpm: 0.32
  perpetual_growth: 0.025
knobs:
  - {anchor: "#低温鲜奶", sub: 销量, family: factor_yoy, unit: pct, values: [7, 6, 6, 6, 6], status: official}
  - {anchor: "#低温鲜奶", sub: 吨价, family: factor_yoy, unit: pct, values: [0.3, 0.3, 0.3, 0.3, 0.3], status: official}
  - {anchor: "#边缘业务", sub: 收入, family: growth, unit: pct, values: [0, -10, -10, -10, -10], status: official}
  - {anchor: "#整体毛利率", family: gpm, unit: pct, values: [29.2, 29.9, 30.5, 31.1, 31.6], status: official, override: true}
  - {anchor: "#销售费用", family: cost_rate, unit: pct, values: [15.4, 15.4, 15.4, 15.4, 15.4], status: official}
  - {anchor: "#有效税率", family: tax_rate, unit: pct, values: [14.6, 14.6, 14.6, 14.6, 14.6], status: official}
  - {anchor: "#资产处置收益", family: op_adj_abs, unit: abs_mn, values: [-70, -30, -30, -30, -30], status: official}
  - {anchor: "#营业外支出", family: below_line_abs, unit: abs_mn, values: [47.39, 47.39, 47.39, 47.39, 47.39], status: official}
```
````

## 14. 常见错误

| 错误 | 后果 | 正确写法 |
|---|---|---|
| `unit: pct` 但写 `[0.154]` | 校验器除以 100 后变成 `0.00154`，与 yaml1 不同源 | 写 `[15.4]`。 |
| `anchor: #销售费用` 不加引号 | YAML 把 `#销售费用` 当注释，anchor 为空 | 写 `anchor: "#销售费用"`。 |
| `values: [15.4%]` | YAML 解析为字符串或失败 | 写 `unit: pct` 和 `values: [15.4]`。 |
| `values: "平推"` | 无法逐年比对 | 展开成满数组。 |
| factor_product 又写派生收入 | block 多出 yaml1 没有的输入，或语义重复 | 只写销量、吨价等人工输入。 |
| 在 block 里写 yaml1 path | 破坏分层 | 用 `anchor/sub`，让 compiler 落路径。 |
| 改正文忘改 block | fidelity 失败或漂移 | 正文、`knobs`、yaml1 三处同步。 |
