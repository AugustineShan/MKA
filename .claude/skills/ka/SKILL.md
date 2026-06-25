---
name: ka
description: 启动精简版 KA 核心假设全量生成/重建流程。KA 专职把最高权重材料、BRKD、LOAD 和 /init 裁决成正式核心假设.md；不做旧稿 modify。先加载共享核心纪律与核心假设源语言，再加载核心假设编辑器 skill。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /ka - 核心假设全量生成器

`/ka` 现在只做一件事：把业务层材料裁决成一份新的正式 `核心假设.md`。它不是旧稿 modify 工具。

- 不直接读原始 Excel；Excel 模型由 `/load` 产出 `{原Excel文件名}_核心假设.md`。
- 不直接读研报/纪要/PDF/Word；材料由 `/brkd` 产出 `Agent业务讨论.md`。
- 不负责 schema 化；`/comp` 才把最终 `核心假设.md` 翻译成 `yaml1`。
- 不做局部改稿；小旋钮改动走 `/frontend-edit` 或 `/adj quick`，增量信息走 `/adj incremental`，年报滚动走 `/annual-update`。

## 0. 共享真源

读任何材料前，先加载：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
```

`/ka` 完整继承核心纪律 A1-A7；最终文件必须符合核心假设源语言 B。KA 本地只负责：输入门禁、冲突裁决、时间边界裁定、骨架门、数值门、防静默 passthrough、正式落盘。

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

不要再把旧 `04_核心假设生成修改器_skill_v*.md` 当 `/ka` 主工作流。旧 v19 的 Excel 阅读职责已迁给 `/load`，研报/纪要职责已迁给 `/brkd`，modify 职责已从 `/ka` 删除。

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

## 6. 读取 LOAD 产物并执行门禁

扫描：

```text
companies\{公司}\Agent\Load\*\*_核心假设.md
```

只把已完成的 LOAD 核心假设算作门禁来源。以下不算：

- `/load prepare` 刚生成的空脚手架。
- 仍包含“待模型装载器补全”的文件。
- 没有末尾 ` ```knobs` 机器自报清单的文件。
- `WEBCLAUDE` 打包副本或公司根目录同名文件。

若有多个 LOAD 产物，默认读取修改时间最新的一份，并把其他可用 LOAD 产物列为“可选参考，不自动并入”。

`/ka` 不能凭空生成。继续前必须至少具备 BRKD 产物或已完成 LOAD 产物之一。若二者都没有，停止：

```text
当前没有已完成 LOAD 产物，也没有 BRKD 产物 Agent业务讨论.md。/ka 不能凭空生成。建议先跑 /brkd 或补完 /load，再回来跑 /ka。
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
2. 显式期从哪年到哪年：解释官方 history_end 与 LOAD vintage_end 的 gap。
3. 衰减期多长或至哪年。
4. 永续增长点是多少。

铁律：

- LOAD 的 vintage 边界不等于官方 horizon，禁止静默继承。
- 显式期必须覆盖所有已知拐点年。
- 四数必须落在 overview、最终文件抬头、正文中期段、末尾 `knobs`/terminal 中。

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

### 9b. 骨架门

先确认：

- 收入分线、上挂科目、compiler family。
- 是否需要其他/残差线。
- 毛利是分线派生还是整体手拍。
- 若毛利分线派生，每条收入线是否同步挂成本/毛利旋钮。

骨架门只押参数化选型，不写正式正文。用户认可后再进数值门。

### 9c. 数值门

按核心假设源语言 B 的过表顺序推进：

```text
收入 -> 毛利/成本 -> 费用 -> below-OP 与税 -> 中期/terminal
```

每个区块在对话里押：参数化、旋钮路径、逐年值、判断三件套、来源与裁决理由。用户拍板后才写入正式底稿。

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
