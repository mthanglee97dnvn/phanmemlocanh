# Đếm cặp RAW–JPEG và sắp xếp theo loại file — thiết kế ngắn

## Vì sao
Ekip chụp RAW+JPEG. Sau mỗi đám, anh Thắng cần biết ngay số RAW và JPEG có khớp nhau không. Nếu lệch là có file bị sót hoặc thẻ nhớ lỗi ở một máy nào đó. Trong Photo Mechanic anh phải sắp theo loại file rồi tự dò. Không cần xếp thứ tự theo mạch câu chuyện.

## Cách đã chọn: C (cả B lẫn A)
- A: thêm "Loại file" vào ô Sắp xếp và nút Đảo chiều, giống PM. Rẻ nhưng vẫn phải tự đếm.
- B: app tự đếm và lọc ra file lẻ cặp. Trả lời thẳng câu hỏi.
- **C = B + A.** Anh Thắng chọn.

## Thiết kế
**Ghép cặp:** dùng đúng quy tắc app đang có (`pairHidden`): cùng thư mục, cùng tên không đuôi (không phân biệt hoa thường), một bên là RAW (RAWRE) và một bên là JPEG/ảnh thường.

**Ô đếm trên thanh công cụ** (đặt cạnh ô RAW+JPEG):
- Hiện `RAW 1.240 · JPEG 1.238 · 2 lẻ`.
- Màu xanh khi 0 lẻ, màu cam khi có lẻ.
- Đếm trên toàn bộ ảnh của thư mục đang mở, không phụ thuộc bộ lọc hay ô tìm.
- Chỉ hiện khi có ít nhất một RAW và một JPEG. Bộ chỉ chụp JPEG hoặc chỉ RAW thì ẩn đi, để khỏi báo cam vô lý.
- Có lẻ thì bấm vào ô đếm để lọc ra file lẻ. Bấm lần nữa thì về lại bộ lọc cũ.

**Bộ lọc "File lẻ cặp":**
- Thêm vào danh sách lọc. Chỉ gồm file RAW không có JPEG và JPEG không có RAW.
- Sắp xếp theo máy rồi theo giờ chụp, để nhìn ra lỗi dồn ở máy nào, quãng giờ nào.
- Ô đếm có tooltip chia theo máy, ví dụ `Sony A7IV ·1234: 2 lẻ`, lấy từ thông tin máy đã đọc khi đồng bộ.

**Sắp xếp:**
- Thêm "Loại file (RAW trước)". Trong mỗi nhóm, ảnh xếp theo giờ chụp rồi đến tên.
- Thêm nút Đảo chiều (☐ Đảo), áp cho mọi kiểu sắp xếp. Nút được nhớ lại giữa các lần mở app (localStorage), giống ô sắp xếp Catalog.

## Không làm
- Không làm Arrangement (tự kéo thả xếp thứ tự).
- Không thêm các mục sắp xếp theo ISO, ống kính, serial…
- Không tự tạo hay xoá file để cân cặp.

## Để người làm tự quyết
- Vị trí và kiểu chữ ô đếm, theo đúng phong cách thanh công cụ hiện có.
- Có cần thêm trường `cam` vào `photos()` cho tooltip theo máy hay không. Nếu tốn thì bỏ tooltip, giữ phần đếm.
