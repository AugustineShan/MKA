# 国内生产总值（GDP）

**文档ID**: 227
**接口**: cn_gdp

## 接口描述

获取国民经济之GDP数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| q | str | N | 季度（2019Q1表示2019年第一季度） |
| start_q | str | N | 开始季度 |
| end_q | str | N | 结束季度 |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| quarter | str | 季度 |
| gdp | float | GDP（亿元） |
| gdp_yoy | float | GDP同比增长率（%） |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.cn_gdp(start_q='2020Q1', end_q='2024Q4')
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*