import time

import numpy as np
import pytest

from photosift import taste


def _rows(n, seed, t0=0.0, step=5.0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        out.append(dict(
            id=i + 1, sharp=float(rng.uniform(10, 500)), fsharp=None, nfaces=int(rng.integers(0, 4)),
            lum=float(rng.uniform(60, 200)), lo=float(rng.uniform(0, 0.1)), hi=float(rng.uniform(0, 0.1)),
            ear_min=float(rng.uniform(0.1, 0.4)) if rng.random() < 0.7 else -1.0,
            smile=float(rng.uniform(0, 1)) if rng.random() < 0.8 else None,
            away=0, focus_c=float(rng.uniform(0, 1)), scene=[None, "decor", "detail", "object"][i % 4],
            grp=0, best=0, taken=t0 + i * step, couple=bool(rng.random() < 0.3), rating=0))
    return out


def _label(rows, frac=0.2):
    sm = np.array([r["smile"] if r["smile"] is not None else 0.5 for r in rows])
    sh = np.array([r["sharp"] for r in rows])
    z = np.argsort(np.argsort(sh)) / len(rows) + np.argsort(np.argsort(sm)) / len(rows)
    y = np.zeros(len(rows), np.float32)
    y[np.argsort(-z, kind="stable")[: int(len(rows) * frac)]] = 1
    return y


def test_fit_learns_signal():
    ra, rb = _rows(2000, 1), _rows(2000, 2)
    ya, yb = _label(ra), _label(rb)
    Xa, Xb = taste.features(ra), taste.features(rb)
    assert Xa.dtype == np.float32 and Xa.shape == (2000, len(taste.FEATS))
    assert np.isfinite(Xa).all() and Xa.min() >= 0 and Xa.max() <= 1
    m = taste.fit(Xa, None, ya, np.ones(2000, np.float32))
    assert m["full"] is None and m["n"] == 2000
    assert taste.agreement(m, Xb, None, yb, rb) >= 0.8
    rnd = {"base": {"w": np.zeros(len(taste.FEATS), np.float32), "b": 0.0}, "full": None, "n": 0}
    # điểm bằng nhau → chọn theo thứ tự, không theo gu: ≈ tỉ lệ giữ
    assert taste.agreement(rnd, Xb, None, yb, rb) < 0.4


def test_prior_pulls_small_data():
    rows = _rows(30, 3)
    X = taste.features(rows)
    y = 1 - _label(rows, 0.3)  # ngược tiên nghiệm
    pw = np.zeros(len(taste.FEATS), np.float32)
    pw[taste.FEATS.index("sharp")] = 4.0
    pw[taste.FEATS.index("smile")] = 4.0
    prior = {"base": {"w": pw, "b": -2.0}, "full": None, "n": 1000}
    w = np.ones(30, np.float32)
    weak = taste.fit(X, None, y, w, prior=prior, lam=0.01)
    strong = taste.fit(X, None, y, w, prior=prior, lam=100.0)
    d_weak = np.linalg.norm(np.asarray(weak["base"]["w"]) - pw)
    d_strong = np.linalg.norm(np.asarray(strong["base"]["w"]) - pw)
    assert d_strong < d_weak


def _clip(n, seed):
    rng = np.random.default_rng(seed)
    C = rng.normal(size=(n, 512)).astype(np.float32)
    return C / np.linalg.norm(C, axis=1, keepdims=True)


def test_score_mixed_clip():
    rows = _rows(400, 4)
    X, y = taste.features(rows), _label(rows)
    C = _clip(400, 5)
    C[::2] = np.nan
    m = taste.fit(X, C, y, np.ones(400, np.float32))
    assert m["full"] is not None
    s = taste.score(m, X, C)
    assert s.shape == (400,) and np.isfinite(s).all() and s.min() >= 0 and s.max() <= 1
    sb = taste.score({"base": m["base"], "full": None, "n": 0}, X, None)
    assert np.allclose(s[::2], sb[::2])
    assert not np.allclose(s[1::2], sb[1::2])


def _prows(n, t0=0.0, step=5.0):
    return [dict(id=i + 1, rating=0, grp=0, taken=t0 + i * step) for i in range(n)]


def test_pick_one_per_group():
    rows = _prows(20)
    s = np.linspace(0.5, 0.1, 20)
    for i in (0, 1, 2):
        rows[i]["grp"] = 7
        s[i] = 0.9 + i * 0.01
    r = taste.pick(5, s, rows, None)
    assert len(r["ids"]) == 5 and r["note"] == ""
    assert len({1, 2, 3} & set(r["ids"])) == 1
    assert 3 in r["ids"]  # tấm điểm cao nhất của nhóm


def test_pick_keeps_starred():
    rows = _prows(30)
    s = np.linspace(0.9, 0.1, 30)
    rows[29]["rating"] = 2
    r = taste.pick(5, s, rows, None)
    assert 30 in r["ids"] and len(r["ids"]) == 5


def test_pick_stars_exceed_n():
    rows = _prows(20)
    s = np.linspace(0.9, 0.1, 20)
    for i in (3, 6, 9, 12, 15):
        rows[i]["rating"] = 1
    r = taste.pick(3, s, rows, None)
    assert sorted(r["ids"]) == [4, 7, 10, 13, 16]
    assert "nhiều hơn" in r["note"]


def test_pick_more_than_available():
    rows = _prows(10)
    r = taste.pick(100, np.linspace(0.9, 0.1, 10), rows, None)
    assert sorted(r["ids"]) == list(range(1, 11))
    assert "chỉ tìm được 10" in r["note"]


def test_pick_timeline_cover():
    a = _prows(50)
    b = _prows(25, t0=50 * 5 + 1800)
    for i, r in enumerate(b):
        r["id"] = 100 + i
    rows = a + b
    s = np.concatenate([np.linspace(0.9, 0.5, 50), np.linspace(0.3, 0.1, 25)])
    r = taste.pick(10, s, rows, None)
    assert len(r["ids"]) == 10
    assert 100 in r["ids"]  # tấm điểm cao nhất của đoạn 2
    assert 10 not in r["ids"]  # đổi lấy tấm điểm thấp nhất đang chọn


def test_pick_near_duplicate_clip():
    rows = _prows(10)
    s = np.linspace(0.9, 0.1, 10)
    C = _clip(10, 6)
    C[1] = C[0]          # giống hệt, cách 5 s → bỏ
    C[3] = np.nan        # không có CLIP → không xét trùng
    r = taste.pick(3, s, rows, C)
    assert r["ids"] == [1, 3, 4]


def test_pick_deterministic():
    rows = _prows(300)
    for i, r in enumerate(rows):
        r["grp"] = i // 3
    s = np.random.default_rng(7).random(300)
    s[10:20] = 0.5  # điểm bằng nhau
    C = _clip(300, 8)
    a = taste.pick(40, s, rows, C)
    b = taste.pick(40, s.copy(), [dict(r) for r in rows], C.copy())
    assert a == b


def test_pick_skips_rejected():
    rows = _prows(10)
    rows[0]["rating"] = -1
    rows[1]["rating"] = -1
    r = taste.pick(100, np.linspace(0.9, 0.1, 10), rows, None)
    assert 1 not in r["ids"] and 2 not in r["ids"] and len(r["ids"]) == 8


def test_save_load_roundtrip(tmp_path):
    rows = _rows(300, 9)
    X, y = taste.features(rows), _label(rows)
    C = _clip(300, 10)
    C[:100] = np.nan
    m = taste.fit(X, C, y, np.ones(300, np.float32))
    p = tmp_path / "taste.npz"
    taste.save(p, m, {"rolls": 3, "agree": 0.78})
    m2, meta = taste.load(p)
    assert meta == {"rolls": 3, "agree": 0.78}
    assert m2["n"] == m["n"]
    assert np.allclose(taste.score(m, X, C), taste.score(m2, X, C))
    assert taste.load(tmp_path / "missing.npz") is None
    (tmp_path / "bad.npz").write_bytes(b"junk")
    assert taste.load(tmp_path / "bad.npz") is None


def test_fit_speed():
    n = 200_000
    rng = np.random.default_rng(11)
    X = rng.random((n, len(taste.FEATS)), dtype=np.float32)
    y = (rng.random(n) < 0.2).astype(np.float32)
    C = np.full((n, 512), np.nan, np.float32)
    C[:30_000] = _clip(30_000, 12)
    t = time.perf_counter()
    m = taste.fit(X, C, y, np.ones(n, np.float32))
    dt = time.perf_counter() - t
    assert m["full"] is not None
    assert dt < 10, dt
