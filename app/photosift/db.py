from __future__ import annotations
import os
import sqlite3
import threading
from pathlib import Path

HOME = Path(os.environ.get("PHOTOSIFT_HOME", Path.home() / ".photosift"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos(
  id INTEGER PRIMARY KEY, path TEXT UNIQUE, dir TEXT, mtime REAL, size INTEGER,
  w INTEGER, h INTEGER, taken REAL, sharp REAL, fsharp REAL, lum REAL, lo REAL, hi REAL,
  dhash TEXT, nfaces INTEGER DEFAULT 0, ear_min REAL DEFAULT -1,
  rating INTEGER DEFAULT 0, label TEXT DEFAULT '',
  grp INTEGER DEFAULT 0, best INTEGER DEFAULT 0, score REAL DEFAULT 0,
  analyzed INTEGER DEFAULT 0, err TEXT, ready INTEGER DEFAULT 0, tv INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS faces(
  id INTEGER PRIMARY KEY, photo_id INTEGER, fx REAL, fy REAL, fw REAL, fh REAL,
  det REAL, px INTEGER, ear REAL, emb BLOB, person_id INTEGER);
CREATE INDEX IF NOT EXISTS faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS faces_person ON faces(person_id);
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT DEFAULT '', cent BLOB);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS catalog(root TEXT PRIMARY KEY, recursive INTEGER DEFAULT 1, opened REAL DEFAULT 0,
  n INTEGER DEFAULT 0, size INTEGER DEFAULT 0, t0 REAL DEFAULT 0, t1 REAL DEFAULT 0, covers TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS cull_log(id INTEGER PRIMARY KEY, root TEXT, time REAL, ids TEXT);
CREATE TABLE IF NOT EXISTS export_log(id INTEGER PRIMARY KEY, time REAL, src TEXT, dest TEXT, n INTEGER DEFAULT 0,
  copied INTEGER DEFAULT 0, n5 INTEGER DEFAULT 0, state TEXT DEFAULT 'done');
"""


class DB:
    def __init__(self, path: Path | None = None):
        HOME.mkdir(parents=True, exist_ok=True)
        self.path = path or HOME / "photosift.db"
        self.lock = threading.RLock()
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        with self.lock:
            self.con.execute("PRAGMA journal_mode=WAL")
            self.con.execute("PRAGMA synchronous=NORMAL")
            self.con.executescript(SCHEMA)
            try:  # nâng cấp CSDL cũ
                self.con.execute("ALTER TABLE photos ADD COLUMN ready INTEGER DEFAULT 0")
                self.con.execute("UPDATE photos SET ready=1 WHERE analyzed=1 AND err IS NULL")
            except sqlite3.OperationalError:
                pass
            for ddl in ("ALTER TABLE photos ADD COLUMN tv INTEGER DEFAULT 0", "ALTER TABLE people ADD COLUMN cent BLOB",
                        "ALTER TABLE photos ADD COLUMN away INTEGER DEFAULT 0",
                        "ALTER TABLE faces ADD COLUMN yaw REAL DEFAULT -1", "ALTER TABLE faces ADD COLUMN vert REAL DEFAULT -1",
                        "ALTER TABLE photos ADD COLUMN smile REAL", "ALTER TABLE faces ADD COLUMN smile REAL DEFAULT -1",
                        "ALTER TABLE photos ADD COLUMN cam TEXT", "ALTER TABLE photos ADD COLUMN toff REAL DEFAULT 0"):
                try:
                    self.con.execute(ddl)
                except sqlite3.OperationalError:
                    pass
            self.con.execute("CREATE TEMP TABLE IF NOT EXISTS cur(id INTEGER PRIMARY KEY)")
            self.con.commit()

    def q(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.lock:
            return self.con.execute(sql, args).fetchone()

    def x(self, sql, args=()):
        with self.lock:
            cur = self.con.execute(sql, args)
            self.con.commit()
            return cur

    def many(self, sql, rows):
        with self.lock:
            self.con.executemany(sql, rows)
            self.con.commit()
