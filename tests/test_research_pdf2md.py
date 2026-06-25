from pathlib import Path
import fitz
from src.research_pdf2md import research_pdf_to_md, convert_research_pdfs


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12, fontname="china-s")
    doc.save(path)
    doc.close()


def test_research_pdf_to_md_creates_md(tmp_path: Path):
    pdf = tmp_path / "研报.pdf"
    _make_pdf(pdf, "hello research 研报")

    md = research_pdf_to_md(pdf)

    assert md is not None
    assert md.exists()
    assert md.suffix == ".md"
    assert md.name == "研报.md"
    content = md.read_text(encoding="utf-8")
    assert "hello research 研报" in content
    # frontmatter 标清来源
    assert "source_pdf" in content
    assert "研报.pdf" in content


def test_research_pdf_to_md_idempotent(tmp_path: Path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, "content v1")

    research_pdf_to_md(pdf)
    md_path = pdf.with_suffix(".md")
    first = md_path.read_text(encoding="utf-8")

    # 第二次不 force → 跳过，md 内容不变
    research_pdf_to_md(pdf)
    second = md_path.read_text(encoding="utf-8")
    assert first == second


def test_research_pdf_to_md_force_overwrites(tmp_path: Path):
    pdf = tmp_path / "r.pdf"
    _make_pdf(pdf, "v1")
    research_pdf_to_md(pdf)
    md_path = pdf.with_suffix(".md")
    assert "v1" in md_path.read_text(encoding="utf-8")

    # 重做 PDF 内容，force=True → 重新抽取
    pdf.unlink()
    _make_pdf(pdf, "v2")
    research_pdf_to_md(pdf, force=True)
    assert "v2" in md_path.read_text(encoding="utf-8")


def test_convert_research_pdfs_walks_folder(tmp_path: Path):
    sub = tmp_path / "BRKD业务理解器（研报和纪要放在这里）"
    sub.mkdir()
    _make_pdf(sub / "a.pdf", "report A")
    _make_pdf(sub / "b.pdf", "report B")
    (sub / "note.md").write_text("已有md", encoding="utf-8")  # 非 pdf，不动

    mds = convert_research_pdfs(sub)

    assert len(mds) == 2
    assert all(p.suffix == ".md" for p in mds)
    assert (sub / "a.md").exists()
    assert (sub / "b.md").exists()
    assert "report A" in (sub / "a.md").read_text(encoding="utf-8")
