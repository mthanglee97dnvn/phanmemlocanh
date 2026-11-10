#!/usr/bin/env python3
"""MThanglee Cull&Collage cho macOS: điểm khởi động của file .app.

- Đang chạy sẵn: chỉ mở lại cửa sổ app.
- Chưa chạy: bật máy chủ cục bộ (ẩn, không có biểu tượng Dock) rồi mở cửa sổ app.
  Cửa sổ app là Chrome / Edge / Brave ở chế độ ứng dụng (không thanh địa chỉ); không có thì mở bằng trình duyệt mặc định.
- Đóng cửa sổ khoảng 4 phút thì máy chủ tự tắt (PHOTOSIFT_AUTOEXIT).
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
os.environ.setdefault("PHOTOSIFT_APPDIR", str(BASE))   # model + version.json nằm trong gói .app
os.environ.setdefault("PHOTOSIFT_AUTOEXIT", "1")
HOME = Path(os.environ.get("PHOTOSIFT_HOME", Path.home() / ".photosift"))

BROWSERS = ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi", "Opera")


def _app_browser():
    for base in ("/Applications", str(Path.home() / "Applications")):
        for n in BROWSERS:
            exe = Path(base) / f"{n}.app" / "Contents" / "MacOS" / n
            if exe.exists():
                return str(exe)
    return None


def open_window(url: str):
    exe = _app_browser()
    if exe:
        prof = HOME / "appwin"
        prof.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={prof}", "--no-first-run",
                          "--no-default-browser-check", "--window-size=1440,900"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        subprocess.Popen(["/usr/bin/open", url])


def running_url(timeout=2.0):
    try:
        r = json.loads((HOME / "running.json").read_text(encoding="utf-8"))
        url = f"http://127.0.0.1:{int(r['port'])}/?t={r['token']}"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status == 200:
                return url, int(r.get("pid") or 0)
    except Exception:  # noqa: BLE001
        pass
    return None, 0


def main():
    if "--selftest" in sys.argv:
        import cv2, numpy, PIL  # noqa: E401
        import photosift.server  # noqa: F401
        print("opencv", cv2.__version__, "| numpy", numpy.__version__, "| pillow", PIL.__version__)
        print("cv2.face:", hasattr(cv2, "face"))
        for m in ("rawpy", "pillow_heif"):
            try:
                __import__(m)
                print(m, "ok")
            except Exception as e:  # noqa: BLE001
                print(m, "KHONG CO", e)
        return
    headless = "--no-browser" in sys.argv
    url, _ = running_url()
    if url:
        if not headless:
            open_window(url)
        return

    def wait_and_open():
        for _ in range(120):
            time.sleep(0.5)
            u, pid = running_url(1.0)
            if u and pid == os.getpid():
                open_window(u)
                return
    if not headless:
        threading.Thread(target=wait_and_open, daemon=True).start()
    from photosift.server import serve
    serve(open_browser=False)


if __name__ == "__main__":
    main()
