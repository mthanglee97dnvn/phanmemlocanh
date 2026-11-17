# Đồng bộ giờ bằng khoảnh khắc chung — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Màn hình hai ảnh cạnh nhau: chọn 1 tấm máy mốc + 1 tấm cùng khoảnh khắc của máy cần chỉnh → tính lệch và áp cho cả máy cần chỉnh.

**Architecture:** Lõi Python (`Library` trong `library.py`) thêm 3 hàm đọc/ghi trên bảng `photos` (cột `cam`, `taken`, `toff`, bảng tạm `cur`), lộ qua 3 route trong `server.py`. Giao diện là một hàm `openMomentSync()` trong `index.html` (cùng kiểu với `openClockSync()` đã có trên nhánh `dongbo-moc`); tìm tấm gần nhất làm phía trình duyệt trên danh sách `[id, taken]`.

**Tech Stack:** Python 3 + numpy + sqlite (lõi), JS thuần trong `index.html`, pytest, Playwright (node) cho kiểm thử giao diện.

**Spec:** `docs/superpowers/specs/2026-11-17-dong-bo-khoanh-khac-design.md`

## Global Constraints

- Làm trên nhánh `dongbo-moc` (đã có `cam_list`, `cam_ref`, `cam_step`, `cam_settime`, `_fill_cams`, `openClockSync`). Không đẩy lên GitHub khi chưa có lệnh "đẩy".
- Không sửa file ảnh gốc; lệch lưu ở cột `toff` (giây, cộng vào `taken`); áp bằng `cameras_apply({cam: offset})`.
- Chạy offline, Windows + macOS, giao diện tối sẵn có (biến `--field`, `--tx`, `--line`, `--acc`).
- Lệnh đọc dùng GET, lệnh ghi dùng POST và gọi `api(path, {...})` CÓ thân (bài học lỗi "Not Found" 1.2.2).
- Chữ hiển thị tiếng Việt; câu xem trước bắt buộc dạng: `Lệch: +7 giây (máy chạy chậm) · áp cho 640 ảnh của <máy>`.
- Tác giả commit giữ nguyên (MThanglee); thêm dòng `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Chọn hai tấm CÙNG một máy → từ chối, báo "Hai tấm cùng một máy — hãy chọn tấm của máy khác" (test `test_pair_same_camera`).
- Máy cần chỉnh không đọc được danh tính (`cam == "?"`) → từ chối, không ghi `toff` cho nhóm "?" (test `test_pair_unknown_camera`).
- Máy mốc đã có lệch (chỉnh nối tiếp) → lệch tính từ giờ hiệu dụng `taken+toff` của tấm mốc (test `test_pair_uses_ref_effective_time`).
- Lệch cả ngày → ước lượng vẫn ra đúng và trả về dưới 2 giây (test `test_estimate_day_offset_fast`); ô ± ngày làm bên phải nhảy tới đúng tấm (UI test bước "± 1 ngày").
- Nhiều tấm trùng một giây (chụp liên tiếp) → lật ← → đi từng tấm một, không nhảy cóc (test `test_photos_order_ties` + UI test lật qua 3 tấm cùng giây).

---

### Task 1: Lõi — danh sách ảnh theo máy, ước lượng nhanh, ghép cặp

**Files:**
- Modify: `app/photosift/library.py` (`_estimate_offset`; thêm `cam_photos`, `cam_estimate`, `cam_pair` cạnh `cam_settime`)
- Modify: `app/photosift/server.py` (GET `/api/cameras/photos`, GET `/api/cameras/estimate`, POST `/api/cameras/pair`, đặt cạnh các route `/api/cameras/*` đã có)
- Test: `tests/test_cam_sync.py` (mới), `tests/conftest.py` (mới: fixture `lib_with`)

**Interfaces:**
- Consumes: `Library._fill_cams()`, `Library.cameras_apply(offsets: dict)`, `Library._estimate_offset(ref_ts, cam_ts) -> (float, float)`, `DB(path)` từ `photosift.db` (đặt `photosift.db.HOME` sang thư mục tạm trước khi tạo).
- Produces:
  - `Library.cam_photos(cam: str) -> {"photos": [[id:int, taken:float], ...]}` — chỉ ảnh trong `cur`, `taken>0`, xếp `taken, id`.
  - `Library.cam_estimate(ref_cam: str, cam: str) -> {"offset": int, "conf": float, "source": "existing"|"auto"|"none"}` — nếu máy `cam` đã có `toff` khác 0 thì trả lệch đó (`existing`); nếu không thì `_estimate_offset([taken+toff của ref_cam], [taken của cam])` (`auto`); thiếu dữ liệu → `{"offset":0,"conf":0,"source":"none"}`.
  - `Library.cam_pair(ref_id: int, pid: int) -> {"ok":True,"cam":str,"offset":int,"n":int}` hoặc `{"error": str}`; `offset = round(ref.taken + ref.toff - photo.taken)`, áp cho máy của `pid`.
  - Route: `GET /api/cameras/photos?cam=…`, `GET /api/cameras/estimate?ref=…&cam=…`, `POST /api/cameras/pair {ref, id}`.

- [ ] **Step 1: Fixture `lib_with` trong `tests/conftest.py`** (factory: `lib_with(rows) -> Library`): tạo DB tạm + JPG có EXIF thật bằng PIL (`Exif` IFD0 0x10F make, 0x110 model; IFD 0x8769: 0x9003 DateTimeOriginal, 0xA431 serial), chèn `photos(path,dir,taken,ready,rating,label)` và `cur`; trả `Library.__new__` với `db`, `cam={}`, `regroup=lambda *a,**k: None`. Hàm dựng nhận danh sách `(máy, serial, taken)`.

- [ ] **Step 2: Viết test thất bại trong `tests/test_cam_sync.py`**

```python
def test_photos_order_ties(lib_with):        # 3 tấm máy B cùng giây 15:02:24
    L = lib_with([("A","1",t0)]*3 + [("B","2",t0+5)]*3)
    ids = [p[0] for p in L.cam_photos(cam_B)["photos"]]
    assert ids == sorted(ids) and len(ids) == 3
def test_pair_basic(...):                    # mốc A 15:02:31, B 15:02:24 → +7, chỉ máy B đổi
    r = L.cam_pair(a_id, b_id); assert r["offset"] == 7 and r["n"] == n_B
    assert all(toff == 0 for toff in toffs(cam_A))
def test_pair_same_camera(...):  assert "error" in L.cam_pair(a1, a2)
def test_pair_unknown_camera(...): assert "error" in L.cam_pair(a_id, unknown_id)   # ảnh không EXIF máy → cam "?"
def test_pair_uses_ref_effective_time(...):  # máy A đã toff=+60 → B nhận 60+7
    L.cameras_apply({cam_A: 60}); assert L.cam_pair(a_id, b_id)["offset"] == 67
def test_estimate_existing(...):  L.cameras_apply({cam_B: 120}); assert L.cam_estimate(cam_A, cam_B) == {"offset":120,"conf":1.0,"source":"existing"}
def test_estimate_day_offset_fast(...):      # 300 tấm/máy, nhịp ngẫu nhiên giống nhau, B lệch -86400+7 giây
    t = time.perf_counter(); r = L.cam_estimate(cam_A, cam_B)
    assert r["source"] == "auto" and r["offset"] == 86400 - 7 and time.perf_counter() - t < 2.0
def test_estimate_matches_old_small():      # 40 mốc ngẫu nhiên, lệch +13s: FFT ra đúng như np.correlate cũ
    assert Library._estimate_offset(ref, [t - 13 for t in ref])[0] == 13.0
```

- [ ] **Step 3: Chạy `cd app && python -m pytest ../tests -q` — Expected: FAIL (`AttributeError: cam_photos`, test thời gian > 2 giây).**

- [ ] **Step 4: Thay `np.correlate(a, b, "full")` trong `_estimate_offset` bằng tương quan FFT (numpy `rfft/irfft`, độ dài ≥ `len(a)+len(b)-1`), giữ nguyên ý nghĩa `lag` và phần tinh chỉnh 1 giây; thêm `cam_photos`, `cam_estimate`, `cam_pair` (gọi `_fill_cams()` đầu `cam_photos`/`cam_pair`; lỗi: thiếu ảnh/giờ → "Không tìm thấy ảnh hoặc ảnh không có giờ chụp"; cùng máy → câu trong Review Focus; `cam=="?"` → "Không đọc được máy ảnh của tấm này"); cập nhật `self.cam["cams"]` như `cam_settime`; thêm 3 route.**

- [ ] **Step 5: Chạy lại pytest — Expected: tất cả PASS. Chạy `python -c "import ast;ast.parse(open('app/photosift/server.py').read())"` — không lỗi.**

- [ ] **Step 6: Commit** `git add tests app/photosift/library.py app/photosift/server.py && git commit -m "Đồng bộ máy: lõi ghép cặp khoảnh khắc + ước lượng lệch nhanh (FFT)"`

### Task 2: Giao diện — màn hình hai ảnh cạnh nhau

**Files:**
- Modify: `app/photosift/web/index.html` (CSS cạnh khối `.ck-*`; hàm `openMomentSync` đặt trước `openClockSync`; nút trong hộp "Đồng bộ máy")
- Modify: `WHATSNEW.txt` (mục đầu)
- Test: `tests/ui/moment_sync.cjs` (mới) — trích `modal`, `esc`, `openMomentSync` từ `index.html` vào trang thử, `api()` giả lập 3 máy, ảnh giả bằng PIL

**Interfaces:**
- Consumes: route Task 1; đã có `GET /api/cameras/list` → `{cams:[{key,n,offset,first}]}`, `GET /api/cameras/ref?id=` → `{id,name,cam,orig:{date,time},eff:{date,time},offset}`, `/api/preview?id=…&s=2000|0`, `modal()`, `toast()`, `loadPhotos()`, `fmt()`, `esc()`, `S.cur`.
- Produces: `openMomentSync(startId: number|null)`; nút `#camMoment` ("Ghép khoảnh khắc chung…", nút chính) và `#camClock` (giữ, nút phụ) trong hộp "Đồng bộ máy".

- [ ] **Step 1: Viết `tests/ui/moment_sync.cjs`** kiểm: mở với `startId` thuộc máy mốc → trái hiện tấm đó; chọn máy B → phải tự nhảy tới tấm B có `taken+estimate` gần giờ tấm mốc nhất; `ArrowRight` đổi bên phải 1 tấm (qua đủ 3 tấm cùng giây), `Shift+ArrowRight` đổi bên trái; kéo thanh kéo về 0 → tấm B đầu tiên; đặt ô ± `1 ngày` → phải nhảy tới tấm gần `giờ mốc − (lệch)`; nút áp gửi `POST /api/cameras/pair {ref, id}` đúng hai id đang hiện; câu xem trước khớp mẫu trong Global Constraints; không có `pageerror`.

- [ ] **Step 2: Chạy `node tests/ui/moment_sync.cjs` — Expected: FAIL (`openMomentSync is not defined`).**

- [ ] **Step 3: Viết `openMomentSync(startId)`**: bố cục theo sơ đồ trong spec (hai cột, mỗi cột: chọn máy, ảnh lớn bấm phóng to, `‹ tên · HH:MM:SS ›`; cột phải thêm `<input type=range>` theo chỉ số ảnh). Trạng thái: `ref={cam,photos,idx}`, `tgt={cam,photos,idx}`, `offset` (giây). Lệch hiện = giờ hiệu dụng tấm trái − giờ gốc tấm phải. Ô ± ngày/giờ/phút/giây chỉnh `offset` rồi nhảy phải tới tấm có `taken + offset` gần giờ tấm trái nhất (tìm nhị phân). Máy mốc mặc định = máy nhiều ảnh nhất; máy cần chỉnh mặc định = máy kế tiếp. Phím: ←/→ phải, Shift+←/→ trái, Home/End phải; bỏ qua khi đang gõ trong ô. Áp xong: `loadPhotos()`, toast, cập nhật nhãn máy trong danh sách chọn, giữ hộp mở. Thêm CSS `.mm-*` cho hai cột (xếp dọc khi rộng < 760px).

- [ ] **Step 4: Thêm nút `#camMoment` (class `pri`) vào hộp "Đồng bộ máy" mở `openMomentSync(S.cur)`; `#camClock` giữ làm nút thường. Thêm mục WHATSNEW: "Đồng bộ giờ nhiều máy bằng khoảnh khắc chung".**

- [ ] **Step 5: Chạy `node tests/ui/moment_sync.cjs` và `node --check` trên script trích từ `index.html` — Expected: PASS, không lỗi cú pháp. Chụp màn hình hộp thoại (deviceScaleFactor 2) để duyệt mắt: hai ảnh rõ, chữ ngày/giờ đọc được trên nền tối.**

- [ ] **Step 6: Commit** `git add app/photosift/web/index.html WHATSNEW.txt tests/ui && git commit -m "Đồng bộ máy: màn hình ghép khoảnh khắc chung (hai ảnh cạnh nhau)"`
