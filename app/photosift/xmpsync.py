"""File .xmp nằm cạnh ảnh gốc: tìm, gộp (không ghi đè dữ liệu Photo Mechanic/Lightroom), đọc, ghi an toàn.

Chỉ đụng tới Rating (sao 1–5, -1 = loại) và Label (nhãn màu) của không gian tên xmp (http://ns.adobe.com/xap/1.0/,
tiền tố thường là xmp:, file Adobe/Photo Mechanic cũ dùng xap:); mọi byte khác của file giữ nguyên.
"""
from __future__ import annotations

import os
import re
import uuid

XMP_NS = b"http://ns.adobe.com/xap/1.0/"
LABEL_OUT = {"red": "Red", "yellow": "Yellow", "green": "Green", "blue": "Blue", "purple": "Purple"}
LABEL_IN = {v.lower(): k for k, v in LABEL_OUT.items()}

_NSDECL = re.compile(rb"""xmlns:([A-Za-z_][\w.-]*)\s*=\s*(["'])http://ns\.adobe\.com/xap/1\.0/\2""")
_DESC = re.compile(rb"<rdf:Description\b[^>]*?(/?)>", re.S)


def _px(data: bytes) -> bytes:
    """Tiền tố đang gắn với không gian tên xmp trong file (xmp, xap…); không có → b'xmp'."""
    m = _NSDECL.search(data)
    return m.group(1) if m else b"xmp"


def _rx(prefixes, prop):
    alt = b"|".join(re.escape(p) for p in prefixes)
    attr = re.compile(rb"(\s)(" + alt + rb"):" + prop + rb"""\s*=\s*(["'])(.*?)\3""", re.S)
    elem = re.compile(rb"<(" + alt + rb"):" + prop + rb"(?:\s[^>]*)?>(.*?)</\1:" + prop + rb"\s*>", re.S)
    empty = re.compile(rb"\s*<(" + alt + rb"):" + prop + rb"(?:\s[^>]*)?/>")
    return attr, elem, empty


def _prefixes(data: bytes):
    found = [m.group(1) for m in _NSDECL.finditer(data)]
    return list(dict.fromkeys(found + [b"xmp", b"xap"]))


def _get(data: bytes, prop: bytes):
    """Giá trị thô (bytes) của thuộc tính/thẻ prop, hoặc None nếu không có."""
    attr, elem, _ = _rx(_prefixes(data), prop)
    m = attr.search(data)
    if m:
        return m.group(4)
    m = elem.search(data)
    return m.group(2) if m else None


def _xmp_parse(data: bytes):
    """Sao trong khối XMP: -1..5 hoặc None."""
    v = _get(data, b"Rating")
    if v is None:
        return None
    try:
        f = float(v.strip())
    except ValueError:
        return None
    return -1 if f < 0 else min(5, int(round(f)))


def _label_parse(data: bytes):
    """Nhãn app: '' khi .xmp không có nhãn (đã bỏ nhãn), 'red'… khi là nhãn màu, None khi tên lạ (vd 'Winner')."""
    raw = _get(data, b"Label")
    if raw is None:
        return ""
    s = raw.decode("utf-8", "replace").strip().lower()
    if not s:
        return ""
    return LABEL_IN.get(s)


def dir_names(d: str) -> dict:
    """{tên viết thường: tên thật} của các file .xmp trong thư mục (một lần liệt kê thay cho nhiều lần isfile qua NAS)."""
    out = {}
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.name.lower().endswith(".xmp"):
                    out[e.name.lower()] = e.name
    except OSError:
        pass
    return out


def sidecar(img_path: str, names: dict | None = None) -> tuple[str, bool]:
    """(.xmp nên dùng, đã có chưa). Dùng đúng tên thật của file sẵn có (IMG.XMP của Photo Mechanic giữ nguyên chữ hoa);
    chưa có → <tên>.xmp. names: kết quả dir_names() của thư mục (đỡ liệt kê lại)."""
    d = os.path.dirname(img_path)
    base = os.path.splitext(os.path.basename(img_path))[0]
    if names is None:
        names = dir_names(d)
    real = names.get((base + ".xmp").lower())
    if real:
        return os.path.join(d, real), True
    return os.path.join(d, base + ".xmp"), False


def _new(rating: int, label: str) -> bytes:
    lab = f' xmp:Label="{LABEL_OUT[label]}"' if label in LABEL_OUT else ""
    return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
            '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            f'<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="{int(rating)}"{lab}/>'
            '</rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>').encode("utf-8")


def _insert_attr(data: bytes, px: bytes, name: bytes, value: bytes) -> bytes:
    """Thêm px:name="value" vào thẻ <rdf:Description> khai báo không gian tên xmp (không có thì thẻ đầu tiên,
    kèm khai báo xmlns ngay trên thẻ đó — để XML luôn hợp lệ dù file có nhiều khối Description)."""
    descs = list(_DESC.finditer(data))
    pick = next((m for m in descs if _NSDECL.search(m.group(0))), descs[0])
    tag = pick.group(0)
    decl = b"" if _NSDECL.search(tag) else b' xmlns:' + px + b'="' + XMP_NS + b'"'
    close = len(tag) - (2 if pick.group(1) else 1)
    new_tag = tag[:close].rstrip() + decl + b" " + px + b":" + name + b'="' + value + b'"' + tag[close:]
    return data[:pick.start()] + new_tag + data[pick.end():]


def _set(data: bytes, prop: bytes, value: bytes | None) -> bytes:
    """Đặt (value) hoặc xoá (None) thuộc tính/thẻ prop."""
    attr, elem, empty = _rx(_prefixes(data), prop)
    if attr.search(data):
        if value is None:
            return attr.sub(b"", data, count=1)
        return attr.sub(lambda m: m.group(1) + m.group(2) + b":" + prop + b"=" + m.group(3) + value + m.group(3), data, count=1)
    if elem.search(data):
        if value is None:
            return re.sub(rb"\s*" + elem.pattern, b"", data, count=1, flags=re.S)
        return elem.sub(lambda m: m.group(0)[:m.start(2) - m.start(0)] + value + m.group(0)[m.end(2) - m.start(0):], data, count=1)
    data = empty.sub(b"", data, count=1)
    if value is None:
        return data
    return _insert_attr(data, _px(data), prop, value)


def merge_xmp(existing: bytes | None, rating: int, label: str) -> bytes | None:
    """Ghi sao + nhãn vào .xmp. existing None và không có gì để ghi (0 sao, không nhãn) → None (không tạo file).
    File có sẵn nhưng hỏng/rỗng (không có <rdf:Description>) → dựng file mới."""
    rating = int(rating)
    if existing is None:
        if rating == 0 and not label:
            return None
        return _new(rating, label)
    if not _DESC.search(existing):
        return _new(rating, label)
    data = _set(existing, b"Rating", str(rating).encode())
    out = LABEL_OUT.get(label)
    return _set(data, b"Label", out.encode() if out else None)


def _read_file(p: str) -> bytes:
    with open(p, "rb") as f:
        return f.read(1 << 20)


def read_sidecar(img_path: str, names: dict | None = None) -> tuple[int | None, str | None, float | None]:
    """(sao, nhãn app — '' nếu không nhãn, None nếu tên lạ —, mtime) của .xmp đi kèm; không có file → (None, None, None).
    Không bao giờ raise."""
    try:
        p, ok = sidecar(img_path, names)
        if not ok:
            return None, None, None
        mt = os.stat(p).st_mtime
        data = _read_file(p)
        return _xmp_parse(data), _label_parse(data), mt
    except Exception:  # noqa: BLE001
        return None, None, None


def write_atomic(path: str, data: bytes) -> None:
    """Ghi ra file tạm (tên riêng cho từng lần ghi — hai máy/hai luồng không giẫm nhau) rồi đổi tên:
    mất mạng giữa chừng không để lại .xmp hỏng."""
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
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
