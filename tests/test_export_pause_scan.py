"""Xuất ảnh từ NAS chậm (411 ảnh ARW / 17,7 GB mất 17 phút ≈ 17 MB/s, trong khi thư mục trước xuất ≥ 84 MB/s):
lúc xuất, app vẫn đang đọc ảnh xem trước của thư mục vừa mở từ cùng NAS → ổ NAS phải nhảy đầu đọc giữa hai việc.
Trong lúc xuất, khâu đọc ảnh từ ổ gốc phải tạm dừng, xuất xong chạy tiếp."""
import shutil
import threading
import time

from photosift import library


def test_export_sets_and_clears_busy_flag(lib_with, tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    rows = []
    for i in range(3):
        p = src / f"A{i}.ARW"
        p.write_bytes(b"raw")
        rows.append(dict(path=str(p), rating=5, mtime=1.0, size=3))
    L, ids = lib_with(rows)
    seen = []
    real = shutil.copy2
    monkeypatch.setattr(library.shutil, "copy2", lambda a, b: (seen.append(library._EXPORTING.is_set()), real(a, b)))
    L.export(ids, str(tmp_path / "out"), progress={})
    assert seen == [True, True, True], "đang chép mà khâu đọc ảnh không được báo tạm dừng"
    assert not library._EXPORTING.is_set(), "xuất xong phải cho khâu đọc ảnh chạy lại"


def test_export_clears_flag_on_error(lib_with, tmp_path, monkeypatch):
    L, ids = lib_with([dict(path=str(tmp_path / "x.ARW"), rating=5, mtime=1.0, size=3)])
    monkeypatch.setattr(L, "_names", lambda: (_ for _ in ()).throw(RuntimeError("hỏng")))
    try:
        L.export(ids, str(tmp_path / "out"), progress={})
    except RuntimeError:
        pass
    assert not library._EXPORTING.is_set()


def test_io_yield_waits_while_exporting():
    library._EXPORTING.set()
    try:
        cancel = threading.Event()
        t = threading.Thread(target=library.io_yield, args=(cancel,))
        t.start()
        time.sleep(0.4)
        assert t.is_alive(), "đang xuất mà khâu đọc ảnh không chờ"
    finally:
        library._EXPORTING.clear()
    t.join(2)
    assert not t.is_alive()


def test_io_yield_stops_waiting_on_cancel():
    library._EXPORTING.set()
    try:
        cancel = threading.Event()
        t = threading.Thread(target=library.io_yield, args=(cancel,))
        t.start()
        cancel.set()
        t.join(2)
        assert not t.is_alive(), "mở thư mục khác (huỷ quét) phải thoát ngay dù đang xuất"
    finally:
        library._EXPORTING.clear()
