#!/usr/bin/env python3
"""MThanglee Cull&Collage — lọc ảnh tự động + nhận diện khuôn mặt (kiểu Photo Mechanic)."""
import argparse
import sys

for _s in (sys.stdout, sys.stderr):   # in chữ có dấu không được làm dừng máy chủ, kể cả khi Windows dùng bảng mã cũ
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

if "--selftest" in sys.argv:   # kiểm tra nhanh gói đóng sẵn có đủ thư viện (dùng khi build)
    import cv2, numpy, PIL
    import photosift.server  # noqa: F401
    print("opencv", cv2.__version__, "| numpy", numpy.__version__, "| pillow", PIL.__version__)
    print("cv2.face:", hasattr(cv2, "face"))
    for m in ("rawpy", "pillow_heif"):
        try:
            __import__(m); print(m, "ok")
        except Exception as e:  # noqa: BLE001
            print(m, "KHONG CO", e)
    sys.exit(0)
from photosift.server import serve

ap = argparse.ArgumentParser(description="MThanglee Cull&Collage")
ap.add_argument("folder", nargs="?", help="thư mục ảnh mở sẵn (tuỳ chọn)")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
a = ap.parse_args()
serve(port=a.port, open_browser=not a.no_browser, folder=a.folder)
