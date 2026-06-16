# Capabilities & Limits

## ✅ 能做什么

### 1. 按股票 + 日期范围查全部公告
```
stock=<6位code>,<orgId>
seDate=2026-04-27~2026-05-04
```
**验证**:爱迪特 7 天 32 条公告,完整。

### 2. 按日期 + 全市场查
```
plate=sz   seDate=2026-04-29~2026-04-29     → 17,599 条
plate=sh   seDate=2026-04-29~2026-04-29     → 7,595 条
column=szse(不传 plate)单日全市场      → 26,053 条
```

### 3. 按 category 过滤
```
category=category_ndbg_szsh   plate=sz   seDate=2026-04-01~2026-05-04   → 4,833 条年报
```
四类定期报告(年报/一季/半年/三季)category 字符串已实证(见 `api_reference.md`)。

### 4. 翻页
```
pageNum=1, 2, 3, ...     // 每页 30 条,直到 hasMore=false
```

### 5. PDF 直链下载
```
adjunctUrl 字段拼接 http://static.cninfo.com.cn/ 前缀即可 GET binary
```

### 6. PyMuPDF 解析全文
- 286 页年报 ≈ 1-2s 解析(单进程)
- 文本提取率 ≥ 95%(年报/季报本体几乎不会是扫描件)
- **少数律所审计意见 / 内部控制鉴证报告** 是扫描件,PyMuPDF 提不到字 → 需 OCR 或接受

### 7. orgId 通过列表查询自然返回
```python
df = query(plate="sz", seDate="2026-04-29~2026-04-29", category="category_ndbg_szsh")
for it in df.announcements:
    org_id = it["orgId"]      # 缓存这个映射,后续按股票查更精准
    sec_code = it["secCode"]
```

## ⚠️ 不能做(硬限制)

### 1. `pageSize` 不可调,固定 30
传 100/200/500 全部返 30。**全量回补必须翻页**。

### 2. 按纯股票代码查不可用
`stock=301580`(无 orgId)→ **0 条返回**。必须 orgId,且 cninfo 不公开 orgId 映射表。

绕过办法:
- (a) 不传 stock,只用 `plate + seDate + category` 拉全市场再 in-memory 过滤 secCode
- (b) 第一次查到时缓存 `secCode → orgId` 映射
- (c) 从 cninfo HTML 页 scrape `<a href="/new/disclosure/stock?stockCode=XXX&orgId=YYY">` 拿映射

### 3. searchkey 是模糊匹配 title,不是 secCode
`searchkey=600552` 也工作,但因为它在所有字段做 LIKE 匹配,可能漏。建议**只作辅助过滤**,严肃查询用 secCode in-memory 过滤。

### 4. 时区注意
`announcementTime` 是 epoch ms,**当 UTC 处理**。北京时间 +8h,所以转 ann_date 时:
```python
from datetime import datetime, timezone, timedelta
beijing = timezone(timedelta(hours=8))
ann_date = datetime.fromtimestamp(ts/1000, tz=beijing).strftime("%Y%m%d")
```
否则跨日公告 ann_date 会差一天。

### 5. 标题格式不一(陷阱)
- 创业板/科创板:`2025年年度报告`
- 沪市老牌国企:`凯盛科技股份有限公司2025年年度报告`(全公司名前缀)
- 部分公司:`<sec_name>:2024年年度报告`(冒号前缀)

精确过滤"年报本体非摘要"应该用:
```python
title_norm = re.sub(r'<\/?em>', '', title).strip()
is_main_report = (
    re.search(r'\d{4}年(年度|第一季度|半年度|第三季度)报告$', title_norm)
    and not title_norm.endswith('摘要')
)
```

## 📊 容量估算

### 单维度

| 维度 | 数字 |
|---|---|
| 单日全市场公告 | ~26,000 条 |
| 单日翻页量 | 26000 / 30 = 870 页 |
| 单页响应时间 | 0.2-0.3s |
| 单日下载耗时(全速) | ~3.6 分钟 |
| 单日下载耗时(0.5s sleep) | ~7-8 分钟 |

### 全量回补

| 范围 | 估算 |
|---|---|
| 单日 5500 只 × 4 类定期报告 | 一年披露集中在 4 月底 + 8 月底 + 10 月底 |
| 一年(250 交易日)全公告 | ~15 小时(全速) |
| 5 年(2021-2026) | ~75 小时 ≈ 3 天(全速),保守 5-7 天 |
| 单 PDF 平均大小 | 年报 1-2 MB,季报 50-200 KB |
| 全市场 5 年 PDF 总下载量 | ~50-100 GB(原始 PDF) |
| 全文 md 总大小 | ~5-10 GB(只存提取后文本,不存 PDF) |

## 🛡️ 反爬观察

实测 5 次/秒连发未触发任何阻断,但保守建议:
- **请求间隔**:0.3-0.5s(列表查询);1s+(批量)
- **失败重试**:看到 503/429 backoff 30s 重试 3 次
- **总并发**:单 worker 顺序跑(不要多线程跑同一个 endpoint)
- **PDF 下载**:可与列表查询并行(走不同 host:`static.cninfo.com.cn` vs `www.cninfo.com.cn`)

如发现 IP 被 ban:
- 等 1 小时(短期)或 24 小时(中期)
- 切到 HTTPS / 不同 UA / 不同 source IP
- 加大 sleep,降到 2s/请求

## 🌐 IP / 网络

测试期没有用代理。但网络环境差时:
- 国内访问 `cninfo.com.cn` 直连最快
- 走代理 / VPN 可能被 cninfo 拒绝(实测过 `127.0.0.1:1082` socks 代理在某些请求上 timeout)

## 推荐策略(给新项目)

### 全量初始化
1. 按 `category × plate × month` 切片(年报/一季/半年/三季 × sz/sh/bj),每个切片翻页拉公告列表
2. 拿到 PDF URL list 后,异步并行下载(限 8-12 worker)
3. PyMuPDF 解析 + 落文件森林 + DB 元数据
4. 总耗时 5-7 天(保守)

定期报告披露窗口集中在 4 月底(年报+一季报)/ 8 月底(半年报)/ 10 月底(三季报),按这些月份切片更省请求。

### 增量
1. 每天 22:30 跑一次 `seDate=昨天~今天` 全 category,翻页
2. 与本地 announcements 表 LEFT JOIN 找新增
3. 下载新 PDF + 入库
4. 单次跑 ~10-30 分钟

### 维护
- `sync_state.json` 记录每个 (category, plate) 的 last_seDate
- failure 表记录连续失败的 ann_id(3 次 fail 后跳过)
- 每周日跑 `verify` 检查 file forest 与 DB 是否一致
