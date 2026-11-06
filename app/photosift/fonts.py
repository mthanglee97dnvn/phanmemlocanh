"""Danh sách font đã cài trên máy có đủ chữ tiếng Việt, và font giao diện người dùng chọn.

Chỉ đọc bảng cmap/name/OS2 của file font (không cần thư viện ngoài). Kết quả lưu cache theo đường dẫn,
kích thước và thời gian sửa file nên lần sau mở gần như tức thì.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import threading
from pathlib import Path

from .db import HOME

VI = ("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")
NEED = {ord(c) for c in VI + VI.upper()}
CACHE = HOME / "fonts_cache.json"
UI = HOME / "ui.json"
_lock = threading.Lock()
_result: list | None = None


def font_dirs():
    if os.name == "nt":
        win = os.environ.get("WINDIR", r"C:\Windows")
        yield Path(win) / "Fonts"
        la = os.environ.get("LOCALAPPDATA")
        if la:
            yield Path(la) / "Microsoft" / "Windows" / "Fonts"
    elif sys.platform == "darwin":
        yield from (Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts")
    else:
        yield from (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts", Path.home() / ".local/share/fonts")


def _tables(f, off):
    f.seek(off)
    _, n = struct.unpack(">IH", f.read(6))
    f.seek(off + 12)
    t = {}
    for _ in range(n):
        tag, _, o, ln = struct.unpack(">4sIII", f.read(16))
        t[tag] = (o, ln)
    return t


def _cmap(f, o, ln) -> set:
    f.seek(o)
    d = f.read(min(ln, 4 << 20))
    _, n = struct.unpack_from(">HH", d)
    best = None
    for i in range(n):
        pid, eid, so = struct.unpack_from(">HHI", d, 4 + 8 * i)
        fmt = struct.unpack_from(">H", d, so)[0]
        if fmt == 12 and (pid, eid) in ((3, 10), (0, 4), (0, 6)):
            best = (12, so)
        elif fmt == 4 and (pid, eid) in ((3, 1), (0, 3), (0, 4), (0, 1)) and not best:
            best = (4, so)
    have = set()
    if not best:
        return have
    fmt, so = best
    if fmt == 4:
        seg = struct.unpack_from(">H", d, so + 6)[0] // 2
        ends = struct.unpack_from(f">{seg}H", d, so + 14)
        starts = struct.unpack_from(f">{seg}H", d, so + 16 + 2 * seg)
        for a, b in zip(starts, ends):
            have.update(c for c in NEED if a <= c <= b)   # bỏ qua glyph 0 hiếm gặp: đủ chính xác để lọc
    else:
        ng = struct.unpack_from(">I", d, so + 12)[0]
        for i in range(ng):
            a, b, _ = struct.unpack_from(">III", d, so + 16 + 12 * i)
            have.update(c for c in NEED if a <= c <= b)
    return have


def _names(f, o, ln):
    f.seek(o)
    d = f.read(ln)
    _, n, so = struct.unpack_from(">HHH", d)
    got = {}
    for i in range(n):
        pid, eid, lang, nid, l, off = struct.unpack_from(">HHHHHH", d, 6 + 12 * i)
        if nid not in (1, 16) or pid != 3 or eid not in (0, 1):
            continue
        s = d[so + off: so + off + l].decode("utf-16-be", "ignore").strip()
        if s and (nid not in got or lang == 0x409):
            got[nid] = s
    return got.get(16) or got.get(1)


def read_font(path: Path):
    """[(họ font, đủ tiếng Việt)] cho mỗi font trong file (.ttc có nhiều font)."""
    out = []
    with open(path, "rb") as f:
        head = f.read(12)
        offs = [0]
        if head[:4] == b"ttcf":
            n = struct.unpack(">I", head[8:12])[0]
            offs = list(struct.unpack(f">{n}I", f.read(4 * n)))
        for off in offs:
            t = _tables(f, off)
            if b"cmap" not in t or b"name" not in t:
                continue
            fam = _names(f, *t[b"name"])
            if fam:
                out.append((fam, NEED <= _cmap(f, *t[b"cmap"])))
    return out


def scan() -> list:
    global _result
    with _lock:
        if _result is not None:
            return _result
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        fresh, fams = {}, {}
        for d in font_dirs():
            if not d.is_dir():
                continue
            for p in d.rglob("*"):
                if p.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                    continue
                try:
                    st = p.stat()
                    key = f"{p}|{st.st_size}|{int(st.st_mtime)}"
                    r = cache.get(key)
                    if r is None:
                        r = read_font(p)
                    fresh[key] = r
                except Exception:  # noqa: BLE001  một file font hỏng không được làm hỏng cả danh sách
                    continue
                for fam, vi in r:
                    if not fam.startswith((".", "@")):
                        fams[fam] = fams.get(fam, False) or vi
        try:
            HOME.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(fresh), encoding="utf-8")
        except OSError:
            pass
        _result = sorted((dict(family=k, vi=v) for k, v in fams.items()), key=lambda x: x["family"].lower())
        return _result


def get_ui() -> dict:
    try:
        d = json.loads(UI.read_text(encoding="utf-8"))
        return dict(font=str(d.get("font") or ""))
    except (OSError, ValueError):
        return dict(font="")


def set_ui(font: str) -> dict:
    font = str(font or "").strip()[:120]
    if font and font not in {x["family"] for x in scan()}:
        raise ValueError("Không thấy font này trên máy")
    HOME.mkdir(parents=True, exist_ok=True)
    UI.write_text(json.dumps(dict(font=font), ensure_ascii=False), encoding="utf-8")
    return get_ui()


def ui_css() -> str:
    f = get_ui()["font"].replace("\\", "").replace('"', "")
    if not f:
        return "/* font mặc định */\n"
    stack = f'"{f}","Segoe UI Variable Text","Segoe UI",system-ui,sans-serif'
    return (f":root{{--ui-font:{stack};--ui:{stack};--display:{stack}}}\n"
            "html body,button,input,select,textarea,dialog,option{font-family:var(--ui-font)}\n")
