# ETF份额规模

**文档ID**: 408
**接口**: etf_share_size

## 接口描述

获取沪深ETF每日份额和规模数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | ETF代码 |
| trade_date | str | N | 交易日期（YYYYMMDD） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |
| exchange | str | N | 交易所（SSE上交所 SZSE深交所） |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| trade_date | str | 交易日期 |
| ts_code | str | ETF代码 |
| etf_name | str | ETF名称 |
| total_share | float | 总份额（万份） |
| total_size | float | 总规模（万元） |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.etf_share_size(ts_code='510330.SH', start_date='20250101', end_date='20251224')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*