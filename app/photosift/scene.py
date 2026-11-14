"""Phân loại ảnh KHÔNG có người thành: decor / chi tiết / vật phẩm.

Dùng một model CLIP (bộ mã hoá ảnh, ONNX) + các vector mô tả văn bản đã tính sẵn
(clip_text.npz, sinh bởi tools/make_clip.py). Chạy bằng onnxruntime. Hoàn toàn offline.

Thiết kế ĐỘC LẬP MODEL: mọi tham số (cỡ ảnh vào, mean/std, logit_scale, nhãn) đọc từ
clip_text.npz, nên đổi model chỉ cần sinh lại 2 file, không sửa code này.

An toàn thoái lui: thiếu onnxruntime hoặc thiếu 2 file model -> available()=False,
classify()=None; app chạy bình thường, chỉ không có phân loại cảnh.
"""
from __future__ import annotations

import threading

import numpy as np

from .models import path as model_path

# nhãn nội bộ -> dùng thống nhất ở DB và UI
CATEGORIES = ("decor", "detail", "object")

_VISION = "clip_vision.onnx"
_TEXT = "clip_text.npz"

_lock = threading.Lock()
_state: dict | None = None   # None = chưa thử nạp


def _load() -> dict:
    """Nạp một lần (lười). Trả dict trạng thái; ok=False nếu không dùng được."""
    try:
        import onnxruntime as ort  # noqa: F401
    except Exception:  # noqa: BLE001
        return dict(ok=False, why="thiếu onnxruntime")
    vpath, tpath = model_path(_VISION), model_path(_TEXT)
    if not vpath.exists() or not tpath.exists():
        return dict(ok=False, why="thiếu file model CLIP")
    try:
        import onnxruntime as ort
        z = np.load(tpath, allow_pickle=True)
        emb = np.ascontiguousarray(z["emb"], dtype=np.float32)      # (N, D) đã chuẩn hoá L2
        cats = [str(c) for c in z["cats"]]                           # (N,) nhãn mỗi câu mô tả
        size = int(z["size"]) if "size" in z else 224
        mean = np.asarray(z["mean"], np.float32).reshape(3, 1, 1) if "mean" in z else \
            np.asarray([0.48145466, 0.4578275, 0.40821073], np.float32).reshape(3, 1, 1)
        std = np.asarray(z["std"], np.float32).reshape(3, 1, 1) if "std" in z else \
            np.asarray([0.26862954, 0.26130258, 0.27577711], np.float32).reshape(3, 1, 1)
        scale = float(z["logit_scale"]) if "logit_scale" in z else 100.0
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1   # phân tích đã chạy đa luồng ở tầng trên
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(str(vpath), so, providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0].name
        # chỉ số các câu mô tả theo từng nhãn (gộp max khi suy luận)
        cat_idx = {c: [i for i, cc in enumerate(cats) if cc == c] for c in dict.fromkeys(cats)}
        return dict(ok=True, sess=sess, inp=inp, emb=emb, cat_idx=cat_idx,
                    size=size, mean=mean, std=std, scale=scale)
    except Exception as e:  # noqa: BLE001
        return dict(ok=False, why=f"lỗi nạp model CLIP: {e}")


def _get() -> dict:
    global _state
    if _state is None:
        with _lock:
            if _state is None:
                _state = _load()
    return _state


def available() -> bool:
    return bool(_get().get("ok"))


def _preprocess(bgr: np.ndarray, size: int, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    """BGR uint8 -> tensor NCHW float chuẩn CLIP (resize cạnh ngắn về size rồi cắt giữa)."""
    import cv2
    h, w = bgr.shape[:2]
    s = size / min(h, w)
    rw, rh = max(size, round(w * s)), max(size, round(h * s))
    img = cv2.resize(bgr, (rw, rh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    y0, x0 = (rh - size) // 2, (rw - size) // 2
    img = img[y0:y0 + size, x0:x0 + size]
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))          # HWC -> CHW
    img = (img - mean) / std
    return img[None].astype(np.float32)         # (1,3,size,size)


def classify(bgr: np.ndarray):
    """Trả (nhãn, độ_tin_cậy 0..1) hoặc None nếu không dùng được / lỗi.
    nhãn ∈ CATEGORIES. độ_tin_cậy = softmax trên các nhãn (đã gộp max theo câu mô tả)."""
    st = _get()
    if not st.get("ok") or bgr is None or getattr(bgr, "size", 0) == 0:
        return None
    try:
        x = _preprocess(bgr, st["size"], st["mean"], st["std"])
        feat = st["sess"].run(None, {st["inp"]: x})[0][0].astype(np.float32)   # (D,)
        feat /= (np.linalg.norm(feat) + 1e-9)
        cos = st["emb"] @ feat                                                   # (N,)
        labels = list(st["cat_idx"].keys())
        per = np.array([cos[st["cat_idx"][c]].max() for c in labels], np.float32)  # max theo nhãn
        logits = st["scale"] * per
        p = np.exp(logits - logits.max()); p /= p.sum()
        k = int(p.argmax())
        return labels[k], float(p[k])
    except Exception:  # noqa: BLE001
        return None
