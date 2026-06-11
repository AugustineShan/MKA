# MKA 系统架构文档

> 本文档描述 MKA 系统的整体架构、模块职责、数据模型与关键决策。
> **每次开发完成后必须同步更新本文档。**

---

## 1. 系统概览

MKA 是 A 股财务数据两阶段流水线系统：

```
TuShare Pro API
      ↓  阶段①：拉取 + 标准化 + 入库
   SQLite (raw_tushare + clean tables)
      ↓  阶段②：透视 + 校验 + 输出
   SQLite clean_annual / clean_quarterly + debug CSV
      ↓  YAML2 defaults_gen.py
   defaults.yaml（无预测默认参数集）
      ↓  calc.py
   forecast 三表 + DCF summary
```

同时提供一个独立的公告下载入口：通过巨潮资讯网 cninfo `hisAnnouncement/query`
接口查询上市公司年度报告公告，并批量下载中文年度报告 PDF，同时用 PyMuPDF 提取全文 Markdown。

**核心目标**：从 TuShare 拉取原始三表数据，经严格配平校验后写入可信赖的年度/季度清洗表；在 clean 数据之上生成无主观预测的 YAML2 默认参数，并用 `calc.py` 跑出会计配平的默认 DCF 预测三表。任何一条历史 hard check 不通过即停止，年度/季度残差均必须 < 1 百万元；预测阶段 BS/CF 会计恒等式不配平也必须失败。

**边界**：仅处理 A 股一般工商业（comp_type=1）财报数据，不覆盖金融企业、港股美股或行情 K 线。YAML2/calc 默认模型不做分析师判断：收入增速默认为 0，参数来自最新 clean 年报，经济不合理项进入 `review_flags` 交分析师调整。

---

## 2. 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                       外部数据源                              │
│  TuShare Pro API (via fastapic.stockai888.top 中转)          │
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
│                            clean_{code}.csv                 │
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

`init.py` 是给 Agent / 人的单一入口，把 data_fetcher → report_downloader → clean
三个独立 CLI 按正确顺序编排成全流程，并保证幂等与如实上报。配套
`.claude/skills/init/SKILL.md` 让 Agent 用 `init <公司>` 触发。

| 组件 | 职责 |
|------|------|
| `resolve_ticker()` | 公司名 / 裸代码 / 完整 ticker → 规范 ticker；中文名经 TuShare `stock_basic` 解析，歧义/无匹配抛 `TickerResolutionError`（退出码 2，交 Agent 用 websearch 兜底） |
| `stage_fetch()` | 阶段①拉取；幂等：当日 `meta.last_updated` 已是今天则跳过（除非 `--force`），否则 UPSERT 增量 |
| `stage_reports()` | 年报 PDF/Markdown 下载（**必须在 clean 之前**，否则失败时 reconciler 无年报可切片）；report_downloader 自身幂等，下载失败不致命 |
| `stage_clean()` | 阶段②清洗校验，含"年度失败→生成 override→重跑应用"两段式；用 `approved_override_count()` 比对前后判断是否新增补数 |
| `build_report()` | 输出数据拉取报告：三阶段状态 + 年度/季度期数 + `clean_adjustments`（年报确认补全科目）+ `clean_warnings` 汇总 |

**编排链路**：
```
输入 → resolve_ticker → stage_fetch → stage_reports → stage_clean
                                                          ├─ 首跑过 → 退出码 0
                                                          └─ 年度失败 → reconciler 生成 override
                                                               → 重跑 clean 应用补数
                                                                    ├─ 过 → 退出码 0
                                                                    └─ 仍失败 → 退出码 3（真问题，如实上报）
```

**退出码语义**：

| 码 | 含义 | Agent 应做 |
|----|------|-----------|
| 0 | 全链路成功（纯 TuShare 或经年报确认补全后通过） | 转述数据拉取报告 |
| 2 | 输入无法解析为唯一 ticker | websearch 查代码后重传完整 ticker |
| 3 | 应用年报补数后仍年度硬校验失败（真数据问题） | 停下如实上报，不静默放行 |
| 1 | API/网络/鉴权等异常 | 报错并提示检查 `.env`/网络 |

**纪律**：失败的 clean 运行不改判成功；override 只在重跑时应用；`raw_tushare` 永不被修改。
批量由 Agent 多次调用或 `python init.py A B C`，严重度取 max（3>2>1>0）。
Windows 控制台 GBK 下强制 UTF-8 输出以兼容报告中的 emoji。

**CLI**：
```bash
python init.py 美的集团          # 中文名
python init.py 000333            # 裸代码
python init.py 000333.SZ 600519.SH   # 批量
python init.py 美的集团 --force  # 全量重拉
```

### 3.1 data_fetcher.py（阶段①）

| 组件 | 职责 |
|------|------|
| `TushareDataFetcher` | 核心拉取类，管理客户端、限速、缓存 |
| `create_tushare_client()` | 初始化 TuShare SDK 客户端，注入中转站 URL |
| `convert_value()` | 单位转换（元→百万元、%→小数、万股→百万股等） |
| `official_statement_mappings()` | 从官方文档解析完整字段映射（缓存） |
| `official_doc_fields()` | 解析 `.refs/tushare-docs/*.md` 获取字段元数据 |
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

**CLI**：`python data_fetcher.py --ticker 300866.SZ [--force] [--verbose]`

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
| `clean_all()` | 同时生成并写入 SQLite `clean_annual` / `clean_quarterly`，并导出 debug CSV |

**公开 API**：
```python
clean("path/to/data.db", "300866.SZ") -> pd.DataFrame
```

**CLI**：`python clean.py --ticker 300866.SZ [--db path] [--verbose]`

### 3.3 report_downloader.py（年报/季报 PDF + Markdown 下载）

| 组件 | 职责 |
|------|------|
| `parse_ticker()` | 校验并解析 `000333.SZ` / `600519.SH` / `430047.BJ` |
| `fetch_company_info()` | 调用 cninfo `topSearch/query` 获取公司简称与 `orgId` |
| `iter_company_category()` | 复用 vendored `cninfo.api.query_page()` 翻页查询指定 category 的公告 |
| `parse_report()` | 标题过滤，匹配年报/一季报/半年报/三季报本体与修订版 |
| `collect_reports()` | 对多个 cninfo category 分别查询，合并去重，按年份从新到旧排序 |
| `render_markdown()` | 复用 vendored `cninfo.parser` 的 PyMuPDF 能力，从 PDF 提取全文 Markdown |
| `download_reports()` | 下载 PDF 并生成 Markdown；年报放 `annuals/`，季报放 `quarterlyreports/{year}/`；目标文件已存在则跳过 |

**CLI**：
```bash
python report_downloader.py --ticker 000333.SZ                    # 只下载年报（默认）
python report_downloader.py --ticker 000333.SZ --quarterly        # 只下载季报
python report_downloader.py --ticker 000333.SZ --all-reports      # 年报 + 季报
python report_downloader.py --ticker 000333.SZ --list-only        # 只列出匹配报告
```

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
- **年报**：保留 `YYYY年年度报告`、`YYYY年年度报告（修订版）`
- **一季报**：保留 `YYYY年第一季度报告` 及修订版
- **半年报**：保留 `YYYY年半年度报告` 及修订版
- **三季报**：保留 `YYYY年第三季度报告` 及修订版
- **统一排除**：`摘要`、`审计报告`、`内部控制`、`提示性公告`、`鉴证报告`、英文版、摘要更新/取消等非中文定期报告本体

**cninfo category 映射**（复用 vendored `cninfo.api` 常量）：
| 报告类型 | category |
|----------|----------|
| 年报 | `category_ndbg_szsh` |
| 一季报 | `category_yjdbg_szsh` |
| 半年报 | `category_bndbg_szsh` |
| 三季报 | `category_sjdbg_szsh` |

**Markdown**：默认生成同名 `.md` 文件，包含 YAML frontmatter（公告 ID、ticker、年份、`kind`、来源、页数、抽取字符数等）和 PyMuPDF 提取的全文。已有 PDF 但缺 Markdown 时会补齐；已有 Markdown 默认跳过，可用 `--force-markdown` 重生成，也可用 `--no-markdown` 仅下载 PDF。

**限速**：默认每次 cninfo 查询或 PDF 下载之间随机等待 1–2 秒，可用 `--min-interval` / `--max-interval` 调整。季报数量约为年报的 3 倍（10 年历史约 30 份季报），下载时间相应增加。

### 3.4 YAML2 defaults_gen.py / calc.py（默认 DCF 预测层）

YAML2 是 `calc.py` 的完整默认参数集。第一版只从最新 `clean_annual` 年报行生成，不做 TTM；它反映“如果没有分析师判断，最新经营状态平推”的会计默认模型。

| 组件 | 职责 |
|------|------|
| `yaml2_schema.py` | YAML2 读写、必填路径校验、默认模型参数、review flag 常量 |
| `defaults_gen.py` | 从 `data.db` 的 `clean_annual` + `meta` 抽取 `defaults.yaml`；每个参数保留 `value/source` 便于审计 |
| `calc.py` | 读取 `defaults.yaml`，按 IS→BS→CF→DCF 顺序生成默认预测，并输出 forecast 文件 |

**CLI**：
```bash
python defaults_gen.py --ticker 300866.SZ
python defaults_gen.py --db companies/安克创新_300866/data.db --output companies/安克创新_300866/defaults.yaml
python calc.py --ticker 300866.SZ
python calc.py --defaults companies/安克创新_300866/defaults.yaml
```

**输出目录**：
```
companies/{公司名}_{代码}/
├── defaults.yaml
└── forecast/
    ├── forecast_is.csv
    ├── forecast_bs.csv
    ├── forecast_cf.csv
    ├── dcf_detail.csv
    ├── dcf_summary.csv
    └── dcf_summary.json
```

**会计顺序**：
1. 利润表：收入默认 0% 增长；毛利率、费用率、below-OP 绝对值、税率、少数股东比例来自最新 clean 年报。财务费用不按历史绝对值硬平推，而是拆为 `利息支出 - 利息收入 + 其他财务费用`；默认利息支出率、现金收益率、其他财务费用由最新年报机械抽取。
2. 资产负债表：应收/存货/应付等用周转或收入占比驱动；固定资产按 CAPEX 与折旧滚动；其他 BS 科目 carry forward；权益按归母净利、分红率、少数股东损益滚动。
3. 循环求解：每个预测年按 IS→BS plug→平均有息负债/平均现金→财务费用→IS 的链路迭代，直到财务费用和 plug 输出收敛；参数可以简单，但引擎必须处理这个会计循环。
4. Plug 配平：默认 `plug=cash`，用 `money_cap` 倒挤 BS。若倒挤出负现金，数学上仍然配平，`calc.py` 不失败，而是在 `review_flags` 写入 `negative_cash_from_plug`，提示“plug产生负现金，建议切换为st_borr模式或检查参数”。
5. 现金流量表：由 IS + BS 变动反推 CFO/CFI/CFF，硬校验 `期初现金 + 现金净增加额 = 期末现金`。
6. DCF：用 `FCFF = NOPAT + D&A - CAPEX - ΔNWC`，折现显式期 FCFF + 终值，得到 EV、股权价值和每股价值。

**验证样本**：当前 5 家公司（安克创新、新乳业、伊利股份、美的集团、比亚迪）均已生成 YAML2 并跑通 calc，BS/CF 残差为浮点误差级；比亚迪触发负现金 review flag，未阻断配平计算。

### 3.5 vendor/use_cninfo（vendored cninfo 工具库）

`vendor/use_cninfo/` 完整 vendored `rollysys/use_cninfo`（MIT License），保留其源码、文档、测试和 skill。
当前项目通过 `vendor/use_cninfo/src` 直接复用其 cninfo API 封装：

| 上游模块 | 当前用途 |
|----------|----------|
| `cninfo.api` | `hisAnnouncement/query` 调用、标题清洗、PDF URL 拼接、PDF 下载 |
| `cninfo.orgid` | `topSearch/query` 地址与 orgId 获取逻辑参考 |
| `cninfo.cache` | 复用 `orgid_map.json` 写入逻辑 |
| `cninfo.parser` | PyMuPDF 提取全文 Markdown，供 `report_downloader.py` 生成同名 `.md` |

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

report_type=1（合并报表）和 report_type=2（单季合并）均保留到 `raw_tushare.report_type`。当前中转站实测只有 `income` 返回真正的 report_type=2；`balancesheet` report_type=2 返回空，`cashflow` report_type=2 请求返回 report_type=1`，因此季度清洗以 income report_type=2 作为季度锚点，并读取同报告期的 BS/CF report_type=1`。

`0331/0630/0930/1231` 等报告期原样保存在 `raw_tushare.end_date`。阶段② `clean.py` 从 `raw_tushare` 读取年度和季度数据并透视为完整 clean 宽表：325 个官方 TuShare 三表字段 + 6 个 QA plug 字段。写入 SQLite 的 `clean_annual` / `clean_quarterly` 与 CSV debug 导出保持同一字段契约，均以 `period` 作为期间列并保留 QA plug。

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

TuShare 三个接口（income/balancesheet/cashflow）的字段集是固定的，所有公司的 SQLite `clean_annual` / `clean_quarterly` **必须输出相同的列集**（`period` + 325 个官方字段 + 6 个 QA plug 字段，其中 `credit_impa_loss` 因跨端点消歧拆为 `income.credit_impa_loss` / `cashflow.credit_impa_loss`）。CSV 仅作为 debug 导出，字段契约与 SQLite clean 表保持一致。

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
| IS 1.2 | 利润表 | operate_profit = revenue - total_cogs + Σ收益项 |
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

`annual_report_reconciler.py` 是 `clean.py` 的外置辅助脚本，不嵌入主清洗路径，也不修改 `data.db`、`raw_tushare`、`clean_annual` 或 CSV。它的职责是在 `clean.py` 出现年度硬校验失败、且本地已有对应年度报告 Markdown 时，自动抽取年报片段并调用配置好的 LLM（默认 GLM `glm-5-turbo`）进行结构化归因，判断是否疑似 TuShare 字段缺失或口径错误。

触发/使用原则：

- 只针对年度硬校验失败；季度数据不直接用年报解释
- 先复用 `clean.py` 的 `load_raw_tushare()`、`pivot_to_wide()`、`check_*()` 和分类/resolve 逻辑收集失败，不重写公式
- 对每条失败按报表类型切出年报 Markdown 主表片段，并附带候选 TuShare 字段、中文说明、当前百万元值、是否出现在 `raw_tushare`
- LLM 仅负责智能归因，输出 JSON evidence；脚本本身不静默补数
- 输出目录为 `companies/{公司名}_{代码}/recon/`，包含时间戳 JSON、`annual_report_reconciliation_latest.json` 与可选 `annual_report_overrides.json`
- `annual_report_overrides.json` 强制来自 LLM 结构化结论；`--write-overrides` 与 `--no-llm` 互斥，规则匹配仅用于诊断辅助，不可生成可应用补数
- `clean.py` 只应用 `annual_report_overrides.json` 中 `status=approved` 的记录，且只应用到年度 clean 宽表；`raw_tushare` 永远不改
- 每条应用过的补数写入 SQLite `clean_adjustments`，同时在 `clean_warnings` 中留下 warning；软校验 warning 也会持久化到 `clean_warnings`

**强触发规则**：当 `clean.py` 在 annual 或 all 模式下遇到年度 hard check 失败时，当前 clean 运行必须失败退出，因为这代表年度 clean 数据不能被信任。随后 `clean.py` 默认自动调用：

```bash
python annual_report_reconciler.py --ticker {ticker} --db {data.db} --max-failures 20 --write-overrides --approve-high-confidence
```

终端提示必须明确说明三点：这是 clean-data blocker，不是软 warning；本次年度 clean 输出没有被视为可信结果；系统正在用本地年报 Markdown + LLM evidence 判断是否为 TuShare 字段缺失/口径问题。自动触发只生成 evidence 与 approved override 文件，不修改 `raw_tushare`，也不把失败的 clean 运行改判成功。若生成了新的 approved override，用户需重跑 `clean.py`，由正常 clean 流程应用补数、写入 `clean_adjustments`/`clean_warnings` 并重新通过 hard checks。

可用 `--no-auto-reconcile` 关闭强触发；可用 `--auto-reconcile-max-failures N` 调整自动分析的失败条数。`annual_report_reconciler.py` 重写默认 `annual_report_overrides.json` 时会合并既有 override，避免部分失败分析覆盖旧的 approved LLM 证据。

CLI：

```bash
python annual_report_reconciler.py --ticker 000333.SZ
python annual_report_reconciler.py --ticker 000333.SZ --only-year 2025 --only-code "BS 2.1"
python annual_report_reconciler.py --ticker 000333.SZ --no-llm
python annual_report_reconciler.py --ticker 000333.SZ --write-overrides --approve-high-confidence
python clean.py --ticker 000333.SZ --mode annual
python clean.py --ticker 000333.SZ --mode annual --no-auto-reconcile
```

LLM 输出字段包括 `suspected_tushare_issue`、`confidence`、`missing_or_suspicious_items`、`candidate_tushare_field`、`value_million_cny`、`evidence_lines`、`recommended_action` 等。`--write-overrides --approve-high-confidence` 只会把 LLM 判断为 high confidence、且残差精确匹配的结果写成 approved override。美的集团 2016–2025 年 `BS 2.1` 可生成 10 条 `lending_funds` approved override；`python clean.py --ticker 000333.SZ --mode annual` 后年度 10 期全部硬校验通过，`clean_adjustments=10`，`clean_warnings=30`。

### 6.5 季度 QA plug 收纳科目

季度报告通常只披露合计数，明细科目覆盖弱于年报。`clean.py` 因此只在 quarterly 模式下，为 BS bucket 小计提供显式 QA plug 字段：

- `qa_bs_current_asset_plug`
- `qa_bs_noncurrent_asset_plug`
- `qa_bs_current_liab_plug`
- `qa_bs_noncurrent_liab_plug`
- `qa_bs_equity_plug`
- `qa_cf_cash_reconcile_plug`

这些字段不是 TuShare 官方字段，而是 clean 阶段的显式审计/防呆字段。BS plug 仅参与 BS 2.1、2.2、3.1、3.2、4.1 的 bucket 小计校验；`qa_cf_cash_reconcile_plug` 仅参与 CF 5.5 的期初期末现金桥接校验，不参与 CF 5.1–5.4 的流量明细加总。不修改 `raw_tushare`，也不替代年度 LLM override。QA plug 保留在 SQLite `clean_annual` / `clean_quarterly`、debug CSV 和 `clean_warnings` 审计中，确保下游读取主库时不会丢失配平桥。

触发时，`apply_quarterly_bs_plugs()` 会计算 `目标合计 - 明细和 = 残差`，把残差写入对应 plug 字段；`apply_quarterly_cf_cash_plugs()` 会计算 `期末现金 - (期初现金 + 净增加额) = 残差`，把残差写入 `qa_cf_cash_reconcile_plug`。两者都会在 `clean_warnings` 写入完整说明：失败编号、目标字段、目标值、plug 前计算值、plug 字段、残差，以及建议检查路径。这样季度数据可以先得到配平的 clean CSV，同时保留“哪里合不上、为什么收纳、后续怎么查”的可追溯 warning。

美的集团实测：`python clean.py --ticker 000333.SZ --mode quarterly` 后 48 个季度全部硬校验通过；仅 `BS 2.1 流动资产合计` 使用 `qa_bs_current_asset_plug`，其余四个 QA plug 均为 0，`clean_warnings` 中每个季度都有公式级说明。

### 6.6 已知 TuShare 缺陷提示卡

`knowledge/known_tushare_defects.json` 是一个轻量记忆文件，只服务于 `annual_report_reconciler.py` 的 LLM 年报检索提示，不参与 clean 校验、不自动补数、不改变 override 审批规则。它记录的是“触发条件 + 字段”的通用诊断经验，而不是某家公司补丁。

当前记录：

- `BS 2.1` / `balancesheet` / `current_asset` / `lending_funds`
- 触发形态：`total_cur_assets` 大于流动资产明细和，`lending_funds` 缺失或为 0
- LLM 检索提示：优先在合并资产负债表中查“发放贷款和垫款 / 发放贷款 / 垫款 / 贷款”，年报千元除以 1000 后与 clean 百万元残差比较
- 确认样本：美的集团 2016–2025 年

命中提示卡时，`annual_report_reconciler.py` 会把 `known_tushare_defect_hints` 写入 reconciliation JSON，并把提示词加入 Markdown 片段检索；LLM prompt 明确说明这些 hint 只是检索线索，不是证据。最终是否生成 approved override 仍必须由年报片段金额解释残差，并由 LLM high confidence 结构化确认。

---

## 7. 配置与依赖

### 7.1 环境配置（.env）

```env
TUSHARE_TOKEN=           # TuShare Pro API 令牌（必填）
TUSHARE_HTTP_URL=https://fastapic.stockai888.top  # 中转站地址
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
| `income` | 86 | `.refs/tushare-docs/33.md` |
| `balancesheet` | 150 | `.refs/tushare-docs/36.md` |
| `cashflow` | 89 | `.refs/tushare-docs/44.md` |
| `daily_basic` | — | `.refs/tushare-docs/32.md` |

---

## 8. 目录结构

```
MKA/
├── data_fetcher.py              # 阶段①：TuShare 拉取 + 标准化 + 入库
├── clean.py                     # 阶段②：EAV→宽表 + 配平校验 + clean 表写入
├── report_downloader.py         # 巨潮资讯网年报 PDF + Markdown 批量下载
├── annual_report_reconciler.py  # clean.py 硬校验失败后的年报 Markdown 智能核对器
├── yaml2_schema.py              # YAML2 读写、必填参数和 review flag 公共定义
├── defaults_gen.py              # clean_annual/meta → defaults.yaml 默认参数集
├── calc.py                      # defaults.yaml → 默认预测三表 + DCF summary
├── ARCHITECTURE.md              # 本文档：系统架构
├── CLAUDE.md                    # 项目约定与关键规则
├── requirements.txt             # Python 依赖
├── .env                         # 敏感配置（不纳入版本控制）
├── .gitignore
├── companies/                   # 运行时输出（不纳入版本控制）
│   └── {公司名}_{代码}/
│       ├── data.db              # SQLite（raw_tushare/meta/clean_annual/clean_quarterly）
│       ├── clean_annual_{code}.csv      # 年度 debug 导出
│       ├── clean_quarterly_{code}.csv   # 季度 debug 导出
│       ├── defaults.yaml                # YAML2 默认参数集（生成产物）
│       ├── forecast/                    # calc.py 默认预测输出
│       │   ├── forecast_is.csv
│       │   ├── forecast_bs.csv
│       │   ├── forecast_cf.csv
│       │   ├── dcf_detail.csv
│       │   └── dcf_summary.json
│       ├── annuals/             # 巨潮资讯网年度报告 PDF + Markdown（扁平目录）
│       │   ├── {年份}_年度报告.pdf
│       │   └── {年份}_年度报告.md
│       ├── quarterlyreports/    # 巨潮资讯网季度报告 PDF + Markdown（按年分子目录）
│       │   └── {年份}/
│       │       ├── {年份}_第一季度报告.pdf
│       │       ├── {年份}_半年度报告.pdf
│       │       └── {年份}_第三季度报告.pdf
│       └── recon/               # 年报核对 evidence JSON（运行 annual_report_reconciler.py 生成）
├── vendor/
│   └── use_cninfo/              # vendored rollysys/use_cninfo（MIT）
└── .refs/                       # TuShare 官方文档缓存
    └── tushare-docs/
        ├── 32.md                # daily_basic
        ├── 33.md                # income
        ├── 36.md                # balancesheet
        ├── 44.md                # cashflow
        └── 79.md                # fina_indicator
```

---

## 9. 运行时数据实例

当前 `companies/` 目录下已有三家公司的完整数据。

### 9.1 安克创新（300866.SZ）

```
companies/安克创新_300866/
├── data.db
├── clean_annual_300866.csv
└── clean_quarterly_300866.csv
```

| 维度 | 数据 |
|------|------|
| raw_tushare | 14,091 行（income rt1: 37期×86字段, income rt2: 31期×86字段, balancesheet rt1: 33期×150字段, cashflow rt1: 37期×89字段） |
| SQLite 表 | `raw_tushare` + `meta` + `clean_annual` + `clean_quarterly` |
| meta | 14 条（ticker, name, total_share=536.28百万股, total_mv=57531.73百万元, close=107.28, pe_ttm=22.82, pb=5.61, ...） |
| clean 表 | `clean_annual`: 10期×332列（period+325官方字段+6 QA plug）；`clean_quarterly`: 30期×332列（period+325官方字段+6 QA plug） |

### 9.2 新乳业（002946.SZ）

```
companies/新乳业_002946/
├── data.db
├── clean_annual_002946.csv
└── clean_quarterly_002946.csv
```

| 维度 | 数据 |
|------|------|
| raw_tushare | 17,531 行（income rt1: 50期×86字段, income rt2: 35期×86字段, balancesheet rt1: 45期×150字段, cashflow rt1: 39期×89字段） |
| SQLite 表 | `raw_tushare` + `meta` + `clean_annual` + `clean_quarterly` |
| meta | 14 条（ticker, name, total_share=860.68百万股, total_mv=14270.03百万元, close=16.58, pe_ttm=18.19, pb=3.73, ...） |
| clean 表 | `clean_annual`: 10期×332列（period+325官方字段+6 QA plug）；`clean_quarterly`: 34期×332列（period+325官方字段+6 QA plug） |

### 9.3 伊利股份（600887.SH）

```
companies/伊利股份_600887/
├── data.db
├── clean_annual_600887.csv
└── clean_quarterly_600887.csv
```

| 维度 | 数据 |
|------|------|
| raw_tushare | 35,256 行（income rt1: 109期×86字段, income rt2: 94期×86字段, balancesheet rt1: 70期×150字段, cashflow rt1: 82期×89字段） |
| SQLite 表 | `raw_tushare` + `meta` + `clean_annual` + `clean_quarterly` |
| meta | 14 条（ticker, name, total_share=6078.13百万股, total_mv=21483.63百万元, close=3.54, pe_ttm=17.05, pb=2.67, ...） |
| clean 表 | `clean_annual`: 10期×332列（period+325官方字段+6 QA plug）；`clean_quarterly`: 48期×332列（period+325官方字段+6 QA plug，最近12年） |

伊利股份暴露并修复了三个系统性的科目口径问题：
1. `int_income` 计入 `total_revenue` 导致 IS 1.2/1.6 校验需要自适应适配（已修复：IS 1.6 改为 `total_revenue = Σrevenue_item` 检测）
2. `const_materials`（工程物资）未归入 BS 字段分类体系（已修复：纳入 `BS_FIELD_CATEGORIES` 的 `noncurrent_asset` 分类）
3. 季报中 `int_receiv`/`div_receiv` 被包含于 `oth_rcv_total`，以及 `specific_payables` 与 `long_pay_total` 口径重叠（已在 `bs_bucket_sum()` 的 `COMBO_RESOLVE` 逻辑中适配）

### 9.4 三家公司对比要点

| 对比项 | 安克创新 (300866) | 新乳业 (002946) | 伊利股份 (600887) |
|--------|-------------------|-----------------|-------------------|
| raw_tushare 报告期数 | income rt1:37 / rt2:31, bs rt1:33, cf rt1:37 | income rt1:50 / rt2:35, bs rt1:45, cf rt1:39 | income rt1:109 / rt2:94, bs rt1:70, cf rt1:82 |
| raw_tushare 字段覆盖 | income:86, bs:150, cf:89 ✓ | income:86, bs:150, cf:89 ✓ | income:86, bs:150, cf:89 ✓ |
| clean 表字段数 | annual/quarterly 均为 332 | annual/quarterly 均为 332 | annual/quarterly 均为 332 |
| 跨端点消歧字段 | `income.credit_impa_loss` + `cashflow.credit_impa_loss` | 同 | 同 |
| 最新市值 | 575.3 亿元 | 142.7 亿元 | 214.8 亿元 |

**clean 表列数一致性**：各公司的 SQLite clean 年度/季度表字段数完全一致（332 列 = `period` + 325 个官方字段 + 6 个 QA plug 字段）。不同公司在某些字段上值全为 0（如安克创新无商誉，goodwill 全为 0），但列始终保留，确保下游模型可使用统一特征集；QA plug 也始终保留，确保下游模型能显式识别季度收纳残差。

### 9.5 meta 字段清单

三家公司的 meta 表结构一致，均含 14 个键值对：

| key | 含义 | 示例（安克创新） |
|-----|------|------------------|
| `ticker` | 股票代码 | 300866.SZ |
| `name` | 公司名称 | 安克创新 |
| `last_updated` | 最后拉取时间 | 2026-06-08T21:34:23 |
| `latest_trade_date` | 最新交易日 | 20260608 |
| `daily_basic_trade_date` | daily_basic 取数日期 | 20260608 |
| `total_share` | 总股本（百万股） | 536.27636 |
| `float_share` | 流通股本（百万股） | 307.58313 |
| `total_mv` | 总市值（百万元） | 57531.727901 |
| `close` | 收盘价（元） | 107.28 |
| `pe_ttm` | 滚动市盈率 | 22.8213 |
| `pb` | 市净率 | 5.6086 |
| `last_ann_date` | 最后公告日期 | 20260430 |
| `last_f_ann_date` | 最后实际公告日期 | 20260430 |
| `last_report_period` | 最后报告期 | 20260331 |

### 9.6 报告期数据范围

报告期原样存放在 `raw_tushare.end_date`，不再生成季度派生表。report_type=2 仅在上游真实返回时保留，目前实测为 income 单季合并。

| 公司 | income rt1 | income rt2 | balancesheet rt1 | cashflow rt1 |
|------|------------|------------|------------------|--------------|
| 安克创新 (300866) | 37 期 | 31 期 | 33 期 | 37 期 |
| 新乳业 (002946) | 50 期 | 35 期 | 45 期 | 39 期 |

### 9.7 美的集团年报 PDF + Markdown（000333.SZ）

```
companies/美的集团_000333/
└── annuals/
    ├── 2013_年度报告.pdf
    ├── 2013_年度报告.md
    ├── ...
    ├── 2025_年度报告.pdf
    └── 2025_年度报告.md
```

| 维度 | 数据 |
|------|------|
| cninfo orgId | `9900005965` |
| 查询类目 | `category_ndbg_szsh` |
| 下载结果 | 13 份中文年度报告 PDF + 13 份 Markdown（2013–2025） |
| 本次验收重点 | 2016–2025 年度报告 PDF 与 Markdown 全部生成成功 |
| Markdown 抽取 | 2025 年报 276 页全部抽取，`text_chars=281227` |
| 跳过验证 | 二次运行 `pdf_downloaded=0, pdf_skipped=13, md_written=0, md_skipped=13`，已存在文件不重复生成 |

---

## 10. 设计决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 存储 | SQLite（每公司一个 db） | 单机离线、零运维、事务保护、EAV→宽表转换方便 |
| 数据模型 | raw_tushare/meta + clean_annual/clean_quarterly | raw_tushare 保留 TuShare 三表官方完整字段；SQLite clean 表和 debug CSV 都提供统一的 `period`+325 官方字段+6 QA plug 字段 |
| 字段命名 | 只用 TuShare 官方名 | 消除别名歧义，与上游对齐 |
| 金额单位 | 百万元 | A 股报表精度到元，百万元级适合分析和校验 |
| 校验容差 | 年度/季度 1 百万元、入库前 0.01 百万元 | 年度与季度均保持严格口径 |
| 中转站 | fastapic.stockai888.top | 绕过 TuShare 官方限速，约 100 次/分钟 |
| 跨端点消歧 | `endpoint.field` 前缀 | credit_impa_loss 在 income/cashflow 中值不同 |
| cninfo 接入 | vendored `rollysys/use_cninfo` | 直接复用成熟的 `hisAnnouncement/query`、orgId、PDF 下载封装，避免重复维护接口细节 |
| 年报文件命名 | `{年份}_年度报告.pdf/.md` / `{年份}_年度报告_修订版.pdf/.md` | 同年份原始版与修订版可并存，文件已存在时跳过 |

---

## 11. 变更日志

| 日期 | 变更 |
|------|------|
| 2026-06-10 | 初始版本：从已有代码和规格书提炼 |
| 2026-06-10 | 新增第9章「运行时数据实例」：补充安克创新(300866)和新乳业(002946)的完整数据画像、对比要点、meta 字段清单、季度数据时间范围 |
| 2026-06-10 | 修复 clean.py pivot 丢列问题：pandas `pivot_table` 静默丢弃全 NaN 列 → 用 `reindex(columns=all_columns)` 补回；两家公司 CSV 列数从 156/226 统一为 325；新增 §5.5 宽表列完整性 |
| 2026-06-10 | 简化 data_fetcher.py：仅保留 raw_tushare + meta，入库校验基于官方字段镜像；手写三表映射与派生表逻辑移除 |
| 2026-06-10 | 数据基座重构：raw_tushare 主键加入 report_type；新增 clean_annual/clean_quarterly 写库；年度/季度统一 325 字段；季度以 income report_type=2 为锚点；两家公司重拉并完成年度+季度校验 |
| 2026-06-10 | 清理废弃产物：删除 field_terms.csv、statement_field_coverage.csv、data_fetcher_spec.md、clean_spec_v3.md；ARCHITECTURE.md 移除过时文件引用 |
| 2026-06-10 | clean.py 季度 CF 拆算补完：cashflow report_type=1 累计值拆为单季（Q2=H1−Q1, Q3=Q3−H1, Q4=Annual−Q3），修正 beg_period；两家公司（安克创新/新乳业）重跑并通过全部硬校验 |
| 2026-06-10 | 全路径验证伊利股份（600887.SH）：年度 10 期 + 季度 48 期全部通过；修复 IS 1.2/1.6 `total_revenue` 含 `int_income` 的自适应口径适配、BS_FIELD_CATEGORIES 补全 `const_materials` 分类、季报 `int_receiv`/`specific_payables` 口径重叠适配；季度范围限制为最近 48 quarter（12 年） |
| 2026-06-10 | 三家验证：安克创新（300866）annual 10+quarterly 31、新乳业（002946）annual 10+quarterly 35、伊利股份（600887）annual 10+quarterly 48，全部硬校验通过 |
| 2026-06-10 | **BS 明细校验重构为全量分类方案**：对 balancesheet 全部 150 个 float 字段建立穷尽分类表 `BS_FIELD_CATEGORIES`（current_asset/noncurrent_asset/current_liab/noncurrent_liab/equity/subtotal/combo/derived），替换原先手动维护的 5 个 ITEMS 列表；新增 `COMBO_RESOLVE` 映射和 `bs_bucket_sum()` 自动推导 bucket 总和；删除 `BS_CUR_ASSET_ITEMS`/`BS_NCA_ITEMS`/`BS_CUR_LIAB_ITEMS`/`BS_NCL_ITEMS`/`BS_EQUITY_ITEMS`/`RESOLVE_SPECS`/`sum_with_resolve`；三家公司重跑全部通过 |
| 2026-06-10 | **IS + CF 字段穷尽分类**：对 income 86 个 float 字段建立 `IS_FIELD_CATEGORIES`（revenue_item/cost_item/operating_adjustment/below_line/tax/attribution/comprehensive/subtotal/sub_item/derived），对 cashflow 89 个 float 字段建立 `CF_FIELD_CATEGORIES`（cfo_inflow/cfo_outflow/cfi_inflow/cfi_outflow/cff_inflow/cff_outflow/subtotal/supplementary/balance/sub_item/derived）；重构 `check_is()` 使用 `is_bucket_sum()` 自动收集字段（保留 total_opcost 与 operate_profit 降级路径）；`check_cf()` 保持原有 5.1–5.5 校验不变；删除 `IS_COGS_STANDARD`/`IS_COGS_EXTRA`/`IS_OPER_PROFIT_EXTRAS`/`EXCLUDED_FROM_CHECKS`/`SUB_ITEMS`；三家公司重跑全部通过 |
| 2026-06-10 | 新增巨潮资讯网年报 PDF 下载能力：完整 vendored `rollysys/use_cninfo` 到 `vendor/use_cninfo/`；新增 `report_downloader.py` 复用其 cninfo API/orgId/PDF 下载封装；支持 `python report_downloader.py --ticker 000333.SZ`，按年份从新到旧下载中文年度报告 PDF 到 `companies/{公司名}_{代码}/annuals/`，已存在文件跳过；美的集团（000333.SZ）实测下载 2013–2025 共 13 份，其中 2016–2025 全部成功 |
| 2026-06-10 | 升级 `report_downloader.py`：默认在 PDF 旁生成同名 Markdown，复用 vendored `cninfo.parser` / PyMuPDF 提取全文，并写入 YAML frontmatter；新增 `--no-markdown` 和 `--force-markdown`；美的集团（000333.SZ）已补齐 2013–2025 共 13 份 `.md`，二次运行 PDF/MD 均跳过 |
| 2026-06-11 | 新增 `annual_report_reconciler.py`：作为 `clean.py` 年度硬校验失败后的外置年报 Markdown 智能核对器，复用 clean 年度透视与 `check_*()` 逻辑收集失败，按报表类型切片年报并调用 LLM 输出结构化 evidence；美的集团 2025 年 `BS 2.1` 实测识别 TuShare `lending_funds` 缺失，年报“发放贷款和垫款”11,779,217 千元完全解释 11,779.217 百万元残差 |
| 2026-06-11 | 新增 approved override 审计层：`annual_report_reconciler.py --write-overrides --approve-high-confidence` 强制基于 LLM 结构化结论生成 `recon/annual_report_overrides.json`，`--no-llm` 不允许写 override；`clean.py` 默认只应用 approved 年报补数到年度宽表并保留 `raw_tushare` 不变，新增 `clean_adjustments`/`clean_warnings` 审计表与 `--mode annual|quarterly|all`、`--no-overrides`；美的集团 2016–2025 年 `lending_funds` 10 条补数后年度硬校验全部通过 |
| 2026-06-11 | 新增季度 QA plug 收纳科目：clean 年度/季度表统一扩展为 325 个官方字段 + 6 个 QA plug 字段；quarterly 模式对 BS bucket 小计残差写入显式 `qa_bs_*_plug`，对 CF 5.5 现金桥接残差写入 `qa_cf_cash_reconcile_plug`，并持久化公式级 warning（含公式、残差、建议核对路径）；美的集团 48 个季度全部硬校验通过，仅 `BS 2.1` 使用 `qa_bs_current_asset_plug` |
| 2026-06-11 | 新增年度 hard-check 强触发：`clean.py` 在 annual/all 年度硬校验失败时默认自动调用 `annual_report_reconciler.py --write-overrides --approve-high-confidence`，终端明确标记为 clean-data blocker；自动触发只生成 LLM evidence/approved override，不修改 raw，也不把失败运行改判成功；override 文件重写时合并既有 approved 记录 |
| 2026-06-11 | 年报智能核对默认 LLM 从 Kimi 切换为 GLM `glm-5-turbo`：`.env` 使用 `LLM_PROVIDER=glm`、`GLM_*` 配置，Kimi 配置保留为注释；`clean.py` 接受 `source=glm/kimi` 的历史 approved override |
| 2026-06-11 | 新增轻量已知缺陷提示卡：`knowledge/known_tushare_defects.json` 以“触发条件+字段”沉淀 TuShare 缺陷诊断经验；首条记录为 `BS 2.1/current_asset/lending_funds`，仅用于 annual_report_reconciler 的 LLM 年报检索提示，不自动补数、不替代 evidence |
| 2026-06-11 | 新增一键编排入口 `init.py` + `.claude/skills/init/SKILL.md`：输入公司名/裸代码/完整 ticker，自动按序编排 data_fetcher→report_downloader→clean，含年报补全两段式重跑；幂等（当日已拉取跳过取数、已有年报跳过下载、补数只在重跑应用）；退出码 0/2/3/1 语义化交给 Agent；输出数据拉取报告（纯 TuShare 通过 vs 年报确认补全科目，全程可追溯）；美的集团（000333.SZ）端到端实测退出码 0 |
| 2026-06-11 | 比亚迪（002594.SZ）暴露并修复 BS 4.1 重复计数 bug：`oth_eqt_tools_p_shr`（优先股）/`oth_eq_ppbond`（永续债）是 `oth_eqt_tools` 的“其中”子项（官方 36.md 证实），原误归 equity 导致权益 bucket 重复计入；改归 `sub_item`，四家公司（安克/新乳业/伊利/美的）回归无破坏 |
| 2026-06-11 | 新增 override `clean_category` 重分类机制：处理 TuShare 字段默认 bucket 与公司列报口径不一致（比亚迪 `estimated_liab` 预计负债列报为流动而非 TuShare 默认非流动）。`bs_bucket_sum`/`check_bs` 接受 per-period `reclass` 映射；`apply_annual_overrides` 从 override 的 `clean_category` 写 `wide.attrs["bs_reclass"]`，只影响该公司该期 bucket 归属，不改静态分类；`clean_adjustments` 增加 `clean_category` 审计列。reconciler 端：`build_field_context` 纳入 known-defect 命中字段（即便不在 bucket）并透传 `clean_category`/别名，override builder 从候选透传 `clean_category`；新增 `knowledge/known_tushare_defects.json` 第 2 条 `BS 3.1/current_liab/estimated_liab`（比亚迪 2016-2025）。候选生成已验证；LLM 端到端 override 生成与 clean 重跑验证待补 |
| 2026-06-11 | 修正 SQLite clean 表输出契约：`clean.py` 写入 `data.db` 的 `clean_annual` / `clean_quarterly` 必须保留完整 clean 宽表（`period` + 325 个官方字段 + 6 个 QA plug 字段），QA plug 是 clean 阶段的显式审计/防呆字段，供 defaults_gen 等下游从 SQLite 主库直接读取 |
| 2026-06-11 | 新增 YAML2 默认 DCF 层：`yaml2_schema.py` 定义 YAML2 读写/校验，`defaults_gen.py` 从最新 `clean_annual` + `meta` 生成带 `value/source` 的 `defaults.yaml`，`calc.py` 按 IS→BS→CF→DCF 顺序生成默认预测三表和估值 summary；财务费用拆为利息支出、利息收入、其他财务费用，每个预测年循环求解 IS→BS plug→平均现金/债务→财务费用直到收敛；会计恒等式不配平即失败，cash plug 产生负现金只写 `review_flags.negative_cash_from_plug` warning，不阻断计算。5 家现有公司均已跑通，BS/CF 残差为浮点误差级 |
| 2026-06-11 | 扩展 `report_downloader.py` 支持季报下载：底层复用 vendored `cninfo.api` 的 `KIND_TO_CATEGORY`（`category_yjdbg_szsh`/`category_bndbg_szsh`/`category_sjdbg_szsh`），分别查询 3 个 category 后合并去重；通用化 `Report` dataclass 替代 `AnnualReport`，支持 `kind`（annual/q1/h1/q3）；标题过滤匹配 `YYYY年第一季度报告`/`半年度报告`/`第三季度报告` 及修订版；CLI 新增 `--quarterly`（仅季报）和 `--all-reports`（年报+季报）互斥参数；年报保持 `annuals/` 扁平目录，季报按年放入 `quarterlyreports/{year}/` 子目录；`init.py` 新增 `--include-quarterly` 参数，默认仍只下载年报，保持向后兼容 |
