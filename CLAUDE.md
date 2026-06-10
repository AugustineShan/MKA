# MKA - A股财务数据拉取与校验系统

两阶段流水线：① 从 TuShare Pro API 拉取三表数据 → 标准化 → 入库 SQLite；② 从 SQLite 读取原始数据 → 透视宽表 → 严格配平校验 → 输出清洗后 CSV。

## 技术栈

- **语言**: Python 3.11+（系统全局 Python，禁止 venv）
- **依赖**: `tushare>=1.4.0`, `pandas>=2.0.0`, `requests>=2.31`, `pymupdf>=1.24`（见 `requirements.txt`）
- **存储**: SQLite（每家公司一个 `data.db`，路径 `companies/{公司名}_{代码}/data.db`）
- **数据源**: TuShare Pro API，经中转站 `fastapic.stockai888.top` 代理；巨潮资讯网 cninfo 用于年报 PDF + Markdown 下载

## 项目结构

```
MKA/
├── data_fetcher.py           # 阶段①：TuShare拉取+标准化+入库（~1250行）
├── clean.py                  # 阶段②：EAV→宽表+配平校验+CSV输出（~820行）
├── report_downloader.py      # 巨潮资讯网年报 PDF + Markdown 批量下载
├── ARCHITECTURE.md           # 系统架构文档（每次开发完必须更新）
├── requirements.txt          # Python依赖
├── .env                      # TUSHARE_TOKEN / HTTP_URL / 限速间隔
├── companies/                # 输出目录，每公司一个子目录
│   └── {公司名}_{代码}/
│       ├── data.db           # SQLite（raw_tushare/meta/clean_annual/clean_quarterly）
│       ├── clean_annual_{code}.csv
│       ├── clean_quarterly_{code}.csv
│       └── annuals/          # 年度报告 PDF + Markdown
├── vendor/
│   └── use_cninfo/           # vendored rollysys/use_cninfo（MIT）
└── .refs/                    # TuShare官方文档缓存
    ├── tushare-docs/         # 32.md(daily_basic), 33.md(income), 36.md(balancesheet), 44.md(cashflow), 79.md(fina_indicator)
    └── tushare-data/         # TuShare SDK技能参考
```

## 数据流水线

```
TuShare API
    ↓ data_fetcher.py（阶段①）
companies/{公司名}_{代码}/data.db
  ├── raw_tushare    (EAV: ticker, endpoint, end_date, field, value, ...)
  ├── raw_annual     (EAV: ticker, year, field, value)
  ├── raw_quarterly  (EAV: ticker, period, field, value)
  └── meta           (KV: key, value)
    ↓ clean.py（阶段②）
companies/{公司名}_{代码}/clean_{code}.csv
  （宽表：行=年份，列=全部TuShare字段，严格配平）
```

## 年报 PDF + Markdown 下载 report_downloader.py

直接复用 `vendor/use_cninfo/src/cninfo` 中的 cninfo API 封装，只在项目根目录维护一个业务薄脚本。

### CLI

```bash
python report_downloader.py --ticker 000333.SZ
python report_downloader.py --ticker 000333.SZ --list-only
python report_downloader.py --ticker 000333.SZ --force-markdown
python report_downloader.py --ticker 000333.SZ --no-markdown
```

### 输出与规则

- 输出目录：`companies/{公司名}_{代码}/annuals/`
- 文件名：`{年份}_年度报告.pdf`；修订版为 `{年份}_年度报告_修订版.pdf`
- Markdown 文件与 PDF 同名：`{年份}_年度报告.md`；修订版为 `{年份}_年度报告_修订版.md`
- Markdown 默认生成，内容包含 YAML frontmatter + PyMuPDF 提取全文
- 只保留 `YYYY年年度报告` 和 `YYYY年年度报告（修订版）`
- 排除 `年度报告摘要`、英文版、英文全文、摘要更新/取消等非中文年报本体
- 按年份从新到旧排序，同年份修订版优先
- 已存在 PDF/Markdown 分别跳过，不重复下载或抽取
- 默认 cninfo 请求/PDF 下载间隔 1-2 秒

### 已验证样例

```bash
python report_downloader.py --ticker 000333.SZ
```

美的集团（000333.SZ）实测下载 2013-2025 共 13 份中文年度报告 PDF，并生成 13 份同名 Markdown，其中 2016-2025 全部成功；二次运行 `pdf_downloaded=0, pdf_skipped=13, md_written=0, md_skipped=13`。

## 阶段① 核心模块 data_fetcher.py

### 公共 API

```python
fetch_company("600519.SH", force_refresh=False) -> str   # 返回 SQLite 文件路径
fetch_companies(["600519.SH", "300866.SZ"]) -> dict       # 批量拉取
```

### CLI

```bash
python data_fetcher.py --ticker 300866.SZ          # 拉取
python data_fetcher.py --ticker 300866.SZ --force   # 强制刷新（清空旧数据后重拉）
python data_fetcher.py --ticker 300866.SZ --verbose # 调试日志
```

### 关键类与函数

| 名称 | 用途 |
|------|------|
| `TushareDataFetcher` | 核心拉取类，管理 TuShare 客户端、限速、缓存 |
| `convert_value(value, unit)` | 单位转换（元→百万元、%→小数、万股→百万股等） |
| `official_statement_mappings(endpoint)` | 从官方文档解析完整字段映射 |
| `records_for_quarterly_flow()` | 流量表季度拆算（Q2=H1-Q1, Q3=Q3cum-H1, Q4=年报-Q3cum） |
| `records_for_quarterly_point()` | 存量表直接入季度（资产负债表不做拆算） |
| `validate_records_before_write()` | 入库前硬健康检查 |
| `run_quality_checks()` | 入库后勾稽校验（BS配平、现金流勾稽、季度加总） |

## 阶段② 核心模块 clean.py

### 公共 API

```python
clean("D:\\MKA\\companies\\某公司_002946\\data.db", "002946.SZ") -> pd.DataFrame
```

### CLI

```bash
python clean.py --ticker 002946.SZ          # 自动定位 data.db 并清洗
python clean.py --ticker 002946.SZ --db path/to/data.db  # 指定 db
python clean.py --ticker 002946.SZ --verbose              # 调试日志
```

### 关键函数

| 名称 | 用途 |
|------|------|
| `load_raw_tushare()` | 读取 EAV，过滤 report_type=1, comp_type=1 |
| `dedupe_by_f_ann_date()` | 同 (endpoint, end_date, field) 取 f_ann_date 最晚 |
| `pivot_to_wide()` | EAV→宽表，处理跨端点同名字段（如 credit_impa_loss 加前缀消歧），**补全全 NaN 列确保所有公司输出相同列集** |
| `resolve()` | 合并科目处理（公司只报合并项时自动适配，如 accounts_receiv_bill） |
| `check_is()` | 利润表硬校验（营业总成本/营业利润/利润总额/净利润/归属/综合收益） |
| `check_bs()` | 资产负债表硬校验（流动/非流动资产/负债、权益明细、终极配平） |
| `check_cf()` | 现金流量表硬校验（三大活动、汇总、期初期末） |
| `check_is_supplement()` | IS 补充校验（综合收益归属、持续/终止经营） |
| `check_cross_table()` | 跨表硬校验（IS净利润=CF附注净利润） |
| `check_soft()` | 软校验仅警告（财务费用差异、现金vs货币资金、方向/量级合理性） |

### 校验层级

- **硬校验**（`CheckError` 报错停止）：IS 1.1-1.6, BS 2.1-4.3, CF 5.1-5.5, IS补充 6.1-6.3, 跨表 7.1, 逐年连续性 7.4
- **软校验**（仅 warning）：跨表 7.2-7.3, 方向合理性 10.1, 量级合理性 10.2, 折旧vs固定资产 10.3, 毛利率范围 10.4
- **容差**：残差 < 1（百万元）

### 合并科目 resolve 规则

部分公司只报合并项，部分报拆分项，`resolve()` 自动适配：

| 合并项 | 拆分项 |
|--------|--------|
| `accounts_receiv_bill` | `notes_receiv` + `accounts_receiv` |
| `oth_rcv_total` | `oth_receiv` |
| `fix_assets_total` | `fix_assets` |
| `cip_total` | `cip` |
| `accounts_pay` | `notes_payable` + `acct_payable` |
| `oth_pay_total` | `oth_payable` |
| `long_pay_total` | `lt_payable` |

## SQLite Schema（4张表）

| 表 | 主键 | 说明 |
|----|------|------|
| `raw_tushare` | (ticker, endpoint, end_date, field) | TuShare原始镜像，完整保留官方字段 |
| `raw_annual` | (ticker, year, field) | 年度数据（利润表/资产负债表/现金流量表/财务指标） |
| `raw_quarterly` | (ticker, period, field) | 季度数据（period格式如 "2024Q1"） |
| `meta` | key | 公司元信息（ticker, name, total_share, total_mv 等） |

## 关键约定（修改代码时必须遵守）

### 字段命名
- **只用 TuShare 官方字段名**，如 `n_income_attr_p`、`total_hldr_eqy_inc_min_int`、`c_pay_acq_const_fiolta`
- **禁止使用任何内部别名**，`field_terms.csv` 和 `statement_field_coverage.csv` 中不得出现非官方字段

### 单位转换（入库单位）
| 类别 | 入库单位 | 转换 |
|------|----------|------|
| `amount_cny` | 百万元 | 元 ÷ 1,000,000 |
| `percent` | 小数 | 原值 ÷ 100（如 roe=15.5 → 0.155） |
| `share` | 百万股 | 股 ÷ 1,000,000 |
| `daily_basic_share_10k` | 百万股 | 万股 ÷ 100 |
| `daily_basic_mv_10k_cny` | 百万元 | 万元 ÷ 100 |
| `turnover_rate` | 天 | 365 ÷ 周转率 |
| `ratio` / `price` | 原值 | 不转换 |

### 去重规则（同一 end_date 多条记录时）
1. `report_type = '1'`（合并报表）
2. `comp_type = '1'`（一般工商业，非此则跳过并 warning）
3. 优先 `update_flag = '1'`
4. 再取 `f_ann_date` 最晚 → `ann_date` 最晚

### 健康检查（硬校验，不通过则拒绝入库）
1. 三张表至少各有一批记录
2. 主键无重复
3. ticker 与请求一致
4. `raw_tushare` 每端点每报告期必须覆盖官方全部数值字段
5. 最新年度核心字段不得缺失（revenue, n_income_attr_p, total_assets, total_liab, total_hldr_eqy_inc_min_int, n_cashflow_act 等）
6. meta 必须包含 ticker, name, latest_trade_date, total_share, total_mv
7. BS 配平：total_assets ≈ total_liab + total_hldr_eqy_inc_min_int（容差 0.01）
8. 现金流勾稽：CFO+CFI+CFF+汇兑 ≈ 现金净增（容差 0.01）
9. 季度加总：Q1+Q2+Q3+Q4 = 年报值（容差 0.01）

### 限速与重试
- 默认每次请求后等待 0.8s（约 75次/分钟，低于中转站 100次/分钟限额）
- 限频错误等待 60s 后重试，最多 3 次
- 鉴权/权限错误直接抛出，不重试

## 官方文档字段数量（校验基准）

| endpoint | 数值字段数 | 本地文档 |
|----------|-----------|----------|
| `income` | 86 | `.refs/tushare-docs/33.md` |
| `balancesheet` | 150 | `.refs/tushare-docs/36.md` |
| `cashflow` | 89 | `.refs/tushare-docs/44.md` |

## 验收方式

```bash
# 1. 语法检查
py -m py_compile data_fetcher.py
py -m py_compile clean.py
py -m py_compile report_downloader.py

# 2. 阶段①：拉取
py data_fetcher.py --ticker 300866.SZ --force --verbose

# 3. 阶段②：清洗+配平校验
py clean.py --ticker 300866.SZ --verbose

# 4. 年报 PDF + Markdown 下载列表检查
py report_downloader.py --ticker 000333.SZ --list-only

# 5. 检查字段覆盖数
# income=86×报告期数, balancesheet=150×报告期数, cashflow=89×报告期数

# 6. 抽查单位：revenue为百万元, total_mv为百万元, total_share为百万股, roe为小数
```

## 项目边界（不做什么）

- 不拉港股、美股、ETF、指数、可转债
- 不做预测数据
- 不做行情 K 线（仅 `daily_basic` 最新市值/股本/价格）
- 不做可视化，只负责取数、标准化、校验和入库
- clean.py 不适用于金融企业（银行/保险/证券），comp_type≠1 的数据会被过滤
- clean.py 只处理年报（end_date 以 1231 结尾），不做季度宽表

## 开发流程

- **每次开发完成后必须更新 `ARCHITECTURE.md`**：包括新增/修改的模块、数据模型变更、校验规则变更、设计决策等。在「变更日志」中追加日期和变更摘要。

## 运行注意

- Python 路径：确认 `which python` 不指向 WindowsApps，若指向则 `source ~/.bashrc` 或使用完整路径 `/c/Users/Sheld/AppData/Local/Programs/Python/Python311/python.exe`
- `.env` 中 `TUSHARE_TOKEN` 为敏感信息，不可提交至版本控制
- 输出目录 `companies/` 为运行时生成，不纳入版本控制
