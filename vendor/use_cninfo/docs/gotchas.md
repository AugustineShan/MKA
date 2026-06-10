# Gotchas / 已知陷阱

把 2026-05-04 实战踩到的坑都列出来,新项目避免重蹈。

## 1. `pageSize` 服务端硬限 30

**症状**:传 `pageSize=500` 仍只返 30 条,以为接口有 bug。

**实测**:30 / 100 / 200 / 500 全部返 30。

**对策**:翻页,`pageNum=1, 2, 3, ...`,直到 `hasMore=false` 或本页 < 30。

## 2. 按 stock 查需要 orgId,且不公开

**症状**:`stock=301580` 返 0 条,以为代码错了。

**实测**:`stock=301580,gfbj0870132` 才有数据。`gfbj0870132` 是 cninfo 给爱迪特的内部 id。

**绕过**:
- (a) 不传 stock,用 `plate + seDate + category` 查全市场再 in-memory 过滤 secCode
- (b) 第一次查到 ts_code 时缓存返回的 orgId
- (c) scrape `http://www.cninfo.com.cn/new/disclosure/stock?stockCode=301580` HTML 页面拿 orgId(redirect URL 里有)

## 3. 标题格式因板块而异(精确过滤陷阱)

**症状**:写过滤 `title == "2025年年度报告"` 漏掉沪市股票,因为它们是 `凯盛科技股份有限公司2025年年度报告`(全公司名前缀)。

**已知格式**:
- 创业板/科创板:`2025年年度报告`(短)
- 沪市老牌国企:`<公司全名>2025年年度报告`(全名前缀)
- 部分公司:`<sec_name>:2024年年度报告`(冒号前缀)
- 同一公司同一报告可能有 2 条记录(不同 announcementId,标题略有差异 — 一条带前缀一条不带)

**对策**:
```python
import re
def is_main_annual_report(title: str, year: int) -> bool:
    """匹配 'YYYY年年度报告' 但不要摘要 / 审计 / 内控 / 提示性公告。"""
    title = re.sub(r'</?em>', '', title).strip()
    if title.endswith('摘要'):
        return False
    if any(kw in title for kw in ['审计报告', '内部控制', '提示性公告', '披露']):
        return False
    return bool(re.search(rf'{year}年年度报告$', title))
```

## 4. `announcementTime` 是 UTC epoch ms,差 8 小时

**症状**:`ann_date` 比真实披露日期早一天。

**根因**:`announcementTime: 1745856000000` 是 UTC 0 点,直接 strftime 算出的日期是 4/28,但实际披露是北京时间 4/29。

**对策**:
```python
from datetime import datetime, timezone, timedelta
beijing = timezone(timedelta(hours=8))
ann_date = datetime.fromtimestamp(ts/1000, tz=beijing).strftime("%Y%m%d")
```

或者偷懒:`(ts/1000 + 8*3600)` 先加 8h 再转。

## 5. 同一公告可能有 2 条记录(去重)

**症状**:cninfo 列表里同一只股票同一份报告出现 2 条,announcementId 不同但 PDF 内容一样。

**实测**:
- `id=874169 title=爱迪特:2024年半年度报告 url=...874169.PDF`
- `id=879117 title=2024年半年度报告 url=...879117.PDF`

**根因**:cninfo 后台对同一份 PDF 在 sz/全市场 两个分类页都有索引,导致重复。

**对策**:
- 按 `(secCode, ann_date_normalized, title 去前缀)` 去重
- 或按 `(secCode, ann_date, adjunctSize)` 去重(同一 PDF 大小一致)
- 优先保留 announcementId 较小的(那条通常更早入库)

## 6. searchkey 是模糊 LIKE,不可信

**症状**:`searchkey=600552` 返 2 条都对,但不能用来精确按代码查(不同股票若 secCode 含 600552 子串也会被搜到)。

**对策**:`searchkey` 只作辅助,精确查永远是 in-memory 过滤 `it["secCode"] == "600552"`。

## 7. 部分老 PDF URL 可能 404

**症状**:2024-06 之前的 `static.cninfo.com.cn/finalpage/...PDF` 偶尔返 404。

**根因**:cninfo 系统迁移过,某些老 URL 可能失效。

**对策**:
- 失败重试 3 次,如仍 404 则记 failure 表,不再尝试
- 不要让单个 404 阻塞整个 pipeline

## 8. 部分 PDF 是扫描件,PyMuPDF 提不到字

**症状**:PDF 下载成功,PyMuPDF 解析后 `text_chars=0`,失败原因 `empty_pdf`。

**根因**:多为律所审计意见 / 内部控制鉴证报告,会计师事务所习惯打印盖章再扫描传 PDF。

**实测占比**:总公告中 ~10-30% 是扫描件(集中在律所/会计师事务所类公告),**年报本体 / 季报本体几乎不会是扫描件**(< 1%)。

**对策**:
- 接受现实,记录 `extracted_pages=0` 但仍保留元数据
- 如要解决:接 OCR(Apple Vision / Tesseract / OpenDataLoader-PDF)
- ROI 视下游需求决定

## 9. plate 不传时 column=szse 多出 ~860 条

**症状**:`plate=sz + plate=sh = 25,194` 但 `不传 plate, column=szse = 26,053`,差 859。

**推测**:差额是北交所(plate=bj)+ 全国股转 / 老三板等。

**对策**:严肃统计时分别按 sz/sh/bj 拉,或不传 plate 一次拉全。

## 10. cninfo 返回 title 含 `<em>` 高亮标签(searchkey 用)

**症状**:`title="<em>凯盛科技</em>股份有限公司2025年年度报告"`,直接用作文件名会带 HTML 标签。

**对策**:落盘前先 `re.sub(r'</?em>', '', title)` 清洗。

## 11. cninfo 的 secCode 不带后缀

**症状**:cninfo 返回 `secCode=301580`,本地 ts_code 习惯写 `301580.SZ`。

**对策**:
- 写映射:`f"{secCode}.{ {'sz':'SZ','sh':'SH','bj':'BJ'}[plate] }"` 拼出 ts_code
- 或简单 dispatch:`'.SZ' if secCode.startswith(('0','3')) else '.SH' if secCode.startswith('6') else '.BJ'`(粗略,不严谨)
- 严谨:存 `(plate, secCode)` 复合 key,不单纯 ts_code

## 12. 频次反爬可能不是立即可见

**症状**:5 次连发都成功,但持续 1 小时 1000+ 请求时未测试是否会被 throttle。

**对策**:
- 大批量回补时**每 100 请求 sleep 30s**(分批)
- 单日全市场拉(870 页)用 0.5-1s 间隔,总 7-15 分钟
- 监控 503/429,出现立即停止 + 报警

## 13. 长跑要有 singleton lock

**症状**:cron 每天 22:30 触发,如果上一轮还在跑(超 24h)会重复启动,撞 IO + 数据库锁。

**对策**:`fcntl.flock` 单文件锁,fcntl 在进程死后自动释放,适合 cron 重叠保护。
```python
import fcntl
LOCK = open("/tmp/cninfo_sync.lock", "w")
try:
    fcntl.flock(LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print("已有实例在跑,退出")
    sys.exit(2)
```

## 14. SQLite WAL 在长跑 reader 下会无限增长

**症状**:大批量写入时如果同时有长跑 reader,WAL 文件会涨到 GB 级。

**对策**:
- 大批量写前 kill 所有 reader
- 写完后 `PRAGMA wal_checkpoint(TRUNCATE)`
- 不要在 sync 写脚本里设 `PRAGMA journal_mode=WAL`(已是 WAL,重设会撞 BUSY)
