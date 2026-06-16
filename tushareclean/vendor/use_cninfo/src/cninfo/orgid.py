"""secCode → orgId 映射。

cninfo 的 `hisAnnouncement/query` 必须用 `<6位>,<orgId>` 才能精确按股票查,只传 6 位返 0 条。
本模块负责拿 orgId 并缓存到 ~/.cache/cninfo/orgid_map.json。

来源(实测有效,2026-05-04):
    POST http://www.cninfo.com.cn/new/information/topSearch/query
    body: keyWord=<code>&maxNum=10
    返回: [{"code":"600519","orgId":"gssh0600519","zwjc":"贵州茅台",...}, ...]

未命中时会自动调一次该接口拉 orgId 并写入 cache。
"""

from __future__ import annotations

import requests

from cninfo.api import DEFAULT_HEADERS
from cninfo.cache import load_orgid_map, upsert_orgid

TOPSEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"


class OrgIdNotFound(LookupError):
    """sec_code 在 cninfo topSearch 中查不到 orgId(下市 / 代码错 / 接口变)。"""


def lookup_orgid(
    sec_code: str,
    *,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> str:
    """同步拉一次 cninfo topSearch,返回精确匹配的 orgId(同时写入 cache)。"""
    s = session or requests
    body = {"keyWord": sec_code, "maxNum": "10"}
    r = s.post(TOPSEARCH_URL, headers=DEFAULT_HEADERS, data=body, timeout=timeout)
    r.raise_for_status()
    items = r.json()
    if not isinstance(items, list):
        raise OrgIdNotFound(f"unexpected topSearch response for {sec_code}: {items!r}")
    for it in items:
        if it.get("code") == sec_code and it.get("orgId"):
            org_id = it["orgId"]
            upsert_orgid(sec_code, org_id)
            return org_id
    raise OrgIdNotFound(f"orgId not found for sec_code={sec_code}")


def get_orgid(sec_code: str, *, fetch_if_missing: bool = True) -> str:
    """从 cache 拿 orgId,缺失时按需回源。"""
    m = load_orgid_map()
    if sec_code in m:
        return m[sec_code]
    if not fetch_if_missing:
        raise OrgIdNotFound(f"orgId not cached for sec_code={sec_code}")
    return lookup_orgid(sec_code)


def stock_param(sec_code: str) -> str:
    """拼出 cninfo `hisAnnouncement/query` 的 `stock` 参数 `<6位>,<orgId>`。"""
    return f"{sec_code},{get_orgid(sec_code)}"
