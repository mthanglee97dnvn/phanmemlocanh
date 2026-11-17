# Đếm cặp RAW–JPEG & sắp theo loại file — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thanh công cụ báo ngay RAW/JPEG có khớp cặp không, lọc ra file lẻ; thêm sắp xếp "Loại file" và nút Đảo.

**Architecture:** Toàn bộ ở client (`index.html`) trên `S.photos`, ghép cặp bằng đúng khoá của `pairHidden` (dir + stem thường). Backend chỉ thêm trường `cam` vào `photos()` cho tooltip theo máy.

**Tech Stack:** Python (library.py), JS thuần trong `app/photosift/web/index.html`, test bằng node (`.cjs`) + pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-dem-cap-raw-jpeg-design.md`

## Global Constraints
- Ghép cặp: cùng `p.dir`, cùng tên bỏ đuôi (không phân biệt hoa thường), một bên khớp `RAWRE`, một bên không.
- Ô đếm dạng `RAW 1.240 · JPEG 1.238 · 2 lẻ` (số định dạng `vi-VN`); xanh khi 0 lẻ, cam khi có lẻ; ẩn khi số RAW = 0 hoặc số JPEG = 0.
- Đếm trên toàn bộ `S.photos`, không phụ thuộc bộ lọc / ô tìm / ô RAW+JPEG.
- Lựa chọn Đảo nhớ bằng `lsGet/lsSet('ps.sortRev')`.
- Không thêm Arrangement, ISO, ống kính, serial; không sửa/xoá file.

## Review Focus
- Tên có nhiều dấu chấm (`IMG.0001.ARW` / `IMG.0001.JPG`) → vẫn là một cặp (chỉ bỏ đuôi cuối).
- Cùng tên ở hai thư mục khác nhau → không ghép chéo; mỗi file lẻ trong thư mục của nó.
- Hoa/thường lệch (`a.arw` + `A.JPG`) → một cặp.
- Đang bật bộ lọc "File lẻ cặp" mà anh đánh dấu/xoá hết file lẻ (0 lẻ) → không kẹt ở danh sách rỗng mà ô đếm hiện xanh và bấm được để về bộ lọc cũ.
- `.heic`/`.png`/`.tif` tính phía JPEG (mọi ảnh không RAW) — đúng như `pairHidden`.

---

### Task 1: Đếm cặp, ô đếm, bộ lọc "File lẻ cặp"

**Files:**
- Modify: `app/photosift/library.py` (hàm `photos()`, cả hai nhánh `out.append(dict(...))`: thêm `cam=(r["cam"] if "cam" in r.keys() else None)`)
- Modify: `app/photosift/web/index.html` (CSS thanh công cụ; HTML cạnh `#fPair`; `FILTERS`; `matchFilter`; `applyView`; chỗ gọi `applyView` sau `loadPhotos`)
- Test: `tests/ui/pair_stats.cjs`

**Interfaces:**
- Produces: `function pairStats(list) -> {raw:number, jpg:number, odd:Set<id>, byCam:Map<string,number>}` (top-level trong `index.html`, viết dạng `function pairStats(list){` ở đầu dòng và kết thúc bằng dòng `}` riêng, để test trích được). `byCam` key = `p.cam||'Chưa dò máy'`, value = số file lẻ.
- Produces: bộ lọc mới `'odd'` nhãn `'⇄ File lẻ cặp (RAW/JPEG)'`; `matchFilter` trả `S.oddSet.has(p.id)`.
- Produces: `S.oddSet` (cập nhật mỗi lần `applyView`), `S.prevFilter`.

- [ ] **Step 1: Viết test hỏng** `tests/ui/pair_stats.cjs`: đọc `index.html`, trích `function pairStats` … `\n}` bằng regex, trích luôn dòng `const RAWRE=`, `eval`, rồi `assert`:
```js
const P=(id,dir,name,cam)=>({id,dir,name,cam});
let r=pairStats([P(1,'a','X1.ARW','A'),P(2,'a','x1.jpg','A'),P(3,'a','X2.ARW','A'),P(4,'b','X2.JPG','B'),P(5,'a','I.0001.CR3'),P(6,'a','I.0001.JPG')]);
assert.equal(r.raw,3); assert.equal(r.jpg,3);
assert.deepEqual([...r.odd].sort(),[3,4]);
assert.equal(r.byCam.get('A'),1); assert.equal(r.byCam.get('B'),1);
r=pairStats([P(1,'a','A.JPG'),P(2,'a','B.JPG')]); assert.equal(r.raw,0); assert.equal(r.odd.size,0);
```
(Bộ chỉ JPEG: `odd` rỗng — không coi là lẻ.)

- [ ] **Step 2: Chạy** `node tests/ui/pair_stats.cjs` → FAIL (không tìm thấy `pairStats`).

- [ ] **Step 3: Cài `pairStats`** như Interfaces; khi `raw===0||jpg===0` trả `odd` rỗng.

- [ ] **Step 4: Chạy lại** → in `ok`, exit 0.

- [ ] **Step 5: Nối giao diện**
  - `<button id="pairCnt" class="paircnt" hidden>` ngay sau `#fPair`.
  - Trong `applyView` (trước khi lọc): `const ps=pairStats(S.photos); S.oddSet=ps.odd;` rồi cập nhật nút: ẩn khi `raw===0||jpg===0`; text `RAW ${n(raw)} · JPEG ${n(jpg)} · ${odd.size} lẻ` (hoặc `· đủ cặp` khi 0); class `ok`/`warn`; `title` = các dòng `cam: k lẻ` từ `byCam`, cộng dòng "Bấm để lọc ra file lẻ cặp".
  - Bấm nút: nếu `S.filter!=='odd'` thì `S.prevFilter=S.filter; S.filter='odd'`; ngược lại `S.filter=S.prevFilter||'all'`; đồng bộ `#fFilter.value`, gọi `applyView()`.
  - Khi `S.filter==='odd'`, `cmp` dùng: `(a.cam||'').localeCompare(b.cam||'')||(a.taken||0)-(b.taken||0)||a.name.localeCompare(b.name)`.
  - Khi đang `odd` mà `S.oddSet.size===0`: tự về `S.prevFilter||'all'` và toast "Đã đủ cặp RAW–JPEG".
- [ ] **Step 6: Kiểm tra tay bằng Playwright** với thư mục mẫu 4 ARW + 3 JPG (scratchpad): ô đếm hiện `RAW 4 · JPEG 3 · 1 lẻ` màu cam; bấm → lưới còn 1 ảnh; bấm lại → về "Tất cả". Chụp màn hình.
- [ ] **Step 7: Commit** `Đếm cặp RAW–JPEG trên thanh công cụ, lọc ra file lẻ cặp`

### Task 2: Sắp xếp "Loại file" và nút Đảo

**Files:**
- Modify: `app/photosift/web/index.html` (`#fSort` options, `applyView` cmp, nút mới sau `#fSort`, CSS)
- Test: `tests/ui/pair_stats.cjs` (thêm phần sort)

**Interfaces:**
- Consumes: `RAWRE`.
- Produces: `function sortCmp(key, rev) -> (a,b)=>number` top-level (trích được như Task 1) thay cho object `cmp` trong `applyView`; khoá mới `'type'`.

- [ ] **Step 1: Thêm test hỏng**:
```js
const L=[P(1,'a','B.JPG'),P(2,'a','A.ARW'),P(3,'a','C.ARW')]; L[0].taken=1;L[1].taken=3;L[2].taken=2;
assert.deepEqual([...L].sort(sortCmp('type',false)).map(p=>p.id),[3,2,1]);
assert.deepEqual([...L].sort(sortCmp('type',true)).map(p=>p.id),[1,2,3]);
assert.deepEqual([...L].sort(sortCmp('time',true)).map(p=>p.id),[2,3,1]);
```
- [ ] **Step 2: Chạy** → FAIL (`sortCmp` chưa có).
- [ ] **Step 3: Cài `sortCmp`**: chuyển các comparator hiện có vào; `type` = RAW trước, rồi `taken`, rồi tên (numeric); `rev` đảo dấu toàn bộ kết quả. `applyView` dùng `sortCmp(S.filter==='odd'?'oddcam':S.sort, S.rev)` (đưa comparator của Task 1 vào khoá `oddcam`, không đảo khi `odd`… vẫn theo `S.rev` cho nhất quán).
- [ ] **Step 4: Chạy** → `ok`.
- [ ] **Step 5: Giao diện**: `<option value="type">Loại file (RAW trước)</option>`; `<label class="rev" title="Đảo chiều sắp xếp"><input type="checkbox" id="fRev"> Đảo</label>` sau `#fSort`; `S.rev=lsGet('ps.sortRev','0')==='1'`; onchange lưu `lsSet` + `applyView()`. Kiểm tra thanh công cụ không tràn ở ngưỡng `@container bar (max-width:1200px)` (ẩn chữ "Đảo", giữ ô tick, như `.lbl`).
- [ ] **Step 6: Playwright**: chọn "Loại file", tick Đảo → JPEG lên trước; tải lại trang → ô Đảo vẫn tick.
- [ ] **Step 7: Commit** `Sắp xếp theo loại file và nút Đảo chiều`
