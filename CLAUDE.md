# MKA - A股财务数据拉取与校验系统

两阶段流水线：① 从 TuShare Pro API 拉取三表数据 → 标准化 → 入库 SQLite；② 从 SQLite 读取原始数据 → 透视宽表 → 严格配平校验 → 输出清洗后 CSV。

## 🔴 项目第一原则（理解项目必须先懂这条）

**TuShare 数据缺口 = 用 reconciler 去年报里拉干净。这是本项目存在的根本理由。**

当 `clean.py` 年度硬校验出现 `target_gt_calc`（合计 > 明细和，即 TuShare 漏披露某明细科目）时，**正确的解法不是放弃、不是人工、不是季度式 plug 收纳，而是 `annual_report_reconciler.py` 去对应年报 Markdown 里把缺失的明细金额找回来**，LLM 高置信确认残差后生成 approved override，重跑 `clean.py` 应用补全。

- `raw_tushare` 永不被修改；补全只进年度 clean 宽表，并写入 `clean_adjustments`/`clean_warnings` 审计，全程可追溯。
- 美的集团 `lending_funds`（发放贷款和垫款）、比亚迪 BS 3.1 流动负债缺明细，都是这一类，都由 reconciler 解决。
- 遇到 `target_gt_calc` 类年度缺口，**默认动作就是让 reconciler 拉年报补全**，不要问"要不要保持失败/要不要人工"——那是对项目使命的误解。
- 唯一例外：`target_lt_calc`（明细和 > 合计，即 clean.py 自己重复计数/误分类），这是 clean.py 的 bug，应修字段分类，**不是** reconciler 的活。

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
├── annual_report_reconciler.py # clean.py 年度硬校验失败后的年报 Markdown 智能核对
├── ARCHITECTURE.md           # 系统架构文档（每次开发完必须更新）
├── requirements.txt          # Python依赖
├── .env                      # TUSHARE_TOKEN / HTTP_URL / 限速间隔
├── companies/                # 输出目录，每公司一个子目录
│   └── {公司名}_{代码}/
│       ├── data.db           # SQLite（raw_tushare/meta/clean_annual/clean_quarterly）
│       ├── clean_annual_{code}.csv
│       ├── clean_quarterly_{code}.csv
│       ├── annuals/          # 年度报告 PDF + Markdown
│       └── recon/            # 年报核对 evidence JSON
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
  ├── raw_tushare      (EAV: ticker, endpoint, report_type, end_date, field, value, ...)
  ├── meta             (KV: key, value)
  ├── clean_annual     (wide: period + 325 official fields + 6 QA plug fields)
  ├── clean_quarterly  (wide: period + 325 official fields + 6 QA plug fields)
  ├── clean_adjustments
  └── clean_warnings
    ↓ clean.py（阶段②）
companies/{公司名}_{代码}/clean_annual_{code}.csv
companies/{公司名}_{代码}/clean_quarterly_{code}.csv
  （宽表：行=period，列=统一 331 数据字段，严格配平并保留 warning）
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

## 年报 Markdown 智能核对 annual_report_reconciler.py

这是 `clean.py` 的外置补全/诊断能力，只在年度硬校验失败且本地已有年报 Markdown 时使用。脚本复用 `clean.py` 的年度透视、字段分类、combo resolve 与 `check_*()` 校验函数收集失败，再切出对应年报片段，必要时调用配置好的 LLM（默认 GLM `glm-5-turbo`）输出结构化 evidence。它不修改 `data.db`、`raw_tushare`、`clean_annual` 或 CSV。

### CLI

```bash
python annual_report_reconciler.py --ticker 000333.SZ
python annual_report_reconciler.py --ticker 000333.SZ --only-year 2025 --only-code "BS 2.1"
python annual_report_reconciler.py --ticker 000333.SZ --no-llm
python annual_report_reconciler.py --ticker 000333.SZ --write-overrides --approve-high-confidence
```

输出目录：`companies/{公司名}_{代码}/recon/`，包含时间戳 JSON、`annual_report_reconciliation_latest.json`，以及可选的 `annual_report_overrides.json`。

`annual_report_overrides.json` 必须由 LLM 结构化结论生成；`--write-overrides` 与 `--no-llm` 互斥。`clean.py` 只应用 `annual_report_overrides.json` 中 `status=approved` 且 `source` 为 approved LLM provider（当前 `glm`，历史 `kimi` 仍兼容）的记录，且只应用到年度 clean 宽表；每条应用记录写入 `clean_adjustments`，补数 warning 和软校验 warning 写入 `clean_warnings`。

美的集团（000333.SZ）2016-2025 年 `BS 2.1` 实测：生成 10 条 approved `lending_funds` 补数；`python clean.py --ticker 000333.SZ --mode annual` 后年度 10 期全部硬校验通过。

### 年度 hard-check 强触发

当 `clean.py` 在 annual 或 all 模式下遇到年度 hard check 失败，必须把它当作 clean-data blocker：这不是 soft warning，当前年度 clean 输出不能被信任。默认行为是自动调用：

```bash
python annual_report_reconciler.py --ticker {ticker} --db {data.db} --max-failures 20 --write-overrides --approve-high-confidence
```

终端要清楚告诉用户：哪里失败导致 clean 停止；系统正在用本地年报 Markdown + LLM evidence 判断是否为 TuShare 字段缺失/口径问题；`raw_tushare` 不会被修改；本次失败运行不会被改判成功。若 LLM 生成新的 approved override，用户重跑 `clean.py` 后才会由正常流程应用补数，并写入 `clean_adjustments`/`clean_warnings`。

可用 `--no-auto-reconcile` 关闭强触发，用 `--auto-reconcile-max-failures N` 控制自动分析条数。`annual_report_reconciler.py` 写默认 override 文件时会合并旧记录，不能覆盖掉已有 approved LLM 证据。

## 季度 QA plug 收纳科目

季度报告明细披露弱于年报，`clean.py` 在 quarterly 模式下允许用显式 QA plug 字段吸收 BS bucket 小计残差：

- `qa_bs_current_asset_plug`
- `qa_bs_noncurrent_asset_plug`
- `qa_bs_current_liab_plug`
- `qa_bs_noncurrent_liab_plug`
- `qa_bs_equity_plug`
- `qa_cf_cash_reconcile_plug`

这些不是 TuShare 官方字段，只是 clean 审计字段。年度/季度 clean 表都保留 325 个官方字段 + 6 个 QA plug 字段，保证 schema 统一；年度 plug 正常为 0。季度 BS plug 只参与 BS 2.1/2.2/3.1/3.2/4.1 bucket 小计校验；`qa_cf_cash_reconcile_plug` 只参与 CF 5.5 期初期末现金桥接，不参与 CF 5.1-5.4 的流量明细加总；不修改 `raw_tushare`。

使用 plug 时必须透明：`clean_warnings` 的 `quarterly_bs_plug` / `quarterly_cf_cash_plug` 记录要写清楚哪里合不上、目标值、计算值、残差、使用哪个 plug 字段，以及建议检查对应季报/半年报/三季报。美的集团（000333.SZ）季度实测 48 期全部硬校验通过，仅 `BS 2.1` 使用 `qa_bs_current_asset_plug`。

## 已知 TuShare 缺陷提示卡

`knowledge/known_tushare_defects.json` 是给 `annual_report_reconciler.py` 的轻量 LLM 检索提示，不是补丁库。索引用“触发条件 + 字段”，不要用公司名；命中后只把 hint 写入 reconciliation JSON 并加入年报 Markdown 检索词。

当前条目：
1. `BS 2.1` / `balancesheet` / `current_asset` / `lending_funds`（美的集团 2016-2025）：`total_cur_assets` 大于流动资产明细和且 `lending_funds` 缺失/为 0 时，提示 LLM 查“发放贷款和垫款 / 发放贷款 / 垫款 / 贷款”。
2. `BS 3.1` / `balancesheet` / `current_liab` / `estimated_liab`（比亚迪 2016-2025）：`total_cur_liab` 大于流动负债明细和且 `estimated_liab` 缺失/为 0 时，提示 LLM 查流动负债段的“预计负债-流动 / 预计负债”。该条带 `clean_category=current_liab`：TuShare 只有一个 `estimated_liab` 字段且默认按非流动归类，当公司把预计负债列在流动负债时，override 用 `clean_category` 把补数在本期重分类到流动负债 bucket（见下「override clean_category 重分类」）。

这些来自确认案例，但不能作为自动补数依据，仍须年报片段金额 + LLM high confidence 确认。

### override clean_category 重分类（处理 TuShare 字段归类与公司列报口径不一致）

部分 TuShare 字段的 bucket 归属对个别公司不成立（典型：`estimated_liab` 预计负债，TuShare 默认非流动，但比亚迪列报为流动）。这类情况**不能改 clean.py 的静态分类**（会破坏其他公司），而是由 reconciler 在 override 记录里写 `clean_category`，`clean.py` 应用时只对**该公司该期**把字段重分类到目标 bucket（写入 `wide.attrs["bs_reclass"]`，`bs_bucket_sum` 按 `reclass.get(field, 静态分类)` 取 bucket）。字段值照常补进宽表（下游可见），bucket 加总落到正确的一侧。`clean_adjustments` 记录 `clean_category` 审计。

重要边界：known defect hint 只是“去哪查”的线索；approved override 仍必须靠年报片段金额解释残差，并由 LLM high confidence 结构化确认。

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
python clean.py --ticker 000333.SZ --mode annual          # 只生成年度 clean 表
python clean.py --ticker 000333.SZ --mode quarterly       # 只生成季度 clean 表，必要时写显式 QA plug warning
python clean.py --ticker 000333.SZ --no-overrides         # 不应用 approved 年报补数
python clean.py --ticker 000333.SZ --mode annual --no-auto-reconcile  # 年度失败时不自动触发年报核对
python clean.py --ticker 002946.SZ --verbose              # 调试日志
```

### 关键函数

| 名称 | 用途 |
|------|------|
| `load_raw_tushare()` | 读取 EAV，过滤 report_type=1, comp_type=1 |
| `dedupe_by_f_ann_date()` | 同 (endpoint, end_date, field) 取 f_ann_date 最晚 |
| `pivot_to_wide()` | EAV→宽表，处理跨端点同名字段（如 credit_impa_loss 加前缀消歧），**补全全 NaN 列和 QA plug 列，确保所有公司输出相同列集** |
| `apply_quarterly_bs_plugs()` | 季度 BS bucket 小计残差收纳到显式 `qa_bs_*_plug`，并写入公式级 `clean_warnings` |
| `apply_quarterly_cf_cash_plugs()` | 季度 CF 5.5 期初期末现金桥接残差收纳到 `qa_cf_cash_reconcile_plug`，并写入公式级 `clean_warnings` |
| `resolve()` | 合并科目处理（公司只报合并项时自动适配，如 accounts_receiv_bill） |
| `check_is()` | 利润表硬校验（营业总成本/营业利润/利润总额/净利润/归属/综合收益） |
| `check_bs()` | 资产负债表硬校验（流动/非流动资产/负债、权益明细、终极配平） |
| `check_cf()` | 现金流量表硬校验（三大活动、汇总、期初期末） |
| `check_is_supplement()` | IS 补充校验（综合收益归属、持续/终止经营） |
| `check_cross_table()` | 跨表硬校验（IS净利润=CF附注净利润） |
| `check_soft()` | 软校验仅警告（财务费用差异、现金vs货币资金、方向/量级合理性） |

### 校验层级

- **硬校验**（`CheckError` 报错停止）：IS 1.1-1.6, BS 2.1-4.3, CF 5.1-5.5, IS补充 6.1-6.3, 跨表 7.1, 逐年连续性 7.4；季度 BS bucket 小计残差和 CF 5.5 现金桥接残差先进入显式 QA plug 并写 warning，plug 后仍不平才停止
- **软校验**（仅 warning）：跨表 7.2-7.3, 方向合理性 10.1, 量级合理性 10.2, 折旧vs固定资产 10.3, 毛利率范围 10.4
- **容差**：残差 < 1（百万元）
- **年度失败处理**：annual hard check 失败会默认强触发 `annual_report_reconciler.py`；这只生成 evidence/override，不修改 raw，不静默放行 clean

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

## SQLite Schema

| 表 | 主键 | 说明 |
|----|------|------|
| `raw_tushare` | (ticker, endpoint, report_type, end_date, field) | TuShare原始镜像，完整保留官方字段 |
| `meta` | key | 公司元信息（ticker, name, total_share, total_mv 等） |
| `clean_annual` | period | 年度 clean 宽表：325 个 TuShare 官方字段 + 6 个 QA plug 字段 |
| `clean_quarterly` | period | 季度 clean 宽表：325 个 TuShare 官方字段 + 6 个 QA plug 字段 |
| `clean_adjustments` | 无 | clean 阶段应用的 approved 年报补数审计记录，不修改 raw_tushare |
| `clean_warnings` | 无 | clean 阶段 warning 记录，包含补数 warning 和软校验 warning |

## 关键约定（修改代码时必须遵守）

### 字段命名
- **只用 TuShare 官方字段名**，如 `n_income_attr_p`、`total_hldr_eqy_inc_min_int`、`c_pay_acq_const_fiolta`；唯一例外是 clean 阶段的 6 个 `qa_*_plug` 审计字段
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
- clean.py 已处理年度和季度宽表；季度 BS 明细不完整、CF 5.5 现金桥接残差只允许用显式 QA plug + warning，不做静默补数

## 开发流程

- **每次开发完成后必须更新 `ARCHITECTURE.md`**：包括新增/修改的模块、数据模型变更、校验规则变更、设计决策等。在「变更日志」中追加日期和变更摘要。

## 运行注意

- Python 路径：确认 `which python` 不指向 WindowsApps，若指向则 `source ~/.bashrc` 或使用完整路径 `/c/Users/Sheld/AppData/Local/Programs/Python/Python311/python.exe`
- `.env` 中 `TUSHARE_TOKEN` 为敏感信息，不可提交至版本控制
- 输出目录 `companies/` 为运行时生成，不纳入版本控制
