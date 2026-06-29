# Codex 快速入门：MKA 项目导航

> 新开 Codex 线程时，先读本文件。它是 MKA 的项目地图，不是所有执行细则的副本。
> 真正执行某个 skill 时，必须再读 `D:\MKA\.claude\skills\{skill}\SKILL.md`。
> 调用 skill 前先读 `docs/技能简要分类.md` 分流；任何新增或修改 skill，必须同步更新该文档，并保留 `CLAUDE.md` / `Codex.md` 的入口提示。
> `/brkd`、`/load`、`docs/Alphapai/Alphapai业务拆分抓取器.md`、`docs/Alphapai/Alphapai-load核心假设参考提示词.md`、`/ka` 同属核心假设生成链路；改其中一个的骨架、门禁、业务拆分历史要求、会议 memo 或 reference/knobs 边界时，必须检查另外几个是否需要同步。同步共同骨架，不复制职责。

## 0. 一句话

MKA 是一条从 A 股财务数据到 DCF 的人机协作流水线：

```text
TuShare 原始数据
-> raw_tushare 不可变镜像
-> clean_annual / clean_quarterly 可信历史宽表
-> defaults.yaml 机器平推底座
-> 非标投研材料 markdown staging / candidate reference
-> 核心假设.md 人话判断
-> yaml1*.yaml 机器可读覆盖层
-> forecast_params.yaml 内部编译产物
-> calc.py 三表 + DCF
-> Agent/forecast/ 正式输出
```

核心分工：

- `clean.py` 负责历史数据可信。
- `defaults.yaml` 是机器平推底座，不是人工判断。
- 非标投研材料必须先 markdown 化并带状态头，再进入 `/ka` 或 `/comp` 的语义链路。
- `核心假设.md` 是人话判断层。
- `yaml1*.yaml` 是人工判断的机器可读覆盖层。
- `Agent/.modelking/forecast_params.yaml` 是编译后的逐年标准参数表，只给 `calc.py` 吃。
- `Agent/forecast/` 是唯一正式 DCF 输出目录。

## 1. Codex 新线程加载协议

如果用户说“按 MKA skill 跑”“/ka 新乳业”“/comp 002946”之类，先按这个顺序做：

1. 读本文件，建立项目地图。
2. 识别用户要用的 skill。
3. 读对应启动器：
   - `D:\MKA\.claude\skills\init\SKILL.md`
   - `D:\MKA\.claude\skills\brkd\SKILL.md`
   - `D:\MKA\.claude\skills\ka\SKILL.md`
   - `D:\MKA\.claude\skills\load\SKILL.md`
   - `D:\MKA\.claude\skills\webload\SKILL.md`
   - `D:\MKA\.claude\skills\webka\SKILL.md`（旧版兼容）
   - `D:\MKA\.claude\skills\comp\SKILL.md`
   - `D:\MKA\.claude\skills\frontend-edit\SKILL.md`
   - `D:\MKA\.claude\skills\annual-update\SKILL.md`
   - `D:\MKA\.claude\skills\da\SKILL.md`
4. 如果启动器要求动态加载执行细则，再读 `D:\MKA\skills\` 中版本号最大的对应文件。
5. 按 skill 纪律执行；不要靠记忆猜。

`D:\MKA\.claude\skills` 是启动器层，`D:\MKA\skills` 是可迭代执行细则层。

### 1.1 Claude skill 在 Codex 里的实际用法

这些 skill 原生写给 Claude Code，但 Codex 可以直接按项目协议执行。关键是不要把 `/ka`、`/comp` 当成 Codex 内置命令；它们是 **MKA 的任务路由标签**。

当用户说 `/ka 新乳业`、`/comp 002946`、`/annual-update 影石创新` 时，Codex 应该：

1. 把斜杠词识别为 MKA skill 名称，而不是 shell 命令。
2. 先读 `D:\MKA\Codex.md` 和 `D:\MKA\docs\技能简要分类.md` 做分流。
3. 再读对应启动器 `D:\MKA\.claude\skills\{skill}\SKILL.md`。
4. 若启动器要求动态 runbook，就扫描 `D:\MKA\skills\`，读取版本号最大的匹配文件，例如 `yaml1compiler_v*.md`、`业务预理解器_skill_v*.md`、`模型装载器_skill_v*.md`。
5. 按启动器和 runbook 执行：解析公司目录、检查门禁、调用 `py -m src.*` 或编辑规定产物。
6. 汇报时固定说清楚：读了什么、写了什么、停过或通过了哪些门禁、跑了什么验证、产物在哪里。

因此，用户可以直接下令：

```text
/init 新乳业
/brkd 新乳业
/ka 重建 新乳业
/comp 002946
/adj quick 新乳业 把毛利率上调 0.5pct
/annual-update 新乳业
```

Codex 不需要用户解释 Claude slash command 的内部细节；Codex 的责任是每次从本地 `Codex.md`、`.claude/skills/{skill}/SKILL.md` 和最新版动态 runbook 恢复执行状态。

### 1.2 Markdown staging 层

MKA 的本质不是让模型直接读 raw 投研材料，而是把非标材料不断转成可信 markdown，再让 `/ka` 分级裁决。

```text
raw PDF / Word / Excel / 网页 / 年报
-> markdown存储区、load 沙箱、WEBCLAUDE 打包或 factpack
-> Agent业务讨论.md / 核心假设参考*.md / Alphapai 参考稿
-> /ka 裁决后的 official 核心假设.md
-> /comp 翻译出的 yaml1
```

`公司判断和最新观点.md`、`重要文件/` 顶层材料和 `Skills素材包/最高权重材料-放Agent最应对齐的材料/` 顶层材料共同叫**同权重判断材料**；文件夹名保留“最高权重材料”，但它不压过分析师手写 thesis 或 `重要文件/`。

中间 markdown 要看抬头状态：`draft`、`reference`、`model-extracted`、`factpack/reference` 都只供 `/ka` 裁决；只有公司根目录、`状态: official` 的 `核心假设.md` 才能被 `/comp` 当作 official forecast 源文。

新的候选 markdown 必须带 `## 待 /ka 裁决清单`。它是 reference 晋升 official 的会议议程：`/ka` 逐条裁成采纳、收纳、缺口或丢弃；不能靠改名、复制到根目录或补 `knobs` 直接晋升。

## 2. 项目第一原则

TuShare 数据缺口要用年报证据补干净。

年度 hard check 失败通常说明 TuShare 漏了明细。正确动作不是手工 plug，也不是把失败改成成功，而是：

```text
annual_report_reconciler.py / recon_subagent_bridge
-> 从年报 Markdown 找证据
-> 写 approved override / restatement exemption
-> 重跑 clean.py
```

硬纪律：

- `raw_tushare` 永不修改。
- 年报补数只进 clean 年度宽表和审计表。
- `clean_adjustments` / `clean_warnings` 必须可追溯。
- 年度失败不能用季度 QA plug 兜底。
- `init` exit 3 不能静默改判成功。
- 2010 年前硬失败走项目定义的降级入库闸门，不做年报核对。

## 3. 目录地图

每家公司是一个工作台：

```text
companies/{公司名}_{代码}/
  公司判断和最新观点.md
  Agent业务讨论.md
  {公司名}-{YYYYMMDD}-核心假设.md
  active_vore/
    核心假设生成（模型放在这里）/
    业务理解器（研报和纪要放在这里）/
  WEBCLAUDE/
    核心假设部分/
    yaml1编译部分/              # 历史目录；webcomp 已废弃
  公告/
    年报/
    季报/
    临时公告/
  研报/
  纪要/
  收集/
  重要文件/
  内部报告/
  Agent/
    data.db
    defaults.yaml
    financial_expense.yaml
    yaml1*.yaml
    da_schedule.yaml
    forecast/
    recon/
    Logs/
    OfficialBreakdowns/
    KAhistory/
    DAhistory/
    .modelking/
```

根目录只放高频人工工作件和材料入口。`Agent/` 是程序产物区，不是外部模型仓库。

重要位置：

- `公司判断和最新观点.md`：分析师 thesis，`/ka`、`/brkd`、`/da`、`annual-update` 都要优先尊重。
- `active_vore/核心假设生成（模型放在这里）/`：`/ka` 读外部模型。
- `active_vore/业务理解器（研报和纪要放在这里）/`：`/brkd` 读研报/纪要。
- `Agent/data.db`：raw + clean + audit。
- `Agent/defaults.yaml`：机器平推底座。
- `Agent/yaml1*.yaml`：compiler 输出。
- `Agent/.modelking/`：内部编译缓存，非人工维护界面。
- `Agent/forecast/`：唯一正式预测和 DCF 输出。

## 4. 数据到 DCF 主流程

### 4.1 数据层

```text
py -m src.init <公司>
```

`src.init` 编排：

1. `data_fetcher.py` 拉 TuShare 三表，写 `Agent/data.db/raw_tushare`。
2. `report_downloader.py` 下载年报/季报 PDF 和 Markdown。
3. `business_breakdown_extractor.py` 抽官方收入拆分。
4. `clean.py` 透视成 `clean_annual` / `clean_quarterly` 并做 hard check。
5. `annual_report_reconciler.py` 必要时从年报补缺口。
6. `financial_expense_analyzer.py` 生成 `Agent/financial_expense.yaml`。
7. `defaults_gen.py` 可从 clean 数据生成 `Agent/defaults.yaml`。

### 4.2 建模层

```text
研报/纪要 -> markdown staging -> /brkd -> Agent业务讨论.md
Excel 模型 -> load 沙箱 markdown -> /load -> 核心假设参考load_*.md
同权重判断材料 + 候选理解 + /init 事实 -> /ka -> 核心假设.md
核心假设.md + defaults.yaml -> /comp -> yaml1*.yaml
```

关键边界：

- `/brkd` 是读懂业务，不拍最终旋钮。
- `/load` 是旧 Excel 模型 load-vintage 装载，不用后验材料补当前判断。
- `docs/Alphapai/Alphapai业务拆分抓取器.md` 是网页端业务拆分 factpack 产物，只抓历史，不写预测。
- `docs/Alphapai/Alphapai-load核心假设参考提示词.md` 是网页端数据库 reference 产物，不是 official。
- `/ka` 是唯一裁决器：把候选 markdown 和同权重判断材料裁成 official 人话核心假设，不写 yaml1。
- `/comp` 是翻译器和信息保全闸，不做投资判断。
- `/comp` 回执固定看六段：A 类覆盖、B 类保全、路径待核、语义待核、主动覆盖回读、Forecast 状态。audit 不干净时只留 reference yaml1，不覆盖 official forecast。

核心假设生成类技能同步纪律：

- 同链路技能：`/brkd`、`/load`、`docs/Alphapai/Alphapai业务拆分抓取器.md`、`docs/Alphapai/Alphapai-load核心假设参考提示词.md`、`/ka`。
- 骨架要相似：时间边界/材料边界、业务拆分历史、收入→毛利→费用→below-OP→terminal 的段序、会议 memo、reference/draft/official 状态、`knobs` 同源边界。
- 分工不能串：`/brkd` 读研报/纪要和 `/init` 事实产 draft；`/load` 只还原模型当时的公式层和历史原子；Alphapai业务拆分抓取器只抓用户指定主拆分、桥表和高价值辅助拆分历史 factpack；Alphapai-load 产 reference 并承接 factpack；`/ka` 裁决候选生成 official；`/comp` 只把 official 源文无损翻译成 yaml1。改一处时同步检查另外几处，但不要让它们互相污染职责。
- 候选产物同步检查 `待 /ka 裁决清单`：BRKD、LOAD、Alphapai factpack/reference 都要把未决事项显式列出来，供 `/ka` 裁决时逐项销账。

### 4.3 DCF 层

正式入口：

```text
py -m src.forecast --ticker 002946.SZ
```

`forecast.py` 做：

1. 定位公司目录。
2. 找 `Agent/defaults.yaml` 和最新 `Agent/yaml1*.yaml`。
3. 调 `yaml1_cleaner.py` 做 fold / expand / resolve / backtest。
4. 写 `Agent/.modelking/forecast_params.yaml`。
5. 可选检测 `Agent/da_schedule.yaml` 并注入 `da_series`。
6. 调 `calc.py` 生成预测三表和 DCF。
7. 写 `Agent/forecast/`。

`calc.py` 永远不直接读 yaml1，也不直接读 defaults。它只吃 `forecast_params.yaml` 这种逐年标准参数表。

## 5. Skills 速查

### `/init`：数据初始化/刷新

入口：

```text
D:\MKA\.claude\skills\init\SKILL.md
```

用途：

- 新公司入库。
- 刷新年报/季报数据。
- 生成或更新 `Agent/data.db`、年报 Markdown、财务费用档案。

产物：

- `Agent/data.db`
- `公告/年报/*.pdf` / `*.md`
- `公告/季报/*.pdf` / `*.md`
- `Agent/financial_expense.yaml`
- `Agent/OfficialBreakdowns/`

纪律：

- exit 3 不改判成功。
- raw_tushare 永不手改。
- 年度 hard check 失败先走 reconciler / subagent 证据闭合。

### `/brkd`：业务预理解

入口：

```text
D:\MKA\.claude\skills\brkd\SKILL.md
```

动态细则：

```text
D:\MKA\skills\业务预理解器_skill_v*.md
```

用途：

- 在没有完整 Excel 模型、业务线复杂、研报纪要很多时，先读懂业务。
- 把研报/纪要消化成 `Agent业务讨论.md`，供 `/ka` 使用。

输入：

- `公司判断和最新观点.md`
- `active_vore/业务理解器（研报和纪要放在这里）/`

产物：

- 公司根目录 `Agent业务讨论.md`

纪律：

- 不直接读 PDF；先转 Markdown。
- 研报是线索，不是权威。
- 只处理收入/业务线预理解，不拍最终 DCF 旋钮。

### `/ka`：核心假设生成/修改

入口：

```text
D:\MKA\.claude\skills\ka\SKILL.md
```

动态细则：

```text
D:\MKA\skills\核心纪律_skill_v*.md
D:\MKA\skills\核心假设源语言_skill_v*.md
D:\MKA\skills\核心假设编辑器_skill_v*.md
```
（旧 v19 `04_核心假设生成修改器_skill_v19.md` 已归档至 `deprecatedlogs/`,不再加载。）

用途：

- 生成或重建 `核心假设.md`。
- 把同权重判断材料、候选理解、年报事实和业务讨论开会成一份 official 人话底稿。

输入：

- `公司判断和最新观点.md`
- `active_vore/核心假设生成（模型放在这里）/`
- 最新年报 Markdown
- 可选 `Agent业务讨论.md`
- modify 模式下的旧 `*核心假设*.md`

产物：

- 公司根目录 `{公司}-{YYYYMMDD}-核心假设.md`
- 旧稿归档到 `Agent/KAhistory/`

纪律：

- 必须先读 `公司判断和最新观点.md`。
- 只认公司根目录的 `*核心假设*.md`，不递归扫 WEBCLAUDE 或历史目录。
- 产物必须落公司根目录。
- 先押再问，关键旋钮拍板后再落盘。
- `/ka` 不写 yaml1，不算 DCF。
- `/ka` 只读 markdown 化后的材料层；raw Excel 交 `/load`，raw 研报/纪要交 `/brkd`。

模型建议：

- `/ka` 仍然复杂，但真正需要网页端强模型理解力的是 `/load`。
- `/load` 是开了时间沙箱的 `/ka`：模型自身历史末年和预测起点最高优先，后验年报/clean 数据不能污染旧模型。
- GLM5.2 建议开 MAX 模式；国内中转站比较多，原生 Claude Code 配 Opus 4.8 high/xhigh 或直接上 Fable 效果最好。
- 网页版完全可平替，推荐先用 `/webload` 打包给网页端跑 `/load`。

### `/load`：旧模型 vintage 装载

入口：

```text
D:\MKA\.claude\skills\load\SKILL.md
```

用途：

- 把 active_vore 中的旧 Excel 模型按它自己的时间轴装入 `Agent/Load/{load_id}/`。
- 若模型历史止于 2024A、预测从 2025E 开始，则 2025 年报和 2025 clean 数据都属于未来信息泄漏。
- 尽量继承 `/ka` 的交互：先讲模型理解 overview，用户确认后，再按收入、毛利、费用、below-OP 与税、中期分段先押再问。

命令：

```text
py -m src.model_load prepare 影石创新 --overwrite
```

产物：

- `Agent/Load/{load_id}/model_boundary.*`
- `Agent/Load/{load_id}/allowed_materials/`
- `Agent/Load/{load_id}/forbidden_materials.md`
- `Agent/Load/{load_id}/核心假设_load.md`

纪律：

- 用户确认 overview 前，不补完假设。
- 只读沙箱 allowed materials；禁读清单只作边界，不打开正文。
- `/load` 止于核心假设参考 markdown，不编译 yaml1、不跑 DCF；load 结果不是当前正式 forecast，不覆盖 `Agent/forecast/`。
- reference/draft/model-extracted/factpack 都要保留 `待 /ka 裁决清单`；缺这节的旧 reference 只能由 `/ka` 在 overview 里补成议程后裁决。

### `/webload`：网页端 load 打包

入口：

```text
D:\MKA\.claude\skills\webload\SKILL.md
```

用途：

- 强烈推荐在跑 `/load` 前使用。
- 先本地 prepare 锁时间边界，再把网页端执行 `/load` 需要的材料打包到 `WEBCLAUDE/模型装载部分/`。

命令：

```text
py -m src.webload 影石创新 --overwrite
```

产物：

- `Agent/Load/{load_id}/`
- `WEBCLAUDE/模型装载部分/`

纪律：

- 纯打包，不生成、不修改、不编译。
- 每次清空旧包再重建。
- 网页端只读 `allowed_materials/`，不得打开 `forbidden_materials.md` 中列出的正文。
- 网页端生成 `核心假设_load.md` 后放回 `Agent/Load/{load_id}/` 与 KA 参考稿区，`/load` 到此为止；转正式另走 `/ka` → `/comp`。
- `/webka` 仅保留旧版普通 `/ka` 网页打包兼容，不再作为强烈推荐入口。

### `/comp`：yaml1 编译 + DCF

入口：

```text
D:\MKA\.claude\skills\comp\SKILL.md
```

动态细则：

```text
D:\MKA\skills\yaml1compiler_v*.md
```

用途：

- 把 `核心假设.md` 忠实翻译成 `yaml1_公司_YYYYMMDD.yaml`。
- yaml1 落盘后立即跑 DCF。

输入四件套：

- 最新 `*核心假设*.md`
- `Agent/defaults.yaml`
- `docs/数据格式参考.md`
- `docs/yaml1算法模板契约.md`

产物：

- `Agent/yaml1_公司_YYYYMMDD.yaml`
- `Agent/.modelking/forecast_params.yaml`
- `Agent/.modelking/yaml1_clean_report.json`
- `Agent/forecast/`

纪律：

- 先过年份门禁；如果核心假设已被最新实际年覆盖，停止并提示 `/annual-update`。
- compiler 是翻译器，形变照翻、歧义举旗。
- 信息保全闸先于 DCF：A 类进入计算覆盖，B 类进入 history/stash/display，歧义进入待核清单。
- `defaults.yaml` 是目标命名空间，不是输入假设。
- yaml1 落盘即主成功；DCF 失败要明示，但不回滚 yaml1。

### `/frontend-edit`：前端试算定点回写

入口：

```text
D:\MKA\.claude\skills\frontend-edit\SKILL.md
```

用途：

- 前端工作台已经试算完，吐出“进入前端编辑模式”的 prompt。
- Codex 按 diff 定点 patch `核心假设.md` 的正文预测行和末尾 `knobs` 块。
- 然后调 `/comp` 重编 yaml1 并跑 DCF。

边界：

- 它是手术刀，不是研究员。
- 不读定调、活跃素材、年报、业务讨论。
- 不先押再问；前端试算已经代表用户拍板。
- 不直接改 yaml1。
- path 映射不上、正文与 knobs 不同源、结构性时间轴变更时停止。

### `/annual-update`：年度滚续

入口：

```text
D:\MKA\.claude\skills\annual-update\SKILL.md
```

动态细则：

```text
D:\MKA\skills\年度更新器_skill_v*.md
```

用途：

- 公司出了新年报后，把旧核心假设从历史末年 H 滚到最新实际年 A。
- 不是从零 `/ka`，也不是单纯 `/init`。

流程：

1. 读旧核心假设、定调文件、建总账。
2. 跑 `/init` 刷数据。
3. 用 `annual_update_fetcher.py` 取标准事实线和偏离诊断。
4. 进入年度更新器 skill，估算非标历史原子、重定未来。
5. `/comp` 收口。

纪律：

- 旧稿只读，另存新稿。
- init exit 3 未闭合就停。
- 拿不到的历史事实只能“估算待校准”或“待补旗”，不能静默捏造。
- 第 4 步起必须人机交互。

### `/da`：重资产折旧摊销排程

入口：

```text
D:\MKA\.claude\skills\da\SKILL.md
```

动态细则：

```text
D:\MKA\skills\da_折旧摊销排程_skill_v*.md
```

用途：

- 重资产公司专用。
- 把固定资产、在建工程、PP&E 折旧和 capex 变成可滚动排程。

产物：

- `Agent/recon/da_facts_latest.json`
- `Agent/da_schedule.yaml`

forecast 接入：

- `enabled: true` 时，`forecast.py` 读 `da_schedule.yaml`。
- `da_roll.py` 生成 `da_series`。
- `calc.py` 消费 `da_series`，PP&E 折旧和 capex 走重资产路径。
- 无 schedule / disabled / 非对齐错误外的 da_roll 异常，回退轻资产路径。

纪律：

- 轻资产公司不要用。
- 事实层和假设层分离。
- 未经用户拍板不能落 `da_schedule.yaml`。
- base_year 必须等于 defaults.base_period。

## 6. 动态执行细则目录

当前 `D:\MKA\skills` 里通常有：

```text
核心纪律_skill_v1.md
核心假设源语言_skill_v1.md
核心假设编辑器_skill_v1.md
核心假设调整器_skill_v1.md
年度更新器_skill_v1.md
业务预理解器_skill_v3.md
模型装载器_skill_v3.md
da_折旧摊销排程_skill_v1.md
yaml1compiler_v5.md
```
（旧 `04_核心假设生成修改器_skill_v19.md` 已归档至 `deprecatedlogs/`。）

使用规则：

- `/ka` 先加载 `核心纪律`+`核心假设源语言`,再动态加载最新版 `核心假设编辑器`。
- `/load` 先加载 `核心纪律`+`核心假设源语言`,再动态加载最新版 `模型装载器`。
- `/adj` 先加载 `核心纪律`+`核心假设源语言`,再动态加载最新版 `核心假设调整器`。
- `/comp` 动态加载最新版 `yaml1compiler`。
- `/annual-update` 动态加载最新版 `年度更新器`。
- `/brkd` 动态加载最新版 `业务预理解器`。
- `/da` 动态加载最新版 `da_折旧摊销排程`。

不要把动态细则复制进本文件。执行前读最新版，才能跟上项目变化。

## 7. 常用命令

```bash
# 数据
py -m src.init 新乳业
py -m src.init 002946.SZ --force-markdown
py -m src.clean --ticker 002946.SZ --mode all
py -m src.defaults_gen --ticker 002946.SZ

# 年报/研报文本
py -m src.report_downloader --ticker 002946.SZ --force-markdown
py -m src.research_pdf2md --ticker 002946.SZ

# forecast / DCF
py -m src.yaml1_cleaner --ticker 002946.SZ
py -m src.forecast --ticker 002946.SZ
py -m src.forecast --yaml1 "companies/新乳业_002946/Agent/yaml1_新乳业_20260618.yaml"

# 网页端打包
py -m src.webload 影石创新 --overwrite

# 工作台
py -m src.workbench --no-open
npm run build
```

## 8. 前端工作台

正式工作台入口：

```text
py -m src.workbench
```

默认端口：

```text
http://127.0.0.1:8765
```

前端源码：

```text
app/src/
```

配置和教程页：

```text
app/src/Tutorial.tsx
app/src/tutorialContent.ts
app/src/styles.css
```

前端改动后至少跑：

```text
npm run build
```

## 9. 常见误区

- 把 `defaults.yaml` 当最终预测参数：错，最终给 `calc.py` 的是 `forecast_params.yaml`。
- 让 `calc.py` 直接读 yaml1：错，必须经过 `yaml1_cleaner.py`。
- 在公司根目录写 `forecast_params.yaml`：错，内部产物属于 `Agent/.modelking/`。
- 在年度 hard check 失败时手工 plug：错，年度失败走年报补证据。
- 在 `/ka` 里写 YAML：错，`/ka` 只写 Markdown。
- 在 `/comp` 里重新判断业务：错，compiler 只翻译，不重做分析师工作。
- 从 `WEBCLAUDE/` 反向覆盖源材料：错，WEBCLAUDE 是可重建打包区。
- 用 `/annual-update` 从零生成核心假设：错，无旧稿时先 `/ka`。
- 轻资产公司滥用 `/da`：错，默认 capex_pct + depr_rate 够用时不要复杂化。
- 前端试算回写时直接改 yaml1：错，必须回写 `核心假设.md` 再 `/comp`。

## 10. 回答用户时的口径

当用户问“你能用这些 skills 吗？”：

可以用。对 Codex 来说，它们不是内置 slash command，而是项目内协议：

1. 用户可以直接说 `/ka 新乳业`、`/comp 002946` 这类 MKA 路由。
2. Codex 先读本文件和 `docs/技能简要分类.md`。
3. 再读 `.claude/skills/{skill}/SKILL.md`。
4. 如果需要，读 `D:\MKA\skills\*_skill_vN.md` 里版本号最大的动态 runbook。
5. 然后按协议调用脚本、读写文件、汇报结果。

所以不是靠当前对话死记，也不是让用户手动解释 Claude Code 的 slash command，而是每次从项目文档和 skill 文件恢复执行状态。
