"""Kiểm tra kết nối mạng (chạy nền). Chỉ dùng để mở khoá các công cụ lọc nhắm mắt / tối / sáng.

Cách kiểm tra: thử mở kết nối TCP tới vài máy chủ công cộng (không gửi dữ liệu gì).
Biến môi trường PHOTOSIFT_ONLINE=1/0 ép trạng thái (dùng để kiểm thử).
"""
from __future__ import annotations
import os
import socket
import threading
import time

PROBES = [("1.1.1.1", 443), ("8.8.8.8", 443), ("www.microsoft.com", 443)]
INTERVAL = 15.0


def _probe() -> bool:
    for host, port in PROBES:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            continue
    return False


class Online:
    def __init__(self):
        self._on = False
        self._checked = 0.0
        self._lock = threading.Lock()
        self._force = os.environ.get("PHOTOSIFT_ONLINE")
        self._thr = None

    def start(self):
        if self._force is not None:
            self._on = self._force == "1"
            return
        self._on = _probe()
        self._checked = time.time()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def _loop(self):
        while True:
            time.sleep(INTERVAL)
            v = _probe()
            with self._lock:
                self._on = v
                self._checked = time.time()

    def recheck(self) -> bool:
        """Kiểm tra ngay (nút «Kiểm tra lại»)."""
        if self._force is not None:
            return self._on
        v = _probe()
        with self._lock:
            self._on = v
            self._checked = time.time()
        return v

    @property
    def ok(self) -> bool:
        return self._on
