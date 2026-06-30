# ETF实时日线

**文档ID**: 400
**接口**: rt_etf_k

## 接口描述

获取ETF实时日K线行情。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 支持通配符方式（e.g. 5*.SH、15*.SZ） |
| topic | str | Y | 分类参数，取上海ETF时需要输入'HQ_FND_TICK' |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | ETF代码 |
| name | str | ETF名称 |
| pre_close | float | 昨收价 |
| high | float | 最高价 |
| open | float | 开盘价 |
| low | float | 最低价 |
| close | float | 收盘价（最新价） |
| vol | int | 成交量（股） |
| amount | int | 成交金额（元） |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.rt_etf_k(ts_code='1*.SZ')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*