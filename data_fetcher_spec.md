# data_fetcher.py - 需求规格书

## 一句话描述

从 TuShare Pro API 拉取 A 股上市公司的历史三表数据（利润表、资产负债表、现金流量表），按 TuShare 官方字段名存入本地 SQLite，并完成单位标准化、季度拆算、完整性校验和健康检查。所有 `field` 均使用 TuShare 官方命名，不再维护任何内部别名列。

## 对外接口

```python
def fetch_company(ticker: str, force_refresh: bool = False) -> str:
    """拉取一家公司的财务数据，返回 SQLite 文件路径。"""

def fetch_companies(tickers: Iterable[str], force_refresh: bool = False) -> list[str]:
    """串行拉取多家公司，复用限速节奏。"""
```

CLI：

```bash
python data_fetcher.py --ticker 300866.SZ
python data_fetcher.py --ticker 300866.SZ --force
```

## 数据源与配置

使用 TuShare SDK + 中转站地址：

```python
import tushare as ts

ts.set_token(api_key)
pro = ts.pro_api()
pro._DataApi__http_url = "https://fastapic.stockai888.top"
```

配置读取 `.env`：

```env
TUSHARE_TOKEN=...
TUSHARE_HTTP_URL=https://fastapic.stockai888.top
TUSHARE_MIN_INTERVAL_SECONDS=0.8
```

不要依赖系统级 TuShare token 环境变量覆盖代理配置。默认每次请求后等待 `0.8s`，约 75 次/分钟，低于中转站约 100 次/分钟的限速。

## 官方文档来源

字段定义以 TuShare 官方维护的 `waditu/tushare-data` 及其索引到的 `wctapi/documents/*.md` 为准。本项目缓存路径：

| endpoint | doc_id | 本地文档 |
|---|---:|---|
| `daily_basic` | 32 | `.refs/tushare-docs/32.md` |
| `income` | 33 | `.refs/tushare-docs/33.md` |
| `balancesheet` | 36 | `.refs/tushare-docs/36.md` |
| `cashflow` | 44 | `.refs/tushare-docs/44.md` |
| `fina_indicator` | 79 | `.refs/tushare-docs/79.md` |

三表完整镜像字段数量必须和官方文档一致：

| endpoint | 数值字段数 |
|---|---:|
| `income` | 86 |
| `balancesheet` | 150 |
| `cashflow` | 89 |

`statement_field_coverage.csv` 是三表完整性覆盖表，必须只包含 TuShare 官方 `field`，不得出现任何人为别名。

## 取数策略

1. 三表与 `fina_indicator` 按 `ts_code` 一次尽可能拉全历史，再在本地过滤报告期、去重、拆季度。
2. 禁止逐股票逐天逐字段循环调用三表接口。
3. `trade_cal` 在同一个 `TushareDataFetcher` 实例内缓存，批量取数时避免重复查交易日历。
4. `daily_basic` 单公司只取最新已开市交易日；未来批量公司可优先按 `trade_date` 一次拿全市场再本地筛选。
5. 限频错误等待 60 秒后重试，最多 3 次；疑似冷却期时停止放大请求。

## SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS raw_tushare (
    ticker      TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    field       TEXT NOT NULL,
    value       REAL,
    ann_date    TEXT,
    f_ann_date  TEXT,
    report_type TEXT,
    comp_type   TEXT,
    update_flag TEXT,
    PRIMARY KEY (ticker, endpoint, end_date, field)
);

CREATE TABLE IF NOT EXISTS raw_annual (
    ticker TEXT NOT NULL,
    year   INTEGER NOT NULL,
    field  TEXT NOT NULL,
    value  REAL,
    PRIMARY KEY (ticker, year, field)
);

CREATE TABLE IF NOT EXISTS raw_quarterly (
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    field  TEXT NOT NULL,
    value  REAL,
    PRIMARY KEY (ticker, period, field)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

命名规则：

1. `raw_tushare.field` 完整保存 TuShare 官方三表字段名，例如 `n_income_attr_p`、`total_hldr_eqy_inc_min_int`、`c_pay_acq_const_fiolta`。
2. `raw_annual.field` 和 `raw_quarterly.field` 也只使用 TuShare 官方字段名。
3. `meta` 中行情与股本字段也使用 TuShare 官方字段名，例如 `total_share`、`float_share`、`total_mv`、`pe_ttm`、`pb`、`close`。

## 字段术语表

`field_terms.csv` 是机器可读字段术语表，列定义如下：

| column | 含义 |
|---|---|
| `field` | TuShare 官方字段名 |
| `chinese_term` | 官方中文说明 |
| `storage_table` | 写入位置 |
| `source_endpoint` | 来源接口 |
| `tushare_type` | 官方类型 |
| `source_doc_id` | 官方文档编号 |
| `unit_category` | 单位转换类别 |
| `stored_unit` | 本地入库单位 |
| `required_for_health_check` | 是否为硬健康检查字段 |
| `official_doc_path` | 本地官方文档路径 |

该表不得包含内部字段别名，或任何不在官方文档中确认过的字段。

## 单位转换

| unit_category | 本地入库单位 | 转换 |
|---|---|---|
| `amount_cny` | 百万元 | 元 / 1,000,000 |
| `percent` | 小数 | 原百分比数值 / 100 |
| `ratio` | 原值直接存储 | 不转换 |
| `turnover_rate` | 天 | 365 / 周转率 |
| `share` | 百万股 | 股 / 1,000,000 |
| `daily_basic_share_10k` | 百万股 | 万股 / 100 |
| `daily_basic_mv_10k_cny` | 百万元 | 万元 / 100 |
| `price` | 元/股 | 不转换 |

关键要求：

1. 人民币金额一律存百万元，不得改成万元、亿元或元。
2. `daily_basic.total_share`、`daily_basic.float_share` 官方单位是万股，入库为百万股时除以 100。
3. `balancesheet.total_share` 若来自三表，官方单位按股处理，入库为百万股时除以 1,000,000。
4. 百分比字段如 `roe=15.5` 表示 15.5%，入库为 `0.155`。
5. `pe_ttm`、`pb`、`current_ratio`、每股指标和价格不做金额单位换算。

## 季度拆算

中国上市公司利润表和现金流量表的季报通常是年初至报告期累计值：

```text
Q1 = Q1累计
Q2 = H1累计 - Q1累计
Q3 = Q3累计 - H1累计
Q4 = 年报累计 - Q3累计
```

资产负债表是时点值，不做拆算，直接按报告期末值入 `raw_quarterly`。

拆算出负值不自动清洗，保留原值并记录 warning，因为这可能来自年末调整或会计重述。

## 去重规则

同一端点同一 `end_date` 可能返回多条记录。保留顺序：

1. `report_type = '1'` 合并报表。
2. `comp_type = '1'` 一般工商业；非一般工商业当前跳过并 warning。
3. 优先 `update_flag = '1'`。
4. 再取 `f_ann_date` 最晚。
5. 再取 `ann_date` 最晚。

## 入库前硬健康检查

只有以下检查全部通过，才允许 commit：

1. `raw_tushare`、`raw_annual`、`raw_quarterly` 均至少生成一批记录。
2. 主键不得重复：`raw_tushare(ticker, endpoint, end_date, field)`、`raw_annual(ticker, year, field)`、`raw_quarterly(ticker, period, field)`。
3. 记录中的 `ticker` 必须和请求 ticker 一致。
4. `raw_tushare` 每个端点、每个报告期必须覆盖该端点官方全部数值字段。
5. 最新年度核心字段不得缺失：`revenue`、`n_income_attr_p`、`total_assets`、`total_liab`、`total_hldr_eqy_inc_min_int`、`n_cashflow_act`、`n_cashflow_inv_act`、`n_cash_flows_fnc_act`、`c_pay_acq_const_fiolta`。
6. `meta` 必须包含 `ticker`、`name`、`latest_trade_date`、`total_share`、`total_mv`。
7. BS 配平必须通过：`total_assets ~= total_liab + total_hldr_eqy_inc_min_int`，容差 `0.01` 百万元。
8. 现金流勾稽必须通过：`n_cashflow_act + n_cashflow_inv_act + n_cash_flows_fnc_act + eff_fx_flu_cash ~= n_incr_cash_cash_equ`，容差 `0.01` 百万元。
9. 流量字段若某年四个季度齐全，则 `Q1+Q2+Q3+Q4` 必须等于年报值，容差 `0.01` 百万元。

软健康问题只记录 warning，不阻止入库：非核心可选字段为空、旧准则字段为空、季度拆算为负、转换后数量级可疑但未破坏核心勾稽。

## 验收方式

1. `py -m py_compile data_fetcher.py test_data_fetcher.py`
2. `py -m unittest -v test_data_fetcher.py`
3. 真实拉取 `py data_fetcher.py --ticker 300866.SZ --force`
4. 检查 `raw_tushare` 三表覆盖数：`income=86 * 报告期数`、`balancesheet=150 * 报告期数`、`cashflow=89 * 报告期数`。
5. 抽查字段命名：数据库和 CSV 中不得出现旧内部别名，只能出现 TuShare 官方字段名。
6. 抽查单位：`revenue` 为百万元，`total_mv` 为百万元，`total_share` 为百万股，`roe` 为小数。

## 不做什么

1. 不拉港股、美股、ETF、指数、可转债。
2. 不做预测数据。
3. 不做行情 K 线，除 `daily_basic` 最新市值、股本和价格外不拉日线。
4. 不做可视化，只负责取数、标准化、校验和入库。
