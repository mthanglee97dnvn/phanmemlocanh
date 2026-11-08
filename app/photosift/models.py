"""Quản lý file model (tải tự động ở lần chạy đầu nếu thiếu)."""
from __future__ import annotations
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

# Bản đóng gói sẵn (PhotoSiftCore.exe) đặt thư mục model cạnh file cài đặt, qua biến PHOTOSIFT_APPDIR
_APP = Path(os.environ["PHOTOSIFT_APPDIR"]) if os.environ.get("PHOTOSIFT_APPDIR") else Path(__file__).resolve().parent.parent
MODELS_DIR = _APP / "models"

# (tên file, URL, bắt buộc?)
MODELS = [
    ("yunet.onnx",
     "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
     True),
    ("sface.onnx",
     "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
     True),
    # Tuỳ chọn: 68 điểm mốc khuôn mặt, dùng để phát hiện nhắm mắt
    ("lbfmodel.yaml",
     "https://raw.githubusercontent.com/kurnianggoro/GSOC2017/master/data/lbfmodel.yaml",
     False),
    # Tuỳ chọn: nhận diện biểu cảm (FER+, 8 cảm xúc) — dùng để lọc / sắp xếp ảnh có nụ cười
    ("ferplus.onnx",
     "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx",
     False),
]


def path(name: str) -> Path:
    return MODELS_DIR / name


def have(name: str) -> bool:
    p = path(name)
    return p.exists() and p.stat().st_size > 10_000


def ensure_models(verbose: bool = True) -> list[str]:
    """Tải các model còn thiếu. Trả về danh sách model bắt buộc vẫn thiếu."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    missing = []
    for name, url, required in MODELS:
        if have(name):
            continue
        sk = path(name + ".skip")
        if not required and sk.exists() and time.time() - sk.stat().st_mtime < 6 * 3600:
            continue  # vừa thử và lỗi: đừng làm chậm các lần mở sau (thử lại sau 6 giờ)
        if verbose:
            print(f"[models] đang tải {name} ...", flush=True)
        try:
            tmp = path(name).with_suffix(".part")
            with urllib.request.urlopen(url, timeout=30 if required else 12) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            tmp.replace(path(name))
            sk.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"[models] không tải được {name}: {e}", file=sys.stderr)
            if required:
                missing.append(name)
            else:
                try:
                    path(name + ".skip").write_text("skip")
                except OSError:
                    pass
    return missing


if __name__ == "__main__":
    m = ensure_models()
    print("Thiếu model bắt buộc:", m if m else "không")
