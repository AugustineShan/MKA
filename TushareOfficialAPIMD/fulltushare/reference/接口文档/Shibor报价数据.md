# Shibor报价数据

**文档ID**: 150
**接口**: shibor_quote

## 接口描述

获取Shibor银行报价数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| date | str | N | 日期（YYYYMMDD） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |
| bank | str | N | 银行名称（中文名称） |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| date | str | 日期 |
| bank | str | 报价银行 |
| on_b | float | 隔夜_Bid |
| on_a | float | 隔夜_Ask |
| 1w_b | float | 1周_Bid |
| 1w_a | float | 1周_Ask |
| 2w_b | float | 2周_Bid |
| 2w_a | float | 2周_Ask |
| 1m_b | float | 1月_Bid |
| 1m_a | float | 1月_Ask |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.shibor_quote(start_date='20180101', end_date='20181130')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*