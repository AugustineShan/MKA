# LPR贷款基础利率

**文档ID**: 151
**接口**: shibor_lpr

## 接口描述

获取LPR贷款基础利率数据。

## 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| date | str | N | 日期（YYYYMMDD） |
| start_date | str | N | 开始日期（YYYYMMDD） |
| end_date | str | N | 结束日期（YYYYMMDD） |

## 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| date | str | 日期 |
| 1y | float | 1年期LPR利率（%） |

## 代码示例

```python
import tushare as ts
pro = ts.pro_api('your_token')
df = pro.shibor_lpr(
    start_date='20240101',
    end_date='20241231'
)
print(df.head())
```

---
*最后更新时间：2026-02-02 10:51*