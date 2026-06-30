# ETF分钟行情

**文档ID**: 387
**接口**: stk_mins

## 接口描述

获取ETF分钟数据，支持1min/5min/15min/30min/60min行情。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | ETF代码 |
| freq | str | Y | 分钟频度（1min/5min/15min/30min/60min） |
| start_date | str | N | 开始日期（2025-06-01 09:00:00） |
| end_date | str | N | 结束时间（2025-06-20 19:00:00） |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | ETF代码 |
| trade_time | str | 交易时间 |
| open | float | 开盘价 |
| close | float | 收盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| vol | int | 成交量 |
| amount | float | 成交金额 |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.stk_mins(ts_code='510330.SH', freq='1min', start_date='2025-06-20 09:00:00', end_date='2025-06-20 19:00:00')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*