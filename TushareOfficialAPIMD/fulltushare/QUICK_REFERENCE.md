# Tushare API 快速参考

本文档提供最常用的 Tushare API 接口和代码示例。

**作者**: [StanleyChanH](https://github.com/StanleyChanH)

## 股票数据

### 获取股票列表
```python
import tushare as ts
pro = ts.pro_api()

df = pro.stock_basic(list_status='L')

df_sz = pro.stock_basic(exchange='SZSE')
df_sh = pro.stock_basic(exchange='SSE')
```

### 获取日线行情
```python
df = pro.daily(ts_code='000001.SZ', start_date='20241201', end_date='20241231')

df = pro.daily(ts_code='000001.SZ,600000.SH', start_date='20241201', end_date='20241231')

df = pro.daily(trade_date='20241231')
```

### 获取财务数据
```python
df = pro.income(ts_code='600000.SH', start_date='20240101', end_date='20241231')

df = pro.balancesheet(ts_code='600000.SH', start_date='20240101', end_date='20241231')

df = pro.cashflow(ts_code='600000.SH', start_date='20240101', end_date='20241231')

df = pro.fina_indicator(ts_code='600000.SH', start_date='20240101', end_date='20241231')
```

## 指数数据

### 获取指数列表
```python
df = pro.index_basic(market='SSE')
df = pro.index_basic(market='SZSE')
```

### 获取指数行情
```python
df = pro.index_daily(ts_code='000001.SH', start_date='20241201', end_date='20241231')

df = pro.index_daily(ts_code='399001.SZ', start_date='20241201', end_date='20241231')
```

## 基金数据

### 获取基金列表
```python
df = pro.fund_basic(market='E')
df = pro.fund_basic(market='O')
```

### 获取基金净值
```python
df = pro.fund_nav(ts_code='000001.OF', start_date='20241201', end_date='20241231')
```

## 宏观经济

### GDP 数据
```python
df = pro.gdp(start_q='2020011', end_q='2024044')
```

### CPI 数据
```python
df = pro.cpi(start_date='20240101', end_date='20241231')
```

### PMI 数据
```python
df = pro.pmi(start_date='20240101', end_date='20241231')
```

### 利率数据
```python
df = pro.shibor(start_date='20241201', end_date='20241231')

df = pro.lpr(start_date='20241201', end_date='20241231')
```

## 港股美股

### 港股数据
```python
df = pro.hk_basic()

df = pro.hk_daily(ts_code='00700.HK', start_date='20241201', end_date='20241231')
```

### 美股数据
```python
df = pro.us_basic()

df = pro.us_daily(ts_code='AAPL', start_date='20241201', end_date='20241231')
```

## 常用字段说明

### 日线行情字段
- `trade_date`: 交易日期
- `ts_code`: 股票代码
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `vol`: 成交量（手）
- `amount`: 成交额（千元）

### 财务指标字段
- `end_date`: 报告期
- `roe`: 净资产收益率
- `net_profit_margin`: 销售净利率
- `gross_margin`: 销售毛利率
- `debt_to_assets`: 资产负债率

## 更多接口

完整接口列表和详细说明请查看：
- [Tushare 官方文档](https://tushare.pro/document/2)

---
*最后更新时间：2026-02-02 10:51*