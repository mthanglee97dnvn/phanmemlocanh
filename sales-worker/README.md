# Tự cấp bản quyền vĩnh viễn 100% tự động — Hướng dẫn cài đặt

Khi khách quét VietQR trả **500.000đ**, hệ thống tự cấp bản quyền vĩnh viễn, app của khách tự
tắt thông báo dùng thử — **bạn không phải làm gì bằng tay**.

## Luồng hoạt động (để bạn hiểu, không cần nhớ)

```
Khách quét QR trả 500.000đ  (nội dung CK đã có sẵn "MTCC<mã máy>")
        │
        ▼
Vietcombank  →  SePay  (đọc biến động số dư, gửi webhook)
        │
        ▼
Cloudflare Worker  (kiểm tra 500.000đ + mã máy → KÝ key vĩnh viễn)
        │
        ▼
GitHub grants.json  →  App của khách tự tải về mỗi 15 phút  →  tự kích hoạt vĩnh viễn
```

Mọi thứ trong app đã sẵn sàng. Bạn chỉ cần dựng **2 tài khoản miễn phí**: SePay và Cloudflare.
Ước tính **20–30 phút**, làm một lần dùng mãi.

---

## Bạn cần chuẩn bị 4 thông tin bí mật (secrets)

| Tên | Là gì | Lấy ở đâu |
|-----|-------|-----------|
| `SALES_SEED_HEX` | Khóa bí mật để ký key | **Mình gửi riêng cho bạn trong khung chat** |
| `SEPAY_APIKEY` | Mật khẩu để SePay gọi Worker | **Bạn tự đặt** (một chuỗi ngẫu nhiên bất kỳ) |
| `GH_TOKEN` | Token GitHub để ghi grants.json | Tạo ở Bước 2 |
| `GH_REPO` | Tên kho | Đã điền sẵn: `mthanglee97dnvn/phanmemlocanh` |

> ⚠️ **Tuyệt đối không** dán 4 thứ này vào file mã nguồn hay gửi cho ai. Chỉ dán vào ô "secret"
> của Cloudflare như hướng dẫn bên dưới.

---

## Bước 1 — Mở tài khoản SePay (miễn phí) và nối Vietcombank

1. Vào **https://sepay.vn** → **Đăng ký** (bằng email của bạn).
2. Vào mục **Ngân hàng → Thêm tài khoản → Vietcombank**, làm theo hướng dẫn của SePay để
   nối tài khoản **0041000316886 (LE MINH THANG)**. SePay chỉ **đọc** biến động số dư, không
   rút được tiền.
3. Chờ sang Bước 3 rồi mới cấu hình webhook (cần có địa chỉ Worker trước).

---

## Bước 2 — Tạo GitHub token để Worker ghi được grants.json

1. Đăng nhập GitHub bằng tài khoản **mthanglee97dnvn**.
2. Vào **https://github.com/settings/tokens?type=beta** → **Generate new token** (fine-grained).
3. Đặt:
   - **Token name**: `mtcc-sales`
   - **Expiration**: `No expiration` (hoặc 1 năm rồi gia hạn).
   - **Repository access** → **Only select repositories** → chọn **phanmemlocanh**.
   - **Permissions** → **Repository permissions** → **Contents** → chọn **Read and write**.
4. **Generate token** → **copy chuỗi token** (dạng `github_pat_...`). Đây là `GH_TOKEN`.
   Lưu tạm vào Ghi chú, lát nữa dán vào Cloudflare.

---

## Bước 3 — Dựng Cloudflare Worker

Cần máy có **Node.js**. Mở **Terminal** (hoặc PowerShell trên Windows) và chạy lần lượt:

```bash
# 1) Đăng nhập Cloudflare (miễn phí — nếu chưa có tài khoản, trang web sẽ cho đăng ký)
npx wrangler login

# 2) Vào thư mục Worker (trong kho đã tải về)
cd sales-worker

# 3) Dán 3 secret — mỗi lệnh sẽ hỏi và bạn dán giá trị vào:
npx wrangler secret put SALES_SEED_HEX      # dán chuỗi mình gửi riêng trong chat
npx wrangler secret put SEPAY_APIKEY        # tự đặt 1 chuỗi ngẫu nhiên, NHỚ LẠI để dùng ở Bước 4
npx wrangler secret put GH_TOKEN            # dán token github_pat_... ở Bước 2

# 4) Triển khai
npx wrangler deploy
```

Sau lệnh cuối, Cloudflare in ra **địa chỉ Worker**, dạng:

```
https://mtcc-sales.<tên-của-bạn>.workers.dev
```

**Copy địa chỉ này** — đây là URL webhook cho Bước 4.

> 💡 Mẹo tạo chuỗi ngẫu nhiên cho `SEPAY_APIKEY`: chạy
> `node -e "console.log(require('crypto').randomBytes(24).toString('hex'))"`
> rồi copy kết quả.

---

## Bước 4 — Nối SePay vào Worker

1. Vào SePay → **Cấu hình → Webhooks (Tích hợp Webhook) → Thêm Webhook**.
2. Điền:
   - **URL / Gọi đến**: dán **địa chỉ Worker** ở Bước 3.
   - **Kiểu xác thực / Authentication**: chọn **API Key** (hoặc "Apikey").
   - **API Key**: dán đúng chuỗi `SEPAY_APIKEY` bạn đã đặt ở Bước 3.
   - **Sự kiện**: chọn **Có tiền vào** (giao dịch ghi có / money in).
   - **Tài khoản**: chọn tài khoản Vietcombank đã nối.
3. **Lưu**.

Xong! Hệ thống đã chạy tự động.

---

## Bước 5 — Kiểm tra thật (khuyến nghị)

1. Mở app trên một máy, vào màn hình kích hoạt, **copy mã máy** (dạng `ABCD-EFGH-IJKLM`).
2. Tự chuyển khoản **500.000đ** (hoặc nhiều hơn) vào tài khoản, **nội dung ghi**: `MTCC` + mã máy
   viết liền không gạch, ví dụ mã `ABCD-EFGH-IJKLM` thì ghi `MTCCABCDEFGHIJKLM`.
   *(Nếu khách quét đúng mã VietQR trong app thì nội dung này đã được điền sẵn, khỏi lo.)*
3. Chờ tối đa vài phút: app sẽ **tự chuyển sang "Vĩnh viễn"** và tắt thông báo dùng thử.
4. Muốn chắc chắn Worker nhận được: vào Cloudflare → Worker `mtcc-sales` → tab **Logs** xem có
   dòng `ok: true`.

---

## Khi nào cần can thiệp tay?

Gần như không bao giờ. Nhưng nếu khách chuyển sai nội dung (thiếu mã máy), Worker sẽ bỏ qua.
Lúc đó bạn cấp tay bằng công cụ có sẵn trong kho:

```bash
python tools/cap_ban_quyen.py "ABCD-EFGH-IJKLM" "MTCC-...key..."
git add license/grants.json && git commit -m "cap tay" && git push
```

(Key cấp tay lấy từ app **MThanglee KeyGen** như trước giờ.)

---

## Chi phí

- SePay: gói miễn phí đủ dùng cho lượng giao dịch studio.
- Cloudflare Workers: miễn phí tới 100.000 lượt gọi/ngày — thừa sức.
- GitHub: miễn phí.

**Tổng: 0đ/tháng.**
