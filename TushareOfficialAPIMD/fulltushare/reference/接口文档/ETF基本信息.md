# ETF基本信息

**文档ID**: 385
**接口**: etf_basic

## 接口描述

获取国内ETF基础信息，包括了QDII。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | ETF代码（带.SZ/.SH后缀的6位数字） |
| index_code | str | N | 跟踪指数代码 |
| list_date | str | N | 上市日期（YYYYMMDD） |
| list_status | str | N | 上市状态（L上市 D退市 P待上市） |
| exchange | str | N | 交易所（SH上交所 SZ深交所） |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | ETF代码 |
| name | str | ETF名称 |
| list_date | str | 上市日期 |
| list_status | str | 上市状态 |
| fund_type | str | 基金类型 |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.etf_basic(list_status='L')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*