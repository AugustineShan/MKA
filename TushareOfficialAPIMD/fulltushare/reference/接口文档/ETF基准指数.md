# ETF基准指数

**文档ID**: 386
**接口**: etf_index

## 接口描述

获取ETF基准指数列表信息。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | 指数代码 |
| pub_date | str | N | 发布日期（YYYYMMDD） |
| base_date | str | N | 指数基期（YYYYMMDD） |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | 指数代码 |
| indx_name | str | 指数全称 |
| indx_csname | str | 指数简称 |
| pub_party_name | str | 指数发布机构 |
| pub_date | str | 指数发布日期 |
| base_date | str | 指数基日 |
| bp | float | 指数基点（点） |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.etf_index(fields='ts_code,indx_name,pub_date,bp')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*