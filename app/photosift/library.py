"""Thư viện ảnh: quét thư mục, phân tích song song, gom người, nhóm ảnh trùng, cờ cảnh báo, xuất ảnh."""
from __future__ import annotations
import hashlib

import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import numpy as np

from .analyzer import ALL_EXT, ANALYSIS_SIDE, RAW_EXT, Analyzer, _jpg, diag_raw, focus_point, hamming, load_view, read_exif
from .errors import friendly
from . import taste
from .db import DB, HOME
from .models import path as _model_path
from .online import Online
from collections import OrderedDict
from . import xmpsync as _xs
from .xmpsync import _xmp_parse, dir_names, merge_xmp, sidecar, write_atomic

# thư mục hệ thống/phần mềm: bỏ qua khi dò tìm thư mục ảnh được kéo thả (đỡ tốn thời gian, không bao giờ chứa ảnh khách)
_LOCATE_SKIP = {"windows", "program files", "program files (x86)", "programdata", "appdata", "application data",
                "system volume information", "recovery", "perflogs", "msocache", "intel", "drivers", "node_modules",
                "library", "system", "applications", "private", "usr", "bin", "sbin", "cores", "dev", "opt",
                "cache", "caches", "temp", "tmp"}

THUMBS = HOME / "thumbs"
COVERS = HOME / "covers"   # ảnh bìa catalog: giữ qua các lần mở app, khác với THUMBS
FACES = HOME / "faces"
VIEWS = HOME / "view"      # ảnh nét đúng cỡ màn hình cho trình xem (RAW đã giải mã), dựng sẵn ở nền
PREVIEWS = HOME / "prev"   # ảnh 1600px đã giải mã sẵn: xem nhanh + phân tích không phải đọc lại RAW từ thẻ nhớ
# gu chọn ảnh: mô hình riêng của người dùng / mô hình mặc định đóng gói trong app
TASTE_FILE = HOME / "taste.npz"
TASTE_DEFAULT = _model_path("taste_default.npz")
TASTE_ROLLS = 40          # học gu riêng từ tối đa 40 đám gần nhất
TASTE_NEG = 4             # mỗi đám: giữ mọi ảnh được chọn, lấy mẫu tối đa 4 ảnh bỏ / 1 ảnh giữ
# phạt L2 về phía gu mặc định (không có thì về 0). taste.fit chia phạt cho tổng trọng số mẫu, nên lam ≈ số mẫu "ảo";
# trọng số CLIP phải lớn (vector đơn vị 512 chiều) nên lam lớn kìm cả gu riêng lẫn gu mặc định. Đo trên dữ liệu giả
# (gu người dùng khác / gần gu mặc định, 1–39 đám): lam 1–3 tốt nhất; ít dữ liệu vẫn gần gu mặc định vì luyện
# bắt đầu từ trọng số mặc định với số bước có hạn.
TASTE_LAM = 2.0
CLIP_DIM = 512
IO_WORKERS = 4             # số luồng đọc file (thẻ nhớ/USB: 4 là hợp lý)
LABELS = {"", "red", "yellow", "green", "blue", "purple"}
XMP_LABEL = {"red": "Red", "yellow": "Yellow", "green": "Green", "blue": "Blue", "purple": "Purple"}

CACHE_VERSION = 4  # 4: thêm hướng mặt (quay ngang / nhìn máy).
# tăng khi đổi cách đọc/xoay ảnh → tự đọc lại toàn bộ (giữ sao, nhãn và tên người)

DEFAULT_SETTINGS = dict(
    cache_gb=20,         # giới hạn bộ nhớ đệm; vượt quá thì dọn thư mục lâu chưa mở
    blur_ratio=0.45,     # mờ nếu độ nét < tỉ lệ này × trung vị của thư mục
    dark=0.20,           # tối nếu độ sáng trung bình < giá trị này
    bright=0.80,         # sáng quá nếu > giá trị này
    ear=0.19,            # nhắm mắt nếu EAR < giá trị này
    dup_hamming=10,      # ảnh giống nhau nếu khoảng cách dHash <= giá trị này
    dup_seconds=20,      # ... và chụp cách nhau <= giây
    face_threshold=0.38, # ngưỡng cosine để coi là cùng một người
    emotion_priority=1,  # trong 1 loạt ảnh trùng, ưu tiên ảnh có cảm xúc (cười) làm ảnh giữ
    xmp_sync=1,          # tự ghi sao/loại/nhãn ra .xmp cạnh ảnh gốc (máy khác mở cùng thư mục thấy kết quả lọc)
)


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "_"


def _is_network(path: str) -> bool:
    if path.startswith("\\\\") or path.startswith("//"):
        return True
    if os.name == "nt":
        try:
            import ctypes
            drv = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
            return ctypes.windll.kernel32.GetDriveTypeW(drv) == 4   # DRIVE_REMOTE
        except Exception:  # noqa: BLE001
            return False
    if sys.platform == "darwin":   # thư mục mạng / ổ ngoài đã gắn trong /Volumes
        return os.path.realpath(path).startswith("/Volumes/")
    return False


# ---- ưu tiên giao diện: việc nền (phân tích, đo nụ cười, dựng ảnh nét cả thư mục) chạy ở mức ưu tiên thấp
# và tạm nhường khi đang lật ảnh, để trình xem (và cửa sổ app) luôn được CPU trước → chuyển ảnh không khựng.
_UI_T = [0.0]
UI_HOT_S = 0.6     # vừa lật ảnh trong khoảng này thì việc nền chờ
UI_WAIT_MAX = 3.0  # chờ tối đa mỗi lượt (đang lật liên tục thì việc nền vẫn chạy dần, không đứng hẳn)


def ui_ping():
    """Gọi mỗi khi giao diện xin ảnh để xem."""
    _UI_T[0] = time.time()


def ui_yield():
    end = time.time() + UI_WAIT_MAX
    while time.time() - _UI_T[0] < UI_HOT_S and time.time() < end:
        time.sleep(0.05)


def _thread_prio(level: int):
    """Đổi mức ưu tiên CPU của luồng hiện tại trên Windows (-2 thấp nhất … 0 bình thường)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetThreadPriority(k.GetCurrentThread(), level)
    except Exception:  # noqa: BLE001
        pass


def _low_prio():
    _thread_prio(-1)   # THREAD_PRIORITY_BELOW_NORMAL



def read_xmp_rating(path: str):
    """Sao từ .xmp (Photo Mechanic/Lightroom): sidecar rồi XMP nhúng trong JPEG. -1..5 hoặc None. Không bao giờ raise."""
    try:
        base, name = os.path.splitext(path)[0], path
        for cand in (base + ".xmp", base + ".XMP", name + ".xmp", name + ".XMP"):
            if os.path.isfile(cand):
                with open(cand, "rb") as f:
                    r = _xmp_parse(f.read(1 << 20))
                if r is not None:
                    return r
        if os.path.splitext(path)[1].lower() in (".jpg", ".jpeg"):
            with open(path, "rb") as f:
                head = f.read(256 * 1024)
            i = head.find(b"<x:xmpmeta")
            if i >= 0:
                return _xmp_parse(head[i:])
    except Exception:  # noqa: BLE001
        pass
    return None


def _num(v, miss=-1.0):
    """Giá trị số đọc từ DB; bản 1.1.46 lỡ lưu điểm cười dạng bytes (float32) → đọc lại thành số."""
    if v is None:
        return miss
    if isinstance(v, (bytes, bytearray)):
        import struct
        try:
            return round(struct.unpack("<f", bytes(v)[:4])[0], 3) if len(v) >= 4 else miss
        except struct.error:
            return miss
    return v


EXPORT_WORKERS = 2       # chép ổ trong máy → ổ trong máy
EXPORT_WORKERS_NET = 3   # nguồn hoặc đích là ổ mạng / NAS (nhiều hơn dễ làm ổ cứng NAS phải nhảy đầu đọc)

class Library:
    def __init__(self, db: DB | None = None):
        THUMBS.mkdir(parents=True, exist_ok=True)
        FACES.mkdir(parents=True, exist_ok=True)
        PREVIEWS.mkdir(parents=True, exist_ok=True)
        VIEWS.mkdir(parents=True, exist_ok=True)
        self.db = db or DB()
        self.an = Analyzer()
        self.online = Online()      # bắt đầu kiểm tra mạng trong serve()
        self.settings = dict(DEFAULT_SETTINGS)
        self._sfile = HOME / "settings.json"
        try:
            self.settings.update(json.loads(self._sfile.read_text()))
        except Exception:  # noqa: BLE001
            pass
        self._migrate()
        self.root = ""
        self.status = dict(state="idle", total=0, done=0, thumbs=0, errors=0, root="", message="", timing={})
        self.cam = dict(state="idle", done=0, total=0, message="", cams=[])  # đồng bộ thời gian nhiều máy
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        # dựng ảnh nét cho trình xem: hàng đợi ưu tiên (ảnh đang xem + vài ảnh kế) và hàng đợi nền (cả thư mục)
        self._vcv = threading.Condition()
        self._vq: list[tuple[int, int]] = []
        self._vlow: list[tuple[int, int]] = []
        self._vbusy: set[tuple[int, int]] = set()
        self._vside = int(self.settings.get("view_side") or 0)
        self._vsides = {self._vside} if self._vside else set()   # các cỡ ảnh nét đang có trên đĩa (khỏi quét cả thư mục mỗi ảnh)
        try:
            for e in os.scandir(VIEWS):
                a = e.name.rsplit(".", 1)[0].split("_")
                if len(a) == 2 and a[1].isdigit():
                    self._vsides.add(int(a[1]))
        except OSError:
            pass
        self._view_reset()
        for k in range(2):
            threading.Thread(target=self._view_worker, args=(k == 0,), daemon=True).start()
        self._xmp_init()
        threading.Thread(target=self._xmp_writer, daemon=True).start()

    # ------------------------------------------------------------------ bộ nhớ đệm
    # Thumbnail, ảnh xem trước và kết quả phân tích được giữ giữa các lần mở app để mở lại thư mục là có ngay.
    def cache_info(self):
        total = 0
        for d in (THUMBS, FACES, PREVIEWS, VIEWS):
            try:
                with os.scandir(d) as it:
                    total += sum(e.stat().st_size for e in it if e.is_file())
            except OSError:
                pass
        return dict(bytes=total, limit_gb=self.settings["cache_gb"])

    def _evict(self, ids) -> int:
        """Xoá cache của các ảnh này, giữ dòng trong CSDL nên sao, nhãn, dấu ✕ và id vẫn còn. Trả về số byte đã giải phóng."""
        ids, freed = list(ids), 0

        def drop(f):
            nonlocal freed
            try:
                freed += f.stat().st_size
                f.unlink()
            except OSError:
                pass

        with self.db.lock:
            c = self.db.con
            for p in self.db.q("SELECT id FROM people WHERE name<>''"):  # nhớ người đã đặt tên trước khi xoá mặt
                self._store_centroid(p["id"])
            for k in range(0, len(ids), 500):
                part = ids[k:k + 500]
                marks = ",".join("?" * len(part))
                for r in self.db.q(f"SELECT id FROM faces WHERE photo_id IN ({marks})", part):
                    drop(FACES / f"{r['id']}.jpg")
                c.execute(f"DELETE FROM faces WHERE photo_id IN ({marks})", part)
                c.execute(f"UPDATE photos SET analyzed=0,ready=0,tv=0,grp=0,best=0,score=0,err=NULL WHERE id IN ({marks})", part)
                for i in part:
                    drop(THUMBS / f"{i}.jpg")
                    drop(PREVIEWS / f"{i}.jpg")
                    for f in VIEWS.glob(f"{i}_*.jpg"):
                        drop(f)
            c.execute("DELETE FROM people WHERE name='' AND id NOT IN (SELECT person_id FROM faces WHERE person_id IS NOT NULL)")
            c.commit()
        return freed

    def _other_cached(self):
        """Ảnh có cache ngoài thư mục đang mở, nhóm theo thư mục, thư mục lâu chưa mở nhất đứng đầu."""
        opened = self.db.q("SELECT root,recursive,opened FROM catalog")
        groups: dict[str, list[int]] = {}
        for r in self.db.q("SELECT id,dir FROM photos WHERE ready=1 AND id NOT IN (SELECT id FROM cur)"):
            groups.setdefault(r["dir"] or "", []).append(r["id"])

        def last(d):
            hits = [c["opened"] for c in opened if d == c["root"] or (c["recursive"] and d.startswith(c["root"].rstrip("\\/") + os.sep))]
            return max(hits, default=0)

        return [groups[d] for d in sorted(groups, key=last)]

    def trim_cache(self):
        limit = self.settings["cache_gb"] * 10 ** 9
        size = self.cache_info()["bytes"]
        if size <= limit:
            return
        for ids in self._other_cached():
            size -= self._evict(ids)
            if size <= limit * 0.8:
                break

    def clear_cache(self):
        for ids in self._other_cached():
            self._evict(ids)

    def _migrate(self):
        db = self.db
        try:   # sửa dữ liệu bản 1.1.46: điểm cười lưu nhầm dạng bytes làm danh sách ảnh báo lỗi (Catalog "chưa có ảnh")
            bad = db.q("SELECT id, smile FROM photos WHERE typeof(smile)='blob'")
            if bad:
                db.many("UPDATE photos SET smile=? WHERE id=?", [(_num(b["smile"]), b["id"]) for b in bad])
            bad = db.q("SELECT id, smile FROM faces WHERE typeof(smile)='blob'")
            if bad:
                db.many("UPDATE faces SET smile=? WHERE id=?", [(_num(b["smile"]), b["id"]) for b in bad])
        except Exception as e:  # noqa: BLE001
            print("smile fix:", e, file=sys.stderr)
        r = db.one("SELECT v FROM meta WHERE k='cache_version'")
        if r and int(r["v"]) == CACHE_VERSION:
            return
        with db.lock:
            for p in db.q("SELECT id FROM people WHERE name<>''"):   # giữ "dấu vân tay" của người đã đặt tên
                self._store_centroid(p["id"])
            db.con.execute("DELETE FROM faces")
            db.con.execute("DELETE FROM people WHERE name=''")
            db.con.execute("UPDATE photos SET analyzed=0, ready=0, tv=0, grp=0, best=0, score=0, err=NULL")
            db.con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('cache_version',?)", (str(CACHE_VERSION),))
            db.con.commit()
        for d in (THUMBS, FACES, PREVIEWS):
            for f in d.glob("*.jpg"):
                try:
                    f.unlink()
                except OSError:
                    pass

    def _store_centroid(self, pid: int):
        rows = self.db.q("SELECT emb FROM faces WHERE person_id=? AND px>=60", (pid,))
        if not rows:
            return
        v = sum(np.frombuffer(r["emb"], dtype=np.float32) for r in rows)
        v = (v / (np.linalg.norm(v) + 1e-9)).astype(np.float32)
        self.db.x("UPDATE people SET cent=? WHERE id=?", (v.tobytes(), pid))

    # ------------------------------------------------------------------ cài đặt
    def set_settings(self, new: dict):
        regroup = any(k in new and new[k] != self.settings.get(k) for k in ("dup_hamming", "dup_seconds", "emotion_priority"))
        xmp_was = self._xmp_on()
        for k, v in new.items():
            if k in DEFAULT_SETTINGS:
                self.settings[k] = type(DEFAULT_SETTINGS[k])(v)
        try:
            self._sfile.write_text(json.dumps(self.settings))
        except Exception:  # noqa: BLE001
            pass
        if "xmp_sync" in new and hasattr(self, "_xq"):
            self._xmp_settings_changed(xmp_was)
        if regroup:
            self.regroup()

    # ------------------------------------------------------------------ quét
    def open_folder(self, root: str, recursive: bool = True):
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=30)
        self._cancel = threading.Event()
        self.root = root
        with self._vcv:   # bỏ hàng dựng ảnh nét của thư mục trước
            self._vq, self._vlow = [], []
        self._catalog_seed()
        self.db.x("INSERT INTO catalog(root,recursive,opened) VALUES(?,?,?) "
                  "ON CONFLICT(root) DO UPDATE SET recursive=excluded.recursive, opened=excluded.opened",
                  (root, int(bool(recursive)), time.time()))
        self.status = dict(state="scanning", total=0, done=0, thumbs=0, quick=0, errors=0, root=root, message="Đang liệt kê file…", timing={})
        self._slock = threading.Lock()
        self._thread = threading.Thread(target=self._scan, args=(root, recursive, self._cancel), daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ catalog thư mục
    # Cache của thư mục cũ có thể đã bị dọn, nên số liệu và ảnh bìa được lưu riêng trong bảng catalog và thư mục COVERS.
    @staticmethod
    def _cover_name(root: str, i: int) -> str:
        return f"{hashlib.sha1(root.encode('utf-8', 'replace')).hexdigest()[:16]}_{i}.jpg"

    def _catalog_seed(self):
        """Lần đầu dùng catalog: đưa các thư mục có ảnh đã chấm vào, chỉ làm một lần
        để thư mục người dùng đã gỡ không tự quay lại."""
        if self.db.one("SELECT 1 FROM meta WHERE k='catalog_seeded'"):
            return
        self.db.many("INSERT OR IGNORE INTO catalog(root,recursive,opened) VALUES(?,1,0)",
                     [(r["dir"],) for r in self.db.q("SELECT DISTINCT dir FROM photos WHERE dir IS NOT NULL")])
        self.db.x("INSERT OR REPLACE INTO meta(k,v) VALUES('catalog_seeded','1')")

    def _catalog_update(self, root: str):
        """Gọi khi đọc xong thư mục: lưu số liệu và chép 4 ảnh đẹp nhất làm ảnh bìa."""
        s = self.db.one("SELECT COUNT(*) n, SUM(size) size, MIN(NULLIF(taken,0)) t0, MAX(NULLIF(taken,0)) t1 "
                        "FROM photos JOIN cur ON cur.id=photos.id")
        top = self.db.q("SELECT photos.id FROM photos JOIN cur ON cur.id=photos.id WHERE ready=1 "
                        "ORDER BY rating<0, best DESC, score DESC, photos.id LIMIT 4")
        COVERS.mkdir(parents=True, exist_ok=True)
        names = []
        for r in top:
            name = self._cover_name(root, len(names))
            try:
                shutil.copyfile(THUMBS / f"{r['id']}.jpg", COVERS / name)
                names.append(name)
            except OSError:
                pass
        self.db.x("UPDATE catalog SET n=?, size=?, t0=?, t1=?, covers=? WHERE root=?",
                  (s["n"], s["size"] or 0, s["t0"] or 0, s["t1"] or 0, json.dumps(names), root))

    def catalog(self):
        self._catalog_seed()
        marks = self.db.q("SELECT dir, SUM(rating>0) stars, SUM(rating=-1) rej FROM photos GROUP BY dir")

        def inside(d, root, rec):
            if d == root:
                return True
            return bool(rec) and bool(d) and d.startswith(root.rstrip("\\/") + os.sep)

        out = []
        for c in self.db.q("SELECT * FROM catalog"):
            root, rec = c["root"], c["recursive"]
            hit = [m for m in marks if inside(m["dir"], root, rec)]
            out.append(dict(root=root, name=os.path.basename(root.rstrip("\\/")) or root, recursive=bool(rec), opened=c["opened"],
                            n=c["n"], size=c["size"], t0=c["t0"], t1=c["t1"], ver=int(c["opened"] or 0),
                            stars=sum(m["stars"] or 0 for m in hit), rej=sum(m["rej"] or 0 for m in hit),
                            covers=json.loads(c["covers"] or "[]"),
                            missing=not root.startswith("\\\\") and not os.path.isdir(root)))  # không dò ổ mạng: có thể treo lâu
        return out

    @staticmethod
    def _explorer_paths():
        """Windows: hỏi các cửa sổ File Explorer đang mở → (thư mục đang mở, mục đang chọn).
        Người dùng kéo thả từ Explorer nên mục vừa kéo đang được chọn ở đó — đây là đường dẫn thật."""
        if sys.platform != "win32":
            return [], []
        ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "$s=New-Object -ComObject Shell.Application;"
              "foreach($w in $s.Windows()){try{$f=$w.Document.Folder.Self.Path;if($f){'D|'+$f};"
              "foreach($i in $w.Document.SelectedItems()){'S|'+$i.Path}}catch{}}")
        try:
            import subprocess
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
                               capture_output=True, timeout=8, creationflags=0x08000000)   # CREATE_NO_WINDOW
            txt = r.stdout.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return [], []
        dirs, sel = [], []
        for ln in txt.splitlines():
            ln = ln.strip().lstrip("﻿")
            if ln.startswith("D|"):
                dirs.append(ln[2:])
            elif ln.startswith("S|"):
                sel.append(ln[2:])
        return dirs, sel

    def locate(self, name: str, samples: list, budget: float = 12.0):
        """Kéo thả thư mục từ Windows vào app: trình duyệt không cho biết đường dẫn thật, chỉ có tên thư mục và vài file bên trong.
        Tìm thư mục cùng tên quanh các thư mục đã có trong Catalog (cùng ổ / cùng NAS, thường là anh em hoặc họ hàng gần),
        rồi xác nhận bằng tên + dung lượng file mẫu. Trả về đường dẫn hoặc None."""
        name = (name or "").strip()
        smp = [(str(x.get("p", "")).replace("/", os.sep), int(x.get("s", -1))) for x in (samples or [])[:12] if x.get("p")]
        end = time.time() + budget

        def ok(d):
            if name and os.path.basename(d.rstrip("\\/")).lower() != name.lower():
                return False
            if not smp:
                return bool(name)
            hit = 0
            for rel, sz in smp[:6]:
                try:
                    st = os.stat(os.path.join(d, rel))
                except OSError:
                    continue
                if sz < 0 or st.st_size == sz:
                    hit += 1
            return hit >= min(2, len(smp[:6]))

        # 1) Hỏi thẳng File Explorer (Windows): mục đang chọn / thư mục đang mở — nhanh và chính xác nhất
        ex_dirs, ex_sel = self._explorer_paths()
        for p in ex_sel:
            try:
                if os.path.isdir(p) and ok(p):
                    return p
                if not name and os.path.isfile(p) and ok(os.path.dirname(p)):   # thả file ảnh → thư mục chứa
                    return os.path.dirname(p)
            except OSError:
                pass
        for d in ex_dirs:
            try:
                c = os.path.join(d, name) if name else d
                if os.path.isdir(c) and ok(c):
                    return c
            except OSError:
                pass

        roots = ex_dirs + [r["root"] for r in self.db.q("SELECT root FROM catalog ORDER BY opened DESC")]
        if self.status.get("root"):
            roots.insert(0, self.status["root"])
        bases, seen = [], set()

        def add(p, depth):
            k = os.path.normcase(os.path.abspath(p)) if p else ""
            if p and k not in seen:
                seen.add(k)
                bases.append((p, depth))
        for d in ex_dirs:   # bên trong các cửa sổ Explorer đang mở
            add(d, 2)
        for lvl in range(1, 4):   # anh em trước, rồi họ hàng xa dần
            for r in roots:
                p = r.rstrip("\\/")
                for _ in range(lvl):
                    q = os.path.dirname(p)
                    if not q or q == p:
                        p = ""
                        break
                    p = q
                if p and not (p.startswith("\\\\") and p.count("\\") <= 3):   # không quét cả máy chủ NAS
                    add(p, lvl)
        home = os.path.expanduser("~")
        for sub in ("Desktop", "Downloads", "Pictures", "Documents", "Videos"):
            add(os.path.join(home, sub), 2)
        if sys.platform == "darwin":   # ổ ngoài, thẻ nhớ, NAS đã kết nối
            try:
                for e in os.scandir("/Volumes"):
                    if e.is_dir():
                        add(e.path, 2 if os.path.realpath(e.path) == "/" else 6)   # ổ hệ thống: dò nông
            except OSError:
                pass
        if sys.platform == "win32":
            import string
            for c in string.ascii_uppercase[3:]:   # ổ dữ liệu (D:, E:…): ảnh thường nằm sâu theo năm/tháng/khách
                d = f"{c}:\\"
                if os.path.isdir(d):
                    add(d, 6)
            add("C:\\", 2)   # ổ hệ thống: chỉ dò nông
        # tìm theo chiều rộng, XEN KẼ từng tầng giữa mọi điểm dò (để một ổ lớn không ăn hết thời gian),
        # giới hạn thời gian để ổ mạng chậm không làm treo
        visited = set()
        front = [[b] for b, _ in bases]
        for lv in range(max((dp for _, dp in bases), default=0) + 1):
            for bi, (base, depth) in enumerate(bases):
                if lv > depth or not front[bi]:
                    continue
                nxt = []
                for d in front[bi]:
                    if time.time() > end:
                        return None
                    k = os.path.normcase(d)
                    if k in visited:
                        continue
                    visited.add(k)
                    if ok(d):
                        return d
                    try:
                        with os.scandir(d) as it:
                            for e in it:
                                if not e.name.startswith((".", "$")) and e.name.lower() not in _LOCATE_SKIP \
                                        and e.is_dir(follow_symlinks=False):
                                    if name and e.name.lower() == name.lower() and ok(e.path):
                                        return e.path
                                    nxt.append(e.path)
                    except OSError:
                        pass
                front[bi] = nxt
        return None

    def catalog_remove(self, root: str):
        self.db.x("DELETE FROM catalog WHERE root=?", (root,))
        for i in range(4):
            try:
                (COVERS / self._cover_name(root, i)).unlink()
            except OSError:
                pass

    def _list_files(self, root: str, recursive: bool):
        """Liệt kê ảnh kèm (đường dẫn, mtime, dung lượng). Dùng scandir: trên Windows thông tin này đi kèm
        danh sách thư mục nên KHÔNG cần stat từng file (tránh hàng nghìn lượt hỏi qua mạng LAN)."""
        out, stack = [], [root]
        while stack:
            d = stack.pop()
            try:
                it = list(os.scandir(d))
            except OSError:
                if d == root:
                    raise
                continue
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        if recursive:
                            stack.append(e.path)
                    elif Path(e.name).suffix.lower() in ALL_EXT:
                        st = e.stat()
                        out.append((e.path, st.st_mtime, st.st_size))
                except OSError:
                    pass
        out.sort(key=lambda t: t[0].lower())
        return out

    def _scan(self, root: str, recursive: bool, cancel: threading.Event):
        try:
            files = self._list_files(root, recursive)
        except Exception as e:  # noqa: BLE001
            self.status.update(state="error", message=friendly(e))
            return
        db = self.db
        fresh = []   # ảnh mới/đổi trong lần quét này: chỉ những ảnh này được đọc sao .xmp
        todo, ids = [], []   # todo: (id, path, đã có ảnh cache?)
        with db.lock:
            for p, mt, sz in files:
                row = db.one("SELECT id,mtime,size,analyzed,ready FROM photos WHERE path=?", (p,))
                if row is None:
                    cur = db.con.execute("INSERT INTO photos(path,dir,mtime,size) VALUES(?,?,?,?)",
                                         (p, os.path.dirname(p), mt, sz))
                    pid = cur.lastrowid
                    fresh.append(pid)
                    todo.append((pid, p, False))
                else:
                    pid = row["id"]
                    changed = row["mtime"] != mt or row["size"] != sz
                    if changed:
                        db.con.execute("UPDATE photos SET mtime=?,size=?,analyzed=0,ready=0,err=NULL WHERE id=?",
                                       (mt, sz, pid))
                        fresh.append(pid)
                        todo.append((pid, p, False))
                    elif row["analyzed"] and not (THUMBS / f"{pid}.jpg").exists():  # cache đã bị dọn: đọc lại
                        db.con.execute("UPDATE photos SET analyzed=0,ready=0,err=NULL WHERE id=?", (pid,))
                        todo.append((pid, p, False))
                    elif not row["analyzed"]:
                        todo.append((pid, p, bool(row["ready"]) and (PREVIEWS / f"{pid}.jpg").exists()))
                ids.append(pid)
            db.con.execute("DELETE FROM cur")
            db.con.executemany("INSERT INTO cur(id) VALUES(?)", [(i,) for i in ids])
            db.con.commit()
        self.status.update(total=len(ids), done=len(ids) - len(todo), thumbs=len(ids) - len(todo),
                           message=f"Đang đọc {len(todo)} ảnh mới…" if todo else "Đã có trong bộ nhớ đệm")

        # nền: không làm chậm tiến độ quét. Lần đầu quét thư mục từ bản có đọc .xmp: đọc cho mọi ảnh còn 0 sao
        # (đám cũ đã chấm bằng Photo Mechanic/Lightroom trước bản này); sau đó chỉ ảnh mới/đổi.
        # Mỗi lần mở: đọc lại .xmp đi kèm ảnh nào mới hơn lần trước (kết quả lọc từ máy khác trong mạng LAN).
        xkey = "xmp_done:" + root
        first = not db.one("SELECT 1 FROM meta WHERE k=?", (xkey,))
        self._xmp_thread = threading.Thread(target=self._xmp_pass, args=(ids, ids if first else fresh, xkey if first else None),
                                            daemon=True)
        self._xmp_thread.start()
        t0 = time.time()
        perf = dict(t=round(t0), root=root, total=len(ids), todo=len(todo), cached=sum(1 for t in todo if t[2]),
                    cpu=os.cpu_count(), net=None, samples=[])
        stop_perf = threading.Event()

        def sampler():   # ghi tiến độ mỗi 10 giây để biết khâu nào chậm (đọc file hay phân tích)
            while not stop_perf.wait(10):
                st = self.status
                perf["samples"].append([round(time.time() - t0), st.get("quick", 0), st.get("thumbs", 0), st.get("done", 0)])
        threading.Thread(target=sampler, daemon=True).start()
        net = _is_network(root)
        perf["net"] = net   # ổ mạng: độ trễ cao → dùng nhiều luồng hơn để các lượt đọc chồng lên nhau
        io_n = IO_WORKERS * 4 if net else IO_WORKERS
        qa_n = 64 if net else IO_WORKERS * 2
        # Giai đoạn A: thumbnail gần như tức thì từ JPEG nhỏ trong file RAW (~10 KB/ảnh) → lưới ảnh hiện ngay
        quick = [(pid, p) for pid, p, cached in todo if not cached and Path(p).suffix.lower() in RAW_EXT]
        if quick:
            self.status.update(message="Đang tạo thumbnail nhanh…")

            def qa(item):
                if cancel.is_set():
                    return
                pid, path = item
                try:
                    r = self.an.quick_thumb(path)
                    if r:
                        (THUMBS / f"{pid}.jpg").write_bytes(r["thumb"])
                        self.db.x("UPDATE photos SET w=?,h=?,taken=?,ready=1,tv=1 WHERE id=? AND ready=0",
                                  (r["w"], r["h"], r["taken"] or time.time(), pid))
                except Exception:  # noqa: BLE001
                    pass
                with self._slock:   # để giao diện làm mới lưới ngay khi có thêm thumbnail
                    self.status["quick"] = self.status.get("quick", 0) + 1
            with ThreadPoolExecutor(max_workers=qa_n, initializer=_low_prio) as pa:
                list(pa.map(qa, quick))
        self.status["timing"]["thumb_s"] = round(time.time() - t0, 1)
        # Pha 1 (I/O): đọc ảnh xem trước → thumbnail hiện ngay. Pha 2 (CPU): độ nét, khuôn mặt… chạy nền song song.
        n = os.cpu_count() or 2
        cpu = n if n <= 8 else min(16, n - 1)   # máy nhiều nhân: chừa một nhân để giao diện vẫn mượt
        p1 = ThreadPoolExecutor(max_workers=io_n, initializer=_low_prio)
        p2 = ThreadPoolExecutor(max_workers=cpu, initializer=_low_prio)

        def bump(**kw):
            with self._slock:
                for k, v in kw.items():
                    self.status[k] += v

        waiting = [0]   # số ảnh đã giải mã đang chờ, giới hạn để không chiếm nhiều bộ nhớ

        def phase2(pid, img=None):
            if img is not None:
                with self._slock:
                    waiting[0] -= 1
            if cancel.is_set():
                return
            ui_yield()
            try:
                ok = self._analyze_cached(pid, img)
            except Exception as e:  # noqa: BLE001
                self.db.x("UPDATE photos SET analyzed=1, err=? WHERE id=?", (str(e)[:200], pid))
                ok = False
            bump(done=1, errors=0 if ok else 1)

        def phase1(pid, path, cached):
            if cancel.is_set():
                return
            ui_yield()
            img = None
            if not cached:
                try:
                    img = self._prepare_one(pid, path)
                except Exception as e:  # noqa: BLE001
                    self.db.x("UPDATE photos SET analyzed=1, ready=0, err=? WHERE id=?", (str(e)[:200], pid))
                    bump(done=1, thumbs=1, errors=1)
                    return
            bump(thumbs=1)
            with self._slock:
                if img is not None and waiting[0] >= cpu * 2:
                    img = None   # hàng chờ dài: phân tích sẽ đọc lại từ ảnh cache
                elif img is not None:
                    waiting[0] += 1
            p2.submit(phase2, pid, img)

        for pid, path, cached in todo:
            p1.submit(phase1, pid, path, cached)
        p1.shutdown(wait=True)
        self.status["timing"]["read_s"] = round(time.time() - t0, 1)
        self.status.update(message="Đang phân tích chất lượng + khuôn mặt…")
        p2.shutdown(wait=True)
        self.status["timing"]["all_s"] = round(time.time() - t0, 1)
        stop_perf.set()
        perf.update(self.status["timing"], cancelled=cancel.is_set(), errors=self.status.get("errors", 0))
        try:   # nhật ký tốc độ (chỉ số liệu thời gian, không có nội dung ảnh) — giữ 50 lần gần nhất
            pf = HOME / "perf.log"
            old = pf.read_text(encoding="utf-8").splitlines()[-49:] if pf.exists() else []
            pf.write_text("\n".join(old + [json.dumps(perf, ensure_ascii=False)]) + "\n", encoding="utf-8")
        except OSError:
            pass
        if cancel.is_set():
            self.status.update(state="idle", message="Đã huỷ")
            return
        self.status.update(message="Đang gom khuôn mặt theo người…")
        self.cluster()
        self.regroup()
        self._smile_backfill(cancel)
        self._focus_backfill(cancel)
        self._scene_backfill(cancel)
        try:
            self._catalog_update(root)
            self.trim_cache()
        except Exception as e:  # noqa: BLE001  catalog lỗi không được làm hỏng phiên lọc
            print("catalog:", e, file=sys.stderr)
        self.status.update(state="done", message="Hoàn tất")
        self.view_all()
        # khâu nền sau cùng (vector nội dung ảnh cho gu chọn ảnh): không giữ trạng thái "Hoàn tất" hay việc dựng ảnh nét;
        # vẫn chạy trong luồng quét nên mở thư mục khác sẽ huỷ (cancel) như các khâu bổ sung khác
        if not cancel.is_set():
            self._clip_backfill(cancel)

    def _xmp_pass(self, all_ids, ids, done_key=None):
        """Nền: (1) .xmp đi kèm mới hơn lần đọc/ghi trước → lấy theo .xmp; (2) sao cũ (XMP nhúng JPEG…) cho ảnh 0 sao —
        ids: lần đầu là cả thư mục, sau đó chỉ ảnh mới; done_key ghi vào meta để lượt (2) cả thư mục chỉ chạy một lần."""
        try:
            self.xmp_requeue()   # lần trước thoát app khi chưa ghi xong .xmp
        except Exception as e:  # noqa: BLE001
            print("xmp:", e, file=sys.stderr)
        try:
            self._import_xmp(all_ids)
        except Exception as e:  # noqa: BLE001
            print("xmp đọc:", e, file=sys.stderr)
        if ids and self._import_xmp_ratings(ids) and done_key:
            self.db.x("INSERT OR REPLACE INTO meta(k,v) VALUES(?,'1')", (done_key,))
        elif not ids and done_key:
            self.db.x("INSERT OR REPLACE INTO meta(k,v) VALUES(?,'1')", (done_key,))

    def _import_xmp(self, ids):
        """Đọc .xmp đi kèm; file đổi so với lần đọc/ghi trước (lệch mtime > 1.5 s — chịu được NAS làm tròn giờ) → ghi đè
        sao (+ nhãn nếu là nhãn màu app hiểu) trong app. Không đánh dấu ghi lại .xmp. Trả số ảnh đã cập nhật.
        Liệt kê mỗi thư mục một lần, chỉ mở file có mtime đổi; ảnh vừa được chấm trong lúc đọc thì không bị ghi đè."""
        rows = []
        for k in range(0, len(ids), 500):
            part = ids[k:k + 500]
            rows += self.db.q(f"SELECT id,path,xmt FROM photos WHERE id IN ({','.join('?' * len(part))})", part)
        if not rows:
            return 0
        names = {}
        for r in rows:
            d = os.path.dirname(r["path"])
            if d not in names:
                names[d] = dir_names(d)
        rows = [r for r in rows if names[os.path.dirname(r["path"])]]   # thư mục không có .xmp nào: bỏ qua

        def one(r):
            try:
                p, ok = sidecar(r["path"], names[os.path.dirname(r["path"])])
                if not ok:
                    return None
                mt = os.stat(p).st_mtime
                if r["xmt"] is not None and abs(mt - r["xmt"]) <= 1.5:
                    return None
                data = _xs._read_file(p)
                return _xs._xmp_parse(data), _xs._label_parse(data), mt
            except Exception:  # noqa: BLE001
                return None
        with ThreadPoolExecutor(max_workers=IO_WORKERS) as ex:
            got = list(ex.map(one, rows))
        q = getattr(self, "_xq", {})
        upd, seen = [], []
        for r, g in zip(rows, got):
            if not g or r["id"] in q:   # đang chờ ghi = vừa chấm trong app → app thắng
                continue
            rating, label, mt = g
            if rating is None:
                seen.append((mt, r["id"], r["xmt"]))   # .xmp không có sao (vd chỉ chú thích): chỉ nhớ mtime
            else:
                upd.append((rating, label, mt, r["id"], r["xmt"]))
        if seen:
            self.db.many("UPDATE photos SET xmt=? WHERE id=? AND xmt IS ?", seen)
        n = 0
        if upd:
            with self.db.lock:
                before = self.db.con.total_changes
                self.db.many("UPDATE photos SET rating=?, label=COALESCE(?, label), rsrc=0, xmt=? "
                             "WHERE id=? AND xmt IS ? AND xdirty=0", upd)
                n = self.db.con.total_changes - before
            st = getattr(self, "status", None)
            if n and st is not None:
                st["xver"] = st.get("xver", 0) + 1
        return n

    def _import_xmp_ratings(self, ids):
        """Nhập sao Photo Mechanic/Lightroom từ .xmp cho ảnh còn 0 sao trong app. rsrc giữ 0. Lỗi không làm hỏng lần quét.
        Trả True khi đã đọc xong (kể cả không có gì để nhập), False khi gặp lỗi."""
        try:
            todo = []
            for k in range(0, len(ids), 500):
                part = ids[k:k + 500]
                todo += [(r["id"], r["path"]) for r in
                         self.db.q(f"SELECT id,path FROM photos WHERE rating=0 AND id IN ({','.join('?' * len(part))})", part)]
            if not todo:
                return True
            with ThreadPoolExecutor(max_workers=IO_WORKERS) as ex:
                got = list(ex.map(lambda t: read_xmp_rating(t[1]), todo))
            upd = [(g, t[0]) for t, g in zip(todo, got) if g]
            if upd:
                self.db.many("UPDATE photos SET rating=? WHERE id=? AND rating=0", upd)
            return True
        except Exception as e:  # noqa: BLE001
            print("xmp:", e, file=sys.stderr)
            return False

    # ------------------------------------------------------------------ .xmp cạnh ảnh gốc (máy khác mở cùng thư mục)
    XMP_ERR = "Không ghi được .xmp vào thư mục này — kiểm tra quyền ghi trên NAS"

    def _xmp_init(self):
        self._xq: OrderedDict[int, int] = OrderedDict()   # id → số thứ tự lần đánh dấu (để biết bị đánh dấu lại trong lúc ghi)
        self._xseq = 0
        self._xlock = threading.Lock()      # hàng đợi
        self._xflock = threading.Lock()     # chỉ một lượt ghi cùng lúc (luồng nền, nút Ghi lại, lúc thoát)
        self._xev = threading.Event()
        self._xfirst = self._xlast = 0.0

    def _xmp_on(self):
        return bool(int((getattr(self, "settings", None) or {}).get("xmp_sync", 1)))

    def _xmp_mark(self, ids, force=False):
        """Ảnh vừa đổi sao/nhãn: ghi cờ xdirty vào DB (còn nguyên nếu app thoát trước khi kịp ghi .xmp) và đưa vào
        hàng đợi cho luồng nền (khi công tắc bật, hoặc force = nút Ghi lại)."""
        if not hasattr(self, "_xq"):   # Library dựng tay trong bài thử (chưa có hàng đợi)
            return
        ids = [int(i) for i in ids]
        if not ids:
            return
        self.db.many("UPDATE photos SET xdirty=1 WHERE id=?", [(i,) for i in ids])
        if not force and not self._xmp_on():
            return
        now = time.time()
        with self._xlock:
            for i in ids:
                self._xseq += 1
                self._xq.pop(i, None)
                self._xq[i] = self._xseq
            self._xlast = now
            self._xfirst = self._xfirst or now
        self._xev.set()

    def xmp_requeue(self):
        """Đưa lại vào hàng đợi các ảnh còn cờ xdirty (lần trước thoát app khi chưa ghi xong, hoặc NAS lỗi)."""
        if not self._xmp_on():
            return 0
        ids = [r["id"] for r in self.db.q("SELECT p.id FROM photos p JOIN cur ON cur.id=p.id WHERE p.xdirty=1")]
        self._xmp_mark(ids)
        return len(ids)

    def xmp_flush(self):
        """Ghi .xmp cho mọi ảnh đang chờ. Cặp RAW+JPEG cùng tên dùng chung một .xmp: thao tác sau cùng thắng.
        Lỗi (NAS không cho ghi, rớt mạng) → giữ lại để thử lại, báo trong status."""
        with self._xflock:
            return self._xmp_flush()

    def _xmp_flush(self):
        with self._xlock:
            snap = list(self._xq.items())
            self._xfirst = 0.0
        if not snap:
            return dict(written=0, failed=0)
        rows = {}
        ids = [i for i, _ in snap]
        for k in range(0, len(ids), 500):
            part = ids[k:k + 500]
            for r in self.db.q(f"SELECT id,path,dir,rating,label FROM photos WHERE id IN ({','.join('?' * len(part))})", part):
                rows[r["id"]] = r
        stem = lambda path: os.path.normcase(os.path.splitext(path)[0])   # noqa: E731
        groups: OrderedDict[str, list] = OrderedDict()   # sidecar → [ids], giá trị lấy theo id cuối
        for i, _ in snap:
            r = rows.get(i)
            if not r:
                continue
            g = groups.pop(stem(r["path"]), [])
            g.append(i)
            groups[stem(r["path"])] = g
        names, sibs = {}, {}
        written = failed = 0
        done, xmts = [], []
        for key, g in groups.items():
            r = rows[g[-1]]
            d = os.path.dirname(r["path"])
            try:
                if d not in names:
                    names[d] = dir_names(d)
                p, exists = sidecar(r["path"], names[d])
                old = None
                if exists:
                    with open(p, "rb") as f:
                        old = f.read()
                new = merge_xmp(old, int(r["rating"] or 0), r["label"] or "")
                if new is not None and new != old:
                    write_atomic(p, new)
                    names[d][os.path.basename(p).lower()] = os.path.basename(p)
                    written += 1
                if new is not None or exists:
                    mt = os.stat(p).st_mtime
                    if d not in sibs:   # cặp RAW+JPEG: ảnh cùng tên trong thư mục cũng đọc chung .xmp này
                        sibs[d] = {}
                        for x in self.db.q("SELECT id,path FROM photos WHERE dir=?", (r["dir"] or d,)):
                            sibs[d].setdefault(stem(x["path"]), []).append(x["id"])
                    xmts += [(mt, i) for i in set(sibs[d].get(key, []) + g)]
                done += g
            except Exception as e:  # noqa: BLE001
                failed += len(g)
                print("xmp ghi:", r["path"], e, file=sys.stderr)
        if xmts:
            self.db.many("UPDATE photos SET xmt=? WHERE id=?", xmts)
        seq = dict(snap)
        cleared = []
        with self._xlock:
            for i in done:
                if self._xq.get(i) == seq.get(i):
                    self._xq.pop(i, None)
                    cleared.append((i,))
        if cleared:
            self.db.many("UPDATE photos SET xdirty=0 WHERE id=?", cleared)
        if failed:
            self.status["xmp_err"] = self.XMP_ERR
        else:
            self.status.pop("xmp_err", None)
        return dict(written=written, failed=failed)

    def xmp_rewrite_all(self):
        """Nút «Ghi lại .xmp cho cả thư mục»: đưa mọi ảnh đã chấm/gắn nhãn (hoặc đã từng có .xmp) vào hàng đợi và
        đánh thức luồng nền ghi ngay — trả lời liền, không bắt giao diện chờ hàng nghìn lần ghi qua NAS."""
        ids = [r["id"] for r in self.db.q(
            "SELECT p.id FROM photos p JOIN cur ON cur.id=p.id WHERE p.rating<>0 OR IFNULL(p.label,'')<>'' OR p.xmt IS NOT NULL")]
        self._xmp_mark(ids, force=True)
        with self._xlock:
            self._xfirst = 1.0   # coi như đã chờ quá 10 giây → ghi ngay
        self._xev.set()
        return dict(n=len(ids))

    def xmp_shutdown(self, timeout=5.0):
        """Trước khi thoát app: ghi nốt hàng đợi (tối đa timeout giây) để máy kia không thiếu mấy tấm chấm cuối."""
        if not hasattr(self, "_xq"):
            return
        t = threading.Thread(target=self.xmp_flush, daemon=True)
        t.start()
        t.join(timeout)

    def _xmp_settings_changed(self, was_on):
        on = self._xmp_on()
        if was_on and not on:   # tắt: bỏ hàng đợi và cảnh báo (cờ xdirty còn đó để bật lại thì ghi bù)
            with self._xlock:
                self._xq.clear()
                self._xfirst = 0.0
            self.status.pop("xmp_err", None)
        elif on and not was_on:
            self.xmp_requeue()

    def _xmp_writer(self):
        """Luồng nền: ghi khi 2 giây không có thay đổi mới hoặc đã chờ 10 giây; lỗi thì 15 giây sau thử lại."""
        while True:
            self._xev.wait(15)
            self._xev.clear()
            while True:
                with self._xlock:
                    pend, last, first = bool(self._xq), self._xlast, self._xfirst
                if not pend:
                    break
                now = time.time()
                if now - last >= 2 or (first and now - first >= 10) or not first:
                    try:
                        r = self.xmp_flush()
                    except Exception as e:  # noqa: BLE001
                        print("xmp:", e, file=sys.stderr)
                        r = dict(failed=1)
                    if r.get("failed"):
                        break   # chờ 15 giây (hoặc lần chấm kế) rồi thử lại
                else:
                    time.sleep(0.3)

    def _smile_backfill(self, cancel):
        """Ảnh đã phân tích từ bản cũ chưa có điểm nụ cười: đo bổ sung từ ảnh cache (không đọc lại file RAW)."""
        if not self.an.has_smile:
            return
        rows = self.db.q("SELECT p.id FROM photos p JOIN cur ON cur.id=p.id WHERE p.analyzed=1 AND p.smile IS NULL")
        todo = [r["id"] for r in rows if (PREVIEWS / f"{r['id']}.jpg").exists()]
        if not todo:
            return
        self.status.update(message=f"Đang nhận diện nụ cười ({len(todo)} ảnh)…")

        def one(pid):
            if cancel.is_set():
                return pid, None
            ui_yield()
            img = cv2.imread(str(PREVIEWS / f"{pid}.jpg"))
            if img is None:
                return pid, -1.0
            h, w = img.shape[:2]
            if max(h, w) > ANALYSIS_SIDE:
                k = ANALYSIS_SIDE / max(h, w)
                img = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
            try:
                return pid, float(self.an.smile_only(img))
            except Exception:  # noqa: BLE001
                return pid, -1.0
        n = os.cpu_count() or 4
        done = []
        with ThreadPoolExecutor(max_workers=n if n <= 8 else min(16, n - 1), initializer=_low_prio) as ex:
            for pid, sm in ex.map(one, todo):
                if sm is not None:
                    done.append((sm, pid))
                if len(done) >= 200:
                    self.db.many("UPDATE photos SET smile=? WHERE id=?", done)
                    done = []
        if done:
            self.db.many("UPDATE photos SET smile=? WHERE id=?", done)

    def _focus_backfill(self, cancel):
        """Ảnh đã phân tích từ bản cũ chưa có điểm nét: đo bổ sung từ ảnh cache (không đọc lại file RAW)."""
        rows = self.db.q("SELECT p.id FROM photos p JOIN cur ON cur.id=p.id WHERE p.analyzed=1 AND p.focus_x IS NULL")
        todo = [r["id"] for r in rows if (PREVIEWS / f"{r['id']}.jpg").exists()]
        if not todo:
            return
        self.status.update(message=f"Đang dò điểm nét ({len(todo)} ảnh)…")

        def one(pid):
            if cancel.is_set():
                return pid, None
            ui_yield()
            img = cv2.imread(str(PREVIEWS / f"{pid}.jpg"), cv2.IMREAD_GRAYSCALE)
            if img is None:
                return pid, (-1.0, -1.0, 0.0)
            h, w = img.shape[:2]
            if max(h, w) > ANALYSIS_SIDE:
                k = ANALYSIS_SIDE / max(h, w)
                img = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
            try:
                return pid, focus_point(img)
            except Exception:  # noqa: BLE001
                return pid, (-1.0, -1.0, 0.0)
        n = os.cpu_count() or 4
        done = []
        with ThreadPoolExecutor(max_workers=n if n <= 8 else min(16, n - 1), initializer=_low_prio) as ex:
            for pid, fp in ex.map(one, todo):
                if fp is not None:
                    done.append((fp[0], fp[1], fp[2], pid))
                if len(done) >= 200:
                    self.db.many("UPDATE photos SET focus_x=?,focus_y=?,focus_c=? WHERE id=?", done)
                    done = []
        if done:
            self.db.many("UPDATE photos SET focus_x=?,focus_y=?,focus_c=? WHERE id=?", done)

    def _scene_backfill(self, cancel):
        """Ảnh KHÔNG người từ bản cũ chưa có nhãn cảnh: phân loại bổ sung từ ảnh cache (nếu có model CLIP)."""
        from . import scene as _scene
        if not _scene.available():
            return
        rows = self.db.q("SELECT p.id FROM photos p JOIN cur ON cur.id=p.id "
                         "WHERE p.analyzed=1 AND (p.nfaces=0 OR p.nfaces IS NULL) AND p.scene IS NULL")
        todo = [r["id"] for r in rows if (PREVIEWS / f"{r['id']}.jpg").exists()]
        if not todo:
            return
        self.status.update(message=f"Đang phân loại ảnh cảnh ({len(todo)} ảnh)…")

        def one(pid):
            if cancel.is_set():
                return pid, None
            ui_yield()
            img = cv2.imread(str(PREVIEWS / f"{pid}.jpg"), cv2.IMREAD_COLOR)
            if img is None:
                return pid, ("", None, None)
            r = _scene.classify_full(img)   # kèm vector nội dung ảnh: khâu CLIP nền khỏi tính lại
            if not r:
                return pid, ("", None, None)
            return pid, (r[0] or "", r[1], np.asarray(r[2], np.float32).astype(np.float16).tobytes())
        mid = _scene.MODEL_ID
        sql = "UPDATE photos SET scene=?,scene_c=?,clip=COALESCE(?,clip),clipv=CASE WHEN ? IS NULL THEN clipv ELSE ? END WHERE id=?"
        done = []
        with ThreadPoolExecutor(max_workers=2, initializer=_low_prio) as ex:   # CLIP nặng -> ít luồng
            for pid, res in ex.map(one, todo):
                if res is not None:
                    done.append((res[0] or None, res[1], res[2], res[2], mid, pid))
                if len(done) >= 100:
                    self.db.many(sql, done); done = []
        if done:
            self.db.many(sql, done)

    def _clip_backfill(self, cancel):
        """Vector nội dung ảnh (CLIP) cho ảnh thư mục đang mở: thiếu hoặc khác phiên bản model -> tính từ ảnh cache."""
        from . import scene as _scene
        if not _scene.available():
            return
        mid = _scene.MODEL_ID
        rows = self.db.q("SELECT p.id FROM photos p JOIN cur ON cur.id=p.id "
                         "WHERE p.analyzed=1 AND p.err IS NULL AND (p.clip IS NULL OR p.clipv IS NULL OR p.clipv!=?)", (mid,))
        todo = [r["id"] for r in rows if (PREVIEWS / f"{r['id']}.jpg").exists()]
        if not todo:   # chạy sau "Hoàn tất" như một khâu nền: không đổi dòng trạng thái
            return

        def one(pid):
            if cancel.is_set():
                return pid, None
            ui_yield()
            img = cv2.imread(str(PREVIEWS / f"{pid}.jpg"), cv2.IMREAD_COLOR)
            if img is None:
                return pid, None
            v = _scene.embed(img)
            return pid, (None if v is None else np.asarray(v, np.float32).astype(np.float16).tobytes())
        sql = "UPDATE photos SET clip=?,clipv=? WHERE id=?"
        done = []
        with ThreadPoolExecutor(max_workers=2, initializer=_low_prio) as ex:
            for pid, blob in ex.map(one, todo):
                if blob is not None:
                    done.append((blob, mid, pid))
                if len(done) >= 100:
                    self.db.many(sql, done); done = []
        if done:
            self.db.many(sql, done)

    @staticmethod
    def _clip_vec(row, mid=None):
        """Vector CLIP đã giải mã (float32, chuẩn hoá L2) hoặc None nếu thiếu / khác phiên bản model / sai độ dài.
        mid: tên phiên bản model đã đọc sẵn (scene.MODEL_ID stat() file mỗi lần đọc — đọc một lần cho cả loạt ảnh)."""
        if mid is None:
            from . import scene as _scene
            mid = _scene.MODEL_ID
        try:
            blob, ver = row["clip"], row["clipv"]
        except (KeyError, IndexError):
            return None
        if not blob or ver != mid or len(blob) != 1024:
            return None
        v = np.frombuffer(blob, np.float16).astype(np.float32)
        n = float(np.linalg.norm(v))
        return v / n if n > 1e-9 else None

    def _prepare_one(self, pid: int, path: str):
        """Pha 1: đọc ảnh xem trước, ghi thumbnail + ảnh cache, đánh dấu ready (hiện được ngay trên lưới)."""
        r = self.an.prepare(path)
        for sd in list(self._vsides):   # đọc lại ảnh (file đổi / cache cũ) thì bản nét cũ không còn đúng
            try:
                (VIEWS / f"{pid}_{sd}.jpg").unlink()
            except OSError:
                pass
        (THUMBS / f"{pid}.jpg").write_bytes(r["thumb"])
        (PREVIEWS / f"{pid}.jpg").write_bytes(r["prev"])
        taken = r["taken"] or os.path.getmtime(path)
        self.db.x("UPDATE photos SET w=?,h=?,taken=?,ready=1,tv=2,err=NULL WHERE id=?", (r["w"], r["h"], taken, pid))
        return r["img"]

    def _analyze_cached(self, pid: int, img=None) -> bool:
        """Pha 2: phân tích từ ảnh cache trên ổ đĩa máy (không đụng tới thẻ nhớ nữa)."""
        row = self.db.one("SELECT w,h FROM photos WHERE id=?", (pid,))
        if img is None:
            f = PREVIEWS / f"{pid}.jpg"
            img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR) if f.exists() else None
        if img is None:
            raise ValueError("thiếu ảnh cache")
        h, w = img.shape[:2]
        if max(h, w) > ANALYSIS_SIDE:   # ảnh cache có thể lớn hơn cỡ phân tích (giữ nguyên JPEG nhúng để xem cho nét)
            k = ANALYSIS_SIDE / max(h, w)
            img = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
        r = self.an.analyze_image(img, row["w"], row["h"])
        crops = []
        with self.db.lock:
            old = self.db.q("SELECT id FROM faces WHERE photo_id=?", (pid,))
            for o in old:
                try:
                    (FACES / f"{o['id']}.jpg").unlink()
                except OSError:
                    pass
            self.db.con.execute("DELETE FROM faces WHERE photo_id=?", (pid,))
            self.db.con.execute(
                """UPDATE photos SET sharp=?,fsharp=?,lum=?,lo=?,hi=?,dhash=?,
                   nfaces=?,ear_min=?,smile=?,focus_x=?,focus_y=?,focus_c=?,scene=?,scene_c=?,
                   clip=COALESCE(?,clip),clipv=COALESCE(?,clipv),analyzed=1,err=NULL WHERE id=?""",
                (r["sharp"], r["fsharp"], r["lum"], r["lo"], r["hi"], r["dhash"], r["nfaces"], r["ear_min"],
                 float(r.get("smile", -1.0)) if self.an.has_smile else None,
                 r.get("focus_x"), r.get("focus_y"), r.get("focus_c"), r.get("scene"), r.get("scene_c"),
                 r.get("clip") if r.get("clipv") else None, r.get("clipv") if r.get("clip") else None, pid))
            for fc in r["faces"]:
                cur = self.db.con.execute(
                    "INSERT INTO faces(photo_id,fx,fy,fw,fh,det,px,ear,emb,yaw,vert,smile) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, fc["fx"], fc["fy"], fc["fw"], fc["fh"], fc["det"], fc["px"], fc["ear"], fc["emb"],
                     fc.get("yaw", -1.0), fc.get("vert", -1.0), float(fc.get("smile", -1.0))))
                if fc["crop"]:
                    crops.append((cur.lastrowid, fc["crop"]))
            self.db.con.commit()
        for fid, crop in crops:   # ghi file ngoài khoá để các luồng khác không phải chờ ổ đĩa
            (FACES / f"{fid}.jpg").write_bytes(crop)
        return True

    # ------------------------------------------------------------------ gom người
    def cluster(self, reset: bool = False):
        """Gán mặt chưa có người vào người gần nhất, hoặc tạo người mới (tham lam theo centroid)."""
        thr = self.settings["face_threshold"]
        db = self.db
        with db.lock:
            if reset:
                # chỉ gỡ các mặt thuộc "người chưa đặt tên"; người đã đặt tên được giữ làm mốc
                db.con.execute("""UPDATE faces SET person_id=NULL WHERE photo_id IN (SELECT id FROM cur)
                                  AND person_id IN (SELECT id FROM people WHERE name='')""")
                db.con.execute("DELETE FROM people WHERE name='' AND id NOT IN (SELECT person_id FROM faces WHERE person_id IS NOT NULL)")
                db.con.commit()
            # chỉ so với thư mục đang mở: người chưa đặt tên ở thư mục khác không được gộp vào; người đã đặt tên dùng cent bên dưới
            assigned = db.q("SELECT f.person_id, f.emb FROM faces f JOIN cur ON cur.id=f.photo_id WHERE f.person_id IS NOT NULL")
            sums: dict[int, np.ndarray] = {}
            for r in assigned:
                v = np.frombuffer(r["emb"], dtype=np.float32)
                sums[r["person_id"]] = sums.get(r["person_id"], 0) + v
            cents = {pid: s / (np.linalg.norm(s) + 1e-9) for pid, s in sums.items()}
            for r in db.q("SELECT id, cent FROM people WHERE cent IS NOT NULL"):
                if r["id"] not in cents:  # người đã đặt tên nhưng chưa có mặt nào ở thư mục này
                    cents[r["id"]] = np.frombuffer(r["cent"], dtype=np.float32).copy()
                    sums[r["id"]] = cents[r["id"]].copy()
            todo = db.q("""SELECT f.id, f.emb, f.px, f.det FROM faces f JOIN cur ON cur.id=f.photo_id
                           WHERE f.person_id IS NULL AND f.px>=60 ORDER BY f.det*f.px DESC""")
            upd = []
            ids = list(cents)                       # so một mặt với mọi người cùng lúc bằng ma trận
            mat = np.zeros((max(16, len(ids) * 2), 128), dtype=np.float32)
            for i, pid in enumerate(ids):
                mat[i] = cents[pid]
            for r in todo:
                v = np.frombuffer(r["emb"], dtype=np.float32)
                i, bs = -1, -1.0
                if ids:
                    sims = mat[:len(ids)] @ v
                    i = int(sims.argmax())
                    bs = float(sims[i])
                if i < 0 or bs < thr:
                    best = db.con.execute("INSERT INTO people(name) VALUES('')").lastrowid
                    sums[best] = v.copy()
                    i = len(ids)
                    ids.append(best)
                    if i >= len(mat):
                        mat = np.vstack([mat, np.zeros_like(mat)])
                else:
                    best = ids[i]
                    sums[best] = sums[best] + v
                mat[i] = sums[best] / (np.linalg.norm(sums[best]) + 1e-9)
                upd.append((best, r["id"]))
            db.con.executemany("UPDATE faces SET person_id=? WHERE id=?", upd)
            db.con.commit()

    def people(self):
        rows = self.db.q("""
            SELECT p.id, p.name, COUNT(DISTINCT f.photo_id) AS n,
                   (SELECT f2.id FROM faces f2 JOIN cur c2 ON c2.id=f2.photo_id
                    WHERE f2.person_id=p.id ORDER BY f2.det*f2.px DESC LIMIT 1) AS face
            FROM people p JOIN faces f ON f.person_id=p.id JOIN cur ON cur.id=f.photo_id
            GROUP BY p.id ORDER BY n DESC, p.id""")
        return [dict(id=r["id"], name=r["name"], n=r["n"], face=r["face"]) for r in rows]

    def rename_person(self, pid: int, name: str):
        self.db.x("UPDATE people SET name=? WHERE id=?", (name.strip(), pid))
        self._store_centroid(pid)

    def merge_people(self, src: int, dst: int):
        if src == dst:
            return
        self.db.x("UPDATE faces SET person_id=? WHERE person_id=?", (dst, src))
        self.db.x("DELETE FROM people WHERE id=?", (src,))

    def person_label(self, pid: int, names: dict) -> str:
        return names.get(pid) or f"Người {pid}"

    # ------------------------------------------------------------------ nhóm ảnh trùng + điểm
    def _rows(self, analyzed_only=True):
        cond = "p.analyzed=1" if analyzed_only else "p.ready=1"
        return self.db.q(f"SELECT p.* FROM photos p JOIN cur ON cur.id=p.id WHERE {cond} AND p.err IS NULL")

    @staticmethod
    def _ref(rows):
        g = [r["sharp"] for r in rows if r["sharp"] is not None]
        f = [r["fsharp"] for r in rows if r["nfaces"] and r["fsharp"]]
        return (float(np.median(g)) if g else 1.0) or 1.0, (float(np.median(f)) if f else 1.0) or 1.0

    def _sharp_val(self, r, ref_g, ref_f):
        if r["nfaces"] and r["fsharp"]:
            return r["fsharp"] / ref_f
        return (r["sharp"] or 0) / ref_g

    @staticmethod
    def _et(r):   # thời gian hiệu dụng = giờ chụp + lệch đồng bộ máy (toff). Dùng để xếp & gom theo thời gian
        return (r["taken"] or 0) + ((r["toff"] or 0) if "toff" in r.keys() else 0)

    def regroup(self):
        rows = sorted(self._rows(), key=lambda r: (self._et(r), r["path"]))
        if not rows:
            return
        ref_g, ref_f = self._ref(rows)
        S = self.settings
        score, raw = {}, {}
        for r in rows:
            sh = min(1.0, self._sharp_val(r, ref_g, ref_f) / 1.3) ** 0.8
            clip = min(1.0, ((r["lo"] or 0) + (r["hi"] or 0)) / 0.25)
            dev = min(1.0, abs((r["lum"] or 0.45) - 0.45) / 0.45)
            s = 100 * (0.65 * sh + 0.2 * (1 - clip) + 0.15 * (1 - dev))
            if 0 <= r["ear_min"] < S["ear"]:
                s *= 0.6
            score[r["id"]] = raw[r["id"]] = round(s, 1)
        groups, cur = [], [rows[0]]
        for prev, r in zip(rows, rows[1:]):
            close = abs(self._et(r) - self._et(prev)) <= S["dup_seconds"]
            same = bool(r["dhash"] and prev["dhash"]) and hamming(r["dhash"], prev["dhash"]) <= S["dup_hamming"]
            if close and same:
                cur.append(r)
            else:
                groups.append(cur)
                cur = [r]
        groups.append(cur)
        away = self._away(groups)
        upd, gid = [], 0
        for g in groups:
            for r in g:   # người quay mặt đi: trừ điểm theo tỉ lệ số người trong khung
                a, n = away.get(r["id"], (0, 0))
                if a and n >= 2:
                    score[r["id"]] = round(score[r["id"]] * (1 - min(0.4, 0.5 * a / n)), 1)
            if len(g) < 2:
                upd.append((0, 0, score[g[0]["id"]], away.get(g[0]["id"], (0, 0))[0], g[0]["id"]))
                continue
            gid += 1
            # ảnh tốt nhất: trong các ảnh đủ nét (>= 85% ảnh cao điểm nhất), ưu tiên ít người quay mặt nhất,
            # rồi (nếu bật ưu tiên cảm xúc) tới nụ cười, cuối cùng mới tới điểm chất lượng
            raw_top = max(raw[r["id"]] for r in g)
            cand = [r for r in g if raw[r["id"]] >= 0.85 * raw_top]
            emo_on = bool(S.get("emotion_priority", 1))

            def _emo(r):   # nụ cười 0..1 (xác suất "happiness" từ FER+); chưa tính/không có mặt = 0
                v = r["smile"]
                return round(v, 1) if (v is not None and v >= 0) else 0.0

            def _key(r):
                a = away.get(r["id"], (0, 0))[0]
                return (a, -_emo(r), -score[r["id"]]) if emo_on else (a, -score[r["id"]])
            top = min(cand, key=_key)["id"]
            for r in g:
                upd.append((gid, 1 if r["id"] == top else 0, score[r["id"]], away.get(r["id"], (0, 0))[0], r["id"]))
        self.db.many("UPDATE photos SET grp=?, best=?, score=?, away=? WHERE id=?", upd)

    # ------------------------------------------------------------- đồng bộ thời gian nhiều máy
    @staticmethod
    def _cam_key(path: str) -> str:
        """Danh tính máy ảnh = Hãng · Dòng máy · Số máy (serial). Đọc EXIF, nhẹ (không giải mã ảnh)."""
        try:
            ex = read_exif(path)
        except Exception:  # noqa: BLE001
            return "?"
        parts = [str(ex.get(k, "") or "").strip() for k in ("make", "model", "serial")]
        return (" · ".join(p for p in parts if p)).strip() or "?"

    @staticmethod
    def _estimate_offset(ref_ts, cam_ts, binw=2.0, snap=3.0):
        """Ước lượng số giây cần CỘNG vào giờ của 'cam' để khớp dòng thời gian 'ref'.
        Dựa trên tương quan mật độ bấm máy theo thời gian. Trả (offset_giây, độ_tin_cậy 0..1)."""
        if len(ref_ts) < 3 or len(cam_ts) < 3:
            return 0.0, 0.0
        t0 = min(min(ref_ts), min(cam_ts))
        t1 = max(max(ref_ts), max(cam_ts))
        n = int((t1 - t0) / binw) + 1
        if n < 4 or n > 4_000_000:
            return 0.0, 0.0

        def dens(ts):
            a = np.zeros(n)
            for t in ts:
                i = int((t - t0) / binw)
                if 0 <= i < n:
                    a[i] += 1
            return np.convolve(a, np.array([.25, .5, .25]), "same")   # mượt nhẹ, chịu lệch 1-2s
        a, b = dens(ref_ts), dens(cam_ts)
        a -= a.mean(); b -= b.mean()
        if a.std() < 1e-9 or b.std() < 1e-9:
            return 0.0, 0.0
        # tương quan chéo bằng FFT (np.correlate "full" là O(n²): lệch cả ngày mất hàng chục giây)
        m = 1 << int(2 * n - 1).bit_length()
        c = np.fft.irfft(np.fft.rfft(a, m) * np.conj(np.fft.rfft(b, m)), m)
        corr = np.concatenate((c[m - (n - 1):], c[:n]))   # cùng thứ tự với np.correlate(a, b, "full")
        lag = int(corr.argmax()) - (len(b) - 1)
        off = lag * binw
        peak = float(corr.max() / (len(a) * a.std() * b.std()))
        # tinh chỉnh ±2 bin ở độ phân giải 1 giây (đếm số ảnh ref trùng giây sau khi dịch)
        refset = {}
        for t in ref_ts:
            k = round(t); refset[k] = refset.get(k, 0) + 1
        best, bo = -1, off
        for o in np.arange(off - 2 * binw, off + 2 * binw + 1, 1.0):
            s = sum(refset.get(round(t + o), 0) for t in cam_ts)
            if s > best:
                best, bo = s, o
        off = bo
        if abs(off - round(off / 60) * 60) <= snap:   # sát phút tròn thì bắt về phút tròn (hay gặp)
            off = round(off / 60) * 60
        return float(off), peak

    def cameras_detect(self):
        """Chạy nền: đọc danh tính máy cho ảnh còn thiếu, rồi ước lượng độ lệch giờ giữa các máy."""
        if self.cam.get("state") == "running":
            return
        self.cam = dict(state="running", done=0, total=0, message="Đang đọc thông tin máy ảnh…", cams=[])
        threading.Thread(target=self._cameras_detect, daemon=True).start()

    def _cameras_detect(self):
        try:
            rows = self.db.q("SELECT p.id, p.path, p.taken, p.cam FROM photos p JOIN cur ON cur.id=p.id "
                             "WHERE p.ready=1 AND p.err IS NULL AND p.taken IS NOT NULL AND p.taken>0")
            todo = [r for r in rows if not r["cam"]]
            self.cam.update(total=len(todo))
            if todo:
                done = [0]
                def work(r):
                    return r["id"], self._cam_key(r["path"])
                with ThreadPoolExecutor(max_workers=8) as ex:
                    buf = []
                    for fut in as_completed([ex.submit(work, r) for r in todo]):
                        pid, key = fut.result()
                        buf.append((key, pid)); done[0] += 1
                        if len(buf) >= 200:
                            self.db.many("UPDATE photos SET cam=? WHERE id=?", buf); buf = []
                        self.cam["done"] = done[0]
                    if buf:
                        self.db.many("UPDATE photos SET cam=? WHERE id=?", buf)
                rows = self.db.q("SELECT p.id, p.path, p.taken, p.cam, p.toff FROM photos p JOIN cur ON cur.id=p.id "
                                 "WHERE p.ready=1 AND p.err IS NULL AND p.taken IS NOT NULL AND p.taken>0")
            else:
                rows = self.db.q("SELECT p.id, p.path, p.taken, p.cam, p.toff FROM photos p JOIN cur ON cur.id=p.id "
                                 "WHERE p.ready=1 AND p.err IS NULL AND p.taken IS NOT NULL AND p.taken>0")
            self.cam.update(message="Đang so dòng thời gian các máy…")
            by = {}
            for r in rows:
                by.setdefault(r["cam"] or "?", []).append(r)
            # bỏ nhóm '?' (không đọc được máy) và nhóm quá ít ảnh khỏi việc ước lượng
            named = {k: v for k, v in by.items() if k != "?" and len(v) >= 3}
            if len(named) < 2:
                self.cam = dict(state="done", done=self.cam.get("done", 0), total=self.cam.get("total", 0),
                                message="Chỉ thấy một máy — không cần đồng bộ." if len(named) <= 1
                                else "Không đủ dữ liệu để đồng bộ.", cams=[
                                    dict(key=k, n=len(v), offset=round(float(v[0]["toff"] or 0)),
                                         conf=1.0, ref=True) for k, v in named.items()])
                return
            ref_key = max(named, key=lambda k: len(named[k]))
            ref_ts = [r["taken"] for r in named[ref_key]]
            cams = [dict(key=ref_key, n=len(named[ref_key]), offset=0, conf=1.0, ref=True)]
            for k, v in named.items():
                if k == ref_key:
                    continue
                off, conf = self._estimate_offset(ref_ts, [r["taken"] for r in v])
                cams.append(dict(key=k, n=len(v), offset=int(round(off)), conf=round(conf, 2), ref=False))
            cams.sort(key=lambda c: (not c["ref"], -c["n"]))
            self.cam = dict(state="done", done=self.cam.get("done", 0), total=self.cam.get("total", 0),
                            message="", cams=cams, ref=ref_key)
        except Exception as e:  # noqa: BLE001
            self.cam = dict(state="error", done=0, total=0, message=friendly(e), cams=[])

    # ---- chỉnh theo ẢNH MỐC (kiểu "Adjust Absolute" của Photo Mechanic):
    #      mỗi máy chụp một đồng hồ có giây → mở ảnh đó → gõ giờ thấy trên đồng hồ → cả máy được chỉnh lệch.
    def _fill_cams(self):
        """Đọc danh tính máy cho mọi ảnh đang mở còn thiếu (để chỉnh lệch áp được cho cả máy)."""
        todo = self.db.q("SELECT p.id, p.path FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam IS NULL OR p.cam=''")
        if not todo:
            return 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            got = list(ex.map(lambda r: (self._cam_key(r["path"]), r["id"]), todo))
        self.db.many("UPDATE photos SET cam=? WHERE id=?", got)
        return len(got)

    @staticmethod
    def _fmt_t(ts):
        d = datetime.fromtimestamp(ts)
        return dict(date=d.strftime("%Y-%m-%d"), time=d.strftime("%H:%M:%S"))

    def cam_ref(self, pid: int):
        """Thông tin để đặt giờ thật cho một ảnh mốc: máy, giờ gốc, giờ đang dùng, số ảnh cùng máy."""
        self._fill_cams()
        r = self.db.one("SELECT id, path, taken, toff, cam FROM photos WHERE id=?", (int(pid),))
        if not r:
            return dict(error="Không tìm thấy ảnh")
        if not r["taken"]:
            return dict(error="Ảnh này không có giờ chụp (EXIF) — hãy chọn ảnh khác của máy đó")
        cam = r["cam"] or "?"
        n = self.db.one("SELECT COUNT(*) n FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam=?", (cam,))["n"]
        off = float(r["toff"] or 0)
        return dict(id=r["id"], name=os.path.basename(r["path"]), cam=cam, n=n, offset=round(off),
                    orig=self._fmt_t(r["taken"]), eff=self._fmt_t(r["taken"] + off))

    def cam_list(self):
        """Các máy trong thư mục đang mở: số ảnh, độ lệch đang dùng, ảnh đầu tiên (theo giờ chụp)."""
        self._fill_cams()
        out = []
        for c in self.db.q("SELECT p.cam k, COUNT(*) n, MAX(COALESCE(p.toff,0)) mx, MIN(COALESCE(p.toff,0)) mn "
                           "FROM photos p JOIN cur ON cur.id=p.id "
                           "WHERE p.taken IS NOT NULL AND p.taken>0 GROUP BY p.cam ORDER BY n DESC"):
            off = c["mx"] if abs(c["mx"] or 0) >= abs(c["mn"] or 0) else c["mn"]   # lệch đang dùng (kể cả âm)
            f = self.db.one("SELECT p.id FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam=? AND p.taken>0 "
                            "ORDER BY p.taken, p.id LIMIT 1", (c["k"],))
            out.append(dict(key=c["k"] or "?", n=c["n"], offset=round(off or 0), first=f["id"] if f else None))
        return dict(cams=out)

    def cam_step(self, pid: int, step: int):
        """Chuyển sang ảnh khác CÙNG MÁY theo giờ chụp: step = -2 đầu, -1 trước, 1 sau, 2 cuối."""
        r = self.db.one("SELECT taken, cam, id FROM photos WHERE id=?", (int(pid),))
        if not r or not r["cam"]:
            return dict(id=pid)
        base = "SELECT p.id FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam=? AND p.taken IS NOT NULL AND p.taken>0 "
        if step <= -2:
            x = self.db.one(base + "ORDER BY p.taken, p.id LIMIT 1", (r["cam"],))
        elif step >= 2:
            x = self.db.one(base + "ORDER BY p.taken DESC, p.id DESC LIMIT 1", (r["cam"],))
        elif step < 0:
            x = self.db.one(base + "AND (p.taken<? OR (p.taken=? AND p.id<?)) ORDER BY p.taken DESC, p.id DESC LIMIT 1",
                            (r["cam"], r["taken"], r["taken"], r["id"]))
        else:
            x = self.db.one(base + "AND (p.taken>? OR (p.taken=? AND p.id>?)) ORDER BY p.taken, p.id LIMIT 1",
                            (r["cam"], r["taken"], r["taken"], r["id"]))
        return dict(id=x["id"] if x else pid)

    def cam_settime(self, pid: int, date: str, tm: str):
        """Giờ thật của ảnh mốc (đọc trên đồng hồ trong ảnh) → độ lệch cho CẢ MÁY chụp ảnh đó."""
        r = self.db.one("SELECT taken, cam FROM photos WHERE id=?", (int(pid),))
        if not r or not r["taken"]:
            return dict(error="Ảnh này không có giờ chụp")
        if not r["cam"] or r["cam"] == "?":
            return dict(error="Không đọc được máy ảnh của file này nên không biết áp cho ảnh nào")
        tm = (tm or "").strip()
        if tm.count(":") == 1:
            tm += ":00"
        try:
            real = datetime.strptime(f"{(date or '').strip()} {tm}", "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            return dict(error="Ngày/giờ chưa đúng dạng (vd 2026-11-17 và 06:35:15)")
        off = round(real - r["taken"])
        self.cameras_apply({r["cam"]: off})
        for c in (self.cam or {}).get("cams", []):   # cập nhật bảng kết quả dò cho khớp
            if c.get("key") == r["cam"]:
                c.update(offset=off, conf=1.0, manual=True)
        n = self.db.one("SELECT COUNT(*) n FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam=?", (r["cam"],))["n"]
        return dict(ok=True, cam=r["cam"], offset=off, n=n)

    # ---- ghép cặp KHOẢNH KHẮC CHUNG: một tấm máy mốc + một tấm cùng lúc của máy cần chỉnh
    def cam_photos(self, cam: str):
        """Ảnh của một máy (đang mở, có giờ chụp) theo giờ gốc: [[id, taken, toff], ...]."""
        self._fill_cams()
        rows = self.db.q("SELECT p.id, p.taken, COALESCE(p.toff,0) toff FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam=? "
                         "AND p.taken IS NOT NULL AND p.taken>0 ORDER BY p.taken, p.id", (cam,))
        return dict(photos=[[r["id"], r["taken"], float(r["toff"])] for r in rows])

    def cam_estimate(self, ref_cam: str, cam: str):
        """Lệch đề xuất cho 'cam' so với 'ref_cam': lệch đang dùng nếu có, không thì dò tự động."""
        cur = self.db.one("SELECT MAX(ABS(COALESCE(p.toff,0))) a, MAX(COALESCE(p.toff,0)) mx, MIN(COALESCE(p.toff,0)) mn "
                          "FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam=?", (cam,))
        if cur and cur["a"]:
            off = cur["mx"] if abs(cur["mx"] or 0) >= abs(cur["mn"] or 0) else cur["mn"]
            return dict(offset=int(round(off)), conf=1.0, source="existing")
        q = ("SELECT p.taken + COALESCE(p.toff,0) t FROM photos p JOIN cur ON cur.id=p.id "
             "WHERE p.cam=? AND p.taken IS NOT NULL AND p.taken>0")
        ref = [r["t"] for r in self.db.q(q, (ref_cam,))]
        mine = [r["taken"] for r in self.db.q(q.replace("p.taken + COALESCE(p.toff,0) t", "p.taken"), (cam,))]
        off, conf = self._estimate_offset(ref, mine)
        if conf <= 0:
            return dict(offset=0, conf=0.0, source="none")
        return dict(offset=int(round(off)), conf=round(float(conf), 2), source="auto")

    def cam_pair(self, ref_id: int, pid: int):
        """Hai tấm cùng khoảnh khắc → lệch = giờ hiệu dụng tấm mốc − giờ gốc tấm kia, áp cho cả máy tấm kia."""
        self._fill_cams()
        a = self.db.one("SELECT p.taken, p.toff, p.cam FROM photos p JOIN cur ON cur.id=p.id WHERE p.id=?", (int(ref_id),))
        b = self.db.one("SELECT p.taken, p.cam FROM photos p JOIN cur ON cur.id=p.id WHERE p.id=?", (int(pid),))   # chỉ ảnh đang mở
        if not a or not b or not a["taken"] or not b["taken"]:
            return dict(error="Không tìm thấy ảnh hoặc ảnh không có giờ chụp")
        if not b["cam"] or b["cam"] == "?" or not a["cam"] or a["cam"] == "?":
            return dict(error="Không đọc được máy ảnh của tấm này")
        if a["cam"] == b["cam"]:
            return dict(error="Hai tấm cùng một máy — hãy chọn tấm của máy khác")
        off = int(round(a["taken"] + float(a["toff"] or 0) - b["taken"]))
        self.cameras_apply({b["cam"]: off})
        for c in (self.cam or {}).get("cams", []):
            if c.get("key") == b["cam"]:
                c.update(offset=off, conf=1.0, manual=True)
        n = self.db.one("SELECT COUNT(*) n FROM photos p JOIN cur ON cur.id=p.id WHERE p.cam=?", (b["cam"],))["n"]
        return dict(ok=True, cam=b["cam"], offset=off, n=n)

    def cameras_apply(self, offsets: dict):
        """offsets: {danh_tính_máy: số_giây_cộng_vào}. Ghi toff cho từng máy rồi gom nhóm lại."""
        pairs = []
        for k, v in (offsets or {}).items():
            try:
                pairs.append((float(v), k))
            except Exception:  # noqa: BLE001
                continue
        if pairs:
            self.db.many("UPDATE photos SET toff=? WHERE cam=?", pairs)
            self.regroup()
        return dict(ok=True, applied=len(pairs))

    # ------------------------------------------------------------------ hướng mặt
    AWAY_YAW = 0.32    # mũi lệch khỏi giữa hai mắt quá mức này (theo khoảng cách hai mắt) = quay ngang rõ
    AWAY_VERT = 1.6    # mắt→miệng / khoảng hai mắt vượt mức này = mặt nghiêng hẳn (gần như chụp nghiêng)
    AWAY_REL = 0.20    # trong nhóm ảnh trùng: cùng một người mà lệch hơn lần nhìn thẳng nhất mức này
    AWAY_REL_VERT = 0.6   # cao vì tay che miệng (trẻ con mút tay) làm lệch điểm miệng

    def _away(self, groups):
        """Số người không nhìn máy trong từng ảnh: {photo_id: (số người quay đi, số người trong khung)}.
        Với nhóm ảnh trùng, so từng người với chính họ ở các ảnh khác trong nhóm (đỡ nhầm với gương mặt nghiêng tự nhiên),
        và tính cả người có mặt ở phần lớn các ảnh khác nhưng không thấy mặt ở ảnh này."""
        ids = [r["id"] for g in groups for r in g]
        if not ids:
            return {}
        size = {r["id"]: (r["w"] or 1, r["h"] or 1) for g in groups for r in g}
        faces: dict[int, list] = {}
        for i in range(0, len(ids), 900):
            part = ids[i:i + 900]
            for f in self.db.q(f"SELECT photo_id,fx,fy,fw,fh,yaw,vert,person_id FROM faces WHERE photo_id IN ({','.join('?' * len(part))})", part):
                faces.setdefault(f["photo_id"], []).append(f)
        out = {}

        def known(f):   # vert < 0 = chưa đo (ảnh phân tích từ bản cũ); yaw có thể âm khi mặt quay hẳn
            return f["yaw"] is not None and f["vert"] is not None and f["vert"] >= 0

        def turned_abs(f):
            return known(f) and (abs(f["yaw"] - 0.5) > self.AWAY_YAW or f["vert"] > self.AWAY_VERT)

        for g in groups:
            if len(g) < 2:
                fs = faces.get(g[0]["id"], [])
                out[g[0]["id"]] = (sum(1 for f in fs if turned_abs(f)), len(fs))
                continue
            # ghép cùng một người giữa các ảnh: ưu tiên mã người, không có thì theo vị trí tâm mặt
            tracks: list[dict] = []
            for r in g:
                W, H = size[r["id"]]
                for f in faces.get(r["id"], []):
                    cx, cy, fw = (f["fx"] + f["fw"] / 2) * W, (f["fy"] + f["fh"] / 2) * H, f["fw"] * W
                    hit = None
                    for t in tracks:
                        if r["id"] in t["m"]:
                            continue
                        if f["person_id"] and f["person_id"] == t["pid"]:
                            hit = t
                            break
                        if hit is None and abs(cx - t["cx"]) < 0.6 * max(fw, t["fw"]) and abs(cy - t["cy"]) < 0.6 * max(fw, t["fw"]):
                            hit = t
                    if hit is None:
                        hit = dict(m={}, pid=f["person_id"], cx=cx, cy=cy, fw=fw)
                        tracks.append(hit)
                    hit["m"][r["id"]] = f
            for t in tracks:
                ok = [f for f in t["m"].values() if known(f)]
                t["dev"] = min((abs(f["yaw"] - 0.5) for f in ok), default=0.0)
                t["vert"] = min(((f["vert"] or 0) for f in ok), default=0.0)
            for r in g:
                n_away, seen = 0, 0
                for t in tracks:
                    f = t["m"].get(r["id"])
                    if f is None:
                        # người này có mặt ở phần lớn các ảnh khác trong nhóm mà ở đây không thấy mặt
                        if len(t["m"]) >= 2 and len(t["m"]) >= 0.6 * (len(g) - 1):
                            n_away += 1
                            seen += 1
                        continue
                    seen += 1
                    if turned_abs(f) or (known(f) and len(t["m"]) >= 2 and (
                            abs(f["yaw"] - 0.5) - t["dev"] > self.AWAY_REL or (f["vert"] or 0) - t["vert"] > self.AWAY_REL_VERT)):
                        n_away += 1
                out[r["id"]] = (n_away, seen)
        return out

    # ------------------------------------------------------------------ danh sách + cờ
    def photos(self):
        # Hiện MỌI file đã quét: có thumbnail (ready=1) HOẶC đọc/giải mã lỗi (err) → không xót file nào.
        # Chỉ bỏ qua file đang trong quá trình đọc (ready=0, chưa lỗi) để không nhấp nháy khi đang quét.
        rows = self.db.q("SELECT p.* FROM photos p JOIN cur ON cur.id=p.id WHERE p.ready=1 OR p.err IS NOT NULL")
        if not rows:
            return []
        S = self.settings
        online = self.online.ok
        ref_g, ref_f = self._ref([r for r in rows if r["analyzed"] and not r["err"]])
        pmap: dict[int, list[int]] = {}
        for r in self.db.q("""SELECT f.photo_id, f.person_id FROM faces f JOIN cur ON cur.id=f.photo_id
                              WHERE f.person_id IS NOT NULL"""):
            pmap.setdefault(r["photo_id"], [])
            if r["person_id"] not in pmap[r["photo_id"]]:
                pmap[r["photo_id"]].append(r["person_id"])
        # cô dâu–chú rể (chủ bộ ảnh) = 2 người có mặt RÕ & LỚN trong nhiều ảnh nhất
        couple = set()
        for r in self.db.q("""SELECT f.person_id AS pid, COUNT(DISTINCT f.photo_id) AS n
                              FROM faces f JOIN cur ON cur.id=f.photo_id
                              WHERE f.person_id IS NOT NULL AND f.px>=90
                              GROUP BY f.person_id ORDER BY n DESC LIMIT 2"""):
            if (r["n"] or 0) >= 2:
                couple.add(r["pid"])
        out = []
        for r in rows:
            flags = []
            if r["err"] or not r["analyzed"] or not r["ready"]:
                # File lỗi đọc/giải mã, hoặc chưa phân tích xong: vẫn hiện (không chấm điểm, không gắn cờ sai)
                out.append(dict(
                    id=r["id"], name=os.path.basename(r["path"]), dir=r["dir"], w=r["w"], h=r["h"], taken=self._et(r),
                    smile=-1, sharp=0, fsharp=0, lum=0, nf=0, ear=-1, rating=r["rating"], label=r["label"], grp=0, best=0,
                    score=0, people=[], flags=[], an=False, err=bool(r["err"]), tv=r["tv"], hl=False, scene=None,
                    cam=(r["cam"] if "cam" in r.keys() else None), sugg=(r["sugg"] if "sugg" in r.keys() else 0)))
                continue
            if self._sharp_val(r, ref_g, ref_f) < S["blur_ratio"]:
                flags.append("blur")
            if online:  # công cụ lọc tối / sáng / nhắm mắt chỉ hoạt động khi có mạng
                if (r["lum"] or 0) < S["dark"]:
                    flags.append("dark")
                if (r["lum"] or 0) > S["bright"]:
                    flags.append("bright")
                if 0 <= r["ear_min"] < S["ear"]:
                    flags.append("eyes")
                if (r["away"] or 0) > 0 and (r["nfaces"] or 0) >= 2:
                    flags.append("away")
            if r["grp"] and not r["best"]:
                flags.append("dup")
            # ảnh highlight: có cô dâu/chú rể, là bản giữ (không trùng kém), chưa loại,
            # không mờ/nhắm mắt/quay mặt, chất lượng khá trở lên
            hl = (bool(couple & set(pmap.get(r["id"], [])))
                  and bool(r["best"] or not r["grp"])
                  and (r["rating"] or 0) >= 0
                  and not ({"blur", "eyes", "away"} & set(flags))
                  and (r["score"] or 0) >= 60)
            out.append(dict(
                id=r["id"], name=os.path.basename(r["path"]), dir=r["dir"], w=r["w"], h=r["h"],
                taken=self._et(r), sharp=round(r["sharp"] or 0, 1), fsharp=round(r["fsharp"] or 0, 1),
                lum=round(r["lum"] or 0, 3), nf=r["nfaces"], ear=round(r["ear_min"], 3),
                smile=_num(r["smile"]),
                rating=r["rating"], label=r["label"], grp=r["grp"], best=r["best"], score=r["score"],
                away=r["away"] or 0, people=pmap.get(r["id"], []), flags=flags, an=True, err=False, tv=r["tv"], hl=hl,
                scene=(r["scene"] if "scene" in r.keys() else None),
                focus=[r["focus_x"], r["focus_y"], r["focus_c"]] if ("focus_x" in r.keys() and r["focus_x"] is not None) else None,
                cam=(r["cam"] if "cam" in r.keys() else None), sugg=(r["sugg"] if "sugg" in r.keys() else 0)))
        return out

    def faces_of(self, photo_id: int):
        return [dict(id=r["id"], x=r["fx"], y=r["fy"], w=r["fw"], h=r["fh"], person=r["person_id"], ear=round(r["ear"], 3))
                for r in self.db.q("SELECT * FROM faces WHERE photo_id=?", (photo_id,))]

    def info(self, pid: int) -> dict:
        """Thông số EXIF + histogram RGB của ảnh (tính trên ảnh cache 1600px, không đụng thẻ nhớ)."""
        path = self.path_of(pid)
        if not path:
            return {}
        if not hasattr(self, "_exif_cache"):
            self._exif_cache = {}
        ex = self._exif_cache.get(pid)
        if ex is None:
            try:
                ex = read_exif(path)
            except Exception:  # noqa: BLE001
                ex = {}
            stem = Path(path).stem
            m = re.search(r"(\d+)(?!.*\d)", stem)
            ex["frame"] = m.group(1)[-4:].zfill(4) if m else ""
            try:
                ex["size_mb"] = round(os.path.getsize(path) / 1e6, 1)
            except OSError:
                ex["size_mb"] = 0
            ex["path"] = path
            if len(self._exif_cache) > 5000:
                self._exif_cache.clear()
            self._exif_cache[pid] = ex
        out = dict(exif=ex, hist=None)
        f = PREVIEWS / f"{pid}.jpg"
        if f.exists():
            img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                b, g, r = (np.bincount(img[..., i].ravel(), minlength=256).tolist() for i in (0, 1, 2))
                mx = img.max(axis=2)
                out["hist"] = dict(r=r, g=g, b=b, hi=round(float((mx >= 250).mean()) * 100, 2),
                                   lo=round(float((mx <= 5).mean()) * 100, 2))
        return out

    def mask_png(self, pid: int, mode: str):
        """Lớp phủ trong suốt: đỏ = vùng cháy sáng, xanh = vùng mất chi tiết tối."""
        f = PREVIEWS / f"{pid}.jpg"
        if not f.exists():
            return None
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        mx = img.max(axis=2)
        m = (mx >= 250) if mode == "hi" else (mx <= 5)
        out = np.zeros((*m.shape, 4), np.uint8)
        out[m] = (40, 40, 255, 215) if mode == "hi" else (255, 150, 40, 215)   # BGRA
        ok, buf = cv2.imencode(".png", out)
        return buf.tobytes() if ok else None

    def diag(self, pid: int) -> str:
        p = self.path_of(pid)
        if not p:
            return "Không tìm thấy ảnh"
        if Path(p).suffix.lower() in RAW_EXT:
            return diag_raw(p)
        return f"File: {p}\n(Không phải RAW — hướng xoay lấy từ EXIF, OpenCV tự xử lý)"

    # ------------------------------------------------------------------ chấm điểm
    def photos_ver(self):
        """Số đổi khi dữ liệu ảnh đổi — điện thoại hỏi nhẹ trước khi tải lại cả danh sách."""
        n = self.db.one("SELECT COUNT(*) n FROM cur")["n"]
        return dict(ver=int(self.db.con.total_changes) * 100003 + int(n))

    def set_rating(self, ids, rating: int):
        rating = max(-1, min(5, int(rating)))
        self.db.many("UPDATE photos SET rating=?, rsrc=0 WHERE id=?", [(rating, int(i)) for i in ids])
        self._xmp_mark(ids)

    def set_ratings(self, pairs):
        self.db.many("UPDATE photos SET rating=?, rsrc=0 WHERE id=?", [(int(r), int(i)) for i, r in pairs])
        self._xmp_mark(i for i, _ in pairs)

    # ------------------------------------------------------------------ đám (roll) cho học gu chọn ảnh
    @staticmethod
    def _norm_root(p: str) -> str:
        return os.path.normcase(os.path.normpath(p)).rstrip("\\/") + os.sep

    def _roll_of(self, paths):
        """path -> root catalog dài nhất là tiền tố của path (ảnh không thuộc root nào thì bỏ)."""
        roots = sorted(((self._norm_root(r["root"]), r["root"]) for r in self.db.q("SELECT root FROM catalog")),
                       key=lambda t: -len(t[0]))
        out = {}
        for p in paths:
            np_ = os.path.normcase(os.path.normpath(p))
            for pre, root in roots:
                if np_.startswith(pre):
                    out[p] = root
                    break
        return out

    def _memo(self, key, build):
        """Kết quả build() giữ tới khi CSDL có ghi mới. Mọi ghi đi qua một kết nối duy nhất (self.db.con),
        nên total_changes của kết nối tăng mỗi lần đổi sao, quét, phân tích, sửa catalog/cull_log…"""
        with self.db.lock:
            ver = self.db.con.total_changes
        memo = self.__dict__.setdefault("_memo_d", {})
        hit = memo.get(key)
        if hit is not None and hit[0] == ver:
            return hit[1]
        val = build()
        memo[key] = (ver, val)   # ver đọc TRƯỚC khi tính: có ghi chen vào lúc tính thì lần sau tính lại
        return val

    def _roll_stats(self):
        """Gom ảnh đã phân tích theo dir trong SQL, rồi gán mỗi dir cho root catalog dài nhất chứa nó.
        → dict(dirs={dir: root}, n={root: số ảnh}, kept={root: số ảnh ≥ 1 sao})."""
        def build():
            roots = sorted(((self._norm_root(r["root"]), r["root"]) for r in self.db.q("SELECT root FROM catalog")),
                           key=lambda t: -len(t[0]))
            stats = self.db.q("SELECT dir, COUNT(*) n, SUM(rating>=1) k FROM photos "
                              "WHERE analyzed=1 AND err IS NULL AND dir IS NOT NULL GROUP BY dir")
            dirs, n, kept = {}, {}, {}
            for s in stats:
                nd = self._norm_root(s["dir"])   # ảnh dir/x.jpg nằm trong root ⇔ "dir/" bắt đầu bằng "root/"
                for pre, root in roots:
                    if nd.startswith(pre):
                        dirs[s["dir"]] = root
                        n[root] = n.get(root, 0) + s["n"]
                        kept[root] = kept.get(root, 0) + (s["k"] or 0)
                        break
            return dict(dirs=dirs, n=n, kept=kept)
        return self._memo("roll_stats", build)

    def _finished_rolls(self):
        st = self._roll_stats()
        out = []
        for c in self.db.q("SELECT root, opened FROM catalog ORDER BY opened DESC"):
            k, m = st["n"].get(c["root"], 0), st["kept"].get(c["root"], 0)
            if k >= 200 and m >= 0.03 * k:
                out.append(dict(root=c["root"], n=k, kept=m, opened=c["opened"]))
        return out

    def _cull_paths(self):
        """Mọi đường dẫn từng bị ✕ bởi Tự động lọc, bất kể lô đó chạy ở thư mục nào (cha hay con của đám)."""
        def build():
            out = set()
            for row in self.db.q("SELECT ids FROM cull_log"):
                try:
                    out.update(self._log_paths(row["ids"]))
                except Exception:  # noqa: BLE001
                    pass
            return frozenset(out)
        return self._memo("cull_paths", build)

    def _roll_rows(self, root: str):
        dirs = [d for d, r in self._roll_stats()["dirs"].items() if r == root]
        rows = []
        for k in range(0, len(dirs), 500):
            part = dirs[k:k + 500]
            rows += self.db.q(f"SELECT * FROM photos WHERE analyzed=1 AND err IS NULL AND dir IN ({','.join('?' * len(part))})",
                              part)
        rows.sort(key=lambda r: (r["taken"] is not None, r["taken"] or 0, r["path"]))   # như ORDER BY taken, path
        return self._feat_rows(rows, self._cull_paths())

    def _feat_rows(self, rows, logged=frozenset()):
        """Hàng ảnh (sqlite Row) → dict đủ cột cho taste.features (+ id, rating, rsrc, score, clip).
        Cô dâu/chú rể tính lại trong chính tập ảnh này (một đám hoặc thư mục đang mở)."""
        ids = [r["id"] for r in rows]
        idset = set(ids)
        cnt, pmap = {}, {}
        for k in range(0, len(ids), 900):
            part = ids[k:k + 900]
            for f in self.db.q(f"SELECT photo_id, person_id, px FROM faces WHERE person_id IS NOT NULL "
                               f"AND photo_id IN ({','.join('?' * len(part))})", part):
                if f["photo_id"] not in idset:
                    continue
                pmap.setdefault(f["photo_id"], set()).add(f["person_id"])
                if (f["px"] or 0) >= 90:
                    cnt.setdefault(f["person_id"], set()).add(f["photo_id"])
        top = sorted(cnt.items(), key=lambda kv: -len(kv[1]))[:2]
        couple = {pid for pid, s in top if len(s) >= 2}
        out = []
        for r in rows:
            d = {k: r[k] for k in ("id", "path", "sharp", "fsharp", "nfaces", "lum", "lo", "hi", "ear_min", "smile",
                                   "away", "focus_c", "scene", "grp", "best", "rating", "rsrc", "score", "clip", "clipv")}
            d["taken"] = float(r["taken"] or 0) + float(r["toff"] or 0)
            d["couple"] = bool(couple & pmap.get(r["id"], set()))
            d["in_cull_log"] = r["path"] in logged
            out.append(d)
        return out

    # ------------------------------------------------------------------ gu chọn ảnh: học, đề xuất, xuất
    @staticmethod
    def _taste_label(r):
        """(nhãn, trọng số): sao ≥ 1 = giữ (chấm hàng loạt từ đề xuất: 0.3); ✕ của Tự động lọc = bỏ 0.5; còn lại bỏ 1."""
        rt = r.get("rating") or 0
        if rt >= 1:
            return 1, (0.3 if r.get("rsrc") == 1 else 1.0)
        if rt < 0 and r.get("in_cull_log"):
            return 0, 0.5
        return 0, 1.0

    def _taste_off(self):
        r = self.db.one("SELECT v FROM meta WHERE k='taste_off'")
        try:
            v = json.loads(r["v"]) if r else []
        except (TypeError, ValueError):
            v = []
        return [str(x) for x in v] if isinstance(v, list) else []

    def _taste_rolls(self):
        off = set(self._taste_off())
        return [dict(r, on=r["root"] not in off) for r in self._finished_rolls()]

    @staticmethod
    def _taste_sig(rolls):
        return [[r["root"], int(r["kept"])] for r in rolls]

    @staticmethod
    def _taste_load(path):
        return taste.load(path) if Path(path).exists() else None

    def _taste_model(self):
        """(nguồn, mô hình, meta) của gu đang dùng: gu riêng > gu mặc định > cơ bản (điểm chất lượng sẵn có)."""
        got = self._taste_load(TASTE_FILE)
        if got:
            return ("personal", *got)
        got = self._taste_load(TASTE_DEFAULT)
        if got:
            return ("default", *got)
        return "basic", None, None

    def _clip_mat(self, rows, mid, dtype=np.float32):
        """Ma trận vector CLIP (hàng NaN = ảnh chưa có / khác phiên bản model)."""
        C = np.full((len(rows), CLIP_DIM), np.nan, dtype)
        for i, r in enumerate(rows):
            v = self._clip_vec(r, mid)
            if v is not None and v.shape == (CLIP_DIM,):
                C[i] = v
        return C

    def _taste_roll(self, root):
        rows = self._roll_rows(root)
        X = taste.features(rows)
        lab = [self._taste_label(r) for r in rows]
        y = np.array([a for a, _ in lab], np.int8)
        w = np.array([b for _, b in lab], np.float32)
        kept = [r for r in rows if (r.get("rating") or 0) >= 1]
        if kept and sum(1 for r in kept if r.get("rsrc") == 1) > 0.5 * len(kept):
            # đám chủ yếu chấm hàng loạt từ đề xuất: ảnh 0 sao có thể chỉ là chưa xem tới → nhãn bỏ yếu hơn
            w[np.array([(r.get("rating") or 0) == 0 for r in rows])] *= np.float32(0.3)
        return rows, X, y, w

    @staticmethod
    def _taste_sample(y, seed=0):
        """Chỉ số dòng dùng để học: mọi ảnh giữ + tối đa TASTE_NEG ảnh bỏ cho mỗi ảnh giữ (mẫu cố định)."""
        pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
        m = TASTE_NEG * len(pos)
        if len(neg) > m:
            neg = np.random.default_rng(seed).choice(neg, m, replace=False)
        return np.sort(np.r_[pos, neg]).astype(np.int64)

    def taste_info(self, _rolls=None):
        rolls = self._taste_rolls() if _rolls is None else _rolls
        on = [r for r in rolls if r["on"]]
        src, _, meta = self._taste_model()
        pm = (meta or {}) if src == "personal" else {}
        return dict(source=src,
                    rolls=[dict(root=r["root"], n=r["n"], kept=r["kept"], on=r["on"]) for r in rolls],
                    n_rolls=len(on), n_photos=sum(r["n"] for r in on),
                    agree=pm.get("agree"), learned=pm.get("learned"), paused=self._taste_paused(),
                    stale=self._taste_sig(on[:TASTE_ROLLS]) != (pm.get("sig") or []))

    def _taste_paused(self):
        return bool(self.db.one("SELECT 1 FROM meta WHERE k='taste_paused' AND v='1'"))

    def taste_reset(self):
        """Dùng lại gu mặc định: xoá gu riêng (HOME/taste.npz), giữ nguyên đám bật/tắt;
        tạm dừng học nền tới khi người dùng bấm Học lại."""
        self.db.x("INSERT OR REPLACE INTO meta(k,v) VALUES('taste_paused','1')")
        try:
            Path(TASTE_FILE).unlink()
        except FileNotFoundError:
            pass
        return self.taste_info()

    def taste_rolls_set(self, off):
        off = sorted({str(x) for x in (off or [])})
        self.db.x("INSERT OR REPLACE INTO meta(k,v) VALUES('taste_off',?)", (json.dumps(off, ensure_ascii=False),))
        return self.taste_info()

    def taste_learn(self, auto=False):
        """Học gu riêng (đồng bộ) từ tối đa 40 đám đã lọc xong đang bật; lưu HOME/taste.npz.
        auto=True (học nền khi mở Chọn ảnh đẹp): bỏ qua nếu đang tạm dừng sau Dùng lại gu mặc định;
        học thật (bấm Học lại) thì bỏ tạm dừng."""
        if auto and self._taste_paused():
            return self.taste_info()
        if not auto:
            self.db.x("DELETE FROM meta WHERE k='taste_paused'")
        from . import scene as _scene
        mid = _scene.MODEL_ID
        every = self._taste_rolls()
        rolls = [r for r in every if r["on"]][:TASTE_ROLLS]
        if not rolls and every and not auto:
            # bấm Học lại khi đã bỏ tick mọi đám: như Dùng lại gu mặc định (gu riêng học từ các đám đã bỏ không còn đúng),
            # nhưng không tạm dừng vì người dùng vừa yêu cầu học
            try:
                Path(TASTE_FILE).unlink()
            except FileNotFoundError:
                pass
            return dict(self.taste_info(every), note="Chưa có đám nào được chọn — đang dùng gu mặc định")
        parts, newest = [], None
        for k, r in enumerate(rolls):
            rows, X, y, w = self._taste_roll(r["root"])
            if not rows:
                continue
            if k == 0 and len(rolls) > 1:   # đám mới nhất: giữ đủ để đo độ trùng khớp
                # chỉ tính ảnh người dùng tự chấm (rsrc=0): ảnh chấm hàng loạt từ đề xuất là lựa chọn của mô hình cũ
                hand = np.array([y[i] == 1 and rows[i].get("rsrc") != 1 for i in range(len(rows))], bool)
                nk = int((y == 1).sum())
                if int(hand.sum()) >= 20 and int(hand.sum()) >= 0.5 * nk:
                    newest = (rows, X, self._clip_mat(rows, mid), hand.astype(np.int8))
            ix = self._taste_sample(y)
            parts.append((X[ix], self._clip_mat([rows[i] for i in ix], mid), y[ix], w[ix]))
        if not parts:
            return dict(self.taste_info(every), error="Chưa có đám nào đã lọc xong để học")
        got = self._taste_load(TASTE_DEFAULT)
        prior = got[0] if got else None
        lam = TASTE_LAM

        def fit(ps):
            m = taste.fit(np.vstack([p[0] for p in ps]), np.vstack([p[1] for p in ps]),
                          np.concatenate([p[2] for p in ps]).astype(np.float32),
                          np.concatenate([p[3] for p in ps]), prior=prior, lam=lam)
            return m   # chưa có CLIP để học thì full=None: chấm mọi ảnh bằng bản cơ bản của chính gu riêng
        model = fit(parts)
        agree = None
        if newest is not None and len(parts) > 1:
            rows0, X0, C0, y0 = newest
            agree = round(float(taste.agreement(fit(parts[1:]), X0, C0, y0, rows0)), 4)
        meta = dict(rolls=len(parts), rows=int(sum(len(p[2]) for p in parts)), learned=time.time(), agree=agree,
                    sig=self._taste_sig(rolls), clipv=mid, feats=list(taste.FEATS), prior=bool(prior), lam=lam)
        dest = Path(TASTE_FILE)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        taste.save(tmp, model, meta)
        os.replace(tmp, dest)
        return self.taste_info(every)

    def suggest(self, n):
        """Gắn dấu đề xuất (sugg=1) cho khoảng n tấm của thư mục đang mở; không đụng tới sao."""
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            return dict(error="Số ảnh cần chọn phải lớn hơn 0")
        from . import scene as _scene
        mid = _scene.MODEL_ID
        rows = self._feat_rows(self.db.q("SELECT p.* FROM photos p JOIN cur ON cur.id=p.id "
                                         "WHERE p.analyzed=1 AND p.err IS NULL ORDER BY p.taken, p.path"))
        src, model, meta = self._taste_model()
        C = self._clip_mat(rows, mid)
        if model is None:   # gu cơ bản (chưa học): điểm chất lượng sẵn có 0..100
            s = np.array([float(r.get("score") or 0) for r in rows], np.float64) / 100.0
        else:               # model CLIP đổi so với lúc học → chỉ dùng bản cơ bản của mô hình
            s = taste.score(model, taste.features(rows), C if (meta or {}).get("clipv") in (None, mid) else None)
        res = taste.pick(n, s, rows, C)
        if len(res["ids"]) < n:
            c = self.db.one("SELECT COUNT(*) y, SUM(p.analyzed=1) x FROM photos p JOIN cur ON cur.id=p.id")
            if (c["x"] or 0) < c["y"]:   # thư mục đang mở chưa phân tích xong: thiếu ảnh là do chưa phân tích tới
                res["note"] = f"Mới phân tích xong {c['x'] or 0}/{c['y']} ảnh — đợi phân tích xong rồi đề xuất lại"
        self.db.x("UPDATE photos SET sugg=0 WHERE id IN (SELECT id FROM cur)")
        self.db.many("UPDATE photos SET sugg=1 WHERE id=?", [(int(i),) for i in res["ids"]])
        self.db.x("INSERT OR REPLACE INTO meta(k,v) VALUES('sugg_n',?)", (str(n),))
        return dict(ids=[int(i) for i in res["ids"]], n=len(res["ids"]), note=res["note"], source=src)

    def suggest_clear(self):
        self.db.x("UPDATE photos SET sugg=0 WHERE id IN (SELECT id FROM cur)")
        return dict(ok=True)

    # Nhật ký chấm sao hàng loạt từ đề xuất: bảng rate_log riêng (không lẫn với cull_log của Tự động lọc),
    # lưu theo đường dẫn như cull_log. Hoàn tác chỉ đưa về 0 ảnh còn đúng 1 sao do đề xuất (rsrc=1).
    def suggest_rate(self):
        hit = self.db.q("SELECT p.id, p.path FROM photos p JOIN cur ON cur.id=p.id WHERE p.sugg=1 AND p.rating=0")
        if not hit:
            return dict(ok=True, n=0, batch=0, ids=[])
        self.db.many("UPDATE photos SET rating=1, rsrc=1 WHERE id=?", [(r["id"],) for r in hit])
        self._xmp_mark(r["id"] for r in hit)
        root = self._root()
        cur = self.db.x("INSERT INTO rate_log(root,time,ids) VALUES(?,?,?)",
                        (root, time.time(), json.dumps([r["path"] for r in hit])))
        self.db.x("DELETE FROM rate_log WHERE root=? AND id NOT IN (SELECT id FROM rate_log WHERE root=? ORDER BY id DESC LIMIT 20)",
                  (root, root))
        return dict(ok=True, n=len(hit), batch=cur.lastrowid, ids=[r["id"] for r in hit])

    def suggest_rate_undo(self, batch=None):
        if batch:
            row = self.db.one("SELECT id, ids FROM rate_log WHERE id=?", (int(batch),))
        else:
            row = self.db.one("SELECT id, ids FROM rate_log WHERE root=? ORDER BY id DESC LIMIT 1", (self._root(),))
        if not row:
            return dict(ok=True, ids=[], n=0)
        paths, left = self._log_paths(row["ids"]), []
        for k in range(0, len(paths), 500):
            part = paths[k:k + 500]
            left += [r["id"] for r in self.db.q(f"SELECT id FROM photos WHERE rating=1 AND rsrc=1 "
                                                 f"AND path IN ({','.join('?' * len(part))})", part)]
        self.db.many("UPDATE photos SET rating=0, rsrc=0 WHERE id=?", [(i,) for i in left])
        self._xmp_mark(left)
        self.db.x("DELETE FROM rate_log WHERE id=?", (row["id"],))
        return dict(ok=True, ids=left, n=len(left))

    def taste_export(self, dest: str):
        """Ghi dest/taste_data.npz (đặc trưng đã chuẩn hoá, CLIP, nhãn, mã đám) để luyện gu mặc định.
        Không có ảnh, tên file hay đường dẫn; giờ chụp tính từ đầu mỗi đám."""
        dest = str(dest or "")
        if not dest or not os.path.isdir(dest):
            return dict(error="Không tìm thấy thư mục để lưu")
        from . import scene as _scene
        mid = _scene.MODEL_ID
        Xs, Cs, ys, ws, rs, gs, ts = [], [], [], [], [], [], []
        for r in self._taste_rolls():
            if not r["on"]:
                continue
            rows, X, y, w = self._taste_roll(r["root"])
            if not rows:
                continue
            Xs.append(X)
            Cs.append(self._clip_mat(rows, mid, np.float16))
            ys.append(y)
            ws.append(w)
            rs.append(np.full(len(rows), len(rs), np.int32))
            gs.append(np.array([int(x.get("grp") or 0) for x in rows], np.int32))
            t = np.array([float(x.get("taken") or 0) for x in rows], np.float64)
            ts.append(t - t.min())
        if not Xs:
            return dict(error="Chưa có đám nào đã lọc xong để xuất")
        path = os.path.join(dest, "taste_data.npz")
        with open(path, "wb") as fh:
            np.savez(fh, X=np.vstack(Xs).astype(np.float32), C=np.vstack(Cs), y=np.concatenate(ys).astype(np.int8),
                     w=np.concatenate(ws).astype(np.float32), roll=np.concatenate(rs), grp=np.concatenate(gs),
                     taken=np.concatenate(ts), feats=np.array(taste.FEATS))
        return dict(ok=True, path=path, rows=int(sum(len(y) for y in ys)))

    # ------------------------------------------------------------------ nhật ký tự động lọc
    # Lưu trong CSDL nên vẫn hoàn tác được sau khi tắt app. Tự động lọc chỉ chạm ảnh chưa chấm sao,
    # nên hoàn tác là đưa ảnh về 0; ảnh đã được chấm lại sau đó thì giữ nguyên.
    # Lưu theo đường dẫn để không phụ thuộc vào id trong CSDL.
    def _rated(self, col: str, vals, rating: int):
        vals, out = list(vals), []
        for k in range(0, len(vals), 500):
            part = vals[k:k + 500]
            marks = ",".join("?" * len(part))
            out += self.db.q(f"SELECT id,path FROM photos WHERE rating=? AND {col} IN ({marks})", [rating, *part])
        return out

    @staticmethod
    def _log_paths(raw: str):
        return [p for p in json.loads(raw) if isinstance(p, str)]

    def _root(self) -> str:
        return (getattr(self, "status", None) or {}).get("root", "") or ""

    def cull_apply(self, ids):
        hit = self._rated("id", [int(i) for i in ids], 0)
        if not hit:
            return dict(id=0, n=0)
        self.db.many("UPDATE photos SET rating=-1 WHERE id=?", [(r["id"],) for r in hit])
        self._xmp_mark(r["id"] for r in hit)
        cur = self.db.x("INSERT INTO cull_log(root,time,ids) VALUES(?,?,?)",
                        (self._root(), time.time(), json.dumps([r["path"] for r in hit])))
        batch = cur.lastrowid
        self.db.x("DELETE FROM cull_log WHERE root=? AND id NOT IN (SELECT id FROM cull_log WHERE root=? ORDER BY id DESC LIMIT 20)",
                  (self._root(), self._root()))
        return dict(id=batch, n=len(hit))

    def cull_last(self):
        for row in self.db.q("SELECT id,time,ids FROM cull_log WHERE root=? ORDER BY id DESC", (self._root(),)):
            left = self._rated("path", self._log_paths(row["ids"]), -1)
            if left:
                return dict(id=row["id"], n=len(left), time=row["time"])
            self.db.x("DELETE FROM cull_log WHERE id=?", (row["id"],))
        return dict(id=0, n=0)

    def cull_undo(self, batch=None):
        target = int(batch) if batch else self.cull_last()["id"]
        row = self.db.one("SELECT ids FROM cull_log WHERE id=?", (target,))
        if not row:
            return dict(ids=[], n=0)
        left = [r["id"] for r in self._rated("path", self._log_paths(row["ids"]), -1)]
        self.db.many("UPDATE photos SET rating=0 WHERE id=?", [(i,) for i in left])
        self._xmp_mark(left)
        self.db.x("DELETE FROM cull_log WHERE id=?", (target,))
        return dict(ids=left, n=len(left))

    def cull_clear(self):
        self.db.x("DELETE FROM cull_log WHERE root=?", (self._root(),))

    def set_label(self, ids, label: str):
        if label not in LABELS:
            raise ValueError("nhãn không hợp lệ")
        self.db.many("UPDATE photos SET label=? WHERE id=?", [(label, int(i)) for i in ids])
        self._xmp_mark(ids)

    # ------------------------------------------------------------------ ảnh nét cho trình xem
    VIEW_VERSION = 2   # 2: khớp méo ống kính trước khi ghép chi tiết RAW (bản 1 bị viền đôi)

    def _view_reset(self):
        """Ảnh nét dựng bằng cách cũ thì bỏ đi (dựng lại khi xem). Đổi tên thư mục cũ ngay (tức thì, trình xem không thể
        dùng nhầm ảnh cũ) rồi xoá nó ở nền để mở app không bị chậm."""
        try:
            r = self.db.one("SELECT v FROM meta WHERE k='view_version'")
            if r and int(r["v"]) >= self.VIEW_VERSION:
                return
            old = VIEWS.with_name(f"view_old_{int(time.time())}")
            if VIEWS.exists():
                VIEWS.rename(old)
            VIEWS.mkdir(parents=True, exist_ok=True)
            self._vsides = {self._vside} if self._vside else set()
            self.db.x("INSERT OR REPLACE INTO meta(k,v) VALUES('view_version',?)", (str(self.VIEW_VERSION),))
            threading.Thread(target=shutil.rmtree, args=(old,), kwargs=dict(ignore_errors=True), daemon=True).start()
        except Exception as e:  # noqa: BLE001
            print("view reset:", e, file=sys.stderr)

    @staticmethod
    def view_file(pid: int, side: int):
        return VIEWS / f"{pid}_{side}.jpg"

    def _view_build(self, pid: int, side: int):
        f = self.view_file(pid, side)
        if f.exists():
            return
        p = self.path_of(pid)
        img = load_view(p, side) if p else None
        data = _jpg(img, 90) if img is not None else b""
        if data:
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, f)

    def _view_worker(self, bg: bool):
        while True:
            with self._vcv:
                while True:
                    job = next((j for j in self._vq if j not in self._vbusy), None)
                    # hàng nền (cả thư mục): chỉ 1 luồng, và chỉ khi không phân tích — để không làm chậm phân tích ảnh
                    if job is None and bg and self.status.get("state") not in ("scanning",):
                        job = next((j for j in self._vlow if j not in self._vbusy), None)
                    if job:
                        break
                    self._vcv.wait(2)
                low = job not in self._vq   # việc nền (cả thư mục), không phải ảnh trình xem đang cần
                for q in (self._vq, self._vlow):
                    if job in q:
                        q.remove(job)
                self._vbusy.add(job)
            try:
                if low:
                    _thread_prio(-2)
                    ui_yield()
                self._view_build(*job)
            except Exception as e:  # noqa: BLE001
                print("view:", e, file=sys.stderr)
            finally:
                if low:
                    _thread_prio(0)
                with self._vcv:
                    self._vbusy.discard(job)
                    self._vcv.notify_all()

    def view_focus(self, ids, side: int):
        """Trình xem báo ảnh đang xem + các ảnh sắp xem: dựng trước theo đúng thứ tự này (bỏ hàng đợi cũ)."""
        side = int(side)
        if side <= 0:
            return
        if side != self._vside:
            self._vside = side
            self.settings["view_side"] = side
            try:
                self._sfile.write_text(json.dumps(self.settings))
            except OSError:
                pass
        self._vsides.add(side)
        with self._vcv:
            self._vq = [(int(i), side) for i in ids if not self.view_file(int(i), side).exists()]
            self._vcv.notify_all()

    def view_all(self):
        """Sau khi phân tích xong: dựng dần ảnh nét cho cả thư mục ở nền (theo cỡ màn hình lần trước)."""
        side = self._vside
        if side <= 0 or _is_network(self.status.get("root") or ""):
            # ổ mạng / NAS: dựng cả thư mục nghĩa là kéo lại toàn bộ file RAW qua mạng (hàng trăm GB) → chỉ dựng quanh ảnh đang xem
            return
        rows = self.db.q("SELECT p.id FROM photos p JOIN cur ON cur.id=p.id WHERE p.ready=1 ORDER BY p.path")
        with self._vcv:
            self._vlow = [(r["id"], side) for r in rows if not self.view_file(r["id"], side).exists()]
            self._vcv.notify_all()

    def view_get(self, pid: int, side: int, timeout: float = 12.0):
        """Ảnh nét đã dựng; chưa có thì xếp lên đầu hàng đợi và chờ."""
        f = self.view_file(pid, side)
        if not f.exists():
            job = (pid, side)
            end = time.time() + timeout
            with self._vcv:
                if job in self._vq:
                    self._vq.remove(job)
                self._vq.insert(0, job)
                self._vcv.notify_all()
                while not f.exists() and time.time() < end:
                    if job not in self._vq and job not in self._vbusy and not f.exists():
                        break   # đã dựng nhưng lỗi
                    self._vcv.wait(0.5)
        try:
            return f.read_bytes()
        except OSError:
            return None

    def path_of(self, pid: int):
        r = self.db.one("SELECT path FROM photos WHERE id=?", (pid,))
        return r["path"] if r else None

    # ------------------------------------------------------------------ xuất
    def _xmp(self, rating: int, label: str, keywords: list[str], when: float | None = None) -> str:
        """when: giờ chụp ĐÃ đồng bộ (giờ gốc + lệch máy). Chỉ ghi khi máy có chỉnh lệch, để Lightroom nhận đúng giờ
        khi nhập ảnh (ảnh gốc không bị sửa)."""
        kw = ""
        if keywords:
            kw = "<dc:subject><rdf:Bag>" + "".join(f"<rdf:li>{escape(k)}</rdf:li>" for k in keywords) + "</rdf:Bag></dc:subject>"
        lab = f' xmp:Label="{XMP_LABEL[label]}"' if label in XMP_LABEL else ""
        tm = ""
        if when:
            s = datetime.fromtimestamp(when).strftime("%Y-%m-%dT%H:%M:%S")
            tm = f' exif:DateTimeOriginal="{s}" photoshop:DateCreated="{s}" xmp:CreateDate="{s}"'
        return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
                '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                '<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
                'xmlns:exif="http://ns.adobe.com/exif/1.0/" xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/" '
                f'xmlns:dc="http://purl.org/dc/elements/1.1/" xmp:Rating="{rating}"{lab}{tm}>{kw}'
                '</rdf:Description></rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>')

    @staticmethod
    def _synced(r):
        """Giờ chụp đã đồng bộ nếu máy có chỉnh lệch, ngược lại None (không ghi giờ vào XMP)."""
        try:
            off = r["toff"] or 0
        except (IndexError, KeyError):
            return None
        return (r["taken"] + off) if (off and r["taken"]) else None

    def _names(self):
        return {r["id"]: r["name"] for r in self.db.q("SELECT id,name FROM people")}

    def write_xmp(self, ids):
        names, n = self._names(), 0
        for pid in ids:
            r = self.db.one("SELECT * FROM photos WHERE id=?", (int(pid),))
            if not r:
                continue
            people = [x["person_id"] for x in self.db.q(
                "SELECT DISTINCT person_id FROM faces WHERE photo_id=? AND person_id IS NOT NULL", (r["id"],))]
            kws = [self.person_label(p, names) for p in people]
            Path(r["path"]).with_suffix(".xmp").write_text(self._xmp(r["rating"], r["label"], kws, self._synced(r)), encoding="utf-8")
            n += 1
        return n

    def start_export(self, ids, dest, by_person=False, template="{name}", xmp=False):
        """Chạy xuất ảnh ở nền; tiến độ lấy qua export_status(), dừng / xoá qua export_cancel()."""
        j = getattr(self, "export_job", None)
        if j and j.get("state") in ("running", "deleting"):
            return dict(error="Đang có một tác vụ xuất chạy — hãy đợi nó xong hoặc bấm Dừng ở bảng tác vụ", busy=True)
        ids = [int(i) for i in ids]
        stop = threading.Event()
        self._export_stop = stop
        self._export_made = []   # file do lần xuất này tạo ra (để xoá được nếu xuất nhầm) — không bao giờ có ảnh gốc
        self._export_dirs = []   # thư mục do lần xuất này tạo ra
        self.export_job = dict(state="running", total=len(ids), done=0, copied=0, n_errors=0, errors=[], cur="",
                               dest=str(dest), started=time.time(), removed=0)

        def work():
            try:
                r = self.export(ids, dest, by_person, template, xmp, progress=self.export_job, stop=stop)
                self.export_job.update(copied=r["copied"], errors=r["errors"], n_errors=r["n_errors"],
                                       state="stopped" if stop.is_set() else "done", ended=time.time())
                self._export_log(ids, dest, r["copied"], "stopped" if stop.is_set() else "done")
            except Exception as e:  # noqa: BLE001
                self.export_job.update(state="error", message=friendly(e), ended=time.time())
            if getattr(self, "_export_wipe", False):
                self._export_delete()
        self._export_wipe = False
        threading.Thread(target=work, daemon=True).start()
        return dict(ok=True, total=len(ids))

    def _export_log(self, ids, dest, copied, state):
        """Ghi lịch sử xuất (hiện dưới Catalog để Add vào Lightroom sau)."""
        try:
            if not copied:
                return
            n5 = 0
            for i in range(0, len(ids), 900):
                part = ids[i:i + 900]
                n5 += self.db.one(f"SELECT COUNT(*) c FROM photos WHERE rating=5 AND id IN ({','.join('?' * len(part))})", part)["c"]
            dest = os.path.abspath(str(dest))
            self.db.x("DELETE FROM export_log WHERE dest=?", (dest,))   # xuất lại cùng thư mục: giữ một dòng mới nhất
            cur = self.db.con.execute("INSERT INTO export_log(time,src,dest,n,copied,n5,state) VALUES(?,?,?,?,?,?,?)",
                                      (time.time(), self.status.get("root") or "", dest, len(ids), copied, n5, state))
            self.db.con.commit()
            self.export_job["log_id"] = cur.lastrowid
        except Exception as e:  # noqa: BLE001
            print("export log:", e, file=sys.stderr)

    def export_history(self):
        out = []
        for r in self.db.q("SELECT * FROM export_log ORDER BY time DESC LIMIT 200"):
            d = r["dest"]
            out.append(dict(id=r["id"], time=r["time"], src=r["src"], dest=d, name=os.path.basename(d.rstrip("\\/")) or d,
                            parent=os.path.basename(os.path.dirname(d.rstrip("\\/"))), n=r["n"], copied=r["copied"],
                            n5=r["n5"], state=r["state"],
                            missing=not d.startswith("\\\\") and not os.path.isdir(d)))   # không dò ổ mạng: có thể treo lâu
        return out

    def export_history_add(self, dest, src=""):
        """Thêm tay một thư mục đã xuất từ trước (khi chưa có lịch sử)."""
        dest = os.path.abspath(str(dest))
        if not os.path.isdir(dest):
            return dict(error="Không tìm thấy thư mục")
        n = 0
        try:
            n = sum(1 for e in os.scandir(dest) if Path(e.name).suffix.lower() in ALL_EXT)
        except OSError:
            pass
        self.db.x("DELETE FROM export_log WHERE dest=?", (dest,))
        self.db.x("INSERT INTO export_log(time,src,dest,n,copied,n5,state) VALUES(?,?,?,?,?,?,?)",
                  (os.path.getmtime(dest), src, dest, n, n, -1, "manual"))
        return dict(ok=True)

    def export_status(self):
        j = dict(getattr(self, "export_job", None) or dict(state="idle"))
        if j.get("state") != "idle":
            j["files"] = len(getattr(self, "_export_made", []))
        return j

    def export_cancel(self, delete=False):
        """Dừng lần xuất đang chạy; delete=True thì xoá luôn các file lần xuất này đã chép (ảnh gốc không bị đụng tới)."""
        j = getattr(self, "export_job", None)
        if not j:
            return dict(state="idle")
        if j.get("state") == "running":
            self._export_stop.set()
            if delete:
                self._export_wipe = True   # luồng xuất sẽ xoá ngay khi dừng hẳn (tránh xoá lúc đang chép dở một file)
        elif delete and j.get("state") in ("done", "stopped", "error"):
            j["state"] = "deleting"
            threading.Thread(target=self._export_delete, daemon=True).start()
        return self.export_status()

    def _export_delete(self):
        j = self.export_job
        j["state"] = "deleting"
        n = 0
        for f in reversed(getattr(self, "_export_made", [])):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
            j["removed"] = n
        for d in sorted(getattr(self, "_export_dirs", []), key=lambda p: len(str(p)), reverse=True):
            try:
                d.rmdir()   # chỉ xoá được khi trống: thư mục có file khác của bạn vẫn giữ nguyên
            except OSError:
                pass
        self._export_made = []
        j.update(state="deleted", removed=n, ended=time.time())
        lid = j.get("log_id")
        if lid:
            self.db.x("DELETE FROM export_log WHERE id=?", (lid,))   # đã xoá file xuất nhầm: bỏ khỏi lịch sử

    def export_dismiss(self):
        j = getattr(self, "export_job", None)
        if j and j.get("state") not in ("running", "deleting"):
            self.export_job = None
        return dict(ok=True)

    def export(self, ids, dest: str, by_person=False, template="{name}", xmp=False, progress=None, stop=None):
        """Sao chép (không bao giờ di chuyển/xoá file gốc)."""
        dest_p = Path(dest)
        made = getattr(self, "_export_made", None) if progress is not None else None
        mdirs = getattr(self, "_export_dirs", None) if progress is not None else None

        def mkdir(p):
            if mdirs is not None:
                q, new = p, []
                while not q.exists() and q != q.parent:
                    new.append(q)
                    q = q.parent
                mdirs.extend(new)
            p.mkdir(parents=True, exist_ok=True)
        mkdir(dest_p)
        names = self._names()
        seq, copied, errors = 0, 0, []
        rows = [self.db.one("SELECT * FROM photos WHERE id=?", (int(i),)) for i in ids]
        rows = sorted([r for r in rows if r], key=lambda r: (self._et(r), r["path"]))
        if progress is not None:
            progress["total"] = len(rows)
        # Bước 1 (nhanh, tuần tự): đặt tên file đích cho từng ảnh — giữ đúng thứ tự {seq}, không trùng tên.
        jobs, taken_names = [], set()
        for r in rows:
            seq += 1
            src = Path(r["path"])
            people = [x["person_id"] for x in self.db.q(
                "SELECT DISTINCT person_id FROM faces WHERE photo_id=? AND person_id IS NOT NULL", (r["id"],))]
            labels = [self.person_label(p, names) for p in people]
            dt = datetime.fromtimestamp(self._et(r) or r["mtime"] or time.time())
            stem = template
            for k, v in {"{name}": src.stem, "{date}": dt.strftime("%Y%m%d"), "{time}": dt.strftime("%H%M%S"),
                         "{seq}": f"{seq:04d}", "{person}": "+".join(labels) if labels else "khong-ro"}.items():
                stem = stem.replace(k, v)
            fname = _safe(stem) + src.suffix
            targets = [dest_p / _safe(l) for l in labels] if by_person and labels else \
                      ([dest_p / "Khong_xac_dinh"] if by_person else [dest_p])
            outs = []
            for t in targets:
                out, i = t / fname, 1
                while os.path.normcase(str(out)) in taken_names or out.exists():
                    out = t / f"{Path(fname).stem}_{i}{src.suffix}"
                    i += 1
                taken_names.add(os.path.normcase(str(out)))
                outs.append(out)
            jobs.append((r, src, labels, outs))
        for t in {o.parent for _, _, _, outs in jobs for o in outs}:
            try:
                mkdir(t)
            except OSError:
                pass
        # Bước 2: chép song song vài file một lúc. Một luồng chép qua mạng LAN / NAS thường không dùng hết băng thông
        # (mỗi file phải chờ mở / đóng / xác nhận qua SMB); 3–4 luồng chồng lên nhau lấp khoảng chờ đó.
        lock = threading.Lock()
        state = dict(done=0, copied=0)

        def one(job):
            r, src, labels, outs = job
            if stop is not None and stop.is_set():
                return
            if progress is not None:
                progress["cur"] = src.name
            for out in outs:
                try:
                    if made is not None:
                        with lock:
                            made.append(out)   # ghi trước khi chép: chép dở rồi bị dừng thì vẫn dọn được
                    shutil.copy2(src, out)
                    if xmp:
                        x = out.with_suffix(".xmp")
                        if made is not None and not x.exists():
                            with lock:
                                made.append(x)
                        x.write_text(self._xmp(r["rating"], r["label"], labels, self._synced(r)), encoding="utf-8")
                    with lock:
                        state["copied"] += 1
                except Exception as e:  # noqa: BLE001
                    with lock:
                        errors.append(f"{src.name}: {friendly(e)}")
            with lock:
                state["done"] += 1
                if progress is not None:
                    progress.update(done=state["done"], copied=state["copied"], n_errors=len(errors), errors=errors[:20])
        net = any(_is_network(str(j[1])) for j in jobs[:1]) or _is_network(str(dest_p))
        with ThreadPoolExecutor(max_workers=EXPORT_WORKERS_NET if net else EXPORT_WORKERS) as ex:
            list(ex.map(one, jobs))
        copied = state["copied"]
        return dict(copied=copied, errors=errors[:20], n_errors=len(errors))
