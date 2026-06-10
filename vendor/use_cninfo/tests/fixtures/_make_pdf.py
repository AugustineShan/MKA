"""一次性生成 fixture PDF。pytest 不会自动跑;需要重生成时手动运行。"""

from pathlib import Path

import fitz

OUT = Path(__file__).parent / "sample.pdf"


def main() -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Hello cninfo test fixture.")
    page.insert_text((72, 130), "Second line for offset check.")
    page2 = doc.new_page()
    page2.insert_text((72, 100), "Page two content.")
    doc.save(str(OUT))
    doc.close()
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
