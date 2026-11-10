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

from .analyzer import ALL_EXT, ANALYSIS_SIDE, RAW_EXT, Analyzer, _jpg, diag_raw, hamming, load_view, read_exif
from .errors import friendly
from .db import DB, HOME
from .online import Online

THUMBS = HOME / "thumbs"
COVERS = HOME / "covers"   # ảnh bìa catalog: giữ qua các lần mở app, khác với THUMBS
FACES = HOME / "faces"
VIEWS = HOME / "view"      # ảnh nét đúng cỡ màn hình cho trình xem (RAW đã giải mã), dựng sẵn ở nền
PREVIEWS = HOME / "prev"   # ảnh 1600px đã giải mã sẵn: xem nhanh + phân tích không phải đọc lại RAW từ thẻ nhớ
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
        regroup = any(k in new and new[k] != self.settings.get(k) for k in ("dup_hamming", "dup_seconds"))
        for k, v in new.items():
            if k in DEFAULT_SETTINGS:
                self.settings[k] = type(DEFAULT_SETTINGS[k])(v)
        try:
            self._sfile.write_text(json.dumps(self.settings))
        except Exception:  # noqa: BLE001
            pass
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

    def locate(self, name: str, samples: list, budget: float = 10.0):
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

        roots = [r["root"] for r in self.db.q("SELECT root FROM catalog ORDER BY opened DESC")]
        if self.status.get("root"):
            roots.insert(0, self.status["root"])
        bases, seen = [], set()

        def add(p, depth):
            k = os.path.normcase(os.path.abspath(p)) if p else ""
            if p and k not in seen:
                seen.add(k)
                bases.append((p, depth))
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
                        add(e.path, 2)
            except OSError:
                pass
        if sys.platform == "win32":
            import string
            for c in string.ascii_uppercase[2:]:
                d = f"{c}:\\"
                if os.path.isdir(d):
                    add(d, 2)
        visited = set()
        for base, depth in bases:   # tìm theo chiều rộng, giới hạn thời gian để ổ mạng chậm không làm treo
            level = [base]
            for _ in range(depth + 1):
                nxt = []
                for d in level:
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
                                if not e.name.startswith((".", "$")) and e.is_dir(follow_symlinks=False):
                                    if name and e.name.lower() == name.lower() and ok(e.path):
                                        return e.path
                                    nxt.append(e.path)
                    except OSError:
                        pass
                level = nxt
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
        todo, ids = [], []   # todo: (id, path, đã có ảnh cache?)
        with db.lock:
            for p, mt, sz in files:
                row = db.one("SELECT id,mtime,size,analyzed,ready FROM photos WHERE path=?", (p,))
                if row is None:
                    cur = db.con.execute("INSERT INTO photos(path,dir,mtime,size) VALUES(?,?,?,?)",
                                         (p, os.path.dirname(p), mt, sz))
                    pid = cur.lastrowid
                    todo.append((pid, p, False))
                else:
                    pid = row["id"]
                    changed = row["mtime"] != mt or row["size"] != sz
                    if changed:
                        db.con.execute("UPDATE photos SET mtime=?,size=?,analyzed=0,ready=0,err=NULL WHERE id=?",
                                       (mt, sz, pid))
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
        try:
            self._catalog_update(root)
            self.trim_cache()
        except Exception as e:  # noqa: BLE001  catalog lỗi không được làm hỏng phiên lọc
            print("catalog:", e, file=sys.stderr)
        self.status.update(state="done", message="Hoàn tất")
        self.view_all()

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
                   nfaces=?,ear_min=?,smile=?,analyzed=1,err=NULL WHERE id=?""",
                (r["sharp"], r["fsharp"], r["lum"], r["lo"], r["hi"], r["dhash"], r["nfaces"], r["ear_min"],
                 float(r.get("smile", -1.0)) if self.an.has_smile else None, pid))
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

    def regroup(self):
        rows = sorted(self._rows(), key=lambda r: (r["taken"] or 0, r["path"]))
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
            close = abs((r["taken"] or 0) - (prev["taken"] or 0)) <= S["dup_seconds"]
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
            # ảnh tốt nhất: trong các ảnh đủ nét (>= 85% ảnh cao điểm nhất), ưu tiên ít người quay mặt nhất, rồi mới tới điểm
            raw_top = max(raw[r["id"]] for r in g)
            cand = [r for r in g if raw[r["id"]] >= 0.85 * raw_top]
            top = min(cand, key=lambda r: (away.get(r["id"], (0, 0))[0], -score[r["id"]]))["id"]
            for r in g:
                upd.append((gid, 1 if r["id"] == top else 0, score[r["id"]], away.get(r["id"], (0, 0))[0], r["id"]))
        self.db.many("UPDATE photos SET grp=?, best=?, score=?, away=? WHERE id=?", upd)

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
        rows = self._rows(analyzed_only=False)
        if not rows:
            return []
        S = self.settings
        online = self.online.ok
        ref_g, ref_f = self._ref([r for r in rows if r["analyzed"]])
        pmap: dict[int, list[int]] = {}
        for r in self.db.q("""SELECT f.photo_id, f.person_id FROM faces f JOIN cur ON cur.id=f.photo_id
                              WHERE f.person_id IS NOT NULL"""):
            pmap.setdefault(r["photo_id"], [])
            if r["person_id"] not in pmap[r["photo_id"]]:
                pmap[r["photo_id"]].append(r["person_id"])
        out = []
        for r in rows:
            flags = []
            if not r["analyzed"]:
                out.append(dict(
                    id=r["id"], name=os.path.basename(r["path"]), dir=r["dir"], w=r["w"], h=r["h"], taken=r["taken"],
                    smile=-1, sharp=0, fsharp=0, lum=0, nf=0, ear=-1, rating=r["rating"], label=r["label"], grp=0, best=0,
                    score=0, people=[], flags=[], an=False, tv=r["tv"]))
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
            out.append(dict(
                id=r["id"], name=os.path.basename(r["path"]), dir=r["dir"], w=r["w"], h=r["h"],
                taken=r["taken"], sharp=round(r["sharp"] or 0, 1), fsharp=round(r["fsharp"] or 0, 1),
                lum=round(r["lum"] or 0, 3), nf=r["nfaces"], ear=round(r["ear_min"], 3),
                smile=_num(r["smile"]),
                rating=r["rating"], label=r["label"], grp=r["grp"], best=r["best"], score=r["score"],
                away=r["away"] or 0, people=pmap.get(r["id"], []), flags=flags, an=True, tv=r["tv"]))
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
    def set_rating(self, ids, rating: int):
        rating = max(-1, min(5, int(rating)))
        self.db.many("UPDATE photos SET rating=? WHERE id=?", [(rating, int(i)) for i in ids])

    def set_ratings(self, pairs):
        self.db.many("UPDATE photos SET rating=? WHERE id=?", [(int(r), int(i)) for i, r in pairs])

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
        return self.status.get("root", "") or ""

    def cull_apply(self, ids):
        hit = self._rated("id", [int(i) for i in ids], 0)
        if not hit:
            return dict(id=0, n=0)
        self.db.many("UPDATE photos SET rating=-1 WHERE id=?", [(r["id"],) for r in hit])
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
        self.db.x("DELETE FROM cull_log WHERE id=?", (target,))
        return dict(ids=left, n=len(left))

    def cull_clear(self):
        self.db.x("DELETE FROM cull_log WHERE root=?", (self._root(),))

    def set_label(self, ids, label: str):
        if label not in LABELS:
            raise ValueError("nhãn không hợp lệ")
        self.db.many("UPDATE photos SET label=? WHERE id=?", [(label, int(i)) for i in ids])

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
    def _xmp(self, rating: int, label: str, keywords: list[str]) -> str:
        kw = ""
        if keywords:
            kw = "<dc:subject><rdf:Bag>" + "".join(f"<rdf:li>{escape(k)}</rdf:li>" for k in keywords) + "</rdf:Bag></dc:subject>"
        lab = f' xmp:Label="{XMP_LABEL[label]}"' if label in XMP_LABEL else ""
        return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
                '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
                '<rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
                f'xmlns:dc="http://purl.org/dc/elements/1.1/" xmp:Rating="{rating}"{lab}>{kw}'
                '</rdf:Description></rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>')

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
            Path(r["path"]).with_suffix(".xmp").write_text(self._xmp(r["rating"], r["label"], kws), encoding="utf-8")
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
        rows = sorted([r for r in rows if r], key=lambda r: (r["taken"] or 0, r["path"]))
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
            dt = datetime.fromtimestamp(r["taken"] or r["mtime"] or time.time())
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
                        x.write_text(self._xmp(r["rating"], r["label"], labels), encoding="utf-8")
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
