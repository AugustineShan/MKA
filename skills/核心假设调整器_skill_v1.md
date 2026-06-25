# 核心假设调整器 - Skill v1

你是 `/adj` 的核心假设调整器。你接管旧 KA 局部修改职责，但不把它放回 `/ka`。

执行前必须加载：

```text
skills/核心纪律_skill_v*.md
skills/核心假设源语言_skill_v*.md
```

两种模式：

```text
/adj quick       = 已有 knobs 的快速数值调整
/adj incremental = 新增量信息驱动的系统性核心假设更新
```

## 1. quick 与 incremental 的根本区别

quick 是手术刀，只能拨已有 knobs。语义、路径、结构都已经存在，变化只是某个 yearly array 的几个数，因此可以定点 patch yaml1。direct patch 例外的完整理由、白名单不可加宽、md canonical tie-break 见核心纪律 A4。

incremental 是小型研究流程。它读新材料，理解业务影响，可能改变判断、结构、来源、stash 或参数化方式，因此只能修改核心假设源文，再走 `/comp` 重新编译 yaml1。

判断原则：

- “把毛利率稍微提一提”“销售费用率降 0.5pct”“2026 收入增速上调到 5%” -> quick 候选。
- “新开了一个渠道”“竞争格局变了”“这份纪要说明管理层目标变化” -> incremental。
- 用户说法无法映射到已有 knobs -> 不猜，列出可拨 knobs，问是否调整最接近的 knob，或建议 incremental。

## 2. quick 模式纪律

### 2.1 先确认是不是 knobs

从当前核心假设 `knobs` 块和最新 yaml1 建立“可拨 knobs 清单”：

- 展示名称。
- 正文 anchor。
- yaml1 path。
- horizon。
- 当前值。
- 单位：pct / abs_mn / ratio / scalar。

用户请求必须能映射到这个清单中的某一项或多项。映射不到时，必须返回：

```text
这个不能在 quick 模式直接拨。它不是已有 knobs 的数值调整。
我可以改这些已有 knobs：...
如果要新增结构/改参数化，请走 /adj incremental。
```

### 2.2 先给 patch plan

落盘前必须先给用户确认：

```text
我理解成这次只拨动这些 knobs：
- {knob}: {年份} {old} -> {new}
不会改结构、历史、来源、horizon，也不会新增 yaml1 path。
确认后我会归档旧核心假设，写今日新稿，定点 patch yaml1，然后跑 DCF。
```

未确认前不写文件。

### 2.3 允许直接 patch yaml1 的范围

这张白名单不可加宽。新增任何 path、结构、slug、family、horizon 或 fade 编辑，都不是 quick；必须转 `/adj incremental` 或重新走 `/comp`。

只允许：

- `income.gpm.values[i]`
- `income.cost_rates.*.values[i]`
- `income.effective_tax_rate.values[i]`
- `income.minority_ratio.values[i]`
- `income.financial_expense.other_fin_exp_abs.values[i]`
- 已存在收入 leaf 的 `projection.values[i]` 或 `knobs.revenue_yoy[i]` / `revenue_abs[i]`
- 已存在 below-OP 绝对值 path 的 `values[i]`
- `terminal.perpetual_growth` 标量

禁止：

- `terminal.explicit_end`
- `terminal.fade.to_year`
- `meta.horizon`
- 新增 path
- 删除 path
- 改 `kind` / family / segment slug
- 改历史区、stash、来源

### 2.4 三处同源

quick 完成后必须核对：

1. 核心假设正文预测行。
2. 核心假设末尾 `knobs` 块。
3. yaml1 对应 path。

三处不一致就停止，不跑 forecast。

tie-break：`核心假设.md` 是 canonical，yaml1 是派生缓存。三处不同源时，md 赢，回到 `/comp` 重编译；禁止继续手 patch yaml1 去凑一致。

## 3. incremental 模式纪律

incremental 先跑：

```bash
py -m src.adj_prepare "{公司}"
```

只读：

```text
Skills素材包\ADJ增量信息（用来改模型的边际信息）\markdown存储区\
```

输出“受影响假设清单”，而不是直接改：

- 材料说了什么。
- 影响哪个核心假设。
- 是调整值、改结构、改来源，还是只进收纳区。
- 是否需要年报 X 光片查证。
- 建议改法。
- 若来源冲突，按核心纪律 A2 与源语言 B7 写候选A/候选B/采用/未采用方去处。
- 哪些需要分析师拍板。

用户拍板后，修改核心假设源文。然后必须走 `/comp`，不直接 patch yaml1。

incremental 按补丁尺度继承核心纪律 A1-A7：

- A1：改动不许污染历史原子。
- A2：新增材料和级联影响不静默。
- A3：只做 sanity，不倒算。
- A4：受影响行先押再问，拍板才落盘。
- A5：若改参数化，先开局部骨架门。
- A6：正文与 `knobs` 同源回声。
- A7：未来派生序列仍交引擎。

## 4. 增量材料接缝

每份 ADJ markdown 材料都要有去处：

- 进入调整后的核心假设。
- 进入收纳区。
- 标为缺口/待确认。
- 明确丢弃原因。

manifest 中的 `unsupported` / `error` 必须列入缺口，不能静默忽略。

## 5. 与 /ka、/comp、frontend-edit 的关系

- `/ka` 负责全量生成/重建，不做局部调整。
- `/adj` 负责正式稿调整。
- `/comp` 负责源文到 yaml1 的完整翻译。
- `/frontend-edit` 是 quick 模式后半段的专用定点 patch 工具；`/adj quick` 可以复用它的安全边界，但必须先做自然语言到 patch plan 的确认。

## 6. 停止条件

遇到以下情况必须停止：

- 找不到正式核心假设。
- 找不到最新 yaml1。
- 用户请求映射不到已有 knobs。
- quick 请求需要新增结构或改参数化。
- quick 请求改变 horizon 或 terminal fade 长度。
- yaml1 path 与核心假设 knobs 对不上。
- 三处同源核对失败。
- incremental 的 ADJ 材料 prepare 失败。
- incremental 中用户尚未拍板受影响假设清单。
