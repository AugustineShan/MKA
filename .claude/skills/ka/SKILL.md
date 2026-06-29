---
name: ka
description: 启动精简版 KA 核心假设全量生成/重建流程。KA 专职把同权重判断材料、BRKD、LOAD、KA 目录顶层 markdown 和 /init 裁决成正式核心假设.md；不做旧稿 modify。先加载共享核心纪律与核心假设源语言，再加载核心假设编辑器 skill。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /ka - 核心假设全量生成器

`/ka` 只做一件事：把业务层材料裁决成一份新的正式 `核心假设.md`。它不是旧稿 modify 工具。

`/brkd`、`/load`、Alphapai 与网页端 reference 都只生产候选理解；`/ka` 是唯一裁决器，负责把候选 markdown 与同权重判断材料拍板成 official 源文。

本启动器只负责**启动机械**：解析公司目录 → 已有正式稿门禁 → 加载真源与编辑器 runbook → 拉起候选材料。**裁决流程（时间轴四数、接缝总账、骨架门、数值门、防静默、收口）在编辑器 runbook**（§2-§10），不在本文件重复——读到那里照做。

范围边界（利润表 + 业务层盈利模型；不处理 BS/CF/DCF 驱动）、分红率强制检测、人工 BS/CF 覆盖闸触发条件、不直接读原始 Excel/研报/PDF 的分流去向——全见编辑器 runbook §0 与源语言 B0.1，本启动器不复述。

**主导方向**：拿 /brkd、/load、Alphapai 产物和分析师裁决预测，同时忠实收集与预测有关的历史防丢数；详见编辑器 runbook 核心指导。

## 0. 共享真源

读任何材料前，先加载：

```text
D:\MKA\docs\MKA规则导航图.md               # 迷路时的契约索引；不替代下列真源
D:\MKA\skills\核心纪律_skill_v*.md          # A1-A7 横切纪律
D:\MKA\skills\核心假设源语言_skill_v*.md     # B 系列块语法 + §B4 family 词表与硬规则
D:\MKA\docs\knobs块契约.md                   # 末尾 official knobs 块语法真源
D:\MKA\skills\核心假设编辑器_skill_v*.md     # KA 裁决流程 runbook（§2-§10）；取 vN 整数最大版
```

`docs/MKA规则导航图.md` 只用于分流和找真源，不作为裁决证据。`/ka` 完整继承核心纪律 A1-A7；最终文件符合核心假设源语言 B，末尾 official `knobs` 块语法以 `docs/knobs块契约.md` 为准。标准块头、候选稿清单和 recommended `reference 裁决回执` 见 `docs/核心假设源语言语法规范.md`。每条业务线块头 `compiler: <family>` 必须落在源语言 §B4 可执行集合内，family 硬规则以 §B4 为准。交互风格继承核心纪律 A4，本启动器不复述。cleaner 折叠机制、unit_factor 换算等 yaml1 侧细节见 `docs/yaml1算法模板契约.md`（`/comp` 读，`/ka` 不需加载）。

## 1. 解析公司目录

从 `$ARGUMENTS` 定位 `D:\MKA\companies\{公司}`：

1. 精确匹配 `companies\{参数}`。
2. 代码匹配 `companies\*_{代码}`。
3. 公司名匹配 `companies\{公司名}_*`。
4. 命中多个时列候选并询问用户。
5. 未命中时报错停止。

## 2. 已有正式稿门禁

Glob 检查 `companies\{公司}\核心假设*.md`，只认公司根目录。

若根目录已有正式 `核心假设*.md` 且用户没有明确说"重建/重新生成正式稿"，停止并返回：

```text
公司根目录已有正式核心假设稿。/ka 现在不做 modify。
小旋钮改动请走 /frontend-edit 或 /adj quick。
新增边际信息请走 /adj incremental。
年报或真实数据滚动请走 /annual-update。
若要用新的同权重判断材料、BRKD、LOAD 或 KA 目录 markdown 全量替换旧稿，请明确说 /ka 重建。
```

若用户明确重建，可读取旧稿，但旧稿只用于收口对照和防静默丢信息；不是逐行 base，不走 affected-line modify。

## 3. 加载核心假设编辑器 skill

扫描并读取最新版本（按 `vN` 的 N 做整数比较取最大，不是字符串排序）：

```text
D:\MKA\skills\核心假设编辑器_skill_v*.md
```

共享 A/B 是上位真源；编辑器 skill 补 KA 本地裁决流程（§2-§10）。**本启动器 §4-§6b 把材料拉起来后，进入编辑器 runbook 走裁决流程。**

## 3b. 人工筛选门

`/ka` 不主动扩大材料面。判断材料入口的排除规则（markdown 存储区、`WEBCLAUDE` 打包目录、`Agent\Load\` 沙箱副本、临时转换件和历史 cache 默认不是判断材料；看见 markdown 不等于必须吸收）见编辑器 runbook §0 / 核心纪律 A0.1，本启动器不复述；下面只讲 KA 目录特有规则。

本轮只读以下明确入口：同权重判断材料、`Agent业务讨论.md`、KA 目录顶层全部 markdown、已完成 LOAD 主产物、Alphapai reference/factpack、`/init` 事实索引和旧 official 对照。其他材料只有在用户明确说“这份材料进入本轮判断”时才可读取，并要在 overview 里说明它为何进入。

KA 目录固定指 `companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\`。用户丢进这个目录的顶层 `*.md` 就是明确给 `/ka` 看的人工筛选材料：文件名以 `核心假设参考` 开头或抬头声明 reference/draft/model-extracted/factpack 的，按候选稿裁决；其他 markdown 按信息指引读取，不强制要求 `待 /ka 裁决清单`，但其中有价值的信息仍要进入 overview、接缝总账、收纳区或裁决理由。只读顶层文件，不递归读取子目录。

人工筛选门只管入口，不削弱收纳区。对已入场材料仍按核心纪律 A2 和编辑器接缝总账执行：未入模但有复盘价值的信息进入收纳区/stash，不得乱扔；只有重复、无关、越界或低可信且无复盘价值的信息才写丢弃理由。

## 4. 读取最高权重材料（同权重判断材料层）

先运行：

```bash
py -m src.ka_prepare "{公司}"
```

该脚本幂等 markdown 化以下**同权重判断材料**：

- `companies\{公司}\公司判断和最新观点.md`
- `companies\{公司}\重要文件\` 下的顶层材料（与公司判断同等权重；常放最重要、最新的会议纪要）
- `companies\{公司}\Skills素材包\最高权重材料-放Agent最应对齐的材料\` 下的顶层材料

输出到：

```text
companies\{公司}\Skills素材包\最高权重材料-放Agent最应对齐的材料\markdown存储区\
```

`公司判断和最新观点.md`、`重要文件\` 与最高权重材料文件夹顶层材料同权重；文件夹名只是历史目录名，不代表它压过分析师手写 thesis。凡读公司判断，必须把 `重要文件\` 下材料按同等权重一起读。后续 AI 只读 `ka_prepare` 为这些同权重判断材料生成的 markdown 存储区和 manifest，不直接读 raw PDF/Word/Excel，也不把其他 markdown cache 顺手并入。manifest 中的 `unsupported/error` 必须进入缺口区。

## 5. 读取 BRKD 产物

读取 `companies\{公司}\Agent业务讨论.md`。这是 `/brkd` 的业务层草稿，可提供当前业务结构、利润表讨论、待 `/ka` 拍板问题清单，其中所有预测建议仍需 KA 重新裁决。若 KA 目录另有 BRKD 核心假设式参考稿，`§6b` 会随全部顶层 markdown 一起读取；命名为 `核心假设参考brkd_*.md` 的按候选稿处理。

## 6. 读取 LOAD 产物并执行门禁

扫描 KA 目录 `companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\核心假设参考load_*.md`。只把已完成的 LOAD 核心假设算作门禁来源。以下不算：

- `/load prepare` 刚生成的空脚手架。
- 仍包含"待模型装载器补全"的文件。
- 没有末尾 ` ```knobs` 机器自报清单的文件。
- 没有抬头声明 `模式: load` / `状态: model-extracted` / `load-vintage` 的文件。
- `WEBCLAUDE` 打包副本、`Agent\Load\` 沙箱副本、正式 `状态: official` 核心假设。

若有多个 LOAD 参考稿，默认读取修改时间最新的一份，并把其他可用 LOAD 产物列为"可选参考，不自动并入"。

## 6b. 读取 KA 目录 markdown 并执行门禁

除 BRKD 和 LOAD 外，`/ka` 必须读取 KA 目录顶层所有 markdown。brkd/load/alphapai reference 仍建议命名 `核心假设参考{来源}_YYYYMMDD.md`，但这只是候选稿命名规范，不是 `/ka` 的读取过滤器：

```text
companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\*.md
```

读取方式：不在 `Agent\`、`WEBCLAUDE\`、`Agent\Load\` 等子目录里，只读 KA 目录非递归 `*.md`。LOAD 参考稿（`核心假设参考load_*`）在 §6 单独计为 LOAD 门禁，这里仍要读入材料包，但不重复计数。

身份区分：

- reference 候选：文件名以 `核心假设参考` 开头，或抬头声明 `状态: reference/draft/model-extracted/factpack`，或 `模式: alphapai-load`。只作候选理解和待裁决清单来源，预测值/knobs/时间轴必须重新裁决。
- 信息指引：KA 目录中其他顶层 markdown。它们是人工放入本轮的判断线索，不要求 `待 /ka 裁决清单`，不自动晋升 official，也不能直接 `/comp`；其中可采纳的信息进入正式判断，有价值但不入模的信息进入收纳区/stash，冲突或缺口进入接缝总账。

Alphapai reference 或信息指引中的 BS/CF/DCF 线索只进收纳区或 `/da` 分流判断，不自动打开 `/ka` 人工覆盖闸。

新的 reference/draft/model-extracted/factpack 候选应包含 `## 待 /ka 裁决清单`。读取 reference 时先把这节当作晋升议程：每条事项必须在 `/ka` 裁决中落到“采纳入 official / 收纳 / 缺口待补 / 丢弃并说明理由”之一，不能只因候选稿里已有 knobs 就静默晋升。旧 reference 若缺这节，不硬停，但必须在 overview 中标记“缺待 /ka 裁决清单”，并从正文、收纳区、缺口和 knobs 自报里补一版议程后再裁决。

`/ka` 不能凭空生成。继续前必须至少具备以下三者之一（**门禁档定义，`/webka` 须与之一致**）：(1) **BRKD 档** = 公司根目录 `Agent业务讨论.md`；(2) **LOAD 档** = KA 目录已完成的 `核心假设参考load_*.md`（完成性判定见 §6）；(3) **KA 目录 markdown 档** = KA 目录任一顶层 markdown（含 `核心假设参考brkd_*.md`，归此档，不计 BRKD 档）。若三者都没有，停止：

```text
当前没有已完成 LOAD 产物、没有 BRKD 产物 Agent业务讨论.md，也没有可读 KA 目录 markdown。/ka 不能凭空生成。建议先跑 /brkd、补完 /load，或把要给 /ka 看的 markdown 放入 KA 目录后再回来。
```

同权重判断材料（含最高权重材料文件夹）、旧正式稿、`公司判断和最新观点.md`、`重要文件\` 不计入本门禁；它们是裁决材料或旧稿对照，不是业务骨架来源。

## 7. 进入裁决流程（交给编辑器 runbook）

材料拉齐后，**进入 `核心假设编辑器_skill_v*.md` 走裁决流程**，本文件不重复：

- 输入权重与冲突顺序 → 编辑器 §1
- defaults 审计标识（`review_flags` 三类处理、分红率强制检测）→ 编辑器 §1.1
- 时间轴四数 + 自动 fade profile → 编辑器 §2 / §2.1
- 开场 overview → 编辑器 §3
- 接缝总账 → 编辑器 §4
- 骨架门（family 必须落在源语言 §B4 可执行集合内，不得自创）→ 编辑器 §5
- 数值门（收入→毛利→费用→below-OP/税/少数股东→分红率→可选 BS/CF 覆盖→terminal）→ 编辑器 §6
- 年报查证纪律 → 编辑器 §7
- 防静默 passthrough → 编辑器 §8
- 收口核对与落盘 → 编辑器 §9 / §10

落盘路径（编辑器 §10 同源）：

```text
companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设.md          # 聊透写正式稿
companies\{公司}\{公司名}-{今日YYYYMMDD}-核心假设参考.md       # 有悬项写参考稿，醒目标注"未拍板，不可直接 /comp"
```

重建且根目录已有旧正式稿时，落盘前先归档旧稿（铁律 1，禁止原地覆盖）：

```bash
py scripts/ka_archive.py "<旧正式稿完整路径>"
```
