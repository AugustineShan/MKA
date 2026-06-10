# cninfo `hisAnnouncement/query` API Reference

完整参数 / 返回结构 / 已验证 schema。所有数据基于 2026-05-04 实测。

## 端点

```
POST http://www.cninfo.com.cn/new/hisAnnouncement/query
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
```

也支持 HTTPS(`https://`),功能一致。

## 必要 headers

```http
User-Agent: Mozilla/5.0 (...)              # 任何浏览器 UA 即可
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
X-Requested-With: XMLHttpRequest           # 推荐加,模拟 ajax
Accept: application/json, text/plain, */*  # 可省
```

不加 `User-Agent` 可能被简单 throttle 拒绝,加上即正常。无需 cookie / token。

## 请求参数(form-urlencoded body)

| 参数 | 必填 | 取值示例 | 说明 |
|---|---|---|---|
| `tabName` | 是 | `fulltext` | 固定值,搜全文 tab |
| `pageSize` | 是 | `30` | **硬限 30,传 100/200/500 也只返 30** |
| `pageNum` | 是 | `1` 起算 | 翻页用 |
| `column` | 是 | `szse` / `sse` | 板块大类。`szse` 含深市+创业板+北交所;`sse` 含沪市+科创板。一般用 `szse` |
| `category` | 否 | `category_ndbg_szsh` 等 | 不传 = 全 category。见下文 category 列表 |
| `plate` | 否 | `sz` / `sh` / `bj` | 二级过滤。**强烈建议带,否则日返几万条** |
| `searchkey` | 否 | `2025年年度报告` 或 `301580` | 关键词搜 title 或 secCode |
| `seDate` | 否 | `2026-04-29~2026-04-29` | 日期范围,**格式 YYYY-MM-DD~YYYY-MM-DD**(短横线!) |
| `stock` | 否 | `301580,gfbj0870132` | **必须 `<6位code>,<orgId>` 格式**,只传 6 位返 0 条;orgId 是 cninfo 内部 id 不公开映射 |
| `secid` | 否 | (空) | 用途不明,留空即可 |
| `trade` | 否 | (空) | 行业过滤,留空即可 |
| `sortName` | 否 | (空) | 排序字段,留空默认按时间倒序 |
| `sortType` | 否 | (空) | desc / asc |
| `isHLtitle` | 否 | `true` | true 时 searchkey 命中部分会用 `<em>` 包裹 |

**实测**:`pageSize` 改大无效,服务端硬限 30。

**实测**:`stock=301580`(无 orgId) → 返回 0 条。`stock=301580,gfbj0870132` → 正常返回。这意味着按股票精确查需要 orgId 映射,绕过办法是不传 stock,只用 `plate + seDate + category` 拉全市场再过滤 secCode。

## 返回 JSON 结构

```json
{
  "totalSecurities": <int>,           // 命中股票总数
  "totalAnnouncement": <int>,         // 公告总数(用此值估翻页)
  "totalRecordNum": <null>,
  "announcements": [
    {
      "id": null,
      "secCode": "301580",
      "secName": "爱迪特",
      "orgId": "gfbj0870132",         // ← 这个 orgId 可以缓存!
      "announcementId": "1225238305",
      "announcementTitle": "2025年年度报告",
      "announcementTime": 1745856000000,   // epoch ms,UTC
      "adjunctUrl": "finalpage/2026-04-29/1225238305.PDF",
      "adjunctSize": 1551,           // KB
      "adjunctType": "PDF",
      "storageTime": null,
      "columnId": null,
      "pageColumn": "ASCXX",
      "announcementType": "01010503",
      "announcementTypeName": null,
      "associateAnnouncement": null,
      "important": null,
      "batchNum": null,
      "announcementContent": "",
      "orgName": null,
      "tileSecName": null,
      "shortTitle": null,
      "announcementTypeStatus": null,
      "secNameOther": null
    }
  ],
  "classifiedAnnouncements": null,
  "totalpages": <int>,
  "hasMore": true|false,             // 是否还有下一页
  "categoryList": null
}
```

## 关键字段含义

- **`secCode`**:6 位股票代码(无后缀)
- **`orgId`**:cninfo 内部公司 id,**唯一可靠的精确按股票查的 key**;格式如 `gfbj0870132` (深) / `gssh0600552` (沪 老格式) / `9900000040` (新格式纯数字)。**首次查到一只股票后应缓存映射**。
- **`announcementId`**:公告唯一 id,**可作为本地 announcements 表的 PK**(cninfo 自己的稳定 id,长期不变)
- **`announcementTime`**:UTC epoch milliseconds(注意时区!披露时间可能 +8h)
- **`adjunctUrl`**:相对路径,前缀 `http://static.cninfo.com.cn/` 即直链 PDF

## PDF 直链

```
http://static.cninfo.com.cn/<adjunctUrl>
```

**特点**:
- 静态文件,直接 GET 拿 PDF binary
- 无需 cookie / referer
- 长期可访问(2021 年的 PDF 也能下)
- 但 **2024-06 以前** 部分 URL 可能 404(老系统迁移过)

## category 列表(已知)

定期报告(本次重点):

| 名称 | category | plate 范围 | 4/1-5/4 实测 |
|---|---|---|---|
| 年度报告 | `category_ndbg_szsh` | sz/sh/bj | 全市场 8914 条 |
| 一季度报告 | `category_yjdbg_szsh` | sz/sh/bj | 全市场 5582 条 |
| 半年度报告 | `category_bndbg_szsh` | sz/sh/bj | 全市场 54 条(集中 8 月) |
| 三季度报告 | `category_sjdbg_szsh` | sz/sh/bj | 全市场 41 条(集中 10 月) |

其它常见 category(根据 cninfo 公告分类页推测,**未在本次会话验证**):
- `category_yjdbg_szsh` — 一季报
- `category_bndbg_szsh` — 半年报
- `category_sjdbg_szsh` — 三季报
- `category_yjygjxz_szsh` — 业绩预告
- `category_yjkb_szsh` — 业绩快报
- `category_qyfpxzcs_szsh` — 权益分派
- `category_dshgg_szsh` — 董事会公告
- `category_jshgg_szsh` — 监事会公告
- `category_gddh_szsh` — 股东大会
- `category_gqjl_szsh` — 股权激励
- `category_zj_szsh` — 中介报告
- `category_qtzlhz_szsh` — 其它资料汇总

完整 category 列表建议在新项目第一步**自动探测**(打开 cninfo 网站浏览器控制台抓 cninfo 自己的 ajax 即可)。

## plate 取值

| plate | 含义 | 4/29 当日公告数(实测) |
|---|---|---|
| `sz` | 深市(主板 + 创业板) | 17,599 |
| `sh` | 沪市(主板 + 科创板) | 7,595 |
| `bj` | 北交所 | (含在 column=szse 总数里,单独统计待补) |
| (不传) | 由 column 决定 | column=szse 全市场 26,053 |

**注意**:`column=szse` + 不传 plate 比 sz+sh 多 ~860 条,差额是北交所 + 其它(如全国股转/老三板)。

## 频次实测

- 5 次连发 stock 查询:5/5 成功
- 单次响应 ~0.2-0.3s
- 未触发反爬

**保守建议**:
- 间隔 0.3-0.5s/请求
- 大批量回补时 1s/请求(避免被识别为 bot)
- 失败 503/429 时 backoff 30s 再试
- 长跑用 IP 单一来源,不要频繁换

## 辅助接口

### `topSearch/query` — secCode → orgId 映射(已实证)

```
POST http://www.cninfo.com.cn/new/information/topSearch/query
Content-Type: application/x-www-form-urlencoded
body: keyWord=600519&maxNum=10
```

返回 JSON 数组,每条:

```json
{"code":"600519","pinyin":"gzmt","sjstsBond":"false","category":"A股",
 "type":"shj","delisted":"false","orgId":"gssh0600519","zwjc":"贵州茅台"}
```

**用途**:这是拿 `orgId` 最直接的途径,比 scrape `/disclosure/stock` HTML 页可靠得多(后者是 SPA,orgId 由 JS 动态渲染,直接 curl 抓不到)。本项目 `src/cninfo/orgid.py` 即基于此。

实测 2026-05-04 有效。无需任何鉴权,UA 任意,与 `hisAnnouncement/query` 同级反爬策略。

## 待探索接口

- `/data20/queryStockInfo` — 本次返 404
- `/new/data/szse_stock` — 本次返 404
- `/api/disclosure/category/getAnnouncementCategory` — 推测返回 category 完整列表
- `/api/cms/search` 系列 — 推测返回搜索接口
