import json

import numpy as np
import pytest

from photosift import library, taste


@pytest.fixture(autouse=True)
def _taste_files(tmp_path, monkeypatch):
    """Mô hình gu riêng / mặc định nằm trong tmp_path: test không bao giờ chạm thư mục nhà thật."""
    monkeypatch.setattr(library, "TASTE_FILE", tmp_path / "home" / "taste.npz", raising=False)
    monkeypatch.setattr(library, "TASTE_DEFAULT", tmp_path / "models" / "taste_default.npz", raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "models").mkdir()


def _roll(prefix, n=240, frac=0.2, seed=0, rejects=0):
    """Một đám giả: giữ (1 sao) = các ảnh nét nhất; độ sáng ngẫu nhiên (nhiễu)."""
    rng = np.random.default_rng(seed)
    sharp = rng.uniform(10, 500, n)
    lum = rng.uniform(0.2, 0.8, n)
    thr = np.sort(sharp)[::-1][int(n * frac) - 1]
    rows = []
    for i in range(n):
        keep = sharp[i] >= thr
        rating = 1 if keep else (-1 if i < rejects and not keep else 0)
        rows.append(dict(path=f"{prefix}/{i:04d}.jpg", analyzed=1, taken=1000.0 + i * 2.0, sharp=float(sharp[i]),
                         lum=float(lum[i]), lo=0.01, hi=0.01, nfaces=0, ear_min=-1.0, score=float(sharp[i] / 5),
                         grp=0, best=0, rating=rating))
    return rows


def _three(lib_with):
    rows = _roll("/r1", seed=1, rejects=30) + _roll("/r2", seed=2) + _roll("/r3", seed=3)
    L, ids = lib_with(rows, catalog=[("/r1", 1.0), ("/r2", 2.0), ("/r3", 3.0)])
    return L, ids


def _open(L, ids):
    L.db.x("DELETE FROM cur")
    L.db.many("INSERT INTO cur(id) VALUES(?)", [(i,) for i in ids])


def test_info_basic_without_models(lib_with):
    L, _ = _three(lib_with)
    info = L.taste_info()
    assert info["source"] == "basic"
    assert info["n_rolls"] == 3 and info["n_photos"] == 720
    assert [r["root"] for r in info["rolls"]] == ["/r3", "/r2", "/r1"]
    assert all(r["on"] for r in info["rolls"])
    assert info["agree"] is None and info["learned"] is None and info["stale"] is True
    # có gu mặc định → "default"
    m = taste.fit(np.random.default_rng(0).random((50, len(taste.FEATS)), dtype=np.float32), None,
                  np.r_[np.ones(10), np.zeros(40)], np.ones(50))
    taste.save(library.TASTE_DEFAULT, m, {"rolls": 1})
    assert L.taste_info()["source"] == "default"


def test_learn_then_personal(lib_with):
    L, ids = _three(lib_with)
    info = L.taste_learn()
    assert library.TASTE_FILE.exists()
    assert info["source"] == "personal"
    assert info["agree"] is not None and info["agree"] >= 0.6
    assert info["learned"] and info["stale"] is False
    # đổi số ảnh giữ của một đám → cần học lại
    L.db.x("UPDATE photos SET rating=1 WHERE path='/r2/0000.jpg' AND rating=0")
    L.db.x("UPDATE photos SET rating=1 WHERE path='/r2/0001.jpg' AND rating=0")
    assert L.taste_info()["stale"] is True


def test_rolls_off_excluded(lib_with):
    L, _ = _three(lib_with)
    info = L.taste_rolls_set(["/r1"])
    assert info["n_rolls"] == 2 and info["n_photos"] == 480
    assert {r["root"]: r["on"] for r in info["rolls"]} == {"/r3": True, "/r2": True, "/r1": False}
    assert json.loads(L.db.one("SELECT v FROM meta WHERE k='taste_off'")["v"]) == ["/r1"]
    L.taste_learn()
    assert taste.load(library.TASTE_FILE)[1]["rolls"] == 2


def test_suggest_sets_sugg_and_keeps_stars(lib_with):
    L, ids = _three(lib_with)
    L.taste_learn()
    cur = ids[480:]                                   # mở đám /r3
    _open(L, cur)
    L.db.x("UPDATE photos SET sugg=1")
    before = {r["id"]: r["rating"] for r in L.db.q("SELECT id,rating FROM photos")}
    stars = {i for i in cur if before[i] >= 1}
    res = L.suggest(60)
    assert res["source"] == "personal" and res["n"] == 60 and len(res["ids"]) == 60
    assert stars <= set(res["ids"])
    got = {r["id"]: r for r in L.db.q("SELECT id,rating,sugg FROM photos")}
    assert {i for i in cur if got[i]["sugg"] == 1} == set(res["ids"])
    assert {i: got[i]["rating"] for i in got} == before
    L.settings, L.online = dict(library.DEFAULT_SETTINGS), type("O", (), {"ok": True})()
    assert {p["id"] for p in L.photos() if p["sugg"] == 1} == set(res["ids"])
    assert L.suggest(0).get("error")
    assert L.suggest_clear() == {"ok": True}
    assert not any(got["sugg"] for got in L.db.q("SELECT sugg FROM photos JOIN cur USING(id)"))
    sugg = {p["id"]: p["sugg"] for p in L.photos()}
    assert set(sugg) == set(cur) and not any(sugg.values())


def test_basic_suggest_uses_score(lib_with):
    rows = [dict(path=f"/x/{i}.jpg", analyzed=1, taken=10.0 + 2 * i, sharp=100.0, score=float((i * 7) % 30),
                 grp=0, rating=0) for i in range(30)]
    L, ids = lib_with(rows, catalog=["/x"])
    res = L.suggest(5)
    assert res["source"] == "basic"
    want = sorted(range(30), key=lambda i: -((i * 7) % 30))[:5]
    assert res["ids"] == [ids[i] for i in want]


def test_suggest_rate_marks_rsrc_and_undo(lib_with):
    rows = [dict(path=f"/x/{i}.jpg", analyzed=1, rating=r, sugg=s) for i, (r, s) in
            enumerate([(0, 1), (0, 1), (0, 1), (3, 1), (0, 0)])]
    L, ids = lib_with(rows, catalog=["/x"])
    res = L.suggest_rate()
    assert res["ok"] and res["n"] == 3 and res["batch"]
    st = [(r["rating"], r["rsrc"]) for r in L.db.q("SELECT rating,rsrc FROM photos ORDER BY id")]
    assert st == [(1, 1), (1, 1), (1, 1), (3, 0), (0, 0)]
    assert L.db.one("SELECT COUNT(*) AS n FROM cull_log")["n"] == 0
    L.set_rating([ids[1]], 4)                        # người chấm lại → giữ nguyên khi hoàn tác
    u = L.suggest_rate_undo(None)
    assert u["n"] == 2 and sorted(u["ids"]) == [ids[0], ids[2]]
    st = [(r["rating"], r["rsrc"]) for r in L.db.q("SELECT rating,rsrc FROM photos ORDER BY id")]
    assert st == [(0, 0), (4, 0), (0, 0), (3, 0), (0, 0)]
    assert L.suggest_rate_undo(res["batch"])["n"] == 0


def test_export_has_no_paths(lib_with, tmp_path):
    L, ids = _three(lib_with)
    L.db.x("INSERT INTO cull_log(root,time,ids) VALUES('/r1',0,?)", (json.dumps(["/r1/0000.jpg", "/r1/0001.jpg"]),))
    L.db.x("UPDATE photos SET rsrc=1 WHERE path='/r1/0005.jpg'")
    L.taste_rolls_set(["/r2"])
    out = tmp_path / "out"
    out.mkdir()
    res = L.taste_export(str(out))
    assert res["ok"] and res["rows"] == 480 and res["path"] == str(out / "taste_data.npz")
    with np.load(res["path"], allow_pickle=False) as z:
        for k in z.files:
            assert z[k].dtype.kind != "O"
            if z[k].dtype.kind in "US":
                assert k == "feats" and list(z[k]) == taste.FEATS
        assert z["X"].dtype == np.float32 and z["X"].shape == (480, len(taste.FEATS))
        assert z["C"].dtype == np.float16 and len(z["C"]) == 480 and np.isnan(z["C"]).all()
        assert z["y"].dtype == np.int8 and z["w"].dtype == np.float32 and z["roll"].dtype == np.int32
        assert sorted(set(z["roll"].tolist())) == [0, 1]
        kept = {r["path"] for r in L.db.q("SELECT path FROM photos WHERE rating>=1 AND path NOT LIKE '/r2/%'")}
        assert int(z["y"].sum()) == len(kept)
        w = z["w"]
        assert (w == np.float32(0.5)).sum() == sum(1 for p in ("/r1/0000.jpg", "/r1/0001.jpg")
                                                   if L.db.one("SELECT rating FROM photos WHERE path=?", (p,))["rating"] == -1)
        assert (np.isclose(w, 0.3)).sum() == (1 if L.db.one("SELECT rating FROM photos WHERE path='/r1/0005.jpg'")["rating"] >= 1 else 0)
        assert len(z["grp"]) == 480 and len(z["taken"]) == 480
    assert L.taste_export(str(tmp_path / "missing")).get("error")


def test_learn_with_default_prior(lib_with):
    L, _ = _three(lib_with)
    rows = _roll("/d", seed=9)
    X = taste.features(rows)
    y = np.array([r["rating"] >= 1 for r in rows], np.float32)
    taste.save(library.TASTE_DEFAULT, taste.fit(X, None, y, np.ones(len(y))), {"rolls": 1})
    info = L.taste_learn()
    assert info["source"] == "personal" and info["agree"] >= 0.6
    meta = taste.load(library.TASTE_FILE)[1]
    assert meta["prior"] is True and meta["rolls"] == 3 and meta["agree"] == info["agree"]


def test_reset_drops_personal_and_pauses_auto_learn(lib_with):
    L, _ = _three(lib_with)
    L.taste_rolls_set(["/r1"])
    assert L.taste_learn()["source"] == "personal"
    info = L.taste_reset()
    assert not library.TASTE_FILE.exists()
    assert info["source"] == "basic" and info["paused"] is True
    assert {r["root"]: r["on"] for r in info["rolls"]} == {"/r3": True, "/r2": True, "/r1": False}, "reset không đổi đám bật/tắt"
    L.taste_reset()   # không có file: không lỗi
    # có gu mặc định → về "default"
    m = taste.fit(np.random.default_rng(0).random((50, len(taste.FEATS)), dtype=np.float32), None,
                  np.r_[np.ones(10), np.zeros(40)], np.ones(50))
    taste.save(library.TASTE_DEFAULT, m, {"rolls": 1})
    assert L.taste_info()["source"] == "default"
    # học nền (auto) bị chặn khi đang tạm dừng
    r = L.taste_learn(auto=True)
    assert r["source"] == "default" and r["paused"] is True and not library.TASTE_FILE.exists()
    # bấm Học lại (học thật) → bỏ tạm dừng, có gu riêng
    r = L.taste_learn()
    assert r["source"] == "personal" and r["paused"] is False and library.TASTE_FILE.exists()
    assert L.taste_learn(auto=True)["source"] == "personal"
