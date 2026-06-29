# 核心假设翻译 IR 契约

本文定义 `/comp` 的 Semantic IR 翻译账本。IR 是 official markdown 到 yaml1 之间的审计模型，不是新的判断源，不要求第一版落地成 JSON 文件。

`核心假设.md` 是判断源头，`yaml1` 是派生缓存，IR 是 `/comp` 用来防漏译、防幻觉、防 B 类丢失的中间账。

## 1. 翻译顺序

`/comp` 必须按以下顺序工作和汇报：

```text
源文块识别 -> IR 分类 -> yaml1 落点 -> audit 六段
```

含义：

- 源文块识别：识别 official 抬头、A 类计算块、B 类历史/收纳/display、裁决回执和 `knobs`。
- IR 分类：把每个信息点分成固定 kind，标明来源层级、decision 和目标去处。
- yaml1 落点：能翻译的落到 yaml1 path、history、stash 或 display；不能翻译的进入 audit flag。
- audit 六段：固定输出 A 类覆盖、B 类保全、路径待核、语义待核、主动覆盖回读、Forecast 状态。

## 2. IR node 最小字段

每个 IR node 至少回答这些字段：

```text
kind, anchor, subject, family, unit, horizon, values, source_layer, decision, target, audit_flags
```

字段含义：

- `kind`: 信息类型。
- `anchor`: 源文锚点或小节标题。
- `subject`: 业务线、科目或判断主题。
- `family`: 源文声明的 compiler family；没有则为 `none`。
- `unit`: `pct` / `ratio` / `abs_mn` / `none`。
- `horizon`: 对应预测期；非预测信息为 `none`。
- `values`: 逐年值、历史序列或 `none`。
- `source_layer`: 同权重判断材料、BRKD、LOAD、Alphapai、init、年报查证、分析师确认等。
- `decision`: adopted / stashed / gap / rejected。
- `target`: yaml1 path、leaf history、stash、display、unaligned 或 `none`。
- `audit_flags`: 路径待核、语义待核、B 类缺失、主动覆盖未回读等。

## 3. kind 枚举

只允许以下六类：

```text
calc_knob
history_atom
stash_item
display_item
decision_receipt
audit_flag
```

对应关系：

- `calc_knob`: A 类，进入计算覆盖。
- `history_atom`: B 类，进入对应 leaf 的 history。
- `stash_item`: B 类，进入顶层 stash。
- `display_item`: B 类，进入顶层 display。
- `decision_receipt`: C 类，记录 reference 裁决回执。
- `audit_flag`: C 类，记录路径待核、语义待核或结构异常。

## 4. decision 枚举

只允许以下四类：

```text
adopted
stashed
gap
rejected
```

含义：

- `adopted`: 已采纳为 official 判断、历史原子或 knobs 回声。
- `stashed`: 有价值但不驱动本层计算，进入 stash/display。
- `gap`: 缺年份、单位、来源、路径或分析师拍板，进入待核。
- `rejected`: 重复、无关、越界或与同权重判断材料冲突，写明理由。

## 5. A/B/C 分类

```text
A 类 = calc_knob
B 类 = history_atom / stash_item / display_item
C 类 = decision_receipt / audit_flag
```

规则：

- A 类必须双射：official 源文每条可计算判断都被 yaml1 认领，无漏无多。
- B 类必须保全：history、stash、display 各归其位，不得塞进 A 类 note。
- C 类必须可审计：裁决回执和待核项清楚列出，不能静默吞掉。

## 6. audit 六段

`/comp` 回执必须固定使用六段：

```text
A 类覆盖
B 类保全
路径待核
语义待核
主动覆盖回读
Forecast 状态
```

`audit_clean = true` 仅当：

- A 类覆盖无漏无多。
- B 类保全完整。
- `unaligned` / 路径待核为空。
- 语义待核为空或已被分析师显式确认。
- 主动覆盖回读完成。

否则 yaml1 只能保存为 reference/draft 产物，不跑 official forecast。

## 7. 后续预留

后续可以实现只读 linter：

```text
py -m src.assumption_md_lint <核心假设.md>
```

本轮只预留名字，不实现 CLI，不新增运行时输出，不改变 `yaml1` schema。
