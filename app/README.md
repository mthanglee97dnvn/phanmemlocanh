# PhotoSift — lọc ảnh tự động + nhận diện khuôn mặt

Công cụ duyệt và chọn ảnh nhanh kiểu Photo Mechanic, có thêm phân tích tự động. Chạy hoàn toàn trên máy bạn (không gửi ảnh đi đâu).
Giao diện mở trong trình duyệt, nhưng server chỉ lắng nghe `127.0.0.1`.

## Cài đặt & chạy
```bash
pip install -r requirements.txt
python run.py              # hoặc: python run.py "D:/Anh/DamCuoi"
```
Windows (không cần biết Python): chạy `MTHANGLEE_PhotoSift_Setup.exe` (cài cho riêng người dùng, không cần quyền Admin), hoặc giải nén bản zip rồi bấm đúp `PhotoSift.bat`.

**Khoá theo mạng:** lọc ảnh *tối*, *cháy sáng* và *nhắm mắt* chỉ hoạt động khi máy có Internet. Ngoại tuyến vẫn duyệt, chấm sao/nhãn màu, lọc mờ/trùng, nhận diện người và xuất ảnh. Đây là cơ chế khoá mềm (kiểm tra kết nối), không phải bản quyền.
Lần chạy đầu sẽ tự tải model còn thiếu (`python -m photosift.models` để tải thủ công).

## Tính năng
| Nhóm | Chi tiết |
|---|---|
| Duyệt | Lưới thumbnail, xem lớn (có dải thumbnail toàn bộ ảnh ở dưới, phím `T` bật/tắt), phóng 100% (`Z`) để kiểm tra độ nét; JPG/PNG/TIFF/WebP/HEIC và RAW (cần `rawpy`) |
| Mạng LAN | Hộp chọn thư mục có nút 🖧 **Mạng LAN**: quét máy đang bật chia sẻ file, xem thư mục chia sẻ, nhập tài khoản nếu máy kia yêu cầu, hoặc gõ `\\\\TÊN-MÁY\\thư-mục`. Dùng được cho cả mở ảnh và thư mục đích khi xuất (Windows) |
| Thông số ảnh | Khung bên phải (nút ℹ️ để bật/tắt): ngày giờ, GPS, máy, số seri, firmware, ống kính, tiêu cự, ISO, khẩu độ, tốc độ, bù sáng, đèn chớp + histogram RGB. Trong trình xem: tô vùng cháy sáng (đỏ) / mất chi tiết tối (cam), phím `H` |
| Chấm ảnh | 0–5 sao, loại (`X`), 5 nhãn màu, chọn nhiều, hoàn tác (`Ctrl+Z`) |
| Tự động lọc | Ảnh **mờ**, **tối**, **cháy sáng**, **nhắm mắt**, **trùng lặp / chụp liên tiếp** (giữ bản điểm cao nhất mỗi nhóm); mỗi loại có ngưỡng chỉnh được |
| Khuôn mặt | Phát hiện (YuNet) + nhận diện/gom theo người (SFace). Đặt tên, gộp người, lọc ảnh theo người |
| Xuất | Sao chép ảnh đã chọn, tách thư mục theo từng người, đổi tên theo mẫu `{date}_{seq}_{person}`, ghi `.xmp` (sao, nhãn, tên người) |

Phím tắt: `← → ↑ ↓` di chuyển · `Enter` xem lớn · `0-5` sao · `X` loại · `6-9` nhãn màu · `F` khung mặt · `Ctrl+A` chọn hết. Bấm `?` trong ứng dụng.

## Dàn trang ngay trong app
Thanh trên cùng có hai chế độ: **Lọc ảnh** (`Ctrl+1`) và **Dàn trang** (`Ctrl+2`). Lọc xong, bấm **🧩 Dàn trang** để gửi ảnh đang chọn hoặc ảnh theo số sao sang dự án layout. Ảnh chỉ được liên kết theo đường dẫn, không sao chép; khâu xuất đọc lại file gốc. Dự án layout tự lưu trong dữ liệu trình duyệt của cửa sổ app. Nếu đổi tên, di chuyển file gốc hoặc rút ổ đĩa, ảnh vẫn hiện bằng bản xem trước nhưng xuất ra sẽ kém nét cho tới khi file trở lại đúng chỗ. Nút **Sao lưu** đóng gói kèm ảnh để chuyển máy.

## Tốc độ khi đọc RAW từ thẻ nhớ
- Chỉ đọc vài KB cấu trúc file + đúng đoạn ảnh JPEG xem trước (khoảng 1–3 MB), **không đọc cả file RAW** (hàng chục MB).
- Hai pha: thumbnail hiện ngay khi đọc xong từng ảnh; việc phân tích (mờ, khuôn mặt…) chạy nền song song, tính trên ảnh cache trong ổ máy.
- Ảnh cache (1600 px) + thumbnail lưu ở thư mục `.photosift` trong thư mục người dùng (khoảng 0,4–0,5 MB/ảnh). Mở lại thư mục đã đọc thì hiện ngay. Muốn dọn: xoá thư mục đó.

## Nếu ảnh dọc vẫn sai chiều
Mở ảnh lớn (Enter) → bấm **🔧 Chẩn đoán file** → bấm "Sao chép" và gửi nội dung cho người hỗ trợ. Báo cáo cho biết file RAW lưu hướng xoay ở đâu.

## An toàn dữ liệu
Không bao giờ xoá hoặc di chuyển file gốc. “Loại” chỉ là một dấu trong cơ sở dữ liệu (`~/.photosift/`); muốn lấy bộ ảnh đã chọn thì dùng **Xuất ảnh** (sao chép).

## Giới hạn cần biết
- **Độ mờ** đo bằng độ nét tương đối so với trung vị của cả thư mục (ưu tiên vùng khuôn mặt nếu có). Ảnh có bokeh mạnh hoặc mặt rất nhỏ có thể bị gắn cờ nhầm → chỉnh ngưỡng, hoặc xem lại bằng bộ lọc “Mờ” trước khi áp dụng.
- **Nhắm mắt** dùng điểm mốc khuôn mặt (EAR), chỉ đo với mặt đủ lớn và nhìn thẳng; cần file `models/lbfmodel.yaml`. Đây là ước lượng, hãy luôn xem lại.
- **Gom người** là tự động nên có thể tách một người thành nhiều nhóm hoặc gộp nhầm; dùng ⚙ để chỉnh ngưỡng, và đổi tên/gộp thủ công.
- File `.xmp` kèm RAW được Lightroom/Bridge/Capture One đọc; với JPEG thì các phần mềm này thường bỏ qua sidecar.
- Ảnh RAW dùng ảnh xem trước JPEG nhúng trong file để phân tích cho nhanh.

## Cấu trúc
`run.py` khởi động · `photosift/analyzer.py` phân tích ảnh · `library.py` quét/gom người/nhóm trùng/xuất · `server.py` API cục bộ · `web/shell.html` khung hai chế độ · `web/index.html` Lọc ảnh · `web/layout.html` Dàn trang
