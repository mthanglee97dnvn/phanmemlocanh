"""Luyện gu mặc định (app/models/taste_default.npz) từ một hoặc nhiều file taste_data.npz.

taste_data.npz do nút ẩn "Xuất dữ liệu học" trong hộp "Gu chọn ảnh" ghi ra (Library.taste_export):
X (đặc trưng đã chuẩn hoá trong đám), C (CLIP float16, hàng NaN = chưa có), y (1 = giữ), w (trọng số), roll (mã đám),
grp (nhóm ảnh trùng), taken (giây tính từ đầu đám), feats (tên đặc trưng). Không có ảnh hay tên file.

    python3 tools/train_taste.py a/taste_data.npz b/taste_data.npz -o app/models/taste_default.npz

In độ trùng khớp kiểu "bỏ ra một đám" trên tối đa 5 đám nhiều ảnh nhất (luyện trên các đám còn lại, chọn N = số ảnh
người dùng đã giữ trong đám đó), rồi luyện trên toàn bộ và lưu. Gu mặc định không có prior, phạt L2 nhỏ.
"""
import argparse
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from photosift import taste  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "app", "models", "taste_default.npz")


def load_all(paths):
    X, C, y, w, roll, grp, taken = [], [], [], [], [], [], []
    off = 0
    for p in paths:
        with np.load(p, allow_pickle=False) as z:
            feats = [str(f) for f in z["feats"]]
            if feats != list(taste.FEATS):
                sys.exit(f"{p}: danh sách đặc trưng khác bản app hiện tại ({len(feats)} so với {len(taste.FEATS)})")
            n = len(z["y"])
            X.append(z["X"].astype(np.float32))
            C.append(z["C"].astype(np.float16))
            y.append(z["y"].astype(np.int8))
            w.append(z["w"].astype(np.float32))
            r = z["roll"].astype(np.int64)
            roll.append(r + off)
            off += int(r.max()) + 1 if n else 0
            grp.append(z["grp"].astype(np.int64) if "grp" in z.files else np.zeros(n, np.int64))
            taken.append(z["taken"].astype(np.float64) if "taken" in z.files else np.arange(n, dtype=np.float64))
            print(f"{p}: {n} ảnh, {len(np.unique(r))} đám, giữ {int(z['y'].sum())}")
    cat = np.concatenate
    return np.vstack(X), np.vstack(C), cat(y), cat(w), cat(roll), cat(grp), cat(taken)


def rows_of(grp, taken):
    """Dòng tối thiểu cho taste.pick: không có sao (blank), nhóm trùng, giờ chụp."""
    return [dict(id=i, rating=0, grp=int(g), taken=float(t)) for i, (g, t) in enumerate(zip(grp, taken))]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Luyện gu mặc định từ các file taste_data.npz")
    ap.add_argument("inputs", nargs="+", help="một hoặc nhiều taste_data.npz")
    ap.add_argument("-o", "--out", default=DEFAULT_OUT, help="file mô hình ra (mặc định app/models/taste_default.npz)")
    ap.add_argument("--lam", type=float, default=1.0, help="hệ số phạt L2 về 0 (mặc định 1.0 — nhỏ)")
    ap.add_argument("--holdout", type=int, default=5, help="số đám đem ra đo độ trùng khớp (mặc định 5)")
    a = ap.parse_args(argv)

    X, C, y, w, roll, grp, taken = load_all(a.inputs)
    yf = y.astype(np.float32)
    ids, cnt = np.unique(roll, return_counts=True)
    print(f"Tổng: {len(y)} ảnh, {len(ids)} đám, giữ {int(y.sum())}, có CLIP {int((~np.isnan(C).any(axis=1)).sum())}")

    scores = []
    if len(ids) < 2:
        print("Chỉ có 1 đám: bỏ qua bước đo độ trùng khớp")
    else:
        for r in ids[np.argsort(-cnt, kind="stable")][:a.holdout]:
            te = roll == r
            if not y[te].any():
                continue
            t0 = time.time()
            m = taste.fit(X[~te], C[~te], yf[~te], w[~te], lam=a.lam)
            ag = taste.agreement(m, X[te], C[te], y[te], rows_of(grp[te], taken[te]))
            scores.append(ag)
            print(f"  Đám #{int(r)}: {int(te.sum())} ảnh, giữ {int(y[te].sum())} → trùng khớp {ag:.1%} ({time.time() - t0:.1f}s)")
        if scores:
            print(f"Trung bình: {np.mean(scores):.1%}")

    t0 = time.time()
    model = taste.fit(X, C, yf, w, lam=a.lam)
    meta = {"rolls": int(len(ids)), "rows": int(len(y)), "feats": list(taste.FEATS), "lam": a.lam,
            "agree": round(float(np.mean(scores)), 4) if scores else None, "learned": time.time()}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    taste.save(a.out, model, meta)
    print(f"Đã lưu {a.out} ({'có' if model['full'] else 'không có'} bản CLIP, {time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
