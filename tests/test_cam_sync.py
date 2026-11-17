import random
import time

import numpy as np

from photosift.library import Library

T0 = 1_790_000_000.0
A, B = "SONY · ILCE-7RM3 · 111", "SONY · ILCE-7M4 · 222"


def toffs(L, cam):
    return [r["toff"] for r in L.db.q("SELECT toff FROM photos WHERE cam=?", (cam,))]


def test_photos_order_ties(lib_with):
    L, ids = lib_with([(A, T0)] * 3 + [(B, T0 + 5)] * 3)
    got = [p[0] for p in L.cam_photos(B)["photos"]]
    assert got == ids[3:]
    assert L.cam_photos(B)["photos"][0][1] == T0 + 5


def test_pair_basic(lib_with):
    L, ids = lib_with([(A, T0 + 31), (A, T0 + 40), (B, T0 + 24), (B, T0 + 60), (B, T0 + 70)])
    r = L.cam_pair(ids[0], ids[2])
    assert r == {"ok": True, "cam": B, "offset": 7, "n": 3}
    assert all(t == 0 for t in toffs(L, A)) and all(t == 7 for t in toffs(L, B))


def test_pair_same_camera(lib_with):
    L, ids = lib_with([(A, T0), (A, T0 + 1)])
    assert L.cam_pair(ids[0], ids[1])["error"] == "Hai tấm cùng một máy — hãy chọn tấm của máy khác"


def test_pair_unknown_camera(lib_with):
    L, ids = lib_with([(A, T0), ("?", T0 + 1)])
    assert "error" in L.cam_pair(ids[0], ids[1])
    assert toffs(L, "?") == [0]


def test_pair_uses_ref_effective_time(lib_with):
    L, ids = lib_with([(A, T0 + 31), (B, T0 + 24)])
    L.cameras_apply({A: 60})
    assert L.cam_pair(ids[0], ids[1])["offset"] == 67


def test_estimate_existing(lib_with):
    L, ids = lib_with([(A, T0), (B, T0)])
    L.cameras_apply({B: 120})
    assert L.cam_estimate(A, B) == {"offset": 120, "conf": 1.0, "source": "existing"}


def test_estimate_none(lib_with):
    L, ids = lib_with([(A, T0), (B, T0)])
    assert L.cam_estimate(A, B) == {"offset": 0, "conf": 0.0, "source": "none"}


def test_estimate_day_offset_fast(lib_with):
    rnd = random.Random(3)
    ts, t = [], T0
    for _ in range(300):
        t += rnd.choice([1, 1, 2, 5, 30, 90, 400])
        ts.append(t)
    L, ids = lib_with([(A, x) for x in ts] + [(B, x - 86400 + 7) for x in ts])
    t1 = time.perf_counter()
    r = L.cam_estimate(A, B)
    assert time.perf_counter() - t1 < 2.0
    assert r["source"] == "auto" and r["offset"] == 86400 - 7


def test_estimate_matches_old_small():
    rnd = random.Random(5)
    ref = sorted(T0 + rnd.uniform(0, 3600) for _ in range(40))
    assert Library._estimate_offset(ref, [t - 13 for t in ref])[0] == 13.0
