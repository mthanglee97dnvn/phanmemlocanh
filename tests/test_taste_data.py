import os

import pytest

from photosift.library import read_xmp_rating


def _xmp_attr(n):
    return f'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description xmp:Rating="{n}"/></rdf:RDF></x:xmpmeta>'


def test_xmp_variants(tmp_path):
    (tmp_path / "IMG.ARW").write_bytes(b"x")
    (tmp_path / "IMG.xmp").write_text(_xmp_attr(3))
    assert read_xmp_rating(str(tmp_path / "IMG.ARW")) == 3
    (tmp_path / "B.ARW").write_bytes(b"x")
    (tmp_path / "B.ARW.xmp").write_text("<xmp:Rating>-1</xmp:Rating>")
    assert read_xmp_rating(str(tmp_path / "B.ARW")) == -1
    (tmp_path / "C.ARW").write_bytes(b"x")
    (tmp_path / "C.XMP").write_text(_xmp_attr(9))
    assert read_xmp_rating(str(tmp_path / "C.ARW")) == 5
    (tmp_path / "D.ARW").write_bytes(b"x")
    (tmp_path / "D.xmp").write_text("<<garbled \x00 not xml")
    assert read_xmp_rating(str(tmp_path / "D.ARW")) is None
    assert read_xmp_rating(str(tmp_path / "none.ARW")) is None
    (tmp_path / "E.jpg").write_bytes(b"\xff\xd8\xff\xe1" + b"junk" * 50 + _xmp_attr(2).encode() + b"\xff\xd9")
    assert read_xmp_rating(str(tmp_path / "E.jpg")) == 2
    (tmp_path / "F.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    assert read_xmp_rating(str(tmp_path / "F.jpg")) is None


def test_scan_applies_xmp_only_unrated(lib_with, tmp_path):
    L, ids = lib_with([dict(path=str(tmp_path / "a.ARW"), rating=4), dict(path=str(tmp_path / "b.ARW"), rating=0),
                       dict(path=str(tmp_path / "c.ARW"), rating=0)])
    for n in "abc":
        (tmp_path / f"{n}.ARW").write_bytes(b"x")
        if n != "c":
            (tmp_path / f"{n}.xmp").write_text(_xmp_attr(2))
    L._import_xmp_ratings(ids)
    got = {r["id"]: (r["rating"], r["rsrc"]) for r in L.db.q("SELECT id,rating,rsrc FROM photos")}
    assert got == {ids[0]: (4, 0), ids[1]: (2, 0), ids[2]: (0, 0)}


def test_rerate_resets_rsrc(lib_with):
    L, ids = lib_with([dict(rating=2, rsrc=1), dict(rating=2, rsrc=1)])
    L.set_rating([ids[0]], 5)
    L.set_ratings([(ids[1], 3)])
    assert [(r["rating"], r["rsrc"]) for r in L.db.q("SELECT rating,rsrc FROM photos ORDER BY id")] == [(5, 0), (3, 0)]


def test_roll_longest_root(lib_with):
    L, _ = lib_with([], catalog=["/a", "/a/b"])
    got = L._roll_of(["/a/x.jpg", "/a/b/y.jpg", "/a/bc/z.jpg", "/a/b/c/w.jpg", "/q/r.jpg"])
    assert got == {"/a/x.jpg": "/a", "/a/b/y.jpg": "/a/b", "/a/bc/z.jpg": "/a", "/a/b/c/w.jpg": "/a/b"}


def _roll(prefix, n, kept):
    return [dict(path=f"{prefix}/{i}.jpg", analyzed=1, rating=1 if i < kept else 0) for i in range(n)]


def test_finished_rolls_threshold(lib_with):
    rows = (_roll("/r1", 200, 6) + _roll("/r2", 199, 50) + _roll("/r3", 300, 6) + _roll("/r4", 300, 9))
    L, _ = lib_with(rows, catalog=[("/r1", 1.0), ("/r2", 2.0), ("/r3", 3.0), ("/r4", 4.0)])
    got = L._finished_rolls()
    assert [g["root"] for g in got] == ["/r4", "/r1"]
    assert got[1] == dict(root="/r1", n=200, kept=6, opened=1.0)


def test_roll_rows(lib_with):
    rows = [dict(path=f"/r/{i}.jpg", analyzed=1, taken=100.0 + i, toff=2.0, sharp=5.0, nfaces=1, grp=0) for i in range(3)]
    rows.append(dict(path="/r/sub/x.jpg", analyzed=1, taken=1.0))
    L, ids = lib_with(rows, catalog=["/r", "/r/sub"])
    for i in ids[:3]:
        L.db.x("INSERT INTO faces(photo_id,px,person_id) VALUES(?,100,7)", (i,))
    L.db.x("INSERT INTO faces(photo_id,px,person_id) VALUES(?,100,8)", (ids[0],))
    L.db.x("INSERT INTO cull_log(root,time,ids) VALUES('/r',0,?)", ('["/r/1.jpg"]',))
    out = L._roll_rows("/r")
    assert [r["id"] for r in out] == ids[:3]
    assert out[0]["taken"] == 102.0 and all(r["couple"] for r in out)
    assert [r["in_cull_log"] for r in out] == [False, True, False]
    assert {"clip", "clipv", "rsrc", "rating", "ear_min", "scene"} <= set(out[0])


def test_xmp_import_only_given_ids(lib_with, monkeypatch, tmp_path):
    import photosift.library as lib
    L, ids = lib_with([dict(path=str(tmp_path / f"{i}.ARW"), rating=0) for i in range(4)])
    seen = []
    monkeypatch.setattr(lib, "read_xmp_rating", lambda p: seen.append(os.path.basename(p)) or 3)
    L._import_xmp_ratings(ids[:2])   # chỉ 2 ảnh mới/đổi
    assert sorted(seen) == ["0.ARW", "1.ARW"]
    assert [r["rating"] for r in L.db.q("SELECT rating FROM photos ORDER BY id")] == [3, 3, 0, 0]


def test_scan_imports_xmp_for_fresh_only():
    import inspect
    from photosift.library import Library
    src = inspect.getsource(Library._scan)
    assert src.count("fresh.append") == 2 and "_import_xmp_ratings, args=(fresh,)" in src
