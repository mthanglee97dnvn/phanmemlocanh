"""Gu chọn ảnh: trích đặc trưng, học (logistic, numpy), chấm điểm, chọn N tấm.

Không phụ thuộc Library — nhận dữ liệu dạng list[dict] / mảng numpy.
"""
import json
import math

import numpy as np

SCENES = ("decor", "detail", "object")

FEATS = [
    "sharp", "lum", "lo", "hi", "eyes", "smile", "away", "nfaces", "focus_c",
    "scene_decor", "scene_detail", "scene_object", "scene_other",
    "best", "grp_rank", "grp_size", "couple", "density",
]

BATCH = 4096
EPOCHS = 6
MIN_STEPS = 200      # ít dữ liệu (vài chục ảnh) vẫn đủ bước để hội tụ
LR = 0.05
DUP_COS = 0.95
DUP_SEC = 60.0
SEG_GAP = 600.0
SEG_MIN = 20


def _f(v, default=np.nan):
    try:
        if v is None:
            return default
        v = float(v)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _prank(v):
    """Thứ hạng phần trăm 0..1 trong mảng; NaN (không rõ) → 0.5; giá trị bằng nhau cùng hạng."""
    v = np.asarray(v, np.float64)
    out = np.full(len(v), 0.5)
    k = ~np.isnan(v)
    m = int(k.sum())
    if m > 1:
        sv = np.sort(v[k])
        lo = np.searchsorted(sv, v[k], "left")
        hi = np.searchsorted(sv, v[k], "right")
        out[k] = (lo + hi - 1) / 2.0 / (m - 1)
    return out


def features(rows):
    """rows của MỘT đám → ma trận float32 n×len(FEATS), chuẩn hoá trong đám."""
    n = len(rows)
    X = np.zeros((n, len(FEATS)), np.float32)
    if not n:
        return X
    col = {k: i for i, k in enumerate(FEATS)}
    sharp = np.empty(n)
    raw = {k: np.empty(n) for k in ("lum", "lo", "hi", "eyes", "smile", "nfaces", "focus_c", "taken")}
    away = np.zeros(n)
    grp = np.zeros(n, np.int64)
    for i, r in enumerate(rows):
        nf = _f(r.get("nfaces"), 0.0)
        fs = _f(r.get("fsharp"))
        sharp[i] = fs if nf > 0 and fs > 0 else _f(r.get("sharp"))
        raw["lum"][i] = _f(r.get("lum"))
        raw["lo"][i] = _f(r.get("lo"))
        raw["hi"][i] = _f(r.get("hi"))
        e = _f(r.get("ear_min"))
        raw["eyes"][i] = e if e >= 0 else np.nan
        s = _f(r.get("smile"))
        raw["smile"][i] = s if s >= 0 else np.nan
        raw["nfaces"][i] = nf
        raw["focus_c"][i] = _f(r.get("focus_c"))
        raw["taken"][i] = _f(r.get("taken"))
        away[i] = min(1.0, _f(r.get("away"), 0.0) / nf) if nf > 0 else 0.0
        grp[i] = int(_f(r.get("grp"), 0.0))
        sc = r.get("scene")
        X[i, col["scene_" + sc if sc in SCENES else "scene_other"]] = 1.0
        X[i, col["couple"]] = 1.0 if r.get("couple") else 0.0
        X[i, col["best"]] = 1.0 if (grp[i] == 0 or r.get("best")) else 0.0

    X[:, col["sharp"]] = _prank(sharp)
    for k in ("lum", "lo", "hi", "eyes", "smile", "nfaces", "focus_c"):
        X[:, col[k]] = _prank(raw[k])
    X[:, col["away"]] = away

    # vị trí trong nhóm ảnh trùng: thứ hạng nét (1 = nét nhất), cỡ nhóm
    grank = np.ones(n)
    gsize = np.ones(n)
    order = np.argsort(grp, kind="stable")
    gs = grp[order]
    starts = np.flatnonzero(np.r_[True, gs[1:] != gs[:-1]])
    ends = np.r_[starts[1:], n]
    for a, b in zip(starts, ends):
        if gs[a] == 0 or b - a < 2:
            continue
        idx = order[a:b]
        grank[idx] = _prank(np.nan_to_num(sharp[idx], nan=-1.0))
        gsize[idx] = b - a
    X[:, col["grp_rank"]] = grank
    X[:, col["grp_size"]] = _prank(gsize)

    # mật độ bấm máy: số ảnh trong ±30 s
    t = raw["taken"]
    dens = np.full(n, np.nan)
    k = ~np.isnan(t)
    if k.any():
        st = np.sort(t[k])
        dens[k] = np.searchsorted(st, t[k] + 30, "right") - np.searchsorted(st, t[k] - 30, "left")
    X[:, col["density"]] = _prank(dens)
    return X


def _sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _has_clip(C, n):
    if C is None:
        return np.zeros(n, bool)
    C = np.asarray(C)
    if C.ndim != 2 or len(C) != n:
        return np.zeros(n, bool)
    return ~np.isnan(C).any(axis=1)


def _train(get, n, d, y, sw, w0, b0, wp, lam, rng):
    """Logistic hồi quy, Adam mini-batch; phạt lam·||w − wp||² (chia theo tổng trọng số mẫu)."""
    w = w0.astype(np.float32).copy()
    b = np.float32(b0)
    wp = wp.astype(np.float32)
    tot = float(sw.sum()) or 1.0
    reg = np.float32(2.0 * lam / tot)
    mw, vw = np.zeros(d, np.float32), np.zeros(d, np.float32)
    mb = vb = 0.0
    b1, b2, eps = 0.9, 0.999, 1e-8
    nb = max(1, -(-n // BATCH))
    epochs = max(EPOCHS, -(-MIN_STEPS // nb))
    step = 0
    for _ in range(epochs):
        perm = rng.permutation(n)
        for j in range(nb):
            ix = np.sort(perm[j * BATCH:(j + 1) * BATCH])
            xb = get(ix)
            p = _sig(xb @ w + b)
            r = ((p - y[ix]) * sw[ix]).astype(np.float32)
            bw = float(sw[ix].sum()) or 1.0
            gw = (xb.T @ r) / np.float32(bw) + reg * (w - wp)
            gb = float(r.sum()) / bw
            step += 1
            mw = b1 * mw + (1 - b1) * gw
            vw = b2 * vw + (1 - b2) * gw * gw
            mb = b1 * mb + (1 - b1) * gb
            vb = b2 * vb + (1 - b2) * gb * gb
            c1, c2 = 1 - b1 ** step, 1 - b2 ** step
            w = (w - LR * (mw / c1) / (np.sqrt(vw / c2) + eps)).astype(np.float32)
            b = np.float32(b - LR * (mb / c1) / (math.sqrt(vb / c2) + eps))
    return {"w": w, "b": float(b)}


def _prior_part(prior, key, d):
    p = (prior or {}).get(key) if isinstance(prior, dict) else None
    if p:
        w = np.asarray(p.get("w"), np.float32).reshape(-1)
        if w.shape == (d,):
            return w, float(p.get("b", 0.0))
    return np.zeros(d, np.float32), None


def fit(X, C, y, w, prior=None, lam=1.0, seed=0):
    X = np.asarray(X, np.float32)
    n, d = X.shape
    y = np.asarray(y, np.float32).reshape(-1)
    w = np.asarray(w, np.float32).reshape(-1)
    pos = y > 0.5
    wpos, wneg = float(w[pos].sum()), float(w[~pos].sum())
    tot = wpos + wneg
    cw = np.where(pos, tot / (2 * wpos) if wpos > 0 else 0.0, tot / (2 * wneg) if wneg > 0 else 0.0)
    sw = (w * cw).astype(np.float32)
    rng = np.random.default_rng(seed)

    def start(wp, bp, swk, yk):
        if bp is not None:
            return wp, bp
        pk = float((swk * yk).sum()) / (float(swk.sum()) or 1.0)
        pk = min(max(pk, 1e-3), 1 - 1e-3)
        return wp, math.log(pk / (1 - pk))

    wp, bp = _prior_part(prior, "base", d)
    w0, b0 = start(wp, bp, sw, y)
    base = _train(lambda ix: X[ix], n, d, y, sw, w0, b0, wp, lam, rng)

    full = None
    k = np.flatnonzero(_has_clip(C, n))
    if len(k) >= 2 and len(np.unique(y[k] > 0.5)) == 2:
        Ck = np.asarray(C)
        df = d + Ck.shape[1]
        yk, swk = y[k], sw[k]
        wp, bp = _prior_part(prior, "full", df)
        w0, b0 = start(wp, bp, swk, yk)
        get = lambda ix: np.hstack([X[k[ix]], Ck[k[ix]].astype(np.float32)])
        full = _train(get, len(k), df, yk, swk, w0, b0, wp, lam, rng)
    return {"base": base, "full": full, "n": int(n)}


def score(model, X, C):
    X = np.asarray(X, np.float32)
    n = len(X)
    bm = model["base"]
    s = _sig(X @ np.asarray(bm["w"], np.float32) + np.float32(bm["b"]))
    fm = model.get("full")
    k = np.flatnonzero(_has_clip(C, n))
    if fm is not None and len(k):
        fw = np.asarray(fm["w"], np.float32)
        Ck = np.asarray(C)[k].astype(np.float32)
        if fw.shape[0] == X.shape[1] + Ck.shape[1]:
            s[k] = _sig(np.hstack([X[k], Ck]) @ fw + np.float32(fm["b"]))
    return s.astype(np.float64)


def pick(n, s, rows, C):
    n = max(0, int(n))
    s = np.asarray(s, np.float64)
    N = len(rows)
    rating = np.array([int(_f(r.get("rating"), 0.0)) for r in rows])
    grp = np.array([int(_f(r.get("grp"), 0.0)) for r in rows])
    t = np.array([_f(r.get("taken")) for r in rows])
    ids = [r["id"] for r in rows]
    ok = (rating >= 0) & np.isfinite(s)
    star = ok & (rating >= 1)
    order = np.lexsort((np.arange(N), -np.where(np.isfinite(s), s, -np.inf)))  # điểm giảm, hoà → thứ tự hàng
    rank = np.empty(N, np.int64)
    rank[order] = np.arange(N)

    def out(sel, note=""):
        sel = sorted(sel, key=lambda i: rank[i])
        return {"ids": [ids[i] for i in sel], "note": note}

    nstar = int(star.sum())
    if nstar >= n:
        note = f"Bạn đã chọn {nstar} tấm, nhiều hơn {n}" if nstar > n else ""
        return out(np.flatnonzero(star), note)

    hc = _has_clip(C, N)
    Cn = np.asarray(C, np.float32) if hc.any() else None
    tk = np.isfinite(t)
    torder = np.flatnonzero(tk)[np.argsort(t[tk], kind="stable")]
    tsorted = t[torder]
    chosen = np.zeros(N, bool)
    used = set()

    def free(i):
        if grp[i] != 0 and grp[i] in used:
            return False
        if Cn is None or not hc[i] or not tk[i]:
            return True
        a = np.searchsorted(tsorted, t[i] - DUP_SEC, "left")
        b = np.searchsorted(tsorted, t[i] + DUP_SEC, "right")
        nb = torder[a:b]
        nb = nb[chosen[nb] & hc[nb] & (np.abs(t[nb] - t[i]) < DUP_SEC)]
        return not (len(nb) and float((Cn[nb] @ Cn[i]).max()) > DUP_COS)

    def add(i):
        chosen[i] = True
        if grp[i] != 0:
            used.add(grp[i])

    for i in order:
        if star[i]:
            add(i)
    cnt = nstar
    for i in order:
        if cnt >= n:
            break
        if ok[i] and not chosen[i] and free(i):
            add(i)
            cnt += 1

    # phủ dòng thời gian: đoạn ≥ SEG_MIN ảnh, tách bởi khoảng trống > SEG_GAP, chưa có tấm nào
    el = torder[ok[torder]]
    if len(el):
        cut = np.flatnonzero(np.diff(t[el]) > SEG_GAP) + 1
        segs = np.split(el, cut)
        seg_of = np.full(N, -1)
        for si, sg in enumerate(segs):
            seg_of[sg] = si
        for sg in segs:
            if len(sg) < SEG_MIN or chosen[sg].any():
                continue
            cand = [i for i in sorted(sg, key=lambda i: rank[i]) if free(i)]
            if not cand:
                continue
            picks = np.flatnonzero(chosen)
            cnt_seg = {}
            for j in picks:
                cnt_seg[seg_of[j]] = cnt_seg.get(seg_of[j], 0) + 1
            drop = [j for j in picks if not star[j] and not (seg_of[j] >= 0 and cnt_seg[seg_of[j]] == 1)]
            if not drop:
                continue
            j = max(drop, key=lambda j: rank[j])
            chosen[j] = False
            if grp[j] != 0:
                used.discard(grp[j])
            add(cand[0])

    sel = np.flatnonzero(chosen)
    note = f"chỉ tìm được {len(sel)} tấm khác nhau" if len(sel) < n else ""
    return out(sel, note)


def agreement(model, X, C, y_keep, rows):
    y = np.asarray(y_keep).reshape(-1) > 0.5
    N = int(y.sum())
    if N == 0:
        return 0.0
    s = score(model, X, C)
    blank = [dict(r, rating=0) for r in rows]
    got = pick(N, s, blank, C)["ids"]
    kept = {rows[i]["id"] for i in np.flatnonzero(y)}
    return len(kept & set(got)) / N


def save(path, model, meta):
    full = model.get("full")
    with open(path, "wb") as fh:
        np.savez(
            fh,
            base_w=np.asarray(model["base"]["w"], np.float32),
            base_b=np.float64(model["base"]["b"]),
            full_w=np.asarray(full["w"], np.float32) if full else np.zeros(0, np.float32),
            full_b=np.float64(full["b"] if full else 0.0),
            has_full=np.bool_(bool(full)),
            n=np.int64(model.get("n", 0)),
            meta=np.array(json.dumps(meta or {}, ensure_ascii=False)),
        )


def load(path):
    try:
        with np.load(path, allow_pickle=False) as z:
            full = None
            if bool(z["has_full"]):
                full = {"w": z["full_w"].astype(np.float32), "b": float(z["full_b"])}
            model = {"base": {"w": z["base_w"].astype(np.float32), "b": float(z["base_b"])},
                     "full": full, "n": int(z["n"])}
            meta = json.loads(str(z["meta"]))
        return model, meta
    except Exception:
        return None
