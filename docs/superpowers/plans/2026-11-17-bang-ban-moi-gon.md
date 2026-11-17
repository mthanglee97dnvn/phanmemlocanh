# Bảng "Có bản mới…" gọn — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bảng cập nhật hiện vài dòng nổi bật của mọi bản khách còn thiếu, thay cho khối ghi chú dài bị cắt.

**Architecture:** `update.py` thêm hàm thuần `_changes(rels, cur, latest)` làm gọn và gom ghi chú; `check()` trả thêm `changes`. `shell.html` dựng danh sách bằng DOM/`textContent`. `WHATSNEW.txt` đổi sang chỉ chứa dòng nổi bật của bản kế.

**Tech Stack:** Python stdlib, pytest; JS thuần trong `app/photosift/web/shell.html`.

**Spec:** `docs/superpowers/specs/2026-11-17-bang-ban-moi-gon-design.md`

## Global Constraints
- Mỗi bản tối đa 4 dòng; tối đa 6 bản, phần thừa thành dòng `…và N bản trước nữa`.
- Dòng chung (mở đầu "Sửa lỗi" hoặc "Cải thiện", sau khi bỏ biểu tượng) gộp thành **một** dòng cuối `Sửa lỗi và chạy ổn định hơn.`; bản chỉ có dòng chung không có tiêu đề riêng.
- Bỏ: comment HTML, dòng trống, dòng mở đầu `•`, dòng mở đầu "Cảm ơn", dòng mở đầu "©".
- Giữ: dòng mà ký tự đầu không phải chữ/số (biểu tượng), hoặc dòng chung.
- Không chèn HTML từ GitHub vào DOM; giữ trường `notes`.
- Không đổi luồng tải/cài.

## Review Focus
- Ghi chú có `\r\n` (soạn trên Windows) → vẫn tách dòng đúng, không dư `\r`.
- Bản cũ 1.2/1.2.1/1.2.2 (body = WHATSNEW dài hiện tại) → mỗi bản đúng 4 dòng tiêu đề đầu, không lọt dòng "•", "Cảm ơn", "©".
- Tag có/không có `v`, và so số kiểu `1.2.10 > 1.2.9` → dùng `_key` sẵn có.
- Bản nháp/prerelease đã bị lọc ở `check()` — `_changes` chỉ nhận danh sách đã lọc.
- Khách đang ở bản mới nhất → `changes` rỗng, bảng vẫn "Bạn đang dùng bản mới nhất."

---

### Task 1: `_changes` trong update.py

**Files:**
- Modify: `app/photosift/update.py` (hàm mới cạnh `_key`; `check()` thêm `changes=` vào `out`)
- Create: `tests/test_update_changes.py`

**Interfaces:**
- Produces: `_changes(rels: list[dict], cur: str, latest: str) -> list[dict]` — mỗi phần tử `{"ver": "1.2.3", "lines": [str,...]}`, bản mới nhất trước; phần tử cuối có thể là `{"ver": "", "lines": ["…và N bản trước nữa"]}` và/hoặc `{"ver": "", "lines": ["Sửa lỗi và chạy ổn định hơn."]}` (thứ tự: "…và N bản" rồi đến dòng sửa lỗi).
- `check()` trả `changes` (list rỗng khi không có bản mới).

- [ ] **Step 1: Viết test hỏng** (dùng `WHATSNEW.txt` hiện tại của repo làm body bản cũ):
```python
from app.photosift.update import _changes
OLD = open("WHATSNEW.txt", encoding="utf-8").read() + "\n<!-- src:abc -->"
R = lambda t, b: {"tag_name": t, "body": b}

def test_old_long_body_trimmed_to_4_titles():
    c = _changes([R("v1.2", OLD)], "1.1.100", "1.2")
    assert c[0]["ver"] == "1.2" and len(c[0]["lines"]) == 4
    assert c[0]["lines"][0].startswith("🖼️")
    assert not any(l.startswith(("•", "Cảm ơn", "©", "<!--")) for x in c for l in x["lines"])

def test_only_newer_than_cur_newest_first_and_fixes_merged():
    rels = [R("v1.2.1", "🍎 Sửa nhập ảnh Mac\r\nSửa lỗi và chạy ổn định hơn."), R("v1.2.2", "Sửa lỗi và chạy ổn định hơn."),
            R("v1.2.3", "🗂 Đếm cặp RAW–JPEG"), R("v1.2", OLD)]
    c = _changes(rels, "1.2", "1.2.3")
    assert [x["ver"] for x in c] == ["1.2.3", "1.2.1", ""]
    assert c[1]["lines"] == ["🍎 Sửa nhập ảnh Mac"]
    assert c[-1]["lines"] == ["Sửa lỗi và chạy ổn định hơn."]

def test_cap_six_versions():
    rels = [R(f"v1.3.{i}", f"✨ Tính năng {i}") for i in range(1, 9)]
    c = _changes(rels, "1.2", "1.3.8")
    assert len([x for x in c if x["ver"]]) == 6 and c[-1]["lines"] == ["…và 2 bản trước nữa"]

def test_up_to_date_is_empty():
    assert _changes([R("v1.2.2", "✨ x")], "1.2.2", "1.2.2") == []
```
- [ ] **Step 2: Chạy** `python -m pytest tests/test_update_changes.py -q` → FAIL (ImportError `_changes`). Nếu import gói `app.photosift` lỗi do thiếu `__init__`/đường dẫn, thêm `tests/conftest.py` chèn repo root vào `sys.path`.
- [ ] **Step 3: Cài `_changes`** theo Global Constraints; lọc `_key(cur) < _key(tag) <= _key(latest)`, sắp giảm dần theo `_key`; "biểu tượng" = `not line[0].isalnum()`; dòng chung nhận diện sau khi bỏ biểu tượng và khoảng trắng đầu.
- [ ] **Step 4: Chạy** → 4 passed.
- [ ] **Step 5: Nối `check()`**: `out = dict(base, ..., changes=_changes(rels, cur, tag or cur))`; thêm `"changes"` vào bộ khoá trả về ở dòng lọc `k in (...)` (khoảng dòng 102); `base` có `changes=[]`.
- [ ] **Step 6: Commit** `Cập nhật: gom ghi chú gọn của mọi bản mới hơn máy khách`

### Task 2: Hiển thị trong shell.html + WHATSNEW mới

**Files:**
- Modify: `app/photosift/web/shell.html` (`#uNotes` CSS dòng ~39, `showU` dòng ~179)
- Modify: `WHATSNEW.txt`

**Interfaces:**
- Consumes: `r.changes` từ Task 1.

- [ ] **Step 1: `showU`**: khi `av && r.changes?.length`, xoá `#uNotes`, với mỗi phần tử: nếu `ver` thì thêm `div.uv` text `Bản ${ver}`; mỗi dòng thêm `div.ul` bằng `textContent`. Không có `changes` thì giữ hành vi cũ (`r.notes`). CSS: `#uNotes .uv{font-size:11px;color:#8ea3b8;margin:8px 0 2px}` (`.uv:first-child{margin-top:0}`), `#uNotes .ul{margin:1px 0}`; giữ `max-height:220px;overflow:auto`, bỏ `white-space:pre-wrap` khi dựng danh sách.
- [ ] **Step 2: Kiểm tra bằng Playwright**: mở `shell.html` với `/api/update/check` giả trả `changes` của test thứ hai; chụp bảng; xác nhận 2 tiêu đề `Bản 1.2.3`, `Bản 1.2.1` và dòng sửa lỗi cuối, không có chữ HTML thô.
- [ ] **Step 3: Đổi `WHATSNEW.txt`** thành đúng dòng nổi bật bản kế (1.2.3), soạn theo những gì thật sự gộp vào bản đó lúc phát hành; nếu nhánh này lên trước các tính năng khác thì tạm để `Sửa lỗi và chạy ổn định hơn.` Không còn dòng "Cảm ơn"/"©".
- [ ] **Step 4: Chạy lại** `python -m pytest tests -q` → pass.
- [ ] **Step 5: Commit** `Bảng cập nhật: hiện dòng nổi bật theo từng bản, gọn và không bị cắt`
