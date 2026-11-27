"""Ảnh nét cho trình xem (RAW Sony, JPEG nhúng 1616px): bản dựng từ RAW không được kém nét hơn chính JPEG nhúng.
Báo lỗi 27/11: TAN08067 — JPEG nhúng độ nét 565, bản 'nét' app dựng ra chỉ 156 (đo Laplacian ở cùng cỡ 1616px):
_match_tone lấy chi tiết từ RAW chưa làm nét, trong khi JPEG máy ảnh đã được máy làm nét."""
import cv2
import numpy as np

from photosift.analyzer import _match_tone


def _scene(W=3000, H=2000, seed=1):
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 150, np.uint8)
    for _ in range(900):   # ren, tóc, viền áo: nhiều nét mảnh
        x, y = rng.integers(0, W), rng.integers(0, H)
        c = tuple(int(v) for v in rng.integers(30, 240, 3))
        cv2.line(img, (int(x), int(y)), (int(x + rng.integers(-60, 60)), int(y + rng.integers(-60, 60))), c, 1, cv2.LINE_AA)
    return img


def _sharp(g):
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def _luma_at(img, w, h):
    return cv2.cvtColor(cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)


def _camera_jpeg(scene):
    """JPEG nhúng: thu nhỏ còn 1616px rồi máy ảnh làm nét."""
    e = cv2.resize(scene, (1616, 1077), interpolation=cv2.INTER_AREA).astype(np.float32)
    e = e + 1.2 * (e - cv2.GaussianBlur(e, (0, 0), 1.0))
    return np.clip(e, 0, 255).astype(np.uint8)


def _raw_decode(scene):
    """RAW giải mã nửa độ phân giải: chưa làm nét (mềm), tông tối hơn JPEG."""
    r = cv2.GaussianBlur(scene, (0, 0), 1.1).astype(np.float32) * 0.8
    return np.clip(r, 0, 255).astype(np.uint8)


def _bands(g):
    g = g.astype(np.float32)
    return [float(np.std(g - cv2.GaussianBlur(g, (0, 0), s))) for s in (0.7, 1.5, 3)]


def test_view_not_softer_than_embedded_jpeg():
    """So ở cỡ hiển thị (cỡ bản nét), với JPEG nhúng phóng lên như trình duyệt vẫn làm — đúng cái mắt người nhìn thấy.
    Ảnh thật TAN08067 trước khi sửa: chi tiết bản nét / JPEG phóng lên = 2.08/2.65, 5.26/6.56, 9.28/10.74 (đều kém hơn)."""
    scene = _scene()
    emb, dec = _camera_jpeg(scene), _raw_decode(scene)
    out = _match_tone(dec, emb)
    assert out.shape == dec.shape
    H, W = dec.shape[:2]
    up = cv2.resize(emb, (W, H), interpolation=cv2.INTER_CUBIC)
    bo = _bands(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY))
    be = _bands(cv2.cvtColor(up, cv2.COLOR_BGR2GRAY))
    for o, e, s in zip(bo, be, (0.7, 1.5, 3)):
        assert o >= e, f"chi tiết cỡ {s}px: bản nét {o:.2f} kém JPEG nhúng phóng lên {e:.2f}"


def test_view_keeps_camera_colour():
    scene = _scene(seed=2)
    emb, dec = _camera_jpeg(scene), _raw_decode(scene)
    out = _match_tone(dec, emb)
    a = cv2.GaussianBlur(cv2.resize(out, (1616, 1077), interpolation=cv2.INTER_AREA), (0, 0), 4).astype(np.float32)
    b = cv2.GaussianBlur(emb, (0, 0), 4).astype(np.float32)
    assert float(np.abs(a - b).mean()) < 4, "màu / độ sáng phải theo JPEG máy ảnh"


def test_gain_not_runaway_on_flat_raw():
    """RAW gần như phẳng (ảnh tối, mất nét hẳn): không khuếch đại nhiễu vô hạn."""
    scene = _scene(seed=3)
    emb = _camera_jpeg(scene)
    flat = np.full((2000, 3000, 3), 120, np.uint8)
    flat = np.clip(flat + np.random.default_rng(0).normal(0, 1, flat.shape), 0, 255).astype(np.uint8)
    out = _match_tone(flat, emb)
    noise = float(np.std(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)
                         - cv2.GaussianBlur(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), (0, 0), 3).astype(np.float32)))
    assert noise < 25


def test_view_focus_items_queues_each_size(monkeypatch, tmp_path):
    """Trình xem gửi mỗi ảnh một cỡ (dọc / ngang chiếm khung khác nhau): hàng đợi dựng đúng từng cỡ."""
    from photosift import library
    monkeypatch.setattr(library, "VIEWS", tmp_path)
    L = library.Library.__new__(library.Library)
    import threading
    L._vcv, L._vq, L._vsides, L._vside = threading.Condition(), [], set(), 0
    L.settings, L._sfile = {}, tmp_path / "s.json"
    L.view_focus_items([(5, 1792), (6, 1216)], 1792)
    assert L._vq == [(5, 1792), (6, 1216)]
    assert {1792, 1216} <= L._vsides
