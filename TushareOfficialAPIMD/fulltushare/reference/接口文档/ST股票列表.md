# ST股票列表

**文档ID**: 397
**接口**: stock_st

## 接口描述

获取ST股票列表，可根据交易日期获取历史上每天的ST列表。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | 股票代码 |
| trade_date | str | N | 交易日期（格式：YYYYMMDD） |
| start_date | str | N | 开始时间 |
| end_date | str | N | 结束时间 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | 股票代码 |
| name | str | 股票名称 |
| start_date | str | ST开始日期 |
| end_date | str | ST结束日期 |
| type | str | ST类型 |

## 代码示例

```python
import tushare as ts

pro = ts.pro_api('your_token')

df = pro.stock_st(trade_date='20241231')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*