# Dùng thử tự động 3 ngày

## Vì sao
Mục tiêu của app là bán được nhiều bản quyền hơn. Hiện cài xong là gặp ngay màn hình nhập key; muốn thử phải nhắn
anh Thắng xin key có hạn (cấp tay). Anh muốn: cài xong dùng thử đủ chức năng 3 ngày, không phải xin; sang ngày
thứ 4 không mua thì **khoá hẳn** (chỉ còn màn hình mua). Thanh toán đã tự động (VietQR → SePay → Worker ký key
vĩnh viễn → app tự kích hoạt), nên từ lúc tải tới lúc trả tiền không cần anh làm gì.

## Cách làm (anh đã chọn: Cách 1 — máy chủ cấp key thử)
Đã cân nhắc: (2) tự tính 3 ngày trên máy khách — xoá cấu hình/cài lại là thêm 3 ngày mãi; (3) lai, mất mạng thì
tự tính — tắt mạng lúc mở lần đầu là lách được. Cả hai làm "khoá hẳn ngày thứ 4" mất tác dụng.

- **Worker bán hàng** (`sales-worker/worker.js`) thêm `POST /trial` body `{"machine":"XXXX-XXXX-XXXXX","day":<số ngày theo giờ máy khách>}`
  - Mã máy sai định dạng → 400.
  - Máy đã có trong danh sách đã thử → trả lại đúng key thử đã cấp lần trước (cài lại trong 3 ngày vẫn dùng tiếp,
    hết hạn thì app báo hết hạn); không cấp key mới.
  - Chưa có → ký key cùng định dạng hiện có (ed25519, khoá bán hàng), gắn mã máy, `issued = day`,
    `exp = day + 2` (dùng hôm nay + 2 ngày nữa = 3 ngày; sang ngày thứ 4 hết hạn), byte serial = 0x54 ('T') để đánh
    dấu key thử; lưu vào Cloudflare KV `TRIALS` (mã máy → key) rồi trả `{ok:true,key}`.
  - `day` do app gửi, chỉ nhận khi lệch ngày UTC của Worker ≤ 1 (giờ Việt Nam lệch UTC 7 tiếng); ngoài khoảng → dùng ngày UTC.
- **App**:
  - Máy chưa có key nào (chưa từng kích hoạt) mở app → màn hình kích hoạt tự gọi `/api/license/trial`; server app gọi
    Worker, nhận key → kích hoạt như key dán tay → vào app ngay.
  - Không có mạng → "Cần kết nối mạng để bắt đầu dùng thử 3 ngày" + nút "Thử lại"; vẫn còn ô dán key và mua như cũ.
  - Máy đã có key (vĩnh viễn, có hạn, hoặc key thử cấp tay đã hết hạn) → không tự xin thử; giữ nguyên hành vi hiện tại.
  - Đang dùng thử: nút bản quyền trên thanh trên ghi "Dùng thử · còn N ngày" (key thử) thay cho "Còn N ngày".
  - Hết hạn key thử → màn hình kích hoạt ghi "Đã hết 3 ngày dùng thử — mua bản quyền vĩnh viễn 500.000đ để dùng tiếp",
    kèm QR thanh toán như hiện có. Chống vặn lùi đồng hồ dùng lại cơ chế `seen` sẵn có.
- **Triển khai Worker**: anh tạo KV một lần (`npx wrangler kv namespace create TRIALS`), dán id vào `wrangler.toml`,
  rồi `npx wrangler deploy`. README thêm mục hướng dẫn. Trước khi Worker mới chạy, app mới vẫn hoạt động như cũ
  (gọi thử lỗi → hiện thông báo mạng + dán key).

## Không làm
- Không giới hạn chức năng trong 3 ngày; không có chế độ "nửa khoá" sau hạn.
- Không đổi giá, không đổi luồng thanh toán.
- Không sửa website (có thể thêm dòng "Dùng thử miễn phí 3 ngày" sau khi Worker đã chạy).

## Điều cấm
- Xoá cấu hình / cài lại / vặn đồng hồ mà được thêm ngày thử.
- Khách đang có key (nhất là vĩnh viễn) bị đổi trạng thái.
- App treo ở màn hình trắng khi Worker lỗi hoặc mất mạng.

## Để người làm tự quyết
Thời gian chờ gọi Worker (gợi ý 10 giây), cách hiện trạng thái đang xin thử, tên hàm.

## Bổ sung 19/11: key thử gắn mã phần cứng (anh Thắng: "anh muốn chặn luôn")
Trên Windows, mã máy lấy từ MachineGuid trong Registry — admin sửa được trong 30 giây để ra mã máy mới và xin thử lại.
Key **dùng thử** (serial 0x54) giờ gắn **mã phần cứng** thay cho mã máy:
- Windows: SMBIOS UUID (`HKLM\SYSTEM\HardwareConfig\LastConfig`, Windows tự ghi lại theo bo mạch mỗi lần khởi động)
  + số serial ổ hệ thống; Mac: IOPlatformUUID + IOPlatformSerialNumber; không đọc được → dùng mã máy như cũ.
- App gửi `hw` (mã 13 ký tự như mã máy) lên `/trial`; Worker bắt buộc có `hw`, nhớ trong KV theo `hw`, ký key với 8 byte
  `hw`. Gửi `hw` giả bằng tay chỉ ra key gắn phần cứng khác → không chạy trên máy đó.
- Key trả tiền / key cấp tay vẫn gắn mã máy như cũ (không đổi gì cho khách đang dùng).
- Còn lại: cài lại Windows + format ổ hệ thống mới ra lượt mới (đổi serial ổ) — tốn công hơn nhiều, chấp nhận.
