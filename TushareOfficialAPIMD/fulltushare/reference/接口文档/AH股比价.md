# AH股比价

**文档ID**: 399
**接口**: stk_ah_comparison

## 接口描述

获取AH股比价数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| hk_code | str | N | 港股股票代码（xxxxx.HK） |
| ts_code | str | N | A股代码（xxxxx.SH/SZ/BJ） |
| trade_date | str | N | 交易日期（YYYYMMDD） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| hk_code | str | 港股股票代码 |
| ts_code | str | A股股票代码 |
| trade_date | str | 交易日期 |
| ah_comparison | float | 比价(A/H) |
| ah_premium | float | 溢价(A/H)% |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.stk_ah_comparison(trade_date='20250812')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*