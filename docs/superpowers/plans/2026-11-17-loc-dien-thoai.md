# Lọc kỹ thuật trên điện thoại — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trang `/m` thành công cụ lọc kỹ thuật thay máy tính: Lưới để quét, Xem để soi nét và chọn trong loạt trùng, chọn nhiều, hoàn tác, Tự động lọc, ✦ Chọn ảnh đẹp, bố cục iPad chia đôi.

**Architecture:**
- Viết lại `app/photosift/web/mobile.html` thành một trang hai chế độ (Lưới / Xem). Các hàm thuần (lọc, gộp loạt, sắp xếp, hoàn tác, toán zoom) nằm trong khối `<script>` riêng, đặt dạng `function tên(` ở đầu dòng để test node trích ra được.
- Backend chỉ thêm `GET /api/photos/ver` và phục vụ `web/cull.js` (hàm chọn ứng viên Tự động lọc dùng chung với máy tính).

**Tech Stack:** HTML/CSS/JS thuần (Safari iOS 15+, Chrome Android), Python http.server, pytest, Playwright (node, `hasTouch`, viewport 390×844 và 1180×820).

**Spec:** `docs/superpowers/specs/2026-11-17-loc-dien-thoai-design.md` (gồm mục "Quyết định của Claude…" và "iPad / màn rộng"). Demo đã duyệt: canvas "Demo lọc ảnh trên điện thoại & iPad". Bố cục, nhãn và màu theo demo.

## Global Constraints
- Màu: nền `#0F0F11`, nhấn `#E8A33D`, đỏ `#E5564B` (chữ đỏ `#F07A70`), chữ `#EDEDEF`, viền `#2A2A30`. Font Be Vietnam Pro (Google Fonts, có font hệ thống dự phòng).
- Vùng chạm ≥ 44px. Bộ lọc và nút chính ở nửa dưới màn hình.
- Mọi POST gửi thân JSON, ít nhất `{}`. Không thư viện ngoài. Không đổi hành vi app máy tính.
- Lưới: mặc định 3 cột dọc / 5 cột ngang, chọn được 2/3/4 (nhớ bằng localStorage, bọc try/catch). Ảnh nhỏ `/thumb/<id>.jpg?v=<tv>`. Cuộn ảo hoá, chỉ giữ DOM ±3 màn hình.
- Gộp loạt trùng mặc định bật, tắt được. Lọc trước rồi mới gộp. Ô hiện tấm `best` còn trong lọc, hoặc tấm đầu nếu `best` bị lọc mất. `×N` = số ảnh loạt còn trong lọc.
- Xem:
  - Ảnh: bản cache `/api/preview?id=<id>` hiện ngay, sau đó thay bằng `&s=<min(2400, cạnh dài màn × dpr)>&hq=1`. Khi zoom > 1.5× thì tải `s=0`.
  - Zoom 1×–4×. Chạm đúp: nếu có `focus` thì tới 100% tại điểm nét, không thì 2.5× tại chỗ chạm. Chạm đúp lần nữa về vừa màn hình.
  - Vuốt ngang chỉ là Giữ/Loại khi ở mức vừa màn hình. Chạm mép (⅓ trái / ⅓ phải) để lùi/tới, chờ 250ms để phân biệt với chạm đúp.
- "Chọn tấm này": tấm đang xem ★1 (giữ sao cũ nếu đã có), các tấm `rating==0` khác cùng `grp` thành -1.
- Hoàn tác: tối đa 50 bước, lưu giá trị cũ từng ảnh. Chỉ trả lại ảnh còn đúng giá trị điện thoại đã đặt, ảnh đã đổi thì bỏ qua và báo "bỏ qua X ảnh đã sửa trên máy tính". Toast có nút "Hoàn tác" 4 giây. Tự động lọc dùng `/api/cull/undo`; chấm sao đề xuất dùng `/api/suggest/rate/undo`.
- Đồng bộ: hỏi `/api/photos/ver` mỗi 10 giây và khi `visibilitychange` → visible; chỉ tải `/api/photos` khi số thay đổi. Thao tác đang gửi dở không bị dữ liệu mới đè.
- Chip người: người có tên trước, sau đó người chưa tên ≥ 20 ảnh; tối đa 10, xếp theo số ảnh; thêm chip "Highlight".
- Màn ≥ 900px: Lưới (5 cột, ~44% bề ngang) bên trái, Xem bên phải, cùng lúc.
- Tác giả commit MThanglee; trailer như các commit trước.

## Review Focus
- Danh sách rỗng (thư mục chưa phân tích xong, hoặc lọc không ra ảnh nào) → hiện thông báo, không lỗi JS (`test_empty_states` trong mobile_grid.cjs).
- Ảnh không có `focus` → chạm đúp vẫn phóng tại chỗ chạm (mobile_view.cjs `double tap without focus`).
- `grp` chỉ còn 1 ảnh trong lọc → không hiện "×1", không hiện dải loạt (mobile_grid.cjs và mobile_view.cjs).
- Mất mạng hoặc server trả 500 khi chấm → giao diện trả về giá trị cũ, toast "Không lưu được" (mobile_tools.cjs `rate failure rollback`).
- Xoay máy dọc ↔ ngang khi đang Xem → giữ đúng ảnh đang xem (mobile_ipad.cjs `rotate keeps current`).

---

### Task 1: Backend nhẹ + `cull.js` dùng chung

**Files:**
- Modify: `app/photosift/server.py` (route `GET /api/photos/ver`; phục vụ `/cull.js` cùng danh sách file tĩnh như `/logo.png`, content-type `application/javascript`, qua kiểm tra bản quyền như trang)
- Modify: `app/photosift/library.py` (`photos_ver() -> {"ver": int}` = `self.db.con.total_changes` cộng số ảnh trong `cur`)
- Create: `app/photosift/web/cull.js`
- Modify: `app/photosift/web/index.html` (nạp `<script src="/cull.js">` trước script chính; `cand()` gọi `cullCandidates`)
- Test: `tests/test_photos_ver.py`, `tests/ui/cull_shared.cjs`

**Interfaces:**
- Produces: `GET /api/photos/ver → {"ver": int}`; `window.cullCandidates(photos, sel) -> photo[]` (photos có `rating`, `flags`; sel ⊆ `['blur','dark','bright','eyes','dup']`; trả ảnh `rating===0` có ít nhất một flag trong sel).

- [ ] **Step 1: Test hỏng.**
  - `tests/test_photos_ver.py`: `ver` tăng sau `set_rating`, không đổi khi gọi lại không có thay đổi. Dùng fixture `lib_with`.
  - `tests/ui/cull_shared.cjs`: nạp `cull.js` bằng `vm`, kiểm `cullCandidates` với 5 ảnh mẫu (rating khác 0 bị bỏ; flag không chọn bị bỏ).
- [ ] **Step 2: Chạy** `python3 -m pytest tests/test_photos_ver.py -q` và `node tests/ui/cull_shared.cjs` → FAIL.
- [ ] **Step 3: Cài** theo Interfaces. `index.html`: thay thân `cand()` bằng `cullCandidates(S.photos, sel)`, hành vi không đổi.
- [ ] **Step 4: Chạy** hai test trên, `python3 -m pytest tests -q`, và `for f in tests/ui/*.cjs; do node $f || exit 1; done` → pass. Các bài UI cũ nạp `index.html` qua route giả, nên phải thêm route `/cull.js` vào các bài đó (đọc file thật).
- [ ] **Step 5: Commit** `Điện thoại: route /api/photos/ver và cull.js dùng chung`

### Task 2: Khung trang + Lưới

**Files:**
- Modify (viết lại): `app/photosift/web/mobile.html`
- Test: `tests/ui/mobile_grid.cjs` (Playwright, viewport 390×844, `hasTouch:true`, API giả; ảnh nhỏ trả 1×1 PNG)

**Interfaces:**
- Consumes: Task 1 (`/api/photos/ver`, `/cull.js`).
- Produces (hàm thuần trong `mobile.html`, dạng `function tên(` đầu dòng):
  - `mFilter(photos, f, ctx) -> photo[]`. `f` ∈ `'all'|'todo'|'keep'|'rej'|'sugg'|'warn'|'hl'|'odd'|'p:<personId>'`. `ctx` = `{oddSet}`. `'warn'` = có flag ∈ blur/dark/bright/eyes/away.
  - `mGroup(list, on) -> tile[]`, `tile = {p, n, ids}`.
  - `mPeopleChips(people) -> [{id,name,n}]`.
  - `mSort(key, rev) -> cmp`. Các khoá như máy tính: `name|time|score|type`.
  - Trạng thái chung `M` = `{all, view, tiles, filter, cols, stack, cur}`. Hàm `mRender()` vẽ lại lưới.
  - Giữ màn hình chọn thư mục hiện có (☰ → `/api/catalog`, `/api/open`).

- [ ] **Step 1: Test hỏng** `mobile_grid.cjs`, gồm:
  - 30 ảnh giả, trong đó 1 loạt `grp`=5 (best id 3) → lưới gộp còn 26 ô, ô của loạt có `×5`.
  - Bấm chip "Đã loại" khi 2 ảnh của loạt bị -1 → chỉ còn ô ảnh đã loại, loạt hiện `×2`.
  - Ô có ✦ (`sugg`), chip đỏ "mờ" (flag `blur`), ★ (rating 2), ✕ (rating -1).
  - Chip người: 12 người, 3 có tên → chip đầu là 3 người có tên, tổng ≤ 10, có chip "Highlight".
  - Đổi 4 cột → còn sau khi tải lại trang.
  - Cuộn ảo hoá: 3.000 ảnh → số `.tile` trong DOM < 400.
  - `test_empty_states`: không ảnh / lọc rỗng → có thông báo, không `pageerror`.
  - Đồng bộ: `/api/photos/ver` đổi số → `/api/photos` được gọi lại đúng 1 lần, vị trí cuộn giữ nguyên.
- [ ] **Step 2: Chạy** `node tests/ui/mobile_grid.cjs` → FAIL.
- [ ] **Step 3: Cài.** Bố cục, nhãn và màu theo demo (artboard 1). Cuộn ảo theo hàng: chiều cao hàng cố định theo số cột và tỉ lệ 4:5.
- [ ] **Step 4: Chạy lại** → `ok`. Chụp `scratchpad/m-grid.png` (390×844) và tự xem.
- [ ] **Step 5: Commit** `Điện thoại: lưới quét nhanh, gộp loạt trùng, bộ lọc, đồng bộ`

### Task 3: Xem — soi nét, vuốt, dải loạt trùng

**Files:**
- Modify: `app/photosift/web/mobile.html`
- Test: `tests/ui/mobile_view.cjs`

**Interfaces:**
- Consumes: Task 2 (`M`, `mRender`, `mFilter`, `mGroup`).
- Produces:
  - `mZoom` = `{scale, tx, ty}`.
  - `function zoomAt(z, factor, cx, cy, vw, vh, iw, ih) -> z` (giữ điểm (cx,cy) đứng yên, kẹp trong 1–4×, không trượt ra ngoài ảnh).
  - `function focusZoom(focus, vw, vh, iw, ih, natW) -> z` (100% tại điểm nét).
  - `openView(id)`, `closeView()` (lưới cuộn tới ô vừa xem).
  - `pickInGroup(id) -> ops` (danh sách `{id, from, to}` cho hoàn tác ở Task 4).

- [ ] **Step 1: Test hỏng** `mobile_view.cjs`:
  - Chạm ô → mở Xem; `img.src` có `id=<id>`; sau `load`, `src` chuyển sang có `hq=1&s=`.
  - Test node cho `zoomAt` / `focusZoom`: kẹp 1–4×; điểm giữ cố định; mép ảnh không lộ nền.
  - Chạm đúp (2 tap cách 120ms) trên ảnh có `focus` → `M.zoom.scale` ≈ natW/iw và điểm nét ở giữa. `double tap without focus` → 2.5×.
  - Khi zoom > 1.5 → có request `s=0`.
  - Ở mức vừa màn hình, vuốt phải 200px → POST `/api/rate {ids:[id],rating:1}` và sang tấm sau. Khi zoom 2×, vuốt ngang không gọi `/api/rate`.
  - Chạm mép phải 1 lần → sang tấm sau sau ≥ 250ms; chạm đúp ở mép → không chuyển tấm.
  - Ảnh thuộc `grp` 5 tấm → dải 5 ảnh nhỏ. Chạm ảnh nhỏ thứ 3 khi đang zoom 2× → giữ `scale` 2.
  - "Chọn tấm này" → `/api/rate` cho tấm đó rating 1 và các tấm chưa chấm khác rating -1. Loạt chỉ 1 ảnh → không có dải.
  - Nút ◎ bật/tắt khung nét.
- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài** theo demo (artboard 2). Cử chỉ bằng Pointer Events; `touch-action: none` trên vùng ảnh.
- [ ] **Step 4: Chạy lại** → `ok`; chạy cả `mobile_grid.cjs`. Chụp `scratchpad/m-view.png`.
- [ ] **Step 5: Commit** `Điện thoại: xem từng tấm, phóng to soi nét, so loạt trùng`

### Task 4: Chọn nhiều, hoàn tác, bảng công cụ ⋯

**Files:**
- Modify: `app/photosift/web/mobile.html`
- Test: `tests/ui/mobile_tools.cjs`

**Interfaces:**
- Consumes: Task 1 `cullCandidates`; Task 3 `pickInGroup`; các route có sẵn `/api/rate`, `/api/cull/apply`, `/api/cull/undo`, `/api/suggest`, `/api/suggest/clear`, `/api/suggest/rate`, `/api/suggest/rate/undo`, `/api/taste`.
- Produces:
  - `function undoPush(entry)`, `function undoPop() -> Promise`.
  - Entry `{t:'rate', ops:[{id,from,to}]}` | `{t:'cull', batch, ids}` | `{t:'suggrate', batch, ids}`.

- [ ] **Step 1: Test hỏng** `mobile_tools.cjs`:
  - Chạm giữ 500ms một ô → chế độ chọn. Chạm thêm 2 ô → "Đã chọn 3 tấm". ★1 → một POST `/api/rate {ids:[3 id],rating:1}`.
  - Chọn một ô gộp ×4 → chọn cả 4 id.
  - Hoàn tác:
    - Sau khi chấm → toast có nút "Hoàn tác", bấm → POST trả rating cũ từng ảnh.
    - Nếu giữa chừng `/api/photos` báo 1 ảnh đã đổi → bỏ qua ảnh đó, toast chứa "bỏ qua 1 ảnh".
  - ⋯ → Tự động lọc, mức Vừa → dòng "Đánh dấu loại X / Y ảnh chưa chấm" với X = `cullCandidates(...)`. Bấm → `/api/cull/apply {ids}`; hoàn tác → `/api/cull/undo {batch}`.
  - ✦ Chọn ảnh đẹp: gõ `15%` → `/api/suggest {n: round(0.15·tổng)}`; lưới chuyển sang chip ✦; dòng "Đang dùng: …" theo `/api/taste`.
  - `rate failure rollback`: `/api/rate` trả 500 → sao trả lại như cũ, toast "Không lưu được".
- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài** theo demo (artboard 3–4). Bảng ⋯ trượt lên từ dưới, đóng bằng vuốt xuống hoặc chạm nền.
- [ ] **Step 4: Chạy** cả 4 file `mobile_*.cjs` → `ok`. Chụp `scratchpad/m-tools.png`.
- [ ] **Step 5: Commit** `Điện thoại: chọn nhiều, hoàn tác, Tự động lọc và Chọn ảnh đẹp`

### Task 5: iPad / màn rộng

**Files:**
- Modify: `app/photosift/web/mobile.html`
- Test: `tests/ui/mobile_ipad.cjs` (viewport 1180×820)

**Interfaces:**
- Consumes: Task 2–4.

- [ ] **Step 1: Test hỏng:**
  - Ở 1180×820: lưới và vùng Xem cùng hiện; lưới 5 cột; chạm ô → ảnh lớn đổi theo, lưới không bị ẩn.
  - Nút "Tự động lọc" và "✦ Chọn ảnh đẹp" có trên thanh trên.
  - `rotate keeps current`: đang Xem id X ở 390×844 → đổi viewport 844×390 rồi 1180×820 → vẫn là X.
  - Ở 390×844 vẫn là hai chế độ tách rời (chạy lại `mobile_view.cjs`).
- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài** bằng CSS `@media (min-width: 900px)` cộng một cờ JS `M.split` đọc từ `matchMedia`. Theo demo (artboard 5).
- [ ] **Step 4: Chạy** toàn bộ `tests/ui/*.cjs` và `python3 -m pytest tests -q` → pass. Chụp `scratchpad/m-ipad.png`.
- [ ] **Step 5: Commit** `Điện thoại: bố cục iPad chia đôi lưới và ảnh`
