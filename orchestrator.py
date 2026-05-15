"""
오케스트라 패턴 파일명 자동 변환 도구

파일 유형 판별 후 처리기 배분:
  텍스트 PDF (세금계산서/거래명세서) → PyMuPDF 처리기
  이미지 PDF / 이미지 파일 (영수증)  → 로컬 OCR 처리기 (EasyOCR)
"""

import os
import sys
import shutil
from pathlib import Path

import fitz

from handlers.pymupdf_handler import detect_type, process_pdf
from handlers.local_ocr_handler import process_receipt

PDF_DIR = Path(r"C:\Users\yujin\OneDrive\Desktop\before")

DEST_SALES    = Path(r"C:\Users\yujin\OneDrive\Desktop\박유진\1. 매출서류")
DEST_PURCHASE = Path(r"C:\Users\yujin\OneDrive\Desktop\박유진\2. 매입서류")
DEST_FINANCE  = Path(r"C:\Users\yujin\OneDrive\Desktop\박유진\0-1. 재무관리")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MIN_TEXT_CHARS = 50


def _dest_folder(file_type: str, new_name: str) -> Path:
    """파일 유형에 따라 목적 폴더를 반환 (월별 하위폴더 없음)."""
    if file_type == "매입세금계산서":
        return DEST_PURCHASE
    return DEST_SALES if file_type in ("세금계산서", "거래명세서") else DEST_FINANCE


# ── 파일 분류 ──────────────────────────────────────────────────────────

def _classify(file_path: Path) -> tuple[str, list | None]:
    ext = file_path.suffix.lower()

    if ext in IMAGE_EXTS:
        return "영수증", None

    if ext == ".pdf":
        doc = fitz.open(str(file_path))
        text = doc[0].get_text()
        doc.close()

        if len(text.strip()) >= MIN_TEXT_CHARS:
            lines = [l.replace('\xa0', ' ').strip() for l in text.splitlines()]
            lines = [l for l in lines if l]
            doc_type = detect_type(lines)
            if doc_type:
                return doc_type, lines

        return "영수증", None

    return "미지원", None


# ── 메인 ──────────────────────────────────────────────────────────────

def run():
    if not PDF_DIR.exists():
        print(f"오류: '{PDF_DIR}' 폴더가 없습니다.")
        sys.exit(1)

    files: list[Path] = []
    for pattern in ["*.[Pp][Dd][Ff]", "*.jpg", "*.jpeg", "*.png",
                    "*.JPG", "*.JPEG", "*.PNG", "*.gif", "*.webp"]:
        files.extend(PDF_DIR.glob(pattern))
    files = sorted(set(files))

    if not files:
        print(f"처리할 파일이 없습니다. '{PDF_DIR}' 폴더를 확인해주세요.")
        return

    print(f"\n{len(files)}개 파일 분석 중...")

    results = []
    for file_path in files:
        try:
            file_type, lines = _classify(file_path)

            if file_type in ("세금계산서", "거래명세서"):
                new_name, effective_type = process_pdf(file_path, file_type, lines)
                results.append((file_path, effective_type, new_name, None))

            elif file_type == "영수증":
                new_name = process_receipt(file_path)
                results.append((file_path, "영수증(로컬OCR)", new_name, None))

            else:
                results.append((file_path, "미지원", None, None))

        except Exception as e:
            results.append((file_path, "오류", None, str(e)))

    print("\n[ 변환 미리보기 ]")
    print("-" * 90)
    for file_path, file_type, new_name, error in results:
        if error:
            print(f"[오류]   {file_path.name}")
            print(f"         {error}")
        elif new_name is None:
            print(f"[{file_type}] {file_path.name}: 처리 불가")
        else:
            dest = _dest_folder(file_type, new_name) / new_name
            print(f"[{file_type}] {file_path.name}")
            print(f"  → {dest}")
    print("-" * 90)

    answer = input("\n위 경로로 이동할까요? (y/n): ").strip().lower()
    if answer != "y":
        print("취소했습니다.")
        return

    opened_folders: set[Path] = set()
    for file_path, file_type, new_name, error in results:
        if error or new_name is None:
            print(f"건너뜀: {file_path.name}")
            continue
        dest_dir = _dest_folder(file_type, new_name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / new_name
        if dest.exists():
            print(f"이미 존재하여 건너뜀: {new_name}")
            continue
        shutil.move(str(file_path), str(dest))
        print(f"완료: {file_path.name} → {dest}")
        opened_folders.add(dest_dir)

    print("\n모든 작업이 완료되었습니다.")

    for folder in opened_folders:
        os.startfile(str(folder))


if __name__ == "__main__":
    run()
