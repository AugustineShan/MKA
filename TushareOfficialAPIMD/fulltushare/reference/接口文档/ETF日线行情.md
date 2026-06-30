# ETF日线行情

**文档ID**: 127
**接口**: fund_daily

## 接口描述

获取ETF行情每日收盘后成交数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | 基金代码 |
| trade_date | str | N | 交易日期（YYYYMMDD） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | TS代码 |
| trade_date | str | 交易日期 |
| open | float | 开盘价（元） |
| high | float | 最高价（元） |
| low | float | 最低价（元） |
| close | float | 收盘价（元） |
| pre_close | float | 昨收盘价（元） |
| change | float | 涨跌额（元） |
| pct_chg | float | 涨跌幅（%） |
| vol | float | 成交量（手） |
| amount | float | 成交额（千元） |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.fund_daily(ts_code='510330.SH', start_date='20250101', end_date='20250618')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*