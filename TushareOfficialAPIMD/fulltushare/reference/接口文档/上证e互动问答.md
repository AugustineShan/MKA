# 上证e互动问答

**文档ID**: 366
**接口**: irm_qa_sh

## 接口描述

获取上交所e互动董秘问答文本数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | 股票代码 |
| trade_date | str | N | 交易日期（YYYYMMDD） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |
| pub_date | str | N | 发布开始日期 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | 股票代码 |
| name | str | 公司名称 |
| trade_date | str | 日期 |
| q | str | 问题 |
| a | str | 回复 |
| pub_time | str | 回复时间 |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.irm_qa_sh(trade_date='20250212')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*