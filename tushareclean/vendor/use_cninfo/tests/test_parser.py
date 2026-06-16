"""parser 模块测试 — 用 fixture PDF。"""

from cninfo.parser import parse_pdf_bytes


def test_parse_pdf_bytes_extracts_text(sample_pdf_bytes):
    parsed = parse_pdf_bytes(sample_pdf_bytes)
    assert parsed.total_pages == 2
    assert parsed.extracted_pages == 2
    assert "Hello cninfo test fixture" in parsed.text
    assert "Page two content" in parsed.text
    assert parsed.text_chars > 0
    assert not parsed.is_scanned
