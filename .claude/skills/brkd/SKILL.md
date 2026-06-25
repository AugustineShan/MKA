---
name: brkd
description: 启动 BRKD 业务理解器。第一步用 Python 幂等地把公司 Skills素材包/BRKD业务理解器（研报和纪要放在这里）里的源文件转换到 markdown存储区；第二步让 AI 只读 markdown 存储区，并结合 /init 标准财务事实与年报按需查证，生成贴近 /ka 和 /comp 源语言的 Agent业务讨论.md。纪律和格式对齐旧 KA v19，功能不替 KA 拍板。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /brkd - 业务理解器启动器

`/brkd` 分两步：

```text
Step 1 deterministic: 原始文件 -> markdown存储区
Step 2 AI: markdown存储区 + /init + 年报按需查证 -> Agent业务讨论.md
```

`/brkd` 的产物不是文献综述，而是 `/ka` 可以接手、`/comp` 源语言也能理解的业务假设草稿。它在纪律和格式上对齐旧 v19，但功能上不替 `/ka` 生成正式核心假设。

## 0. 共享真源

在 AI 理解阶段之前，必须加载两份共享真源：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
```

`/brkd` 完整继承核心纪律 A1/A2/A3/A7；A5/A6 只到草稿态；A4 是弱形态，产物整体保持 draft。输出必须符合核心假设源语言 B 的半成品形态。

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
   - 外部材料增强模式下，只在需要查证分部、成本/毛利、费用明细、税收优惠、非经常性损益、减值、财务费用附注时查对应位置。
   - 年报 + 历史财务模式下，可以用最新年报建立最小业务拆分，但必须明确保守性。

研报/纪要只提供业务线索、共识分歧、管理层语言和争议；headline 财务事实以 `/init` clean 后的历史事实和年报为准。

## 7. 生成 Agent业务讨论.md

按业务预理解器 skill 执行。产物写到：

```text
companies\{公司}\Agent业务讨论.md
```

输出要求：

- 结构贴近 `/ka` 和 `/comp` 的核心假设源语言。
- 收入业务线尽量写成“上挂科目 + compiler family + 历史事实 + 建议旋钮 + 三件套 + 待 /ka 拍板”。
- 费用、毛利、below-OP、税率也按 `/comp` 可理解的标准语义组织。
- 所有建议值必须标注 `draft / 待 /ka 拍板`。
- 不锁定最终时间轴，只记录建议 horizon、已知拐点和材料引用年份，交给 `/ka` 裁决。
- 末尾必须有 `knobs` 草稿块；没有明确建议值时留空并说明原因。

## 8. `/brkd` 独有纪律

共享纪律见 `核心纪律_skill_v*.md`，源语言语法见 `核心假设源语言_skill_v*.md`。`/brkd` 本地只补这些独有条款：

- 年报是 X 光片：外部材料存在时，不把年报升格为常规主材料；只按需查证。
- 不替 `/ka` 拍板：不写正式核心假设，不写当前最终旋钮，不落正式 forecast。
- 不编造量价原子：年报、研报、纪要都不支持时，不硬造销量、价格、门店、吨价、ARPU。
- 研报线索 vs clean_annual 事实必须分级；headline 财务事实以 `/init` 或年报为准。
- 不锁最终时间轴，只交建议 horizon、材料年份和拐点线索。
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
