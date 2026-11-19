# Dùng thử tự động 3 ngày — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Máy chưa từng có key mở app → tự nhận key thử 3 ngày từ Worker bán hàng; hết hạn thì khoá hẳn.

**Architecture:** Worker Cloudflare thêm `POST /trial` (ký key thử cùng định dạng, nhớ mã máy trong KV `TRIALS`, chạy ở
tên miền `api.cullcollage.com`). App: `License.start_trial()` gọi Worker rồi kích hoạt như key dán tay; màn hình kích hoạt
tự gọi khi máy chưa có key; thanh trên ghi "Dùng thử · còn N ngày".

**Tech Stack:** Cloudflare Worker (JS, WebCrypto Ed25519, KV), Python (license.py, server.py), HTML/JS thuần, pytest,
Node test (`node --test`), Playwright.

**Spec:** docs/superpowers/specs/2026-11-19-dung-thu-3-ngay-design.md

## Global Constraints

- Key thử: định dạng key hiện có; byte serial `body[1] = 0x54`; `issued = day`; `exp = day + 2`; gắn mã máy.
- `day` của app chỉ được nhận khi `|day - ngày UTC của Worker| <= 1`, ngược lại dùng ngày UTC.
- Mỗi mã máy một key thử: gọi lại → trả đúng key đã cấp, không cấp mới.
- Địa chỉ Worker trong app: `TRIAL_URL = "https://api.cullcollage.com/trial"`; thời gian chờ 10 giây.
- Câu chữ cố định:
  - mất mạng: "Cần kết nối mạng để bắt đầu dùng thử 3 ngày"
  - hết hạn key thử: "Đã hết 3 ngày dùng thử — mua bản quyền vĩnh viễn 500.000đ để dùng tiếp"
  - nút trên thanh trên khi đang thử: "Dùng thử · còn N ngày"
- Máy đã có file key (bất kỳ trạng thái) → không bao giờ tự xin thử.
- Commit giữ tác giả MThanglee + 2 dòng trailer.

## Review Focus

- Worker lỗi/chưa triển khai (404, 500, HTML trả về thay vì JSON) → app hiện câu mất mạng + vẫn dán key được, không màn trắng (test Task 2).
- Key thử Worker trả về bị sửa/giả (chữ ký sai, sai máy) → không kích hoạt (test Task 2).
- Bấm "Thử lại" nhiều lần / tải lại trang khi đang xin → không ghi đè key đã có (test Task 2: start_trial khi đã có key trả lỗi, không gọi mạng).
- Key thử đã hết hạn còn trong máy → màn hình hiện câu hết hạn dùng thử, không tự xin lại (test Task 3).
- `day` khách gửi lệch xa (đồng hồ sai) → Worker dùng ngày UTC (test Task 1).

---

### Task 1: Worker `POST /trial`

**Files:**
- Modify: `sales-worker/worker.js` (tách `signKey(seedHex, machine8, {serial, issued, exp})`, thêm nhánh `/trial`)
- Modify: `sales-worker/wrangler.toml` (KV `TRIALS`, custom domain `api.cullcollage.com`)
- Modify: `sales-worker/README.md` (mục "Bật dùng thử 3 ngày")
- Test: `tests/worker/trial.test.mjs`

**Interfaces:**
- Produces: `POST /trial` JSON `{machine, day}` → 200 `{ok:true, key, again:boolean}`; mã máy sai → 400 `{ok:false}`.
  Không cần header Authorization. Webhook SePay cũ (POST `/` có Authorization) giữ nguyên.

- [ ] **Step 1: Write the failing test** `tests/worker/trial.test.mjs` (nạp worker bằng bản sao `.mjs`, env giả: `SALES_SEED_HEX` 32 byte cố định, `TRIALS` = Map bọc `get/put`):
  - cấp mới: body key giải ra `body[0]=1, body[1]=0x54, issued=day, exp=day+2`, 8 byte máy đúng, chữ ký Ed25519 hợp lệ với khoá công khai sinh từ seed; `again=false`.
  - gọi lại cùng máy (khác `day`) → cùng key, `again=true`.
  - `day` lệch ngày UTC 5 → `issued` = ngày UTC.
  - mã máy `"ABC"` → 400.
  - POST `/` không Authorization vẫn 401 (không phá webhook).
- [ ] **Step 2: Run** `node --test tests/worker/` → Expected: FAIL (route chưa có).
- [ ] **Step 3: Implement** nhánh `/trial` trước bước xác thực SePay; KV key = mã máy dạng có gạch.
- [ ] **Step 4: Run** `node --test tests/worker/` → Expected: pass.
- [ ] **Step 5: Commit** "Worker: cấp key dùng thử 3 ngày (mỗi máy một lần, nhớ trong KV)".

### Task 2: App xin key thử

**Files:**
- Modify: `app/photosift/license.py` (`TRIAL_URL`, `parse` trả thêm `trial`, `License.has_key()`, `License.start_trial()`)
- Modify: `app/photosift/server.py` (`POST /api/license/trial` cho phép khi chưa có key)
- Test: `tests/test_trial.py`

**Interfaces:**
- Produces:
  - `parse(text)["trial"]: bool` (serial 0x54).
  - `License.has_key() -> bool` — file license có `key`.
  - `License.start_trial(timeout=10) -> dict` — đã có key → `dict(ok=False, reason="Máy này đã có key.")` không gọi mạng;
    lỗi mạng / Worker trả không phải JSON `{ok:true,key}` → `dict(ok=False, reason="Cần kết nối mạng để bắt đầu dùng thử 3 ngày", offline=True)`;
    key nhận về → `self.activate(key)` (kiểm chữ ký + đúng máy như key dán tay) và trả kết quả đó.
  - Gửi `{"machine": machine_code(), "day": today_num()}` qua `net.urlopen`.
- `info()` giữ nguyên trường cũ, thêm `has_key` và `trial`.

- [ ] **Step 1: Write the failing tests** (`cryptography` ký key thử bằng khoá tạm; monkeypatch `license.SALES_PUB_HEX`, `license.HOME/FILE` → tmp, `machine_bytes`, và `net.urlopen`):
  `test_trial_activates`, `test_trial_flag_and_days_left` (days_left == 2 ngày cấp), `test_offline_message`,
  `test_worker_html_or_404_is_offline`, `test_bad_signature_rejected`, `test_has_key_never_calls_network`,
  `test_expired_trial_reason` (key thử exp < hôm nay → `reason` = câu hết hạn dùng thử, `expired=True`).
- [ ] **Step 2: Run** `python -m pytest tests/test_trial.py -q` → FAIL.
- [ ] **Step 3: Implement**; hết hạn mà `trial` → đổi `reason` thành câu hết hạn dùng thử.
- [ ] **Step 4: Run** `python -m pytest -q` → pass.
- [ ] **Step 5: Commit** "Bản quyền: tự xin key dùng thử 3 ngày khi máy chưa có key".

### Task 3: Giao diện

**Files:**
- Modify: `app/photosift/web/activate.html`, `app/photosift/web/shell.html`
- Test: `tests/ui/trial_ui.cjs`

**Interfaces:**
- activate.html: `load()` thấy `!s.ok && !s.has_key` → hiện "Đang mở dùng thử 3 ngày…", POST `/api/license/trial`; ok → `location.href='/'`;
  không ok → hiện `reason` + nút `#trialRetry` "Thử lại". Có key (hết hạn…) → không gọi.
- shell.html: `s.trial` → nút ghi `Dùng thử · còn ${s.days_left} ngày`.

- [ ] **Step 1: Write the failing UI test**: (a) `/api/license` → `{ok:false,has_key:false}`, `/api/license/trial` → `{ok:true}` → trang chuyển về `/`; (b) trial trả `{ok:false,reason:'Cần kết nối mạng để bắt đầu dùng thử 3 ngày'}` → `#err` chứa câu đó, `#trialRetry` hiện, bấm → gọi lại; (c) `{ok:false,has_key:true,expired:true,reason:'Đã hết 3 ngày dùng thử — …'}` → không gọi `/api/license/trial`; (d) shell với `{ok:true,trial:true,days_left:2}` → `#tLic .t` = "Dùng thử · còn 2 ngày".
- [ ] **Step 2: Run** `node tests/ui/trial_ui.cjs` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** all UI tests + pytest + node --test → pass.
- [ ] **Step 5: Commit** "Giao diện: tự mở dùng thử 3 ngày, nút Thử lại, nhãn Dùng thử · còn N ngày".
