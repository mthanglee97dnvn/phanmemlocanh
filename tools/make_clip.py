"""Sinh 2 file model cho chức năng phân loại cảnh (decor / chi tiết / vật phẩm):
  app/models/clip_vision.onnx   — bộ mã hoá ảnh CLIP, lượng tử int8
  app/models/clip_text.npz      — vector mô tả văn bản đã tính sẵn + tham số tiền xử lý

CHẠY Ở MÁY CÓ INTERNET (máy build CI). Cần: torch, transformers, onnx, onnxruntime.
    python tools/make_clip.py
Model shipped chỉ cần onnxruntime + numpy (xem app/photosift/scene.py).

Đổi câu mô tả / model ở đây rồi chạy lại là xong, không phải sửa code app.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import torch
from transformers import CLIPModel, CLIPTokenizer

MODEL = os.environ.get("CLIP_MODEL", "openai/clip-vit-base-patch32")
OUT = Path(__file__).resolve().parents[1] / "app" / "models"

# Câu mô tả cho từng nhãn (tiếng Việt + tiếng Anh, nhiều cách diễn đạt để zero-shot ổn định).
# Khi suy luận, mỗi nhãn lấy câu khớp nhất (max) rồi softmax giữa các nhãn.
PROMPTS: dict[str, list[str]] = {
    "decor": [
        "trang trí tiệc cưới", "phông nền chụp ảnh cưới", "sân khấu lễ cưới",
        "bàn tiệc cưới trang trí hoa", "cổng hoa cưới", "backdrop hoa", "không gian tiệc cưới",
        "a wedding venue decoration", "a wedding photo backdrop", "a decorated wedding stage",
        "a banquet table with flower arrangements", "a floral wedding arch", "wedding hall decor",
    ],
    "detail": [
        "cận cảnh nhẫn cưới", "cận cảnh đôi giày cô dâu", "thiệp cưới", "hoa cầm tay cô dâu",
        "cận cảnh phụ kiện cưới", "cận cảnh trang sức", "chi tiết váy cưới",
        "a close-up of wedding rings", "a close-up of the bride's shoes", "a wedding invitation card",
        "a bridal bouquet close-up", "a close-up of wedding accessories", "a macro detail shot",
    ],
    "object": [
        "bánh cưới", "quà cưới", "ly rượu champagne", "hộp quà", "đồ vật trên bàn tiệc",
        "chai rượu vang", "món đồ vật phẩm",
        "a wedding cake", "a wedding gift box", "champagne glasses", "a bottle of wine",
        "an object on a table", "a single product object",
    ],
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[make_clip] model: {MODEL}")
    model = CLIPModel.from_pretrained(MODEL).eval()
    tokz = CLIPTokenizer.from_pretrained(MODEL)   # chỉ cần tokenizer văn bản (không cần bộ xử lý ảnh)

    cats: list[str] = []
    texts: list[str] = []
    for c, ps in PROMPTS.items():
        for p in ps:
            cats.append(c)
            texts.append(p)
    with torch.no_grad():
        tok = tokz(texts, return_tensors="pt", padding=True)
        temb = model.get_text_features(**tok)
        temb = temb / temb.norm(dim=-1, keepdim=True)
    emb = temb.cpu().numpy().astype(np.float32)
    size = int(model.config.vision_config.image_size)
    # Hằng số chuẩn hoá của CLIP (OpenAI) — cố định, khớp với app/photosift/scene.py
    mean = np.asarray([0.48145466, 0.4578275, 0.40821073], np.float32)
    std = np.asarray([0.26862954, 0.26130258, 0.27577711], np.float32)
    scale = float(model.logit_scale.exp().item())
    np.savez(OUT / "clip_text.npz", emb=emb, cats=np.asarray(cats), size=size,
             mean=mean, std=std, logit_scale=scale)
    print(f"[make_clip] clip_text.npz: {emb.shape[0]} câu, {emb.shape[1]} chiều, size={size}, scale={scale:.1f}")

    class Vision(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):   # trả embedding đã chiếu (cùng không gian với text)
            return self.m.get_image_features(pixel_values=pixel_values)

    dummy = torch.randn(1, 3, size, size)
    fp32 = OUT / "clip_vision_fp32.onnx"
    torch.onnx.export(
        Vision(model), dummy, str(fp32),
        input_names=["pixel_values"], output_names=["image_features"],
        dynamic_axes={"pixel_values": {0: "batch"}}, opset_version=17,
    )
    from onnxruntime.quantization import QuantType, quantize_dynamic
    quantize_dynamic(str(fp32), str(OUT / "clip_vision.onnx"), weight_type=QuantType.QInt8)
    fp32.unlink(missing_ok=True)
    mb = (OUT / "clip_vision.onnx").stat().st_size / 1e6
    print(f"[make_clip] clip_vision.onnx (int8): {mb:.1f} MB")


if __name__ == "__main__":
    main()
