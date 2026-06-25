---
name: brkd
description: 启动 BRKD 业务理解器。第一步用 Python 幂等地把公司 Skills素材包/BRKD业务理解器（研报和纪要放在这里）里的源文件转换到 markdown存储区；第二步让 AI 只读 markdown 存储区，并结合 /init 标准财务事实与年报按需查证，生成贴近 /ka 和 /comp 源语言的 Agent业务讨论.md。纪律和格式对齐核心纪律 A 与核心假设源语言 B，功能不替 KA 拍板。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /brkd - 业务理解器启动器

`/brkd` 分两步：

```text
Step 1 deterministic: 原始文件 -> markdown存储区
Step 2 AI: markdown存储区 + /init + 年报按需查证 -> Agent业务讨论.md
```

`/brkd` 的产物不是文献综述，而是 `/ka` 可以接手、`/comp` 源语言也能理解的业务假设草稿。它明确收窄为**利润表 + 业务层盈利模型理解器**：只讨论收入、成本/毛利、费用率、below-OP、税率、少数股东等利润表相关判断；不处理由 BS/现金/债务派生的 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等 BS/CF/DCF 驱动因素。只有材料明确给出利润表外生“其他财务费用”时，才可作为 `other_fin_exp_abs` 草稿项提示。它在纪律和格式上对齐核心纪律 A 与核心假设源语言 B，但功能上不替 `/ka` 生成正式核心假设。

## 0. 共享真源

在 AI 理解阶段之前，必须加载两份共享真源：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
D:\MKA\docs\knobs块契约.md
```

`/brkd` 完整继承核心纪律 A1/A2/A3/A7；A5/A6 只到草稿态；A4 是弱形态，产物整体保持 draft。输出必须符合核心假设源语言 B 的半成品形态；末尾 draft/partial `knobs` 块语法以 `docs/knobs块契约.md` 为准。

交互和汇报口吻继承核心纪律 A4 的会议 memo 风格：先输出你对业务和利润表的理解、初步预测倾向、主要分歧和待 `/ka` 拍板点，再写入 `Agent业务讨论.md`。不要把材料摘录、完整 draft knobs 或 markdown 模板直接倾倒给用户；用户要的是你读完后的判断。

## 1. 解析公司目录

从 `$ARGUMENTS` 定位 `D:\MKA\companies\{公司}`：

1. 精确匹配 `companies\{参数}`。
2. 代码匹配 `companies\*_{代码}`。
3. 公司名匹配 `companies\{公司名}_*`。
4. 命中多个时列候选并询问用户。
5. 未命中时报错停止。

## 2. 确定 BRKD 素材入口

只从固定素材包读取源文件：

```text
companies\{公司}\Skills素材包\BRKD业务理解器（研报和纪要放在这里）\
```

该目录允许用户放 PDF、Markdown、TXT、CSV、DOCX、Excel 等材料。AI 不直接读取这些源文件，必须先 deterministic markdown 化。

## 3. 先跑 deterministic markdown prepare

AI 阅读材料之前，必须先运行：

```bash
py -m src.brkd_prepare "{公司}"
```

脚本会：

1. 扫描 BRKD 素材包顶层源文件。
2. 创建或复用：

```text
companies\{公司}\Skills素材包\BRKD业务理解器（研报和纪要放在这里）\markdown存储区\
```

3. 幂等转换：
   - `.pdf` -> PyMuPDF plain-text markdown
   - `.md/.markdown/.txt/.csv/.tsv` -> 带来源 frontmatter 的 markdown
   - `.docx` -> Word XML text markdown
   - `.xlsx/.xlsm` -> workbook sheets markdown 表
   - `.doc/.xls` -> 生成“不支持确定性转换”的 markdown 占位，提示用户另存
4. 写入：

```text
markdown存储区\brkd_prepare_manifest.json
```

如果脚本失败，停止并报告 stdout/stderr，不进入 AI 阅读阶段。

## 4. 先加载业务预理解器 skill

prepare 成功后，扫描并读取最新版本：

```text
D:\MKA\skills\业务预理解器_skill_v*.md
```

必须先加载 skill，再开始 AI 理解。读取顺序、年报使用方式、输出语法和草稿态纪律都由该 skill 约束。

## 5. 判断 brkd 模式

读取 `markdown存储区\` 里的 `.md` 文件和 manifest：

- 若有成功转换或已有 markdown 材料 -> 外部材料增强模式：全读 markdown 存储区，不交互挑选。
- 若源素材为空、markdown 存储区也无有效材料 -> 年报 + 历史财务模式：不报错；读取年报和 `/init` 历史事实包，产出更保守的 `Agent业务讨论.md`，明确标注“无外部研报/纪要”。
- 若 manifest 中存在 `unsupported` 或 `error`，不得静默忽略；必须进入 `Agent业务讨论.md` 的缺口区。

## 6. 读取定调、/init 与年报查证材料

1. 读取 `companies\{公司}\公司判断和最新观点.md`。它是背景锚点，不覆盖、不另起 thesis。若不存在，停止。
2. 读取 `/init` 历史事实包：
   - 优先 `Agent/core_metrics_overview.md/json/csv`
   - 若没有，读 `Agent/data.db` 的 `clean_annual`
   - 若 `data.db` 或 `clean_annual` 不可用，停止并提示先跑 `/init`
3. 年报是 X 光片，不是主材料：
   - 外部材料增强模式下，只在需要查证分部、成本/毛利、费用明细、税收优惠、非经常性损益、减值等利润表口径时查对应位置；不为 BS/现金/债务派生的 `financial expense` 或 DCF 驱动去翻 BS/CF 附注。
   - 年报 + 历史财务模式下，可以用最新年报建立最小业务拆分，但必须明确保守性。

研报/纪要只提供业务线索、共识分歧、管理层语言和争议；headline 财务事实以 `/init` clean 后的历史事实和年报为准。

## 7. 生成 Agent业务讨论.md

按业务预理解器 skill 执行。产物写到：

```text
companies\{公司}\Agent业务讨论.md
```

`Agent业务讨论.md` 是 BRKD 的 canonical 产物。若用户额外要求输出“核心假设式参考稿”到公司根目录，文件名必须带来源后缀：

```text
companies\{公司}\{公司名或材料stem}_核心假设_brkd{运行YYYYMMDD}.md
```

该文件必须声明 `状态: draft` 或 `状态: reference`，只供 `/ka` 识别为 BRKD 候选；不得命名为普通 `*_核心假设.md`，不得伪装 official。

输出要求：

- 结构贴近 `/ka` 和 `/comp` 的核心假设源语言。
- 收入业务线尽量写成“上挂科目 + compiler family + 历史事实 + 建议旋钮 + 三件套 + 待 /ka 拍板”。
- 费用、毛利、below-OP、税率也按 `/comp` 可理解的标准语义组织；BS/现金/债务派生的 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等不作为 BRKD/KA 预测对象；明确利润表外生项才可提示 `other_fin_exp_abs` 草稿。
- 所有建议值必须标注 `draft / 待 /ka 拍板`。
- 不锁定最终时间轴，但 overview 第一项必须先报时间线索：材料年份、历史事实区间、建议 horizon、已知拐点和可能需要覆盖的年份；最终四数交给 `/ka` 裁决。
- 末尾必须有 `knobs` 草稿块；没有明确建议值时留空并说明原因。

写文件前先给用户一页会议 memo：

```text
我读完材料后，先给结论：
1. 这家公司现在的核心增长/压力来自...
2. 利润表上最该让 /ka 拍板的是...
3. 我建议的业务骨架是...

主要证据:
| 主题 | 材料怎么说 | 我怎么处理 |

待 /ka 拍板:
- ...

这个业务理解方向如果没问题，我就写成 Agent业务讨论.md 的 draft 源语言稿。
```

用户要求看完整草稿时再展开；默认不要在聊天里全量贴 `Agent业务讨论.md` 模板和 draft `knobs`。

## 8. `/brkd` 独有纪律

共享纪律见 `核心纪律_skill_v*.md`，源语言语法见 `核心假设源语言_skill_v*.md`。`/brkd` 本地只补这些独有条款：

- 年报是 X 光片：外部材料存在时，不把年报升格为常规主材料；只按需查证。
- 不替 `/ka` 拍板：不写正式核心假设，不写当前最终旋钮，不落正式 forecast。
- 利润表 + 业务层盈利模型边界：不处理由 BS/现金/债务派生的 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等 BS/CF/DCF 驱动因素；材料里出现时只进收纳区或丢弃原因，标注“非 BRKD 范围”。只有材料明确给出利润表外生“其他财务费用”时，才可按核心假设源语言 B 写成 `other_fin_exp_abs` 草稿，并标 `draft / 待 /ka 拍板`；是否升格为 `/ka` 的人工 BS/CF 覆盖，只能由最高权重材料或分析师明示触发。
- 不编造量价原子：年报、研报、纪要都不支持时，不硬造销量、价格、门店、吨价、ARPU。
- 研报线索 vs clean_annual 事实必须分级；headline 财务事实以 `/init` 或年报为准。
- 不锁最终时间轴，只交建议 horizon、材料年份和拐点线索；这些线索必须在 Agent业务讨论.md 的 overview 第一项先报。
- 所有预测建议标 `draft / 待 /ka 拍板`。
- AI 只读 markdown 存储区，不碰生料。
- prepare manifest 的 `unsupported/error` 不静默忽略。
- 不生成 YAML1、DCF 或完整 `model_assumption_schema.json`。

## 9. CLI

```bash
/brkd 新乳业
/brkd 002946
/brkd 002946.SZ
```

底层 prepare 可单独运行：

```bash
py -m src.brkd_prepare 新乳业
py -m src.brkd_prepare 新乳业 --force
```

## 10. 退出码

- `0`：`Agent业务讨论.md` 生成成功。
- `2`：输入无法解析为唯一公司目录，或 `src.brkd_prepare` 失败。
- `3`：缺 `公司判断和最新观点.md`，或 `/init` 历史事实不可用，或在无外部材料时缺最新年报 Markdown。
- `1`：其他 IO 异常。
