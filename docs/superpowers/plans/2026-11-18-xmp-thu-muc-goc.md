# Ghi .xmp vào thư mục ảnh gốc — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Máy lọc tự ghi sao/loại/nhãn ra .xmp cạnh ảnh gốc; máy khác mở cùng thư mục thấy ngay kết quả đó.

**Architecture:** Module thuần `xmpsync.py` (tìm sidecar, gộp XMP không ghi đè, đọc, ghi an toàn). `Library` đánh dấu id
"cần ghi" ở mọi chỗ đổi rating/label; một luồng nền gom và ghi. Lượt quét thư mục đọc lại sidecar có mtime khác lần
trước và ghi đè sao/nhãn trong app. Giao diện máy tính: mục trạng thái `.xmp` ở thanh dưới (cảnh báo + công tắc + nút
"Ghi lại .xmp cho cả thư mục").

**Tech Stack:** Python 3 (stdlib re/os/threading, sqlite qua `photosift.db.DB`), HTML/JS thuần, pytest, Playwright.

**Spec:** docs/superpowers/specs/2026-11-18-xmp-thu-muc-goc-design.md

## Global Constraints

- Không bao giờ sửa file ảnh gốc; JPEG cũng dùng sidecar `.xmp`.
- .xmp có sẵn: chỉ thay/thêm `xmp:Rating` và `xmp:Label`; mọi byte khác giữ nguyên.
- Loại = `xmp:Rating="-1"`. Nhãn: `red/yellow/green/blue/purple` ↔ `Red/Yellow/Green/Blue/Purple` (bảng `XMP_LABEL` có sẵn).
- Ảnh 0 sao, không nhãn, chưa có sidecar → không tạo file.
- Ghi chạy nền: gom khi 2 giây không có thay đổi mới, hoặc tối đa 10 giây kể từ thay đổi đầu tiên chưa ghi.
- Lỗi ghi: giữ trong hàng đợi, thử lại sau 15 giây; thông báo đúng câu: "Không ghi được .xmp vào thư mục này — kiểm tra quyền ghi trên NAS".
- Công tắc cài đặt `xmp_sync` (int, mặc định 1), nhãn giao diện: "Ghi .xmp vào thư mục ảnh gốc".
- Nút: "Ghi lại .xmp cho cả thư mục".
- Commit giữ tác giả MThanglee, kèm 2 dòng trailer Co-Authored-By / Claude-Session.

## Review Focus

- So mtime trên NAS/SMB lệch vài trăm ms hoặc làm tròn 2 giây (FAT) → coi là "đổi" chỉ khi lệch > 1.5 giây, nếu không app sẽ tự nhập lại file của chính nó mỗi lần mở (test ở Task 3).
- .xmp của Photo Mechanic viết `xmp:Rating` dạng thẻ `<xmp:Rating>3</xmp:Rating>` thay vì thuộc tính → phải sửa đúng chỗ, không thêm thuộc tính thứ hai (test ở Task 1).
- Thư mục không ghi được (quyền NAS) → không làm hỏng chấm sao trong app, không ném lỗi ra API, chỉ hiện cảnh báo (test ở Task 2).
- Cặp RAW+JPEG cùng tên chấm khác nhau → một file .xmp, giá trị của thao tác sau cùng (test ở Task 2).
- Nhãn lạ trong .xmp (ví dụ "Winner" do Photo Mechanic đặt tên lớp màu) → giữ nhãn hiện có trong app, vẫn nhập sao (test ở Task 3).

---

### Task 1: Module `xmpsync.py`

**Files:**
- Create: `app/photosift/xmpsync.py`
- Test: `tests/test_xmpsync.py`

**Interfaces:**
- Produces:
  - `sidecar(img_path: str) -> tuple[str, bool]` — đường dẫn .xmp nên dùng và đã tồn tại chưa. Ưu tiên file có sẵn cùng tên gốc, bất kể hoa/thường đuôi (`IMG.XMP`, `IMG.xmp`); không có thì `<gốc>.xmp`.
  - `merge_xmp(existing: bytes | None, rating: int, label: str) -> bytes | None` — `label` là giá trị trong app (`""` = không nhãn). Trả `None` khi `existing is None and rating == 0 and label == ""`.
  - `read_sidecar(img_path: str) -> tuple[int | None, str | None, float | None]` — (rating −1..5, nhãn app hoặc None nếu thiếu/lạ, mtime) ; không có file → (None, None, None). Không bao giờ raise.
  - `write_atomic(path: str, data: bytes) -> None` — ghi `path + ".tmp"` cùng thư mục rồi `os.replace`; lỗi thì xoá file tạm và raise lại.

- [ ] **Step 1: Write the failing tests** in `tests/test_xmpsync.py`

```python
PM = (b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
      b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
      b'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmp:Rating="2">'
      b'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">Le vu quy</rdf:li></rdf:Alt></dc:description>'
      b'</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>')

def test_merge_attr_keeps_rest():          # đổi sao, giữ chú thích
    out = merge_xmp(PM, 5, "")
    assert b'xmp:Rating="5"' in out and b'xmp:Rating="2"' not in out and b"Le vu quy" in out
    assert out.count(b"xmp:Rating") == 1
def test_merge_element_form():              # Photo Mechanic dạng thẻ
    src = PM.replace(b' xmp:Rating="2">', b'><xmp:Rating>2</xmp:Rating>')
    out = merge_xmp(src, -1, "")
    assert b"<xmp:Rating>-1</xmp:Rating>" in out and out.count(b"xmp:Rating") == 2   # mở + đóng thẻ
def test_merge_label_add_replace_remove():
    a = merge_xmp(PM, 3, "red");  assert b'xmp:Label="Red"' in a
    b = merge_xmp(a, 3, "green"); assert b'xmp:Label="Green"' in b and b"Red" not in b
    c = merge_xmp(b, 3, "");      assert b"xmp:Label" not in c and b"Le vu quy" in c
def test_merge_new_and_nothing():
    assert merge_xmp(None, 0, "") is None
    n = merge_xmp(None, 4, "blue"); assert b'xmp:Rating="4"' in n and b'xmp:Label="Blue"' in n
    assert read_back(n) == (4, "blue")       # helper trong test: ghi tạm rồi read_sidecar
def test_sidecar_prefers_existing_case(tmp_path):
    img = tmp_path / "IMG_1.ARW"; img.write_bytes(b"x"); (tmp_path / "IMG_1.XMP").write_bytes(PM)
    assert sidecar(str(img)) == (str(tmp_path / "IMG_1.XMP"), True)
    assert sidecar(str(tmp_path / "IMG_2.JPG")) == (str(tmp_path / "IMG_2.xmp"), False)
def test_read_unknown_label(tmp_path):      # nhãn lạ → None, sao vẫn đọc
    img = tmp_path / "A.JPG"; (tmp_path / "A.xmp").write_bytes(merge_xmp(PM, 3, "").replace(b"xmp:Rating", b'xmp:Label="Winner" xmp:Rating', 1))
    r, lab, mt = read_sidecar(str(img)); assert (r, lab) == (3, None) and mt
def test_write_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "B.xmp"; write_atomic(str(p), b"abc")
    assert p.read_bytes() == b"abc" and not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run to see it fail** — `python -m pytest tests/test_xmpsync.py -q` → Expected: FAIL (`ModuleNotFoundError: photosift.xmpsync`).
- [ ] **Step 3: Implement the four functions** in `app/photosift/xmpsync.py`. Gộp bằng regex trên bytes: thay thuộc tính `xmp:Rating="…"` hoặc nội dung thẻ `<xmp:Rating>…</xmp:Rating>`; thiếu cả hai thì chèn thuộc tính vào thẻ mở `<rdf:Description` đầu tiên (thêm `xmlns:xmp` nếu thiếu). Nhãn tương tự với `xmp:Label`. File mới: dùng khuôn tối giản như `Library._xmp` (không từ khoá, không giờ). Đọc sao bằng `_xmp_parse` sẵn có trong `library.py` (chuyển `_xmp_parse` sang `xmpsync.py`, `library.py` import lại để không lặp).
- [ ] **Step 4: Run** — `python -m pytest tests/test_xmpsync.py -q` → Expected: all pass; `python -m pytest -q` → không hỏng bài cũ.
- [ ] **Step 5: Commit** — `git add app/photosift/xmpsync.py app/photosift/library.py tests/test_xmpsync.py && git commit -m "XMP: module gộp/đọc/ghi .xmp cạnh ảnh gốc (không ghi đè dữ liệu Photo Mechanic)"`

### Task 2: Ghi nền khi sao/nhãn đổi

**Files:**
- Modify: `app/photosift/db.py` (thêm cột `ALTER TABLE photos ADD COLUMN xmt REAL` vào danh sách migrate)
- Modify: `app/photosift/library.py` (DEFAULT_SETTINGS, các hàm đổi rating/label, luồng ghi)
- Test: `tests/test_xmp_write.py`

**Interfaces:**
- Consumes: `sidecar`, `merge_xmp`, `write_atomic` (Task 1).
- Produces:
  - `DEFAULT_SETTINGS["xmp_sync"] = 1`
  - `Library._xmp_mark(ids: Iterable[int]) -> None` — bỏ qua khi `settings["xmp_sync"]` tắt; giữ thứ tự thao tác (id đánh dấu sau cùng nằm cuối).
  - `Library.xmp_flush() -> dict(written=int, failed=int)` — ghi đồng bộ toàn bộ hàng đợi; gom theo đường dẫn sidecar, id đánh dấu sau cùng thắng; ghi xong đặt `photos.xmt` = mtime file vừa ghi; lỗi → id ở lại hàng đợi, `self.status["xmp_err"]` = câu lỗi trong Global Constraints; thành công trọn vẹn → xoá `xmp_err`.
  - `Library.xmp_rewrite_all() -> dict(n=int)` — đánh dấu mọi id trong `cur` (rating ≠ 0 hoặc label ≠ "" hoặc đã có xmt) rồi `xmp_flush()`.
  - Luồng nền `_xmp_writer` (daemon, khởi động trong `__init__`) chạy `xmp_flush` theo nhịp debounce 2 s / tối đa 10 s; sau lỗi chờ 15 s.
- Gọi `_xmp_mark` sau UPDATE trong: `set_rating`, `set_ratings`, `set_label`, `cull_apply`, `cull_undo`, `suggest_rate`, `suggest_rate_undo`. KHÔNG gọi trong `_import_xmp_ratings` / lượt đọc (Task 3).

- [ ] **Step 1: Write the failing tests** (dùng fixture `lib_with`; gán `L.settings = dict(DEFAULT_SETTINGS)`, `L.status = {}` và hàng đợi bằng `L._xmp_init()` — hàm khởi tạo trạng thái hàng đợi không chạy luồng, `__init__` gọi nó rồi mới start luồng)

```python
def test_rate_then_flush_writes(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4); assert L.xmp_flush() == dict(written=1, failed=0)
    x = tmp_path / "IMG_0000.xmp"; assert b'xmp:Rating="4"' in x.read_bytes()
    assert abs(L.db.one("SELECT xmt FROM photos WHERE id=?", (ids[0],))["xmt"] - x.stat().st_mtime) < 0.01
def test_zero_without_file_not_created(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=2)]); prep(L)
    L.set_rating([ids[0]], 0); L.xmp_flush(); assert not list(tmp_path.glob("*.xmp"))
def test_pair_last_action_wins(lib_with, tmp_path):
    L, ids = lib_with([dict(path=str(tmp_path / "A.ARW")), dict(path=str(tmp_path / "A.JPG"))]); prep(L)
    L.set_rating([ids[0]], 5); L.set_rating([ids[1]], 2); L.xmp_flush()
    assert b'xmp:Rating="2"' in (tmp_path / "A.xmp").read_bytes()
def test_cull_and_label_marked(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.cull_apply([ids[0]]); L.set_label([ids[0]], "red"); L.xmp_flush()
    b = (tmp_path / "IMG_0000.xmp").read_bytes(); assert b'xmp:Rating="-1"' in b and b'xmp:Label="Red"' in b
def test_unwritable_keeps_queue_and_warns(lib_with, tmp_path):
    L, ids = lib_with([dict(path=str(tmp_path / "nope" / "X.JPG"))]); prep(L)   # thư mục không tồn tại
    L.set_rating([ids[0]], 3); r = L.xmp_flush()
    assert r == dict(written=0, failed=1) and L.status["xmp_err"] == "Không ghi được .xmp vào thư mục này — kiểm tra quyền ghi trên NAS"
    (tmp_path / "nope").mkdir(); assert L.xmp_flush()["written"] == 1 and "xmp_err" not in L.status
def test_setting_off_writes_nothing(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L); L.settings["xmp_sync"] = 0
    L.set_rating([ids[0]], 4); L.xmp_flush(); assert not list(tmp_path.glob("*.xmp"))
def test_rewrite_all(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=3), dict(rating=0), dict(rating=-1)]); prep(L)
    assert L.xmp_rewrite_all()["n"] == 2 and len(list(tmp_path.glob("*.xmp"))) == 2
```

- [ ] **Step 2: Run** — `python -m pytest tests/test_xmp_write.py -q` → Expected: FAIL (`AttributeError: _xmp_init`).
- [ ] **Step 3: Implement** cột `xmt`, setting, `_xmp_init`, `_xmp_mark` (OrderedDict id→None, `move_to_end`), `xmp_flush`, `xmp_rewrite_all`, luồng `_xmp_writer` (một `threading.Event` đánh thức khi có mark), và các lệnh gọi `_xmp_mark` liệt kê ở Interfaces. Gom lỗi theo từng sidecar: một file lỗi không chặn file khác.
- [ ] **Step 4: Run** — `python -m pytest -q` → Expected: tất cả pass (bài mới + 68 bài cũ).
- [ ] **Step 5: Commit** — `git commit -m "XMP: tự ghi .xmp cạnh ảnh gốc khi sao/loại/nhãn đổi (chạy nền, thử lại khi NAS lỗi)"`

### Task 3: Đọc lại .xmp mỗi lần mở thư mục

**Files:**
- Modify: `app/photosift/library.py` (`_import_xmp_ratings`, chỗ khởi chạy `_xmp_pass` ở `open_folder`/quét)
- Test: `tests/test_xmp_read.py`

**Interfaces:**
- Consumes: `read_sidecar` (Task 1); cột `xmt` (Task 2).
- Produces: `Library._import_xmp(ids: list[int]) -> int` — số ảnh đã cập nhật. Với mỗi id: có sidecar và `xmt IS NULL or abs(mtime - xmt) > 1.5` → `UPDATE photos SET rating=?, label=COALESCE(?, label), rsrc=0, xmt=?` (ghi đè, kể cả rating ≠ 0); không có sidecar → giữ luật cũ (chỉ ảnh rating=0, đọc XMP nhúng JPEG qua `read_xmp_rating`, chỉ ở lần quét đầu `xmp_done:<root>`). Có cập nhật → `self.status["xver"] = self.status.get("xver", 0) + 1`. Không gọi `_xmp_mark`.
- Lượt đọc chạy nền ở MỌI lần quét thư mục cho toàn bộ `ids` (bỏ điều kiện `first or fresh` cho phần sidecar).

- [ ] **Step 1: Write the failing tests**

```python
def test_newer_sidecar_overrides(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=3, label="")]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 5, "yellow"))
    assert L._import_xmp(ids) == 1
    r = L.db.one("SELECT rating,label,xmt FROM photos WHERE id=?", (ids[0],)); assert (r["rating"], r["label"]) == (5, "yellow") and r["xmt"]
    assert L.status["xver"] == 1
def test_own_write_not_reimported(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4); L.xmp_flush()
    L.db.x("UPDATE photos SET rating=2 WHERE id=?", (ids[0],))      # đổi trong app, file chưa đổi
    assert L._import_xmp(ids) == 0 and L.db.one("SELECT rating FROM photos WHERE id=?", (ids[0],))["rating"] == 2
def test_mtime_jitter_tolerated(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    L.set_rating([ids[0]], 4); L.xmp_flush()
    x = tmp_path / "IMG_0000.xmp"; st = x.stat(); os.utime(x, (st.st_atime, st.st_mtime + 1.0))
    assert L._import_xmp(ids) == 0
def test_unknown_label_keeps_app_label(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0, label="blue")]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 2, "").replace(b"xmp:Rating", b'xmp:Label="Winner" xmp:Rating', 1))
    L._import_xmp(ids); r = L.db.one("SELECT rating,label FROM photos WHERE id=?", (ids[0],)); assert (r["rating"], r["label"]) == (2, "blue")
def test_import_does_not_queue_writes(lib_with, tmp_path):
    L, ids = lib_with([dict(rating=0)]); prep(L)
    (tmp_path / "IMG_0000.xmp").write_bytes(merge_xmp(None, 5, "")); L._import_xmp(ids)
    assert L.xmp_flush() == dict(written=0, failed=0)
```

- [ ] **Step 2: Run** — `python -m pytest tests/test_xmp_read.py -q` → Expected: FAIL (`AttributeError: _import_xmp`).
- [ ] **Step 3: Implement** `_import_xmp`, nối vào `_xmp_pass` (đọc stat song song bằng `ThreadPoolExecutor(IO_WORKERS)` như hiện nay), sửa điều kiện khởi chạy lượt đọc.
- [ ] **Step 4: Run** — `python -m pytest -q` → Expected: tất cả pass.
- [ ] **Step 5: Commit** — `git commit -m "XMP: mỗi lần mở thư mục đọc lại .xmp mới hơn (kết quả lọc từ máy khác)"`

### Task 4: API + giao diện máy tính

**Files:**
- Modify: `app/photosift/server.py` (POST `/api/xmp/all` → `lib.xmp_rewrite_all()`)
- Modify: `app/photosift/web/index.html` (mục `#sXmp` trong `#status`, hộp nhỏ, khoá poll)
- Test: `tests/ui/xmp_ui.cjs` (theo kiểu `taste_ui.cjs`: route giả `/api/*`)

**Interfaces:**
- Consumes: `status.xmp_err`, `status.xver`, `settings.xmp_sync`, `/api/settings` có sẵn.
- Produces (UI):
  - `<span id="sXmp">` đặt ngay trước `#sNet`. Bình thường: chữ ".xmp ✓" (class `hint`), tắt: ".xmp tắt"; có `xmp_err`: chữ cảnh báo (class `warn`) đúng câu lỗi. Bấm vào → hộp có checkbox `#xmpSync` "Ghi .xmp vào thư mục ảnh gốc" (POST `/api/settings {xmp_sync:0|1}`) và nút `#xmpAll` "Ghi lại .xmp cho cả thư mục" (POST `/api/xmp/all`, xong toast "Đã ghi .xmp cho N ảnh").
  - Khoá `key` trong `poll()` thêm `':'+(st.xver||0)` để lưới tải lại khi lượt đọc .xmp nhập được sao.

- [ ] **Step 1: Write the failing UI test** `tests/ui/xmp_ui.cjs`: mở trang với status `{xmp_err:'Không ghi được .xmp vào thư mục này — kiểm tra quyền ghi trên NAS', settings:{xmp_sync:1}}` → `#sXmp` chứa câu lỗi và có class `warn`; bấm `#sXmp` → bấm `#xmpAll` → đã gọi POST `/api/xmp/all`; bỏ chọn `#xmpSync` → đã gọi `/api/settings` với body `{xmp_sync:0}`; đổi status sang `xver:1` → `/api/photos` được gọi lại; không có `pageerror`. In `ok`.
- [ ] **Step 2: Run** — `node tests/ui/xmp_ui.cjs` → Expected: FAIL (không tìm thấy `#sXmp`).
- [ ] **Step 3: Implement** route và giao diện như Interfaces.
- [ ] **Step 4: Run** — `for f in tests/ui/*.cjs; do node $f; done` → mọi bài in `ok`; `python -m pytest -q` → pass.
- [ ] **Step 5: Commit** — `git commit -m "XMP: thanh trạng thái .xmp, công tắc và nút Ghi lại .xmp cho cả thư mục"`
