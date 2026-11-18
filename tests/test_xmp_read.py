import os

from photosift.library import DEFAULT_SETTINGS
from photosift.xmpsync import merge_xmp


def prep(L):
    L.settings = dict(DEFAULT_SETTINGS)
    L.status = {}
    L._xmp_init()
    return L


def row(L, i):
    return L.db.one("SELECT rating,label,xmt,rsrc FROM photos WHERE id=?", (i,))


def test_newer_sidecar_overrides(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=3, label="")]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 5, "yellow"))
    assert L._import_xmp(ids) == 1
    r = row(L, ids[0]); assert (r["rating"], r["label"]) == (5, "yellow") and r["xmt"] and r["rsrc"] == 0
    assert L.status["xver"] == 1


def test_reject_from_other_machine(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=2)]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, -1, ""))
    L._import_xmp(ids); assert row(L, ids[0])["rating"] == -1


def test_own_write_not_reimported(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4); L.xmp_flush()
    L.db.x("UPDATE photos SET rating=2 WHERE id=?", (ids[0],))
    assert L._import_xmp(ids) == 0 and row(L, ids[0])["rating"] == 2


def test_mtime_jitter_tolerated(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4); L.xmp_flush()
    x = tmp_path / "IMG_0000.xmp"; st = x.stat(); os.utime(x, (st.st_atime, st.st_mtime + 1.0))
    assert L._import_xmp(ids) == 0


def test_later_edit_is_picked_up(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4); L.xmp_flush()
    x = tmp_path / "IMG_0000.xmp"; x.write_bytes(merge_xmp(x.read_bytes(), 1, "")); st = x.stat()
    os.utime(x, (st.st_atime, st.st_mtime + 30))
    assert L._import_xmp(ids) == 1 and row(L, ids[0])["rating"] == 1


def test_unknown_label_keeps_app_label(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0, label="blue")]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 2, "").replace(b"xmp:Rating", b'xmp:Label="Winner" xmp:Rating', 1))
    L._import_xmp(ids); r = row(L, ids[0]); assert (r["rating"], r["label"]) == (2, "blue")


def test_import_does_not_queue_writes(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 5, "")); L._import_xmp(ids)
    assert L.xmp_flush() == dict(written=0, failed=0)


def test_no_sidecar_untouched(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=3)]); prep(L)
    assert L._import_xmp(ids) == 0 and row(L, ids[0])["rating"] == 3 and "xver" not in L.status
