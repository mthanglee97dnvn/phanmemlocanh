from photosift.library import DEFAULT_SETTINGS
from photosift.xmpsync import merge_xmp  # noqa: F401  (dùng ở test đọc)

ERR = "Không ghi được .xmp vào thư mục này — kiểm tra quyền ghi trên NAS"


def prep(L):
    L.settings = dict(DEFAULT_SETTINGS)
    L.status = {}
    L._xmp_init()
    return L


def test_default_on():
    assert DEFAULT_SETTINGS["xmp_sync"] == 1


def test_rate_then_flush_writes(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4)
    assert L.xmp_flush() == dict(written=1, failed=0)
    x = tmp_path / "IMG_0000.xmp"
    assert b'xmp:Rating="4"' in x.read_bytes()
    assert abs(L.db.one("SELECT xmt FROM photos WHERE id=?", (ids[0],))["xmt"] - x.stat().st_mtime) < 0.01


def test_zero_without_file_not_created(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=2)]); prep(L)
    L.set_rating([ids[0]], 0); L.xmp_flush()
    assert not list(tmp_path.glob("*.xmp"))


def test_zero_with_file_updates(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 3); L.xmp_flush()
    L.set_rating([ids[0]], 0); L.xmp_flush()
    assert b'xmp:Rating="0"' in (tmp_path / "IMG_0000.xmp").read_bytes()


def test_pair_last_action_wins(lib_with, tmp_path):
    L, ids = lib_with([dict(path=str(tmp_path / "A.ARW")), dict(path=str(tmp_path / "A.JPG"))]); prep(L)
    L.set_rating([ids[0]], 5); L.set_rating([ids[1]], 2); L.xmp_flush()
    assert b'xmp:Rating="2"' in (tmp_path / "A.xmp").read_bytes()
    L.set_rating([ids[0]], 4); L.xmp_flush()
    assert b'xmp:Rating="4"' in (tmp_path / "A.xmp").read_bytes()


def test_cull_and_label_marked(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.cull_apply([ids[0]]); L.set_label([ids[0]], "red"); L.xmp_flush()
    b = (tmp_path / "IMG_0000.xmp").read_bytes()
    assert b'xmp:Rating="-1"' in b and b'xmp:Label="Red"' in b


def test_cull_undo_and_suggest_marked(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0, sugg=1), dict(rating=0)]); prep(L)
    L.status["root"] = str(tmp_path)
    L.suggest_rate(); L.xmp_flush()
    assert b'xmp:Rating="1"' in (tmp_path / "IMG_0000.xmp").read_bytes()
    L.suggest_rate_undo(); L.xmp_flush()
    assert b'xmp:Rating="0"' in (tmp_path / "IMG_0000.xmp").read_bytes()
    r = L.cull_apply([ids[1]]); L.xmp_flush()
    assert b'xmp:Rating="-1"' in (tmp_path / "IMG_0001.xmp").read_bytes()
    L.cull_undo(r["id"]); L.xmp_flush()
    assert b'xmp:Rating="0"' in (tmp_path / "IMG_0001.xmp").read_bytes()


def test_unwritable_keeps_queue_and_warns(lib_with, tmp_path):
    L, ids = lib_with([dict(path=str(tmp_path / "nope" / "X.JPG"))]); prep(L)
    L.set_rating([ids[0]], 3)
    assert L.xmp_flush() == dict(written=0, failed=1)
    assert L.status["xmp_err"] == ERR
    (tmp_path / "nope").mkdir()
    assert L.xmp_flush()["written"] == 1 and "xmp_err" not in L.status


def test_setting_off_writes_nothing(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L); L.settings["xmp_sync"] = 0
    L.set_rating([ids[0]], 4); L.xmp_flush()
    assert not list(tmp_path.glob("*.xmp"))


def test_rewrite_all(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=3), dict(rating=0), dict(rating=-1)]); prep(L)
    assert L.xmp_rewrite_all()["n"] == 2
    L.xmp_flush()
    assert len(list(tmp_path.glob("*.xmp"))) == 2


def test_keeps_existing_pm_content(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    (tmp_path / "IMG_0000.XMP").write_bytes(merge_xmp(None, 2, "").replace(b"/>", b"><dc:x>giu</dc:x></rdf:Description>", 1))
    L.set_rating([ids[0]], 5); L.xmp_flush()
    files = list(tmp_path.glob("*.[xX][mM][pP]"))
    assert len(files) == 1 and b"giu" in files[0].read_bytes() and b'xmp:Rating="5"' in files[0].read_bytes()
