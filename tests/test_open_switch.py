"""Mở thư mục 2 khi đang ở thư mục 1: lưới không được hiện ảnh thư mục 1 trong lúc liệt kê thư mục 2
(báo lỗi 1.2.9 trên Mac M1 — NAS liệt kê chậm)."""
import threading
import time

from photosift.library import DEFAULT_SETTINGS
from test_taste_fixes import _scan_lib


def test_switch_folder_hides_old_photos_while_listing(lib_with, tmp_path, monkeypatch):
    L, ids, root, _ = _scan_lib(lib_with, tmp_path, monkeypatch, n=3)
    L.settings = dict(DEFAULT_SETTINGS); L.online = type("O", (), {"ok": True})()
    L._scan(root, True, threading.Event())            # đang mở thư mục 1
    L.db.x("UPDATE photos SET ready=1")
    assert {r["id"] for r in L.photos()} == set(ids)

    gate = threading.Event()

    def slow_list(r, rec):                            # thư mục 2 trên NAS: liệt kê mất vài giây
        gate.wait(5)
        return []
    L._list_files = slow_list
    L._thread = None
    L._cancel = threading.Event()
    L._vcv = threading.Condition(); L._vq, L._vlow = [], []
    L._catalog_seed = lambda: None
    L.open_folder(str(tmp_path / "roll2"))
    time.sleep(0.1)
    assert L.photos() == [], "đang liệt kê thư mục 2 mà vẫn trả ảnh thư mục 1"
    gate.set(); L._thread.join(5)


def test_cancelled_scan_does_not_overwrite_cur(lib_with, tmp_path, monkeypatch):
    """Đổi thư mục lần nữa khi lượt quét cũ vừa liệt kê xong: lượt cũ không được ghi đè danh sách ảnh hiện tại."""
    L, ids, root, _ = _scan_lib(lib_with, tmp_path, monkeypatch, n=3)
    L.db.x("DELETE FROM cur")
    ev = threading.Event(); ev.set()                  # lượt quét đã bị huỷ (người dùng mở thư mục khác)
    L._scan(root, True, ev)
    assert L.db.one("SELECT COUNT(*) n FROM cur")["n"] == 0
