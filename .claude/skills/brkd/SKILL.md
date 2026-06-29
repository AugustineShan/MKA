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

本启动器只负责**启动机械**：解析目录 → 素材入口 → deterministic prepare → 加载 runbook → 拉起材料。**理解流程（范围边界、输入优先级、工作模式、输出语法、分段流程、本地纪律、memo 风格）在业务预理解器 runbook**（`业务预理解器_skill_v*.md`），不在本文件重复——读到那里照做。

`/brkd` 产物不是文献综述，而是 `/ka` 可接手、`/comp` 源语言能理解的业务假设草稿（draft，不替 `/ka` 拍板）。

**主导方向**：忠实记录业务拆分+历史+收纳数据（即便不参与计算）优先于预测；详见 runbook 核心指导。

## 0. 共享真源

AI 理解阶段前必须加载：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
D:\MKA\docs\knobs块契约.md
D:\MKA\skills\业务预理解器_skill_v*.md     # BRKD 理解流程 runbook
```

`/brkd` 完整继承核心纪律 A1/A2/A3/A7；A5/A6 只到草稿态；A4 弱形态。输出符合核心假设源语言 B 半成品；末尾 draft/partial `knobs` 块语法以 `docs/knobs块契约.md` 为准。范围边界（利润表 + 业务层盈利模型；不处理 BS/CF/DCF 驱动）、输入优先级、工作模式、分段流程、本地独有纪律、memo 风格——全见 runbook。

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

该目录允许放 PDF、Markdown、TXT、CSV、DOCX、Excel 等材料。AI 不直接读取这些源文件，必须先 deterministic markdown 化。

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
   - `.doc/.xls` -> 生成"不支持确定性转换"的 markdown 占位，提示用户另存
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

必须先加载 skill，再开始 AI 理解。**读取顺序、年报使用方式、输出语法、分段流程和草稿态纪律都由该 runbook 约束**——本启动器 §5-§7 把材料和模式拉起来后，进入 runbook 走理解流程。

## 5. 判断 brkd 模式

读取 `markdown存储区\` 里的 `.md` 文件和 manifest：

- 有成功转换或已有 markdown 材料 → 外部材料增强模式。
- 源素材为空、markdown 存储区也无有效材料 → 年报 + 历史财务模式（不报错，产出更保守的稿）。
- manifest 中 `unsupported`/`error` 不得静默忽略，必须进入 `Agent业务讨论.md` 缺口区。

两种模式各自怎么读、怎么写见 runbook §2。

## 6. 读取同权重定调、/init 与年报查证材料

1. 先运行 `py -m src.ka_prepare "{公司}"`，读取同权重判断材料 markdown 存储区与 manifest：
   ```text
   companies\{公司}\Skills素材包\最高权重材料-放Agent最应对齐的材料\markdown存储区\
   ```
   其中 `公司判断和最新观点.md` 是背景锚点，不覆盖、不另起 thesis；`companies\{公司}\重要文件\` 下材料与其同等权重，常放最重要、最新的会议纪要，凡读公司判断必须一起读。`公司判断和最新观点.md` 不存在则停止；manifest 中 `unsupported/error` 必须进入缺口区。
2. 读取 `/init` 历史事实包：优先 `Agent/core_metrics_overview.*`，否则 `Agent/data.db` 的 `clean_annual`；不可用则停止提示先跑 `/init`。
3. 年报是 X 光片不是主材料，按需查证口径——查证纪律见 runbook §1/§2。

研报/纪要只提供业务线索、共识分歧、管理层语言；headline 财务事实以 `/init` clean 后历史事实和年报为准。

## 7. 生成 Agent业务讨论.md

按业务预理解器 runbook 执行（输出语法 §4、分段流程 §5、模板 §6、纪律 §3/§7）。产物写到：

```text
companies\{公司}\Agent业务讨论.md
```

`Agent业务讨论.md` 是 BRKD 的 canonical 产物，留在公司根目录。若用户额外要求输出"核心假设式参考稿"，统一输出到 KA 参考稿区，命名：

```text
companies\{公司}\Skills素材包\KA（ALPHAPAI拆出来的东西放在这里）\核心假设参考brkd_{运行YYYYMMDD}.md
```

该文件必须声明 `状态: draft` 或 `状态: reference`，只供 `/ka` 到 KA 参考稿区识别为 BRKD 候选；不得命名为普通 `*_核心假设.md`，不得伪装 official。

## 8. CLI

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

## 9. 退出码

- `0`：`Agent业务讨论.md` 生成成功。
- `2`：输入无法解析为唯一公司目录，或 `src.brkd_prepare` 失败。
- `3`：缺 `公司判断和最新观点.md`，`ka_prepare` 同权重判断材料准备失败，或 `/init` 历史事实不可用，或在无外部材料时缺最新年报 Markdown。
- `1`：其他 IO 异常。
