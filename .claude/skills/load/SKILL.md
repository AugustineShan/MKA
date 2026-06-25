---
name: load
description: 启动 LOAD 外部 Excel 模型理解器。只读取公司 Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）里的唯一 Excel，先建立 load 沙箱与时间边界，再按 v19 的纪律层把模型公式层翻译为 /comp 能继续 schema 化的 `{原Excel文件名}_核心假设.md`。纪律和格式对齐旧 KA v19，功能不回退到 KA。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /load - 外部 Excel 模型理解器

`/load` 的职责是把一个外部 Excel 模型翻译成 `/comp` 能继续 schema 化的核心假设源文。它只保存原模型的 load-vintage，不生成当前正式判断，不接管 `/ka` 的裁决。

一句话：

```text
/load = Excel 公式层理解器 + 时间沙箱 + v19 纪律化装载 + /comp 源语言
```

它与 `D:\04_核心假设生成修改器_skill_v19.md` 的关系是：纪律和格式对齐旧 v19，功能不回退。旧 v19 里的“读模型能力”迁移到 `/load`；旧 v19 里的“当前核心假设裁决”仍留给 `/ka`。

## 0. 共享真源

在执行任何阅读和写作之前，必须先加载两份共享真源：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
```

`/load` 完整继承核心纪律 A1-A7；输出必须符合核心假设源语言 B。本文只保留 `/load` 独有边界：load-vintage 隔离、forbidden_materials 沙箱、模型公式层权威顺序、只写 `Agent/Load/`。

## 1. 解析公司目录

从 `$ARGUMENTS` 定位 `D:\MKA\companies\{公司}`：

1. 精确匹配 `companies\{参数}`。
2. 代码匹配 `companies\*_{代码}`，如 `002946`。
3. 公司名匹配 `companies\{公司名}_*`。
4. 命中多个时列候选并询问用户。
5. 未命中时报错停止。

## 2. 定位 LOAD 素材入口

只从固定素材包读取模型：

```text
companies\{公司}\Skills素材包\LOAD外部EXCEL模型理解器（一次最多一个）\
```

硬规则：

- 该文件夹必须恰好有一个 `.xlsx` / `.xlsm` / `.xls`。
- 跳过 Office lock 文件 `~$*.xls*`。
- 没有 Excel 时停止，提示用户把模型放入该文件夹。
- 多于一个 Excel 时停止，列出文件名，让用户只保留一个。
- 不从 `active_vore`、`WEBCLAUDE`、公司根目录或正式 `Agent/forecast` 寻找模型。

## 3. 先跑 deterministic prepare

在 AI 阅读材料、年报、数据库、旧核心假设之前，先运行：

```bash
py -m src.model_load prepare "{公司}" --overwrite
```

prepare 是 `/load` 的“时间轴第零件事”。它会：

1. 用 `openpyxl(data_only=False)` 读取公式层。
2. 锁定模型边界：
   - `model_asof_date`
   - `history_end_year`
   - `forecast_start_year`
   - `forecast_years`
3. 创建沙箱：

```text
companies\{公司}\Agent\Load\{load_id}\
```

4. 写入：
   - `model_boundary.json`
   - `model_boundary.md`
   - `allowed_materials\`
   - `forbidden_materials.md`
   - `data_cutoff.db`，若正式 `Agent\data.db` 存在
   - `defaults.yaml`，若 `data_cutoff.db` 可生成
   - `{原Excel文件名}_核心假设.md` 脚手架

如果 prepare 报时间轴冲突、base period 冲突、Excel 数量异常或无法建立沙箱，必须停止并报告，不允许绕过。

## 4. 先加载模型装载器 skill，再读沙箱

扫描并读取最新版本：

```text
D:\MKA\skills\模型装载器_skill_v*.md
```

必须先加载模型装载器 skill，再开始 AI 阅读沙箱材料。读取纪律、确认顺序、输出格式都由该 skill 定义。

不要把旧 `04_核心假设生成修改器_skill_v*.md` 当成 `/load` 主流程。旧 v19 只提供纪律参照：时间轴、历史保全、接缝、对账不是算账、押不等于落盘、knobs 自报清单。

## 5. 只读 load 沙箱，不读越界材料

AI 只允许读取：

```text
Agent\Load\{load_id}\model_boundary.md
Agent\Load\{load_id}\model_boundary.json
Agent\Load\{load_id}\allowed_materials\
```

`forbidden_materials.md` 只能作为禁读清单读取，禁止打开其中列出的正文材料。

禁止读取或引用：

- `forecast_start_year` 及之后的实际年报、季报、公告正文。
- 当前正式 `Agent/data.db`、正式 `Agent/defaults.yaml`、正式 `Agent/forecast/`。
- 公司根目录旧正式核心假设。
- `WEBCLAUDE/` 打包副本。
- 超出 load-vintage 的最新观点来覆盖模型边界。

若存在 `公司判断和最新观点.md`，只能作为背景口径，不能覆盖模型公式层、模型时间轴和原模型预测旋钮。

## 6. `/load` 独有纪律

共享纪律见 `核心纪律_skill_v*.md`，源语言语法见 `核心假设源语言_skill_v*.md`。`/load` 本地只补这些独有条款：

- load-vintage 隔离：后验事实绝不写进原模型预测。
- `model_boundary.*` 是 vintage 时间轴唯一归口；公司判断和最新观点不得覆盖模型时间轴、预测起点或原模型旋钮。
- 权威顺序：模型公式层 > 模型内文字 > `allowed_materials` > 背景口径。
- 公式层读法：用 `openpyxl(data_only=False)`，硬编码首列通常是预测起点。
- forbidden_materials 沙箱：禁读材料只能作为清单，不能打开正文。
- 只写 `Agent/Load/{load_id}/`，不碰公司根目录和正式 `Agent/forecast/`。
- 不做完整 `model_assumption_schema.json`；结构化翻译交给 `/comp`。

## 7. 模型理解 overview 确认门

补完 `{原Excel文件名}_核心假设.md` 前，必须先给用户一个完整 overview 并停止。

overview 至少覆盖：

- 模型源文件、模型日期、历史末年、预测起点、显式预测期。
- 允许读取的材料与禁读材料摘要。
- 收入拆分：几条业务线、如何汇总、各线 driver。
- 毛利/成本处理：分线派生、整体手拍还是混合；若和收入成本旋钮耦合，先说明。
- 费用、below-OP、税率、资本开支、营运资本、终值的主要旋钮。
- 哪些格子像人工判断，哪些公式或标签可能误读。
- 准备如何写成 `/comp` 源语言。

结尾必须明确问：

```text
我这样理解这个模型对不对？你确认后，我再按收入 -> 毛利 -> 费用 -> below-OP 与税 -> 中期的顺序，一段一段先押再问、拍板后写入 load 沙箱。
```

用户未确认前：

- 不得补完 `{原Excel文件名}_核心假设.md`。
- 不得编译 `yaml1_load_*.yaml`。
- 不得运行 `model_load dcf`。
- 不得把任何 load 产物写到公司根目录或正式 `Agent/forecast/`。

## 8. 生成 /comp 源语言的 load 核心假设

用户确认 overview 后，才补写：

```text
companies\{公司}\Agent\Load\{load_id}\{原Excel文件名}_核心假设.md
```

这份文件必须是 `/comp` 已经吃得懂的核心假设源语言：

- 按收入 -> 毛利 -> 费用 -> below-OP 与税 -> 中期组织。
- 收入线写清上挂科目、compiler family、旋钮、派生、历史原子、来源。
- 标准利润表项目写清是否是旋钮、是否沿用模型、是否只是派生。
- 历史只写到 `history_end_year`。
- 预测从 `forecast_start_year` 开始，即使该年现在已经成为实际年，也按原模型预测处理。
- 副拆分、算了不用的历史、口径说明进入收纳区。
- 末尾必须有 `knobs` 机器自报清单，值与正文一字不差。

文件名必须保留原 Excel stem：

```text
{原Excel文件名}_核心假设.md
```

## 9. 编译 yaml1_load 与沙箱 DCF

只有所有必要段落均被用户确认后，才能按最新 `yaml1compiler_v*.md` 把 `{原Excel文件名}_核心假设.md` 编译为：

```text
companies\{公司}\Agent\Load\{load_id}\yaml1_load_{公司}_{YYYYMMDD}.yaml
```

编译后必须执行 `yaml1compiler_v*.md` §9 的 compiler audit。只有 `audit_clean`（覆盖双射、B 类完整性、`unaligned`/路径待核为空、语义待核已确认、主动覆盖回读完成）才允许继续跑沙箱 DCF。若 audit 不干净，`yaml1_load_*.yaml` 只能作为 reference/draft 留在 load 沙箱，**不得**运行 `model_load dcf`。

然后运行：

```bash
py -m src.model_load dcf --load-dir "companies\{公司}\Agent\Load\{load_id}" --yaml1 "companies\{公司}\Agent\Load\{load_id}\yaml1_load_{公司}_{YYYYMMDD}.yaml"
```

DCF 输出只能落：

```text
companies\{公司}\Agent\Load\{load_id}\forecast\
```

禁止覆盖：

```text
companies\{公司}\Agent\forecast\
```

## 10. 汇报格式

最后向用户汇报：

- 模型源文件。
- 历史末年、预测起点、显式预测期。
- 禁读材料摘要。
- `{原Excel文件名}_核心假设.md` 路径。
- `yaml1_load_*.yaml` 路径，若已编译。
- 沙箱 DCF 路径和每股价值，若已运行。
- 明确说明：这是 load-vintage 沙箱，不是当前正式 forecast。
