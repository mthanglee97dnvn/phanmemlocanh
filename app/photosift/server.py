"""Server HTTP cục bộ (chỉ lắng nghe 127.0.0.1) phục vụ giao diện web + API."""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import string
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2

from . import models
from .update import Updater
from . import fonts
from .analyzer import ALL_EXT, _jpg, load_bgr, read_meta
from .library import COVERS, FACES, PREVIEWS, THUMBS, Library
from .license import License

WEB = Path(__file__).parent / "web"
LAST_SEEN = [time.time()]   # lần cuối giao diện hỏi trạng thái (để tự thoát khi đóng trình duyệt)
IDLE_EXIT_S = 240
WEB_SAFE = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class _Preview:
    """LRU nhỏ cho ảnh xem trước."""
    def __init__(self, n=16):
        self.n, self.d, self.lock = n, {}, threading.Lock()

    def get(self, key, fn):
        with self.lock:
            if key in self.d:
                v = self.d.pop(key)
                self.d[key] = v
                return v
        v = fn()
        with self.lock:
            self.d[key] = v
            while len(self.d) > self.n:
                self.d.pop(next(iter(self.d)))
        return v


_drive_seen: dict[str, dict | None] = {}   # kết quả dò ổ gần nhất; None là ổ chưa sẵn sàng
_drive_time = [0.0]


def probe_drive(k32, root: str):
    """Thông tin ổ nếu ổ đang có dữ liệu; None nếu là ổ trống, ví dụ khe đọc thẻ chưa cắm thẻ."""
    import ctypes
    free, total = ctypes.c_ulonglong(0), ctypes.c_ulonglong(0)
    if not k32.GetDiskFreeSpaceExW(ctypes.c_wchar_p(root), ctypes.byref(free), ctypes.byref(total), None) or not total.value:
        return None
    name = ctypes.create_unicode_buffer(261)
    k32.GetVolumeInformationW(ctypes.c_wchar_p(root), name, 261, None, None, None, None, 0)
    return dict(path=root, label=name.value, free=free.value)


def list_drives(k32, wait: float = 1.2):
    """Các ổ đang dùng được. Dò song song và có giới hạn thời gian vì ổ mạng mất kết nối có thể treo rất lâu;
    ổ trả lời muộn sẽ xuất hiện ở lần xem sau."""
    k32.SetErrorMode(1)   # không để Windows hiện hộp thoại "chưa có đĩa"
    mask = k32.GetLogicalDrives()
    roots = [f"{c}:\\" for i, c in enumerate(string.ascii_uppercase) if mask & (1 << i)]

    def run(root):
        try:
            _drive_seen[root] = probe_drive(k32, root)
        except Exception:  # noqa: BLE001  lỗi lạ thì vẫn hiện ổ, để không mất lối vào ổ đó
            _drive_seen[root] = dict(path=root, label="", free=0)

    if time.time() - _drive_time[0] > 5:   # bấm qua các thư mục liên tiếp không phải dò lại
        _drive_time[0] = time.time()
        ts = [threading.Thread(target=run, args=(r,), daemon=True) for r in roots]
        for t in ts:
            t.start()
        end = time.time() + wait
        for t in ts:
            t.join(max(0.0, end - time.time()))
    return [_drive_seen[r] for r in roots if _drive_seen.get(r)]


def list_dir(path: str):
    path = os.path.abspath(os.path.expanduser(path or "~"))
    dirs, n_img = [], 0
    try:
        for e in sorted(os.scandir(path), key=lambda e: e.name.lower()):
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir():
                    dirs.append(e.name)
                elif Path(e.name).suffix.lower() in ALL_EXT:
                    n_img += 1
            except OSError:
                pass
    except OSError as e:
        return dict(path=path, parent=os.path.dirname(path), dirs=[], images=0, error=str(e))
    parent = os.path.dirname(path)
    quick = []
    home = Path.home()
    for nm in ("Pictures", "Desktop", "Documents", "Downloads"):
        if (home / nm).is_dir():
            quick.append(dict(name=nm, path=str(home / nm)))
    drives = []
    if os.name == "nt":
        try:
            import ctypes
            drives = list_drives(ctypes.windll.kernel32)
        except Exception:  # noqa: BLE001
            drives = []
    if sys.platform == "darwin":   # ổ ngoài, thẻ nhớ và thư mục mạng đã kết nối nằm trong /Volumes
        try:
            drives = [dict(path=str(Path("/Volumes") / v), label=v, free=0)
                      for v in sorted(os.listdir("/Volumes")) if not v.startswith(".")]
        except OSError:
            drives = []
    return dict(path=path, parent=parent if parent != path else "", dirs=dirs, images=n_img,
                quick=[dict(name="Thư mục chính", path=str(home))] + quick, drives=drives)


# ------------------------------------------------------------------ mạng LAN (thư mục chia sẻ SMB / UNC)
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_USER_RE = re.compile(r"^[\w.@\\ -]{1,100}$")
_NOWIN = 0x08000000 if os.name == "nt" else 0


def _run(args, timeout=10):
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_NOWIN)
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    raw = r.stdout + b"\n" + r.stderr
    for enc in (("oem", "utf-8") if os.name == "nt" else ("utf-8",)):
        try:
            return r.returncode, raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return r.returncode, raw.decode("utf-8", "replace")


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


def _has_smb(ip):
    try:
        with socket.create_connection((ip, 445), timeout=0.5):
            return True
    except OSError:
        return False


def _rname(ip):
    try:
        socket.setdefaulttimeout(1.0)
        return socket.gethostbyaddr(ip)[0].split(".")[0].upper()
    except OSError:
        return ""
    finally:
        socket.setdefaulttimeout(None)


def lan_scan():
    """Tìm các máy đang bật chia sẻ file (cổng 445) trong cùng mạng /24, kèm tên máy nếu phân giải được."""
    me = _local_ip()
    found = {}
    nv = {}

    def _netview():
        if os.name == "nt":   # danh sách máy theo cách cũ (nếu mạng còn bật tính năng duyệt) — chạy song song, tối đa 4 giây
            rc, out = _run(["net", "view"], 4)
            for m in re.finditer(r"^\s*\\\\(\S+)", out, re.M):
                nv[m.group(1).upper()] = 1
    import threading as _th
    t_nv = _th.Thread(target=_netview, daemon=True)
    t_nv.start()
    if me:
        base = me.rsplit(".", 1)[0]
        ips = [f"{base}.{i}" for i in range(1, 255) if f"{base}.{i}" != me]
        with ThreadPoolExecutor(64) as ex:
            ok = [ip for ip, v in zip(ips, ex.map(_has_smb, ips)) if v]
        with ThreadPoolExecutor(32) as ex:
            for ip, nm in zip(ok, ex.map(_rname, ok)):
                found[ip] = nm
    t_nv.join(timeout=4.5)
    for nm in list(nv):
        if nm not in found.values():
            found["~" + nm] = nm
    hosts = []
    for ip, nm in found.items():
        hosts.append(dict(name=nm, ip="" if ip.startswith("~") else ip, host=nm or ip))
    hosts.sort(key=lambda h: (h["name"] == "", h["name"] or h["ip"]))
    return dict(hosts=hosts, me=me)


_SMB_RE = re.compile(r"^smb://[A-Za-z0-9][A-Za-z0-9._@:%-]*(/[\w .%-]*)?$")


def lan_mount(url):
    """macOS: nhờ Finder kết nối thư mục chia sẻ SMB (hiện hộp thoại hỏi tài khoản nếu cần). Sau đó nó nằm trong /Volumes."""
    if sys.platform != "darwin":
        return dict(error="Chỉ dùng trên macOS")
    url = (url or "").strip()
    if not url.lower().startswith("smb://"):
        url = "smb://" + url.lstrip("/")
    if not _SMB_RE.match(url):
        return dict(error="Địa chỉ không hợp lệ. Ví dụ: smb://192.168.1.10/TenThuMuc")
    rc, out = _run(["open", url], 10)
    return dict(ok=rc == 0, error="" if rc == 0 else (out.strip() or "Không kết nối được"))


def lan_shares(host):
    if not _HOST_RE.match(host or ""):
        return dict(error="Tên máy / địa chỉ IP không hợp lệ")
    if os.name != "nt":
        return dict(error="Chỉ hỗ trợ trên Windows")
    rc, out = _run(["net", "view", "\\\\" + host], 8)
    shares, started = [], False
    for ln in out.splitlines():
        if re.match(r"^-{5,}", ln.strip()):
            started = True
            continue
        if not started:
            continue
        if not ln.strip():
            if shares:
                break
            continue
        parts = re.split(r"\s{2,}", ln.strip())
        name = parts[0]
        typ = parts[1].lower() if len(parts) > 1 else ""
        if name.endswith("$") or "print" in typ or "máy in" in typ:
            continue
        shares.append(name)
    if not shares:
        low = out.lower()
        need = rc != 0 and any(k in low for k in ("5", "1219", "1326", "access", "denied", "logon", "credential", "từ chối"))
        return dict(shares=[], error=out.strip()[-300:] or "Không liệt kê được thư mục chia sẻ", need_login=need)
    return dict(shares=shares)


def lan_connect(host, user, password):
    if not _HOST_RE.match(host or ""):
        return dict(error="Tên máy / địa chỉ IP không hợp lệ")
    if not _USER_RE.match(user or ""):
        return dict(error="Tên đăng nhập không hợp lệ")
    if os.name != "nt":
        return dict(error="Chỉ hỗ trợ trên Windows")
    if (password or "").startswith("/"):
        return dict(error="Mật khẩu không được bắt đầu bằng dấu /")
    args = ["net", "use", "\\\\" + host + "\\IPC$"] + ([password] if password else [""]) + ["/user:" + user, "/persistent:no"]
    rc, out = _run(args, 20)
    if rc != 0:
        return dict(error=out.strip()[-300:] or "Kết nối thất bại")
    return dict(ok=True)


def make_handler(lib: Library, token: str, port: int, lic: License):
    upd = Updater()
    threading.Thread(target=fonts.scan, daemon=True).start()   # đọc sẵn danh sách font để hộp chọn mở ngay

    previews = _Preview(32)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "CullCollage"

        def log_message(self, *a):  # im lặng
            pass

        # ---------- tiện ích
        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                       {"Cache-Control": "no-store"})

        def _authed(self):
            if self.headers.get("Host", "") not in allowed_hosts:
                return False  # chống DNS rebinding
            ck = self.headers.get("Cookie", "")
            return f"ps={token}" in [c.strip() for c in ck.split(";")]

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        # ---------- GET
        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/":
                    if self.headers.get("Host", "") not in allowed_hosts:
                        return self._send(403, b"forbidden", "text/plain")
                    if q.get("t") == token or self._authed():
                        html = (WEB / ("shell.html" if lic.ok() else "activate.html")).read_bytes()   # chưa có key: bảng kích hoạt
                        return self._send(200, html, "text/html; charset=utf-8",
                                          {"Set-Cookie": f"ps={token}; HttpOnly; SameSite=Strict; Path=/",
                                           "Cache-Control": "no-store"})
                    return self._send(403, "Mở ứng dụng bằng lối tắt MThanglee Cull&Collage.".encode(), "text/plain; charset=utf-8")
                if not self._authed():
                    return self._send(403, b"forbidden", "text/plain")
                if u.path == "/api/license":
                    LAST_SEEN[0] = time.time()
                    return self._json(lic.info())
                if u.path == "/ui.css":
                    return self._send(200, fonts.ui_css().encode("utf-8"), "text/css; charset=utf-8", {"Cache-Control": "no-store"})
                if not lic.ok() and u.path not in ("/logo.png", "/favicon.png", "/api/status"):
                    return self._json(dict(error="Chưa kích hoạt key", license=False), 402)

                if u.path in ("/filter", "/layout"):
                    name = "index.html" if u.path == "/filter" else "layout.html"
                    return self._send(200, (WEB / name).read_bytes(), "text/html; charset=utf-8", {"Cache-Control": "no-store"})
                if u.path == "/api/file":
                    p = os.path.abspath(q.get("path", ""))
                    ext = Path(p).suffix.lower()
                    if ext not in ALL_EXT or not os.path.isfile(p):   # chỉ phục vụ file ảnh
                        return self._send(404, b"", "text/plain")
                    side = int(q.get("s", 0))
                    if not side and ext in WEB_SAFE:   # ảnh gốc nguyên vẹn cho khâu xuất
                        return self._send(200, Path(p).read_bytes(), WEB_SAFE[ext], {"Cache-Control": "max-age=3600"})

                    def make_file():
                        ow, oh, _ = read_meta(p)
                        img = load_bgr(p, side, (ow, oh))
                        return _jpg(img, 92) if img is not None else b""
                    data = previews.get(("f", p, side), make_file)
                    if not data:
                        return self._send(404, b"", "text/plain")
                    return self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=3600"})
                if u.path in ("/logo.png", "/favicon.png"):
                    return self._send(200, (WEB / u.path[1:]).read_bytes(), "image/png", {"Cache-Control": "max-age=86400"})
                if u.path == "/api/status":
                    idle = time.time() - LAST_SEEN[0]
                    LAST_SEEN[0] = time.time()
                    if not lic.ok():
                        return self._json(dict(idle=round(idle, 1), license=False))
                    return self._json(dict(lib.status, eyes=lib.an.has_eyes, settings=lib.settings,
                                           online=lib.online.ok, idle=round(idle, 1), os=os.name, plat=sys.platform))
                if u.path == "/api/cache":
                    return self._json(lib.cache_info())
                if u.path == "/api/fonts":
                    return self._json(fonts.scan())
                if u.path == "/api/ui":
                    return self._json(fonts.get_ui())
                if u.path == "/api/update/check":
                    return self._json(upd.public(upd.check("force" in q)))
                if u.path == "/api/update/status":
                    return self._json(upd.state)
                if u.path == "/api/catalog":
                    return self._json(lib.catalog())
                if u.path == "/api/cull/last":
                    return self._json(lib.cull_last())
                if u.path == "/api/export/status":
                    return self._json(lib.export_status())
                if u.path == "/api/photos":
                    return self._json(lib.photos())
                if u.path == "/api/people":
                    return self._json(lib.people())
                if u.path == "/api/faces":
                    return self._json(lib.faces_of(int(q["id"])))
                if u.path == "/api/info":
                    return self._json(lib.info(int(q["id"])))
                if u.path == "/api/mask":
                    png = lib.mask_png(int(q["id"]), "hi" if q.get("m") == "hi" else "lo")
                    if not png:
                        return self._send(404, b"", "text/plain")
                    return self._send(200, png, "image/png", {"Cache-Control": "max-age=300"})
                if u.path == "/api/diag":
                    return self._json(dict(text=lib.diag(int(q["id"]))))
                if u.path == "/api/lan":
                    return self._json(lan_scan())
                if u.path == "/api/lan/shares":
                    return self._json(lan_shares(q.get("host", "")))
                if u.path == "/api/ls":
                    return self._json(list_dir(q.get("path", "")))
                if u.path == "/api/preview":
                    pid, side = int(q["id"]), int(q.get("s", 2000))
                    p = lib.path_of(pid)
                    if not p:
                        return self._send(404, b"", "text/plain")

                    cached = PREVIEWS / f"{pid}.jpg"
                    if side and cached.exists():  # ảnh 1600px đã giải mã sẵn trên ổ máy: không đụng tới thẻ nhớ
                        return self._send(200, cached.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=3600"})

                    def make():
                        ow, oh, _ = read_meta(p)
                        img = load_bgr(p, side, (ow, oh))
                        return _jpg(img, 90) if img is not None else b""
                    data = previews.get((pid, side), make)
                    if not data:
                        return self._send(404, b"", "text/plain")
                    return self._send(200, data, "image/jpeg", {"Cache-Control": "max-age=3600"})
                if u.path.startswith("/cover/"):
                    name = os.path.basename(u.path)
                    f = COVERS / name
                    if not name.endswith(".jpg") or not f.exists():
                        return self._send(404, b"", "text/plain")
                    return self._send(200, f.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=86400"})
                if u.path.startswith("/thumb/") or u.path.startswith("/face/"):
                    base = THUMBS if u.path.startswith("/thumb/") else FACES
                    name = os.path.basename(u.path)
                    f = base / name
                    if not name.endswith(".jpg") or not f.exists():
                        return self._send(404, b"", "text/plain")
                    return self._send(200, f.read_bytes(), "image/jpeg", {"Cache-Control": "max-age=86400"})
                return self._send(404, b"not found", "text/plain")
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # noqa: BLE001
                try:
                    self._json(dict(error=str(e)), 500)
                except Exception:  # noqa: BLE001
                    pass

        # ---------- POST
        def do_POST(self):
            u = urlparse(self.path)
            if not self._authed() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._send(403, b"forbidden", "text/plain")
            try:
                b = self._body()
                if u.path == "/api/license/activate":
                    return self._json(lic.activate(str(b.get("key", ""))))
                if u.path == "/api/license/remove":
                    lic.remove()
                    return self._json(dict(ok=True))
                if not lic.ok() and u.path != "/api/quit":
                    return self._json(dict(error="Chưa kích hoạt key", license=False), 402)
                if u.path == "/api/open":
                    path = os.path.abspath(os.path.expanduser(b["path"]))
                    if not os.path.isdir(path):
                        return self._json(dict(error="Không phải thư mục"), 400)
                    lib.open_folder(path, bool(b.get("recursive", True)))
                    return self._json(dict(ok=True))
                if u.path == "/api/cache/clear":
                    lib.clear_cache()
                    return self._json(lib.cache_info())
                if u.path == "/api/cache/limit":
                    lib.set_settings(dict(cache_gb=int(b["limit_gb"])))
                    lib.trim_cache()
                    return self._json(lib.cache_info())
                if u.path == "/api/catalog/remove":
                    lib.catalog_remove(str(b["root"]))
                    return self._json(dict(ok=True))
                if u.path == "/api/cull/apply":
                    return self._json(lib.cull_apply(b["ids"]))
                if u.path == "/api/cull/undo":
                    return self._json(lib.cull_undo(b.get("id")))
                if u.path == "/api/cull/clear":
                    lib.cull_clear()
                    return self._json(dict(ok=True))
                if u.path == "/api/rate":
                    if "pairs" in b:
                        lib.set_ratings(b["pairs"])
                    else:
                        lib.set_rating(b["ids"], b["rating"])
                    return self._json(dict(ok=True))
                if u.path == "/api/label":
                    lib.set_label(b["ids"], b["label"])
                    return self._json(dict(ok=True))
                if u.path == "/api/lan/mount":
                    return self._json(lan_mount(str(b.get("url", ""))))
                if u.path == "/api/lan/connect":
                    return self._json(lan_connect(str(b.get("host", "")), str(b.get("user", "")), str(b.get("password", ""))))
                if u.path == "/api/online":
                    return self._json(dict(online=lib.online.recheck()))
                if u.path == "/api/ui":
                    try:
                        return self._json(fonts.set_ui(b.get("font", "")))
                    except ValueError as e:
                        return self._json(dict(error=str(e)), 400)
                if u.path == "/api/reveal":   # mở thư mục đích sau khi xuất ảnh
                    d = os.path.abspath(str(b.get("path", "")))
                    if not os.path.isdir(d):
                        return self._json(dict(error="Không tìm thấy thư mục"), 404)
                    if os.name == "nt":
                        os.startfile(d)  # noqa: S606
                    else:
                        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", d])
                    return self._json(dict(ok=True))
                if u.path == "/api/update/start":
                    return self._json(upd.start())
                if u.path == "/api/update/install":
                    r = upd.install()
                    self._json(r)
                    if r.get("ok"):
                        threading.Timer(0.4, lambda: os._exit(0)).start()
                    return
                if u.path == "/api/quit":
                    self._json(dict(ok=True))
                    threading.Timer(0.4, lambda: os._exit(0)).start()
                    return
                if u.path == "/api/settings":
                    lib.set_settings(b)
                    return self._json(dict(ok=True, settings=lib.settings))
                if u.path == "/api/person/rename":
                    lib.rename_person(int(b["id"]), b["name"])
                    return self._json(dict(ok=True))
                if u.path == "/api/person/merge":
                    lib.merge_people(int(b["src"]), int(b["dst"]))
                    return self._json(dict(ok=True))
                if u.path == "/api/recluster":
                    if "threshold" in b:
                        lib.set_settings(dict(face_threshold=b["threshold"]))
                    lib.cluster(reset=True)
                    return self._json(dict(ok=True))
                if u.path == "/api/mkdir":
                    name = str(b.get("name", "")).strip().rstrip(". ")
                    if not str(b.get("parent", "")).strip():
                        return self._json(dict(error="Chưa xác định thư mục cha"), 400)
                    parent = os.path.abspath(os.path.expanduser(b["parent"]))
                    if not name or name in (".", "..") or any(c in name for c in '\\/:*?"<>|'):
                        return self._json(dict(error='Tên không hợp lệ (không dùng \\ / : * ? " < > |)'), 400)
                    if not os.path.isdir(parent):
                        return self._json(dict(error="Thư mục cha không tồn tại"), 400)
                    path = os.path.join(parent, name)
                    os.makedirs(path, exist_ok=True)
                    return self._json(dict(ok=True, path=path))
                if u.path == "/api/export":
                    r = lib.start_export(b["ids"], b["dest"], bool(b.get("by_person")),
                                         b.get("template") or "{name}", bool(b.get("xmp")))
                    return self._json(r, 409 if r.get("error") else 200)
                if u.path == "/api/pick":   # chuyển ảnh đã lọc sang Dàn trang: giữ đường dẫn, không sao chép file
                    items = []
                    for pid in b["ids"]:
                        r = lib.db.one("SELECT path,w,h FROM photos WHERE id=?", (int(pid),))
                        if r:
                            items.append(dict(path=r["path"], name=os.path.basename(r["path"]), w=r["w"], h=r["h"]))
                    return self._json(dict(items=items))
                if u.path == "/api/xmp":
                    return self._json(dict(written=lib.write_xmp(b["ids"])))
                return self._send(404, b"not found", "text/plain")
            except KeyError as e:
                self._json(dict(error=f"thiếu tham số {e}"), 400)
            except Exception as e:  # noqa: BLE001
                self._json(dict(error=str(e)), 500)

    return H


class _Srv(ThreadingHTTPServer):
    """Windows: cho phép nhiều chương trình dùng chung một cổng (SO_REUSEADDR) khiến yêu cầu bị chuyển nhầm sang
    chương trình khác. Dùng SO_EXCLUSIVEADDRUSE để cổng của ứng dụng luôn là của riêng nó."""
    allow_reuse_address = os.name != "nt"
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt":
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                pass
        super().server_bind()


def serve(port: int = 8765, open_browser: bool = True, folder: str | None = None):
    missing = models.ensure_models()
    if missing:
        print("Thiếu model:", ", ".join(missing), "- chạy: python -m photosift.models", file=sys.stderr)
        sys.exit(1)
    lib = Library()
    lic = License()
    token = secrets.token_urlsafe(18)
    httpd = None
    import random
    from .db import HOME as _H
    # Cổng 8765 hay bị chương trình khác chiếm nên dùng cổng ngẫu nhiên, nhưng phải GIỮ NGUYÊN cổng đó
    # giữa các lần mở: dự án Dàn trang lưu theo địa chỉ cổng, đổi cổng thì dự án sẽ như bị mất.
    cands = random.sample(range(49200, 65000), 40) if port in (0, 8765) else list(range(port, port + 20))
    port_file = _H / "port.txt"
    default_port = port in (0, 8765)
    if default_port:
        try:
            cands.insert(0, int(port_file.read_text().strip()))
        except (OSError, ValueError):
            pass
    for p in cands:
        try:
            httpd = _Srv(("127.0.0.1", p), make_handler(lib, token, p, lic))
            port = p
            if default_port:
                try:
                    _H.mkdir(parents=True, exist_ok=True)
                    port_file.write_text(str(p))
                except OSError:
                    pass
            break
        except OSError:
            continue
    if httpd is None:
        print("Không mở được cổng nào", file=sys.stderr)
        sys.exit(1)
    url = f"http://127.0.0.1:{port}/?t={token}"
    print("=" * 60, flush=True)
    print(" MThanglee Cull&Collage đã chạy. Nếu trình duyệt không tự mở, hãy copy", flush=True)
    print(" TOÀN BỘ đường dẫn dưới đây dán vào Chrome/Edge:", flush=True)
    print("\n " + url + "\n", flush=True)
    print(" (Đóng cửa sổ này để thoát)", flush=True)
    print("=" * 60, flush=True)
    if not lib.an.has_eyes:
        print("Ghi chú: chưa có lbfmodel.yaml nên chưa phát hiện được ảnh nhắm mắt (chạy: python -m photosift.models).")
    lib.online.start()
    # Ghi thông tin phiên để bộ khởi chạy có thể mở lại cửa sổ đang chạy
    from .db import HOME
    run_file = HOME / "running.json"
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        run_file.write_text(json.dumps(dict(pid=os.getpid(), port=port, token=token)), encoding="utf-8")
    except OSError:
        pass
    if os.environ.get("PHOTOSIFT_AUTOEXIT") == "1":   # chạy không cửa sổ: tự thoát khi đóng trình duyệt
        def _idle():
            while True:
                time.sleep(10)
                if time.time() - LAST_SEEN[0] > IDLE_EXIT_S:
                    try:
                        run_file.unlink()
                    except OSError:
                        pass
                    os._exit(0)
        threading.Thread(target=_idle, daemon=True).start()
    if folder and lic.ok():
        lib.open_folder(os.path.abspath(folder), True)
    if open_browser:
        def _open():
            try:
                if os.name == "nt":
                    os.startfile(url)  # type: ignore[attr-defined]
                else:
                    import webbrowser
                    webbrowser.open(url)
            except Exception as e:  # noqa: BLE001
                print("Không tự mở được trình duyệt:", e, flush=True)
        threading.Timer(0.8, _open).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return lib
