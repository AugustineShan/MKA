# Shibor利率

**文档ID**: 149
**接口**: shibor

## 接口描述

获取上海银行间同业拆放利率（Shibor）。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| date | str | N | 日期（YYYYMMDD） |
| start_date | str | N | 开始日期 |
| end_date | str | N | 结束日期 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| date | str | 日期 |
| on | float | 隔夜 |
| 1w | float | 1周 |
| 2w | float | 2周 |
| 1m | float | 1个月 |
| 3m | float | 3个月 |
| 6m | float | 6个月 |
| 9m | float | 9个月 |
| 1y | float | 1年 |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.shibor(start_date='20180101', end_date='20181101')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*