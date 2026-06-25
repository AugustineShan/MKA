---
name: load
description: 启动 LOAD 外部 Excel 模型理解器。只读取公司 Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）里的唯一 Excel，先建立 load 沙箱与时间边界，再按核心纪律 A 与核心假设源语言 B 把模型公式层翻译为 /comp 能继续 schema 化的 `{原Excel文件名}_核心假设_load{YYYYMMDD}.md`。产物是 load-vintage，不回退到 KA。
argument-hint: [公司名或代码，如 新乳业 / 002946]
allowed-tools: Read, Grep, Glob, Edit, Write, Bash
---

# /load - 外部 Excel 模型理解器

`/load` 的职责是把一个外部 Excel 模型翻译成 `/comp` 能继续 schema 化的核心假设源文。它只保存原模型的 load-vintage，不生成当前正式判断，不接管 `/ka` 的裁决。

一句话：

```text
/load = Excel 公式层理解器 + 时间沙箱 + 核心纪律 A/B + /comp 源语言
```

它与历史 v19(已归档至 `deprecatedlogs/`)的关系是：读模型能力已经迁移到 `/load`；当前核心假设裁决仍留给 `/ka`。横切纪律权威以 `核心纪律_skill`(A1-A7) + `核心假设源语言_skill`(B) 为准，不引用旧 v19。

## 0. 共享真源

在执行任何阅读和写作之前，必须先加载两份共享真源：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
D:\MKA\docs\knobs块契约.md
```

`/load` 完整继承核心纪律 A1-A7；输出必须符合核心假设源语言 B，末尾 `model-extracted` knobs 块语法以 `docs/knobs块契约.md` 为准。本文只保留 `/load` 独有边界：load-vintage 隔离、forbidden_materials 沙箱、模型公式层权威顺序、根目录主产物 + `Agent/Load/` 沙箱副本。

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
   - `{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md` 脚手架（沙箱内，仅供装载器续写/同步）
   - `root_core_assumption_path`：最终主产物应回填到公司根目录的路径

如果 prepare 报时间轴冲突、base period 冲突、Excel 数量异常或无法建立沙箱，必须停止并报告，不允许绕过。

## 4. 先加载模型装载器 skill，再读沙箱

扫描并读取最新版本：

```text
D:\MKA\skills\模型装载器_skill_v*.md
```

必须先加载模型装载器 skill，再开始 AI 阅读沙箱材料。读取纪律、确认顺序、输出格式都由该 skill 定义。

不要把已归档的旧 v19(`deprecatedlogs/04_核心假设生成修改器_skill_v19.md`)当主流程。纪律权威是 `核心纪律_skill_v*.md`(A1-A7) + `核心假设源语言_skill_v*.md`(B);旧 v19 只作历史复盘,不引用。

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
- sheet 读取习惯：如果 Excel 里有名为 `年度和半年度` 的 sheet，默认只看这个 sheet；这是本项目外部模型的主视图习惯。只有该 sheet 明确缺失关键结构时，才说明缺口并按需看其他相关 sheet。
- 装载范围只限利润表和业务层盈利模型：收入、成本/毛利、费用率、below-OP、税率、少数股东等利润表项目。禁止为了补 DCF 去读取或导出 `Model-BS` / `DCF` 表里的 `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等驱动因素；这些通常由引擎/defaults 平推。只有最高权重材料或分析师明确把 BS/CF 因素提升为核心 thesis 时，才由 `/ka` 开人工覆盖闸；重资产 DA/capex 排程优先走 `/da`。
- 财务费用若在利润表主表中由现金/负债/利率等 BS 公式推导，只标为“派生·不进旋钮”，不得继续追 Model-BS；只有利润表主表明确给了外生手填财务费用项时，才按利润表旋钮处理。
- forbidden_materials 沙箱：禁读材料只能作为清单，不能打开正文。
- 完成稿的**主产物写公司根目录**：`companies\{公司}\{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md`，供 `/ka` 读取。`_load{运行YYYYMMDD}` 后缀不可省略，防止被误认作 official 核心假设。
- 同步副本写 `Agent/Load/{load_id}/{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md`，供 `/load` 自己做 yaml1_load 编译、审计和沙箱 DCF。
- 不碰正式 `Agent/forecast/`。
- 不做完整 `model_assumption_schema.json`；结构化翻译交给 `/comp`。

## 7. 模型理解 overview 确认门

补完 `{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md` 前，必须先给用户一个完整 overview 并停止。

交互风格必须像分析师开会，不像机器审表。聊天里先给“口头 memo”，落盘时再写完整 `/comp` 源语言：

- 先讲结论，再讲证据：用“我读下来，这个模型其实在讲三件事……”开场，不要一上来倾倒 cell range、完整 markdown 段或 knobs 列表。
- 每次确认控制在一个可读屏幕左右：时间轴、模型形状、关键旋钮、主要风险、下一步。
- 数值用紧凑表格或短句归纳；source range 只保留最关键出处，完整来源和历史原子写进文件。
- 不在聊天确认阶段逐条展示 JSON/YAML 风格 `knobs`；除非用户要求或存在歧义。`knobs` 必须完整落盘，但不必每段都在聊天里全量贴出。
- 每段结尾问一个自然问题：`这段我这样装可以吗？确认后我写入底稿，再进下一段。`

overview 第一项必须先核对时间轴四数：

1. 历史数据到哪一年：以 `model_boundary.*` 的 `history_end_year` 为 vintage 边界，并用公式层验证。
2. 显式预测期从哪年到哪年：以 `forecast_start_year` 和 `forecast_years` 为准。
3. 衰减期多长或至哪年：只有模型主表明确给出才记录；没给就写“模型未给，不默认”。
4. 永续增长点是多少：只有模型主表明确给出才记录；没给就写“模型未给，不默认”。

这四个数字至少落在三处：本次交互第一次 overview 的第一项、产出文件抬头、进入“中期”段之前的二次核对。铁律：不默认、不平推、不等分析师自己说；先问、先确认、先写进底稿，再进下一道工序。

overview 至少覆盖：

- 模型源文件、模型日期、时间轴四数。
- 允许读取的材料与禁读材料摘要。
- 收入拆分：几条业务线、如何汇总、各线 driver。
- 毛利/成本处理：分线派生、整体手拍还是混合；若和收入成本旋钮耦合，先说明。
- 费用、below-OP、税率、少数股东等利润表项目；若财务费用是 BS 派生，只标派生，不追 Model-BS。
- 哪些格子像人工判断，哪些公式或标签可能误读。
- 准备如何写成 `/comp` 源语言。

结尾必须明确问：

```text
我先对一下时间轴：历史到 {YYYY}，显式期 {YYYY-YYYY}，衰减期 {模型给出/模型未给}，永续 {x%/模型未给}。这四个数字如果没问题，我就按“时间轴 -> 收入 -> 毛利 -> 费用 -> below-OP 与税 -> 中期”的顺序往下装。每段我先用会议 memo 的方式给你看结论和关键旋钮，你确认后我再写入底稿，并同步到 load 沙箱。
```

用户未确认前：

- 不得补完 `{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md`。
- 不得编译 `yaml1_load_*.yaml`。
- 不得运行 `model_load dcf`。
- 不得把完成稿写到公司根目录或正式 `Agent/forecast/`；prepare 沙箱脚手架不算完成稿。

## 8. 生成 /comp 源语言的 load 核心假设

用户确认 overview 后，才补写：

```text
companies\{公司}\{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md
```

这份文件是 `/load` 的主产物，也是 `/ka` 在公司根目录读取的 LOAD 产物。写完根目录主产物后，必须把同一内容同步到：

```text
companies\{公司}\Agent\Load\{load_id}\{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md
```

沙箱副本只供 `/load` 后续编译 `yaml1_load_*.yaml`、compiler audit 和沙箱 DCF 使用；`/ka` 只从公司根目录读主产物。

逐段确认时，聊天输出用“会议 memo”，文件落盘用“机器可读源语言”。例如收入段不要直接贴三条 leaf 的完整底稿和 knobs 清单；先压成：

```text
收入段，我读成三条线：
1. 中高端黄酒：量价齐升，是模型的增长主线。
2. 普通黄酒：量缩价涨，模型假设继续让位给中高端。
3. 其他产品：按 5% 稳定低增处理。

关键旋钮（2025-2028）：
| 线 | 量/收入 | 价 | 我会怎么装 |
| ... |

需要你拍的点：
- 显式期截到 2028，所以 2029-2031 和 2031 断裂列不装。
- 普通黄酒销量 -12.35% flat 偏强假设，我按原模型保留。

这段我这样装可以吗？确认后我写入底稿，再进毛利。
```

用户要求看完整底稿时可以展开；否则不要用完整 markdown 段和逐条 `knobs` 淹没聊天。

主产物必须是 `/comp` 已经吃得懂的核心假设源语言：

- 按时间轴 -> 收入 -> 毛利 -> 费用 -> below-OP 与税 -> 中期组织。
- 文件抬头必须回写 overview 已确认的时间轴四数；进入“中期”段之前必须再核一次。
- 收入线写清上挂科目、compiler family、旋钮、派生、历史原子、来源。
- 标准利润表项目写清是否是旋钮、是否沿用模型、是否只是派生。
- `financial expense`、`EBIT`、`DA`、`CAPEX`、`CWC`、`shares`、`WACC` 等 DCF/BS 驱动因素不进入 LOAD 旋钮；如模型主表露出相关派生结果，只可在风险/缺口中一句话标明“不装载，默认交引擎/defaults；显式 thesis 才由 /ka 人工覆盖或 /da 处理”。
- 历史只写到 `history_end_year`。
- 预测从 `forecast_start_year` 开始，即使该年现在已经成为实际年，也按原模型预测处理。
- 副拆分、算了不用的历史、口径说明进入收纳区。
- 末尾必须有 `knobs` 机器自报清单，值与正文一字不差。
- 抬头必须声明 `模式: load` / `状态: model-extracted` / `说明: load-vintage`，防止 `/comp` 把它误当 `official` 正式核心假设。

文件名必须保留原 Excel stem：

```text
{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md
```

## 9. 编译 yaml1_load 与沙箱 DCF

只有所有必要段落均被用户确认后，才能按最新 `yaml1compiler_v*.md` 把 `{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md` 编译为：

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
- 根目录主产物 `{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md` 路径。
- 沙箱副本 `{原Excel文件名}_核心假设_load{运行YYYYMMDD}.md` 路径。
- `yaml1_load_*.yaml` 路径，若已编译。
- 沙箱 DCF 路径和每股价值，若已运行。
- 明确说明：这是 load-vintage 沙箱，不是当前正式 forecast。
