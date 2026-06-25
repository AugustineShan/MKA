# MKA 系统架构文档

> 本文档描述 MKA 系统的**代码现状**：整体架构、模块职责、数据模型、契约注册表与关键决策。
> **每次开发完成后必须同步更新本文档。**
>
> 设计意图与职责边界见 [`ModelKing 开发文档 v2`](ModelKing_开发文档_v2%20(1).md) 与 [`理解层设计决策`](理解层_设计决策与开发方向%20(6).md)；命名双语对照见本文档附录 A。

---

## 1. 系统概览

MKA 是 A 股财务数据两阶段流水线系统：

```
TuShare Pro API
      ↓  阶段①：拉取 + 标准化 + 入库
   SQLite (raw_tushare + clean tables)
      ↓  阶段②：透视 + 校验 + 输出
   SQLite clean_annual / clean_quarterly
      ↓  clean 后事实速览
   Agent/core_metrics_overview.md/json/csv
      ↓  YAML2 defaults_gen.py
   defaults.yaml（YAML2：机器平推底座）
      +  yaml1*.yaml（compiler 输出：人的判断覆盖层）
      ↓  forecast.py（内部调用 yaml1_cleaner.py + calc.py）
   Agent/forecast/ 三表 + DCF summary
```

同时提供一个独立的公告下载入口：通过巨潮资讯网 cninfo `hisAnnouncement/query`
接口查询上市公司年度报告公告，并批量下载中文年度报告 PDF，同时用 PyMuPDF 提取全文 Markdown。

**核心目标**：从 TuShare 拉取原始三表数据，经严格配平校验后写入可信赖的年度/季度清洗表；在 clean 数据之上生成无主观预测的 YAML2 默认参数，并把 compiler 产出的 `yaml1` 判断覆盖层清洗成标准参数后跑出会计配平的 DCF 预测三表。任何一条历史 hard check 不通过即停止，年度/季度残差均必须 < 1 百万元；预测阶段 BS/CF 会计恒等式不配平也必须失败。

**边界**：仅处理 A 股一般工商业（comp_type=1）财报数据，不覆盖金融企业、港股美股或行情 K 线。`defaults.yaml` 是唯一 YAML2，表示“什么都不变会怎样”的机器平推底座；`yaml1` 是稀疏判断覆盖层，`calc.py` 永远看不到 yaml1，只吃清洗后的标准参数。

**建模技能管线**：取数流水线之外，业务理解层由多个 skill 协同，而不是一个 Agent 通吃。`/load` 只读 `Skills素材包/LOAD外部EXCEL模型理解器（一次最多一个）/` 的唯一 Excel，产出 `Agent/Load/{load_id}/{原Excel文件名}_核心假设.md`；`/brkd` 只读 `Skills素材包/BRKD业务理解器（研报和纪要放在这里）/markdown存储区/`，产出 `Agent业务讨论.md`；`/ka` 裁决最高权重材料、BRKD、LOAD 和 `/init` 校验层，生成正式 `核心假设.md`；`/comp` 忠实翻译为 `yaml1` 并跑 forecast。已有正式稿的调整交给 `/adj` 或 `/annual-update`。

---

## 2. 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                       外部数据源                              │
│  TuShare Pro API (official endpoint only)                    │
│  endpoints: income / balancesheet / cashflow /               │
│             daily_basic / stock_basic / trade_cal            │
│                                                             │
│  巨潮资讯网 cninfo                                           │
│  endpoints: topSearch/query / hisAnnouncement/query / PDF    │
└──────────┬──────────────────────────────────────────────────┘
           │ HTTP (限速 0.8s/请求)
           ▼
┌─────────────────────────────────────────────────────────────┐
│  阶段①  data_fetcher.py                                     │
│                                                             │
│  TushareDataFetcher                                         │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐ │
│  │ API 调用层    │  │ 数据转换层     │  │ 入库与校验层     │ │
│  │              │  │               │  │                  │ │
│  │ _call_api()  │  │ convert_value │  │ validate_records │ │
│  │ 限速/重试    │  │ 单位标准化    │  │ _before_write()  │ │
│  │ 错误分类     │  │ 官方字段镜像   │  │ run_quality_     │ │
│  │              │  │ 去重排序      │  │ checks()         │ │
│  └──────┬───────┘  └──────┬────────┘  └────────┬─────────┘ │
│         │                 │                     │           │
│         └────────────┬────┘                     │           │
│                      ▼                          ▼           │
│               records_for_             SQLite UPSERT        │
│               tushare_mirror()          + 事务保护/回滚       │
└──────────────────────┬──────────────────────────────────────┘
                       │ 写入
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  存储层  SQLite (data.db)                                    │
│                                                             │
│  ┌──────────────────────────────┐ ┌──────────────────────┐ │
│  │raw_tushare                   │ │meta                  │ │
│  │PK:(ticker, endpoint,         │ │PK:key                │ │
│  │    report_type, end_date,    │ │                      │ │
│  │    field)                    │ │                      │ │
│  └──────────────────────────────┘ └──────────────────────┘ │
└──────────────────────┬──────────────────────────────────────┘
                       │ 读取
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  阶段②  clean.py                                            │
│                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐ │
│  │ 数据读取层    │  │ 透视与合并层   │  │  校验引擎层      │ │
│  │              │  │               │  │                  │ │
│  │ load_raw_    │  │ dedupe_by_    │  │ check_is()       │ │
│  │  tushare()   │  │  f_ann_date() │  │ check_bs()       │ │
│  │              │  │               │  │ check_cf()       │ │
│  │ 过滤:        │  │ pivot_to_     │  │ check_is_        │ │
│  │  report_type │  │  wide()       │  │  supplement()    │ │
│  │  comp_type   │  │               │  │ check_cross_     │ │
│  │              │  │ 跨端点消歧    │  │  table()         │ │
│  │              │  │ resolve()     │  │ check_soft()     │ │
│  └──────────────┘  └──────┬────────┘  └────────┬─────────┘ │
│                           │                     │           │
│                           ▼                     ▼           │
│                    宽表 DataFrame        31条校验结果         │
│                    (行=年份,列=字段)     25硬 + 6软          │
│                           │                     │           │
│                           └──────────┬──────────┘           │
│                                      ▼                      │
│                         SQLite clean_annual /               │
│                         clean_quarterly                     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  年报 PDF + Markdown 下载  report_downloader.py              │
│                                                             │
│  ticker → cninfo topSearch 获取 orgId → hisAnnouncement/query │
│  查询 category_ndbg_szsh → 标题过滤 → 下载 static PDF        │
│                                                             │
│  输出: companies/{公司名}_{代码}/公告/年报/{年份}_年度报告.pdf/md│
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 模块职责

### 3.0 init.py（一键编排入口）

`init.py` 是给 Agent / 人的单一入口，把 data_fetcher → report_downloader → clean →
core_metrics_overview → financial_expense_analyzer 五个独立阶段按正确顺序编排成全流程，并保证幂等与如实上报。配套
`.claude/skills/init/SKILL.md` 让 Agent 用 `init <公司>` 触发。

| 组件 | 职责 |
|------|------|
| `resolve_ticker()` | 公司名 / 裸代码 / 完整 ticker → 规范 ticker；中文名经 TuShare `stock_basic` 解析，歧义/无匹配抛 `TickerResolutionError`（退出码 2，交 Agent 用 websearch 兜底） |
| `stage_fetch()` | 阶段①拉取；幂等：当日 `meta.last_updated` 已是今天则跳过（除非 `--force`），否则 UPSERT 增量 |
| `stage_reports()` | 年报 PDF/Markdown 下载（**必须在 clean 之前**，否则失败时 reconciler 无年报可切片）；report_downloader 自身幂等，下载失败不致命 |
| `stage_clean()` | 阶段③清洗校验，含"年度失败→生成 override→重跑应用"两段式；用 `approved_override_count()` 比对前后判断是否新增补数 |
| `stage_core_metrics_overview()` | 阶段④：从 `clean_annual` 覆盖生成 `Agent/core_metrics_overview.md/json/csv` 年度事实速览；只读 clean 历史，不读 forecast/yaml，不阻塞管线 |
| `stage_financial_expense()` | 阶段⑤：从年报附注切片「财务费用」明细，LLM 拆出利息支出/资本化利息/财政贴息/利息收入/其他，按年份归档到 `financial_expense.yaml`；失败只 warning，不阻塞管线 |
| `build_report()` | 输出数据拉取报告：五阶段状态 + 年度/季度期数 + `clean_adjustments`（年报确认补全科目）+ `clean_warnings` 汇总 |

**编排链路**：
```
输入 → resolve_ticker → stage_fetch → stage_reports → stage_clean
                                                          ├─ 首跑过 → stage_core_metrics_overview → stage_financial_expense → 退出码 0
                                                          └─ 年度失败 → reconciler 生成 override
                                                               → 重跑 clean 应用补数
                                                                    ├─ 过 → stage_core_metrics_overview → stage_financial_expense → 退出码 0
                                                                    └─ 仍失败 → 退出码 3（真问题，如实上报）
```

**退出码语义**：

| 码 | 含义 | Agent 应做 |
|----|------|-----------|
| 0 | 全链路成功（纯 TuShare 或经年报确认补全后通过） | 转述数据拉取报告 |
| 2 | 输入无法解析为唯一 ticker | websearch 查代码后重传完整 ticker |
| 3 | 应用年报补数后仍年度硬校验失败（真数据问题） | 停下如实上报，不静默放行 |
| 1 | API/网络/鉴权等异常 | 报错并提示检查 `.env`/网络 |

**纪律**：失败的 clean 运行不改判成功；override 只在重跑时应用；`raw_tushare` 永不被修改；
`financial_expense_analyzer` 只写 evidence，YAML2 合并归 `defaults_gen.py` 所有。
批量由 Agent 多次调用或 `python -m src.init A B C`，严重度取 max（3>2>1>0）。
Windows 控制台 GBK 下强制 UTF-8 输出以兼容报告中的 emoji。

**CLI**：
```bash
python -m src.init 美的集团          # 中文名
python -m src.init 000333            # 裸代码
python -m src.init 000333.SZ 600519.SH   # 批量
python -m src.init 美的集团 --force  # 全量重拉并重跑财务费用分析
```

### 3.0a webka.py（已废弃）

`/webka` 已从 active skills 中移除，旧入口说明留档于：

```text
D:\MKA\deprecatedlogs\webka\SKILL.md
```

当前网页端重活只保留 `/webload`：旧 Excel 模型 vintage 保存必须先锁时间沙箱，再在网页端完成模型理解 overview 和分段确认。普通 `/ka` 现在是本地全量裁决器，直接读取最高权重材料、BRKD、LOAD 和 `/init` 校验层，不再提供网页端打包入口。

### 3.0b webload.py（网页端 load vintage 打包器）

`webload.py` 是 `/load` 的网页端打包器。它先调用 `src.model_load.prepare` 创建 `Agent/Load/{load_id}/`，锁定外部 Excel 模型的历史末年、预测起点和显式预测期；然后把网页端执行 `/load` 需要的安全材料复制到 `companies/{公司}/WEBCLAUDE/模型装载部分/`。

与 `/load` 的区别：
- `/load` 是真正的模型装载流程，按 `/ka` 的会议纪律先 overview、再分段确认、最后写 `{原Excel文件名}_核心假设.md`。
- `/webload` 只负责 prepare + 打包，不替用户理解模型、不生成核心假设、不编译 yaml1、不跑 DCF。

**复制清单**：

| 文件/目录 | 来源 | 用途 |
|---|---|---|
| `00_webload_网页端执行说明.md` | `src.webload` 生成 | 网页端第一阅读入口 |
| `01_load启动器_SKILL.md` | `.claude/skills/load/SKILL.md` | `/load` 启动器纪律 |
| `02_model_boundary.md` | `Agent/Load/{load_id}/model_boundary.md` | 人读时间边界 |
| `03_model_boundary.json` | `Agent/Load/{load_id}/model_boundary.json` | 机器可读时间边界 |
| `04_forbidden_materials.md` | `Agent/Load/{load_id}/forbidden_materials.md` | 禁读清单，只可看清单 |
| `05_{原Excel文件名}_核心假设_脚手架.md` | `Agent/Load/{load_id}/{原Excel文件名}_核心假设.md` | 网页端补写目标 |
| `06_核心假设生成修改器_skill_vN.md` | `D:\MKA\skills\` 最新版 | 继承 `/ka` 会议流程 |
| `07_模型装载器_skill_vN.md` | `D:\MKA\skills\` 最新版 | load 时间沙箱覆盖层 |
| `08_load_manifest.json` | `Agent/Load/{load_id}/load_manifest.json` | 沙箱路径和材料清单 |
| `09_defaults.yaml` | `Agent/Load/{load_id}/defaults.yaml` | 沙箱 base_period 和平推底座，可缺省 |
| `allowed_materials/` | `Agent/Load/{load_id}/allowed_materials/` | 网页端唯一可读正文材料 |

**关键纪律**：
- `model_load.prepare` 报时间轴冲突则停止，不打包。
- 网页端不得读取 `forbidden_materials.md` 中列出的正文材料。
- 网页端用户确认 overview 前，不补完 `{原Excel文件名}_核心假设.md`。
- 网页端产出的 `{原Excel文件名}_核心假设.md` 放回 `Agent/Load/{load_id}/` 后，本地继续编译 `yaml1_load_*.yaml` 并运行 `py -m src.model_load dcf`。

**CLI**：
```bash
python -m src.webload 影石创新 --overwrite
python -m src.webload 688775 --overwrite
python -m src.webload 688775.SH --overwrite
```

配套 skill 文件：
- `D:\MKA\.claude\skills\webload\SKILL.md`
- `D:\MKA\.claude\skills\load\SKILL.md`

### 3.0c `/comp` skill（yaml1 compiler 启动器）

`/comp` 是 `/ka` 的 compiler 兄弟。它不负责生成 `核心假设.md`，而是把已有的 `核心假设.md` 编译成机器可读的 `yaml1_公司名_YYYYMMDD.yaml`，供 `forecast.py` 使用。

**执行顺序**（必须遵守）：
1. 解析公司目录。
2. **先动态加载最新版 `yaml1compiler` skill**：扫描 `D:\MKA\skills\`，匹配 `yaml1compiler_v*.md`，取版本号最大。
3. 再读取四份输入材料：
   - `companies/{公司}/*核心假设*.md` 最新一份（语义层：判断、历史、旋钮、时间轴、覆盖项）
   - `companies/{公司}/Agent/defaults.yaml`（目标命名空间）
   - `docs/数据格式参考.md`（中文科目 ↔ TuShare 字段字典）
   - `docs/yaml1算法模板契约.md`（cleaner/calc 支持的算法模板硬边界）
4. 按加载到的 compiler skill 执行编译。
5. 输出：`companies/{公司}/Agent/yaml1_公司名_YYYYMMDD.yaml`。

**关键纪律**：
- 所有 skill 均不读取 PDF。
- `defaults.yaml` 是目标命名空间，compiler 只把 `核心假设.md` 的覆盖项落到 `defaults.yaml` 已有的真实路径上。
- `docs/数据格式参考.md` 和 `docs/yaml1算法模板契约.md` 是只读契约，compiler 不能改写。

**退出码语义**：

| 码 | 含义 |
|----|------|
| 0 | 编译成功 |
| 2 | 输入无法解析为唯一公司目录 |
| 3 | 缺少 `核心假设.md` 或 `defaults.yaml` |
| 1 | compiler 执行异常或其他 IO 错误 |

配套 skill 文件同时部署于：
- `D:\MKA\.claude\skills\comp\SKILL.md`
- `C:\Users\Sheld\.claude\skills\comp\SKILL.md`

### 3.1 data_fetcher.py（阶段①）

| 组件 | 职责 |
|------|------|
| `TushareDataFetcher` | 核心拉取类，管理客户端、限速、缓存 |
| `create_tushare_client()` | 初始化 TuShare SDK 客户端，并校验官方 TuShare URL |
| `convert_value()` | 单位转换（元→百万元、%→小数、万股→百万股等） |
| `official_statement_mappings()` | 从官方文档解析完整字段映射（缓存） |
| `official_doc_fields()` | 解析 `D:\MKA\TushareOfficialAPIMD\*.md` 获取字段元数据 |
| `records_for_tushare_mirror()` | 原始全字段镜像（完整性校验基准） |
| `filter_and_dedupe_statement()` | 过滤 report_type/comp_type + 去重 |
| `dedupe_by_period()` | 按报告期去重（update_flag → f_ann_date → ann_date） |
| `validate_records_before_write()` | 入库前硬健康检查（raw_tushare 非空/主键无重复/ticker一致/字段覆盖/核心字段非空/meta完整） |
| `run_quality_checks()` | 基于 raw_tushare 的 BS 配平与 CF 勾稽校验 |

**公开 API**：
```python
fetch_company("600519.SH", force_refresh=False) -> str   # 返回 SQLite 路径
fetch_companies(["600519.SH", "300866.SZ"]) -> dict       # 批量拉取
```

**CLI**：`python -m src.data_fetcher --ticker 300866.SZ [--force] [--verbose]`

### 3.2 clean.py（阶段②）

| 组件 | 职责 |
|------|------|
| `load_raw_tushare()` | 读取 EAV；年度取 report_type=1，季度取 income report_type=2 + BS/CF report_type=1 |
| `dedupe_by_f_ann_date()` | 同 (endpoint, end_date, field) 取 f_ann_date 最晚 |
| `pivot_to_wide()` | EAV→内存宽表（325官方字段+6 QA plug），跨端点同名字段加前缀消歧 |
| `split_cashflow_quarterly()` | 季度模式：CF 流量字段从累计值拆为单季（Q2=H1−Q1, Q3=Q3−H1, Q4=Annual−Q3），并修正 beg_period |
| `resolve()` | 合并科目处理（拆分项全在→求和；否则用合并项；否则 0） |
| `is_bucket_sum()` / `bs_bucket_sum()` | 按字段分类自动 bucket 求和（含 combo/derived/sub_item 处理） |
| `check_is()` | 利润表硬校验 IS 1.1–1.6 |
| `check_bs()` | 资产负债表硬校验 BS 2.1–4.3 |
| `check_cf()` | 现金流量表硬校验 CF 5.1–5.5 |
| `check_is_supplement()` | IS 补充校验 6.1–6.3（年度硬校验，季度 warning） |
| `check_cross_table()` | 跨表硬校验 7.1 |
| `check_soft()` | 软校验 7.2–7.3 + 10.1–10.4 |
| `clean_all()` | 同时生成并写入 SQLite `clean_annual` / `clean_quarterly` |

**公开 API**：
```python
clean("path/to/Agent/data.db", "300866.SZ") -> pd.DataFrame
```

**CLI**：`python -m src.clean --ticker 300866.SZ [--db path] [--verbose]`

#### 3.2.1 会计系统（field_registry）—— 唯一真源

三表 325 字段的会计元数据(分类/会计序/标签/resolve/sign/role)统一在 `src/field_registry.yaml`。clean.py 校验分类、workbench 渲染排序/标签、`docs/数据格式参考.md` 三处同源。**改字段分类/排序/标签只编辑该 YAML,详见 `docs/会计系统.md`(改会计科目必读)。** 边界:check_* subtotal 公式留代码(B1);known_tushare_defects 独立;6 个 qa_*_plug 不在 registry。

#### 3.2.2 Workbench 三表展示层（Investor Presentation View）

`field_registry` 是数据工程/清洗真源，不等于投资人页面的默认展示全集。Workbench 的“完整三表”在 `_statement_rows()` 给每一行补展示元数据：

- `display_role`: `primary` / `technical` 等展示角色。
- `is_technical`: 标记 combo、derived、sub_item、qa_* 等技术口径字段。
- `combo_of`: combo 字段对应的拆分项列表，来自 `field_registry.yaml`。
- `display_label`: 当 combo 作为 fallback 展示时去除 `(合计)(元)` 等源系统尾缀。

前端默认展示 `primary + metric` 的投资阅读口径，隐藏 `technical` 字段；只有打开“显示技术口径”时才展示 combo/derived/sub_item 等底层字段。combo 字段的展示规则是互斥的：若拆分项存在且有有效值，主表展示拆分项并隐藏 combo；若拆分项缺失或全为 0，而 combo 有值，则用 combo 作为 fallback 展示，并使用投资人友好的 `display_label`。这样保留底层追溯能力，同时避免在 BS 主表同时出现“在建工程”和“在建工程(合计)(元)”这类重复口径。

### 3.3 report_downloader.py（年报/季报 PDF + Markdown 下载）

| 组件 | 职责 |
|------|------|
| `parse_ticker()` | 校验并解析 `000333.SZ` / `600519.SH` / `430047.BJ` |
| `fetch_company_info()` | 调用 cninfo `topSearch/query` 获取公司简称与 `orgId` |
| `iter_company_category()` | 复用 vendored `cninfo.api.query_page()` 翻页查询指定 category 的公告 |
| `parse_report()` | 标题过滤，匹配年报/一季报/半年报/三季报本体；`年+` 容忍 cninfo 录入重复"年"字（如三一 2020 `2020年年年度报告`），版本尾缀白名单（全文/正文/修订版/更正版/更新版/取代版/正式版/最终版，裸写或全半角括号）+ `$` 锚定容忍正文版本变体同时挡住非正文尾串；修订类（修订版/更正版/更新版/取代版）→ `_修订版` 命名；排除摘要、补充公告/更正公告/更新公告、取消、英文、审计/内控/鉴证/提示性公告等非正文（用完整短语而非裸"更新/更正"，避免与"更新版/更正版"正文版本相撞） |
| `collect_reports()` | 对多个 cninfo category 分别查询；按 category 检测漏匹配（若某 category 返回了公告但 0 条匹配成功，或存在疑似定期报告本体却未被匹配，则输出 warning）；合并去重时优先保留 `全文` 而非 `正文`，按年份从新到旧排序。`main()` 在 `collect_reports()` 之后按 `--min-year` 丢弃该年之前的报告（2010 闸门，与 `clean.RECONCILE_MIN_YEAR` 对齐），不下载、不抽 Markdown |
| `render_markdown()` | 复用 vendored `cninfo.parser` 的 PyMuPDF 能力，从 PDF 提取全文 Markdown |
| `download_reports()` | 下载 PDF 并生成 Markdown；年报放 `公告/年报/`，季报放 `公告/季报/{year}/`；`--all-reports` 时年报+季报共用单一线程池（`quarterly_target_dir` 按 kind 分流目录），目标文件已存在则跳过 |

**CLI**：
```bash
python -m src.report_downloader --ticker 000333.SZ                    # 只下载年报（默认）
python -m src.report_downloader --ticker 000333.SZ --quarterly        # 只下载季报
python -m src.report_downloader --ticker 000333.SZ --all-reports      # 年报 + 季报
python -m src.report_downloader --ticker 000333.SZ --list-only        # 只列出匹配报告
python -m src.report_downloader --ticker 000333.SZ --min-year 2010    # 只下 2010 及以后（默认）
```

**2010 闸门**：`--min-year` 默认 `DEFAULT_MIN_REPORT_YEAR=2010`，与 `clean.RECONCILE_MIN_YEAR` 对齐——2010 前年报/季报披露稀疏、reconciler 也不核对，下载纯浪费 cninfo 请求与磁盘。`init.py` 的 `stage_reports` 默认传 `--min-year=clean.RECONCILE_MIN_YEAR`，可用 `--min-year` 覆写。注意此闸门只作用于 cninfo 报告下载（PDF/Markdown），不限制 TuShare 三表拉取（`data_fetcher.py` 仍拉全历史，2010 前年度由 `clean.py` 降级为 warning 直接入库）。

**输出目录**：
```
companies/{公司名}_{代码}/
├── 公告/年报/                          # 年报（扁平目录）
│   ├── 2025_年度报告.pdf
│   ├── 2025_年度报告.md
│   ├── 2024_年度报告.pdf
│   ├── 2024_年度报告.md
│   ├── 2024_年度报告_修订版.pdf
│   └── 2024_年度报告_修订版.md
└── 公告/季报/                 # 季报（按年分子目录）
    ├── 2025/
    │   ├── 2025_第一季度报告.pdf
    │   ├── 2025_第一季度报告.md
    │   ├── 2025_半年度报告.pdf
    │   ├── 2025_半年度报告.md
    │   ├── 2025_第三季度报告.pdf
    │   └── 2025_第三季度报告.md
    ├── 2024/
    │   └── ...
```

**过滤规则**：
- **年报**：保留 `YYYY年年度报告`、`YYYY年年度报告（修订版）`；允许 `全文` / `正文` 后缀，存在两者时优先保留 `全文`
- **一季报**：保留 `YYYY年第一季度报告` 及修订版；允许 `全文` / `正文` 后缀，存在两者时优先保留 `全文`
- **半年报**：保留 `YYYY年半年度报告` 及修订版；允许 `全文` / `正文` 后缀，存在两者时优先保留 `全文`
- **三季报**：保留 `YYYY年第三季度报告` 及修订版；允许 `全文` / `正文` 后缀，存在两者时优先保留 `全文`
- **统一排除**：`摘要`、`审计报告`、`内部控制`、`提示性公告`、`鉴证报告`、英文版、摘要/报告更新或取消、披露提示等非中文定期报告本体

**漏匹配检测**：
`collect_reports()` 按 category 统计匹配情况。若某个 category 返回了公告但 0 条通过 `parse_report()` 匹配，或存在标题明显是定期报告本体（含 `年年度报告` / `年第一季度报告` / `年半年度报告` / `年第三季度报告`）却未被匹配的条目，终端会输出 warning 并列出前 5 个未匹配标题。该机制用于及时发现标题后缀/格式变化导致的季报漏下。

**cninfo category 映射**（复用 vendored `cninfo.api` 常量）：
| 报告类型 | category |
|----------|----------|
| 年报 | `category_ndbg_szsh` |
| 一季报 | `category_yjdbg_szsh` |
| 半年报 | `category_bndbg_szsh` |
| 三季报 | `category_sjdbg_szsh` |

**Markdown**：仅年报生成同名 `.md` 文件（reconciler / financial_expense 只读年报 md，季报 md 零消费者，PyMuPDF 抽取对季报是纯 CPU 浪费）；季报只下 PDF。年报 `.md` 包含 YAML frontmatter（公告 ID、ticker、年份、`kind`、来源、页数、抽取字符数等）和 PyMuPDF 提取的全文。已有 PDF 但缺 Markdown 时会补齐；已有 Markdown 默认跳过，可用 `--force-markdown` 重生成，也可用 `--no-markdown` 连年报也不抽。

**限速**：默认每次 cninfo 查询或 PDF 下载之间随机等待 1–2 秒，可用 `--min-interval` / `--max-interval` 调整。下载并发 `--max-workers` 默认 6；`--all-reports` 时年报+季报进同一个池，季报数量约为年报的 3 倍（10 年历史约 30 份季报），单池共享让年报/季报 PDF 并发下载而非两趟串行。

### 3.4 YAML2 / YAML1 清洗 / DCF 预测层

`defaults.yaml` 是唯一 YAML2：完整、配平、无判断，由 `defaults_gen.py` 从最新 `clean_annual` 年报行生成，反映“如果没有分析师判断，最新经营状态平推”的会计默认模型。`yaml1*.yaml` 是 compiler 输出的稀疏判断覆盖层，不是 calc 输入。正式 DCF 入口是 `forecast.py`：它读取 `yaml1*.yaml + defaults.yaml`，内部调用 `yaml1_cleaner.py` 做 fold / expand / resolve / backtest，再把清洗后的标准参数交给 `calc.py`。

| 组件 | 职责 |
|------|------|
| `yaml2_schema.py` | YAML2 读写、必填路径校验、默认模型参数、review flag 常量 |
| `defaults_gen.py` | 从 `data.db` 的 `clean_annual` + `meta` 抽取 `defaults.yaml`；每个参数保留 `value/source` 便于审计 |
| `yaml1_cleaner.py` | 理解层 clean.py：读取 `yaml1*.yaml + defaults.yaml`，折叠 decomposition、展开 fade、resolve 到标准参数并做历史回测硬闸；支持无 yaml1 的恒等清洗（`--defaults-only`），中间产物默认写入 `Agent/.modelking/` |
| `forecast.py` | **编排器**：读取 `yaml1*.yaml + defaults.yaml`，调用 `yaml1_cleaner.py` 生成逐年标准参数，再调用 `calc.py` 生成 `Agent/forecast/` 与内部产物；用户正式入口 |
| `calc.py` | 纯算账核：只吃清洗后的逐年标准参数表（`--forecast-params`），按 IS→BS→CF→DCF 顺序生成预测；永远看不到 yaml1，也不直接读取 `defaults.yaml` |

**Formula/DAG 边界**：复杂 Excel 关系（滞后链、分段函数、中间变量复用、DAG）只允许在 `yaml1_cleaner.py` 内求值，先压平成收入折叠或 YAML2 标准路径覆盖，再交给 `calc.py`。`calc.py` 仍保持纯算账核，不直接理解 formula。完整设计与约束见 `docs/formula_DAG开发文档.md`；生成口径以 `docs/yaml1算法模板契约.md` 为准。

**CLI**：
```bash
python -m src.defaults_gen --ticker 300866.SZ
python -m src.defaults_gen --db companies/安克创新_300866/Agent/data.db --output companies/安克创新_300866/Agent/defaults.yaml
py -m src.yaml1_cleaner --defaults-only --ticker 002946.SZ   # YAML2 baseline 恒等清洗
py -m src.forecast --ticker 002946.SZ                        # 正式入口（有 yaml1）
py -m src.calc --forecast-params companies/新乳业_002946/Agent/.modelking/forecast_params.yaml
```

`calc.py` 只接受 `--forecast-params` 一个输入，是纯粹的低层算账核/回归工具。`defaults.yaml` 进入 `calc.py` 的唯一合法路径是先经过 `yaml1_cleaner.py`（无 yaml1 时为恒等清洗），生成 `Agent/.modelking/forecast_params.yaml`。

**公司目录契约**：
```
companies/{公司名}_{代码}/
├── 公司判断和最新观点.md
├── *核心假设*.md
├── Skills素材包/
│   ├── 最高权重材料-放Agent最应对齐的材料/
│   ├── LOAD外部EXCEL模型理解器（一次最多一个）/
│   ├── BRKD业务理解器（研报和纪要放在这里）/
│   └── ADJ增量信息（用来改模型的边际信息）/
├── active_vore/                 # 遗留目录；新技能入口不再使用
├── WEBCLAUDE/
├── 公告/
│   ├── 年报/
│   ├── 季报/
│   └── 临时公告/
├── 研报/
├── 纪要/
├── 收集/
├── 重要文件/
├── 内部报告/
│   ├── 评级报告/
│   ├── 跟踪报告/
│   ├── 深度报告/
│   └── 其他材料/
└── Agent/
    ├── data.db
    ├── core_metrics_overview.md/json/csv
    ├── defaults.yaml
    ├── financial_expense.yaml
    ├── yaml1*.yaml
    ├── recon/
    ├── .modelking/
    │   ├── forecast_params.yaml     # 逐年标准参数表（yaml1_cleaner 输出）
    │   ├── yaml1_clean_report.json  # 清洗报告
    │   └── forecast_build.json      # DCF 三表/FCFF 快照，供 sensitivity 复用
    └── forecast/
        ├── forecast_is.csv
        ├── forecast_bs.csv
        ├── forecast_cf.csv
        ├── full_is.csv        # 2015-2036 历史 + 预测完整利润表
        ├── full_bs.csv        # 2015-2036 历史 + 预测完整资产负债表
        ├── full_cf.csv        # 2015-2036 历史 + 预测完整现金流量表
        ├── dcf_detail.csv
        ├── dcf_summary.csv
        ├── dcf_summary.json
        └── run_manifest.json
```

`Agent/forecast/` 是唯一正式 DCF 输出目录，每次重算必须先清空再生成。`forecast_current/forecast_fixed/forecast_yaml1` 这类目录只能是历史调试产物，不能作为正式链路输出。`yaml2_yearly.yaml` 不是合法顶层产物：清洗后的逐年标准参数表不是 YAML2，默认只能作为内部编译缓存写入 `Agent/.modelking/forecast_params.yaml`。

**完整三表拼接**：`forecast.py` 在生成预测三表后，自动从 `data.db/clean_annual` 读取 2015–2024 年历史，按预测表的列名投影并拼接为 `full_is.csv` / `full_bs.csv` / `full_cf.csv`。拼接规则：
- BS / CF 列名与 `clean_annual` 完全同名，直接投影；
- IS 需将 `clean_annual.income.credit_impa_loss` 重命名为 `credit_impa_loss`，以匹配预测引擎的内部列名；
- 为保持口径一致，历史行的 `total_opcost` 被覆盖为 `total_cogs`（预测代码中 `total_opcost = total_cogs`），避免 2024→2025 年出现定义跳变。

**会计顺序**：
1. 利润表：收入默认 0% 增长；毛利率、费用率、below-OP 绝对值、税率、少数股东比例来自最新 clean 年报。财务费用不按历史绝对值硬平推，而是拆为 `利息支出 - 利息收入 + 其他财务费用`；默认利息支出率、现金收益率、其他财务费用由最新年报机械抽取。所得税按 `total_profit * effective_tax_rate` 计算，但亏损年 `total_profit ≤ 0` 时 `income_tax = 0`。
2. 资产负债表：应收/存货/应付等用周转或收入占比驱动；固定资产按 CAPEX 与折旧滚动（`fix_assets = max(prev_fix + capex - depreciation, 0)`，不允许固定资产为负）；其他 BS 科目 carry forward；权益按归母净利、分红率、少数股东损益滚动（分红 `dividends = max(n_income_attr_p, 0) * dividend_payout`，亏损年不分红）。
3. 循环求解：每个预测年按 IS→BS plug→平均有息负债/平均现金→财务费用→IS 的链路迭代，直到财务费用和 plug 输出收敛；参数可以简单，但引擎必须处理这个会计循环。
4. Plug 配平：默认 `plug=cash`，用 `money_cap` 倒挤 BS。若倒挤出负现金，数学上仍然配平，`calc.py` 不失败，而是在 `review_flags` 写入 `negative_cash_from_plug`，提示“plug产生负现金，建议切换为st_borr模式或检查参数”。
5. 现金流量表：由 IS + BS 变动反推 CFO/CFI/CFF，硬校验 `期初现金 + 现金净增加额 = 期末现金`。
6. DCF：`FCFF = NOPAT + D&A - CAPEX - ΔNWC`，折现显式期 FCFF + 终值，得到 EV、股权价值和每股价值。`calc.py` 内部把"三表/显式期 FCFF 构建"与"DCF 估值"拆成两层：`build_forecast_statements()` 只负责 IS→BS→CF 和原始 FCFF；`value_from_statements()` 负责贴现、稳态终值和每股价值。终值改用**稳态 terminal FCFF**：`ΔNWC = 0`，`CAPEX = D&A × terminal_capex_da_ratio`（默认 1.0），即 `terminal_fcff = last_nopat + last_da × (1 - ratio)`，再按 Gordon Growth 外推。`model.terminal_capex_da_ratio` 与 `model.wacc`、`model.terminal_growth` 一起构成 DCF 层三个可调参数，修改时只重跑 `value_from_statements()`，不重建三表。`forecast.py` 跑完后把最小 build 状态写入 `Agent/.modelking/forecast_build.json`，供工作台 sensitivity 端点实时重算。**capex 路由（2026-06-23）**：`build_balance_sheet` 只把合并 capex 的 PP&E 份（`capex − Σ三项摊销`）灌进 `fix_assets` 滚存，非 PP&E capex 不再抬高固定资产基数。关键：折旧不进利润表（`oper_cost` 由 `gpm` 派生），故 DA 在 FCFF 系数是 +1 而非 +t——路由修复是一阶去高估，不是二阶税盾微调。`metrics["capex"]`（CFI/FCFF）保持完整合并口径不变。非 PP&E 资产稳态平推。`capex < Σ摊销` 时 `capex_ppe` 落底 0 并发`REVIEW_FLAG_CAPEX_BELOW_NON_PPE_AMORT`。

**验证样本**：当前 5 家公司（安克创新、新乳业、伊利股份、美的集团、比亚迪）均已生成 YAML2 并跑通 calc，BS/CF 残差为浮点误差级；比亚迪触发负现金 review flag，未阻断配平计算。

### 3.5 本地 Web 工作台（FastAPI + React）

本地 Web 工作台把公司文件夹变成可浏览的投研模型页。它不是另一个建模引擎，只是 `companies/{公司名}_{代码}/` 的本地 UI：读 `核心假设.md`、`yaml1*.yaml`、`Agent/forecast/`、`Skills素材包/` 等文件，并通过 `src.forecast` 触发 DCF 重算。

| 组件 | 职责 |
|------|------|
| `app/` | React + Vite 前端；公司列表、Overview、核心假设渲染与假设沙盘、YAML1/Xcode 风 source view、DCF/三表、素材文件浏览 |
| `src/workbench.py` | FastAPI 本地壳；扫描 `companies/`，读取本地文件，调用 `src.forecast.run_company_forecast()`；枚举可编辑假设并提供内存预览接口 |
| `src.forecast` | 仍是唯一正式 DCF 运行入口；前端按钮只调用它，不复刻模型逻辑 |

核心假设页分为两层：默认只读展示 yaml1，进入 edit 模式后变成分析师假设沙盘。`GET /api/companies/{id}` 会返回 `editable_assumptions`，由后端从 yaml1 中自动枚举标准路径 knobs、收入拆分 driver factors、leaf margin 以及 terminal 参数；前端只渲染这份结构，不按公司名或业务线写死字段。

沙盘预览调用 `POST /api/companies/{id}/assumption-preview`：后端复制 yaml1，在内存中按 JSON pointer 应用 patch，走 `clean_yaml1_data()` → `build_forecast_statements()` → `value_from_statements()`，返回临时 DCF、临时 forecast 三表和可展示的 result rows。该接口不写 `核心假设.md`、不写 `yaml1*.yaml`、不写 `.modelking/`，因此不会污染正式输出。

正式落盘仍通过语义源头闭环：前端调用 `POST /api/companies/{id}/assumption-brief` 生成 `/ka` prompt，提示核心假设生成修改器更新 `核心假设.md`；随后 `/comp` 重新编译 yaml1，最后 `forecast.py` 正式重算。禁止前端直接把 patch 写回 yaml1，因为 yaml1 是 compiler 产物，不是人工编辑源。

DCF tab 额外提供三个实时 sensitivity 滑块（WACC、terminal growth、terminal CAPEX / D&A ratio），调用 `POST /api/companies/{id}/dcf-sensitivity` 即时刷新每股价值，无需重跑三表。视觉遵循 Apple HIG / SF Pro：白/灰系统底色、单一 #0071E3 交互蓝、轻边框和轻阴影；金融表格数字右对齐、SF Mono、负数红色、轻 zebra；YAML 面板是唯一允许多语法色的区域。

第 7 个顶级 tab「重资产排程」为**条件 tab**：仅当 `GET /api/companies/{id}` 返回 `da_view` 非 null（`Agent/da_schedule.yaml` 存在且 `enabled:true`）才渲染。`da_view` 由 `workbench._da_view()` 只读装配 `da_schedule.yaml` + `recon/da_facts_latest.json` + `.modelking/forecast_params.yaml["da_series"]` 三个磁盘文件，重算每类 `policy_dep` 与 `scale` 并调用 `da_roll.normalization_gate`。四段只读展示（存量快照 / 扩张排程+转固 / da_series 结果 / 历史证据折叠），类别名全部来自 `da_schedule.ppe.categories[].name`，N 类 N 行零公司特判；改假设走 `/da`，前端不写回。轻资产公司 `da_view=null`，tab 不可见。

运行：
```bash
npm install
npm run build
py -m src.workbench
```

Windows 双击入口为 `run_workbench.cmd`。默认服务地址为 `http://127.0.0.1:8765`；如只验证前端构建，可运行 `npm run build`。

### 3.6 vendor/use_cninfo（vendored cninfo 工具库）

`vendor/use_cninfo/` 完整 vendored `rollysys/use_cninfo`（MIT License），保留其源码、文档、测试和 skill。
当前项目通过 `vendor/use_cninfo/src` 直接复用其 cninfo API 封装：

| 上游模块 | 当前用途 |
|----------|----------|
| `cninfo.api` | `hisAnnouncement/query` 调用、标题清洗、PDF URL 拼接、PDF 下载 |
| `cninfo.orgid` | `topSearch/query` 地址与 orgId 获取逻辑参考 |
| `cninfo.cache` | 复用 `orgid_map.json` 写入逻辑 |
| `cninfo.parser` | PyMuPDF 提取全文 Markdown，供 `report_downloader.py` 生成同名 `.md` |

### 3.7 fetch_tushare_api_docs.py（Tushare 官方接口文档下载器）

`D:\MKA\fetch_tushare_api_docs.py` 是独立的官方 API 文档抓取脚本，按需把 Tushare Pro 的接口 markdown 拉取到本地，解决 skill 自带的 `references/数据接口.md` 只有目录、没有完整入参/出参/示例的问题。

**职责**：

| 组件 | 职责 |
|------|------|
| `parse_catalog()` | 解析 `~/.claude/skills/tushare/references/数据接口.md`，提取接口名、中文标题、分类、描述、官方 URL |
| `find_records()` | 按 `--titles` / `--names` / `--categories` 筛选要下载的接口 |
| `download_markdown()` | 用 `requests` 拉取官方 markdown 并保存为 `{接口名}.md` |

**输出目录**：`D:\MKA\TushareOfficialAPIMD`

**CLI 示例**：

```bash
# 下载财务数据相关接口文档
python D:/MKA/fetch_tushare_api_docs.py --titles 利润表 资产负债表 现金流量表 业绩预告 业绩快报 分红送股数据 财务指标数据 财务审计意见 主营业务构成 财报披露日期表

# 按接口名下载
python D:/MKA/fetch_tushare_api_docs.py --names income cashflow

# 按分类下载全部财务数据接口
python D:/MKA/fetch_tushare_api_docs.py --categories 财务数据

# 下载全部接口
python D:/MKA/fetch_tushare_api_docs.py --all
```

**纪律**：

- 默认读取 skill 内置的 `references/数据接口.md` 作为目录，不硬编码接口列表
- 默认 0.5 秒请求间隔，避免对 Tushare 官网造成压力
- 输出文件统一使用 UTF-8 编码，命名规则 `{接口名}.md`

---

### 3.8 annual_update_fetcher.py（年度更新器·标准线取数）

年度更新器 skill v1 第2步"标准线填历史(免费)"的可执行化——把"从已清洗数据取 (H, A] 标准线实际值"做成确定性脚本,避免 skill 自己查 SQL。从 `data.db` 的 `clean_annual` 表 + `financial_expense.yaml` 取数,输出结构化 JSON。

**CLI**：

```bash
py -m src.annual_update_fetcher --ticker 002946.SZ --history-end 2024 [--extra-fields "f1,f2"] [--forecast-md "旧稿.md"] [--out path.json]
```

**职责边界（铁律）**：只取数 + 算历史实际比率 + 标缺口。零判断、零估算、零写 .md。符号直接搬（clean_annual 已是"对利润正负贡献"口径,与旧稿一致）,不翻号——翻号归 compiler 附录 A。费用率/税率的除法是搬运历史事实（分母分子都在 clean_annual）,不是预测派生,与生成器"派生量不手算"不冲突。

**`STANDARD_LINES` 映射**（与 `skills/年度更新器_skill_v1.md` 第2步同源,TuShare 官方名,通用于所有公司）：

- direct（直接取绝对值）：`revenue`、`assets_impair_loss`、`income.credit_impa_loss`（带 `income.` 前缀,跨端点消歧）、`oth_income`、`invest_income`、`fv_value_chg_gain`、`asset_disp_income`、`non_oper_income`、`non_oper_exp`、`fin_exp`（财务费用合计,注意非 `finan_exp`）、派生观测行 `operate_profit`/`total_profit`/`income_tax`/`n_income`/`n_income_attr_p`
- ratio（`字段/revenue`）：`sell_exp`、`admin_exp`、`rd_exp`、`biz_tax_surchg`
- tax（`income_tax/total_profit`）：有效税率
- gpm（`(revenue-oper_cost)/revenue`）：整体毛利率历史观测
- minority（`minority_gain/n_income`）：少数股东损益率
- nincome_margin（`n_income_attr_p/revenue`）：归母净利率历史观测
- yaml（`financial_expense.yaml` 的 `periods.{年}.derived.other_fin_exp_abs`）：其他财务费用外生项（clean_annual 无此字段）
- **按需扩展**（`--extra-fields`）：旧稿有、默认 19 条未覆盖的行（典型 BS 科目:营运资本/资本开支/存货/应收应付/有息负债;行业特有指标）,skill 查 `src/field_registry.yaml` 映射到 TuShare 字段名后传入,按 direct 取、core=False 不阻塞,输出在 `lines.extra:<字段>`

**`status` 语义**：`ok`→按 `lines` append 进旧稿（费率/税率是 ratio,写 .md 转百分比显示;绝对值原样搬）;`noop`→N=0 已最新;`gap`→核心字段（revenue/sell_exp/admin_exp/income_tax/total_profit）缺失,守门失败指 `/init`+`clean.py`,不硬填不静默用 0 顶替 NULL。`other_fin_exp_abs` 为 null（yaml 缺该年）不阻塞,走 `公告/年报/{年}_年度报告.md` 财务费用附注 fallback。

**默认 19 条 = IS 通用标准线**(revenue headline + 4 费用率 + 8 below-OP 绝对值 + 有效税率 + 其他财务费用 + gpm/少数比率/财务费用合计/5 派生观测/归母净利率)。BS/CF/行业特有行不预输出——由 skill 按「按需扩展」传 `--extra-fields` 现取,避免把 150 个 BS 字段每次都吐出来。

**偏离诊断 md(`--forecast-md`)**:传旧稿核心假设.md 路径,fetcher 读末尾 knobs 块(机器自报清单,结构化 YAML,值与正文一字不差)取预测值,和真实值对比,产 `companies/{公司}/Agent/Logs/annual_update_deviation_{YYYYMMDD}_{A}.md`。两段表:比率类(%)+ 绝对值类(百万元),每行真实/预测/偏离。只覆盖 knobs 块里能映射到 19 条标准线的旋钮(anchor↔key 同源);收入 leaf 量价因子不在(走第3步估算,非真实 vs 预测);`other_fin_exp_abs` 特殊标(维持平推不写 knob)。是第4步人机交互的起点——分析师扫表决定重拨哪些旋钮。knobs 块 horizon 前缀 ≠ new_periods 时标错位警告。

---

## 4. 数据模型

### 4.1 SQLite Schema

```sql
-- TuShare 原始镜像（完整性校验基准）
raw_tushare (
    ticker      TEXT NOT NULL,
    endpoint    TEXT NOT NULL,       -- income / balancesheet / cashflow
    report_type TEXT NOT NULL,       -- 1=合并报表, 2=单季合并（上游真实返回时保留）
    end_date    TEXT NOT NULL,       -- YYYYMMDD
    field       TEXT NOT NULL,       -- TuShare 官方字段名
    value       REAL,               -- 已转换单位
    ann_date    TEXT,
    f_ann_date  TEXT,
    comp_type   TEXT,
    update_flag TEXT,
    PRIMARY KEY (ticker, endpoint, report_type, end_date, field)
)

-- 公司元信息
meta (
    key   TEXT PRIMARY KEY,         -- ticker / name / total_share / total_mv / ...
    value TEXT
)

clean_annual (
    period TEXT,                    -- YYYY（由 pandas index_label 写入）
    ...                            -- 325 个 TuShare 官方三表字段 + 6 个 QA plug 字段
)

clean_quarterly (
    period TEXT,                    -- YYYYQn（由 pandas index_label 写入）
    ...                            -- 325 个 TuShare 官方三表字段 + 6 个 QA plug 字段
)

clean_adjustments (
    applied_at TEXT,
    ticker TEXT,
    period TEXT,
    endpoint TEXT,
    field TEXT,
    old_value_million_cny REAL,
    new_value_million_cny REAL,
    delta_million_cny REAL,
    failure_code TEXT,
    annual_report_item TEXT,
    confidence TEXT,
    source TEXT,
    source_markdown_path TEXT,
    source_reconciliation_path TEXT,
    evidence_lines TEXT,
    reason TEXT
)

clean_warnings (
    created_at TEXT,
    ticker TEXT,
    period TEXT,
    severity TEXT,
    code TEXT,
    message TEXT,
    source TEXT,
    evidence TEXT
)
```

### 4.2 字段分类体系

三表全部 325 个 float 字段（income 86 + balancesheet 150 + cashflow 89）均已穷尽分类，每个字段只归一类。

#### 4.2.1 IS（income，86 个 float 字段）

| 分类 | 字段数 | 说明 | 示例 |
|------|--------|------|------|
| `revenue_item` | 13 | 构成 total_revenue 的科目 | `revenue`, `int_income`, `comm_income`, `oth_b_income` |
| `cost_item` | 24 | 构成 total_cogs 的成本费用项 | `oper_cost`, `sell_exp`, `admin_exp`, `fin_exp`, `rd_exp`, `assets_impair_loss` |
| `operating_adjustment` | 6 | 营业利润调节项（加项） | `oth_income`, `invest_income`, `fv_value_chg_gain`, `asset_disp_income` |
| `below_line` | 2 | 营业外收支 | `non_oper_income`, `non_oper_exp` |
| `tax` | 1 | 所得税 | `income_tax` |
| `attribution` | 2 | 净利润归属拆分 | `n_income_attr_p`, `minority_gain` |
| `comprehensive` | 4 | 综合收益 | `oth_compr_income`, `t_compr_income` |
| `subtotal` | 6 | 利润表小计/合计 | `total_revenue`, `total_cogs`, `operate_profit`, `total_profit`, `n_income` |
| `sub_item` | 7 | 父项的子明细，已含于父项不重复加 | `ass_invest_income` ⊂ `invest_income`, `fin_exp_int_exp` ⊂ `fin_exp` |
| `derived` | 21 | 衍生字段或利润分配字段，不参与加总 | `basic_eps`, `ebit`, `ebitda`, `undist_profit` |

#### 4.2.2 BS（balancesheet，150 个 float 字段）

| 分类 | 字段数 | 说明 | 示例 |
|------|--------|------|------|
| `current_asset` | 41 | 流动资产 | `money_cap`, `notes_receiv`, `inventories`, `oth_cur_assets` |
| `noncurrent_asset` | 25 | 非流动资产 | `fix_assets`, `cip`, `intan_assets`, `goodwill`, `lt_eqt_invest` |
| `current_liab` | 44 | 流动负债 | `st_borr`, `notes_payable`, `acct_payable`, `oth_payable` |
| `noncurrent_liab` | 10 | 非流动负债 | `lt_borr`, `bond_payable`, `lt_payable`, `lease_liab` |
| `equity` | 13 | 所有者权益 | `total_share`, `cap_rese`, `undistr_porfit`, `minority_int` |
| `subtotal` | 9 | 小计/合计 | `total_cur_assets`, `total_assets`, `total_liab`, `total_hldr_eqy_inc_min_int` |
| `combo` | 7 | 合并科目（与拆分项二选一） | `accounts_receiv_bill`, `oth_pay_total`, `fix_assets_total` |
| `derived` | 1 | 不参与加总 | `invest_loss_unconf` |

#### 4.2.3 CF（cashflow，89 个 float 字段）

| 分类 | 字段数 | 说明 | 示例 |
|------|--------|------|------|
| `cfo_inflow` | 14 | 经营活动流入 | `c_fr_sale_sg`, `recp_tax_rends`, `c_fr_oth_operate_a` |
| `cfo_outflow` | 9 | 经营活动流出 | `c_paid_goods_s`, `c_paid_to_for_empl`, `oth_cash_pay_oper_act` |
| `cfi_inflow` | 5 | 投资活动流入 | `c_disp_withdrwl_invest`, `c_recp_return_invest`, `n_recp_disp_fiolta` |
| `cfi_outflow` | 5 | 投资活动流出 | `c_pay_acq_const_fiolta`, `c_paid_invest`, `oth_pay_ral_inv_act` |
| `cff_inflow` | 4 | 筹资活动流入 | `c_recp_borrow`, `proc_issue_bonds`, `c_recp_cap_contrib` |
| `cff_outflow` | 3 | 筹资活动流出 | `c_prepay_amt_borr`, `c_pay_dist_dpcp_int_exp`, `oth_cashpay_ral_fnc_act` |
| `subtotal` | 13 | 小计/合计/净额 | `c_inf_fr_operate_a`, `n_cashflow_act`, `stot_inflows_inv_act`, `n_incr_cash_cash_equ` |
| `supplementary` | 27 | 间接法附注项 | `net_profit`, `depr_fa_coga_dpba`, `decr_inventories`, `others` |
| `balance` | 6 | 期初期末现金余额 | `c_cash_equ_beg_period`, `c_cash_equ_end_period`, `end_bal_cash` |
| `sub_item` | 2 | 父项的子明细 | `incl_dvd_profit_paid_sc_ms` ⊂ `c_pay_dist_dpcp_int_exp` |
| `derived` | 1 | 不参与加总 | `free_cashflow` |

#### 4.2.4 分类通用规则

- **sub_item**：已包含在父项中，bucket sum 时自动跳过子项、只加父项值，避免重复计数
- **combo**（仅 BS）：与拆分项二选一，通过 `resolve()` 处理互斥（拆分项全在 → 用拆分项和；否则用 combo 值）
- **derived / supplementary**：不参与任何 bucket 加总校验
- **subtotal**：作为校验的等号右侧目标值，不参与自身 bucket 的加总

展示边界：`combo` / `derived` / `sub_item` 是数据工程口径，默认不进入 Workbench 完整三表主视图。主视图优先展示拆分项；只有拆分项缺失或全 0、combo 有值时，combo 才作为 fallback 展示。需要排查底层口径时，前端打开“显示技术口径”查看这些字段。

### 4.3 单位转换规则

| 类别 | 入库单位 | 转换公式 |
|------|----------|----------|
| `amount_cny` | 百万元 | 元 ÷ 1,000,000 |
| `percent` | 小数 | 原值 ÷ 100 |
| `share` | 百万股 | 股 ÷ 1,000,000 |
| `daily_basic_share_10k` | 百万股 | 万股 ÷ 100 |
| `daily_basic_mv_10k_cny` | 百万元 | 万元 ÷ 100 |
| `turnover_rate` | 天 | 365 ÷ 周转率 |
| `ratio` / `price` | 原值 | 不转换 |

---

## 5. 关键算法

### 5.1 raw_tushare 官方镜像

三表数据以 TuShare 官方字段为准，按 `endpoint + report_type + end_date + field` 写入 `raw_tushare`：

- `income`：86 个官方 float 字段
- `balancesheet`：150 个官方 float 字段
- `cashflow`：89 个官方 float 字段

report_type=1（合并报表）和 report_type=2（单季合并）均保留到 `raw_tushare.report_type`。季度清洗优先使用 income report_type=2；若单季利润表缺失，则允许回退到 report_type=1。BS/CF 使用同报告期 report_type=1 数据。

`0331/0630/0930/1231` 等报告期原样保存在 `raw_tushare.end_date`。阶段② `clean.py` 从 `raw_tushare` 读取年度和季度数据并透视为完整 clean 宽表：325 个官方 TuShare 三表字段 + 6 个 QA plug 字段，写入 SQLite 的 `clean_annual` / `clean_quarterly`，均以 `period` 作为期间列并保留 QA plug。

**CF 季度拆算**：`cashflow` 的 report_type=1 季度数据是累计值（Q1cum, H1cum, Q3cum, Annual），需在透视后拆为单季：
- Q1 = Q1cum（不变）
- Q2 = H1cum - Q1cum
- Q3 = Q3cum - H1cum
- Q4 = Annual - Q3cum

同时 `c_cash_equ_beg_period` 修正为上季度末的 `c_cash_equ_end_period`；若 TuShare 原始期初/期末现金与净增加额之间仍有小额桥接残差，季度模式写入显式 `qa_cf_cash_reconcile_plug` 并记录 warning。时点字段 `c_cash_equ_end_period` 不拆算。

**季度范围限制**：为避免 2005–2013 年早期季报披露口径不完整导致的配平失败，`pivot_to_wide()` 在 quarterly 模式下仅保留最近 48 个 quarter（12 年）的数据。安克创新、新乳业等上市较晚的公司不受影响。

### 5.2 去重规则

同一 (endpoint, report_type, end_date) 可能有多条记录，保留优先级：

1. `report_type = '1'`（合并报表）
2. `comp_type = '1'`（一般工商业；非此则 warning 并跳过）
3. `update_flag = '1'` 优先
4. `f_ann_date` 最晚
5. `ann_date` 最晚

### 5.3 合并科目 resolve 逻辑

```python
def resolve(split_fields, combo_field, row, present_fields):
    if ALL split_fields in present_fields:
        → 用拆分项求和
        → 特例：拆分项全为 0 但 combo 非 0 时用 combo（公司只报合并项）
        → 特例：oth_pay_total 非 0 时优先使用合并项，避免其他应付款合计与应付利息/股利重复计入
    elif combo_field in present_fields:
        → 用合并项
    else:
        → 0.0
```

7 组合并对：

| 合并项 | 拆分项 | 所属 |
|--------|--------|------|
| `accounts_receiv_bill` | `notes_receiv` + `accounts_receiv` | 流动资产 |
| `oth_rcv_total` | `oth_receiv` | 流动资产 |
| `fix_assets_total` | `fix_assets` | 非流动资产 |
| `cip_total` | `cip` | 非流动资产 |
| `accounts_pay` | `notes_payable` + `acct_payable` | 流动负债 |
| `oth_pay_total` | `oth_payable` + `int_payable` + `div_payable` | 流动负债 |
| `long_pay_total` | `lt_payable` | 非流动负债 |

### 5.4 跨端点同名字段消歧

`credit_impa_loss` 同时存在于 `income` 和 `cashflow` 两个端点，值可能不同。`pivot_to_wide()` 自动检测跨端点同名字段，加 `endpoint.` 前缀消歧（如 `income.credit_impa_loss` / `cashflow.credit_impa_loss`）。校验函数通过 `_vi()` / `_vc()` 辅助函数正确寻址。

### 5.5 宽表列完整性

TuShare 三个接口（income/balancesheet/cashflow）的字段集是固定的，所有公司的 SQLite `clean_annual` / `clean_quarterly` **必须输出相同的列集**（`period` + 325 个官方字段 + 6 个 QA plug 字段，其中 `credit_impa_loss` 因跨端点消歧拆为 `income.credit_impa_loss` / `cashflow.credit_impa_loss`）。下游模型（如 forecast 引擎）直接从 SQLite clean 表读取统一特征集。

某公司某字段无值时填 0，保留该列。这确保下游模型（如 forecast 引擎）可以对所有公司使用统一的特征集，即使某字段历史上全为 0（如安克创新无商誉），未来也可能出现非零值。

实现方式：`pivot_to_wide()` 在 `pivot_table` 之前收集全部列名，pivot 后用 `reindex(columns=all_columns)` 补回被 pandas 静默丢弃的全 NaN 列，再 `fillna(0.0)`，最后补齐 `qa_bs_current_asset_plug`、`qa_bs_noncurrent_asset_plug`、`qa_bs_current_liab_plug`、`qa_bs_noncurrent_liab_plug`、`qa_bs_equity_plug`、`qa_cf_cash_reconcile_plug` 六个 QA 字段。`write_clean_table()` 写 SQLite 时保留完整 clean 宽表，并用 `DataFrame.to_sql(..., index=True, index_label="period")` 生成供 defaults_gen 等下游读取的 clean 表。

---

## 6. 校验体系

### 6.1 校验层级

| 层级 | 行为 | 编号 |
|------|------|------|
| **年度硬校验** | 残差 ≥ 1 百万元 → `CheckError` 停止 | IS 1.1–1.6, BS 2.1–4.3, CF 5.1–5.5, IS补充 6.1–6.3, 跨表 7.1, 连续性 7.4 |
| **季度硬校验** | BS bucket 明细残差、CF 5.5 现金桥接残差先进入显式 QA plug 并写 warning；plug 后残差 ≥ 1 百万元 → `CheckError` 停止 | BS 2.1–4.3, CF 5.1–5.5；IS 主表和 IS 补充按 warning 输出 |
| **软校验** | 仅 `LOGGER.warning`，不阻止输出 | 跨表 7.2–7.3, 方向 10.1, 量级 10.2, 折旧 10.3, 毛利率 10.4 |
| **入库前硬检查** | 不通过则拒绝写入 SQLite | raw_tushare 非空/主键无重复/ticker一致/官方字段覆盖/最新年报核心字段非空/meta完整 |

### 6.2 硬校验公式一览

| 编号 | 报表 | 公式 |
|------|------|------|
| IS 1.1 | 利润表 | total_cogs = Σ标准费用项 + fin_exp + Σ额外项 |
| IS 1.2 | 利润表 | operate_profit = revenue_base - total_cogs + Σ收益项（revenue_base 通常为 `revenue`；当 `int_income`/`comm_income`/`n_oth_b_income` 可解释 `total_revenue` 与 `revenue` 的差额时，取 `total_revenue`） |
| IS 1.3 | 利润表 | total_profit = operate_profit + non_oper_income - non_oper_exp |
| IS 1.4 | 利润表 | n_income = total_profit - income_tax |
| IS 1.5 | 利润表 | n_income = n_income_attr_p + minority_gain |
| IS 1.6 | 利润表 | total_revenue = Σrevenue_item（自适应：兼容 revenue-only 与含 int_income/comm_income 的口径） |
| BS 2.1 | 资产负债表 | total_cur_assets = Σ流动资产明细（含 resolve） |
| BS 2.2 | 资产负债表 | total_nca = Σ非流动资产明细（含 resolve） |
| BS 2.3 | 资产负债表 | total_assets = total_cur_assets + total_nca |
| BS 3.1 | 资产负债表 | total_cur_liab = Σ流动负债明细（含 resolve） |
| BS 3.2 | 资产负债表 | total_ncl = Σ非流动负债明细（含 resolve） |
| BS 3.3 | 资产负债表 | total_liab = total_cur_liab + total_ncl |
| BS 4.1 | 资产负债表 | total_hldr_eqy_inc_min_int = Σ权益明细 |
| BS 4.2 | 资产负债表 | total_hldr_eqy_inc_min_int = total_hldr_eqy_exc_min_int + minority_int |
| BS 4.3 | 资产负债表 | total_assets = total_liab + total_hldr_eqy_inc_min_int |
| CF 5.1 | 现金流量表 | n_cashflow_act = c_inf_fr_operate_a - st_cash_out_act |
| CF 5.2 | 现金流量表 | n_cashflow_inv_act = stot_inflows_inv_act - stot_out_inv_act |
| CF 5.3 | 现金流量表 | n_cash_flows_fnc_act = stot_cash_in_fnc_act - stot_cashout_fnc_act |
| CF 5.4 | 现金流量表 | n_incr_cash_cash_equ = CFO + CFI + CFF + eff_fx_flu_cash |
| CF 5.5 | 现金流量表 | c_cash_equ_end_period = c_cash_equ_beg_period + n_incr_cash_cash_equ + qa_cf_cash_reconcile_plug |
| IS 6.1 | 利润表补充 | t_compr_income = n_income + oth_compr_income |
| IS 6.2 | 利润表补充 | t_compr_income = compr_inc_attr_p + compr_inc_attr_m_s |
| IS 6.3 | 利润表补充 | n_income = continued_net_profit + end_net_profit（如有披露） |
| 跨表 7.1 | 跨表 | IS n_income = CF net_profit |
| 跨表 7.4 | 跨表 | 上年 CF 期末现金 = 本年 CF 期初现金 |

### 6.3 IS 1.1 营业总成本三步降级

当标准费用项加总 ≠ total_cogs 时，依次尝试：

1. **total_opcost 路线**：total_cogs = total_opcost + fin_exp → 差额归因于未归属成本（如合同履约成本）
2. **operate_profit 反推**：total_cogs = revenue + Σ收益项 - operate_profit → total_cogs 值本身可验证
3. **真正不一致** → 硬校验报错

### 6.4 年报 Markdown 智能核对（外置补全/诊断）

`annual_report_reconciler.py` 是 `clean.py` 的外置辅助脚本，不嵌入主清洗路径，也不修改 `data.db`、`raw_tushare`、`clean_annual` 或 `clean_quarterly`。它的职责是在 `clean.py` 出现年度硬校验失败、且本地已有对应年度报告 Markdown 时，自动抽取年报片段并调用配置好的 LLM（默认 GLM `glm-5-turbo`）进行结构化归因，判断是否疑似 TuShare 字段缺失或口径错误。

触发/使用原则：

- 只针对年度硬校验失败；季度数据不直接用年报解释
- 先复用 `clean.py` 的 `load_raw_tushare()`、`pivot_to_wide()`、`check_*()` 和分类/resolve 逻辑收集失败，不重写公式
- 对每条失败按报表类型切出年报 Markdown 主表片段，并附带候选 TuShare 字段、中文说明、当前百万元值、是否出现在 `raw_tushare`
- 若目标年度缺少单独年报 Markdown，可使用后续年度年报的比较报表列作为证据来源；例如上市首年年报通常同时披露上一年度比较数
- LLM 仅负责智能归因，输出 JSON evidence；脚本本身不静默补数
- 输出目录为 `companies/{公司名}_{代码}/Agent/recon/`，包含时间戳 JSON、`annual_report_reconciliation_latest.json` 与可选 `annual_report_overrides.json`
- `annual_report_overrides.json` 强制来自 LLM 结构化结论；`--write-overrides` 与 `--no-llm` 互斥，规则匹配仅用于诊断辅助，不可生成可应用补数
- `clean.py` 只应用 `annual_report_overrides.json` 中 `status=approved` 的记录，且只应用到年度 clean 宽表；`raw_tushare` 永远不改
- 每条应用过的补数写入 SQLite `clean_adjustments`，同时在 `clean_warnings` 中留下 warning；软校验 warning 也会持久化到 `clean_warnings`

**强触发规则**：当 `clean.py` 在 annual 或 all 模式下遇到年度 hard check 失败时，当前 clean 运行必须失败退出，因为这代表年度 clean 数据不能被信任。随后 `clean.py` 默认自动调用：

> **2010 闸门（`RECONCILE_MIN_YEAR=2010`）**：强触发与年报核对只对 2010 年及以后的年度硬校验失败生效。2010 之前的年度硬校验失败在 `validate_wide` 里被降级为 warning（前缀 `[pre-2010 直接入库，不触发核对]`），clean 仍把该年度写进 `clean_annual`，不阻塞、不触发 reconciler；`annual_report_reconciler.collect_failures` 同步跳过 2010 之前的年度（仍携带期末现金以保证 2010+ 的跨表 7.4 解析）。原因：A 股 2010 前披露稀疏、格式早期，对年报核对得不偿失。季度不受影响（走 QA plug，且已截断到近 12 年）。

```bash
python -m src.annual_report_reconciler --ticker {ticker} --db {data.db} --max-failures 20 --write-overrides --approve-high-confidence
```

终端提示必须明确说明三点：这是 clean-data blocker，不是软 warning；本次年度 clean 输出没有被视为可信结果；系统正在用本地年报 Markdown + LLM evidence 判断是否为 TuShare 字段缺失/口径问题。自动触发只生成 evidence 与 approved override 文件，不修改 `raw_tushare`，也不把失败的 clean 运行改判成功。若生成了新的 approved override，用户需重跑 `clean.py`，由正常 clean 流程应用补数、写入 `clean_adjustments`/`clean_warnings` 并重新通过 hard checks。

可用 `--no-auto-reconcile` 关闭强触发；可用 `--auto-reconcile-max-failures N` 调整自动分析的失败条数。`annual_report_reconciler.py` 重写默认 `annual_report_overrides.json` 时会合并既有 override，避免部分失败分析覆盖旧的 approved LLM 证据。

CLI：

```bash
python -m src.annual_report_reconciler --ticker 000333.SZ
python -m src.annual_report_reconciler --ticker 000333.SZ --only-year 2025 --only-code "BS 2.1"
python -m src.annual_report_reconciler --ticker 000333.SZ --no-llm
python -m src.annual_report_reconciler --ticker 000333.SZ --write-overrides --approve-high-confidence
python -m src.clean --ticker 000333.SZ --mode annual
python -m src.clean --ticker 000333.SZ --mode annual --no-auto-reconcile
```

LLM 输出字段包括 `suspected_tushare_issue`、`confidence`、`missing_or_suspicious_items`、`candidate_tushare_field`、`value_million_cny`、`evidence_lines`、`recommended_action` 等。`--write-overrides --approve-high-confidence` 只会把 LLM 判断为 high confidence、且残差精确匹配的结果写成 approved override。美的集团 2016–2025 年 `BS 2.1` 可生成 10 条 `lending_funds` approved override；`python -m src.clean --ticker 000333.SZ --mode annual` 后年度 10 期全部硬校验通过，`clean_adjustments=10`，`clean_warnings=30`。

### 6.5 clean 后年度核心指标速览

`core_metrics_overview.py` 是 `/init` 在 `stage_clean()` 成功后触发的年度事实面板生成器。它只读取 `data.db/clean_annual` 和 `meta` 中稳定的 ticker/name，不读取 `defaults.yaml`、`yaml1*.yaml`、`Agent/forecast/`，也不调用 LLM。职责是把后续 Agent 最常看的利润表主链路转成 LLM 易读的横向历史表：收入同比、毛利率、费用率、营业利润率、利润总额率、所得税率、净利率、净利润同比，以及资产减值、信用减值、其他收益、投资收益、公允价值变动、资产处置收益、营业外收支等波动项。

输出固定覆盖写入：

```text
companies/{公司}/Agent/core_metrics_overview.md
companies/{公司}/Agent/core_metrics_overview.json
companies/{公司}/Agent/core_metrics_overview.csv
```

幂等约束：输出不包含生成时间或 market quote 这类易变元数据；同一份 `clean_annual` 重跑应保持字节稳定。`.md` 供人和 LLM 直接阅读，`.json` 供后续脚本稳定消费，`.csv` 供表格横向对比。生成失败只作为 `/init` warning 上报，不把已经通过的 clean 改判失败；`--mode quarterly` 不更新年度速览。

CLI：

```bash
python -m src.core_metrics_overview --ticker 002946.SZ
python -m src.core_metrics_overview --db companies/新乳业_002946/Agent/data.db
```

### 6.6 财务费用细则分析（外置 evidence 生成器）

`financial_expense_analyzer.py` 是 `defaults_gen.py` 的外置辅助，**不属于 clean 主路径**，也不修改 `data.db` 或 `defaults.yaml`。它的职责是在 clean 数据已落定、且本地有对应年度报告 Markdown 时，遍历 `clean_annual` 的每一年，从「财务费用」附注中拆出利息支出的真实构成，生成按年份归档的审计级档案 `financial_expense.yaml`，供 `defaults_gen.py` 选择是否覆盖机械拆分出的 `income.financial_expense` 参数。

处理流程：

1. 遍历 `clean_annual` 每一期，取 anchor：`fin_exp`、`fin_exp_int_exp`、`fin_exp_int_inc`、有息负债、货币资金。
2. 对每一期按 `base_period N → 报告年份 N+1` 映射，找到对应年报 Markdown；在报告中读取**上期发生额**列（即 FY N）。
3. 切片「财务费用」附注表，调用 LLM 返回结构化分项：
   - `interest_expense_gross`：银行/租赁/债券等利息支出
   - `capitalized_interest`：资本化利息（正数）
   - `interest_subsidy`：财政贴息冲减（正数）
   - `interest_income`：利息收入（正数）
   - `other_non_interest`：汇兑损益、手续费、其他财务费用（保持表内符号）
4. 按固定规则 derive：
   - `interest_expense = gross - capitalized`（贴息不进利率分子）
   - `other_fin_exp_abs = fin_exp - interest_expense + interest_income`（贴息效果自然落进 other）
5. 两道勾稽：
   - **总额勾稽**：`interest_expense - interest_income + other_fin_exp_abs ≈ fin_exp`
   - **边界勾稽**：从 LLM 分项重建四种口径（gross / net_of_capitalized / net_of_subsidy / net_of_capitalized_and_subsidy），动态 detect `clean.fin_exp_int_exp` 的实际口径
6. 写入 `companies/{公司}/Agent/financial_expense.yaml`（多年档案）；同时保留 `Agent/recon/financial_expense_detail_latest.json` 作为最近一次单期运行的调试/审计副本。

`defaults_gen.py` 读取 `financial_expense.yaml`，仅在记录 `status=approved`、`confidence=high`、勾稽全过且 `base_period` 与 YAML2 `base_period` 匹配时，才用该年 derived 值覆盖 `interest_expense_rate`、`cash_interest_rate`、`other_fin_exp_abs`、`base_interest_expense`、`base_interest_income`，并将 `source` 改为 `annual_report.fin_exp_note`；否则保持机械值。`init.py` 在 `stage_core_metrics_overview()` 之后调用 `stage_financial_expense()` 生成全量档案，失败只 warning，不阻塞后续流程。

CLI：

```bash
python -m src.financial_expense_analyzer --ticker 002946.SZ        # 全量生成 financial_expense.yaml
python -m src.financial_expense_analyzer --ticker 002946.SZ --force  # 强制重新生成
python -m src.financial_expense_analyzer --ticker 002946.SZ --latest-only  # 只分析最新一年并写 debug JSON
```

新乳业（002946.SZ）实测：10 个 clean_annual 年份中 8 个生成 approved high 记录（2015/2016 因缺年报 Markdown 报错），2024 基期 `interest_expense_gross=124.15M`、`capitalized=14.06M`、`subsidy=3.82M`；detected basis 为 `net_of_capitalized_and_subsidy`，即 TuShare `fin_exp_int_exp` 已同时净掉资本化利息与财政贴息；derive 后 `interest_expense=110.09M`、`other_fin_exp_abs=-1.47M`。

### 6.7 季度 QA plug 收纳科目

季度报告通常只披露合计数，明细科目覆盖弱于年报。`clean.py` 因此只在 quarterly 模式下，为 BS bucket 小计提供显式 QA plug 字段：

- `qa_bs_current_asset_plug`
- `qa_bs_noncurrent_asset_plug`
- `qa_bs_current_liab_plug`
- `qa_bs_noncurrent_liab_plug`
- `qa_bs_equity_plug`
- `qa_cf_cash_reconcile_plug`

这些字段不是 TuShare 官方字段，而是 clean 阶段的显式审计/防呆字段。BS plug 仅参与 BS 2.1、2.2、3.1、3.2、4.1 的 bucket 小计校验；`qa_cf_cash_reconcile_plug` 仅参与 CF 5.5 的期初期末现金桥接校验，不参与 CF 5.1–5.4 的流量明细加总。不修改 `raw_tushare`，也不替代年度 LLM override。QA plug 保留在 SQLite `clean_annual` / `clean_quarterly`、debug CSV 和 `clean_warnings` 审计中，确保下游读取主库时不会丢失配平桥。

触发时，`apply_quarterly_bs_plugs()` 会计算 `目标合计 - 明细和 = 残差`，把残差写入对应 plug 字段；`apply_quarterly_cf_cash_plugs()` 会计算 `期末现金 - (期初现金 + 净增加额) = 残差`，把残差写入 `qa_cf_cash_reconcile_plug`。两者都会在 `clean_warnings` 写入完整说明：失败编号、目标字段、目标值、plug 前计算值、plug 字段、残差，以及建议检查路径。这样季度数据可以先得到配平的 clean CSV，同时保留“哪里合不上、为什么收纳、后续怎么查”的可追溯 warning。

美的集团实测：`python -m src.clean --ticker 000333.SZ --mode quarterly` 后 48 个季度全部硬校验通过；仅 `BS 2.1 流动资产合计` 使用 `qa_bs_current_asset_plug`，其余四个 QA plug 均为 0，`clean_warnings` 中每个季度都有公式级说明。

### 6.7 已知 TuShare 缺陷提示卡

`knowledge/known_tushare_defects.json` 是一个轻量记忆文件，只服务于 `annual_report_reconciler.py` 的 LLM 年报检索提示，不参与 clean 校验、不自动补数、不改变 override 审批规则。它记录的是“触发条件 + 字段”的通用诊断经验，而不是某家公司补丁。

当前记录：

- `BS 2.1` / `balancesheet` / `current_asset` / `lending_funds`
- 触发形态：`total_cur_assets` 大于流动资产明细和，`lending_funds` 缺失或为 0
- LLM 检索提示：优先在合并资产负债表中查“发放贷款和垫款 / 发放贷款 / 垫款 / 贷款”，年报千元除以 1000 后与 clean 百万元残差比较
- 确认样本：美的集团 2016–2025 年

命中提示卡时，`annual_report_reconciler.py` 会把 `known_tushare_defect_hints` 写入 reconciliation JSON，并把提示词加入 Markdown 片段检索；LLM prompt 明确说明这些 hint 只是检索线索，不是证据。最终是否生成 approved override 仍必须由年报片段金额解释残差，并由 LLM high confidence 结构化确认。

---

## 6.5 契约注册表

> **规则**：每种数据格式有且只有一个拥有者（协议文档或代码），其他文档只链接、不复制字段。格式变更只发生在拥有者处。

| 契约 | 拥有者 | 消费者 | 状态 | 路径 |
|---|---|---|---|---|
| 核心假设.md | `skills/核心假设生成修改器_skill_v17.md` | compiler skill | v17 | `skills/...` |
| YAML1 (drivers) | `skills/yaml1compiler_v4 (2).md` | `src/yaml1_cleaner.py` | 定稿 | `companies/{公司}/Agent/yaml1*.yaml` |
| YAML1 formula/DAG 开发契约 | `docs/formula_DAG开发文档.md` | `src/yaml1_cleaner.py`, compiler/core-assumption skills, tests | 实验性·受限（仅合成 fixture 验证） | `docs/formula_DAG开发文档.md` |
| YAML2 / defaults.yaml | `src/yaml2_schema.py` | `src/yaml1_cleaner.py`, `src/defaults_gen.py` | 稳定 | `companies/{公司}/Agent/defaults.yaml` |
| 逐年标准参数表 | `src/yaml1_cleaner.py` | `src/calc.py` | 稳定 | `companies/{公司}/Agent/.modelking/forecast_params.yaml` |
| yaml1 清洗报告 | `src/yaml1_cleaner.py` | 工作台 / 人 | 稳定 | `companies/{公司}/Agent/.modelking/yaml1_clean_report.json` |
| DCF build 快照 | `src/forecast.py` | `src/workbench.py`（sensitivity） | 稳定 | `companies/{公司}/Agent/.modelking/forecast_build.json` |
| DCF 运行清单 | `src/forecast.py` | 工作台 / 人 | 稳定 | `companies/{公司}/Agent/forecast/run_manifest.json` |
| 年度核心指标速览 | `src/core_metrics_overview.py` | Agent / 人 / 后续脚本 | 稳定 | `companies/{公司}/Agent/core_metrics_overview.md/json/csv` |
| 财务费用档案 | `src/financial_expense_analyzer.py` | `src/defaults_gen.py` | 稳定 | `companies/{公司}/Agent/financial_expense.yaml` |
| 年报补数 override | `src/annual_report_reconciler.py` | `src/clean.py` | 稳定 | `companies/{公司}/Agent/recon/annual_report_overrides.json` |
| 年报核对 evidence | `src/annual_report_reconciler.py` | 人 / 审计 | 稳定 | `companies/{公司}/Agent/recon/*_reconciliation.json` |
| clean 宽表 | `src/clean.py` | `src/defaults_gen.py` | 稳定 | `data.db: clean_annual / clean_quarterly` |
| clean 补数审计 | `src/clean.py` | 审计 | 稳定 | `data.db: clean_adjustments` |
| clean 警告 | `src/clean.py` | 审计 | 稳定 | `data.db: clean_warnings` |
| raw 数据镜像 | `src/data_fetcher.py` | `src/clean.py` | 稳定 | `data.db: raw_tushare` |
| 季度预测格式 | 待定（任务 E） | — | 未设计 | — |
| commit 存储格式 | 待定（任务 D） | — | 未设计 | — |

---

## 7. 配置与依赖

### 7.1 环境配置（.env）

```env
TUSHARE_TOKEN=           # TuShare Pro API 令牌（必填）
TUSHARE_HTTP_URL=http://api.waditu.com/dataapi    # 官方 SDK 入口
TUSHARE_MIN_INTERVAL_SECONDS=0.8                    # 请求间隔（秒）
LLM_PROVIDER=glm
GLM_API_KEY=             # GLM API Key（annual_report_reconciler.py）
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_MODEL=glm-5-turbo
GLM_TIMEOUT_SECONDS=120
LLM_MAX_TOKENS=8192

# Kimi disabled; keep only as commented fallback if needed.
# KIMI_API_KEY=
# KIMI_BASE_URL=https://api.moonshot.cn/v1
# KIMI_MODEL=kimi-k2.6
```

### 7.2 Python 依赖

```
tushare>=1.4.0
pandas>=2.0.0
requests>=2.31
pymupdf>=1.24
pyyaml>=6.0
```

`requests` 用于 cninfo 接口与 PDF 下载；`pymupdf` 用于 `report_downloader.py`
复用 vendored `use_cninfo` 的 PyMuPDF 全文抽取能力，生成 Markdown；`pyyaml`
用于 `defaults_gen.py` / `calc.py` 读写 YAML2 默认参数集。

### 7.3 官方文档字段数基准

| endpoint | 数值字段数 | 文档 |
|----------|-----------|------|
| `income` | 86 | `D:\MKA\TushareOfficialAPIMD\income.md` |
| `balancesheet` | 150 | `D:\MKA\TushareOfficialAPIMD\balancesheet.md` |
| `cashflow` | 89 | `D:\MKA\TushareOfficialAPIMD\cashflow.md` |

---

## 8. 目录结构

```
MKA/
├── src/                           # 核心 Python 源码
│   ├── __init__.py                # 使 src 成为 package
│   ├── init.py                    # 一键编排入口
│   ├── webka.py                   # 已废弃的旧版网页端核心假设打包器；active skill 已移至 deprecatedlogs/webka/
│   ├── webload.py                 # 网页端 load 打包器：prepare 时间沙箱并汇总到 WEBCLAUDE/模型装载部分/
│   ├── data_fetcher.py            # 阶段①：TuShare 拉取 + 标准化 + 入库
│   ├── clean.py                   # 阶段②：EAV→宽表 + 配平校验 + clean 表写入（字段分类/resolve 从 field_registry import）
│   ├── core_metrics_overview.py   # clean_annual → Agent/core_metrics_overview.* 年度事实速览
│   ├── field_registry.py          # field_registry.yaml loader:三表字段元数据唯一真源(clean + workbench 同源)
│   ├── field_registry.yaml        # 全程序会计科目唯一真源(分类/会计序/标签/resolve/sign/role)
│   ├── report_downloader.py       # 巨潮资讯网年报 PDF + Markdown 批量下载
│   ├── annual_report_utils.py     # 年报 Markdown/LLM 公共工具（被 reconciler / analyzer 共用）
│   ├── annual_report_reconciler.py # clean.py 硬校验失败后的年报 Markdown 智能核对器
│   ├── annual_report_extractor.py # 年报 Markdown LLM 萃取
│   ├── financial_expense_analyzer.py # 财务费用附注细则分析：生成 financial_expense.yaml（多年档案）+ recon/ 调试副本
│   ├── yaml2_schema.py            # YAML2 读写、必填参数和 review flag 公共定义
│   ├── defaults_gen.py            # clean_annual/meta → defaults.yaml 默认参数集
│   ├── yaml1_cleaner.py           # yaml1 + defaults.yaml → 内部 forecast params + report
│   ├── forecast.py                # 正式入口：defaults.yaml + yaml1*.yaml → Agent/forecast/
│   └── calc.py                    # 标准参数表 → 预测三表 + DCF summary
├── fetch_tushare_api_docs.py      # 按需抓取 Tushare 官方接口 markdown 文档到 TushareOfficialAPIMD/
├── app/                           # React + Vite 本地工作台前端
│   └── src/
├── docs/                          # 项目文档
│   ├── ARCHITECTURE.md            # 本文档：系统架构
│   └── ...                        # 补充设计文档
├── CLAUDE.md                      # 项目约定与关键运行规则
├── package.json                   # React/Vite 前端脚本与依赖
├── requirements.txt               # Python 依赖
├── .env                           # 敏感配置（不纳入版本控制）
├── .gitignore
├── companies/                     # 运行时输出（不纳入版本控制）
│   └── {公司名}_{代码}/
│       ├── 公司判断和最新观点.md
│       ├── Agent业务讨论.md       # /brkd 产出：业务预理解参考，/ka 消费
│       ├── *核心假设*.md
│       ├── Skills素材包/          # 建模材料固定入口
│       │   ├── 最高权重材料-放Agent最应对齐的材料/
│       │   ├── LOAD外部EXCEL模型理解器（一次最多一个）/
│       │   ├── BRKD业务理解器（研报和纪要放在这里）/
│       │   └── ADJ增量信息（用来改模型的边际信息）/
│       ├── active_vore/           # 遗留目录；新技能入口不再使用
│       ├── WEBCLAUDE/             # 高频打包输出，供分析师粘贴到 Claude
│       ├── 公告/
│       │   ├── 年报/              # 巨潮资讯网年度报告 PDF + Markdown（扁平目录）
│       │   ├── 季报/              # 巨潮资讯网季度报告 PDF + Markdown（按年分子目录）
│       │   └── 临时公告/
│       ├── 研报/
│       ├── 纪要/
│       ├── 收集/
│       ├── 重要文件/
│       ├── 内部报告/             # 内部研究报告：评级/跟踪/深度/其他
│       │   ├── 评级报告/
│       │   ├── 跟踪报告/
│       │   ├── 深度报告/
│       │   └── 其他材料/
│       └── Agent/                 # 建模 Agent 的运行时与机器产物
│           ├── data.db            # SQLite（raw_tushare/meta/clean_annual/clean_quarterly）
│           ├── core_metrics_overview.md/json/csv
│           ├── defaults.yaml      # YAML2 默认参数集（生成产物）
│           ├── yaml1*.yaml        # compiler 输出的判断覆盖层
│           ├── financial_expense.yaml
│           ├── recon/             # reconciler / financial_expense_analyzer 生成的 evidence JSON
│           ├── .modelking/        # 内部编译缓存：forecast_params/report
│           └── forecast/          # 唯一正式 DCF 输出
│               ├── forecast_is.csv
│               ├── forecast_bs.csv
│               ├── forecast_cf.csv
│               ├── full_is.csv
│               ├── full_bs.csv
│               ├── full_cf.csv
│               ├── dcf_detail.csv
│               ├── dcf_summary.json
│               └── run_manifest.json
├── vendor/
│   └── use_cninfo/                # vendored rollysys/use_cninfo（MIT）
└── TushareOfficialAPIMD/          # TuShare 官方 skill 导出的接口 Markdown
    ├── income.md                  # income
    ├── balancesheet.md            # balancesheet
    ├── cashflow.md                # cashflow
    └── ...                        # 其他官方财务接口
```

---

## 9. 已验证公司与暴露的口径教训

已端到端验证 5 家（安克创新 300866 / 新乳业 002946 / 伊利股份 600887 / 美的集团 000333 / 比亚迪 002594），年度+季度全部硬校验通过。具体行数、meta、市值等运行时数据随重拉漂移，不在此沉淀——查 `companies/{公司}/Agent/data.db` 即得。各公司暴露的系统性口径问题（已在源头修复，对接手者有设计含义）：

| 公司 | 暴露的系统性问题 | 修复方式 |
|------|------------------|----------|
| 伊利 600887 | `int_income` 计入 `total_revenue`；`const_materials` 未分类；季报 `int_receiv`/`specific_payables` 口径重叠 | IS 1.6 改 `total_revenue=Σrevenue_item` 检测；补 `BS_FIELD_CATEGORIES`；`COMBO_RESOLVE` 适配 |
| 美的 000333 | `lending_funds`（发放贷款和垫款）TuShare 漏披露 → BS 2.1 `target_gt_calc` | reconciler 从年报 Markdown 补数 + approved override |
| 比亚迪 002594 | `oth_eqt_tools_p_shr`/`oth_eq_ppbond` 重复计入权益；`estimated_liab` 列报为流动而非默认非流动 | 改归 `sub_item`；override `clean_category` per-period 重分类 |

**clean 表列恒等**：所有公司 `clean_annual`/`clean_quarterly` 均为 332 列（`period` + 325 官方字段 + 6 QA plug）；公司缺某科目则值全 0，列恒保留，保证下游统一特征集。

---

## 10. 设计决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 存储 | SQLite（每公司一个 db） | 单机离线、零运维、事务保护、EAV→宽表转换方便 |
| 数据模型 | raw_tushare/meta + clean_annual/clean_quarterly | raw_tushare 保留 TuShare 三表官方完整字段；SQLite clean 表提供统一的 `period`+325 官方字段+6 QA plug 字段 |
| 字段命名 | 只用 TuShare 官方名 | 消除别名歧义，与上游对齐 |
| 金额单位 | 百万元 | A 股报表精度到元，百万元级适合分析和校验 |
| 校验容差 | 年度/季度 1 百万元、入库前 0.01 百万元 | 年度与季度均保持严格口径 |
| TuShare 接入 | 官方源 `api.waditu.com/dataapi` | raw_tushare 只接受官方源返回 |
| 跨端点消歧 | `endpoint.field` 前缀 | credit_impa_loss 在 income/cashflow 中值不同 |
| cninfo 接入 | vendored `rollysys/use_cninfo` | 直接复用成熟的 `hisAnnouncement/query`、orgId、PDF 下载封装，避免重复维护接口细节 |
| NULL vs 0 provenance | `null_fields_by_period`（`wide.attrs`，fillna 前捕获 income 端 NULL 字段） | `fillna(0.0)` 把 TuShare NULL 抹成 0，validator 无法区分"数据源缺口"与"公司真报 0"。provenance 只喂 validator（compute 路径仍吃 fillna 后数字），让 IS 1.2 的 operating_adjustment NULL 缺口硬失败进 reconciler，而非被 `missing_optional` 静默放行。reconciler `collect_failures` 同步取此 provenance 传 `check_is`，`llm_override_suggestions` 加联合闭合处理多字段联合缺失 |
| 年报文件命名 | `{年份}_年度报告.pdf/.md` / `{年份}_年度报告_修订版.pdf/.md` | 同年份原始版与修订版可并存，文件已存在时跳过 |

---

## 11. 变更日志

变更日志已分离至 [`docs/CHANGELOG.md`](./CHANGELOG.md)。本节不再在本文档维护，每次开发完成后在该文件按日期倒序追加里程碑条目。

---

## 附录 A：命名双语对照表

| 设计文档/中文名 | 代码/文件名 | 说明 |
|---|---|---|
| 清洗yaml1.py | `src/yaml1_cleaner.py` | 理解层的 clean.py |
| 逐年标准参数表 | `Agent/.modelking/forecast_params.yaml` | yaml1_cleaner 输出，calc.py 唯一输入 |
| 核心假设.md | `skills/核心假设生成修改器_skill_v17.md` | 由 skill 拥有；设计文档版本号需同步 |
| compiler / yaml1compiler | `skills/yaml1compiler_v4 (2).md` | 设计文档版本号需与磁盘一致 |
| YAML2 | `defaults.yaml` | 同物两名 |
| 三棒 pipeline | `src/forecast.py` 编排 `yaml1_cleaner.py` + `src/calc.py` | `forecast.py` 是实际编排器 |
| 年报清洗器 | `src/report_downloader.py` + `src/annual_report_extractor.py` | 设计文档未精确对应，以代码为准 |
| DCF build 快照 | `Agent/.modelking/forecast_build.json` | 供工作台 sensitivity 复用 |
| 季度跟踪层 | `src/quarterly_tracker.py` + workbench「季度展示」 | `forecast_is.csv` 年度预测 + `clean_quarterly` 实际 + `quarterly_overrides` 覆盖现算四态季度 IS |

