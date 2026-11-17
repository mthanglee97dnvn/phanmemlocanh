# Học gu chọn ảnh & đề xuất N tấm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Chọn khoảng N tấm" gắn dấu ✦ đề xuất theo gu học được từ sao người dùng (cộng gu mặc định đóng gói sẵn), đọc được sao cũ từ Photo Mechanic/Lightroom.

**Architecture:** Lõi thuần numpy trong `app/photosift/taste.py` (đặc trưng → hồi quy logistic có tiên nghiệm → điểm → chọn N tấm), không phụ thuộc `Library`. `library.py` lo dữ liệu: cột mới, đọc sao `.xmp`, vector CLIP chạy nền, gom ảnh theo đám, gọi `taste.py`. `server.py` thêm route; `index.html` thêm phần "Chọn ảnh đẹp", hộp "Gu chọn ảnh", bộ lọc ✦. `tools/train_taste.py` luyện gu mặc định từ file xuất.

**Tech Stack:** Python 3.12 + numpy + sqlite + onnxruntime (CLIP có sẵn), JS thuần, pytest, Playwright (node).

**Spec:** `docs/superpowers/specs/2026-11-17-gu-chon-anh-design.md`

## Global Constraints
- Không thêm thư viện; offline; Windows + macOS.
- Không tự chấm sao, không tự gắn ✕; đề xuất chỉ là cột `sugg`.
- Nhãn học: sao ≥ 1 = giữ (trọng số 1; `rsrc=1` → 0.3); ✕ người bấm = bỏ (1); ✕ nằm trong `cull_log` = bỏ (0.5); 0 sao = bỏ (1).
- Đám đã lọc xong: ≥ 200 ảnh đã phân tích và ≥ 3% ảnh sao ≥ 1; mỗi ảnh thuộc root dài nhất chứa nó.
- Học gu riêng: 40 đám gần nhất (theo `catalog.opened`), ảnh bỏ lấy mẫu tối đa 4× số ảnh giữ (hạt giống cố định); dưới 10 giây.
- Mô hình hai bản trong một file: `full` (số đo + CLIP 512) và `base` (chỉ số đo); ảnh thiếu CLIP chấm bằng `base`.
- Gu mặc định: `app/models/taste_default.npz` (qua `models.path`); thiếu thì chấm bằng `score` hiện có, nhãn "gu cơ bản (chưa học)".
- Gu riêng: `HOME/taste.npz`, phạt L2 kéo về trọng số mặc định.
- Đọc `.xmp`: chỉ áp cho ảnh đang 0 sao; rating âm → -1; không ghi đè sao trong app.
- Chọn N: tất định; sao ≥1 luôn vào và tính trong N; mỗi `grp` ≤ 1 tấm; bỏ trùng cos CLIP > 0.95 và cách < 60 giây; phủ đoạn thời gian (khoảng trống > 10 phút, đoạn ≥ 20 ảnh).
- Đọc = GET; ghi = POST có thân. Chữ tiếng Việt. Tác giả commit MThanglee.

## Review Focus
- Người dùng chấm lại sao một tấm vừa được "Chấm 1 sao cho tất cả đề xuất" → `rsrc` về 0 (test `test_rerate_resets_rsrc`).
- Đám chỉ có JPEG không `.xmp`, `.xmp` hỏng/không có Rating, hoặc `ảnh.ARW.xmp` → không lỗi, không đổi sao sai (test `test_xmp_variants`).
- N lớn hơn số ảnh khác nhau, hoặc số ảnh đã có sao > N → không treo, báo đúng (test `test_pick_more_than_available`, `test_pick_stars_exceed_n`).
- Đám không có model CLIP / vector trống một phần → chấm bằng `base`, vẫn đủ N (test `test_score_mixed_clip`).
- Một thư mục mở lồng trong thư mục khác → ảnh chỉ tính một đám (test `test_roll_longest_root`).

---

### Task 1: Lõi `taste.py`

**Files:**
- Create: `app/photosift/taste.py`
- Test: `tests/test_taste.py`

**Interfaces:**
- Produces:
  - `FEATS: list[str]` — tên cột số đo theo thứ tự cố định.
  - `features(rows: list[dict]) -> np.ndarray` (float32, n×len(FEATS)) — đã chuẩn hoá **trong đám** (thứ hạng phần trăm 0..1); rows có các khoá: `sharp,fsharp,nfaces,lum,lo,hi,ear_min,smile,away,focus_c,scene,grp,best,taken,couple` (`couple`: bool có cô dâu/chú rể). Tự tính thứ hạng nét trong `grp`, cỡ nhóm, mật độ ±30s.
  - `fit(X: np.ndarray, C: np.ndarray|None, y: np.ndarray, w: np.ndarray, prior: dict|None=None, lam: float=1.0, seed: int=0) -> dict` — trả `{"base":{"w","b"}, "full":{"w","b"}|None, "n":int}`; `C` (n×512, NaN hàng = thiếu); `full` học chỉ trên hàng có CLIP; cân lớp; mini-batch, float32.
  - `score(model: dict, X, C) -> np.ndarray` — 0..1; hàng có CLIP dùng `full` (nếu có), còn lại `base`.
  - `pick(n: int, s: np.ndarray, rows: list[dict], C: np.ndarray|None) -> dict` — `{"ids":[...], "note": str}`; rows cần `id, rating, grp, taken`.
  - `agreement(model, X, C, y_keep: np.ndarray, rows) -> float` — tỉ lệ trùng khi pick N = số ảnh giữ.
  - `save(path, model, meta: dict)`, `load(path) -> (model, meta)|None`.

- [ ] **Step 1: Viết test hỏng** `tests/test_taste.py` với dữ liệu giả tổng hợp (hạt giống cố định):
```python
def test_fit_learns_signal():           # nhãn = nét cao & cười → agreement ≥ 0.8, ngẫu nhiên ≈ tỉ lệ giữ
def test_prior_pulls_small_data():      # 30 mẫu ngược tiên nghiệm: trọng số gần prior hơn khi lam lớn
def test_score_mixed_clip():            # nửa hàng C = NaN → score không NaN, dùng base cho các hàng đó
def test_pick_one_per_group():          # 3 ảnh cùng grp điểm cao nhất → chỉ 1 vào; tổng = n
def test_pick_keeps_starred():          # ảnh sao ≥1 điểm thấp vẫn có trong ids
def test_pick_stars_exceed_n():         # 5 ảnh sao, n=3 → ids = 5 ảnh sao, note chứa "nhiều hơn"
def test_pick_more_than_available():    # n=100 trên 10 ảnh khác nhau → 10 ids, note chứa "chỉ tìm được 10"
def test_pick_timeline_cover():         # đoạn 2 (sau khoảng trống 30 phút, 25 ảnh điểm thấp) vẫn có 1 tấm
def test_pick_deterministic():          # gọi 2 lần → cùng ids
def test_pick_skips_rejected():         # rating -1 không bao giờ vào
def test_save_load_roundtrip(tmp_path)
def test_fit_speed():                   # 200_000 × len(FEATS) + 30_000 hàng CLIP 512 → fit < 10 s
```
- [ ] **Step 2: Chạy** `python3 -m pytest tests/test_taste.py -q` → FAIL (ImportError `photosift.taste`).
- [ ] **Step 3: Cài `taste.py`** theo Interfaces và Global Constraints. Logistic: Adam mini-batch 4096, 6 epoch, phạt `lam*||w - w_prior||²` (prior thiếu → 0); `base` và `full` luyện riêng (full = [X | C]).
- [ ] **Step 4: Chạy lại** → 12 passed.
- [ ] **Step 5: Commit** `Gu chọn ảnh: lõi học và chọn N tấm (taste.py)`

### Task 2: Dữ liệu — cột mới, đám, sao `.xmp`, nguồn sao

**Files:**
- Modify: `app/photosift/db.py` (ALTER: `clip BLOB`, `clipv TEXT`, `sugg INTEGER DEFAULT 0`, `rsrc INTEGER DEFAULT 0`)
- Modify: `app/photosift/library.py` (`_scan`: đọc `.xmp`; `set_rating`/`set_ratings`: `rsrc=0`; hàm đám)
- Test: `tests/test_taste_data.py` (dùng fixture `lib_with` của `tests/conftest.py`, mở rộng nhận thêm cột)

**Interfaces:**
- Produces:
  - `read_xmp_rating(path: str) -> int|None` (module-level trong `library.py`): sidecar `stem.xmp`/`stem.XMP`/`file.ext.xmp`, hoặc XMP nhúng trong JPEG (đọc ≤ 256 KB đầu file); trả -1..5 hoặc None.
  - `Library._roll_of(paths: list[str]) -> dict[str, str]` — path → root dài nhất trong `catalog`.
  - `Library._finished_rolls() -> list[dict]` — `{root, n, kept, opened}` thoả ngưỡng, mới nhất trước.
  - `Library._roll_rows(root) -> list[dict]` — rows cho `taste.features` + `id, rating, rsrc, clip, in_cull_log`.

- [ ] **Step 1: Test hỏng:**
```python
def test_xmp_variants(tmp_path):   # 'IMG.ARW'+'IMG.xmp' Rating=3 → 3; 'B.ARW.xmp' Rating=-1 → -1; xmp hỏng → None; JPEG nhúng Rating=2 → 2
def test_scan_applies_xmp_only_unrated(lib_with)   # ảnh đã 4 sao trong app giữ 4; ảnh 0 sao nhận sao .xmp
def test_rerate_resets_rsrc(lib_with)              # rsrc=1 → set_rating → rsrc=0
def test_roll_longest_root(lib_with)               # catalog /a và /a/b → ảnh trong /a/b thuộc /a/b
def test_finished_rolls_threshold(lib_with)        # 199 ảnh hoặc 2% sao → không tính
```
- [ ] **Step 2: Chạy** `python3 -m pytest tests/test_taste_data.py -q` → FAIL.
- [ ] **Step 3: Cài** theo Interfaces. Việc đọc `.xmp` trong `_scan` chỉ chạy cho ảnh `rating=0`, gom `UPDATE` theo lô; không để lỗi đọc `.xmp` làm hỏng lần quét.
- [ ] **Step 4: Chạy lại** → pass; chạy cả `python3 -m pytest tests -q` → pass.
- [ ] **Step 5: Commit** `Gu chọn ảnh: đọc sao từ .xmp (Photo Mechanic/Lightroom), nguồn sao, gom ảnh theo đám`

### Task 3: Vector CLIP chạy nền

**Files:**
- Modify: `app/photosift/scene.py` (`embed(bgr) -> np.ndarray|None`; `classify` dùng `embed`; `MODEL_ID: str` = tên file + kích thước model)
- Modify: `app/photosift/library.py` (`_clip_backfill(cancel)` cạnh `_scene_backfill`, gọi sau nó)
- Test: `tests/test_taste_data.py`

**Interfaces:**
- Produces: cột `clip` (float16 bytes, 512), `clipv = scene.MODEL_ID`; `Library._clip_vec(row) -> np.ndarray|None` (None nếu `clipv` khác `MODEL_ID`).

- [ ] **Step 1: Test hỏng:** `test_clip_backfill_fills_and_versions` — monkeypatch `scene.embed` trả vector cố định, `scene.available` True; ảnh có file `PREVIEWS/<id>.jpg` → cột `clip` có 1024 byte, `clipv` đúng; đổi `MODEL_ID` → `_clip_vec` trả None; ảnh không có cache → bỏ qua, không lỗi.
- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài.** Ảnh thư mục đang mở trước; 2 luồng `_low_prio`; ghi theo lô 100; `classify` không đổi kết quả cũ.
- [ ] **Step 4: Chạy lại** → pass.
- [ ] **Step 5: Commit** `Gu chọn ảnh: tính vector nội dung ảnh (CLIP) chạy nền`

### Task 4: Học, đề xuất, xuất — Library + route

**Files:**
- Modify: `app/photosift/library.py` (`taste_info`, `taste_learn`, `taste_rolls_set`, `suggest`, `suggest_clear`, `suggest_rate`, `taste_export`; `photos()` thêm `sugg`)
- Modify: `app/photosift/server.py`
- Create: `tools/train_taste.py`
- Test: `tests/test_taste_lib.py`

**Interfaces:**
- Consumes: Task 1 (`features, fit, score, pick, agreement, save, load`), Task 2 (`_finished_rolls, _roll_rows`), Task 3 (`_clip_vec`).
- Produces:
  - `taste_info() -> {"source":"default"|"personal"|"basic", "rolls":[{root,n,kept,on}], "n_rolls":int, "n_photos":int, "agree":float|None, "learned":float|None, "stale":bool}`
  - `taste_learn() -> taste_info()` (đồng bộ; luyện trên đám bật; agreement = luyện trừ đám mới nhất, đo trên đám đó; lưu `HOME/taste.npz`)
  - `taste_rolls_set(off: list[str]) -> taste_info()` (lưu trong `meta` key `taste_off`)
  - `suggest(n: int) -> {"ids":[...], "n":int, "note":str, "source":str}` (đặt `sugg` cho thư mục đang mở)
  - `suggest_clear() -> {"ok":True}`; `suggest_rate() -> {"ok":True,"n":int,"batch":int}` (chấm 1 sao ảnh `sugg=1` đang 0 sao, `rsrc=1`, ghi `cull_log`-kiểu để Hoàn tác)
  - `taste_export(dest: str) -> {"ok":True,"path":str,"rows":int}` — `taste_data.npz`: `X, C(float16, NaN), y, w, roll(int)`; không có đường dẫn/tên file.
  - Route: GET `/api/taste`; POST `/api/taste/learn {}`, `/api/taste/rolls {off}`, `/api/suggest {n}`, `/api/suggest/clear {}`, `/api/suggest/rate {}`, `/api/taste/export {dest}`.
  - `tools/train_taste.py file1.npz [file2…] -o app/models/taste_default.npz` — in agreement theo từng đám giữ lại.

- [ ] **Step 1: Test hỏng** (dựng 3 đám giả trong DB tạm với sao theo luật biết trước):
```python
def test_info_basic_without_models(lib_with)       # không có taste_default/taste.npz → source "basic"
def test_learn_then_personal(lib_with)             # taste_learn → source "personal", agree ≥ 0.6, file tồn tại
def test_rolls_off_excluded(lib_with)               # tắt 1 đám → n_rolls giảm
def test_suggest_sets_sugg_and_keeps_stars(lib_with)
def test_suggest_rate_marks_rsrc_and_undo(lib_with) # undo đưa về 0 sao, rsrc 0
def test_export_has_no_paths(lib_with, tmp_path)    # npz không có chuỗi đường dẫn; y khớp nhãn
def test_basic_suggest_uses_score(lib_with)         # không mô hình → thứ tự theo score
```
- [ ] **Step 2: Chạy** `python3 -m pytest tests/test_taste_lib.py -q` → FAIL.
- [ ] **Step 3: Cài** theo Interfaces; thêm route (đọc GET, ghi POST); `train_taste.py` dùng `taste.fit` không prior, lam nhỏ.
- [ ] **Step 4: Chạy** `python3 -m pytest tests -q` → pass; `python3 tools/train_taste.py <file xuất từ test>` chạy được và in agreement.
- [ ] **Step 5: Commit** `Gu chọn ảnh: học gu, đề xuất N tấm, xuất dữ liệu học`

### Task 5: Giao diện

**Files:**
- Modify: `app/photosift/web/index.html`
- Modify: `WHATSNEW.txt`
- Test: `tests/ui/taste_ui.cjs` (index.html + API giả, như `moment_sync.cjs`)

**Interfaces:**
- Consumes: route Task 4; `photos[].sugg`.
- Produces: phần "Chọn ảnh đẹp" trong hộp Tự động lọc (`#tN`, `#tGo`, `#tInfo`, link `#tTaste`); hộp `openTaste()`; bộ lọc `'sugg'` nhãn `'✦ Đề xuất'`; dấu `.sugg` trên ô ảnh; nút thanh `#bSuggRate` "Chấm 1 sao cho tất cả đề xuất", `#bSuggClear` "Bỏ đề xuất" (chỉ hiện khi có đề xuất).

- [ ] **Step 1: Test hỏng** `tests/ui/taste_ui.cjs`:
  - mở Tự động lọc → thấy "Đang dùng: gu mặc định" theo `/api/taste` giả; gõ `400` → `POST /api/suggest {n:400}`; gõ `15%` → n = 15% số ảnh;
  - sau đề xuất: bộ lọc là `sugg`, ô ảnh đề xuất có `.sugg`, hai nút thanh hiện;
  - `#bSuggRate` → `POST /api/suggest/rate {}`, toast có số ảnh; Hoàn tác có trong `S.undo`;
  - hộp Gu: tắt một đám → `POST /api/taste/rolls {off:[root]}`; "Học lại" → `POST /api/taste/learn {}`; Alt+mở hộp → nút "Xuất dữ liệu học" hiện;
  - note "nhiều hơn" / "chỉ tìm được" từ máy chủ hiện thành toast; không `pageerror`.
- [ ] **Step 2: Chạy** `node tests/ui/taste_ui.cjs` → FAIL.
- [ ] **Step 3: Cài** giao diện; tự gọi `taste_learn` nền khi mở phần "Chọn ảnh đẹp" mà `stale=true`; nhớ N lần trước bằng `lsGet/lsSet('ps.suggN')`. WHATSNEW: `✦ Chọn ảnh đẹp: gõ số ảnh cần giao, app đề xuất theo gu của bạn và ngày càng giống gu bạn` và `⭐ Đọc sao cũ từ Photo Mechanic/Lightroom (.xmp)`.
- [ ] **Step 4: Chạy** `node tests/ui/taste_ui.cjs`, `node tests/ui/pair_ui.cjs`, `node tests/ui/moment_sync.cjs`, `python3 -m pytest tests -q` → tất cả pass. Chụp màn hình hộp Tự động lọc và lưới có ✦ để duyệt mắt.
- [ ] **Step 5: Commit** `Gu chọn ảnh: giao diện Chọn ảnh đẹp, bộ lọc ✦ Đề xuất, hộp Gu chọn ảnh`
