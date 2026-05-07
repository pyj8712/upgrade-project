"""
PDF 폴더 실시간 감시 모드

pdf/ 폴더를 감시하다가 파일이 감지되면 자동으로 처리합니다.
  처리 성공 → done/ 폴더로 이동
  처리 실패 → error/ 폴더로 이동
"""

import time
import shutil
import threading
from pathlib import Path
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from orchestrator import _classify, _dest_folder
from handlers.pymupdf_handler import process_pdf
from handlers.local_ocr_handler import process_receipt

BASE_DIR   = Path(__file__).parent
PDF_DIR    = BASE_DIR / "pdf"
ERROR_DIR  = BASE_DIR / "error"

SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"}

_processing: set[Path] = set()
_lock = threading.Lock()


# ── 로그 ──────────────────────────────────────────────────────────────

def _log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    tag = {"INFO": "[ ]", "OK": "[OK]", "ERR": "[!!]", "WAIT": "[..]"}.get(level, "[ ]")
    print(f"{ts} {tag} {msg}", flush=True)


# ── 파일 안정화 대기 ───────────────────────────────────────────────────

def _wait_stable(path: Path, stable_secs: float = 1.0, timeout: int = 30) -> bool:
    """파일 크기가 stable_secs 동안 변하지 않을 때까지 대기 (쓰기 완료 확인)."""
    prev_size = -1
    stable_count = 0
    needed = max(1, int(stable_secs / 0.5))

    for _ in range(timeout * 2):
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False

        if size > 0 and size == prev_size:
            stable_count += 1
            if stable_count >= needed:
                return True
        else:
            stable_count = 0

        prev_size = size
        time.sleep(0.5)

    return False


# ── 파일 처리 ──────────────────────────────────────────────────────────

def _process(file_path: Path):
    try:
        _log(f"감지: {file_path.name}", "WAIT")

        if not _wait_stable(file_path):
            raise RuntimeError("파일 쓰기 대기 시간 초과")

        file_type, lines = _classify(file_path)

        if file_type in ("세금계산서", "거래명세서"):
            new_name = process_pdf(file_path, file_type, lines)
        elif file_type == "영수증":
            new_name = process_receipt(file_path)
        else:
            raise RuntimeError("지원하지 않는 파일 형식")

        dest_dir = _dest_folder(file_type, new_name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / new_name
        if dest.exists():
            stem, ext = Path(new_name).stem, Path(new_name).suffix
            dest = dest_dir / f"{stem}_{int(time.time())}{ext}"

        shutil.move(str(file_path), str(dest))
        _log(f"{file_path.name}  →  {dest}", "OK")

    except Exception as e:
        ERROR_DIR.mkdir(exist_ok=True)
        dest = ERROR_DIR / file_path.name
        try:
            if file_path.exists():
                shutil.move(str(file_path), str(dest))
        except Exception:
            pass
        _log(f"{file_path.name}  처리 실패: {e}", "ERR")

    finally:
        with _lock:
            _processing.discard(file_path)


def _submit(file_path: Path):
    """중복 방지 후 백그라운드 스레드에서 처리."""
    if file_path.suffix.lower() not in SUPPORTED_EXTS:
        return
    with _lock:
        if file_path in _processing:
            return
        _processing.add(file_path)
    threading.Thread(target=_process, args=(file_path,), daemon=True).start()


# ── watchdog 핸들러 ───────────────────────────────────────────────────

class _PDFHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            _submit(Path(event.src_path))

    def on_moved(self, event):
        # 다른 폴더에서 드래그해서 이동할 때
        if not event.is_directory:
            _submit(Path(event.dest_path))


# ── 메인 ──────────────────────────────────────────────────────────────

def run():
    PDF_DIR.mkdir(exist_ok=True)
    ERROR_DIR.mkdir(exist_ok=True)

    # 시작 시 pdf/ 폴더에 이미 있는 파일 처리
    existing = [f for f in PDF_DIR.iterdir()
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS]
    if existing:
        _log(f"기존 파일 {len(existing)}개 처리 시작")
        for f in sorted(existing):
            _submit(f)

    observer = Observer()
    observer.schedule(_PDFHandler(), str(PDF_DIR), recursive=False)
    observer.start()

    _log(f"감시 시작: {PDF_DIR}")
    _log("종료하려면 Ctrl+C 를 누르세요")
    print()

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    observer.stop()
    observer.join()
    _log("감시 종료")


if __name__ == "__main__":
    run()
