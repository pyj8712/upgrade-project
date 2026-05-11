import re
import asyncio
from itertools import combinations
from pathlib import Path

import fitz

_TOTAL_KEYWORDS = [
    "승인금액", "합계금액", "청구금액", "결제금액",
    "수납요금", "총요금", "합계", "총액", "청구액",
]
_SUPPLY_KEYWORDS = ["공급가액", "공급금액", "판매금액"]
_VAT_KEYWORDS = ["부가세", "세액", "부가가치세"]


async def _windows_ocr(img_bytes: bytes) -> str:
    from winsdk.windows.media.ocr import OcrEngine
    from winsdk.windows.globalization import Language
    from winsdk.windows.graphics.imaging import BitmapDecoder
    from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(img_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_language(Language("ko"))
    if engine is None:
        raise RuntimeError("Windows 한국어 OCR 언어 팩이 설치되어 있지 않습니다.")

    result = await engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)


def _load_image_bytes(file_path: Path) -> bytes:
    if file_path.suffix.lower() == ".pdf":
        doc = fitz.open(str(file_path))
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
        doc.close()
        return pix.tobytes("jpeg")
    with open(file_path, "rb") as f:
        return f.read()


def _normalize_ko(s: str) -> str:
    """한글 글자 사이 공백 제거 ('합 계 금 액' → '합계금액')."""
    prev = ""
    while prev != s:
        prev = s
        s = re.sub(r"([가-힣]) ([가-힣])", r"\1\2", s)
    return s


def _normalize_num(s: str) -> str:
    """숫자 콤마 뒤 공백 제거 ('40, 000' → '40,000')."""
    return re.sub(r"(\d),\s+(\d)", r"\1,\2", s)


def _extract_date(text: str) -> str:
    # 20XX / 19XX 연도만 허용 — 영수증 번호(20260507-01-0003) 오인 방지
    pattern = r"((?:20|19)\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})"
    for m in re.finditer(pattern, text):
        year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}{month:02d}{day:02d}"
    return "날짜미상"


def _is_valid_amount(val: str) -> bool:
    if not val or not (3 <= len(val) <= 7):  # 최대 7자리 — 8자리 날짜코드 제외
        return False
    n = int(val)
    if n < 100:
        return False
    if 1900 <= n <= 2099:  # 4자리 연도 제외
        return False
    if len(val) >= 4 and len(set(val)) == 1:  # 1111, 111111 등 바코드 반복 숫자 제외
        return False
    return True


def _kw_match(keyword: str, line: str) -> bool:
    """키워드 앞에 한글이 붙어 있으면 스킵 — '세액합계'에서 '합계' 오매칭 방지."""
    idx = line.find(keyword)
    if idx == -1:
        return False
    if idx > 0 and "가" <= line[idx - 1] <= "힣":
        return False
    return True


def _nums_from(line: str) -> list:
    return re.findall(r"[\d,]+", _normalize_num(line))


def _first_amount(lines: list, norm_lines: list, keywords: list) -> int | None:
    for keyword in keywords:
        for i, norm in enumerate(norm_lines):
            if _kw_match(keyword, norm):
                for check in lines[i: i + 3]:
                    for num in reversed(_nums_from(check)):
                        val = re.sub(r"[^0-9]", "", num)
                        if _is_valid_amount(val):
                            return int(val)
    return None


def _all_amounts(lines: list, norm_lines: list, keywords: list) -> list:
    results = []
    for keyword in keywords:
        for i, norm in enumerate(norm_lines):
            if _kw_match(keyword, norm):
                for check in lines[i: i + 3]:
                    for num in _nums_from(check):
                        val = re.sub(r"[^0-9]", "", num)
                        if _is_valid_amount(val):
                            results.append(int(val))
    return results


def _extract_amount(text: str) -> str:
    norm_text = _normalize_num(text)

    # 1단계: 전체 문서에서 supply × 1.1 ≈ total 쌍 탐색
    # - 수신전화번호·사업자번호 등 잡숫자가 섞여도 올바른 쌍이 있으면 우선 선택
    all_amts = set()
    for num in re.findall(r"[\d,]+", norm_text):
        val = re.sub(r"[^0-9]", "", num)
        if _is_valid_amount(val):
            all_amts.add(int(val))

    # a × 1.1 ≈ b 이면서 부가세(b-a)도 문서에 실제로 존재해야 유효
    vat_totals = [
        b for a, b in combinations(sorted(all_amts), 2)
        if abs(a * 1.1 - b) <= 10 and (b - a) in all_amts
    ]
    if vat_totals:
        return f"{max(vat_totals):,}"

    # 2단계: 키워드 기반 (VAT 구조 없는 영수증)
    lines = text.splitlines()
    norm_lines = [_normalize_ko(line) for line in lines]

    supply = _first_amount(lines, norm_lines, _SUPPLY_KEYWORDS)
    vat    = _first_amount(lines, norm_lines, _VAT_KEYWORDS)
    totals = _all_amounts(lines, norm_lines, _TOTAL_KEYWORDS)

    if supply and vat:
        expected = supply + vat
        matches = [t for t in totals if abs(t - expected) <= 100]
        if matches:
            return f"{min(matches, key=lambda x: abs(x - expected)):,}"

    total = _first_amount(lines, norm_lines, _TOTAL_KEYWORDS)
    if total:
        return f"{total:,}"

    if supply and vat:
        return f"{supply + vat:,}"

    # 3단계: 최종 fallback
    return f"{max(all_amts):,}" if all_amts else "금액미상"


def sanitize(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()


def process_receipt(file_path: Path) -> str:
    try:
        img_bytes = _load_image_bytes(file_path)
        text = asyncio.run(_windows_ocr(img_bytes))

        date_str = _extract_date(text)
        amount_str = sanitize(_extract_amount(text))

        ext = file_path.suffix.lower()
        return f"{date_str} {amount_str} 원{ext}"
    except Exception as e:
        raise RuntimeError(f"Windows OCR 처리 실패: {str(e)[:120]}")
