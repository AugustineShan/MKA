"""cninfo-cli — A 股公告按需抓取 CLI。

子命令:
    fetch-report   单股指定定期报告(annual/q1/h1/q3)
    fetch-stock    单股时间窗全公告
    list           全市场切片(可选 --download)
    search         按 announcement_filter 标签 / cninfo searchkey 搜索
    cache          stats / verify / prune
    orgid          查 / 反查 secCode→orgId
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

from cninfo import __version__
from cninfo import cache as cache_mod
from cninfo.api import (
    KIND_TO_CATEGORY,
    clean_title,
    epoch_ms_to_ann_date,
    guess_plate,
)
from cninfo.fetcher import (
    fetch_announcement,
    find_periodic_report,
    iter_market_slice,
    iter_stock_announcements,
)
from cninfo.orgid import OrgIdNotFound, get_orgid, lookup_orgid

# --------------------------------------------------------------------- helpers

def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _print_table(rows: list[dict], cols: list[str]) -> None:
    if not rows:
        print("(no rows)")
        return
    widths = {c: max(len(c), max((len(str(r.get(c, ""))) for r in rows), default=0)) for c in cols}
    line = "  ".join(c.ljust(widths[c]) for c in cols)
    print(line)
    print("  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


def _err(msg: str, code: int = 1) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return code


# ------------------------------------------------------------------ subcommands


def cmd_fetch_report(args) -> int:
    sec_code = args.code
    plate = args.plate or guess_plate(sec_code)
    try:
        item = find_periodic_report(
            sec_code, year=args.year, kind=args.kind, plate=plate
        )
    except OrgIdNotFound as e:
        return _err(str(e))
    if item is None:
        return _err(
            f"no {args.kind} report body found for {sec_code} year={args.year} (plate={plate})",
            code=2,
        )
    res = fetch_announcement(item, plate, force=args.force)
    _print_json(res.to_dict())
    return 0


def cmd_fetch_stock(args) -> int:
    sec_code = args.code
    plate = args.plate or guess_plate(sec_code)
    rows: list[dict] = []
    session = requests.Session()
    try:
        for item in iter_stock_announcements(
            sec_code,
            since=args.since,
            until=args.until,
            plate=plate,
            category=KIND_TO_CATEGORY.get(args.kind, "") if args.kind else "",
            session=session,
        ):
            row = {
                "ann_id": item.get("announcementId"),
                "sec_code": item.get("secCode"),
                "ann_date": epoch_ms_to_ann_date(int(item.get("announcementTime") or 0)),
                "title": clean_title(item.get("announcementTitle")),
                "adjunct_size_kb": item.get("adjunctSize"),
            }
            if args.download:
                res = fetch_announcement(item, plate, force=args.force, session=session)
                row["cache_hit"] = res.cache_hit
                row["md_path"] = res.md_path
                row["pages"] = res.total_pages
                row["text_chars"] = res.text_chars
            rows.append(row)
    except OrgIdNotFound as e:
        return _err(str(e))

    if args.json:
        _print_json(rows)
    else:
        cols = ["ann_date", "ann_id", "title", "adjunct_size_kb"]
        if args.download:
            cols += ["cache_hit", "pages", "text_chars"]
        _print_table(rows, cols)
    return 0


def cmd_list(args) -> int:
    rows: list[dict] = []
    session = requests.Session()
    category = KIND_TO_CATEGORY.get(args.category, args.category) if args.category else ""
    for item in iter_market_slice(
        plate=args.plate,
        category=category,
        date=args.date,
        since=args.since,
        until=args.until,
        searchkey=args.keyword or "",
        session=session,
    ):
        row = {
            "ann_id": item.get("announcementId"),
            "sec_code": item.get("secCode"),
            "sec_name": item.get("secName"),
            "ann_date": epoch_ms_to_ann_date(int(item.get("announcementTime") or 0)),
            "title": clean_title(item.get("announcementTitle")),
            "adjunct_size_kb": item.get("adjunctSize"),
        }
        if args.download:
            res = fetch_announcement(item, args.plate, force=args.force, session=session)
            row["cache_hit"] = res.cache_hit
            row["md_path"] = res.md_path
        rows.append(row)
        if args.limit and len(rows) >= args.limit:
            break
    if args.json:
        _print_json(rows)
    else:
        cols = ["ann_date", "sec_code", "sec_name", "ann_id", "title"]
        if args.download:
            cols += ["cache_hit", "md_path"]
        _print_table(rows, cols)
    return 0


def cmd_search(args) -> int:
    """标签 / 关键词搜索。

    --type/--sub-type 走 announcement_filter 给每条 title 打标签后过滤。
    --keyword         走 cninfo 原生 searchkey(模糊 LIKE,只搜 title)。
    """
    use_classifier = bool(args.type or args.sub_type)
    if use_classifier:
        try:
            from cninfo.classify import classify
        except ImportError as e:
            return _err(str(e))
    else:
        classify = None  # type: ignore[assignment]

    session = requests.Session()
    rows: list[dict] = []

    # 数据源: --stock 优先,否则用 plate + date/since/until
    if args.stock:
        plate = args.plate or guess_plate(args.stock)
        if not args.since or not args.until:
            return _err("--stock requires --since and --until")
        try:
            iterator = iter_stock_announcements(
                args.stock,
                since=args.since,
                until=args.until,
                plate=plate,
                session=session,
            )
        except OrgIdNotFound as e:
            return _err(str(e))
    else:
        if not args.plate:
            return _err("--plate is required when --stock not given")
        plate = args.plate
        iterator = iter_market_slice(
            plate=plate,
            date=args.date,
            since=args.since,
            until=args.until,
            searchkey=args.keyword or "",
            session=session,
        )

    for item in iterator:
        title = clean_title(item.get("announcementTitle"))
        ann_date = epoch_ms_to_ann_date(int(item.get("announcementTime") or 0))

        # 标签过滤
        tag = None
        if use_classifier:
            try:
                tag = classify(title, ann_date)  # type: ignore[misc]
            except Exception as e:
                return _err(f"classifier error: {e}")
            if args.type and tag.get("type") != args.type:
                continue
            if args.sub_type and tag.get("sub_type") != args.sub_type:
                continue

        # 关键词过滤(client 侧二次过滤,在 cninfo searchkey 已做 LIKE 上加严)
        if args.keyword and args.keyword not in title:
            continue

        row = {
            "ann_id": item.get("announcementId"),
            "sec_code": item.get("secCode"),
            "sec_name": item.get("secName"),
            "ann_date": ann_date,
            "title": title,
        }
        if tag:
            row["type"] = tag.get("type")
            row["sub_type"] = tag.get("sub_type")
        if args.download:
            res = fetch_announcement(item, plate, force=args.force, session=session)
            row["cache_hit"] = res.cache_hit
            row["md_path"] = res.md_path
        rows.append(row)
        if args.limit and len(rows) >= args.limit:
            break

    if args.json:
        _print_json(rows)
    else:
        cols = ["ann_date", "sec_code", "sec_name", "ann_id", "title"]
        if use_classifier:
            cols += ["type", "sub_type"]
        if args.download:
            cols += ["cache_hit", "md_path"]
        _print_table(rows, cols)
    return 0


def cmd_cache(args) -> int:
    sub = args.cache_cmd
    if sub == "stats":
        s = cache_mod.stats()
        _print_json(
            {
                "cache_root": str(cache_mod.cache_root()),
                "pdf_count": s.pdf_count,
                "md_count": s.md_count,
                "meta_count": s.meta_count,
                "orgid_count": s.orgid_count,
                "pdf_bytes": s.pdf_bytes,
                "md_bytes": s.md_bytes,
                "meta_bytes": s.meta_bytes,
                "total_bytes": s.total_bytes,
                "total_human": _human_bytes(s.total_bytes),
            }
        )
        return 0
    if sub == "verify":
        warns = cache_mod.verify()
        if not warns:
            print("ok: cache is consistent")
            return 0
        for w in warns:
            print(f"warn: {w}")
        return 3
    if sub == "prune":
        n = cache_mod.prune_older_than(args.older_than_days)
        print(f"pruned {n} announcement(s) older than {args.older_than_days}d")
        return 0
    return _err(f"unknown cache subcommand: {sub}")


def cmd_orgid(args) -> int:
    sec_code = args.code
    if args.refresh:
        try:
            org_id = lookup_orgid(sec_code)
        except OrgIdNotFound as e:
            return _err(str(e))
        _print_json({"sec_code": sec_code, "orgId": org_id, "source": "cninfo-topSearch"})
        return 0
    try:
        org_id = get_orgid(sec_code, fetch_if_missing=not args.cache_only)
    except OrgIdNotFound as e:
        return _err(str(e))
    _print_json({"sec_code": sec_code, "orgId": org_id})
    return 0


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ----------------------------------------------------------------------- parser


def _parse_older_than(s: str) -> int:
    """'365d' / '12h' / '30' → 天数(向下取整,最少 1)。"""
    s = s.strip().lower()
    if s.endswith("d"):
        return max(1, int(s[:-1]))
    if s.endswith("h"):
        return max(1, int(s[:-1]) // 24 or 1)
    return max(1, int(s))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cninfo", description=__doc__)
    p.add_argument("--version", action="version", version=f"cninfo-cli {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # fetch-report
    sp = sub.add_parser("fetch-report", help="单股指定定期报告(annual/q1/h1/q3)")
    sp.add_argument("code", help="6 位股票代码,如 600519")
    sp.add_argument("--year", type=int, required=True, help="报告所属财年,如 2024")
    sp.add_argument("--kind", choices=["annual", "q1", "h1", "q3"], required=True)
    sp.add_argument("--plate", choices=["sz", "sh", "bj"], help="板块(默认按代码推测)")
    sp.add_argument("--force", action="store_true", help="忽略缓存重新下载")
    sp.set_defaults(func=cmd_fetch_report)

    # fetch-stock
    sp = sub.add_parser("fetch-stock", help="单股时间窗全公告")
    sp.add_argument("code", help="6 位股票代码")
    sp.add_argument("--since", required=True, help="起 YYYY-MM-DD")
    sp.add_argument("--until", required=True, help="止 YYYY-MM-DD")
    sp.add_argument("--plate", choices=["sz", "sh", "bj"])
    sp.add_argument("--kind", choices=["annual", "q1", "h1", "q3"], help="只过滤定期报告类目")
    sp.add_argument("--download", action="store_true", help="下载并解析(默认只列表)")
    sp.add_argument("--force", action="store_true", help="忽略缓存重新下载")
    sp.add_argument("--json", action="store_true", help="JSON 输出")
    sp.set_defaults(func=cmd_fetch_stock)

    # list
    sp = sub.add_parser("list", help="全市场切片")
    sp.add_argument("--plate", choices=["sz", "sh", "bj"], required=True)
    sp.add_argument("--category", help="annual/q1/h1/q3 或原生 category_xxx_szsh 字符串")
    sp.add_argument("--date", help="单日 YYYY-MM-DD(与 since/until 互斥)")
    sp.add_argument("--since")
    sp.add_argument("--until")
    sp.add_argument("--keyword", help="cninfo searchkey(模糊 LIKE)")
    sp.add_argument("--limit", type=int, default=0, help="最多返回多少条(0=不限)")
    sp.add_argument("--download", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    # search
    sp = sub.add_parser("search", help="标签 / 关键词搜索(标签需 announcement_filter)")
    sp.add_argument("--stock", help="6 位股票代码(与 --plate+date/since/until 互斥)")
    sp.add_argument("--plate", choices=["sz", "sh", "bj"])
    sp.add_argument("--date")
    sp.add_argument("--since")
    sp.add_argument("--until")
    sp.add_argument("--type", help="argus_legal type(如 shareholder)")
    sp.add_argument("--sub-type", dest="sub_type", help="argus_legal sub_type(如 reduce_plan)")
    sp.add_argument("--keyword", help="标题关键词(走 cninfo searchkey + 客户端二次过滤)")
    sp.add_argument("--limit", type=int, default=0)
    sp.add_argument("--download", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_search)

    # cache
    sp = sub.add_parser("cache", help="缓存管理")
    csub = sp.add_subparsers(dest="cache_cmd", required=True)
    csub.add_parser("stats", help="缓存命中率 / 占用空间")
    csub.add_parser("verify", help="检查 md/pdf/meta 三件套一致性")
    sp_prune = csub.add_parser("prune", help="按 mtime 删早于 N 天的条目")
    sp_prune.add_argument(
        "--older-than",
        dest="older_than_days",
        type=_parse_older_than,
        default=365,
        help="如 365d / 30d (默认 365d)",
    )
    sp.set_defaults(func=cmd_cache)

    # orgid
    sp = sub.add_parser("orgid", help="查 secCode→orgId 映射")
    sp.add_argument("code", help="6 位股票代码")
    sp.add_argument("--refresh", action="store_true", help="忽略 cache 强制重拉")
    sp.add_argument("--cache-only", action="store_true", help="只查 cache,不回源")
    sp.set_defaults(func=cmd_orgid)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
