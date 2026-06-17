#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按需抓取 Tushare 官方接口 markdown 文档到本地。

用法示例：
    python D:\MKA\fetch_tushare_api_docs.py --titles 利润表 资产负债表 现金流量表 业绩预告 业绩快报 分红送股数据 财务指标数据 财务审计意见 主营业务构成 财报披露日期表

默认：
    目录文件来源：~/.claude/skills/tushare/references/数据接口.md
    输出目录：D:\MKA\TushareOfficialAPIMD
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


DEFAULT_CATALOG = Path.home() / ".claude" / "skills" / "tushare" / "references" / "数据接口.md"
DEFAULT_OUTPUT_DIR = Path(r"D:\MKA\TushareOfficialAPIMD")
BASE_URL = "https://tushare.pro/wctapi/documents/"


def parse_catalog(catalog_path: Path):
    """解析数据接口.md，返回接口记录列表。"""
    if not catalog_path.exists():
        raise FileNotFoundError(f"目录文件不存在: {catalog_path}")

    text = catalog_path.read_text(encoding="utf-8")
    records = []
    # 匹配 markdown 表格行，格式：| [接口名](URL) | 标题 | 分类 | 描述 |
    pattern = re.compile(
        r"\|\s*\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)\s*\|\s*(?P<title>[^|]+)\|\s*(?P<category>[^|]+)\|\s*(?P<desc>[^|]+)\|"
    )
    for match in pattern.finditer(text):
        records.append(
            {
                "name": match.group("name").strip(),
                "url": match.group("url").strip(),
                "title": match.group("title").strip(),
                "category": match.group("category").strip(),
                "desc": match.group("desc").strip(),
            }
        )
    return records


def find_records(records, titles=None, names=None, categories=None):
    """按标题/接口名/分类筛选记录。"""
    selected = []
    titles = set(titles or [])
    names = set(names or [])
    categories = set(categories or [])

    for rec in records:
        if titles and rec["title"] in titles:
            selected.append(rec)
        elif names and rec["name"] in names:
            selected.append(rec)
        elif categories and any(c.strip() in rec["category"] for c in categories):
            selected.append(rec)

    # 去重保持顺序
    seen = set()
    unique = []
    for rec in selected:
        key = rec["name"]
        if key not in seen:
            seen.add(key)
            unique.append(rec)
    return unique


def download_markdown(record: dict, output_dir: Path, session: requests.Session):
    """下载单个接口 markdown 并保存。"""
    url = record["url"]
    name = record["name"]
    title = record["title"]
    filename = f"{name}.md"
    output_path = output_dir / filename

    print(f"  正在下载: {name} ({title}) -> {output_path}")
    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    # 保持 UTF-8 保存
    output_path.write_text(resp.text, encoding="utf-8")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="抓取 Tushare 官方接口 markdown 文档")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="数据接口.md 路径",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录",
    )
    parser.add_argument(
        "--titles",
        nargs="+",
        help="按中文标题下载，可多个",
    )
    parser.add_argument(
        "--names",
        nargs="+",
        help="按接口名下载，可多个",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        help="按分类下载，可多个",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="下载目录中全部接口",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="请求间隔秒数（默认 0.5）",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    records = parse_catalog(args.catalog)
    print(f"目录解析完成，共 {len(records)} 个接口记录")

    if args.all:
        selected = records
    elif args.titles or args.names or args.categories:
        selected = find_records(records, args.titles, args.names, args.categories)
    else:
        print("错误：请指定 --titles / --names / --categories 之一，或使用 --all")
        sys.exit(1)

    if not selected:
        print("未匹配到任何接口，请检查标题/接口名/分类")
        sys.exit(1)

    print(f"准备下载 {len(selected)} 个接口文档到 {output_dir}")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
    )

    success = []
    failed = []
    for rec in selected:
        try:
            download_markdown(rec, output_dir, session)
            success.append(rec)
        except Exception as e:
            print(f"  下载失败: {rec['name']} - {e}")
            failed.append((rec, str(e)))
        time.sleep(args.delay)

    print(f"\n完成：成功 {len(success)} 个，失败 {len(failed)} 个")
    if failed:
        print("失败列表:")
        for rec, err in failed:
            print(f"  - {rec['name']}: {err}")


if __name__ == "__main__":
    main()
