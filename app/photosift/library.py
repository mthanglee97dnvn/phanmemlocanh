"""Thư viện ảnh: quét thư mục, phân tích song song, gom người, nhóm ảnh trùng, cờ cảnh báo, xuất ảnh."""
from __future__ import annotations

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

from .analyzer import ALL_EXT, RAW_EXT, Analyzer, diag_raw, hamming, read_exif
from .db import DB, HOME
from .online import Online

THUMBS = HOME / "thumbs"
FACES = HOME / "faces"
PREVIEWS = HOME / "prev"   # ảnh 1600px đã giải mã sẵn: xem nhanh + phân tích không phải đọc lại RAW từ thẻ nhớ
IO_WORKERS = 4             # số luồng đọc file (thẻ nhớ/USB: 4 là hợp lý)
LABELS = {"", "red", "yellow", "green", "blue", "purple"}
XMP_LABEL = {"red": "Red", "yellow": "Yellow", "green": "Green", "blue": "Blue", "purple": "Purple"}

CACHE_VERSION = 3  # tăng khi đổi cách đọc/xoay ảnh → tự đọc lại toàn bộ (giữ sao, nhãn và tên người)

DEFAULT_SETTINGS = dict(
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


class Library:
    def __init__(self, db: DB | None = None):
        THUMBS.mkdir(parents=True, exist_ok=True)
        FACES.mkdir(parents=True, exist_ok=True)
        PREVIEWS.mkdir(parents=True, exist_ok=True)
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
        self.reset_cache()   # mỗi lần mở app là một phiên mới: không hiện lại thư mục/ảnh/người của lần trước

    def reset_cache(self):
        """Xoá toàn bộ cache (thumbnail, ảnh xem trước, khuôn mặt) và kết quả phân tích của phiên trước.
        Chỉ giữ lại số sao / nhãn màu đã chấm (theo đường dẫn file) để mở lại đúng thư mục đó thì không mất công chấm."""
        self._cancel.set()
        with self.db.lock:
            c = self.db.con
            keep = [(r["path"], r["dir"], r["rating"], r["label"])
                    for r in self.db.q("SELECT path,dir,rating,label FROM photos WHERE rating<>0 OR label<>''")]
            for t in ("faces", "people", "photos", "cur"):
                try:
                    c.execute(f"DELETE FROM {t}")
                except Exception:  # noqa: BLE001
                    pass
            c.executemany("INSERT INTO photos(path,dir,rating,label) VALUES(?,?,?,?)", keep)
            c.commit()
            try:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:  # noqa: BLE001
                pass
        for d in (THUMBS, FACES, PREVIEWS):
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
        self._exif_cache = {}
        self.status = dict(state="idle", total=0, done=0, thumbs=0, quick=0, errors=0, root="", message="", timing={})
        self.root = ""

    def _migrate(self):
        db = self.db
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
        self.status = dict(state="scanning", total=0, done=0, thumbs=0, quick=0, errors=0, root=root, message="Đang liệt kê file…", timing={})
        self._slock = threading.Lock()
        self._thread = threading.Thread(target=self._scan, args=(root, recursive, self._cancel), daemon=True)
        self._thread.start()

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
            self.status.update(state="error", message=str(e))
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
                    elif not row["analyzed"]:
                        todo.append((pid, p, bool(row["ready"]) and (PREVIEWS / f"{pid}.jpg").exists()))
                ids.append(pid)
            db.con.execute("DELETE FROM cur")
            db.con.executemany("INSERT INTO cur(id) VALUES(?)", [(i,) for i in ids])
            db.con.commit()
        self.status.update(total=len(ids), done=len(ids) - len(todo), thumbs=len(ids) - len(todo),
                           message=f"Đang đọc {len(todo)} ảnh mới…" if todo else "Đã có trong bộ nhớ đệm")

        t0 = time.time()
        net = _is_network(root)   # ổ mạng: độ trễ cao → dùng nhiều luồng hơn để các lượt đọc chồng lên nhau
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
            with ThreadPoolExecutor(max_workers=qa_n) as pa:
                list(pa.map(qa, quick))
        self.status["timing"]["thumb_s"] = round(time.time() - t0, 1)
        # Pha 1 (I/O): đọc ảnh xem trước → thumbnail hiện ngay. Pha 2 (CPU): độ nét, khuôn mặt… chạy nền song song.
        cpu = max(1, min(8, (os.cpu_count() or 2)))
        p1 = ThreadPoolExecutor(max_workers=io_n)
        p2 = ThreadPoolExecutor(max_workers=cpu)

        def bump(**kw):
            with self._slock:
                for k, v in kw.items():
                    self.status[k] += v

        def phase2(pid):
            if cancel.is_set():
                return
            try:
                ok = self._analyze_cached(pid)
            except Exception as e:  # noqa: BLE001
                self.db.x("UPDATE photos SET analyzed=1, err=? WHERE id=?", (str(e)[:200], pid))
                ok = False
            bump(done=1, errors=0 if ok else 1)

        def phase1(pid, path, cached):
            if cancel.is_set():
                return
            if not cached:
                try:
                    self._prepare_one(pid, path)
                except Exception as e:  # noqa: BLE001
                    self.db.x("UPDATE photos SET analyzed=1, ready=0, err=? WHERE id=?", (str(e)[:200], pid))
                    bump(done=1, thumbs=1, errors=1)
                    return
            bump(thumbs=1)
            p2.submit(phase2, pid)

        for pid, path, cached in todo:
            p1.submit(phase1, pid, path, cached)
        p1.shutdown(wait=True)
        self.status["timing"]["read_s"] = round(time.time() - t0, 1)
        self.status.update(message="Đang phân tích chất lượng + khuôn mặt…")
        p2.shutdown(wait=True)
        self.status["timing"]["all_s"] = round(time.time() - t0, 1)
        if cancel.is_set():
            self.status.update(state="idle", message="Đã huỷ")
            return
        self.status.update(message="Đang gom khuôn mặt theo người…")
        self.cluster()
        self.regroup()
        self.status.update(state="done", message="Hoàn tất")

    def _prepare_one(self, pid: int, path: str):
        """Pha 1: đọc ảnh xem trước, ghi thumbnail + ảnh cache, đánh dấu ready (hiện được ngay trên lưới)."""
        r = self.an.prepare(path)
        (THUMBS / f"{pid}.jpg").write_bytes(r["thumb"])
        (PREVIEWS / f"{pid}.jpg").write_bytes(r["prev"])
        taken = r["taken"] or os.path.getmtime(path)
        self.db.x("UPDATE photos SET w=?,h=?,taken=?,ready=1,tv=2,err=NULL WHERE id=?", (r["w"], r["h"], taken, pid))

    def _analyze_cached(self, pid: int) -> bool:
        """Pha 2: phân tích từ ảnh cache trên ổ đĩa máy (không đụng tới thẻ nhớ nữa)."""
        row = self.db.one("SELECT w,h FROM photos WHERE id=?", (pid,))
        f = PREVIEWS / f"{pid}.jpg"
        img = cv2.imdecode(np.fromfile(str(f), dtype=np.uint8), cv2.IMREAD_COLOR) if f.exists() else None
        if img is None:
            raise ValueError("thiếu ảnh cache")
        r = self.an.analyze_image(img, row["w"], row["h"])
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
                   nfaces=?,ear_min=?,analyzed=1,err=NULL WHERE id=?""",
                (r["sharp"], r["fsharp"], r["lum"], r["lo"], r["hi"], r["dhash"], r["nfaces"], r["ear_min"], pid))
            for fc in r["faces"]:
                cur = self.db.con.execute(
                    "INSERT INTO faces(photo_id,fx,fy,fw,fh,det,px,ear,emb) VALUES(?,?,?,?,?,?,?,?,?)",
                    (pid, fc["fx"], fc["fy"], fc["fw"], fc["fh"], fc["det"], fc["px"], fc["ear"], fc["emb"]))
                if fc["crop"]:
                    (FACES / f"{cur.lastrowid}.jpg").write_bytes(fc["crop"])
            self.db.con.commit()
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
            assigned = db.q("SELECT person_id, emb FROM faces WHERE person_id IS NOT NULL")
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
            for r in todo:
                v = np.frombuffer(r["emb"], dtype=np.float32)
                best, bs = None, -1.0
                for pid, c in cents.items():
                    s = float(v @ c)
                    if s > bs:
                        best, bs = pid, s
                if best is None or bs < thr:
                    best = db.con.execute("INSERT INTO people(name) VALUES('')").lastrowid
                    sums[best] = v.copy()
                else:
                    sums[best] = sums[best] + v
                cents[best] = sums[best] / (np.linalg.norm(sums[best]) + 1e-9)
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
        score = {}
        for r in rows:
            sh = min(1.0, self._sharp_val(r, ref_g, ref_f) / 1.3) ** 0.8
            clip = min(1.0, ((r["lo"] or 0) + (r["hi"] or 0)) / 0.25)
            dev = min(1.0, abs((r["lum"] or 0.45) - 0.45) / 0.45)
            s = 100 * (0.65 * sh + 0.2 * (1 - clip) + 0.15 * (1 - dev))
            if 0 <= r["ear_min"] < S["ear"]:
                s *= 0.6
            score[r["id"]] = round(s, 1)
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
        upd, gid = [], 0
        for g in groups:
            if len(g) < 2:
                upd.append((0, 0, score[g[0]["id"]], g[0]["id"]))
                continue
            gid += 1
            top = max(g, key=lambda r: score[r["id"]])["id"]
            for r in g:
                upd.append((gid, 1 if r["id"] == top else 0, score[r["id"]], r["id"]))
        self.db.many("UPDATE photos SET grp=?, best=?, score=? WHERE id=?", upd)

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
                    sharp=0, fsharp=0, lum=0, nf=0, ear=-1, rating=r["rating"], label=r["label"], grp=0, best=0,
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
            if r["grp"] and not r["best"]:
                flags.append("dup")
            out.append(dict(
                id=r["id"], name=os.path.basename(r["path"]), dir=r["dir"], w=r["w"], h=r["h"],
                taken=r["taken"], sharp=round(r["sharp"] or 0, 1), fsharp=round(r["fsharp"] or 0, 1),
                lum=round(r["lum"] or 0, 3), nf=r["nfaces"], ear=round(r["ear_min"], 3),
                rating=r["rating"], label=r["label"], grp=r["grp"], best=r["best"], score=r["score"],
                people=pmap.get(r["id"], []), flags=flags, an=True, tv=r["tv"]))
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

    def set_label(self, ids, label: str):
        if label not in LABELS:
            raise ValueError("nhãn không hợp lệ")
        self.db.many("UPDATE photos SET label=? WHERE id=?", [(label, int(i)) for i in ids])

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
        """Chạy xuất ảnh ở nền; tiến độ lấy qua export_status()."""
        j = getattr(self, "export_job", None)
        if j and j.get("state") == "running":
            return dict(error="Đang có một tác vụ xuất chạy — hãy đợi nó xong")
        ids = [int(i) for i in ids]
        self.export_job = dict(state="running", total=len(ids), done=0, copied=0, n_errors=0, errors=[], cur="", dest=str(dest))

        def work():
            try:
                r = self.export(ids, dest, by_person, template, xmp, progress=self.export_job)
                self.export_job.update(state="done", copied=r["copied"], errors=r["errors"], n_errors=r["n_errors"])
            except Exception as e:  # noqa: BLE001
                self.export_job.update(state="error", message=str(e))
        threading.Thread(target=work, daemon=True).start()
        return dict(ok=True, total=len(ids))

    def export_status(self):
        return dict(getattr(self, "export_job", None) or dict(state="idle"))

    def export(self, ids, dest: str, by_person=False, template="{name}", xmp=False, progress=None):
        """Sao chép (không bao giờ di chuyển/xoá file gốc)."""
        dest_p = Path(dest)
        dest_p.mkdir(parents=True, exist_ok=True)
        names = self._names()
        seq, copied, errors = 0, 0, []
        rows = [self.db.one("SELECT * FROM photos WHERE id=?", (int(i),)) for i in ids]
        rows = sorted([r for r in rows if r], key=lambda r: (r["taken"] or 0, r["path"]))
        if progress is not None:
            progress["total"] = len(rows)
        for r in rows:
            seq += 1
            src = Path(r["path"])
            if progress is not None:
                progress["cur"] = src.name
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
            for t in targets:
                try:
                    t.mkdir(parents=True, exist_ok=True)
                    out, i = t / fname, 1
                    while out.exists():
                        out = t / f"{Path(fname).stem}_{i}{src.suffix}"
                        i += 1
                    shutil.copy2(src, out)
                    if xmp:
                        out.with_suffix(".xmp").write_text(self._xmp(r["rating"], r["label"], labels), encoding="utf-8")
                    copied += 1
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{src.name}: {e}")
            if progress is not None:
                progress.update(done=seq, copied=copied, n_errors=len(errors), errors=errors[:20])
        return dict(copied=copied, errors=errors[:20], n_errors=len(errors))
