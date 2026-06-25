"""Prepare KA highest-weight materials as Markdown.

The /ka AI step should align to analyst-provided high-weight materials, but it
should not read raw Office/PDF files directly.  This module converts the root
``公司判断和最新观点.md`` plus top-level files under
``Skills素材包/最高权重材料-放Agent最应对齐的材料`` into that folder's
``markdown存储区`` and writes a manifest.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.brkd_prepare import _safe_output_name, _source_files, convert_material
from src.company_paths import (
    COMPANIES_DIR,
    find_company_dir,
    top_weight_markdown_store_dir,
    top_weight_material_dir,
)


DEFAULT_CORE_VIEW = "公司判断和最新观点.md"
MANIFEST_NAME = "ka_prepare_manifest.json"


class KaPrepareError(RuntimeError):
    """Raised when KA high-weight materials cannot be prepared."""


def resolve_company(raw: str | Path, *, companies_dir: Path = COMPANIES_DIR) -> Path:
    path = Path(raw)
    if path.exists() and path.is_dir():
        return path

    text = str(raw).strip()
    if not text:
        raise KaPrepareError("company argument is empty")

    if re.fullmatch(r"\d{6}(?:\.(?:SZ|SH|BJ))?", text.upper()):
        return find_company_dir(text, companies_dir)

    candidates = sorted(companies_dir.glob(f"{text}_*"))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise KaPrepareError(f"multiple company directories match {text}: {names}")
    raise KaPrepareError(f"no company directory matches {text}")


def _source_entries(company_dir: Path) -> list[tuple[Path, str, str | None]]:
    source_dir = top_weight_material_dir(company_dir)
    entries: list[tuple[Path, str, str | None]] = []

    core_view = company_dir / DEFAULT_CORE_VIEW
    if core_view.exists() and core_view.is_file():
        entries.append((core_view, "default_core_view", f"00_{_safe_output_name(core_view)}"))

    for source in _source_files(source_dir):
        entries.append((source, "top_weight_material", None))
    return entries


def prepare_top_weight_materials(
    company: str | Path,
    *,
    force: bool = False,
    companies_dir: Path = COMPANIES_DIR,
) -> dict[str, Any]:
    company_dir = resolve_company(company, companies_dir=companies_dir)
    source_dir = top_weight_material_dir(company_dir)
    markdown_dir = top_weight_markdown_store_dir(company_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    markdown_dir.mkdir(parents=True, exist_ok=True)

    materials: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for source, role, output_name in _source_entries(company_dir):
        result = convert_material(source, markdown_dir, force=force, output_name=output_name)
        item = asdict(result)
        item["role"] = role
        materials.append(item)
        counts[result.status] = counts.get(result.status, 0) + 1

    manifest = {
        "mode": "ka_top_weight_prepare",
        "company_dir": str(company_dir),
        "source_dir": str(source_dir),
        "markdown_dir": str(markdown_dir),
        "default_core_view": str(company_dir / DEFAULT_CORE_VIEW),
        "force": force,
        "source_count": len(materials),
        "counts": counts,
        "materials": materials,
    }
    (markdown_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _print_manifest(manifest: dict[str, Any]) -> None:
    print(f"KA top-weight source dir: {manifest['source_dir']}")
    print(f"Markdown store: {manifest['markdown_dir']}")
    print(f"Sources: {manifest['source_count']}")
    for status, count in sorted((manifest.get("counts") or {}).items()):
        print(f"{status}: {count}")
    for item in manifest.get("materials", []):
        source = Path(item["source_path"]).name
        output = Path(item["markdown_path"]).name
        print(f"- [{item['status']}] {item['role']}: {source} -> {output}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare KA highest-weight materials into markdown存储区")
    parser.add_argument("company", help="公司名、裸代码、完整 ticker 或公司目录")
    parser.add_argument("--force", action="store_true", help="强制重新转换")
    args = parser.parse_args()

    try:
        manifest = prepare_top_weight_materials(args.company, force=args.force)
    except Exception as exc:  # noqa: BLE001 - CLI should report concise failure.
        print(f"KA prepare failed: {exc}")
        return 2
    _print_manifest(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
