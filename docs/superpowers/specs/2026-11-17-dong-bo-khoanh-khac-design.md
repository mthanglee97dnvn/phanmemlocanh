# Đồng bộ giờ nhiều máy bằng khoảnh khắc chung — thiết kế ngắn

## Vì sao
Ekip thường tự chỉnh giờ trên máy nên không chụp đồng hồ đầu buổi, nhưng giờ máy thỉnh thoảng vẫn lệch
(vài giây, có khi cả phút, giờ hay ngày). Trộn ảnh cả ekip thì sai thứ tự. Lúc phát hiện thì buổi cưới đã xong,
nên mốc phải là thứ ảnh nào cũng có sẵn: **một khoảnh khắc hai máy cùng chụp** (trao nhẫn, hôn, nâng ly…).

## Mục tiêu
- Chọn 1 tấm của máy mốc + 1 tấm cùng khoảnh khắc của máy cần chỉnh → app tính lệch, áp cho cả máy cần chỉnh.
- Chính xác tới từng giây (lật từng tấm trong loạt chụp liên tiếp), nhưng lệch cả giờ/ngày vẫn tìm được nhanh.
- Làm được mà không cần bấm "Dò các máy" trước.

## Không làm
- Đọc giờ tự động trên ảnh đồng hồ (OCR); độ chính xác dưới 1 giây (EXIF chỉ có giây).
- Sửa file ảnh gốc.

## Phải tránh
- Áp nhầm độ lệch mà không thấy: luôn hiện trước "Lệch +7 giây · áp cho 640 ảnh của máy …", và "Bỏ đồng bộ" đưa về giờ gốc.

## Ràng buộc
Chạy offline, Windows + macOS, cùng giao diện tối của app; giữ cách lưu không phá huỷ (cột toff) và ghi giờ đã chỉnh vào .xmp.

## Các cách đã cân nhắc
- **A. Ghép cặp khoảnh khắc, xem hai ảnh cạnh nhau** — chính xác tới giây, không cần đồng hồ; tốn công giao diện nhất. **Anh chọn.**
- B. Chỉnh ± ngày/giờ/phút/giây kèm dải ảnh trộn để nhìn — nhanh làm, nhưng khớp từng giây phải đoán bằng mắt.
- Chụp đồng hồ (kiểu Photo Mechanic) — đã làm, nhưng không hợp thói quen ekip → giữ làm tùy chọn phụ.

## Thiết kế (A)
```
Máy mốc [SONY 7RM3 ▾]                    Máy cần chỉnh [SONY 7M4 ▾]
[ ảnh lớn ]                              [ ảnh lớn ]
‹ NNB0612 · 15:02:31 ›                   ‹ DSC4410 · 15:02:24 ›
                                         ◀━━━ kéo nhanh theo giờ ━━━▶
Lệch: +7 giây (máy chạy chậm) · ± [0] ngày [0] giờ [0] phút [7] giây
                                [Hai tấm này cùng lúc → áp cho 640 ảnh]
```
- Mở từ nút trong hộp "Đồng bộ máy". Máy mốc mặc định = máy nhiều ảnh nhất (đổi được). Bên trái bắt đầu ở ảnh đang chọn nếu thuộc máy mốc.
- Chọn máy cần chỉnh → bên phải **tự nhảy tới tấm gần khoảnh khắc nhất** theo độ lệch ước lượng (dùng bộ dò tự động cho cặp máy này; nếu đã có lệch thì dùng lệch đó).
- Lật từng tấm: ← → cho bên phải (bên hay chỉnh), Shift + ← → cho bên trái; thanh kéo nhanh để tìm khi ước lượng sai. Bấm ảnh để phóng to.
- Độ lệch = giờ hiệu dụng của tấm mốc (giờ gốc + lệch đang có của máy mốc) − giờ gốc tấm bên phải. Đổi ô ± thì bên phải nhảy theo.
- "Hai tấm này cùng lúc" → ghi lệch cho cả máy cần chỉnh, tải lại lưới ảnh, giữ màn hình để chỉnh tiếp máy khác.
- Cách chụp đồng hồ thành một nút phụ trong cùng hộp "Đồng bộ máy".

## Để người làm tự quyết
Bố cục chi tiết, cỡ ảnh, cách vẽ thanh kéo, xử lý máy chỉ có vài ảnh, kiểm thử.
