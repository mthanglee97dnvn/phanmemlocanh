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

    def make(rows):
        db = DB(tmp_path / "t.db")
        ids = []
        for i, (cam, taken) in enumerate(rows):
            c = db.x("INSERT INTO photos(path,dir,taken,ready,cam,toff) VALUES(?,?,?,1,?,0)",
                     (str(tmp_path / f"IMG_{i:04d}.JPG"), str(tmp_path), taken, cam))
            ids.append(c.lastrowid)
        db.many("INSERT INTO cur(id) VALUES(?)", [(i,) for i in ids])
        L = Library.__new__(Library)
        L.db, L.cam = db, {}
        L.regroup = lambda *a, **k: None
        return L, ids
    return make
