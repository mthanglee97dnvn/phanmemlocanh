"""Kiểm tra key offline: key do app KeyGen ký Ed25519, phần mềm chỉ giữ khóa công khai nên không tự tạo được key."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import sys
import re
import secrets

from .db import HOME
from .license_pub import PUB_HEX
try:
    from .license_pub import SALES_PUB_HEX
except ImportError:
    SALES_PUB_HEX = ""

EPOCH = dt.date(2024, 1, 1)
PERMANENT = 0xFFFF
FILE = HOME / "license.json"
REVOKED_FILE = HOME / "revoked.txt"   # bản lưu gần nhất của danh sách key bị thu hồi (dùng khi mất mạng)
REVOKE_EVERY = 6 * 3600
GRANT_EVERY = 15 * 60   # mỗi 15 phút kiểm tra danh sách key vĩnh viễn đã cấp (sau khi khách thanh toán)


def _raw_key(text: str) -> bytes | None:
    t = re.sub(r"[^A-Za-z2-7]", "", text or "").upper()
    if t.startswith("MTCC"):
        t = t[4:]
    try:
        raw = base64.b32decode(t + "=" * (-len(t) % 8))
    except ValueError:
        return None
    return raw if len(raw) == 78 else None


def key_id(text: str) -> str:
    """Mã nhận diện của một key (16 ký tự hex). Danh sách thu hồi chỉ chứa mã này, không chứa key."""
    raw = _raw_key(text)
    return hashlib.sha256(b"MTCC-REVOKE|" + raw).hexdigest()[:16] if raw else ""


def _revoked_ids() -> set[str]:
    try:
        return {ln.strip().lower() for ln in REVOKED_FILE.read_text(encoding="utf-8").splitlines()
                if re.fullmatch(r"[0-9a-fA-F]{16}", ln.strip())}
    except OSError:
        return set()

# ---- Ed25519 (RFC 8032), phần xác minh, thuần Python để không thêm thư viện vào gói cài
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x):
    return pow(x, _P - 2, _P)


def _xrecover(y):
    xx = (y * y - 1) * _inv(_D * y * y + 1) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _I % _P
    if (x * x - xx) % _P:
        return None
    return x


_By = 4 * _inv(5) % _P
_Bx = _xrecover(_By)
if _Bx % 2:
    _Bx = _P - _Bx
_B = (_Bx, _By, 1, _Bx * _By % _P)
_ZERO = (0, 1, 1, 0)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(p, n):
    q = _ZERO
    while n:
        if n & 1:
            q = _add(q, p)
        p = _add(p, p)
        n >>= 1
    return q


def _decode(b):
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x = _xrecover(y)
    if x is None or (x == 0 and sign):
        return None
    if x & 1 != sign:
        x = _P - x
    return (x, y, 1, x * y % _P)


def _same(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def ed25519_verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(pub) != 32 or len(sig) != 64:
        return False
    A, R = _decode(pub), _decode(sig[:32])
    s = int.from_bytes(sig[32:], "little")
    if A is None or R is None or s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _L
    return _same(_mul(_B, s), _add(R, _mul(A, h)))


# ---- mã máy
def _guid() -> str:
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
        except OSError:
            pass
    if sys.platform == "darwin":   # mã phần cứng của máy Mac (giữ nguyên khi cài lại app / macOS)
        try:
            import subprocess
            out = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True,
                                 text=True, timeout=5).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            if m:
                return m.group(1)
        except Exception:  # noqa: BLE001
            pass
    f = HOME / "machine.id"
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        v = secrets.token_hex(16)
        HOME.mkdir(parents=True, exist_ok=True)
        f.write_text(v, encoding="utf-8")
        return v


def machine_bytes() -> bytes:
    return hashlib.sha256(("MTCC|" + _guid().lower()).encode()).digest()[:8]


def machine_code() -> str:
    t = base64.b32encode(machine_bytes()).decode().rstrip("=")
    return f"{t[:4]}-{t[4:8]}-{t[8:]}"


# ---- key
def today_num() -> int:
    return (dt.date.today() - EPOCH).days


def _date(n: int) -> str:
    return (EPOCH + dt.timedelta(days=n)).strftime("%d/%m/%Y")


def parse(text: str) -> dict:
    """Trả dict(ok, reason, ...). Không đọc file, không ghi gì."""
    _pubs = [p for p in (PUB_HEX, SALES_PUB_HEX) if re.fullmatch(r"[0-9a-f]{64}", p or "")]
    if not _pubs:
        return dict(ok=False, reason="Bản cài này chưa có khóa công khai, không kích hoạt được.")
    t = re.sub(r"[^A-Za-z2-7]", "", text or "").upper()
    if t.startswith("MTCC"):
        t = t[4:]
    try:
        raw = base64.b32decode(t + "=" * (-len(t) % 8))
    except ValueError:
        return dict(ok=False, reason="Key không đúng định dạng. Hãy dán lại toàn bộ key.")
    if len(raw) != 78:
        return dict(ok=False, reason="Key không đúng định dạng. Hãy dán lại toàn bộ key.")
    body, sig = raw[:14], raw[14:]
    if body[0] != 1 or not any(ed25519_verify(bytes.fromhex(p), b"MTCC1" + body, sig) for p in _pubs):
        return dict(ok=False, reason="Key không hợp lệ.")
    issued = int.from_bytes(body[2:4], "big")
    exp = int.from_bytes(body[4:6], "big")
    mach = body[6:14]
    if mach != b"\0" * 8 and mach != machine_bytes():
        return dict(ok=False, reason="Key này dành cho máy khác. Hãy gửi đúng mã máy để nhận key mới.")
    perm = exp == PERMANENT
    left = None if perm else exp - today_num()
    if not perm and left < 0:
        return dict(ok=False, reason=f"Key đã hết hạn từ ngày {_date(exp)}.", expired=True)
    return dict(ok=True, reason="", permanent=perm, expires="" if perm else _date(exp), days_left=left,
                issued=_date(issued), any_machine=mach == b"\0" * 8)


class License:
    def __init__(self):
        self.state = dict(ok=False, reason="")
        self.reload()

    def _read(self):
        try:
            return json.loads(FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, d):
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        tmp.replace(FILE)

    def reload(self):
        d = self._read()
        if not d.get("key"):
            self.state = dict(ok=False, reason="")
            return self.state
        st = parse(d["key"])
        if st.get("ok") and key_id(d["key"]) in _revoked_ids():
            st = dict(ok=False, reason="Key này đã bị thu hồi. Hãy liên hệ MTHANGLEE STUDIO để được cấp key mới.", revoked=True)
        now = today_num()
        if st.get("ok") and not st["permanent"]:
            if now < int(d.get("seen", 0)) - 1:   # chống vặn lùi đồng hồ để kéo dài key có hạn
                st = dict(ok=False, reason="Đồng hồ máy đang bị lùi. Hãy chỉnh lại ngày giờ rồi mở lại.")
            elif now > int(d.get("seen", 0)):
                d["seen"] = now
                self._write(d)
        self.state = st
        return st

    def ok(self) -> bool:
        s = self.state
        if s.get("ok") and not s.get("permanent") and today_num() != self._day0:
            self._day0 = today_num()   # sang ngày mới: kiểm tra lại hạn dùng
            return self.reload().get("ok", False)
        return bool(s.get("ok"))

    _day0 = 0

    def info(self) -> dict:
        s = self.reload()
        self._day0 = today_num()
        return dict(s, machine=machine_code(), has_pub=bool(re.fullmatch(r"[0-9a-f]{64}", PUB_HEX or "") or re.fullmatch(r"[0-9a-f]{64}", SALES_PUB_HEX or "")))

    def activate(self, key: str) -> dict:
        st = parse(key)
        if st.get("ok") and key_id(key) in _revoked_ids():
            return dict(ok=False, reason="Key này đã bị thu hồi. Hãy liên hệ MTHANGLEE STUDIO để được cấp key mới.")
        if st.get("ok"):
            self._write(dict(key=key.strip(), seen=today_num()))
            self.reload()
        return st

    def remove(self):
        try:
            FILE.unlink()
        except OSError:
            pass
        self.reload()


def fetch_grants(repo: str, lic) -> bool:
    """Tải danh sách key vĩnh viễn đã cấp (grants.json: {mã máy: key}). Nếu có key cho máy này và app
    chưa phải bản vĩnh viễn, tự kích hoạt. Trả True nếu vừa chuyển sang vĩnh viễn. Không gửi gì lên mạng."""
    if not repo or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return False
    try:
        if lic.state.get("ok") and lic.state.get("permanent"):
            return False   # đã vĩnh viễn, khỏi cần
    except Exception:  # noqa: BLE001
        pass
    url = f"https://github.com/{repo}/releases/download/license/grants.json"
    try:
        import json as _json
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "MThanglee-CullCollage"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = _json.loads(r.read(1 << 20).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001  mất mạng / chưa có danh sách
        return False
    if not isinstance(data, dict):
        return False
    me = machine_code()
    key = data.get(me) or data.get(me.replace("-", ""))
    if not isinstance(key, str) or not key.strip():
        return False
    st = parse(key)   # chỉ nhận key hợp lệ: đúng chữ ký, đúng máy này
    if not st.get("ok") or not st.get("permanent"):
        return False
    lic.activate(key)   # ghi license.json + reload
    return bool(lic.state.get("ok") and lic.state.get("permanent"))


def start_grants(repo: str, lic):
    """Định kỳ kiểm tra key vĩnh viễn đã cấp cho máy này rồi tự kích hoạt."""
    def loop():
        import time
        while True:
            try:
                fetch_grants(repo, lic)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(GRANT_EVERY)
    import threading
    threading.Thread(target=loop, daemon=True).start()


def start_revocation(repo: str):
    """Định kỳ tải danh sách key bị thu hồi từ kho phát hành (chỉ mã nhận diện, không gửi gì lên mạng).
    Mất mạng thì dùng bản lưu gần nhất, không khoá app."""
    if not repo or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return
    url = f"https://github.com/{repo}/releases/download/license/revoked.txt"

    def loop():
        import threading as _t  # noqa: F401
        import time
        import urllib.request
        while True:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "MThanglee-CullCollage"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    txt = r.read(1 << 20).decode("utf-8", "replace")
                ids = [ln.strip().lower() for ln in txt.splitlines() if re.fullmatch(r"[0-9a-fA-F]{16}", ln.strip())]
                HOME.mkdir(parents=True, exist_ok=True)
                REVOKED_FILE.write_text("\n".join(ids) + "\n", encoding="utf-8")
            except Exception:  # noqa: BLE001  mất mạng / chưa có danh sách: giữ bản cũ
                pass
            time.sleep(REVOKE_EVERY)
    import threading
    threading.Thread(target=loop, daemon=True).start()
