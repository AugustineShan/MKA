"""PDF 解析 — PyMuPDF 提取全文。

> docs/gotchas.md #8: 部分 PDF 是扫描件,PyMuPDF 提不到字。返回 extracted_pages=0 时,
> 用户可决定是否走 OCR(本 skill 不内置)。
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass
class ParsedPdf:
    text: str
    total_pages: int
    extracted_pages: int

    @property
    def text_chars(self) -> int:
        return len(self.text)

    @property
    def is_scanned(self) -> bool:
        return self.total_pages > 0 and self.extracted_pages == 0


def parse_pdf_bytes(data: bytes) -> ParsedPdf:
    """从 PDF 二进制提取全文。"""
    doc = fitz.open(stream=data, filetype="pdf")
    parts: list[str] = []
    extracted = 0
    try:
        for page in doc:
            t = page.get_text()
            if t.strip():
                extracted += 1
            parts.append(t)
        return ParsedPdf(
            text="\n\n".join(parts),
            total_pages=len(doc),
            extracted_pages=extracted,
        )
    finally:
        doc.close()


def parse_pdf_file(path: str) -> ParsedPdf:
    """从磁盘 PDF 文件提取全文。"""
    with open(path, "rb") as f:
        return parse_pdf_bytes(f.read())
