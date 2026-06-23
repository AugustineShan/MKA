"""research_pdf2md.py — 把研报/纪要 PDF 转成 Markdown 供 /brkd 读取。

/brkd 业务预理解器"不读 PDF"——只读已转成文本的 .md。外部研报几乎都是 PDF，
本模块是 /brkd 的前置转换器：扫 `active_vore/业务理解器（研报和纪要放在这里）/`，
把每个 .pdf 用 PyMuPDF 抽成同名 .md（UTF-8 + frontmatter 标来源），幂等跳过。

设计:
- 复用项目既有 PyMuPDF(fitz) 引擎（与年报 PDF→MD 同源），确定性、可审计。
- 研报表格/图表抽取会乱，但 /brkd 产物是"研报线索版"非权威——乱表格靠四级可信度标注
  + ka 用年报/clean_annual 校验兜底。故不上 LLM vision（overkill）。
- 不修改原 PDF；.md 落在 PDF 同目录，文件名换后缀。
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import fitz  # PyMuPDF


def _extract_text(pdf_path: Path) -> tuple[str, int]:
    """逐页抽文本，返回 (markdown 正文, 页数)。"""
    parts: list[str] = []
    with fitz.open(pdf_path) as doc:
        n = doc.page_count
        for i, page in enumerate(doc, start=1):
            parts.append(f"## 第 {i} 页\n")
            parts.append(page.get_text("text").strip())
            parts.append("")
    return "\n".join(parts), n


def research_pdf_to_md(pdf_path: Path, *, force: bool = False) -> Path:
    """把单个 PDF 转成同名 .md（UTF-8 + frontmatter）。

    幂等：.md 已存在且非 force 时跳过抽取，直接返回现有 .md 路径。
    返回 .md 路径。
    """
    md_path = pdf_path.with_suffix(".md")
    if md_path.exists() and not force:
        return md_path

    body, pages = _extract_text(pdf_path)
    frontmatter = (
        "---\n"
        f"source_pdf: {pdf_path.name}\n"
        f"converted_at: {dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"pages: {pages}\n"
        f"extractor: PyMuPDF(fitz) plain-text\n"
        "---\n\n"
    )
    md_path.write_text(frontmatter + body, encoding="utf-8")
    return md_path


def convert_research_pdfs(folder: Path, *, force: bool = False) -> list[Path]:
    """扫 folder 下所有 *.pdf，逐个转 .md。返回生成的 .md 路径列表（含已存在的）。"""
    if not folder.exists():
        return []
    md_paths: list[Path] = []
    for pdf in sorted(folder.glob("*.pdf")):
        md_paths.append(research_pdf_to_md(pdf, force=force))
    return md_paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把研报/纪要 PDF 转成 Markdown（供 /brkd 读取）"
    )
    parser.add_argument("--folder", type=Path, help="直接指定含 PDF 的文件夹")
    parser.add_argument("--ticker", type=str, help="按公司定位 active_vore/业务理解器 子文件夹")
    parser.add_argument("--force", action="store_true", help="强制重新抽取（覆盖已有 .md）")
    args = parser.parse_args()

    if args.folder:
        folder = args.folder
    elif args.ticker:
        from src.company_paths import find_company_dir, brkd_material_dir
        folder = brkd_material_dir(find_company_dir(args.ticker))
    else:
        parser.error("需要 --folder 或 --ticker")

    if not folder.exists():
        print(f"文件夹不存在: {folder}", flush=True)
        return 1

    mds = convert_research_pdfs(folder, force=args.force)
    pdfs = sorted(folder.glob("*.pdf"))
    print(f"PDF: {len(pdfs)}  生成/已有 MD: {len(mds)}  -> {folder}", flush=True)
    for md in mds:
        print(f"  {md.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
