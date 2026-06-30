# Tushare-Complete

Tushare Pro 最完整的数据接口库，包含 266 个数据接口，覆盖 A 股、港股、美股、基金、期货、债券、宏观经济等所有领域。

## 功能特点

- ✅ **接口全面**：涵盖 26 大类、266 个数据接口
- ✅ **市场覆盖**：A股、港股、美股、期货、期权、外汇、债券等
- ✅ **文档完整**：每个接口都有详细的参数说明和代码示例
- ✅ **易于使用**：提供快速参考和字段速查手册

## 适用场景

- 量化投资研究
- 财务分析
- 行业研究
- 宏观经济分析
- 资金流向分析
- 两融数据分析

## 安装

### 安装依赖

```bash
pip install tushare pandas
```

### 配置 Token

Tushare Pro 需要访问 Token，获取方式：

1. 访问 [Tushare Pro 官网](https://tushare.pro) 注册账号
2. 完成实名认证获取 Token
3. 配置 Token（二选一）：

**方式一：环境变量**

```bash
# Windows
setx TUSHARE_TOKEN "your_token_here"

# Linux/Mac
export TUSHARE_TOKEN="your_token_here"
```

**方式二：代码中配置**

```python
import tushare as ts

pro = ts.pro_api('your_token_here')
```

## 快速开始

### 获取股票列表

```python
import tushare as ts

pro = ts.pro_api()

# 获取所有上市股票
df = pro.stock_basic(exchange='', list_status='L',
                  fields='ts_code,symbol,name,area,industry,list_date')
print(df.head())
```

### 获取日线行情

```python
# 获取单只股票的日线行情
df = pro.daily(ts_code='000001.SZ',
             start_date='20240101',
             end_date='20241231')
print(df.head())
```

### 获取财务数据

```python
# 获取资产负债表（含在建工程）
df_balance = pro.balancesheet(ts_code='600000.SH',
                            start_date='20240101',
                            end_date='20241231')
print(df_balance[['ts_code', 'end_date', 'cip', 'total_assets']].head())

# 获取现金流量表（含资本开支）
df_cashflow = pro.cashflow(ts_code='600000.SH',
                          start_date='20240101',
                          end_date='20241231')
print(df_cashflow[['ts_code', 'end_date', 'c_pay_acq_const_fiolta']].head())
```

## 接口分类

### 一、股票数据 (14个)

| 接口 | 方法 | 说明 |
|------|------|------|
| 股票列表 | pro.stock_basic() | 获取所有股票基本信息 |
| 每日股本（盘前） | pro.daily_basic() | 每日股本变动 |
| 交易日历 | pro.trade_calendar() | 交易日历查询 |

### 二、行情数据 (23个)

| 接口 | 方法 | 说明 |
|------|------|------|
| 历史日线 | pro.daily() | 日线行情数据 |
| 实时日线 | pro.daily_now() | 实时日线 |
| 历史分钟 | pro.stk_mins() | 分钟线数据 |

### 三、财务数据 (10个)

| 接口 | 方法 | 说明 |
|------|------|------|
| 利润表 | pro.income() | 营业收入、净利润 |
| 资产负债表 | pro.balancesheet() | 在建工程、总资产 |
| 现金流量表 | pro.cashflow() | 资本开支、现金流 |
| 财务指标数据 | pro.fina_indicator() | ROE、ROA等 |

## 重要字段速查

### 资产负债表

| 字段 | 说明 |
|------|------|
| cip | 在建工程 |
| fix_assets | 固定资产 |
| total_assets | 资产总计 |

### 现金流量表

| 字段 | 说明 |
|------|------|
| c_pay_acq_const_fiolta | 购建固定资产、无形资产和其他长期资产支付的现金（资本开支） |
| n_cashflow_act | 经营活动产生的现金流量净额 |

## 接口调用频率限制

- 免费用户：每分钟 120 次
- 积分用户：根据积分等级提升

## 积分要求

部分接口需要特定积分：

- **基础数据**：免费
- **财务数据**：2000 积分
- **高级数据**：5000 积分

## 参考资源

- [Tushare 官方文档](https://tushare.pro/document/2)
- [API 测试工具](https://tushare.pro/document/1)
- [积分说明](https://tushare.pro/document/1?doc_id=108)

## 目录结构

```
tushare-complete/
├── SKILL.md                    # Skill 主文档
├── QUICK_REFERENCE.md           # 快速参考手册
├── README.md                   # GitHub 项目说明
└── reference/
    ├── 接口文档/               # 接口详细文档（98个）
    ├── FIELD_REFERENCE.md         # 字段速查手册
    └── README.md
```

## 许可证

MIT License

---

*最后更新时间：2026-02-02 10:51*