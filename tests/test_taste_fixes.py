"""Sửa sau đợt xem lại toàn nhánh gu chọn ảnh (1–9)."""
import json
import os
import threading
import time

import cv2
import numpy as np
import pytest

from photosift import library, scene, taste


@pytest.fixture(autouse=True)
def _taste_files(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "TASTE_FILE", tmp_path / "home" / "taste.npz", raising=False)
    monkeypatch.setattr(library, "TASTE_DEFAULT", tmp_path / "models" / "taste_default.npz", raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "models").mkdir()


def _roll(prefix, n=240, frac=0.2, seed=0):
    rng = np.random.default_rng(seed)
    sharp = rng.uniform(10, 500, n)
    thr = np.sort(sharp)[::-1][int(n * frac) - 1]
    return [dict(path=f"{prefix}/{i:04d}.jpg", analyzed=1, taken=1000.0 + i * 2.0, sharp=float(sharp[i]),
                 lum=float(rng.uniform(0.2, 0.8)), lo=0.01, hi=0.01, nfaces=0, ear_min=-1.0, score=float(sharp[i] / 5),
                 grp=0, best=0, rating=1 if sharp[i] >= thr else 0) for i in range(n)]


def _three(lib_with):
    rows = _roll("/r1", seed=1) + _roll("/r2", seed=2) + _roll("/r3", seed=3)
    return lib_with(rows, catalog=[("/r1", 1.0), ("/r2", 2.0), ("/r3", 3.0)])


# ---------------------------------------------------------------- 1. danh sách đám nhanh, theo dir
def _big_lib(tmp_path, n_rolls=240, per=834, n_roots=240):
    from photosift.db import DB
    from photosift.library import Library
    db = DB(tmp_path / "big.db")
    rows = []
    for k in range(n_rolls):
        for i in range(per):
            p = f"/lib/roll{k:03d}/cam{i % 4}/{i:05d}.jpg"
            rows.append((p, os.path.dirname(p), 1, 1 if i % 10 == 0 else 0))
    db.many("INSERT INTO photos(path,dir,analyzed,rating) VALUES(?,?,?,?)", rows)
    db.many("INSERT INTO catalog(root,opened) VALUES(?,?)",
            [(f"/lib/roll{k:03d}", float(k)) for k in range(n_roots)] + [("/lib", -1.0)])
    L = Library.__new__(Library)
    L.db = db
    return L


def test_finished_rolls_fast_large_library(tmp_path):
    L = _big_lib(tmp_path)
    assert L.db.one("SELECT COUNT(*) n FROM photos")["n"] == 200_160
    t0 = time.perf_counter()
    got = L._finished_rolls()
    dt = time.perf_counter() - t0
    assert len(got) == 240 and got[0]["root"] == "/lib/roll239"
    assert all(g["n"] == 834 and g["kept"] == 84 for g in got)
    assert dt < 0.5, f"_finished_rolls mất {dt:.2f}s"
    t0 = time.perf_counter()
    L._finished_rolls()
    assert time.perf_counter() - t0 < 0.05, "lần gọi lại (không đổi gì) phải dùng kết quả đã tính"
    t0 = time.perf_counter()
    rows = L._roll_rows("/lib/roll007")
    assert len(rows) == 834 and time.perf_counter() - t0 < 0.5


def test_finished_rolls_cache_tracks_changes(lib_with):
    rows = [dict(path=f"/a/{i}.jpg", analyzed=1, rating=1 if i < 5 else 0) for i in range(200)]
    rows += [dict(path=f"/a/b/{i}.jpg", analyzed=1, rating=1 if i < 10 else 0) for i in range(210)]
    L, ids = lib_with(rows, catalog=[("/a/", 1.0)])   # gốc có dấu / cuối vẫn khớp
    got = L._finished_rolls()
    assert [(g["root"], g["n"], g["kept"]) for g in got] == [("/a/", 410, 15)]
    L.db.x("UPDATE photos SET rating=0 WHERE id=?", (ids[0],))           # đổi sao
    assert L._finished_rolls()[0]["kept"] == 14
    L.db.x("INSERT INTO catalog(root,opened) VALUES('/a/b',2.0)")          # thêm đám con
    got = L._finished_rolls()
    assert [(g["root"], g["n"], g["kept"]) for g in got] == [("/a/b", 210, 10)]   # /a còn 200 ảnh, 4 sao < 3%
    L.db.x("UPDATE photos SET analyzed=0 WHERE id=?", (ids[300],))         # ảnh bị đọc lại
    assert L._finished_rolls()[0]["n"] == 209
    L.db.x("DELETE FROM catalog WHERE root='/a/b'")
    L.db.x("INSERT INTO catalog(root,opened) VALUES('/q',2.0)")            # cùng số dòng catalog
    assert [g["root"] for g in L._finished_rolls()] == ["/a/"]
    assert [r["path"] for r in L._roll_rows("/a/")][:1] == ["/a/0.jpg"]
    assert len(L._roll_rows("/a/")) == 409   # /a/b đã gỡ: ảnh của nó lại thuộc /a/


# ---------------------------------------------------------------- 2. CLIP sau khi xong, không tính hai lần
def _scan_lib(lib_with, tmp_path, monkeypatch, n=3, rating=0):
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir(exist_ok=True)
    monkeypatch.setattr(library, "THUMBS", thumbs)
    root = tmp_path / "roll"
    root.mkdir(exist_ok=True)
    rows = [dict(path=str(root / f"{i}.ARW"), analyzed=1, mtime=1.0, size=10, rating=rating) for i in range(n)]
    L, ids = lib_with(rows)
    for i in ids:
        (thumbs / f"{i}.jpg").write_bytes(b"x")
    calls = []
    L._list_files = lambda r, rec: [(row["path"], 1.0, 10) for row in rows]
    L.status = dict(state="scanning", total=0, done=0, thumbs=0, quick=0, errors=0, root=str(root), message="", timing={})
    L._slock = threading.Lock()
    for name in ("cluster", "regroup", "_smile_backfill", "_focus_backfill", "_scene_backfill", "trim_cache", "view_all"):
        setattr(L, name, (lambda nm: lambda *a, **k: calls.append((nm, L.status["state"])))(name))
    L._catalog_update = lambda r: calls.append(("_catalog_update", L.status["state"]))
    L._clip_backfill = lambda cancel: calls.append(("_clip_backfill", L.status["state"], L.status["message"]))
    return L, ids, str(root), calls


def test_scan_done_before_clip_stage(lib_with, tmp_path, monkeypatch):
    L, ids, root, calls = _scan_lib(lib_with, tmp_path, monkeypatch)
    L._scan(root, True, threading.Event())
    names = [c[0] for c in calls]
    assert names.index("_clip_backfill") > names.index("view_all") > names.index("_catalog_update")
    clip = calls[names.index("_clip_backfill")]
    assert clip[1] == "done" and clip[2] == "Hoàn tất", "trạng thái Hoàn tất phải có trước khâu CLIP"
    assert L.status["state"] == "done" and L.status["message"] == "Hoàn tất"


def test_scan_cancelled_skips_clip(lib_with, tmp_path, monkeypatch):
    L, ids, root, calls = _scan_lib(lib_with, tmp_path, monkeypatch)
    ev = threading.Event()
    ev.set()
    L._scan(root, True, ev)
    assert "_clip_backfill" not in [c[0] for c in calls]


def _clip_stubs(monkeypatch, vec):
    monkeypatch.setattr(scene, "available", lambda: True)
    monkeypatch.setattr(scene, "embed", lambda bgr: vec)
    monkeypatch.setattr(scene, "MODEL_ID", "m1")


def test_clip_backfill_quiet_and_cancellable(lib_with, tmp_path, monkeypatch):
    prev = tmp_path / "prev"
    prev.mkdir()
    monkeypatch.setattr(library, "PREVIEWS", prev)
    L, ids = lib_with([dict(path=f"/r/{i}.jpg", analyzed=1) for i in range(3)])
    for i in ids:
        cv2.imwrite(str(prev / f"{i}.jpg"), np.full((16, 16, 3), 90, np.uint8))
    vec = np.ones(512, np.float32) / np.sqrt(512)
    _clip_stubs(monkeypatch, vec)
    L.status = dict(state="done", message="Hoàn tất")
    ev = threading.Event()
    ev.set()
    L._clip_backfill(ev)   # đã mở thư mục khác: không tính gì
    assert L.db.one("SELECT COUNT(*) n FROM photos WHERE clip IS NOT NULL")["n"] == 0
    L._clip_backfill(threading.Event())
    assert L.db.one("SELECT COUNT(*) n FROM photos WHERE clip IS NOT NULL")["n"] == 3
    assert L.status == dict(state="done", message="Hoàn tất"), "khâu nền không ghi đè Hoàn tất"


def test_classify_full_returns_vector(monkeypatch):
    v = np.array([0, 1, 0, 0], np.float32)
    monkeypatch.setattr(scene, "_get", lambda: dict(
        ok=True, emb=np.eye(3, 4, dtype=np.float32), cat_idx={"decor": [0], "detail": [1], "object": [2]}, scale=100.0))
    monkeypatch.setattr(scene, "embed", lambda bgr: v)
    lbl, conf, vec = scene.classify_full(np.zeros((4, 4, 3), np.uint8))
    assert lbl == "detail" and conf > 0.9 and vec is v
    assert scene.classify(np.zeros((4, 4, 3), np.uint8))[0] == "detail"
    monkeypatch.setattr(scene, "embed", lambda bgr: None)
    assert scene.classify_full(np.zeros((4, 4, 3), np.uint8)) is None


def test_analyze_image_returns_clip_for_no_face(monkeypatch):
    from photosift.analyzer import Analyzer
    A = Analyzer.__new__(Analyzer)
    A._det = lambda w, h: type("D", (), {"detect": lambda self, img: (None, None)})()
    v = np.arange(512, dtype=np.float32)
    v /= np.linalg.norm(v)
    monkeypatch.setattr(scene, "classify_full", lambda img: ("decor", 0.8, v))
    monkeypatch.setattr(scene, "MODEL_ID", "m1")
    r = A.analyze_image(np.full((64, 64, 3), 100, np.uint8), 64, 64)
    assert r["scene"] == "decor" and r["nfaces"] == 0
    assert r["clipv"] == "m1" and np.allclose(np.frombuffer(r["clip"], np.float16), v, atol=1e-3)


def test_analyze_cached_stores_clip_and_backfill_skips(lib_with, tmp_path, monkeypatch):
    prev, faces = tmp_path / "prev", tmp_path / "faces"
    prev.mkdir()
    faces.mkdir()
    monkeypatch.setattr(library, "PREVIEWS", prev)
    monkeypatch.setattr(library, "FACES", faces)
    L, ids = lib_with([dict(path="/r/0.jpg", w=16, h=16), dict(path="/r/1.jpg", w=16, h=16)])
    vec = np.ones(512, np.float32) / np.sqrt(512)
    blob = vec.astype(np.float16).tobytes()
    base = dict(sharp=1.0, fsharp=0.0, lum=0.5, lo=0.0, hi=0.0, dhash="0", nfaces=0, ear_min=-1.0, faces=[],
                smile=-1.0, focus_x=0.5, focus_y=0.5, focus_c=0.1, scene="decor", scene_c=0.9)
    outs = {ids[0]: dict(base, clip=blob, clipv="m1"), ids[1]: dict(base, clip=None, clipv=None)}
    cur = []
    L.an = type("A", (), {"has_smile": False, "analyze_image": lambda self, img, w, h: outs[cur[-1]]})()
    img = np.full((16, 16, 3), 90, np.uint8)
    for i in ids:
        cur.append(i)
        L._analyze_cached(i, img)
        cv2.imwrite(str(prev / f"{i}.jpg"), img)
    got = {r["id"]: (r["clip"], r["clipv"]) for r in L.db.q("SELECT id,clip,clipv FROM photos")}
    assert got[ids[0]] == (blob, "m1") and got[ids[1]] == (None, None)
    seen = []
    _clip_stubs(monkeypatch, vec)
    monkeypatch.setattr(scene, "embed", lambda bgr: seen.append(1) or vec)
    L.status = dict(state="done", message="Hoàn tất")
    L._clip_backfill(threading.Event())
    assert len(seen) == 1, "ảnh đã có vector từ lúc phân tích không tính lại"


# ---------------------------------------------------------------- 3. độ trùng khớp không tính sao từ đề xuất
def test_agree_counts_only_hand_picked(lib_with, monkeypatch):
    L, ids = _three(lib_with)
    seen = []
    real = taste.agreement
    monkeypatch.setattr(taste, "agreement", lambda m, X, C, y, rows: seen.append(np.asarray(y).copy()) or real(m, X, C, y, rows))
    kept3 = [r["id"] for r in L.db.q("SELECT id FROM photos WHERE path LIKE '/r3/%' AND rating>=1 ORDER BY id")]
    assert len(kept3) == 48
    L.db.many("UPDATE photos SET rsrc=1 WHERE id=?", [(i,) for i in kept3[:20]])   # 28/48 tự chọn
    info = L.taste_learn()
    assert info["agree"] is not None
    assert int(seen[-1].sum()) == 28, "N = số ảnh người dùng tự chấm (rsrc=0)"
    L.db.many("UPDATE photos SET rsrc=1 WHERE id=?", [(i,) for i in kept3[:25]])   # 23/48 < 50%
    assert L.taste_learn()["agree"] is None
    L.db.x("UPDATE photos SET rsrc=0 WHERE path LIKE '/r3/%'")
    L.db.many("UPDATE photos SET rating=0 WHERE id=?", [(i,) for i in kept3[19:]])  # còn 19 tấm < 20
    assert L.taste_learn()["agree"] is None
    meta = taste.load(library.TASTE_FILE)[1]
    assert meta["agree"] is None


def test_drop_weight_lower_when_roll_mostly_suggested(lib_with):
    rows = _roll("/s", n=240, seed=5)
    rows[0]["rating"] = rows[1]["rating"] = -1
    rows[0]["path"], rows[1]["path"] = "/s/x0.jpg", "/s/x1.jpg"
    L, ids = lib_with(rows, catalog=["/s"])
    L.db.x("INSERT INTO cull_log(root,time,ids) VALUES('/s',0,?)", ('["/s/x0.jpg"]',))
    kept = [r["id"] for r in L.db.q("SELECT id FROM photos WHERE rating>=1 ORDER BY id")]
    L.db.many("UPDATE photos SET rsrc=1 WHERE id=?", [(i,) for i in kept[:len(kept) // 2]])   # đúng 50%: chưa giảm
    rr, X, y, w = L._taste_roll("/s")
    zero = [wi for r, wi in zip(rr, w) if r["rating"] == 0]
    assert np.allclose(zero, 1.0)
    L.db.many("UPDATE photos SET rsrc=1 WHERE id=?", [(i,) for i in kept[:len(kept) // 2 + 1]])  # > 50%
    rr, X, y, w = L._taste_roll("/s")
    by = {r["path"]: (r["rating"], r["rsrc"], float(wi)) for r, wi in zip(rr, w)}
    assert all(np.isclose(v[2], 0.3) for v in by.values() if v[0] == 0), "ảnh 0 sao (chưa xem) giảm còn 0.3"
    assert np.isclose(by["/s/x0.jpg"][2], 0.5) and np.isclose(by["/s/x1.jpg"][2], 1.0), "✕ giữ nguyên"
    assert all(np.isclose(v[2], 0.3) for v in by.values() if v[0] >= 1 and v[1] == 1)
    assert all(np.isclose(v[2], 1.0) for v in by.values() if v[0] >= 1 and v[1] == 0)


# ---------------------------------------------------------------- 4. đọc .xmp một lần cho thư mục cũ
def _join_xmp(L):
    t = getattr(L, "_xmp_thread", None)
    if t is not None:
        t.join(5)
    else:
        time.sleep(0.5)


def test_scan_imports_xmp_once_for_existing_root(lib_with, tmp_path, monkeypatch):
    L, ids, root, calls = _scan_lib(lib_with, tmp_path, monkeypatch, n=3)
    L.db.x("UPDATE photos SET rating=4 WHERE id=?", (ids[2],))
    for i in range(3):
        (tmp_path / "roll" / f"{i}.xmp").write_text(f'<x:xmpmeta><rdf:Description xmp:Rating="{i + 2}"/></x:xmpmeta>')
    L._scan(root, True, threading.Event())
    _join_xmp(L)
    got = [r["rating"] for r in L.db.q("SELECT rating FROM photos ORDER BY id")]
    assert got == [2, 3, 4], "ảnh cũ 0 sao nhận sao .xmp; ảnh đã chấm giữ nguyên"
    assert L.db.one("SELECT v FROM meta WHERE k=?", ("xmp_done:" + root,))
    L.db.x("UPDATE photos SET rating=0")
    L._scan(root, True, threading.Event())
    _join_xmp(L)
    assert [r["rating"] for r in L.db.q("SELECT rating FROM photos ORDER BY id")] == [0, 0, 0], "chỉ một lần mỗi thư mục"


def test_scan_after_xmp_done_reads_fresh_only(lib_with, tmp_path, monkeypatch):
    L, ids, root, calls = _scan_lib(lib_with, tmp_path, monkeypatch, n=3)
    L.db.x("INSERT INTO meta(k,v) VALUES(?,'1')", ("xmp_done:" + root,))
    for i in range(3):
        (tmp_path / "roll" / f"{i}.xmp").write_text('<x:xmpmeta><rdf:Description xmp:Rating="3"/></x:xmpmeta>')
    paths = [r["path"] for r in L.db.q("SELECT path FROM photos ORDER BY id")]
    L._list_files = lambda r, rec: [(p, 2.0 if k == 1 else 1.0, 10) for k, p in enumerate(paths)]   # ảnh 1 đổi
    L._prepare_one = lambda pid, path: None
    L._analyze_cached = lambda pid, img=None: True
    L._scan(root, True, threading.Event())
    _join_xmp(L)
    # .xmp đi kèm mới (chưa từng đọc) → nhập cho mọi ảnh, kể cả sau lượt đầu (kết quả lọc từ máy khác)
    assert [r["rating"] for r in L.db.q("SELECT rating FROM photos ORDER BY id")] == [3, 3, 3]
    # quét lại khi .xmp không đổi: không ghi đè sao vừa chấm trong app
    L.db.x("UPDATE photos SET rating=5")
    L._scan(root, True, threading.Event())
    _join_xmp(L)
    assert [r["rating"] for r in L.db.q("SELECT rating FROM photos ORDER BY id")] == [5, 5, 5]


# ---------------------------------------------------------------- 5. ghi chú khi chưa phân tích xong
def test_suggest_note_when_not_fully_analyzed(lib_with):
    rows = [dict(path=f"/x/{i}.jpg", analyzed=1 if i < 10 else 0, taken=10.0 + 2 * i, score=float(i), rating=0)
            for i in range(30)]
    L, ids = lib_with(rows, catalog=["/x"])
    res = L.suggest(20)
    assert res["n"] == 10
    assert res["note"] == "Mới phân tích xong 10/30 ảnh — đợi phân tích xong rồi đề xuất lại"
    L.db.x("UPDATE photos SET analyzed=1")
    res = L.suggest(40)
    assert res["note"].startswith("chỉ tìm được")


# ---------------------------------------------------------------- 7. không có CLIP → không mượn bản đầy đủ của gu mặc định
def test_personal_model_without_clip_has_no_full(lib_with):
    L, _ = _three(lib_with)
    rng = np.random.default_rng(0)
    X = rng.random((60, len(taste.FEATS)), dtype=np.float32)
    C = rng.standard_normal((60, 512)).astype(np.float32)
    y = np.r_[np.ones(15), np.zeros(45)]
    d = taste.fit(X, C, y, np.ones(60))
    assert d["full"] is not None
    taste.save(library.TASTE_DEFAULT, d, {"rolls": 1})
    L.taste_learn()
    model, meta = taste.load(library.TASTE_FILE)
    assert model["full"] is None and meta["prior"] is True


# ---------------------------------------------------------------- 8. Học lại khi bỏ tick mọi đám
def test_learn_with_all_rolls_off_resets(lib_with):
    L, _ = _three(lib_with)
    assert L.taste_learn()["source"] == "personal"
    L.taste_reset()
    L.taste_rolls_set(["/r1", "/r2", "/r3"])
    L.taste_learn()   # đang tạm dừng: học thật bỏ tạm dừng dù không có đám nào
    assert not library.TASTE_FILE.exists()
    taste.save(library.TASTE_FILE, taste.fit(np.zeros((4, len(taste.FEATS)), np.float32), None,
                                             np.r_[1, 0, 1, 0], np.ones(4)), {"rolls": 3})
    info = L.taste_learn()
    assert not library.TASTE_FILE.exists(), "gu riêng học từ đám đã bỏ tick phải bị xoá"
    assert "error" not in info and info["source"] == "basic" and info["paused"] is False
    assert info["note"] == "Chưa có đám nào được chọn — đang dùng gu mặc định"
    auto = L.taste_learn(auto=True)   # học nền không xoá gì, không báo
    assert "note" not in auto


# ---------------------------------------------------------------- 9. ✕ của Tự động lọc ở thư mục cha
def test_in_cull_log_any_root(lib_with):
    rows = [dict(path=f"/r/sub/{i}.jpg", analyzed=1, rating=-1) for i in range(3)]
    L, ids = lib_with(rows, catalog=["/r", "/r/sub"])
    L.db.x("INSERT INTO cull_log(root,time,ids) VALUES('/r',0,?)", (json.dumps(["/r/sub/1.jpg"]),))
    L.db.x("INSERT INTO cull_log(root,time,ids) VALUES('/other',0,?)", (json.dumps(["/r/sub/2.jpg"]),))
    out = L._roll_rows("/r/sub")
    assert [r["in_cull_log"] for r in out] == [False, True, True]
    assert [L._taste_label(r)[1] for r in out] == [1.0, 0.5, 0.5]
