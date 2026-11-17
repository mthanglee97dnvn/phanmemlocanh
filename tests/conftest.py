import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))
os.environ.setdefault("PHOTOSIFT_HOME", tempfile.mkdtemp(prefix="ps_test_"))

import pytest


@pytest.fixture
def lib_with(tmp_path):
    """lib_with([(cam, taken), ...]) -> (Library, [ids]). cam đặt sẵn (None = chưa đọc, '?' = không rõ máy)."""
    from photosift.db import DB
    from photosift.library import Library

    def make(rows, catalog=()):
        db = DB(tmp_path / "t.db")
        ids = []
        for i, row in enumerate(rows):
            if isinstance(row, dict):   # dict: mọi cột của photos (path, rating, analyzed, ...); mặc định như dạng tuple
                d = {**dict(path=str(tmp_path / f"IMG_{i:04d}.JPG"), taken=None, ready=1, cam=None, toff=0), **row}
                d.setdefault("dir", os.path.dirname(d["path"]))
            else:
                cam, taken = row
                d = dict(path=str(tmp_path / f"IMG_{i:04d}.JPG"), dir=str(tmp_path), taken=taken, ready=1, cam=cam, toff=0)
            c = db.x(f"INSERT INTO photos({','.join(d)}) VALUES({','.join('?' * len(d))})", list(d.values()))
            ids.append(c.lastrowid)
        for k, root in enumerate(catalog):   # root hoặc (root, opened)
            root, opened = root if isinstance(root, tuple) else (root, float(k))
            db.x("INSERT INTO catalog(root,opened) VALUES(?,?)", (root, opened))
        db.many("INSERT INTO cur(id) VALUES(?)", [(i,) for i in ids])
        L = Library.__new__(Library)
        L.db, L.cam = db, {}
        L.regroup = lambda *a, **k: None
        return L, ids
    return make
