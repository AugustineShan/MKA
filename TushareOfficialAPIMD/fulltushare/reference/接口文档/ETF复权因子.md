# ETF复权因子

**文档ID**: 199
**接口**: fund_adj

## 接口描述

获取基金复权因子，用于计算基金复权行情。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | TS基金代码（支持多只基金输入） |
| trade_date | str | N | 交易日期（YYYYMMDD） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | ts基金代码 |
| trade_date | str | 交易日期 |
| adj_factor | float | 复权因子 |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.fund_adj(ts_code='513100.SH', start_date='20190101', end_date='20190926')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*