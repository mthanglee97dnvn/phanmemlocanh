"""Phân tích một ảnh: độ nét, phơi sáng, dHash (trùng lặp), khuôn mặt + embedding, độ mở mắt."""
from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import models

cv2.setNumThreads(1)  # song song hoá theo từng ảnh thay vì trong từng ảnh

RAW_EXT = {".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".orf", ".raf",
           ".rw2", ".pef", ".srw", ".3fr", ".erf", ".kdc", ".mrw", ".x3f"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".heic", ".heif"}
ALL_EXT = RAW_EXT | IMG_EXT

ANALYSIS_SIDE = 1600   # cạnh dài tối đa khi phân tích
SHARP_SIDE = 1024      # cạnh dài khi đo độ nét
DETECT_SIDE = 960         # cạnh dài ảnh dùng để tìm mặt; 960px vẫn thấy mặt từ khoảng 36px trên ảnh 1616px
FACE_REF_SIDE = 1280      # MIN_FACE_PX và EAR_MIN_FACE_PX tính theo cỡ ảnh này
MIN_ID_PX = 60            # mặt nhỏ hơn cỡ này (theo ảnh gốc) không được nhận diện người
THUMB_SIDE = 360
MIN_FACE_PX = 28       # mặt nhỏ hơn (trên ảnh phân tích) bị bỏ qua
EAR_MIN_FACE_PX = 60   # chỉ đo mắt với mặt đủ lớn


def _imdecode(data: bytes | np.ndarray, flag=cv2.IMREAD_COLOR):
    if isinstance(data, (bytes, bytearray)):
        data = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(data, flag)


def _apply_orientation(img, ori: int):
    ops = {2: lambda a: cv2.flip(a, 1), 3: lambda a: cv2.rotate(a, cv2.ROTATE_180), 4: lambda a: cv2.flip(a, 0),
           5: lambda a: cv2.flip(cv2.rotate(a, cv2.ROTATE_90_CLOCKWISE), 1),
           6: lambda a: cv2.rotate(a, cv2.ROTATE_90_CLOCKWISE),
           7: lambda a: cv2.flip(cv2.rotate(a, cv2.ROTATE_90_COUNTERCLOCKWISE), 1),
           8: lambda a: cv2.rotate(a, cv2.ROTATE_90_COUNTERCLOCKWISE)}
    return ops[ori](img) if ori in ops else img


_SOI = b"\xff\xd8\xff"
_TSZ = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4}
_TFMT = {1: "B", 3: "H", 4: "I", 6: "b", 7: "B", 8: "h", 9: "i", 13: "I"}
MIN_GOOD_PREVIEW = 150_000   # JPEG nhúng nhỏ hơn mức này coi là thumbnail → tìm thêm ảnh lớn hơn
READ_BUF = 64 * 1024     # bộ đệm đọc: gom nhiều lần đọc nhỏ thành 1 lần (rất quan trọng khi đọc qua mạng LAN)
SCAN_BYTES = 8 << 20         # chỉ quét 8 MB đầu file khi cần dự phòng (không đọc cả file)


def _tiff_info(f):
    """Đọc cấu trúc TIFF của RAW (ARW/CR2/NEF/DNG/ORF/RW2...): chỉ vài KB.
    Trả về dict(ori, taken, jpegs=[(offset, length)]) hoặc None nếu không phải TIFF."""
    import struct
    f.seek(0)
    head = f.read(8)
    if len(head) < 8 or head[:2] not in (b"II", b"MM"):
        return None
    e = "<" if head[:2] == b"II" else ">"
    u16 = lambda b: struct.unpack(e + "H", b)[0]  # noqa: E731
    u32 = lambda b: struct.unpack(e + "I", b)[0]  # noqa: E731
    info = dict(ori=1, taken=None, jpegs=[], oris=[], ifds=[], endian=head[:2].decode())
    seen: set[int] = set()

    def vals(typ, cnt, raw):
        size = _TSZ.get(typ, 1) * cnt
        if cnt > 256 or size == 0:
            return []
        if size <= 4:
            data = raw[:size]
        else:
            f.seek(u32(raw))
            data = f.read(size)
        if typ == 2:
            return data
        fmt = _TFMT.get(typ)
        if not fmt or len(data) < size:
            return []
        return list(struct.unpack(e + fmt * cnt, data))

    def ifd(off, depth, is0=False):
        if off in seen or off < 8 or depth > 5:
            return
        seen.add(off)
        f.seek(off)
        b = f.read(2)
        if len(b) < 2:
            return
        n = u16(b)
        if n == 0 or n > 400:
            return
        blob = f.read(n * 12 + 4)
        if len(blob) < n * 12 + 4:
            return
        tags = {}
        for i in range(n):
            ent = blob[i * 12:i * 12 + 12]
            tags[u16(ent[0:2])] = (u16(ent[2:4]), u32(ent[4:8]), ent[8:12])
        nxt = u32(blob[n * 12:n * 12 + 4])
        g = lambda t: vals(*tags[t]) if t in tags else []  # noqa: E731
        v112 = g(0x112) if 0x112 in tags else []
        if is0 and v112:
            info["ori"] = v112[0]
        if v112:
            info["oris"].append((off, v112[0]))
        info["ifds"].append((off, depth, sorted(tags), v112[0] if v112 else None))
        for t in (0x9003, 0x132):
            if t in tags and info["taken"] is None:
                try:
                    info["taken"] = datetime.strptime(bytes(g(t))[:19].decode("ascii"), "%Y:%m:%d %H:%M:%S").timestamp()
                except Exception:  # noqa: BLE001
                    pass
        o, ln = g(0x201), g(0x202)
        if o and ln:
            info["jpegs"].append((o[0], ln[0]))
        comp, so, sc = g(0x103), g(0x111), g(0x117)
        if comp and comp[0] in (6, 7) and len(so) == 1 and len(sc) == 1:
            info["jpegs"].append((so[0], sc[0]))
        for sub in g(0x14A):
            ifd(sub, depth + 1)
        for ptr in g(0x8769):
            ifd(ptr, depth + 1)
        if nxt:
            ifd(nxt, depth + 1)

    try:
        ifd(u32(head[4:8]), 0, True)
    except Exception:  # noqa: BLE001
        pass
    return info


def _jpeg_size(blob: bytes):
    import io
    try:
        with Image.open(io.BytesIO(blob[:524288])) as im:
            ori = 1
            try:
                ori = int(im.getexif().get(0x0112, 1))
            except Exception:  # noqa: BLE001
                pass
            return im.size, ori
    except Exception:  # noqa: BLE001
        return None, 1


def _jpeg_exif_ori(head: bytes) -> int:
    """Đọc EXIF Orientation từ vài KB đầu của một JPEG (không cần giải mã)."""
    import struct
    try:
        i = 2
        while i + 4 <= len(head) and head[i] == 0xFF:
            mk, ln = head[i + 1], struct.unpack(">H", head[i + 2:i + 4])[0]
            if mk == 0xE1 and head[i + 4:i + 10] == b"Exif\0\0":
                t = head[i + 10:i + 2 + ln]
                e = "<" if t[:2] == b"II" else ">"
                off = struct.unpack(e + "I", t[4:8])[0]
                n = struct.unpack(e + "H", t[off:off + 2])[0]
                for k in range(n):
                    ent = t[off + 2 + k * 12:off + 14 + k * 12]
                    if struct.unpack(e + "H", ent[:2])[0] == 0x112:
                        return struct.unpack(e + "H", ent[8:10])[0]
                return 1
            if mk == 0xDA:
                break
            i += 2 + ln
    except Exception:  # noqa: BLE001
        pass
    return 1


def _decode_raw_jpeg(data: bytes):
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)


def _scan_largest(f):
    """Dự phòng: tìm JPEG lớn nhất trong 8 MB đầu file. Trả về (img chưa xoay, orientation của JPEG)."""
    f.seek(0)
    buf = f.read(SCAN_BYTES)
    best, pos = None, buf.find(_SOI)
    while pos != -1:
        size, ori = _jpeg_size(buf[pos:pos + 524288])
        if size and 0 < size[0] <= 30000 and 0 < size[1] <= 30000 and size[0] * size[1] >= 160 * 120:
            if best is None or size[0] * size[1] > best[0][0] * best[0][1]:
                best = (size, pos, ori)
        pos = buf.find(_SOI, pos + 3)
    if best is None:
        return None, 1
    (w, h), pos, ori = best
    img = _decode_raw_jpeg(buf[pos:])
    if img is None or img.shape[:2] != (h, w):  # bị cắt ở ranh giới 8 MB → đọc thêm đúng đoạn cần
        f.seek(pos)
        img = _decode_raw_jpeg(f.read(32 << 20))
    return img, ori


def _resolve_ori(info, jpeg_ori: int):
    """Hướng xoay: ưu tiên IFD0 → IFD khác trong file RAW → EXIF của chính ảnh JPEG nhúng."""
    if info:
        if info["ori"] not in (0, 1):
            return info["ori"], "IFD0 của file RAW"
        for off, v in info["oris"]:
            if v not in (0, 1):
                return v, f"IFD khác (offset {off})"
    if jpeg_ori not in (0, 1):
        return jpeg_ori, "EXIF của JPEG nhúng"
    return 1, "không có thông tin xoay (coi như ảnh ngang)"


def read_raw_preview(path: str, thumb: bool = False):
    """Ảnh xem trước nhúng trong file RAW + thời gian chụp.
    Chỉ đọc vài KB cấu trúc + đúng đoạn JPEG, không đọc cả file RAW → nhanh khi đọc từ thẻ nhớ.
    thumb=True: lấy JPEG nhỏ nhất (thường 160×120, ~10 KB) để hiện thumbnail gần như tức thì."""
    img, jori = None, 1
    with open(path, "rb", buffering=(32 * 1024 if thumb else 128 * 1024)) as f:
        info = _tiff_info(f)
        taken = info["taken"] if info else None
        cands = sorted(info["jpegs"], key=lambda x: x[1]) if info else []   # tăng dần theo dung lượng
        pick = [c for c in cands if c[1] >= 3000][:1] if thumb else cands[-1:]
        for off, ln in pick:
            f.seek(off)
            data = f.read(ln)
            if data[:2] == b"\xff\xd8":
                img = _decode_raw_jpeg(data)
                jori = _jpeg_size(data)[1]
        if not thumb and (img is None or max(img.shape[:2]) < 1000):
            alt, aori = _scan_largest(f)
            if alt is not None and (img is None or alt.shape[0] * alt.shape[1] > img.shape[0] * img.shape[1]):
                img, jori = alt, aori
        ori, _ = _resolve_ori(info, jori)
        if thumb and ori == 1 and cands:   # thumbnail không mang hướng xoay → xem phần đầu JPEG lớn (vài KB)
            f.seek(cands[-1][0])
            ori = _jpeg_exif_ori(f.read(16384))
    if img is not None:
        img = _apply_orientation(img, ori)
    return img, taken


def _num(v):
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return None


def _dms(v, ref):
    try:
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        ref = ref.decode() if isinstance(ref, bytes) else str(ref or "")
        return f"{d:.5f}° {ref.strip()}"
    except Exception:  # noqa: BLE001
        return ""


def read_exif(path: str) -> dict:
    """Thông số chụp: máy, ống kính, ISO, khẩu độ, tốc độ, ngày giờ, GPS... JPEG/PNG/TIFF dùng Pillow;
    RAW (ARW, CR2, NEF, DNG...) dùng bộ đọc IFD riêng vì Pillow không mở được."""
    import struct
    from PIL import TiffImagePlugin
    ext = Path(path).suffix.lower()
    d0 = ex = gps = None
    try:
        if ext in RAW_EXT or ext in (".tif", ".tiff"):
            with open(path, "rb", buffering=READ_BUF) as f:
                head = f.read(8)
                if head[:2] in (b"II", b"MM"):
                    e = "<" if head[:2] == b"II" else ">"

                    def ifd_at(o):
                        f.seek(o)
                        d = TiffImagePlugin.ImageFileDirectory_v2(ifh=head)
                        d.load(f)
                        return d
                    d0 = ifd_at(struct.unpack(e + "I", head[4:8])[0])
                    try:
                        ex = ifd_at(int(d0[0x8769])) if 0x8769 in d0 else None
                    except Exception:  # noqa: BLE001
                        ex = None
                    try:
                        gps = ifd_at(int(d0[0x8825])) if 0x8825 in d0 else None
                    except Exception:  # noqa: BLE001
                        gps = None
        if d0 is None:
            with Image.open(path) as im:
                e0 = im.getexif()
                d0 = e0
                ex = e0.get_ifd(0x8769)
                gps = e0.get_ifd(0x8825)
    except Exception:  # noqa: BLE001
        pass
    d0, ex, gps = d0 or {}, ex or {}, gps or {}
    g = lambda t: ex.get(t, d0.get(t))  # noqa: E731
    out = {}
    dt = g(0x9003) or d0.get(0x132)
    if dt:
        try:
            t = datetime.strptime(str(dt).strip()[:19], "%Y:%m:%d %H:%M:%S")
            out["date"], out["time"] = t.strftime("%d/%m/%Y"), t.strftime("%H:%M:%S")
        except Exception:  # noqa: BLE001
            pass
    out["make"] = str(d0.get(0x10F, "")).strip("\x00 ")
    out["model"] = str(d0.get(0x110, "")).strip("\x00 ")
    out["firmware"] = str(d0.get(0x131, "")).strip("\x00 ")
    ser = g(0xA431) or d0.get(0xC62F)
    out["serial"] = str(ser).strip("\x00 ") if ser else ""
    fl = _num(g(0x920A))
    out["focal"] = f"{fl:g}" if fl else ""
    out["lens"] = str(g(0xA434) or "").strip("\x00 ")
    iso = g(0x8827)
    if isinstance(iso, (tuple, list)):
        iso = iso[0] if iso else None
    out["iso"] = str(int(iso)) if iso else ""
    fn = _num(g(0x829D))
    out["aperture"] = f"{fn:.1f}".rstrip("0").rstrip(".") if fn else ""
    et = _num(g(0x829A))
    if et:
        out["shutter"] = f"1/{round(1 / et)}" if et < 0.95 else f"{et:g}\""
    ec = _num(g(0x9204))
    out["expcomp"] = f"{ec:+.1f}" if ec is not None else ""
    fh = g(0x9209)
    out["flash"] = ("Có chớp" if int(fh) & 1 else "Không chớp") if fh is not None else ""
    out["lat"] = _dms(gps.get(2), gps.get(1)) if gps.get(2) else ""
    out["lon"] = _dms(gps.get(4), gps.get(3)) if gps.get(4) else ""
    return out


def diag_raw(path: str) -> str:
    """Báo cáo chẩn đoán: file RAW lưu hướng xoay và ảnh xem trước ở đâu."""
    L = [f"File: {path}", f"Dung lượng: {os.path.getsize(path) / 1e6:.1f} MB"]
    with open(path, "rb", buffering=READ_BUF) as f:
        info = _tiff_info(f)
        if not info:
            L.append("Không phải cấu trúc TIFF (ví dụ RAF/CR3) → dùng quét JPEG dự phòng.")
            img, aori = _scan_largest(f)
            L.append(f"JPEG lớn nhất trong 8MB đầu: {None if img is None else img.shape[1::-1]}, EXIF orientation={aori}")
            return "\n".join(L)
        L.append(f"Kiểu byte: {info['endian']}")
        L.append("Các IFD đã duyệt (offset, độ sâu, Orientation, danh sách tag):")
        for off, depth, tags, ori in info["ifds"]:
            L.append(f"  - @{off} sâu={depth} orientation={ori} tags={[hex(t) for t in tags][:40]}")
        L.append(f"Orientation IFD0 = {info['ori']}; mọi giá trị tìm thấy = {info['oris']}")
        L.append(f"Giờ chụp: {info['taken']}")
        L.append("JPEG nhúng tìm thấy qua cấu trúc TIFF:")
        for off, ln in sorted(info["jpegs"], key=lambda x: -x[1]):
            f.seek(off)
            d = f.read(min(ln, 524288))
            size, jo = _jpeg_size(d)
            L.append(f"  - offset {off}, {ln / 1e6:.2f} MB, kích thước {size}, EXIF orientation của JPEG = {jo}, bắt đầu FFD8: {d[:2] == b'\xff\xd8'}")
        best_jo = 1
        c = sorted(info["jpegs"], key=lambda x: -x[1])[:1]
        if c:
            f.seek(c[0][0])
            best_jo = _jpeg_size(f.read(min(c[0][1], 524288)))[1]
        ori, src = _resolve_ori(info, best_jo)
        L.append(f"=> HƯỚNG XOAY ÁP DỤNG: {ori} (nguồn: {src})")
        buf = f.seek(0) or f.read(SCAN_BYTES)
        n = buf.count(_SOI)
        L.append(f"Số JPEG (FFD8FF) trong 8MB đầu: {n}")
    try:
        import rawpy
        with rawpy.imread(path) as raw:
            L.append(f"rawpy: flip={raw.sizes.flip}, kích thước raw={raw.sizes.width}x{raw.sizes.height}")
    except Exception as e:  # noqa: BLE001
        L.append(f"rawpy: không dùng được ({type(e).__name__})")
    return "\n".join(L)


def _read_raw(path: str, full: bool = False):
    """Đọc RAW: ưu tiên JPEG nhúng (nhanh, mọi đời máy); dự phòng bằng rawpy.
    full=True và JPEG nhúng nhỏ → thử giải mã RAW thật (nửa độ phân giải) nếu có rawpy."""
    img = None
    try:
        img, _ = read_raw_preview(path)
    except Exception:  # noqa: BLE001
        img = None
    if img is not None and not (full and max(img.shape[:2]) < 3000):
        return img
    try:
        import rawpy
        with rawpy.imread(path) as raw:
            if img is None:
                try:
                    t = raw.extract_thumb()
                    if t.format == rawpy.ThumbFormat.JPEG:
                        img = _imdecode(t.data)
                    elif t.format == rawpy.ThumbFormat.BITMAP:
                        img = cv2.cvtColor(t.data, cv2.COLOR_RGB2BGR)
                except Exception:  # noqa: BLE001
                    img = None
            if img is None or full:
                rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)  # đã xoay đúng chiều
                return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception:  # noqa: BLE001
        pass
    return img


def read_meta(path: str):
    """(w, h đã xoay, thời gian chụp hoặc None) — chỉ đọc header/EXIF. RAW: xử lý trong read_raw_preview."""
    ext = Path(path).suffix.lower()
    if ext in RAW_EXT:
        return 0, 0, None
    w = h = 0
    taken = None
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            w, h = im.size
            if ex.get(0x0112, 1) in (5, 6, 7, 8):
                w, h = h, w
            s = None
            try:
                s = ex.get_ifd(0x8769).get(0x9003)
            except Exception:  # noqa: BLE001
                pass
            s = s or ex.get(0x0132)
            if s:
                taken = datetime.strptime(str(s).strip()[:19], "%Y:%m:%d %H:%M:%S").timestamp()
    except Exception:  # noqa: BLE001
        pass
    return w, h, taken


def load_bgr(path: str, max_side: int = 0, size_hint: tuple[int, int] | None = None):
    """Đọc ảnh BGR đã xoay đúng chiều EXIF. max_side=0 → kích thước gốc.
    Hỗ trợ đường dẫn có ký tự Unicode (tiếng Việt) trên Windows."""
    ext = Path(path).suffix.lower()
    img = None
    if ext in RAW_EXT:
        img = _read_raw(path, full=(max_side == 0))
    else:
        data = np.fromfile(path, dtype=np.uint8)
        flag = cv2.IMREAD_COLOR
        if ext in (".jpg", ".jpeg") and max_side and size_hint and size_hint[0]:
            big = max(size_hint)
            for f, fl in ((8, cv2.IMREAD_REDUCED_COLOR_8), (4, cv2.IMREAD_REDUCED_COLOR_4),
                          (2, cv2.IMREAD_REDUCED_COLOR_2)):
                if big / f >= max_side:
                    flag = fl
                    break
        img = _imdecode(data, flag)
        if img is None:  # HEIC (cần pillow-heif) hoặc định dạng lạ
            try:
                from PIL import ImageOps
                with Image.open(path) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    img = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
            except Exception:  # noqa: BLE001
                img = None
    if img is None:
        return None
    if max_side:
        h, w = img.shape[:2]
        s = max_side / max(h, w)
        if s < 1:
            img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    return img


def _jpg(img, q=85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes() if ok else b""


def lap_var(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def dhash(gray: np.ndarray) -> str:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return f"{v:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def head_pose(r) -> tuple[float, float]:
    """Hướng mặt từ 5 điểm mốc của YuNet (mắt phải, mắt trái, mũi, hai khoé miệng).
    yaw: vị trí mũi dọc theo trục hai mắt (0,5 = nhìn thẳng; lệch xa 0,5 = quay ngang).
    vert: khoảng mắt→miệng chia khoảng cách hai mắt (mặt nghiêng hẳn thì hai mắt sát nhau nên số này tăng vọt)."""
    er, el, no = np.asarray(r[4:6], float), np.asarray(r[6:8], float), np.asarray(r[8:10], float)
    mo = (np.asarray(r[10:12], float) + np.asarray(r[12:14], float)) / 2
    span = float(np.linalg.norm(el - er))
    if span < 1e-6:
        return -1.0, -1.0
    yaw = float(np.dot(no - er, (el - er) / span) / span)
    vert = float(np.linalg.norm(mo - (er + el) / 2) / span)
    return yaw, vert


def eye_aspect_ratio(p6: np.ndarray) -> float:
    """EAR từ 6 điểm mốc của một mắt (kiểu 68 điểm dlib/LBF)."""
    d = lambda i, j: float(np.linalg.norm(p6[i] - p6[j]))  # noqa: E731
    horiz = d(0, 3)
    return (d(1, 5) + d(2, 4)) / (2 * horiz) if horiz > 1e-6 else -1.0


class Analyzer:
    def __init__(self):
        self._local = threading.local()
        self._lbf_lock = threading.Lock()
        self._lbf = None
        self.has_eyes = False
        if models.have("lbfmodel.yaml") and hasattr(cv2, "face"):
            try:
                fm = cv2.face.createFacemarkLBF()
                fm.loadModel(str(models.path("lbfmodel.yaml")))
                self._lbf = fm
                self.has_eyes = True
            except Exception:  # noqa: BLE001
                self._lbf = None

    # --- model theo thread (YuNet / SFace không an toàn đa luồng khi dùng chung) ---
    def _det(self, w, h):
        d = getattr(self._local, "det", None)
        if d is None:
            d = cv2.FaceDetectorYN.create(str(models.path("yunet.onnx")), "", (w, h), 0.85, 0.3, 5000)
            self._local.det = d
        d.setInputSize((w, h))
        return d

    def _rec(self):
        r = getattr(self._local, "rec", None)
        if r is None:
            r = cv2.FaceRecognizerSF.create(str(models.path("sface.onnx")), "")
            self._local.rec = r
        return r

    def _ear(self, img, rects):
        """EAR nhỏ nhất của từng khuôn mặt (trung bình hai mắt); -1 nếu không đo được."""
        if not self._lbf or not rects:
            return [-1.0] * len(rects)
        try:
            with self._lbf_lock:
                ok, lms = self._lbf.fit(img, np.array(rects, dtype=np.int32))
            if not ok:
                return [-1.0] * len(rects)
            out = []
            for lm in lms:
                pts = np.asarray(lm).reshape(-1, 2)
                if pts.shape[0] < 48:
                    out.append(-1.0)
                    continue
                r, l = eye_aspect_ratio(pts[36:42]), eye_aspect_ratio(pts[42:48])
                out.append((r + l) / 2 if r > 0 and l > 0 else -1.0)
            return out
        except Exception:  # noqa: BLE001
            return [-1.0] * len(rects)

    def prepare(self, path: str) -> dict:
        """Pha 1 (I/O): đọc ảnh xem trước, tạo thumbnail + ảnh cache 1600px. Rất nhanh."""
        ext = Path(path).suffix.lower()
        if ext in RAW_EXT:
            try:
                img, taken = read_raw_preview(path)
            except Exception:  # noqa: BLE001
                img, taken = None, None
            if img is None:
                img = _read_raw(path)
            ow = oh = 0
        else:
            ow, oh, taken = read_meta(path)
            img = load_bgr(path, ANALYSIS_SIDE, (ow, oh))
        if img is None:
            raise ValueError("không đọc được ảnh")
        h, w = img.shape[:2]
        if not ow:  # RAW: kích thước theo ảnh xem trước
            ow, oh = w, h
        s = ANALYSIS_SIDE / max(h, w)
        if s < 1:
            img = cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
            h, w = img.shape[:2]
        th = THUMB_SIDE / max(h, w)
        thumb = cv2.resize(img, (max(1, round(w * th)), max(1, round(h * th))), interpolation=cv2.INTER_AREA) if th < 1 else img
        return dict(img=img, w=ow, h=oh, taken=taken, thumb=_jpg(thumb, 85), prev=_jpg(img, 88))

    def quick_thumb(self, path: str):
        """Giai đoạn A: thumbnail gần như tức thì từ JPEG nhỏ nhất trong file RAW (đọc ~10 KB)."""
        img, taken = read_raw_preview(path, thumb=True)
        if img is None:
            return None
        h, w = img.shape[:2]
        th = THUMB_SIDE / max(h, w)
        if th < 1:
            img = cv2.resize(img, (max(1, round(w * th)), max(1, round(h * th))), interpolation=cv2.INTER_AREA)
        return dict(w=w, h=h, taken=taken, thumb=_jpg(img, 85))

    def analyze(self, path: str) -> dict:
        p = self.prepare(path)
        r = self.analyze_image(p["img"], p["w"], p["h"])
        r.update(taken=p["taken"], thumb=p["thumb"])
        return r

    def analyze_image(self, img, ow: int, oh: int) -> dict:
        """Pha 2 (CPU): độ nét, phơi sáng, dHash, khuôn mặt.
        Tìm mặt trên ảnh thu nhỏ cho nhanh, còn nhận diện và đo mắt dùng ảnh lớn cho chính xác."""
        h, w = img.shape[:2]
        sd = min(1.0, DETECT_SIDE / max(h, w))
        small = cv2.resize(img, (round(w * sd), round(h * sd)), interpolation=cv2.INTER_LINEAR) if sd < 1 else img
        ref = min(1.0, FACE_REF_SIDE / max(h, w))   # các ngưỡng cỡ mặt tính theo ảnh cạnh dài 1280px
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        s = SHARP_SIDE / max(h, w)
        g1 = cv2.resize(gray, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else gray
        sharp = lap_var(g1)
        lum = float(g1.mean() / 255.0)
        lo = float((g1 <= 8).mean())
        hi = float((g1 >= 247).mean())
        dh = dhash(gray)

        # ---- khuôn mặt ----
        det = self._det(small.shape[1], small.shape[0])
        _, rows = det.detect(small)
        faces = []
        if rows is not None:
            rec = self._rec()
            rows = rows.copy()
            rows[:, :14] /= sd   # đổi toạ độ về ảnh lớn
            kept = [r for r in rows if r[14] >= 0.85 and min(r[2], r[3]) * ref >= MIN_FACE_PX]
            kept.sort(key=lambda r: -(r[2] * r[3]))
            rects = []
            for r in kept:
                x, y, fw, fh = r[:4]
                x0, y0 = max(0, int(x)), max(0, int(y))
                x1, y1 = min(w, int(x + fw)), min(h, int(y + fh))
                rects.append((x0, y0, max(1, x1 - x0), max(1, y1 - y0)))
            ears = self._ear(img, [rc for rc, r in zip(rects, kept) if rc[2] * ref >= EAR_MIN_FACE_PX])
            ear_iter = iter(ears)
            for r, rc in zip(kept, rects):
                px = int(rc[2] / w * ow)
                emb = None
                if px >= MIN_ID_PX:   # mặt nhỏ hơn không dùng để gom người nên không tốn công nhận diện
                    try:
                        emb = rec.feature(rec.alignCrop(img, r)).flatten().astype(np.float32)
                        emb /= (np.linalg.norm(emb) + 1e-9)
                    except Exception:  # noqa: BLE001
                        continue
                ear = -1.0
                if rc[2] * ref >= EAR_MIN_FACE_PX:
                    ear = next(ear_iter)
                    # chỉ tin EAR khi mặt nhìn thẳng (mũi nằm giữa hai mắt)
                    ex_r, ex_l, nx = r[4], r[6], r[8]
                    span = abs(ex_l - ex_r)
                    if span > 1e-6 and not (0.3 <= abs(nx - ex_r) / span <= 0.7):
                        ear = -1.0
                yaw, vert = head_pose(r)
                x0, y0, fw, fh = rc
                side = int(max(fw, fh) * 1.5)
                cx, cy = x0 + fw // 2, y0 + fh // 2
                a0, b0 = max(0, cx - side // 2), max(0, cy - side // 2)
                crop = img[b0:min(h, b0 + side), a0:min(w, a0 + side)]
                gcrop = gray[y0:y0 + fh, x0:x0 + fw]
                fsh = lap_var(cv2.resize(gcrop, (96, 96), interpolation=cv2.INTER_AREA)) if gcrop.size else 0.0
                faces.append(dict(
                    fx=x0 / w, fy=y0 / h, fw=fw / w, fh=fh / h, det=float(r[14]),
                    px=px, ear=float(ear), sharp=fsh, yaw=yaw, vert=vert,
                    emb=emb.tobytes() if emb is not None else b"", crop=_jpg(cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA), 88) if crop.size else b"",
                ))

        ears = [f["ear"] for f in faces if f["ear"] >= 0]
        return dict(
            w=ow, h=oh, sharp=sharp,
            fsharp=faces[0]["sharp"] if faces else 0.0,  # mặt lớn nhất
            lum=lum, lo=lo, hi=hi, dhash=dh, nfaces=len(faces),
            ear_min=min(ears) if ears else -1.0, faces=faces,
        )
