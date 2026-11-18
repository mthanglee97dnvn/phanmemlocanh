"""File .xmp nằm cạnh ảnh gốc: tìm, gộp (không ghi đè dữ liệu Photo Mechanic/Lightroom), đọc, ghi an toàn.

Chỉ đụng tới xmp:Rating (sao 1–5, -1 = loại) và xmp:Label (nhãn màu); mọi byte khác của file giữ nguyên.
"""
from __future__ import annotations

import os
import re

XMP_NS = b"http://ns.adobe.com/xap/1.0/"
LABEL_OUT = {"red": "Red", "yellow": "Yellow", "green": "Green", "blue": "Blue", "purple": "Purple"}
LABEL_IN = {v.lower(): k for k, v in LABEL_OUT.items()}

_R_ATTR = re.compile(rb"""xmp:Rating\s*=\s*(["'])\s*(-?\d+(?:\.\d+)?)\s*\1""")
_R_ELEM = re.compile(rb"<xmp:Rating>\s*(-?\d+(?:\.\d+)?)\s*</xmp:Rating>")
_L_ATTR = re.compile(rb"""\s*xmp:Label\s*=\s*(["'])(.*?)\1""", re.S)
_L_ELEM = re.compile(rb"<xmp:Label>(.*?)</xmp:Label>", re.S)
_L_ELEM_EMPTY = re.compile(rb"\s*<xmp:Label\s*/>")
_DESC = re.compile(rb"<rdf:Description\b")


def _xmp_parse(data: bytes):
    """Sao trong khối XMP: -1..5 hoặc None."""
    m = _R_ATTR.search(data)
    v = m.group(2) if m else None
    if v is None:
        m = _R_ELEM.search(data)
        v = m.group(1) if m else None
    if v is None:
        return None
    f = float(v)
    return -1 if f < 0 else min(5, int(round(f)))


def _label_parse(data: bytes):
    """Nhãn app ('red'…) từ xmp:Label; thiếu hoặc tên lạ (vd 'Winner' của Photo Mechanic) → None."""
    m = _L_ATTR.search(data)
    raw = m.group(2) if m else None
    if raw is None:
        m = _L_ELEM.search(data)
        raw = m.group(1) if m else None
    if raw is None:
        return None
    return LABEL_IN.get(raw.decode("utf-8", "replace").strip().lower())


def sidecar(img_path: str) -> tuple[str, bool]:
    """(.xmp nên dùng, đã có chưa). Ưu tiên file sẵn có (IMG.XMP của Photo Mechanic, IMG.xmp); không có → IMG.xmp."""
    base = os.path.splitext(img_path)[0]
    for cand in (base + ".xmp", base + ".XMP", base + ".Xmp"):
        if os.path.isfile(cand):
            return cand, True
    return base + ".xmp", False


def _new(rating: int, label: str) -> bytes:
    lab = f' xmp:Label="{LABEL_OUT[label]}"' if label in LABEL_OUT else ""
    return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            f'<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="{int(rating)}"{lab}/>'
            '</rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>').encode("utf-8")


def _insert_attr(data: bytes, attr: bytes) -> bytes:
    """Chèn thuộc tính vào thẻ <rdf:Description đầu tiên (thêm xmlns:xmp nếu thiếu)."""
    m = _DESC.search(data)
    if not m:
        return data
    end = m.end()
    if XMP_NS not in data:
        attr = b' xmlns:xmp="' + XMP_NS + b'"' + attr
    return data[:end] + attr + data[end:]


def merge_xmp(existing: bytes | None, rating: int, label: str) -> bytes | None:
    """Ghi sao + nhãn vào .xmp. existing None và không có gì để ghi (0 sao, không nhãn) → None (không tạo file)."""
    rating = int(rating)
    if existing is None:
        if rating == 0 and not label:
            return None
        return _new(rating, label)
    data = existing
    rv = str(rating).encode()
    if _R_ATTR.search(data):
        data = _R_ATTR.sub(lambda m: b"xmp:Rating=" + m.group(1) + rv + m.group(1), data, count=1)
    elif _R_ELEM.search(data):
        data = _R_ELEM.sub(b"<xmp:Rating>" + rv + b"</xmp:Rating>", data, count=1)
    else:
        data = _insert_attr(data, b' xmp:Rating="' + rv + b'"')
    out = LABEL_OUT.get(label, "").encode()
    if _L_ATTR.search(data):
        data = _L_ATTR.sub((lambda m: b" xmp:Label=" + m.group(1) + out + m.group(1)) if out else (lambda m: b""), data, count=1)
    elif _L_ELEM.search(data):
        data = _L_ELEM.sub(b"<xmp:Label>" + out + b"</xmp:Label>", data, count=1) if out else \
            re.sub(rb"\s*<xmp:Label>.*?</xmp:Label>", b"", data, count=1, flags=re.S)
    elif out:
        data = _L_ELEM_EMPTY.sub(b"", data, count=1)
        data = _insert_attr(data, b' xmp:Label="' + out + b'"')
    return data


def read_sidecar(img_path: str) -> tuple[int | None, str | None, float | None]:
    """(sao, nhãn app hoặc None, mtime) của .xmp đi kèm; không có file → (None, None, None). Không bao giờ raise."""
    try:
        p, ok = sidecar(img_path)
        if not ok:
            return None, None, None
        mt = os.stat(p).st_mtime
        with open(p, "rb") as f:
            data = f.read(1 << 20)
        return _xmp_parse(data), _label_parse(data), mt
    except Exception:  # noqa: BLE001
        return None, None, None


def write_atomic(path: str, data: bytes) -> None:
    """Ghi ra file tạm cùng thư mục rồi đổi tên — mất mạng giữa chừng không để lại .xmp hỏng."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
