"""Prepare ADJ incremental materials as Markdown.

The /adj incremental mode reads marginal business information from the company
ADJ material folder. As with /brkd, the AI step should read only deterministic
Markdown, not raw PDF/Word/Excel files.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.brkd_prepare import (
    BrkdPrepareError,
    MaterialResult,
    _source_files,
    convert_material,
    resolve_company,
)
from src.company_paths import (
    COMPANIES_DIR,
    adj_increment_dir,
    adj_markdown_store_dir,
)


class AdjPrepareError(RuntimeError):
    """Raised when ADJ incremental materials cannot be prepared."""


def prepare_adj_materials(
    company: str | Path | None = None,
    *,
    folder: str | Path | None = None,
    force: bool = False,
    companies_dir: Path = COMPANIES_DIR,
) -> dict[str, Any]:
    if folder is not None:
        source_dir = Path(folder)
        company_dir = None
        markdown_dir = source_dir / "markdown存储区"
    elif company is not None:
        try:
            company_dir = resolve_company(company, companies_dir=companies_dir)
        except BrkdPrepareError as exc:
            raise AdjPrepareError(str(exc)) from exc
        source_dir = adj_increment_dir(company_dir)
        markdown_dir = adj_markdown_store_dir(company_dir)
    else:
        raise AdjPrepareError("provide company or folder")

    if not source_dir.exists():
        raise AdjPrepareError(f"ADJ material directory does not exist: {source_dir}")

    sources = _source_files(source_dir)
    markdown_dir.mkdir(parents=True, exist_ok=True)
    results: list[MaterialResult] = [
        convert_material(source, markdown_dir, force=force) for source in sources
    ]
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    manifest = {
        "mode": "adj_prepare",
        "company_dir": str(company_dir) if company_dir is not None else None,
        "source_dir": str(source_dir),
        "markdown_dir": str(markdown_dir),
        "force": force,
        "source_count": len(sources),
        "counts": counts,
        "materials": [asdict(result) for result in results],
    }
    (markdown_dir / "adj_prepare_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _print_manifest(manifest: dict[str, Any]) -> None:
    print(f"ADJ source dir: {manifest['source_dir']}")
    print(f"Markdown store: {manifest['markdown_dir']}")
    print(f"Sources: {manifest['source_count']}")
    for status, count in sorted((manifest.get("counts") or {}).items()):
        print(f"{status}: {count}")
    for item in manifest.get("materials", []):
        print(f"- [{item['status']}] {Path(item['source_path']).name} -> {Path(item['markdown_path']).name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare ADJ materials into markdown存储区")
    parser.add_argument("company", nargs="?", help="公司名、裸代码、完整 ticker 或公司目录")
    parser.add_argument("--folder", type=Path, help="直接指定 ADJ 增量信息文件夹")
    parser.add_argument("--force", action="store_true", help="强制重新转换")
    args = parser.parse_args()

    try:
        manifest = prepare_adj_materials(args.company, folder=args.folder, force=args.force)
    except Exception as exc:  # noqa: BLE001 - CLI should report concise failure.
        print(f"ADJ prepare failed: {exc}")
        return 2
    _print_manifest(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
