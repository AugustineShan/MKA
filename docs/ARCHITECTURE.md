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
      ↓  YAML2 defaults_gen.py
   defaults.yaml（YAML2：机器平推底座）
      +  yaml1*.yaml（compiler 输出：人的判断覆盖层）
      ↓  forecast.py（内部调用 yaml1_cleaner.py + calc.py）
   forecast/ 三表 + DCF summary
```

同时提供一个独立的公告下载入口：通过巨潮资讯网 cninfo `hisAnnouncement/query`
接口查询上市公司年度报告公告，并批量下载中文年度报告 PDF，同时用 PyMuPDF 提取全文 Markdown。

**核心目标**：从 TuShare 拉取原始三表数据，经严格配平校验后写入可信赖的年度/季度清洗表；在 clean 数据之上生成无主观预测的 YAML2 默认参数，并把 compiler 产出的 `yaml1` 判断覆盖层清洗成标准参数后跑出会计配平的 DCF 预测三表。任何一条历史 hard check 不通过即停止，年度/季度残差均必须 < 1 百万元；预测阶段 BS/CF 会计恒等式不配平也必须失败。

**边界**：仅处理 A 股一般工商业（comp_type=1）财报数据，不覆盖金融企业、港股美股或行情 K 线。`defaults.yaml` 是唯一 YAML2，表示“什么都不变会怎样”的机器平推底座；`yaml1` 是稀疏判断覆盖层，`calc.py` 永远看不到 yaml1，只吃清洗后的标准参数。

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
│  输出: companies/{公司名}_{代码}/annuals/{年份}_年度报告.pdf/md│
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 模块职责

### 3.0 init.py（一键编排入口）

`init.py` 是给 Agent / 人的单一入口，把 data_fetcher → report_downloader → clean →
financial_expense_analyzer 四个独立 CLI 按正确顺序编排成全流程，并保证幂等与如实上报。配套
`.claude/skills/init/SKILL.md` 让 Agent 用 `init <公司>` 触发。

| 组件 | 职责 |
|------|------|
| `resolve_ticker()` | 公司名 / 裸代码 / 完整 ticker → 规范 ticker；中文名经 TuShare `stock_basic` 解析，歧义/无匹配抛 `TickerResolutionError`（退出码 2，交 Agent 用 websearch 兜底） |
| `stage_fetch()` | 阶段①拉取；幂等：当日 `meta.last_updated` 已是今天则跳过（除非 `--force`），否则 UPSERT 增量 |
| `stage_reports()` | 年报 PDF/Markdown 下载（**必须在 clean 之前**，否则失败时 reconciler 无年报可切片）；report_downloader 自身幂等，下载失败不致命 |
| `stage_clean()` | 阶段②清洗校验，含"年度失败→生成 override→重跑应用"两段式；用 `approved_override_count()` 比对前后判断是否新增补数 |
| `stage_financial_expense()` | 阶段③：从年报附注切片「财务费用」明细，LLM 拆出利息支出/资本化利息/财政贴息/利息收入/其他，按年份归档到 `financial_expense.yaml`；失败只 warning，不阻塞管线 |
| `build_report()` | 输出数据拉取报告：四阶段状态 + 年度/季度期数 + `clean_adjustments`（年报确认补全科目）+ `clean_warnings` 汇总 |

**编排链路**：
```
输入 → resolve_ticker → stage_fetch → stage_reports → stage_clean
                                                          ├─ 首跑过 → stage_financial_expense → 退出码 0
                                                          └─ 年度失败 → reconciler 生成 override
                                                               → 重跑 clean 应用补数
                                                                    ├─ 过 → stage_financial_expense → 退出码 0
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

### 3.0a webka.py（网页端核心假设打包器）

`webka.py` 是 `/ka` 的网页端前置打包器，用于把生成 `核心假设.md` 所需的源文件一键汇总到 `companies/{公司}/WEBCLAUDE/核心假设部分/`，方便用户在 Claude.ai 网页端拖拽上传。

与 `/ka` 的区别：
- `/ka` 在 Claude Code 本地执行，直接读取文件系统并调用核心假设生成修改器 skill。
- `/webka` 只负责**复制源文件和执行 skill 到固定文件夹**，本身不做判断、不生成核心假设；生成工作交给网页端完成。

**复制清单**（按阅读顺序加序号前缀）：

| 序号文件 | 来源 | 是否必须 |
|---|---|---|
| `00_公司判断和最新观点.md` | `companies/{公司}/公司判断和最新观点.md` | **必须**，不存在则报错 |
| `01_核心假设_现有底稿.md` | `companies/{公司}/*核心假设*.md` 最新一份 | 可选，init 模式无则跳过 |
| `02_活跃素材_xxx` | `active_vore/` 中时间最新文件 | 可选 |
| `03_最新年报_202X_年度报告.md` | `annuals/` 最新一年年报 Markdown | 可选，**永远不打包 PDF** |
| `04_核心假设生成修改器_skill_vN.md` | `D:\MKA\skills\` 最新版 | 可选，网页端执行时需要 |

**关键纪律**：
- 每次执行先清空 `WEBCLAUDE/核心假设部分/` 再复制，防止过时文件污染。
- 所有 skill（包括 `/ka`、`/webka` 及核心假设生成修改器）**均不读取 PDF**；年报只打包已生成的 Markdown。
- 若仅有 PDF，报告会提示用户先运行 `python -m src.report_downloader --ticker ... --force-markdown` 生成年报 Markdown。

**退出码语义**：

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 2 | 输入无法解析为唯一公司目录 |
| 3 | 缺少 `公司判断和最新观点.md` |
| 1 | 其他 IO 异常 |

**CLI**：
```bash
python -m src.webka 新乳业
python -m src.webka 002946
python -m src.webka 002946.SZ
```

配套 skill 文件同时部署于：
- `D:\MKA\.claude\skills\webka\SKILL.md`
- `C:\Users\Sheld\.claude\skills\webka\SKILL.md`

### 3.0b `/comp` skill（yaml1 compiler 启动器）

`/comp` 是 `/ka` 的 compiler 兄弟。它不负责生成 `核心假设.md`，而是把已有的 `核心假设.md` 编译成机器可读的 `yaml1_公司名_YYYYMMDD.yaml`，供 `forecast.py` 使用。

**执行顺序**（必须遵守）：
1. 解析公司目录。
2. **先动态加载最新版 `yaml1compiler` skill**：扫描 `D:\MKA\skills\`，匹配 `yaml1compiler_v*.md`，取版本号最大。
3. 再读取四份输入材料：
   - `companies/{公司}/*核心假设*.md` 最新一份（语义层：判断、历史、旋钮、时间轴、覆盖项）
   - `companies/{公司}/defaults.yaml`（目标命名空间）
   - `docs/数据格式参考.md`（中文科目 ↔ TuShare 字段字典）
   - `docs/yaml1算法模板契约.md`（cleaner/calc 支持的算法模板硬边界）
4. 按加载到的 compiler skill 执行编译。
5. 输出：`companies/{公司}/yaml1_公司名_YYYYMMDD.yaml`。

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

### 3.0c webcomp.py（网页端 yaml1 compiler 打包器）

`webcomp.py` 是 `/comp` 的网页端前置打包器，用于把编译 yaml1 所需的四份输入材料一键汇总到 `companies/{公司}/WEBCLAUDE/yaml1编译部分/`，方便用户在 Claude.ai 网页端上传后执行 compiler。

与 `/comp` 的区别：
- `/comp` 在 Claude Code 本地执行，动态加载 `yaml1compiler` skill 后直接编译。
- `/webcomp` 只负责**复制输入材料和执行 skill 到固定文件夹**，本身不执行编译；编译工作交给网页端完成。

**复制清单**（按阅读顺序加序号前缀）：

| 序号文件 | 来源 | 是否必须 |
|---|---|---|
| `00_核心假设.md` | `companies/{公司}/*核心假设*.md` 最新一份 | **必须**，不存在则报错 |
| `01_defaults.yaml` | `companies/{公司}/defaults.yaml` | **必须**，不存在则报错 |
| `02_数据格式参考.md` | `D:\MKA\docs\数据格式参考.md` | 可选 |
| `03_yaml1算法模板契约.md` | `D:\MKA\docs\yaml1算法模板契约.md` | 可选 |
| `04_yaml1compiler_skill_vN.md` | `D:\MKA\skills\` 最新版 | 可选，网页端执行时需要 |

**关键纪律**：
- 每次执行先清空 `WEBCLAUDE/yaml1编译部分/` 再复制，防止过时文件污染。
- 所有 skill（包括 `/comp`、`/webcomp` 及 yaml1compiler）**均不读取 PDF**。
- `defaults.yaml` 是目标命名空间；`docs/数据格式参考.md` 和 `docs/yaml1算法模板契约.md` 是只读契约。

**退出码语义**：

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 2 | 输入无法解析为唯一公司目录 |
| 3 | 缺少 `*核心假设*.md` 或 `defaults.yaml` |
| 1 | 其他 IO 异常 |

**CLI**：
```bash
python -m src.webcomp 新乳业
python -m src.webcomp 002946
python -m src.webcomp 002946.SZ
```

配套 skill 文件同时部署于：
- `D:\MKA\.claude\skills\webcomp\SKILL.md`
- `C:\Users\Sheld\.claude\skills\webcomp\SKILL.md`

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
clean("path/to/data.db", "300866.SZ") -> pd.DataFrame
```

**CLI**：`python -m src.clean --ticker 300866.SZ [--db path] [--verbose]`

#### 3.2.1 会计系统（field_registry）怎么用

`src/field_registry.yaml` 是三表 325 个 TuShare 官方字段的**会计元数据唯一真源**。`clean.py` 的校验分类、`workbench.py` 的前端排序与标签、`docs/数据格式参考.md` 全部从它派生。改一处,三处同步,不再有并行声明漂移。

**YAML 结构**(每个 statement 一个块):

```yaml
statements:
  income:                       # 顶层 key = income / balancesheet / cashflow
    name: 利润表
    unit: 百万元
    category_order:             # 展示桶顺序(不含 subtotal——subtotal 是内联小计,非展示桶)
      [revenue_item, cost_item, operating_adjustment, ...]
    category_labels:            # 全 category → 中文标签(含 subtotal)
      revenue_item: 收入项
      subtotal: 小计/合计
      ...
    fields:                     # ← 有序列表,顺序 = 会计准则序 = 前端展示序
      - {field: revenue, label: 营业收入, category: revenue_item}
      - {field: oper_cost, label: 减:营业成本, category: cost_item}
      - {field: total_cogs, label: 营业总成本, category: subtotal}      # 小计就插在它该出现的位置
      - {field: invest_income, label: 投资收益, category: operating_adjustment,
         resolve_children: [ass_invest_income, amodcost_fin_assets]}
      - {field: ass_invest_income, label: '其中:对联营和合营企业的投资收益',
         category: sub_item, resolve_parent: invest_income}
      - {field: assets_impair_loss, label: '减:资产减值损失',
         category: operating_adjustment, sign: questionable}
      - {field: total_assets, label: 资产总计, category: subtotal, role: total}  # BS 总计粗体
```

**字段维度**(每条 field 最多七维):

| 维度 | 必填 | 说明 |
|------|------|------|
| `field` | 是 | TuShare 官方字段名 |
| `label` | 是 | 中文展示标签,直接带"减:/其中:"前缀 |
| `category` | 是 | bucket 归类(revenue_item / cost_item / subtotal / current_asset / ...) |
| `resolve_children` | 否 | 父项 → 子明细列表(IS/CF 合并科目拆分) |
| `resolve_parent` | 否 | 子项 → 父项(反向索引,文档用) |
| `sign` | 否 | `questionable` = 符号已带会计含义(三个减值科目) |
| `role` | 否 | `total` = BS 三个总计粗体;缺省按 `category==subtotal` 判小计 |
| `combo_of` | 否 | BS 合并科目 → 拆分项列表(combo category 专用) |

**谁消费它:**

| 消费方 | 从 registry 取 | 取代了改版前的 |
|--------|---------------|---------------|
| `clean.py` | `IS/BS/CF_FIELD_CATEGORIES`·`IS/BS_SUB_RESOLVE`·`COMBO_RESOLVE`·`SIGN_QUESTIONABLE_IS_FIELDS`(via `from .field_registry import`) | 手维护的分类字典 |
| `workbench._statement_rows` | `stmt.field_order`(直接迭代,小计内联)+ `stmt.labels` + `stmt.field_categories` + `stmt.total_fields` | `FIELD_REFERENCE` 解析 + `field_order`/`category_order`/`subtotal_after` + `LABEL_OVERRIDE` 五源合流 |
| `docs/数据格式参考.md` | `scripts/gen_field_reference.py` 从 registry 派生 | stale 的手生成文档 |

**怎么改(常见操作):**

1. **改某字段分类**(如把 X 从 cost_item 移到 operating_adjustment):编辑 `field_registry.yaml` 改该字段的 `category`,跑 `python -m scripts.gen_field_reference` 重生文档,跑 `python -m pytest tests/test_field_registry.py`。clean.py 的 bucket 求和自动跟进(它读 registry)。
2. **改某字段展示顺序**:在 `fields` 列表里挪那一行。顺序就是会计序。
3. **改中文标签**:改该字段 `label`(含"减:"前缀就写进 label)。
4. **加新字段**(罕见,通常是 TuShare 新增官方字段):在对应 statement 的 `fields` 加一条,category 必须在 `category_labels` 里;若是新 category,同时在 `category_order`/`category_labels` 登记。

**不要做的事:**

- ❌ 不要在 `clean.py` 里改分类——`IS/BS/CF_FIELD_CATEGORIES` 等已是从 registry import 的别名,改不动(改了也会被下次 import 覆盖)。
- ❌ 不要在 `workbench.py` 里加排序/标签——`STATEMENT_META` 已瘦身到只剩 key/name/title/unit,排序标签全在 registry。
- ❌ 不要手改 `docs/数据格式参考.md`——它是生成物,跑 `gen_field_reference` 重生。

**边界(B1):** `check_is/bs/cf` 里的 subtotal 公式(`total_cogs = sum(cost_item)` 等)仍写在代码里,不数据驱动。registry 只统元数据,不统校验公式——check 函数已稳定(美的/紫金/茅台/比亚迪/万科/三一全过),数据驱动重写是另一个独立重构,风险不值。`known_tushare_defects.json` 也独立保留,未并入 registry(它是 reconciler 的 LLM 检索提示,不是字段元数据)。

**长期守卫:** `tests/test_field_registry.py` 锁 9 条不变量(字段数 86/150/89、每字段有标签且 category 在 category_labels、resolve/combo 引用真实存在、total_fields 是 subtotal、sign_questionable ⊆ IS、credit_impa_loss 漂移已修、field_order 覆盖全字段无重复、subtotal 不在 category_order)。

### 3.3 report_downloader.py（年报/季报 PDF + Markdown 下载）

| 组件 | 职责 |
|------|------|
| `parse_ticker()` | 校验并解析 `000333.SZ` / `600519.SH` / `430047.BJ` |
| `fetch_company_info()` | 调用 cninfo `topSearch/query` 获取公司简称与 `orgId` |
| `iter_company_category()` | 复用 vendored `cninfo.api.query_page()` 翻页查询指定 category 的公告 |
| `parse_report()` | 标题过滤，匹配年报/一季报/半年报/三季报本体；`年+` 容忍 cninfo 录入重复"年"字（如三一 2020 `2020年年年度报告`），版本尾缀白名单（全文/正文/修订版/更正版/更新版/取代版/正式版/最终版，裸写或全半角括号）+ `$` 锚定容忍正文版本变体同时挡住非正文尾串；修订类（修订版/更正版/更新版/取代版）→ `_修订版` 命名；排除摘要、补充公告/更正公告/更新公告、取消、英文、审计/内控/鉴证/提示性公告等非正文（用完整短语而非裸"更新/更正"，避免与"更新版/更正版"正文版本相撞） |
| `collect_reports()` | 对多个 cninfo category 分别查询；按 category 检测漏匹配（若某 category 返回了公告但 0 条匹配成功，或存在疑似定期报告本体却未被匹配，则输出 warning）；合并去重时优先保留 `全文` 而非 `正文`，按年份从新到旧排序。`main()` 在 `collect_reports()` 之后按 `--min-year` 丢弃该年之前的报告（2010 闸门，与 `clean.RECONCILE_MIN_YEAR` 对齐），不下载、不抽 Markdown |
| `render_markdown()` | 复用 vendored `cninfo.parser` 的 PyMuPDF 能力，从 PDF 提取全文 Markdown |
| `download_reports()` | 下载 PDF 并生成 Markdown；年报放 `annuals/`，季报放 `quarterlyreports/{year}/`；`--all-reports` 时年报+季报共用单一线程池（`quarterly_target_dir` 按 kind 分流目录），目标文件已存在则跳过 |

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
├── annuals/                          # 年报（扁平目录）
│   ├── 2025_年度报告.pdf
│   ├── 2025_年度报告.md
│   ├── 2024_年度报告.pdf
│   ├── 2024_年度报告.md
│   ├── 2024_年度报告_修订版.pdf
│   └── 2024_年度报告_修订版.md
└── quarterlyreports/                 # 季报（按年分子目录）
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
| `yaml1_cleaner.py` | 理解层 clean.py：读取 `yaml1*.yaml + defaults.yaml`，折叠 decomposition、展开 fade、resolve 到标准参数并做历史回测硬闸；支持无 yaml1 的恒等清洗（`--defaults-only`），中间产物默认写入 `.modelking/` |
| `forecast.py` | **编排器**：读取 `yaml1*.yaml + defaults.yaml`，调用 `yaml1_cleaner.py` 生成逐年标准参数，再调用 `calc.py` 生成 `forecast/` 与内部产物；用户正式入口 |
| `calc.py` | 纯算账核：只吃清洗后的逐年标准参数表（`--forecast-params`），按 IS→BS→CF→DCF 顺序生成预测；永远看不到 yaml1，也不直接读取 `defaults.yaml` |

**Formula/DAG 边界**：复杂 Excel 关系（滞后链、分段函数、中间变量复用、DAG）只允许在 `yaml1_cleaner.py` 内求值，先压平成收入折叠或 YAML2 标准路径覆盖，再交给 `calc.py`。`calc.py` 仍保持纯算账核，不直接理解 formula。完整设计与约束见 `docs/formula_DAG开发文档.md`；生成口径以 `docs/yaml1算法模板契约.md` 为准。

**CLI**：
```bash
python -m src.defaults_gen --ticker 300866.SZ
python -m src.defaults_gen --db companies/安克创新_300866/data.db --output companies/安克创新_300866/defaults.yaml
py -m src.yaml1_cleaner --defaults-only --ticker 002946.SZ   # YAML2 baseline 恒等清洗
py -m src.forecast --ticker 002946.SZ                        # 正式入口（有 yaml1）
py -m src.calc --forecast-params companies/新乳业_002946/.modelking/forecast_params.yaml
```

`calc.py` 只接受 `--forecast-params` 一个输入，是纯粹的低层算账核/回归工具。`defaults.yaml` 进入 `calc.py` 的唯一合法路径是先经过 `yaml1_cleaner.py`（无 yaml1 时为恒等清洗），生成 `.modelking/forecast_params.yaml`。

**公司目录契约**：
```
companies/{公司名}_{代码}/
├── defaults.yaml
├── yaml1*.yaml
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

`forecast/` 是唯一正式 DCF 输出目录，每次重算必须先清空再生成。`forecast_current/forecast_fixed/forecast_yaml1` 这类目录只能是历史调试产物，不能作为正式链路输出。`yaml2_yearly.yaml` 不是合法顶层产物：清洗后的逐年标准参数表不是 YAML2，默认只能作为内部编译缓存写入 `.modelking/forecast_params.yaml`。

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
6. DCF：`FCFF = NOPAT + D&A - CAPEX - ΔNWC`，折现显式期 FCFF + 终值，得到 EV、股权价值和每股价值。`calc.py` 内部把"三表/显式期 FCFF 构建"与"DCF 估值"拆成两层：`build_forecast_statements()` 只负责 IS→BS→CF 和原始 FCFF；`value_from_statements()` 负责贴现、稳态终值和每股价值。终值改用**稳态 terminal FCFF**：`ΔNWC = 0`，`CAPEX = D&A × terminal_capex_da_ratio`（默认 1.0），即 `terminal_fcff = last_nopat + last_da × (1 - ratio)`，再按 Gordon Growth 外推。`model.terminal_capex_da_ratio` 与 `model.wacc`、`model.terminal_growth` 一起构成 DCF 层三个可调参数，修改时只重跑 `value_from_statements()`，不重建三表。`forecast.py` 跑完后把最小 build 状态写入 `.modelking/forecast_build.json`，供工作台 sensitivity 端点实时重算。

**验证样本**：当前 5 家公司（安克创新、新乳业、伊利股份、美的集团、比亚迪）均已生成 YAML2 并跑通 calc，BS/CF 残差为浮点误差级；比亚迪触发负现金 review flag，未阻断配平计算。

### 3.5 本地 Web 工作台（FastAPI + React）

本地 Web 工作台把公司文件夹变成可浏览的投研模型页。它不是另一个建模引擎，只是 `companies/{公司名}_{代码}/` 的本地 UI：读 `核心假设.md`、`yaml1*.yaml`、`forecast/`、`active_vore/` 等文件，并通过 `src.forecast` 触发 DCF 重算。

| 组件 | 职责 |
|------|------|
| `app/` | React + Vite 前端；公司列表、Overview、核心假设渲染、YAML1/Xcode 风 source view、DCF/三表、素材文件浏览 |
| `src/workbench.py` | FastAPI 本地壳；扫描 `companies/`，读取本地文件，调用 `src.forecast.run_company_forecast()` |
| `src.forecast` | 仍是唯一正式 DCF 运行入口；前端按钮只调用它，不复刻模型逻辑 |

第一版是只读展示 + 一键重算，不直接编辑 `核心假设.md` 或 `yaml1`。DCF tab 额外提供三个实时 sensitivity 滑块（WACC、terminal growth、terminal CAPEX / D&A ratio），调用 `POST /api/companies/{id}/dcf-sensitivity` 即时刷新每股价值，无需重跑三表。视觉遵循 Apple HIG / SF Pro：白/灰系统底色、单一 #0071E3 交互蓝、轻边框和轻阴影；金融表格数字右对齐、SF Mono、负数红色、轻 zebra；YAML 面板是唯一允许多语法色的区域。

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
- 输出目录为 `companies/{公司名}_{代码}/recon/`，包含时间戳 JSON、`annual_report_reconciliation_latest.json` 与可选 `annual_report_overrides.json`
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

### 6.5 财务费用细则分析（外置 evidence 生成器）

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
6. 写入 `companies/{公司}/financial_expense.yaml`（多年档案）；同时保留 `recon/financial_expense_detail_latest.json` 作为最近一次单期运行的调试/审计副本。

`defaults_gen.py` 读取 `financial_expense.yaml`，仅在记录 `status=approved`、`confidence=high`、勾稽全过且 `base_period` 与 YAML2 `base_period` 匹配时，才用该年 derived 值覆盖 `interest_expense_rate`、`cash_interest_rate`、`other_fin_exp_abs`、`base_interest_expense`、`base_interest_income`，并将 `source` 改为 `annual_report.fin_exp_note`；否则保持机械值。`init.py` 在 `stage_clean()` 之后调用 `stage_financial_expense()` 生成全量档案，失败只 warning，不阻塞后续流程。

CLI：

```bash
python -m src.financial_expense_analyzer --ticker 002946.SZ        # 全量生成 financial_expense.yaml
python -m src.financial_expense_analyzer --ticker 002946.SZ --force  # 强制重新生成
python -m src.financial_expense_analyzer --ticker 002946.SZ --latest-only  # 只分析最新一年并写 debug JSON
```

新乳业（002946.SZ）实测：10 个 clean_annual 年份中 8 个生成 approved high 记录（2015/2016 因缺年报 Markdown 报错），2024 基期 `interest_expense_gross=124.15M`、`capitalized=14.06M`、`subsidy=3.82M`；detected basis 为 `net_of_capitalized_and_subsidy`，即 TuShare `fin_exp_int_exp` 已同时净掉资本化利息与财政贴息；derive 后 `interest_expense=110.09M`、`other_fin_exp_abs=-1.47M`。

### 6.6 季度 QA plug 收纳科目

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
| YAML1 (drivers) | `skills/yaml1compiler_v4 (2).md` | `src/yaml1_cleaner.py` | 定稿 | `companies/{公司}/yaml1*.yaml` |
| YAML1 formula/DAG 开发契约 | `docs/formula_DAG开发文档.md` | `src/yaml1_cleaner.py`, compiler/core-assumption skills, tests | 实验性·受限（仅合成 fixture 验证） | `docs/formula_DAG开发文档.md` |
| YAML2 / defaults.yaml | `src/yaml2_schema.py` | `src/yaml1_cleaner.py`, `src/defaults_gen.py` | 稳定 | `companies/{公司}/defaults.yaml` |
| 逐年标准参数表 | `src/yaml1_cleaner.py` | `src/calc.py` | 稳定 | `companies/{公司}/.modelking/forecast_params.yaml` |
| yaml1 清洗报告 | `src/yaml1_cleaner.py` | 工作台 / 人 | 稳定 | `companies/{公司}/.modelking/yaml1_clean_report.json` |
| DCF build 快照 | `src/forecast.py` | `src/workbench.py`（sensitivity） | 稳定 | `companies/{公司}/.modelking/forecast_build.json` |
| DCF 运行清单 | `src/forecast.py` | 工作台 / 人 | 稳定 | `companies/{公司}/forecast/run_manifest.json` |
| 财务费用档案 | `src/financial_expense_analyzer.py` | `src/defaults_gen.py` | 稳定 | `companies/{公司}/financial_expense.yaml` |
| 年报补数 override | `src/annual_report_reconciler.py` | `src/clean.py` | 稳定 | `companies/{公司}/recon/annual_report_overrides.json` |
| 年报核对 evidence | `src/annual_report_reconciler.py` | 人 / 审计 | 稳定 | `companies/{公司}/recon/*_reconciliation.json` |
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
│   ├── webka.py                   # 网页端核心假设打包器：汇总源文件到 WEBCLAUDE/核心假设部分/
│   ├── webcomp.py                 # 网页端 yaml1 compiler 打包器：汇总输入材料到 WEBCLAUDE/yaml1编译部分/
│   ├── data_fetcher.py            # 阶段①：TuShare 拉取 + 标准化 + 入库
│   ├── clean.py                   # 阶段②：EAV→宽表 + 配平校验 + clean 表写入（字段分类/resolve 从 field_registry import）
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
│   ├── forecast.py                # 正式入口：defaults.yaml + yaml1*.yaml → forecast/
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
│       ├── data.db                # SQLite（raw_tushare/meta/clean_annual/clean_quarterly）
│       ├── defaults.yaml                 # YAML2 默认参数集（生成产物）
│       ├── yaml1*.yaml                  # compiler 输出的判断覆盖层
│       ├── .modelking/                   # 内部编译缓存：forecast_params/report
│       ├── forecast/                     # 唯一正式 DCF 输出
│       │   ├── forecast_is.csv
│       │   ├── forecast_bs.csv
│       │   ├── forecast_cf.csv
│       │   ├── full_is.csv
│       │   ├── full_bs.csv
│       │   ├── full_cf.csv
│       │   ├── dcf_detail.csv
│       │   ├── dcf_summary.json
│       │   └── run_manifest.json
│       ├── annuals/               # 巨潮资讯网年度报告 PDF + Markdown（扁平目录）
│       │   ├── {年份}_年度报告.pdf
│       │   └── {年份}_年度报告.md
│       ├── quarterlyreports/      # 巨潮资讯网季度报告 PDF + Markdown（按年分子目录）
│       │   └── {年份}/
│       │       ├── {年份}_第一季度报告.pdf
│       │       ├── {年份}_半年度报告.pdf
│       │       └── {年份}_第三季度报告.pdf
│       └── recon/                 # reconciler / financial_expense_analyzer 生成的 evidence JSON
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

已端到端验证 5 家（安克创新 300866 / 新乳业 002946 / 伊利股份 600887 / 美的集团 000333 / 比亚迪 002594），年度+季度全部硬校验通过。具体行数、meta、市值等运行时数据随重拉漂移，不在此沉淀——查 `companies/{公司}/data.db` 即得。各公司暴露的系统性口径问题（已在源头修复，对接手者有设计含义）：

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
| 年报文件命名 | `{年份}_年度报告.pdf/.md` / `{年份}_年度报告_修订版.pdf/.md` | 同年份原始版与修订版可并存，文件已存在时跳过 |

---

## 11. 变更日志

> 完整逐条变更见 `git log`。本表只留里程碑级架构变更，避免与 git 历史重复。

| 日期 | 里程碑 |
|------|------|
| 2026-06-22 | **field_registry 统一会计科目与排序**:三表 325 字段元数据(分类/会计序/标签/resolve/sign/role)统一进 `src/field_registry.yaml`(单一真源)。`clean.py` 的 `IS/BS/CF_FIELD_CATEGORIES`·`SUB_RESOLVE`·`COMBO_RESOLVE`·`SIGN_QUESTIONABLE` 与 `workbench.py` 的三表渲染排序/标签都改为 `from .field_registry import`;`数据格式参考.md` 由 `scripts/gen_field_reference.py` 从 registry 派生。消除改版前 5 处并行声明(clean 分类/workbench field_order+category_order+subtotal_after/LABEL_OVERRIDE/数据格式参考.md)的漂移。flat 有序列表=会计序;label 带"减:"前缀,LABEL_OVERRIDE 溶解;BS 三总计 `role:total`。check_* 公式留代码(B1,不数据驱动)。修 stale drift:`credit_impa_loss`/`assets_impair_loss`/`oth_impair_loss_assets` 旧文档误标 cost_item,统一为 clean.py 真值 operating_adjustment。等价性闸门 + 茅台/比亚迪/万科/三一 6 次 clean 回归(年度+季度,331 字段不变)验证 day-1 行为一致;`tests/test_field_registry.py` 长期守一致性。设计稿 `docs/plans/2026-06-22-field-registry-design.md` |
| 2026-06-19 | 「核心假设展示」(YAML1) tab 重构为**三区一表一轴**：① 收入拆分 / ② 关键假设 / ③ 参考项，每区一张 `UnifiedYearTable`（`table-layout: fixed`、共享年份轴、缺数据留空），彻底解决"多张表各用各的年份轴、对不齐"。① 总收入(营业收入+同比)+主拆分·业务线(各线 收入/同比/销量)+副拆分(地域/子公司)合并进一表，副拆分（stash name 含「拆分」）上移紧跟主拆分；总收入历史从完整 IS 表 `revenue` 补全。② 各 knob section 合并进一表，组标题分隔，+三段式块。③ 历史观测+核对项合并进一表（2014-2024 轴），非年份块（分线 attr/口径/溯源/定性）折叠在表下。`AxisRow.format` 区分 int/num2/decimal/signedDecimal/volume（修比率被 formatNumber 截成 0 的 bug）；`humanizeUnit` 中文化单位（million_cny→百万元、100mn_cny(存疑)→亿元·存疑、pct→%）。后端 `_humanize_label`/`_humanize_path` 中文化 stash 行/列标签与 terminal 路径（复用 FIELD_LABELS+STASH_CODE_LABELS，展示层不碰契约）。纯展示层，不改 yaml1，约定分派非公司特判 |
| 2026-06-18 | `report_downloader` 标题正则通用化：① `年+` 替代固定"年年"个数，兜住 cninfo 录入重复"年"字整类错误（三一重工 2020 `2020年年年度报告` 三个"年"曾整年漏下），任何重复次数都匹配；② 版本尾缀白名单（全文/正文/修订版/更正版/更新版/取代版/正式版/最终版，裸写或全/半角括号）+ `$` 锚定，容忍正文版本变体同时挡住"…补充公告/更正公告"等非正文尾串；修订类（修订版/更正版/更新版/取代版）→ `_修订版` 命名，正式版/最终版/全文/正文 → 原始版命名；③ `EXCLUDED_TITLE_KEYWORDS` 裸"更新"→"更新公告"、新增"补充公告/更正公告"，避免与正文版本"更新版/更正版"相撞。`KIND_TITLE_TAIL_VARIANTS`→`KIND_TITLE_STEMS`+`BODY_VERSION_*`+`REVISION_VERSIONS`，`_looks_like_periodic_report` 改用 `PERIODIC_REPORT_KEYWORDS` |
| 2026-06-10 | 数据基座成型：raw_tushare（EAV 官方镜像）+ clean_annual/clean_quarterly 宽表；BS/IS/CF 全字段穷尽分类（`*_FIELD_CATEGORIES`），替代手维护科目清单 |
| 2026-06-11 | 年报补全闭环：`annual_report_reconciler` + approved override 审计链 + 季度 QA plug；`init.py` 一键编排；默认 LLM 切 GLM |
| 2026-06-11 | YAML2/DCF 层上线：`yaml2_schema` + `defaults_gen` + `calc.py`（IS→BS→CF→DCF，财务费用循环求解） |
| 2026-06-14 | 理解层正式入口 `forecast.py`（`defaults.yaml + yaml1*.yaml → forecast/`）；ModelKing 只读 Web 工作台（`workbench.py` + `app/`）；财务费用细则分析器 |
| 2026-06-15 | `calc.py` 终值重构（稳态 terminal FCFF + DCF sensitivity 三参数实时调节）；`forecast.py` 拼接历史 `full_*.csv` |
| 2026-06-16 | formula/DAG 受限执行器落地（`yaml1_formula.py`，实验性·仅合成 fixture 验证）；回绿测试基线（冻结 fixture + 不变式，83 passed） |
| 2026-06-17 | reconciler 通用性加固（格力 000651 验证：30 个年度硬失败全靠年报证据配平，年度零 plug）：LLM 确认按 (period,code) 分片调用（单次大调用会 ReadTimeout 丢全部证据）；`call_llm` temperature→0 + 重试 + finish_reason 截断检测（根治"伪不稳定"）；默认超时兑齐 300s；年报 statement/term snippet 窗口放宽（覆盖含金融子公司的长合并报表）；单字段精确命中残差时抑制投机性 group；`target_lt_calc` 按 -residual 匹配负值缺失项（如终止经营净亏损）；子串别名碰撞抑制（"应收款项"⊂"应收款项融资"）；自动核对 max-failures 默认 20/12→60；新增 `receiv_financing`（应收款项融资）已知缺陷卡 |
| 2026-06-17 | LLM 调用并发化：`annual_report_utils.parallel_map`（有界、保序、异常透传）作为唯一并发开关（`LLM_MAX_WORKERS`，默认 6）；reconciler 的 (period,code) 分片确认与 `financial_expense_analyzer` 的逐年分析从串行循环改为并发——分片已相互隔离，每次调用各自保留超时/重试/`chunk_errors` 审计，输出经 `zip(order,…)` 保持字节级确定性；墙钟从"逐次相加"压成"最慢一次"，取数/下载不变 |
| 2026-06-17 | init 下载/核对提速四项：(1) 季报默认不再抽 markdown（`_download_single_report` 按 `report.kind=="annual"` 守卫，季报只下 PDF；年报仍抽 md），消除 40 份季报的 PyMuPDF 纯 CPU 浪费；(2) `--all-reports` 把年报/季报两次串行 `download_reports` 合并成单一线程池（`download_reports` 新增 `quarterly_target_dir` 按 kind 分流目录），`--max-workers` 默认 4→6；(3) reconciler Phase A（逐 failure 分析）从串行 `for` 改为 `parallel_map`，与 Phase B 一致保序/异常透传；(4) `.env` 设 `LLM_MAX_WORKERS=10`（Phase A/B 同时受益，代码零改动，429 由既有退避吸收） |
| 2026-06-18 | reconciler 剩余串行 + 2010 闸门：紫金矿业 601899 实测暴露 reconciler 全量跑 21 分钟挂死，定位为 `collect_rule_candidates` 串行 + `itertools.combinations` 爆炸（40 term snippet 驱动 matched_items 过大）+ `collect_failures` 全年跑 + override `failure_code` 按 period 误取。修：(1) `collect_rule_candidates` 改 `parallel_map`；(2) `MAX_TERM_SNIPPETS` 40→6，`matched_items` 进 combinations 前按"合理成员≤残差"过滤 + 封顶 16 防 C(N,4) 爆炸；(3) `collect_failures` 接 `only_period/only_code`，非目标 period 只携带期末现金不做重检查（消除 IS 1.2 全年 spam）；(4) `build_override_file_from_batch_llm` 按 (period, field) 查 failure，修 failure_code 张冠李戴。同时引入 **2010 闸门** `clean.RECONCILE_MIN_YEAR=2010`：2010 前年度硬校验失败降级为 warning 直接入库、不触发 reconciler，`collect_failures` 同步跳过 2010 前 |
| 2026-06-18 | 修紫金矿业 BS 4.1 权益合计 `target_lt_calc`（10 个年度全挂）：根因是 TuShare balancesheet `total_share` 是**股数（百万股）**而非股本(元)，clean.py 权益 bucket 把它当百万元与资本公积等相加——面值 1 元公司百万股=百万元碰巧平衡，紫金面值 0.1 元则 10× 偏（残差 23696.38 = total_share×0.9，精确）。TuShare 无独立股本(元)字段。修：clean.py 加 `infer_par_value`（面值为离散法定常量 1/0.1/0.5/...，按权益恒等式跨年搜索使配平期数最多的值，平票归 1.0），`check_bs` 加 `par` 参数，BS 4.1 用 `股本(元)=par×total_share` 参与求和（**仅校验折算，total_share 存储值不变**，下游每股计算安全）；`validate_wide`/reconciler `collect_failures` 同步推断 par。紫金 par=0.1 推断生效，BS 4.1 全部通过；新乳业等 par=1 公司零影响。属 clean.py 字段口径修复（target_lt_calc 归 clean.py，非 reconciler） |
| 2026-06-18 | /ka 防呆与命名澄清：① 核心假设底稿只认公司根目录 `核心假设*.md`、产物只写根目录（禁止 `WEBCLAUDE\` 等子目录自我污染，输入/输出两侧钉死）；② `核心观点.md` 更名为 `公司判断和最新观点.md`（同步 `init.py`/`webka.py`/ka/webka skill/v19 生成器/两份 doc + 磁盘文件 + 打包序号 `00_`），消除"核心观点 vs 核心假设"文件名混淆，无旧名兜底 |
| 2026-06-18 | LLM 升级 glm-5.2 + reconciler 两层 fallback（紫金矿业 601899 残余硬失败攻坚）：① `.env` `GLM_MODEL` glm-5-turbo→glm-5.2（智谱官方 API，裸串；`[1m]` 仅 Claude Code 显示标签非 API 参数）；② `call_llm` 对 model 含 "5.2" 的推理模型发 `thinking:{"type":"disabled"}`——glm-5.2 默认烧 reasoning_tokens，32-token 调用 finish=length 返回空（截断陷阱），关思考后 1.5s 出干净 JSON；glm-5-turbo/glm-4-long 不动；`GLM_THINKING=enabled` 可覆写；③ 429 长退避：`_call_llm_once` 标记 `_status=429`，`call_llm` 对 429 用 30/60/90s 退避（原 2/4s 对 GLM 按分钟限流无效，3 个硬失败被静默吞成"无提议"）；④ **两层 fallback 架构**：rule-first（精确便宜）→ rule+Phase B 未闭合的残余进 `_llm_propose_fallback`，用 `full_context=True`（`slim_markdown_context_for_llm` 的 full 模式不截 statement snippet、总额 200K，让 NCA/权益尾部可见）让 LLM 提议缺失字段，复用 Phase A 已抽 context 不重抽；并发降到 3（full-context 重 calls，10 并发打爆限流）；⑤ 三道防脏配平闸门：`llm_override_suggestions` 加 `recommended_action=="add_override"`（LLM 自判 fix_classification/manual_review 不批，挡住"资产减值损失值写进 rd_exp"）；fallback 提议字段必须在 failure 的 candidate 字段集内（挡 LLM 编造的 `impair_imp_loss_or_rd_exp` 等不存在字段，也是正确性要求——只有 bucket 求和集字段能闭合 bucket 残差）；diff<TOLERANCE 不变。紫金实测：25 条 approved override，年度 clean 仍剩 **4 个硬失败**（BS 2.1 2025 残差 2174.28=应收款项融资 2153.53+20.75 第二未知项；BS 2.2 2020/2024/2025 残差 6758/16447/17977，jumbled 文本里 LLM 找不到单一吻合项，2024 还缺 cninfo 年报）——与 glm-5-turbo 基线一致，fallback 未突破但守卫正确拒绝脏配平 |
| 2026-06-18 | 年报下载器修 cninfo 标题笔误 + 两轮补数 + 年度 plug 兜底：① **2024 年报漏下根因**：紫金 2024 年报在 cninfo 标题为"2024年**年报报告**"（非"年度报告"，录入笔误），下载器正则 `YYYY年年度报告` 太严漏掉整年。`report_downloader.py` 加 `ANNUAL_TITLE_TAILS=("年年度报告","年年报报告","年年报")` 变体匹配（通用性修复，非紫金特判；摘要/披露/更新/取消已先行排除故裸"年报"尾安全），`parse_report` annual 用 alternation，`_looks_like_periodic_report` 同步。紫金 2024 PDF+md 已补回（379 页）。② **两轮补数**：reconciler `main()` 在 `collect_failures` 前用 `clean.load_approved_overrides`+`apply_annual_overrides` 应用已有 approved override——第二次跑天然只见第一轮补完后的残差（LLM 在 field_context 看到 round1 已补的值，专攻更小残差=“核对第一轮”）；`init.py` `MAX_BACKFILL_CYCLES` 1→2，`stage_clean` 改两轮 reconcile+apply 循环。紫金实测 round1 32 失败→24 approved，round2 应用后只见 15 残差。③ **年度 plug 兜底**：两轮都不过的硬残差→`init.py` `_offer_annual_plug` 交互问用户是否塞年度 QA plug（`annual_plugs.json` 指令，period 为纯年份匹配 wide.index）；`clean.py` 加 `apply_annual_bs_plugs`（镜像季度 plug，但只在用户指令的 (period,code) 生效，非自动全期）+ `--allow-annual-plug` flag + `load_annual_plugs`/`default_plugs_path`；`bs_bucket_sum` 已含 `qa_bs_*_plug` 故 check_bs 自动吸收。紫金 5 个硬失败（BS 2.1 2025、BS 2.2 2020/2024/2025、BS 3.2 2024）塞 plug 后 "All checks passed!"，带 `annual_bs_plug` warning+审计公式。`_run_clean` 改捕获 stderr 解析 `HARD CHECK FAIL` 行供 plug 提示展示残差 |
| 2026-06-18 | LLM 并发 10→5 降 429：紫金 reconciler 全量跑的 override 数量在 18~25 间漂移，根因是 Phase B confirm（`batch_llm_confirm_candidates` 用默认 `LLM_MAX_WORKERS`=10）吃满 GLM 按分钟请求配额，紧接着的 fallback propose（已 hardcode 3 并发）撞残余限流，429 被 30/60/90s 退避兜住但整片 LLM 响应被吞成"无提议"假阴性。`.env` `LLM_MAX_WORKERS` 10→5 直接压低 Phase B 突发，给 fallback 留出按分钟配额；fallback 维持 3（full-context 重 calls，再升反增 429 风险）。429 真正兜底是 `call_llm` 的长退避，并发只是减少触发频率 |
| 2026-06-18 | init 可见性 + plug 幂等：① **每阶段计时**：`run_one` 每个 stage 结束打 `⏱ 阶段N 用时 Xm Ys`，最后打总用时分解（取数/下载/clean/财务费用），解决"下载多久、核对多久"不可见。② **`_run_clean` 改流式逐行回显**：`Popen(stderr=PIPE, bufsize=1)` + `PYTHONUNBUFFERED=1`，clean/reconciler 日志（`Analyzing BS 2.2 2018...`、`第 1 轮...`）实时回显而非跑完才出，消除核对阶段黑屏；stdout 丢弃（clean 只打一行 All checks passed），stderr 边流式边累积解析 `HARD CHECK FAIL`。③ **plug 幂等**：既有 `annual_plugs.json` 视为用户已批准，`stage_clean` 2 轮循环的 clean 自动带 `--allow-annual-plug` 沿用（既有残差被吸收，不重复提示）；`_offer_annual_plug` 改**合并**写入（追加新硬失败、dedupe、不覆盖既有），只对 plug 未覆盖的新硬失败提示。紫金重跑 clean 3m22s→3s、无提示无 reconcile。init SKILL 指引复杂公司后台跑（`run_in_background`，不接 `| tail`，避免 10min 超时 + 缓冲黑屏）|
| 2026-06-18 | **年度核对混合分层：reconciler 无人值守地板 + init skill subagent 升级通道**（比亚迪 002594 2019/2021 BS 3.2 实测驱动）。reconciler 的 GLM 对某些案例结构性赢不了：喂 jumbled snippet、拿 compound 残差（重分类未反映）单字段打分闭合不了、发字段名会飘（`lease_ncl`/null 被守卫挡）。改为两层：① **reconciler 地板**（无人值守，工作台/cron/批量 `init` 都靠它）只做便宜加固——`COMMON_ANNUAL_ALIASES` 补 lease_liab/estimated_liab/lt_borr/bond_payable/defer_tax_liab/oth_ncl/use_right_assets/receiv_financing 等；新增 `resolve_candidate_field`（轻量①）：LLM 自报字段不在 candidate 集时用 `annual_report_item` 反向匹配 candidate 的 description/alias 确定性映射（长名优先，挡子串误命中）；砍掉危险的 ②③ 服务端 diff/耦合提案集重写。② **subagent 升级通道**（agent 在线、init exit 3 时）：新增 `src/recon_subagent_bridge.py` 两个 CLI——`context` 重跑 `clean --mode annual --no-auto-reconcile` 解析 `HARD CHECK FAIL` 取**净残差**（绕开 reconciler 内部 collect_failures 重分类未反映 bug），为每个失败算 candidate/年报 section/已批准 override 上下文写到 `recon/subagent_context.json`；`apply` 吃 subagent 提案 `recon/subagent_proposals.json`，**服务端按提案集合净影响验闭合**（`evaluate_proposals`：字段必须在 candidate 集、add_override/reclass 的 calc 有符号影响、`|净影响−所需|<TOLERANCE` 才整组批准，防脏配平闸门在代码不信 subagent 自报），写 `source=claude` approved override 合并进 `annual_report_overrides.json`。`clean.py` `APPROVED_OVERRIDE_SOURCES` 加 `claude`。init SKILL.md 写详细 7 步升级流程 + subagent prompt 模板 + 纪律（subagent 只读只提案，不写文件不批准自己；raw_tushare 不动；不闭环不算成功；找不到诚实留 exit 3）。BYD 实测：撤手工 override 后 2 个 subagent 并发读年报各定位 lease_liab（548.68/1415.291 百万），bridge 验闭合写 2 条 claude override，clean 10 期年度+48 期季度全过，49 条审计（47 reconciler+2 subagent）。测试 `tests/test_recon_subagent_bridge.py` 11 passed 锁定场景 |
| 2026-06-18 | **修季报下载只剩半年报**（比亚迪 002594 quarterlyreports/2024 实测驱动）：根因是 cninfo 季报标题命名从 2022 年起由"第X季度报告"改为"X季度报告"（去掉"第"字，如 `2024年一季度报告`/`2024年三季度报告`），而 `KIND_TO_TITLE_TAIL` 的 q1=`年第一季度报告`/q3=`年第三季度报告` 是硬匹配，2022+ 一季报/三季报全部被静默漏掉；半年报标题未变（始终"半年度报告"）故唯独存活——表现为"季报全丢只剩半年报"。raw 探测确认 cninfo YJDBG/SJDBG 分类 2022-2026 条目齐全（无分页/日期窗口问题），纯标题正则没认。修：把原 annual 专用的多 tail 变体机制（`ANNUAL_TITLE_TAILS`）推广为通用 `KIND_TITLE_TAIL_VARIANTS` 字典，q1 收 `年第一季度报告`+`年一季度报告`、q3 收 `年第三季度报告`+`年三季度报告`、annual 不变；`parse_report` 全 kind 走 alternation；`_looks_like_periodic_report` 同步派生自该字典；删除孤儿导入 `KIND_TO_TITLE_TAIL`。按通用性原则收齐命名长尾，非 BYD 特判。BYD `--list-only` matched 51→60（补回 2022-2026 一/三季报 9 份），实跑回填 9 个 Q1/Q3 PDF，2022/2023/2024/2025 各三份季报齐全 |
| 2026-06-18 | **年报/季报下载 2010 闸门**：`report_downloader.py` 加 `--min-year`（默认 `DEFAULT_MIN_REPORT_YEAR=2010`，与 `clean.RECONCILE_MIN_YEAR` 对齐），`main()` 在 `collect_reports()` 之后丢弃该年之前的报告（不下载、不抽 Markdown、`--list-only` 也过滤），输出 `filter: dropped N report(s) before 2010`。`init.py` `stage_reports` 默认传 `--min-year=clean.RECONCILE_MIN_YEAR`（单一真源），`run_one`/`main` 透传同名 CLI flag 可覆写。动机：2010 前披露稀疏、reconciler 也不核对，下载纯浪费 cninfo 请求与磁盘。**作用域仅 cninfo 报告下载（PDF/Markdown）**，不限制 TuShare 三表拉取——`data_fetcher.py` 仍拉全历史，2010 前年度由 `clean.py` 降级为 warning 直接入库（既有 `mirror_cutoff_year` 基础设施未启用） |
| 2026-06-18 | **修 bridge 静默吞 `跨表 7.4` 失败（编码缺陷）+ 跨表 7.4 重述豁免通道**（潍柴动力 000338 实测驱动）。① **bridge 编码 bug**：`recon_subagent_bridge.run_clean_annual` 子进程未强制 UTF-8，Windows 下 clean.py 按 cp936 输出 stderr，bridge 按 `encoding="utf-8"` 解码 → 中文 `跨表` prefix 乱码 → `parse_failure_message` 正则 `(?P<prefix>IS\|BS\|CF\|跨表)` 失配 → `code="UNKNOWN"` → 被 `parse_hard_check_failures` 过滤 → bridge 误报 "annual clean already passes"，把真失败静默吞掉。ASCII code（BS/IS/CF）因 GBK/UTF-8 同形幸存，唯独中文 prefix 的 `跨表 7.4` 被吞——隐蔽的静默错误。修：subprocess env 注入 `PYTHONIOENCODING=utf-8`+`PYTHONUTF8=1`。② **跨表 7.4 重述豁免通道**（与 BS 残差 override 通道并行，**不补数**）：7.4 残差来自年报重述——公司在新一年年报比较列追溯重述上年期末现金，TuShare 存各年原始披露值致边界不衔接。override 闭合结构性不可行（破坏 CF 5.5→级联 5.4/5.1-5.3，多年连续重述需整表重载）。重述是披露会计事件、非数据错误，故走**证据化豁免→clean 降级软 warning**（与 2010 闸门同性质）。新增 `build_restatement_context`（解析 prev_end/cur_beg/残差/方向 + 定位合并现金流量表期初/期末现金行号）、`evaluate_restatement_proposal`（6 道确定性闸门：confirmed / 引用行号真实出现元金额反幻觉 / 年报本期期初==上年比较列期末自洽 / ==TuShare 本期期初 / ≠TuShare 上年期末确属重述 / 残差吻合）、`merge_and_write_exemptions`、CLI `apply-restatements`；`clean.py` 加 `default_restatement_exemptions_path`/`load_restatement_exemptions`，`validate_wide` 7.4 检查对豁免边界降级为 `clean_warnings`（带 source=claude 审计，残差需与豁免记录吻合防脏豁免），`--no-restatement-exemptions` 可关。潍柴 2021/2022 两条 7.4 经 2 个 subagent 读年报确认（期初现金=上年比较列期末=52,873,038,942.90 / 68,626,280,826.76）→ bridge 验证据写豁免 → clean 年度 10 期+季度 48 期全过。`tests/test_recon_subagent_bridge.py` 11→18 passed（+7 重述/编码回归） |
| 2026-06-18 | **修 reconciler 脏 `total_cogs` override（贵州茅台 600519 实测驱动）**：init exit 3 表面是 IS 1.1（营业总成本）2019/2022/2024 三期失败，真因是 reconciler 的 `_llm_propose_fallback` 造了脏 override——LLM 把年报"信用减值损失"值（恰好≈残差量级的负数）塞给 `total_cogs` 这个 subtotal 字段本身（new=-5.31/-14.69/-23.25，恰等于各期残差取反），clean 应用脏 override 覆盖了 `apply_annual_income_subtotal_adaptations` 已修好的 total_cogs（明细和），反而制造 IS 1.1 失败。三道防脏闸门同时失守。修（三层防御，全在 `annual_report_reconciler.py`）：① **`failure_candidate_fields` 所有 IS/CF 分支移除 `"subtotal"`**——subtotal（total_cogs/total_opcost/operate_profit/total_profit/n_income/total_revenue 等）是被校验等式的汇总目标本身，不是待补明细，纳入 candidate 即允许 LLM 改写校验目标=脏配平（BS 走 `bs_fields_for_bucket` 本就不含 subtotal，仅影响 IS/CF）；② **reconciler `collect_failures` 前先跑 `clean.apply_annual_income_subtotal_adaptations`**（与 clean.py 主流程 adaptation→overrides→check 顺序对齐）——IS 1.1 的 official total_cogs vs 明细和的小残差（四舍五入/未归项成本）本就被 adaptation 兜底，reconciler 不再误报为 failure，从源头不进 LLM fallback；③ **`_llm_propose_fallback` 批准处加 `add_override` 拒绝非 0 `old_value` 守卫**（与 `rule_based_override_suggestions` 既有守卫对齐）——add_override 语义只补 TuShare 漏录/为 0 字段，不得覆盖已有非 0 值（total_cogs old=29817≠0 一律拒）。验证：删 3 条脏 override 后 clean annual 10 期+quarterly 48 期全过；重跑 reconciler `--no-llm` **0 failure**（IS 1.1 不再误报）；`failure_candidate_fields` IS 1.1/1.2/1.6/CF 5.4 candidate 集 subtotal 泄漏=[]。raw_tushare 未动，16 条合理 BS override（oth_illiq_fin_assets/use_right_assets/lease_liab/receiv_financing，known defect）保留 |
| 2026-06-18 | **两处通用性修复（三一重工 600031 init 驱动）**：① **年报标题"年"字重复容忍**——三一 2020 年报 cninfo 标题为"2020年**年年年**度报告"（录入多打两个"年"），原 matcher 把"年"个数焊死（双"年"变体）致整年 PDF/Markdown 漏下，reconciler 无法确认该年 7.4 重述。`report_downloader.py` 改用 `年+`（一个或多个"年"）正则前缀 + `KIND_TITLE_STEMS`（度报告/报报告/报）匹配，换任何公司、任何"年"重复次数都认，不再枚举固定变体。② **重述豁免闸门认元/千元两单位**——`recon_subagent_bridge.evaluate_restatement_proposal` 闸门②（反幻觉：披露金额须真实出现在引用行）原 `_yuan_digits` 只生成元制数字串，而三一合并现金流量表为「千元」制（"4,541,395"），元值 4,541,395,000 的数字串不在原文 → 真实重述被误拒；A 股千元制公司常见，该缺陷会令所有千元制公司的 7.4 重述豁免通道失效。改 `_value_in_evidence`：对元值在元/千元两单位各取整数与两位小数共四候选，任一出现在去逗号 evidence 即过；反幻觉不单靠此步，闸门③-⑥（披露期初须同时吻合 TuShare 本期期初、上年期末、残差）兜底。三一实测：两轮 reconciler 31 条 BS override（receiv_financing/oth_eq_invest/oth_illiq_fin_assets/use_right_assets/lease_liab，known defect 新准则字段）闭合 BS 2.1/2.2/3.2 全部 21→0；残余 2 条 跨表 7.4（2020/2021）经 subagent 读 2020/2021 年报确认重述（本期期初=上年比较列期末，TuShare 存原始值致边界不衔接）→ bridge 验证据写 2 条 source=claude 豁免 → clean 年度 10 期 + 季度 48 期全过。`tests/test_recon_subagent_bridge.py` 18→19 passed（+千元制回归） |

---

## 附录 A：命名双语对照表

| 设计文档/中文名 | 代码/文件名 | 说明 |
|---|---|---|
| 清洗yaml1.py | `src/yaml1_cleaner.py` | 理解层的 clean.py |
| 逐年标准参数表 | `.modelking/forecast_params.yaml` | yaml1_cleaner 输出，calc.py 唯一输入 |
| 核心假设.md | `skills/核心假设生成修改器_skill_v17.md` | 由 skill 拥有；设计文档版本号需同步 |
| compiler / yaml1compiler | `skills/yaml1compiler_v4 (2).md` | 设计文档版本号需与磁盘一致 |
| YAML2 | `defaults.yaml` | 同物两名 |
| 三棒 pipeline | `src/forecast.py` 编排 `yaml1_cleaner.py` + `src/calc.py` | `forecast.py` 是实际编排器 |
| 年报清洗器 | `src/report_downloader.py` + `src/annual_report_extractor.py` | 设计文档未精确对应，以代码为准 |
| DCF build 快照 | `.modelking/forecast_build.json` | 供工作台 sensitivity 复用 |
