---
name: ka
description: 启动精简版 KA 核心假设全量生成/重建流程。KA 专职把最高权重材料、BRKD、LOAD 和 /init 裁决成正式核心假设.md；不做旧稿 modify。先加载共享核心纪律与核心假设源语言，再加载核心假设编辑器 skill。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /ka - 核心假设全量生成器

`/ka` 现在只做一件事：把业务层材料裁决成一份新的正式 `核心假设.md`。它不是旧稿 modify 工具。

范围边界：`/ka` 默认收窄为**利润表 + 业务层盈利模型裁决器**。它主动裁决收入、成本/毛利、费用率、below-OP、税率、少数股东等利润表相关判断；不主动裁决 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等 BS/CF/DCF 驱动因素。

人工注入例外：如果最高权重材料或分析师明确说周转率提升、库存去化、应收压降、合同负债改善、资本开支变化等 BS/CF 因素是核心 thesis，`/ka` 可以单独开启“BS/营运资本/现金流人工覆盖”闸；否则这些项目维持 defaults.yaml/引擎/专门流程。

- 不直接读原始 Excel；Excel 模型由 `/load` 产出 `{原Excel文件名}_核心假设_load{YYYYMMDD}.md`。
- 不直接读研报/纪要/PDF/Word；材料由 `/brkd` 产出 `Agent业务讨论.md`。
- 不负责 schema 化；`/comp` 才把最终 `核心假设.md` 翻译成 `yaml1`。
- 不做局部改稿；小旋钮改动走 `/frontend-edit` 或 `/adj quick`，增量信息走 `/adj incremental`，年报滚动走 `/annual-update`。

## 0. 共享真源

读任何材料前，先加载：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
D:\MKA\docs\knobs块契约.md
```

`/ka` 完整继承核心纪律 A1-A7；最终文件必须符合核心假设源语言 B，末尾 official `knobs` 块语法以 `docs/knobs块契约.md` 为准。KA 本地只负责：输入门禁、冲突裁决、时间边界裁定、骨架门、数值门、防静默 passthrough、正式落盘。

交互风格继承核心纪律 A4：像投资委员会开会，不像机器审表。每个确认点先给你的理解、建议预测和裁决理由，再等分析师拍板；聊天里用会议 memo，正式文件里写完整 `/comp` 源语言和 `knobs`。

## 1. 解析公司目录

从 `$ARGUMENTS` 定位 `D:\MKA\companies\{公司}`：

1. 精确匹配 `companies\{参数}`。
2. 代码匹配 `companies\*_{代码}`。
3. 公司名匹配 `companies\{公司名}_*`。
4. 命中多个时列候选并询问用户。
5. 未命中时报错停止。

## 2. 已有正式稿门禁

Glob 检查 `companies\{公司}\核心假设*.md`，只认公司根目录。

若根目录已有正式 `核心假设*.md` 且用户没有明确说“重建/重新生成正式稿”，停止并返回：

```text
公司根目录已有正式核心假设稿。/ka 现在不做 modify。
小旋钮改动请走 /frontend-edit 或 /adj quick。
新增边际信息请走 /adj incremental。
年报或真实数据滚动请走 /annual-update。
若要用新的最高权重材料、BRKD 或 LOAD 全量替换旧稿，请明确说 /ka 重建。
```

若用户明确重建，可读取旧稿，但旧稿只用于收口对照和防静默丢信息；不是逐行 base，不走 affected-line modify。

## 3. 加载核心假设编辑器 skill

扫描并读取最新版本：

```text
D:\MKA\skills\核心假设编辑器_skill_v*.md
```

共享 A/B 是上位真源；编辑器 skill 只补 KA 本地裁决流程。

不要再把旧 v19(已归档至 `deprecatedlogs/04_核心假设生成修改器_skill_v19.md`)当 `/ka` 主工作流。旧 v19 的 Excel 阅读职责已迁给 `/load`，研报/纪要职责已迁给 `/brkd`，modify 职责已从 `/ka` 删除。横切纪律以 `核心纪律_skill`(A1-A7) + `核心假设源语言_skill`(B) 为准。

## 4. 读取最高权重材料

先运行：

```bash
py -m src.ka_prepare "{公司}"
```

该脚本会把以下材料幂等 markdown 化：

- `companies\{公司}\公司判断和最新观点.md`
- `companies\{公司}\Skills素材包\最高权重材料-放Agent最应对齐的材料\` 下的顶层材料

输出到：

```text
companies\{公司}\Skills素材包\最高权重材料-放Agent最应对齐的材料\markdown存储区\
```

`公司判断和最新观点.md` 是默认最高权重材料。后续 AI 只读 markdown 存储区和 manifest，不直接读 raw PDF/Word/Excel。manifest 中的 `unsupported/error` 必须进入缺口区。

## 5. 读取 BRKD 产物

读取：

```text
companies\{公司}\Agent业务讨论.md
```

这是 `/brkd` 的业务层草稿。它可提供当前业务结构、利润表讨论、待 `/ka` 拍板问题清单，但其中所有预测建议仍需 KA 重新裁决。
若根目录另有 BRKD 核心假设式参考稿，只读取命名为 `*_核心假设_brkd*.md` 的文件；这些文件必须声明 `状态: draft` 或 `状态: reference`，只能作为 BRKD 候选，不得被当作 official。
若 BRKD 材料中出现 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等 BS/CF/DCF 驱动因素，默认只认作“非本层范围”的收纳或丢弃原因，不纳入 `/ka` 数值门；只有最高权重材料或分析师明确把它提升为核心 thesis 时，才进入人工覆盖闸。

## 6. 读取 LOAD 产物并执行门禁

扫描公司根目录的 LOAD 命名产物：

```text
companies\{公司}\*_核心假设_load*.md
```

只把已完成的 LOAD 核心假设算作门禁来源。以下不算：

- `/load prepare` 刚生成的空脚手架。
- 仍包含“待模型装载器补全”的文件。
- 没有末尾 ` ```knobs` 机器自报清单的文件。
- 没有抬头声明 `模式: load` / `状态: model-extracted` / `load-vintage` 的文件。
- `WEBCLAUDE` 打包副本、`Agent\Load\` 沙箱副本、正式 `状态: official` 核心假设。

若有多个根目录 LOAD 产物，默认读取修改时间最新的一份，并把其他可用 LOAD 产物列为“可选参考，不自动并入”。

## 6b. 读取 reference 候选并执行门禁

除 BRKD 和 LOAD 外，`/ka` 可以读取根目录 reference 候选，包括 Alphapai 网页端输出：

```text
companies\{公司}\*核心假设参考*.md
companies\{公司}\*_核心假设_brkd*.md
companies\{公司}\*_核心假设_alphapai*.md
```

识别条件：

- 文件抬头声明 `状态: reference` 或 `模式: alphapai-load`，或文件名是 `核心假设参考.md`。
- 不在 `Agent\`、`WEBCLAUDE\`、`Agent\Load\` 等子目录里，只读公司根目录非递归文件。
- 只能作为候选理解和待裁决清单来源；预测值、`knobs` 和时间轴都必须重新裁决后才能进入 official。
- Alphapai reference 中的 BS/CF/DCF 线索只进收纳区或 `/da` 分流判断，不自动打开 `/ka` 人工覆盖闸。

`/ka` 不能凭空生成。继续前必须至少具备 BRKD 产物、已完成 LOAD 产物或 root reference 候选之一。若三者都没有，停止：

```text
当前没有已完成 LOAD 产物、没有 BRKD 产物 Agent业务讨论.md，也没有可读 root reference 候选（如 Alphapai 核心假设参考.md）。/ka 不能凭空生成。建议先跑 /brkd、补完 /load，或放入 Alphapai-load reference 后再回来跑 /ka。
```

最高权重材料、旧正式稿、`公司判断和最新观点.md` 不计入本门禁；它们是裁决材料或旧稿对照，不是业务骨架来源。

## 7. 读取 /init 标准财务数据

优先读取：

- `Agent/core_metrics_overview.md`
- `Agent/core_metrics_overview.json`
- `Agent/core_metrics_overview.csv`

若没有速览但 `Agent/data.db` 存在，可读 `clean_annual` 作为历史事实来源。若不可用，停止并提示先跑 `/init`。

`/init` 是标准化财务事实和 headline 校验层，不是业务事实地基。

## 8. 三方时间边界对齐

进入任何收入、毛利、费用或 below-OP 数值裁决前，必须独立锁定时间轴四数，并向分析师确认：

1. 历史数据到哪一年：以 `/init` 标准财务数据作为官方 history_end；LOAD 的 vintage history_end 只是旧模型边界。
2. 显式期从哪年到哪年：解释官方 history_end 与 LOAD vintage_end 的 gap；若 LOAD 落后于 `/init`，这是正常 vintage gap，不是报错、不是脏数据、不是 time-boundary 缺口。
3. 衰减期多长或至哪年，以及 `/ka` 自动建议的衰减交接增速 `fade.target_growth`。
4. 永续增长点是多少；它是 Gordon 终值长期锚，不等于衰减交接增速。

铁律：

- LOAD 的 vintage 边界不等于官方 horizon，禁止静默继承。
- LOAD 多数时候就是历史模型沙箱。若 `model_boundary.history_end_year` 早于 `/init` 最新 clean 年度，只需冷静说明：正式 KA 的历史末年跟 `/init`，LOAD 中已经变成真实历史的预测年保留为旧预测 vs 新实际的复盘证据，不把正常差异写成异常门禁。
- 只有 `model_boundary` 自身冲突、LOAD 读取了 forbidden post-boundary 材料、LOAD 产物未完成，或 `/ka` 想把 vintage horizon 静默继承为正式 horizon 时，才举旗或硬停。
- 显式期必须覆盖所有已知拐点年。
- 四数必须至少落在三处：本次交互第一次 overview 的第一项、最终文件抬头、进入“中期/terminal”段之前的二次核对；末尾 `knobs`/terminal 也必须同源回声。
- 不默认、不平推、不等分析师自己说；先问、先确认、先写进底稿，再进下一道工序。
- 不让分析师手填衰减交接增速。`/ka` 必须自动给 fade profile、`target_growth`、`to_year` 和理由，用户只拍板“保守/标准/乐观/重算”。

对用户的输出不要像校验清单，必须先讲判断：

```text
我先把三方时间边界摆一下：
- /init 官方历史到 ...
- LOAD 是旧模型 vintage，边界是 ...；若它早于 /init，这是正常 vintage gap，不是数据异常
- BRKD/最高权重材料提示 ... 年有拐点

我的建议：正式稿用 /init 的 ... 作为 history_end；LOAD 的 ... 之后预测只作为旧预测 vs 新实际复盘和候选判断，不直接继承为正式 horizon。显式期 ...，衰减期至 ...，fade target ...，永续 ...
理由是 ...

这组时间轴你认吗？认了我再进骨架门。
```

### 8a. 自动 fade profile

进入中期/terminal 前，`/ka` 自动给一版 fade profile，不把交接增速丢给用户手填：

1. 取显式期最后 2-3 年 `model.revenue_yoy` 或收入主轴增速均值为 `g_exp`；利润 CAGR 只做 sanity check，不做 fade 主轴。
2. 依据材料判断 profile：
   - `mature`：成熟稳态、空间有限、周期正常化，`target_growth = perpetual_growth + 0~2pp`。
   - `stable_brand`：品牌消费、现金牛、仍有结构升级，`target_growth = perpetual_growth + 2~4pp`。
   - `long_runway`：渗透率/份额/结构升级仍明显，`target_growth = perpetual_growth + 4~6pp`。
   - `cycle_repair`：高增来自修复或周期，`target_growth = perpetual_growth + 0~2pp`，fade 更快。
3. 按年降速估算 `to_year`：`mature/cycle_repair` 每年约 1.5-2.0pp，`stable_brand` 约 1.0-1.5pp，`long_runway` 约 0.7-1.0pp；fade 年限最少 5 年、最多 10 年。
4. sanity check 必须汇报 `g1` 显式期利润 CAGR、`g2` fade 期利润 CAGR、`gT` 永续增长。若 `g1 > 10%` 但 `g2 < 5%`，或 `g1 -> g2` 断崖超过 8-10pp，先自动延长 fade，再在 profile 合理区间内提高 `target_growth`；仍不顺则举旗。
5. 不拆第一/第二过渡期；只保留一个 linear fade。`target_growth` 是衰减期末年交接增速，`perpetual_growth` 仍是 Gordon 终值长期锚。

正式落盘时 terminal 必须写：

```yaml
terminal:
  explicit_end: <显式期末年>
  fade:
    kind: linear
    to_year: <自动建议并确认的 fade_end>
    target_growth: <自动建议并确认的交接增速>
    target_basis: <auto_mature|auto_stable_brand|auto_long_runway|auto_cycle_repair>
    fade_paths: [model.revenue_yoy]
    hold_paths: [...]
  perpetual_growth: <永续点>
```

## 9. 进入全量裁决

读取权重顺序：

1. 最高权重材料：当前 thesis、口径和关注点。
2. BRKD 产物：当前业务理解和草稿块。
3. LOAD 产物：旧模型结构、历史拆分、公式族和 load-vintage 旋钮。
4. /init：历史 headline 和标准利润表事实。
5. 年报：只作按需查证工具，不通读升格。

裁决分三闸：

### 9a. 接缝总账

所有输入信息都有去处：入模、收纳、缺口、丢弃原因。若重建旧正式稿，旧稿中有价值的历史、stash、风险提示也要逐项认领。
`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等 BS/CF/DCF 驱动因素默认不得进入入模清单或待拍板清单；材料里出现时，按“非本层范围”进入收纳区或写明丢弃原因，交引擎/defaults/专门流程。若触发人工注入例外，必须单列“人工 BS/CF 覆盖”入模清单，并写明触发来源。

### 9b. 骨架门

先确认：

- 收入分线、上挂科目、compiler family。
- 是否需要其他/残差线。
- 毛利是分线派生还是整体手拍。
- 若毛利分线派生，每条收入线是否同步挂成本/毛利旋钮。

骨架门只押参数化选型，不写正式正文。用户认可后再进数值门。

骨架门聊天输出用“我建议怎么搭模型”的 memo，不要直接贴源语言块：

```text
我建议这版核心假设先搭成：
| 区块 | 采用方案 | 为什么 |
|---|---|---|
| 收入 | ... | ... |
| 毛利 | ... | ... |

这里最需要你拍的是...
这个骨架可以吗？确认后我进收入数值。
```

### 9c. 数值门

按核心假设源语言 B 的过表顺序推进：

```text
收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 可选 BS/营运资本/现金流人工覆盖 -> 中期/terminal
```

每个区块在对话里押：参数化、旋钮路径、逐年值、判断三件套、来源与裁决理由。用户拍板后才写入正式底稿。

人工 BS/CF 覆盖闸只在触发例外时打开，且必须先确认三件事：它是不是核心 thesis、能否落到现有 defaults/yaml1 路径、是否需要 `/da` 而不是 `/ka`。模板装不下时举旗，不硬塞。

数值门每段默认只给会议 memo：核心判断、逐年值表、来源冲突和待拍板点。不要把完整 markdown 正文、完整历史原子或 official `knobs` 整块贴进聊天；用户确认后再写文件。

## 10. 防静默 passthrough

BRKD、LOAD、KA 的输入输出同构，不能因为某个块已经长得像正式 `核心假设.md` 就整块照抄。

冲突或同构候选必须写：

```text
候选A:
候选B:
采用:
为什么:
未采用方去处:
```

尤其是 LOAD 的 `knobs` 块和 BRKD 的 draft `knobs` 块：它们只能作为候选，不是自动正式旋钮。

## 11. 收口核对与落盘

写盘前做一次“过完了没”：

- 接缝总账点完，没有材料信息被静默丢失。
- 骨架行点全：收入、成本/毛利、费用、below-OP、税率、少数股东、terminal 都有去处。
- 范围边界点全：`financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 没有被默认写进正式 knobs 或 `/ka` 待拍板项；若有人工 BS/CF 覆盖，必须有核心 thesis 触发来源、现有 defaults/yaml1 路径、唯一旋钮说明和 `/da` 分流判断。
- 历史保全：/init headline 没被旧模型或研报覆盖。
- 时间轴四数一致。
- 显式期覆盖已知拐点。
- 每个已拍板预测项在 `knobs` 中有同源回声。
- 有价值但未入模的信息进入收纳区。
- manifest 缺口、BRKD/LOAD 冲突、年报未查证项都有说明。

聊透了 -> 写正式稿：

```text
companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md
```

有悬项 -> 写参考稿：

```text
companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设参考.md
```

参考稿必须醒目标注“未拍板，不可直接 /comp”。

若本轮是重建且根目录已有旧正式稿，落盘前先归档旧稿：

```bash
py scripts/ka_archive.py "<旧正式稿完整路径>"
```

再写新底稿。禁止原地覆盖。
