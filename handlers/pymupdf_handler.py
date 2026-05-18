import re
import fitz
from pathlib import Path

SKIP_KEYWORDS = {"합계금액", "현금", "수표", "어음", "외상", "비고", "수정사유", "총합계"}


def get_lines(pdf_path: Path) -> list[str]:
    doc = fitz.open(str(pdf_path))
    lines = [l.replace('\xa0', ' ').strip() for l in doc[0].get_text().splitlines()]
    doc.close()
    return [l for l in lines if l]


def detect_type(lines: list[str]) -> str | None:
    joined = "\n".join(lines)
    # 거래명세서/표를 먼저 확인 (문서 하단에 '전자세금계산서' 언급 포함될 수 있음)
    if "거래명세" in joined or "거 래 명 세" in joined:
        return "거래명세서"
    if "전자세금계산서" in joined:
        return "세금계산서"
    return None


def sanitize(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()


# ── 세금계산서 ─────────────────────────────────────────────────────────

def _parse_date(s: str) -> str | None:
    """'YYYY/MM/DD', 'YYYY. MM. DD' 등 단일 문자열에서 날짜 추출."""
    m = re.match(r"(\d{4})[/.\s-]+(\d{1,2})[/.\s-]+(\d{1,2})$", s.strip())
    if m:
        return f"{m.group(1)}{m.group(2).zfill(2)}{m.group(3).zfill(2)}"
    return None


def _extract_tax_invoice(lines: list[str]) -> tuple:
    date_str = None

    # 방법 1: '작성일자' 레이블 주변에서 날짜 탐색
    for i, line in enumerate(lines):
        if "작성일자" in line:
            for j in range(i, min(i + 5, len(lines))):
                d = _parse_date(lines[j])
                if d:
                    date_str = d
                    break
            if date_str:
                break

    # 방법 2: 한 줄에 'YYYY/MM/DD' 형식으로 존재
    if not date_str:
        for line in lines:
            d = _parse_date(line)
            if d and d[:4] in ("2024", "2025", "2026", "2027"):
                date_str = d
                break

    # 방법 3: 연도·월·일이 연속된 별도 줄 (기존 방식)
    if not date_str:
        for i, line in enumerate(lines):
            if re.match(r"^\d{4}$", line) and i + 2 < len(lines):
                month = lines[i + 1].zfill(2)
                day = lines[i + 2].zfill(2)
                if re.match(r"^\d{1,2}$", month) and re.match(r"^\d{1,2}$", day):
                    date_str = f"{line}{month}{day}"
                    break

    matches = re.findall(r"\(법인명\)\s*(.+)", "\n".join(lines))
    supplier  = matches[0].strip() if len(matches) >= 1 else None
    recipient = matches[1].strip() if len(matches) >= 2 else None

    item = None

    # 방법 A: 'MM DD 품목명 ...' 이 한 줄에 존재
    for line in lines:
        m = re.match(r"^\d{2}\s+\d{2}\s+(.+)", line)
        if m:
            raw = m.group(1).strip()
            # 뒤에 붙은 숫자(수량·단가·금액) 제거
            raw = re.sub(r"(\s+[\d,]+){2,}$", "", raw).strip()
            if raw and raw not in SKIP_KEYWORDS and not re.match(r"^[\d,]+$", raw):
                item = raw
                break

    # 방법 B: 'MM DD'가 한 줄(\xa0 정규화 후), 다음 줄이 품목명
    if not item:
        for i, line in enumerate(lines):
            if re.match(r"^\d{2}\s+\d{2}$", line) and i + 1 < len(lines):
                candidate = lines[i + 1].strip()
                if candidate and not re.match(r"^[\d,]+$", candidate) and candidate not in SKIP_KEYWORDS:
                    item = candidate
                    break

    # 방법 C: 월이 단독 줄, 다음 줄에 '일 품목명' 또는 일이 단독 줄
    if not item:
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

    return date_str, supplier, recipient, item


# ── 거래명세서 ─────────────────────────────────────────────────────────

def _extract_delivery_note(lines: list[str]) -> tuple:
    # 날짜: 'YYYY/MM/DD' (거래일자 레이블) 또는 'YYYY년 MM월 DD일' (자유 형식)
    date_str = None
    for i, line in enumerate(lines):
        if line == "거래일자" and i + 1 < len(lines):
            m = re.match(r"(\d{4})/(\d{2})/(\d{2})", lines[i + 1])
            if m:
                date_str = m.group(1) + m.group(2) + m.group(3)
                break
    if not date_str:
        for line in lines:
            m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", line)
            if m:
                date_str = f"{m.group(1)}{m.group(2).zfill(2)}{m.group(3).zfill(2)}"
                break

    # 공급자: '상호' 레이블 기준으로 탐색, 귀중(수신자) 줄은 제외
    supplier = None
    for i, line in enumerate(lines):
        if re.match(r"^상호", line):
            # 같은 줄에 회사명: '상호(법인명) 주식회사 산소프트' 또는 '상호 (주)카이저랩'
            m = re.match(r"^상호[^\s]*\s+(.+)", line)
            if m:
                raw = re.sub(r"(성명|대표자?|사업장).*$", "", m.group(1)).strip()
                if len(raw) > 2:
                    supplier = raw
                    break
            # 다음 줄 이후에서 회사명 탐색 (합쳐진 텍스트, 괄호 잘림 등 대응)
            for j in range(i + 1, min(i + 25, len(lines))):
                raw = re.sub(r"(성명|대표자?|사업장주소).*$", "", lines[j]).strip()
                if len(raw) <= 2 or re.match(r"^[\d\-\(\)\s,\.]+$", raw):
                    continue
                # 귀중(수신자) 줄이면 건너뜀
                is_recipient = ("귀중" in raw or
                                (j + 1 < len(lines) and "귀중" in lines[j + 1]))
                if not is_recipient and re.match(r"^(주식회사|㈜|\(주\))", raw):
                    supplier = raw
                    break
            if supplier:
                break

    # 거래처 (buyer): '거래처명' 레이블로 탐색
    recipient = None
    for i, line in enumerate(lines):
        if line == "거래처명" and i + 1 < len(lines):
            recipient = lines[i + 1].strip()
            break

    # 품목: Format 2 (MM/DD 접두사) → Format 1 폴백 (한글 포함 실질 품목명)
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

                    core_m = re.match(r"^(.+?)\((.+?)\s+\S+건\)$", product_text)
                    if core_m:
                        core = core_m.group(1).strip().replace(" ", "")
                        location = core_m.group(2).strip()
                        item_joyo = f"{location} {core}건"
                    else:
                        item_joyo = joyo_raw
                    break
            break

    # Format 1 폴백: MM/DD 패턴 없을 때 한글 포함 품목명 직접 탐색
    _ADMIN = re.compile(
        r"^(상호|등록번호|사업장|업태|종목|대표|전화|주소|귀중|원정|계좌번호|"
        r"발행|메일|담당|이\s*하\s*여\s*백|거\s*래\s*명\s*세|공|급|자|아래와|"
        r"주식회사|㈜|\(주\))"
    )
    if not item_joyo:
        for line in lines:
            if (len(line) > 5
                    and re.search(r"[가-힣]{2,}", line)
                    and not re.match(r"^[\d,\.\s￦]+$", line)
                    and not _ADMIN.match(line)
                    and not re.match(r"^\d{4}년", line)
                    and line not in SKIP_KEYWORDS):
                item_joyo = line.strip()
                break

    return date_str, supplier, recipient, item_joyo


# ── 공통 처리 ──────────────────────────────────────────────────────────

KAIZER_LAB = "카이저랩"


def process_pdf(pdf_path: Path, doc_type: str, lines: list[str]) -> tuple[str, str]:
    if doc_type == "세금계산서":
        date_str, supplier, recipient, item = _extract_tax_invoice(lines)
        date_part = date_str or "날짜미상"
        it = sanitize(item).replace(" ", "") if item else "품목미상"

        if recipient and KAIZER_LAB in recipient:
            s = sanitize(supplier) if supplier else "공급자미상"
            return f"{date_part} 세금계산서({s}-{it}).pdf", "매입세금계산서"
        else:
            r = sanitize(recipient) if recipient else "거래처미상"
            return f"{date_part} 세금계산서({r}-{it}).pdf", "세금계산서"

    if doc_type == "거래명세서":
        date_str, supplier, recipient, joyo = _extract_delivery_note(lines)
        date_part = date_str or "날짜미상"
        j = sanitize(joyo) if joyo else "적요미상"

        if supplier and KAIZER_LAB in supplier:
            # 카이저랩이 공급자 → 매출
            r = sanitize(recipient) if recipient else "거래처미상"
            return f"{date_part} 거래명세서({r}-{j}).pdf", "거래명세서"
        else:
            # 다른 회사가 공급자 → 매입
            s = sanitize(supplier) if supplier else "공급자미상"
            return f"{date_part} 거래명세서({s}-{j}).pdf", "매입거래명세서"

    raise ValueError(f"알 수 없는 문서 유형: {doc_type}")
