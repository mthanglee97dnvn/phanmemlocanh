# Bảng "Có bản mới…" chỉ hiện tính năng đáng chú ý — thiết kế ngắn

## Vì sao
Bảng cập nhật đang đổ nguyên `WHATSNEW.txt`. File này được viết dồn qua nhiều bản, dài khoảng 3.400 ký tự, mỗi mục kèm đoạn giải thích và hướng dẫn. App cắt ở 2.000 ký tự và hiện thành một khối chữ trơn. Bản 1.2.1 và 1.2.2 chỉ sửa lỗi nhưng vẫn liệt kê lại toàn tính năng cũ. Anh Thắng muốn khách đọc lướt là biết bản mới có gì đáng chú ý.

## Ai chọn nội dung
Anh Thắng chọn để Claude soạn sẵn mỗi lần phát hành: 2–4 dòng nổi bật cho đúng bản đó, mỗi dòng mở đầu bằng một biểu tượng.

## Cách làm
- A: bảng chỉ hiện ghi chú của bản mới nhất. Khách bỏ qua vài bản sẽ không thấy gì của các bản đó.
- **B (anh Thắng chọn):** gom ghi chú của mọi bản mới hơn máy khách, bản mới nhất nằm trên.

## Thiết kế
**Nguồn ghi chú (`WHATSNEW.txt`):**
- Từ nay file chỉ chứa các dòng nổi bật của riêng bản sắp phát hành, không viết dồn nữa.
- Mỗi dòng mở đầu bằng biểu tượng, theo dạng `🗂 Đếm cặp RAW–JPEG, lọc ra file lẻ`, tối đa 4 dòng.
- Bản chỉ sửa lỗi thì file chỉ có đúng dòng `Sửa lỗi và chạy ổn định hơn.`
- `release.yml` giữ nguyên.

**App (`update.py`, hàm `check`):**
- App đã tải 30 bản phát hành gần nhất. Lấy thêm mọi bản có số phiên bản lớn hơn máy khách và nhỏ hơn hoặc bằng bản mới nhất, bản mới nhất xếp trên.
- Trả thêm trường `changes: [{ver, lines:[...]}]`. Giữ trường `notes` để tương thích.
- Làm gọn mỗi ghi chú:
  - Bỏ comment HTML (dấu `src:`), dòng trống, dòng mở đầu bằng `•`, dòng "Cảm ơn…" và dòng "©…".
  - Chỉ giữ dòng mở đầu bằng biểu tượng (ký tự không phải chữ hay số), hoặc dòng "Sửa lỗi…/Cải thiện…".
  - Tối đa 4 dòng mỗi bản.
  - Cách lọc này làm gọn được luôn ghi chú dài của các bản cũ (1.2, 1.2.1, 1.2.2) mà không cần sửa lại trên GitHub.
- Dòng chung chung ("Sửa lỗi và chạy ổn định hơn", "Cải thiện độ ổn định…") gộp thành một dòng duy nhất ở cuối bảng. Bản nào chỉ có dòng chung thì không hiện tiêu đề riêng.
- Tối đa 6 bản. Còn hơn thì thêm dòng "…và N bản trước nữa".
- Giữ cache theo giờ như hiện tại.

**Giao diện bảng (`shell.html`):**
- Tiêu đề vẫn là "Có bản mới X".
- Bên dưới, mỗi bản có một tiêu đề nhỏ màu mờ `Bản 1.2.3`, rồi đến các dòng của bản đó.
- Bảng có chiều cao tối đa và cuộn được.
- Dựng bằng `textContent`, không chèn HTML lấy từ GitHub.
- Khi không có bản mới, vẫn hiện "Bạn đang dùng bản mới nhất." như cũ.

## Không làm
- Không sửa lại ghi chú các bản cũ trên GitHub.
- Không thêm trang "Xem đầy đủ".
- Không đổi luồng tải và cài cập nhật.

## Để người làm tự quyết
- Khoảng cách, cỡ chữ và màu của tiêu đề phiên bản, theo phong cách hộp thoại hiện có.
- Cách nhận diện dòng mở đầu bằng biểu tượng, miễn là các tiêu đề trong `WHATSNEW.txt` hiện tại đều lọt.
