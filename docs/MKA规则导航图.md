# MKA 规则导航图

本文是规则索引，不是新的真源。若本文与具体契约冲突，以被引用的契约和 skill runbook 为准。

它只回答一个问题：当你在 MKA skill 里迷路时，下一份应该读什么。

## 0. 主干链路

```text
raw 投研材料
-> markdown staging / candidate reference
-> 待 /ka 裁决清单
-> /ka 裁决
-> official 核心假设.md + reference 裁决回执
-> /comp 按 Semantic IR 盘点
-> yaml1 + audit 六段
-> forecast
```

三条身份铁律：

- `核心假设.md` 是 canonical 判断源头。
- `yaml1` 是派生缓存，不反向统治源文。
- Semantic IR 是 `/comp` 的翻译账本，不是第三份可编辑事实源。

## 0.1 人工筛选门

MKA 的第一门禁是人工筛选，不是 markdown 数量。`markdown存储区/`、`WEBCLAUDE/`、`Agent/Load/` 沙箱副本、临时转换件和历史 cache 默认不是证据入口；看见 markdown 不等于必须吸收。

只有这些入口默认进入本轮判断：同权重判断材料、`Agent业务讨论.md`、KA 目录顶层全部 markdown、已完成 LOAD 主产物、Alphapai reference/factpack、`/init` 事实索引和旧 official 对照。其他材料只有在用户明确说“这份材料进入本轮判断”时才读取。

KA 目录固定指 `companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\`。这里的顶层 `*.md` 都是给 `/ka` 的人工筛选材料：`核心假设参考*.md` 或声明 reference/draft/model-extracted/factpack 的文件按候选稿裁决；其他 markdown 按信息指引读取，不要求 `待 /ka 裁决清单`，也不自动晋升 official。

入口窄，收纳宽：人工筛选门只限制读取范围，不削弱接缝铁律。已进入本轮的材料里，有复盘价值但不入模的信息优先进入收纳区/stash；丢弃只用于重复、无关、越界或低可信且无复盘价值的信息，并写明理由。

## 1. 读取顺序

执行任何 MKA 路由时，按这个顺序恢复上下文：

1. 用 `docs/技能简要分类.md` 判断入口。
2. 读 `.claude/skills/{skill}/SKILL.md` 启动器。
3. 若启动器要求动态 runbook，读 `skills/*_skill_v*.md` 最新版本。
4. 碰到语法、翻译、knobs、display、BS/CF 例外，再按本文索引读具体契约。

不要把动态 runbook 复制到启动器里。启动器只做机械启动，规则看契约和最新版 runbook。

## 2. 契约索引

| 问题 | 先读 | 作用 |
|---|---|---|
| 候选稿、official 稿、标准块头、裁决回执、受控词表 | `docs/核心假设源语言语法规范.md` | 统一 markdown 外形 |
| `核心假设.md` B 系列写法、family、BS/CF 例外 | `skills/核心假设源语言_skill_v1.md` | 源语言 runbook |
| 横切纪律、接缝、防静默、操作分流 | `skills/核心纪律_skill_v1.md` | 不丢、不漂、不偷算 |
| `/ka` 全量裁决流程 | `skills/核心假设编辑器_skill_v1.md` | 时间轴、总账、骨架门、数值门 |
| `/comp` Semantic IR、A/B/C 分类、audit 六段 | `docs/核心假设翻译IR契约.md` | 翻译账本契约 |
| yaml1 具体译法、路径、B 类保全、official audit | `skills/yaml1compiler_v5.md` | compiler runbook |
| 末尾 `knobs` 块、quick/frontend 可拨边界 | `docs/knobs块契约.md` | knobs 单一真源 |
| `stash` 在前端如何摆放 | `docs/yaml1前端展示契约.md` | display 单一真源 |
| cleaner/calc 支持的算法模板 | `docs/yaml1算法模板契约.md` | yaml1 算法硬边界 |
| 中文科目与标准字段语义 | `docs/数据格式参考.md` | 科目字典 |

## 3. 命令边界

| 用户意图 | 路由 | 不要走错到 |
|---|---|---|
| 只想扫描 coverage 的财务健康度历史风险 | `/audit` | 不走 `/ka`，不改数据，不写判断，不给买卖建议 |
| 只有 raw 研报、纪要、年报材料，要先读懂业务 | `/brkd` 或 Alphapai factpack | 不直接 `/ka` 读 raw |
| 只有旧 Excel 模型，要按模型当时 vintage 装载 | `/load` | 不让 `/ka` 直接读 raw Excel |
| 候选材料已成型，要生成新的正式核心假设 | `/ka` | 不在 `/comp` 里重判 |
| 只是某个目录里出现了 markdown cache | 先由人筛选入口 | 不让 `/ka` 主动扩读 |
| 已有 official，只拨已有 knobs 的几个数 | `/adj quick` 或 `/frontend-edit` | 不回 `/ka` 重建 |
| 已有 official，有新增边际材料影响判断 | `/adj incremental` | 不用 quick 硬改结构 |
| 新年报实际年覆盖旧预测起点 | `/annual-update` | 不直接 `/comp` |
| official 源文要翻译成 yaml1 并跑 DCF | `/comp` | 不读 reference/draft |
| 重资产固定资产、在建工程、转固、折旧、capex cohort | `/da` | 不在 `/ka` 自造排程 |

一句话分界：

- `/ka` 负责全量生成或重建 official 源文。
- `/adj` 和 `/frontend-edit` 负责已有 official 的安全调整。
- `/annual-update` 负责真实历史滚动。
- `/comp` 只翻译，不研究、不重判。

## 4. B 类信息去向

B 类信息是不直接驱动 DCF、但必须保全的业务证据。按这个顺序分流：

| 情况 | 去向 |
|---|---|
| 绑定某条 revenue leaf 的历史原子 | leaf `history` |
| 不绑定单一 leaf 的副拆分、口径、风险、事实收纳 | 顶层 `stash` |
| 需要告诉工作台摆在主表、副拆分表、Reference 页或技术页 | 顶层 `display` |
| reference 裁决销账 | `decision_receipt` |
| 路径、语义、模板、来源无法确认 | `audit_flag` / `unaligned` |

禁止把 B 类塞进 A 类 note 来假装保全。B 类是否进入 DCF 不重要，是否有归宿才重要。

对已被人工筛选纳入本轮的材料，B 类默认是“收纳/展示/审计”的候选，不是“删掉”的候选。只有确认无复盘价值时，才从接缝总账里写丢弃理由。

## 5. BS/CF/DCF 例外分流

默认规则：BRKD、LOAD、KA 收窄为利润表 + 业务层盈利模型。生息财务费用/利息净额（`interest_expense_rate`、`cash_interest_rate`、由现金/债务/利率/BS 推导的 `financial expense`）、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等不主动变成预测旋钮；`other_fin_exp_abs` 是利润表外生·非利息项，默认可沿用 `/init` 生成的 `Agent/financial_expense.yaml` / defaults 平推，特殊企业或材料明示结构变化时可裁决。

例外按顺序判断：

1. 生息财务费用/利息净额若来自现金、债务、利率或 BS 推导，交引擎/defaults/专门流程；其他财务费用外生·非利息项走 `other_fin_exp_abs`，默认沿用 `Agent/financial_expense.yaml` / `income.financial_expense.other_fin_exp_abs` 平推，特殊时再由 KA 拍板覆盖。
2. `balance_sheet.dividend_payout` 是强制检测例外，可以确认沿用 defaults，也可以在需要覆盖时按 `bs_scalar_pct` 写入。
3. 同权重判断材料或分析师明确说 BS/CF 因素是核心 thesis 时，才开人工覆盖闸。
4. 人工覆盖必须落到本公司 `defaults.yaml` 已有路径，例如 `balance_sheet.revenue_pct.*`、`balance_sheet.cogs_days.*`、`balance_sheet.capex_pct`、`balance_sheet.depr_rate`。
5. 路径确认不了就保留判断，同时标 `# 路径待核` 并进入 `unaligned`。
6. 需要重资产排程、转固时滞或资产 cohort 时，转 `/da`，不要在 `/ka` 自造 cohort。
7. WACC、股本、估值参数默认不是核心假设源语言旋钮；若用户要改，应另开专项规则，不在 `/brkd`、`/load`、`/ka` 里顺手补。

## 6. 修改规则时的同步清单

改规则时按影响面同步，避免同义规则四处长出来：

| 改动类型 | 必须同步 |
|---|---|
| markdown 状态、候选晋升、official 块头、裁决回执 | `docs/核心假设源语言语法规范.md` + `/ka`、`/brkd`、`/load`、Alphapai prompt 指针 |
| family、BS/CF 例外、源语言段序 | `skills/核心假设源语言_skill_v1.md` |
| `/ka` 裁决流程 | `skills/核心假设编辑器_skill_v1.md` + `.claude/skills/ka/SKILL.md` |
| knobs 可拨边界 | `docs/knobs块契约.md` + `/adj` + `/frontend-edit` |
| `/comp` 翻译、IR、A/B/C、audit | `docs/核心假设翻译IR契约.md` + `skills/yaml1compiler_v5.md` + `.claude/skills/comp/SKILL.md` |
| B 类展示位置 | `docs/yaml1前端展示契约.md` + `skills/yaml1compiler_v5.md` |
| 命令分流边界 | 本文 + `docs/技能简要分类.md` + `Codex.md` |

如果一次改动需要复制三段以上规则，先停下，把规则收回上面的单一真源，再让其他文件只引用。
