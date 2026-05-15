"""
PDF 텍스트 추출 진단 도구
사용법: python debug_pdf.py <파일경로>
"""

import sys
import fitz
from pathlib import Path


def dump_lines(pdf_path: Path):
    doc = fitz.open(str(pdf_path))
    raw = doc[0].get_text()
    doc.close()

    lines = raw.splitlines()
    print(f"\n=== {pdf_path.name} ===")
    print(f"총 {len(lines)}줄 (빈 줄 포함)\n")
    for i, line in enumerate(lines):
        if line.strip():
            print(f"[{i:3d}] {repr(line)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python debug_pdf.py <파일경로>")
        sys.exit(1)
    dump_lines(Path(sys.argv[1]))
