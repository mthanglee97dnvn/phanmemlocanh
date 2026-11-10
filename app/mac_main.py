#!/usr/bin/env python3
"""MThanglee Cull&Collage cho macOS: điểm khởi động của file .app.

Mặc định là app độc lập: cửa sổ riêng (WebKit có sẵn của macOS qua pywebview), có biểu tượng trên Dock,
đóng cửa sổ hoặc ⌘Q là thoát hẳn — không cần trình duyệt.
Dự phòng (thiếu pywebview, hoặc đặt PHOTOSIFT_BROWSER=1): mở bằng Chrome / Edge / trình duyệt mặc định như trước.
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
if getattr(sys, "frozen", False) and "--selftest" not in sys.argv and "--no-browser" not in sys.argv:
    try:   # app không có cửa sổ dòng lệnh: ghi nhật ký ra file để chẩn đoán khi cần
        _log = Path(os.environ.get("PHOTOSIFT_HOME", Path.home() / ".photosift"))
        _log.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(_log / "mac.log", "w", encoding="utf-8", buffering=1)
    except OSError:
        pass
os.environ.setdefault("PHOTOSIFT_APPDIR", str(BASE))   # model + version.json nằm trong gói .app
HOME = Path(os.environ.get("PHOTOSIFT_HOME", Path.home() / ".photosift"))

BROWSERS = ("Google Chrome", "Microsoft Edge", "Brave Browser", "CocCoc", "Cốc Cốc", "Chromium", "Vivaldi", "Opera")


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
        for m in ("rawpy", "pillow_heif", "webview"):
            try:
                __import__(m)
                print(m, "ok")
            except Exception as e:  # noqa: BLE001
                print(m, "KHONG CO", e)
        return
    headless = "--no-browser" in sys.argv
    if not headless and os.environ.get("PHOTOSIFT_BROWSER") != "1":
        try:
            import webview  # noqa: F401
        except Exception as e:  # noqa: BLE001
            print("pywebview không dùng được, mở bằng trình duyệt:", e, file=sys.stderr)
        else:
            native()
            return
    os.environ.setdefault("PHOTOSIFT_AUTOEXIT", "1")   # chế độ trình duyệt: đóng cửa sổ ~4 phút thì máy chủ tự tắt
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


def native():
    """Cửa sổ app riêng: máy chủ chạy trong cùng tiến trình, đóng cửa sổ là thoát."""
    import webview
    url, pid = running_url()
    if not url:   # chưa có phiên nào (mở app lần đầu): bật máy chủ trong tiến trình này
        def run_server():
            from photosift.server import serve
            serve(open_browser=False)
        threading.Thread(target=run_server, daemon=True).start()
        for _ in range(240):
            time.sleep(0.25)
            url, pid = running_url(1.0)
            if url and pid == os.getpid():
                break
        else:
            url = None
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    except Exception:  # noqa: BLE001  bản pywebview cũ không có settings
        pass
    title = "MThanglee Cull&Collage"
    if url:
        webview.create_window(title, url, width=1440, height=900, min_size=(1000, 640),
                              background_color="#16181D", text_select=True)
    else:
        webview.create_window(title, html="<body style='background:#16181D;color:#eee;font:15px -apple-system;padding:40px'>"
                              "<h2>Không khởi động được MThanglee Cull&amp;Collage</h2>"
                              "<p>Hãy thoát app (⌘Q) rồi mở lại. Nếu vẫn lỗi, gửi file ~/.photosift/mac.log cho nhà phát triển.</p></body>",
                              width=720, height=360)
    store = HOME / "webview"
    store.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(private_mode=False, storage_path=str(store))
    except TypeError:   # bản pywebview cũ
        webview.start()
    if running_url(0.5)[1] == os.getpid():   # chỉ dọn phiên do chính app này mở
        try:
            (HOME / "running.json").unlink()
        except OSError:
            pass
    os._exit(0)   # đóng cửa sổ = thoát hẳn (dừng cả máy chủ và các việc nền)


if __name__ == "__main__":
    main()
