"""Sửa sau đợt soát cuối nhánh xmp-goc (C1, I1–I4, I6, I7, M1–M3)."""
import inspect
import os
import threading
from xml.dom import minidom

import photosift.xmpsync as xs
from photosift.library import DEFAULT_SETTINGS, Library
from photosift.xmpsync import merge_xmp, read_sidecar, sidecar, write_atomic

TWO_DESC = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            b'<rdf:Description rdf:about="" xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Make="Sony"/>'
            b'<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:CreatorTool="LR"/>'
            b'</rdf:RDF></x:xmpmeta>')
XAP = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       b'<rdf:Description rdf:about="" xmlns:xap="http://ns.adobe.com/xap/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
       b'<dc:title>giu</dc:title></rdf:Description></rdf:RDF></x:xmpmeta>')


def prep(L):
    L.settings = dict(DEFAULT_SETTINGS)
    L.status = {}
    L._xmp_init()
    return L


def ok_xml(b):
    minidom.parseString(b)   # ném lỗi nếu XML hỏng (prefix chưa khai báo…)
    return b


# C1
def test_two_descriptions_valid_xml(tmp_path):
    out = ok_xml(merge_xmp(TWO_DESC, 3, "red"))
    assert b'tiff:Make="Sony"' in out and b"CreatorTool" in out
    (tmp_path / "A.xmp").write_bytes(out)
    assert read_sidecar(str(tmp_path / "A.JPG"))[:2] == (3, "red")


def test_xap_prefix_reused(tmp_path):
    out = ok_xml(merge_xmp(XAP, 4, "blue"))
    assert b'xap:Rating="4"' in out and b'xap:Label="Blue"' in out and b"xmp:Rating" not in out and b"giu" in out
    (tmp_path / "B.xmp").write_bytes(out)
    assert read_sidecar(str(tmp_path / "B.JPG"))[:2] == (4, "blue")
    out2 = ok_xml(merge_xmp(out, 1, ""))
    assert b'xap:Rating="1"' in out2 and b"Label" not in out2


def test_no_namespace_anywhere_valid():
    src = TWO_DESC.replace(b' xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:CreatorTool="LR"', b"")
    ok_xml(merge_xmp(src, 2, "green"))


# M2 / M3
def test_garbage_existing_rebuilt():
    for junk in (b"", b"\x00\x00garbage"):
        out = merge_xmp(junk, 3, "")
        assert b'xmp:Rating="3"' in ok_xml(out)


def test_element_with_space_or_attr():
    src = XAP.replace(b"<dc:title>", b"<xap:Rating >2</xap:Rating><dc:title>")
    out = ok_xml(merge_xmp(src, 5, ""))
    assert out.count(b"Rating") == 2 and b">5</xap:Rating>" in out


# I1
def test_label_cleared_propagates(lib_with, tmp_path):
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 3, ""))
    assert read_sidecar(str(tmp_path / "IMG_0000.JPG"))[1] == ""
    L, ids = lib_with([dict(rating=3, label="red")]); prep(L)
    L._import_xmp(ids)
    assert L.db.one("SELECT label FROM photos")["label"] == ""


# I2
def test_import_does_not_clobber_rating_made_meanwhile(lib_with, tmp_path, monkeypatch):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 3, ""))
    real = xs._read_file

    def slow(p):   # người dùng chấm 5 đúng lúc lượt đọc đang chạy
        data = real(p)
        L.set_rating([ids[0]], 5); L.xmp_flush()
        return data
    monkeypatch.setattr(xs, "_read_file", slow)
    L._import_xmp(ids)
    assert L.db.one("SELECT rating FROM photos")["rating"] == 5


# I3
def test_dirty_survives_restart(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4)                 # chưa kịp ghi thì thoát app
    prep(L)                                   # mở lại: hàng đợi rỗng
    assert L.xmp_requeue() == 1 and L.xmp_flush()["written"] == 1
    assert L.db.one("SELECT xdirty FROM photos")["xdirty"] == 0


def test_quit_paths_flush():
    import photosift.server as srv
    src = inspect.getsource(srv)
    assert src.count("xmp_shutdown(") >= 3          # /api/quit, cài bản cập nhật, tự tắt khi rảnh
    import importlib.util
    mac = open(os.path.join(os.path.dirname(srv.__file__), "..", "mac_main.py"), encoding="utf-8").read()
    assert "xmp_shutdown(" in mac


def test_shutdown_flushes(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 2)
    L.xmp_shutdown(5)
    assert (tmp_path / "IMG_0000.xmp").exists()


# I4
def test_concurrent_flush_no_failures(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0) for _ in range(40)]); prep(L)
    L.set_rating(ids, 3)
    res = []
    th = [threading.Thread(target=lambda: res.append(L.xmp_flush())) for _ in range(3)]
    [t.start() for t in th]; [t.join() for t in th]
    assert sum(r["failed"] for r in res) == 0 and len(list(tmp_path.glob("*.xmp"))) == 40


def test_tmp_name_unique(tmp_path, monkeypatch):
    seen = []
    real = os.replace
    monkeypatch.setattr(xs.os, "replace", lambda a, b: (seen.append(a), real(a, b)))
    write_atomic(str(tmp_path / "C.xmp"), b"1"); write_atomic(str(tmp_path / "C.xmp"), b"2")
    assert len(set(seen)) == 2 and all(s != str(tmp_path / "C.xmp") + ".tmp" for s in seen)


def test_rewrite_all_is_async(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=3), dict(rating=2)]); prep(L)
    assert L.xmp_rewrite_all()["n"] == 2
    assert not list(tmp_path.glob("*.xmp"))       # trả lời ngay, luồng nền ghi
    L.xmp_flush(); assert len(list(tmp_path.glob("*.xmp"))) == 2


# I6
def test_toggle_off_clears_on_catches_up(lib_with, tmp_path, monkeypatch):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L._sfile = tmp_path / "s.json"; L.regroup = lambda: None
    L.set_rating([ids[0]], 3); L.status["xmp_err"] = "x"
    L.set_settings({"xmp_sync": 0})
    assert L.xmp_flush() == dict(written=0, failed=0) and "xmp_err" not in L.status
    L.set_rating([ids[0]], 4)                 # chấm lúc đang tắt
    L.set_settings({"xmp_sync": 1})
    L.xmp_flush()
    assert b'xmp:Rating="4"' in (tmp_path / "IMG_0000.xmp").read_bytes()


# I7
def test_pair_not_reimported_on_same_machine(lib_with, tmp_path):
    L, ids = lib_with([dict(path=str(tmp_path / "A.JPG")), dict(path=str(tmp_path / "A.ARW"))]); prep(L)
    L.set_rating([ids[0]], 2); L.xmp_flush()
    L.set_rating([ids[1]], 5); L.xmp_flush()
    assert L._import_xmp(ids) == 0
    assert [r["rating"] for r in L.db.q("SELECT rating FROM photos ORDER BY id")] == [2, 5]


# M1
def test_sidecar_uses_real_name_from_listing(tmp_path):
    p, ex = sidecar(str(tmp_path / "IMG_9.ARW"), names={"img_9.xmp": "IMG_9.XMP"})
    assert ex and os.path.basename(p) == "IMG_9.XMP"
