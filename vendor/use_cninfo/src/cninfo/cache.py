"""本地长期缓存层。

布局(根目录可被 $CNINFO_CACHE_DIR 覆盖,默认 ~/.cache/cninfo):

    <root>/
    ├── orgid_map.json                                        # secCode → orgId
    ├── pdf/<ts_code>/<ann_date>__<ann_id>.pdf                # 原始 PDF
    ├── md/<ts_code>/<ann_date>__<ann_id>.md                  # PyMuPDF 全文 + YAML frontmatter
    └── meta/<ann_id>.json                                    # 单条公告原始 cninfo 返回 + 派生字段

命中策略:
- pdf + md + meta 三件齐全才算命中
- 任一缺失走"未命中"路径(回源 + 重写三件)
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "cninfo"


def cache_root() -> Path:
    env = os.environ.get("CNINFO_CACHE_DIR")
    return Path(env).expanduser() if env else DEFAULT_CACHE_ROOT


@dataclass
class CachePaths:
    pdf: Path
    md: Path
    meta: Path

    def all_exist(self) -> bool:
        return self.pdf.exists() and self.md.exists() and self.meta.exists()

    def any_exist(self) -> bool:
        return self.pdf.exists() or self.md.exists() or self.meta.exists()


def paths_for(ts_code: str, ann_date: str, ann_id: str | int) -> CachePaths:
    root = cache_root()
    ann_id = str(ann_id)
    fname = f"{ann_date}__{ann_id}"
    return CachePaths(
        pdf=root / "pdf" / ts_code / f"{fname}.pdf",
        md=root / "md" / ts_code / f"{fname}.md",
        meta=root / "meta" / f"{ann_id}.json",
    )


def write_pdf(paths: CachePaths, data: bytes) -> None:
    paths.pdf.parent.mkdir(parents=True, exist_ok=True)
    paths.pdf.write_bytes(data)


def write_md(paths: CachePaths, frontmatter: dict, body: str) -> None:
    paths.md.parent.mkdir(parents=True, exist_ok=True)
    yaml = "---\n"
    for k, v in frontmatter.items():
        if isinstance(v, str):
            yaml += f'{k}: "{v}"\n'
        else:
            yaml += f"{k}: {json.dumps(v, ensure_ascii=False)}\n"
    yaml += "---\n\n"
    paths.md.write_text(yaml + body, encoding="utf-8")


def write_meta(paths: CachePaths, meta: dict) -> None:
    paths.meta.parent.mkdir(parents=True, exist_ok=True)
    paths.meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read_meta(paths: CachePaths) -> dict | None:
    if not paths.meta.exists():
        return None
    return json.loads(paths.meta.read_text(encoding="utf-8"))


def read_md(paths: CachePaths) -> str | None:
    if not paths.md.exists():
        return None
    return paths.md.read_text(encoding="utf-8")


# --- orgId 映射 ----------------------------------------------------------

ORGID_MAP_PATH_NAME = "orgid_map.json"


def orgid_map_path() -> Path:
    return cache_root() / ORGID_MAP_PATH_NAME


def load_orgid_map() -> dict[str, str]:
    p = orgid_map_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_orgid_map(m: dict[str, str]) -> None:
    p = orgid_map_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def upsert_orgid(sec_code: str, org_id: str) -> None:
    m = load_orgid_map()
    if m.get(sec_code) == org_id:
        return
    m[sec_code] = org_id
    save_orgid_map(m)


# --- stats / verify / prune ----------------------------------------------

@dataclass
class CacheStats:
    pdf_count: int
    md_count: int
    meta_count: int
    pdf_bytes: int
    md_bytes: int
    meta_bytes: int
    orgid_count: int

    @property
    def total_bytes(self) -> int:
        return self.pdf_bytes + self.md_bytes + self.meta_bytes


def _scan_dir(p: Path) -> tuple[int, int]:
    if not p.exists():
        return 0, 0
    n = 0
    sz = 0
    for f in p.rglob("*"):
        if f.is_file():
            n += 1
            sz += f.stat().st_size
    return n, sz


def stats() -> CacheStats:
    root = cache_root()
    pdf_n, pdf_sz = _scan_dir(root / "pdf")
    md_n, md_sz = _scan_dir(root / "md")
    meta_n, meta_sz = _scan_dir(root / "meta")
    return CacheStats(
        pdf_count=pdf_n,
        md_count=md_n,
        meta_count=meta_n,
        pdf_bytes=pdf_sz,
        md_bytes=md_sz,
        meta_bytes=meta_sz,
        orgid_count=len(load_orgid_map()),
    )


def verify() -> list[str]:
    """返回不一致的告警列表(空 list = 一致)。

    检查:每个 meta/<id>.json 都有对应的 pdf 和 md;反之亦然。
    """
    root = cache_root()
    warnings: list[str] = []

    meta_ids: set[str] = set()
    for f in (root / "meta").rglob("*.json") if (root / "meta").exists() else []:
        meta_ids.add(f.stem)

    pdf_ids: set[str] = set()
    for f in (root / "pdf").rglob("*.pdf") if (root / "pdf").exists() else []:
        ann_id = f.stem.split("__", 1)[-1]
        pdf_ids.add(ann_id)

    md_ids: set[str] = set()
    for f in (root / "md").rglob("*.md") if (root / "md").exists() else []:
        ann_id = f.stem.split("__", 1)[-1]
        md_ids.add(ann_id)

    for aid in meta_ids - pdf_ids:
        warnings.append(f"meta but no pdf: ann_id={aid}")
    for aid in meta_ids - md_ids:
        warnings.append(f"meta but no md: ann_id={aid}")
    for aid in pdf_ids - meta_ids:
        warnings.append(f"pdf but no meta: ann_id={aid}")
    for aid in md_ids - meta_ids:
        warnings.append(f"md but no meta: ann_id={aid}")

    return warnings


def prune_older_than(days: int) -> int:
    """删除 meta.mtime 早于 N 天的所有三件套。返回删除的 ann_id 数。"""
    import time as _time

    cutoff = _time.time() - days * 86400
    root = cache_root()
    meta_dir = root / "meta"
    if not meta_dir.exists():
        return 0

    removed = 0
    for f in meta_dir.rglob("*.json"):
        if f.stat().st_mtime >= cutoff:
            continue
        ann_id = f.stem
        meta = json.loads(f.read_text(encoding="utf-8"))
        ts_code = meta.get("ts_code") or ""
        ann_date = meta.get("ann_date") or ""
        paths = paths_for(ts_code, ann_date, ann_id)
        for p in (paths.pdf, paths.md, paths.meta):
            if p.exists():
                p.unlink()
        removed += 1

    # 顺手清空目录
    for sub in ("pdf", "md"):
        d = root / sub
        if d.exists():
            for ts_dir in d.iterdir():
                if ts_dir.is_dir() and not any(ts_dir.iterdir()):
                    shutil.rmtree(ts_dir)

    return removed
