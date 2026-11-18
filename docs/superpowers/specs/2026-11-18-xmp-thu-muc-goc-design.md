# Ghi .xmp vào thư mục ảnh gốc — chuyển kết quả lọc giữa hai máy

## Vì sao
Anh Thắng nhờ người khác lọc hoàn thiện trên máy A; tối về anh mở máy B, tìm tới đúng thư mục ảnh gốc
(trên NAS hoặc thư mục chia sẻ LAN), mở trong Cull & Collage để xuất ảnh đã chọn đem đi chỉnh. Máy B phải
thấy ngay những tấm máy A đã chọn — giống Photo Mechanic nhờ file .xmp nằm cạnh ảnh. Làm tuần tự: A lọc xong hẳn
rồi B mới mở; không cần hai máy cập nhật cho nhau trong lúc cùng mở.

## Hiện trạng
- Đọc .xmp (bản 1.2.5): chỉ chạy lần đầu một máy mở thư mục, chỉ cho ảnh đang 0 sao, sau đó chỉ ảnh mới → máy B
  đã từng mở thư mục sẽ không thấy kết quả lọc mới của máy A.
- Ghi .xmp: chỉ khi xuất (vào thư mục xuất). Hàm `write_xmp` (ghi cạnh ảnh gốc) ghi đè cả file, chưa ai gọi.

## Mục tiêu
- Máy A: mỗi lần sao/loại/nhãn màu của ảnh thay đổi (chấm tay trên máy tính hoặc điện thoại, Tự động lọc,
  Chọn ảnh đẹp chấm 1 sao, hoàn tác) → app tự ghi .xmp cạnh ảnh gốc, chạy nền, không làm chậm lúc lọc.
- Máy B: mỗi lần mở thư mục → đọc lại .xmp; tấm nào có .xmp mới hơn lần đọc trước thì lấy sao/loại/nhãn theo .xmp.
- Mang theo: sao 1–5, loại (xmp:Rating="-1", đúng chuẩn "Rejected" của Lightroom), nhãn màu (xmp:Label).

## Không làm
- Không đồng bộ trực tiếp giữa hai máy đang cùng mở; không chuyển tên người, ✦ đề xuất, vùng nhóm trùng.
- Không sửa file ảnh gốc (JPEG cũng dùng .xmp đi kèm, không nhúng vào JPEG).

## Điều cấm (làm hỏng = thất bại dù chạy được)
- Ghi đè mất dữ liệu .xmp có sẵn của Photo Mechanic/Lightroom (chú thích, từ khoá, IPTC…).
- Lúc lọc bị khựng vì ghi qua mạng.
- Máy B im lặng không thấy gì khi máy A không có quyền ghi vào NAS.

## Cách làm (đã chọn: Cách 1 — tự ghi như Photo Mechanic)
Đã cân nhắc: (2) nút "Ghi kết quả" bấm tay — người lọc dễ quên; (3) một file dữ liệu riêng trong thư mục —
Lightroom/Photo Mechanic không đọc được, dễ hỏng khi ghi đè. Anh chọn Cách 1.

- **Ghi**: mọi chỗ trong library đổi `rating`/`label` gọi chung một hàm đánh dấu "cần ghi" cho các id đó. Một luồng nền
  gom lại (≈2 giây không có thay đổi mới, hoặc tối đa 10 giây) rồi ghi. Ghi xong lưu mtime .xmp vào DB để lần mở sau
  không coi chính file mình vừa ghi là "thay đổi từ máy khác".
- **Gộp, không ghi đè**: .xmp đã có → chỉ thay/thêm `xmp:Rating` và `xmp:Label` (dạng thuộc tính hoặc thẻ), giữ nguyên
  phần còn lại; chưa có → tạo file tối giản. Ảnh 0 sao, không nhãn, chưa có .xmp → không tạo file.
- **Tên file**: `<tên-không-đuôi>.xmp`; nếu đã có file cùng tên khác hoa/thường (.XMP của Photo Mechanic) thì sửa file đó.
  Cặp RAW+JPEG cùng tên dùng chung một .xmp: thao tác mới nhất thắng.
- **Ghi an toàn**: ghi ra file tạm cùng thư mục rồi đổi tên, để mất mạng giữa chừng không để lại .xmp hỏng.
- **Đọc (máy B)**: mỗi lần quét thư mục, chạy nền: với từng ảnh, xem .xmp có mtime khác mtime đã lưu → đọc sao + nhãn,
  ghi đè giá trị trong app (kể cả khi app đang có sao khác — .xmp mới hơn là kết quả lọc mới hơn). Ảnh nhập từ .xmp giữ
  `rsrc=0` như hiện nay. Xong thì điện thoại/lưới tự cập nhật.
- **Lỗi quyền ghi / rớt mạng**: ghi lỗi → giữ lại trong hàng đợi, thử lại sau; báo một lần trên thanh trạng thái
  "Không ghi được .xmp vào thư mục này — kiểm tra quyền ghi trên NAS". Menu có "Ghi lại .xmp cho cả thư mục".
- **Cài đặt**: công tắc "Ghi .xmp vào thư mục ảnh gốc", mặc định bật.

## Để người làm tự quyết
Chi tiết debounce, cách lưu mtime (cột mới trong photos), vị trí công tắc và nút trong giao diện hiện có.
