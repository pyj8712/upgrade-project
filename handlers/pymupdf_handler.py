import re
import fitz
from pathlib import Path

SKIP_KEYWORDS = {"합계금액", "현금", "수표", "어음", "외상", "비고", "수정사유", "총합계"}


def get_lines(pdf_path: Path) -> list[str]:
    doc = fitz.open(str(pdf_path))
    lines = [l.strip() for l in doc[0].get_text().splitlines()]
    doc.close()
    return [l for l in lines if l]


def detect_type(lines: list[str]) -> str | None:
    joined = "\n".join(lines)
    if "전자세금계산서" in joined:
        return "세금계산서"
    if "거래명세서" in joined:
        return "거래명세서"
    return None


def sanitize(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()


# ── 세금계산서 ─────────────────────────────────────────────────────────

def _extract_tax_invoice(lines: list[str]) -> tuple:
    date_str = None
    for i, line in enumerate(lines):
        if re.match(r"^\d{4}$", line) and i + 2 < len(lines):
            month = lines[i + 1].zfill(2)
            day = lines[i + 2].zfill(2)
            if re.match(r"^\d{1,2}$", month) and re.match(r"^\d{1,2}$", day):
                date_str = f"{line}{month}{day}"
                break

    matches = re.findall(r"\(법인명\)\s*(.+)", "\n".join(lines))
    recipient = matches[1].strip() if len(matches) >= 2 else (matches[0].strip() if matches else None)

    item = None
    for i, line in enumerate(lines):
        if re.match(r"^\d{2}$", line) and i + 1 < len(lines):
            nxt = lines[i + 1]
            m = re.match(r"^\d{2}\s+(.+)", nxt)
            if m:
                item = m.group(1).strip()
                if i + 2 < len(lines):
                    cont = lines[i + 2]
                    if not re.match(r"^[\d,]+$", cont) and cont not in SKIP_KEYWORDS:
                        item += " " + cont
                break
            if re.match(r"^\d{2}$", nxt) and i + 2 < len(lines):
                candidate = lines[i + 2]
                if not re.match(r"^[\d,]+$", candidate) and candidate not in SKIP_KEYWORDS:
                    item = candidate.strip()
                    if i + 3 < len(lines):
                        cont = lines[i + 3]
                        if not re.match(r"^[\d,]+$", cont) and cont not in SKIP_KEYWORDS:
                            item += " " + cont
                    break

    return date_str, recipient, item


# ── 거래명세서 ─────────────────────────────────────────────────────────

def _extract_delivery_note(lines: list[str]) -> tuple:
    date_str = None
    for i, line in enumerate(lines):
        if line == "거래일자" and i + 1 < len(lines):
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", lines[i + 1])
            if m:
                date_str = m.group(1) + m.group(2) + m.group(3)
                break

    recipient = None
    for i, line in enumerate(lines):
        if line == "거래처명" and i + 1 < len(lines):
            recipient = lines[i + 1].strip()
            break

    item_joyo = None
    for i, line in enumerate(lines):
        if re.match(r"^\d{2}/\d{2}\s+.+", line):
            product_text = re.sub(r"^\d{2}/\d{2}\s+", "", line).strip()

            for j in range(i + 1, min(i + 6, len(lines))):
                m = re.match(r"^[\d,]+\s+(.+)", lines[j])
                if m:
                    joyo_raw = m.group(1).strip()
                    if j + 1 < len(lines):
                        cont = lines[j + 1]
                        if (not re.match(r"^[\d,]+$", cont)
                                and cont not in SKIP_KEYWORDS
                                and not re.match(r"^\d{2}/\d{2}", cont)):
                            joyo_raw += cont

                    # 품목명이 "제품명(장소 ...건)" 형식이면 "장소 제품명건" 으로 조합
                    core_m = re.match(r"^(.+?)\((.+?)\s+\S+건\)$", product_text)
                    if core_m:
                        core = core_m.group(1).strip().replace(" ", "")
                        location = core_m.group(2).strip()
                        item_joyo = f"{location} {core}건"
                    else:
                        item_joyo = joyo_raw
                    break
            break

    return date_str, recipient, item_joyo


# ── 공통 처리 ──────────────────────────────────────────────────────────

def process_pdf(pdf_path: Path, doc_type: str, lines: list[str]) -> str:
    if doc_type == "세금계산서":
        date_str, recipient, item = _extract_tax_invoice(lines)
        date_part = date_str or "날짜미상"
        r = sanitize(recipient) if recipient else "거래처미상"
        it = sanitize(item).replace(" ", "") if item else "품목미상"
        return f"{date_part} 세금계산서({r}-{it}).pdf"

    if doc_type == "거래명세서":
        date_str, recipient, joyo = _extract_delivery_note(lines)
        date_part = date_str or "날짜미상"
        r = sanitize(recipient) if recipient else "거래처미상"
        j = sanitize(joyo) if joyo else "적요미상"
        return f"{date_part} 거래명세서({r}-{j}).pdf"

    raise ValueError(f"알 수 없는 문서 유형: {doc_type}")
