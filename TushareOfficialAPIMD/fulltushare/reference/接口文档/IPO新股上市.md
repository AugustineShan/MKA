# IPO新股上市

**文档ID**: 123
**接口**: new_share

## 接口描述

获取新股上市列表数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| start_date | str | N | 上网发行开始日期 |
| end_date | str | N | 上网发行结束日期 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | TS股票代码 |
| sub_code | str | 申购代码 |
| name | str | 名称 |
| ipo_date | str | 上网发行日期 |
| issue_date | str | 上市日期 |
| amount | float | 发行总量（万股） |
| market_amount | float | 上网发行总量（万股） |
| price | float | 发行价格 |
| pe | float | 市盈率 |
| limit_amount | float | 个人申购上限（万股） |
| funds | float | 募集资金（亿元） |
| ballot | float | 中签率 |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.new_share(start_date='20180901', end_date='20181018')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*