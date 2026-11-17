# Học gu chọn ảnh và đề xuất đúng số ảnh cần giao — thiết kế

## Vì sao
Anh Thắng muốn bán được nhiều bản quyền hơn. Hai thứ còn thiếu so với Aftershoot và Narrative (bán thuê bao 10–55 USD/tháng) là:
1. "Chọn giúp tôi khoảng N tấm đẹp nhất".
2. App học gu chọn ảnh của từng người.

"Tự động lọc" hiện nay **hên xui**. App chỉ biết gắn ✕ cho ảnh dính cảnh báo theo ngưỡng so tương đối trong từng thư mục. Điểm chất lượng là một công thức cố định (65% độ nét + 35% phơi sáng, trừ khi nhắm mắt hoặc quay mặt), không biết khoảnh khắc hay gu của người chọn.

Cull & Collage bán đứt 500.000đ. Câu bán hàng nhắm tới: **"bán đứt 500k, lọc theo gu của thợ cưới thật, và càng dùng càng giống gu của bạn"**.

## Thói quen của người dùng (anh Thắng nói)
- Chọn ảnh đẹp bằng **1–5 sao**. Ảnh không được chọn coi như bỏ.
- Vậy trong một đám đã lọc xong: **sao ≥ 1 = giữ**, còn lại (0 sao hoặc ✕) = bỏ.

## Mục tiêu
- Ô "Chọn khoảng **N** tấm" → app gắn dấu **đề xuất** cho đúng N tấm. Ảnh đã chấm sao luôn nằm trong N và được tính vào N.
- App tự học gu từ các đám đã chấm sao trên máy người dùng. Không cần mạng, không gửi ảnh đi đâu.
- Người mới mua dùng được ngay nhờ **gu mặc định**, học từ các đám anh Thắng đã lọc và đóng gói sẵn trong app. Sau vài đám tự chấm, app chuyển dần sang gu riêng của người đó.
- Cho người dùng thấy app đã giống gu mình tới đâu, ví dụ "Trên đám gần nhất, app đoán trúng 78% số ảnh bạn đã chọn".

## Không làm
- Không chạy trên máy chủ hay đám mây. Không gửi ảnh hoặc dữ liệu người dùng đi đâu.
- Không làm gallery cho khách tự chọn, không chỉnh màu, không retouch.
- Không tự chấm sao. Không tự gắn ✕ cho ảnh ngoài N tấm.
- Không thay chức năng "Tự động lọc" (loại ảnh lỗi) hiện có. Nó vẫn giữ nguyên.

## Phải tránh
- **App học lại chính đề xuất của nó.** Sao luôn là lựa chọn của người. Lô sao chấm hàng loạt từ đề xuất được đánh dấu và tính nhẹ đi khi học.
- **Học từ đám đang lọc dở.** Chỉ học từ đám đã lọc xong (xem cách nhận biết bên dưới). Người dùng xem và bỏ tick được từng đám.
- **Làm chậm lúc nhập ảnh.** Phần đo thêm chạy nền sau khi phân tích xong, giống `_scene_backfill`.
- **Kết quả không ổn định.** Cùng dữ liệu và cùng N thì luôn ra cùng một bộ ảnh.

## Các cách đã cân nhắc
- **A. Lọc đúng N tấm theo điểm cố định hiện có:** nhanh nhưng vẫn hên xui.
- **B. Học gu của từng người, rồi lọc đúng N tấm:** đúng gu, nhưng người mới mua chưa có gì để học.
- **C. B + gu mặc định học từ studio anh Thắng:** **anh Thắng chọn (C, gồm cả B).**
- Cách đánh dấu kết quả. Đã cân nhắc: tự chấm 1 sao (dữ liệu học bị bẩn), gắn ✕ cho phần còn lại (ngược với thói quen chọn bằng sao). **Anh Thắng chọn: chỉ gắn dấu "đề xuất"**, kèm nút chấm sao hàng loạt.

## Thiết kế

### 1. Dữ liệu cho mỗi ảnh
Đã có sẵn trong bảng `photos`: `sharp`, `fsharp`, `lum`, `lo`, `hi`, `nfaces`, `ear_min`, `smile`, `away`, `focus_c`, `scene`, `grp`, `best`, `score`, `taken` (cộng `toff`), `w`, `h`, `people` (bảng `faces`).

Thêm mới:
- `photos.clip BLOB`: vector nội dung ảnh 512 chiều từ model CLIP (`scene.py`, cùng model đang dùng để phân loại cảnh), chuẩn hoá L2, lưu float16 (khoảng 1 KB mỗi ảnh). Đây là "dấu vân tay" bố cục và khoảnh khắc.
  - Ảnh mới: tính trong pha phân tích hoặc pha nền.
  - Ảnh cũ: tính bù từ ảnh cache (`PREVIEWS/<id>.jpg`), chạy nền 2 luồng như `_scene_backfill`.
  - Không có model CLIP thì cột để trống và app chỉ học bằng các số đo còn lại.
  - `scene.py` thêm hàm `embed(bgr) -> np.ndarray | None`. `classify` dùng lại hàm này để không chạy model hai lần.
- `photos.sugg INTEGER DEFAULT 0`: 1 = đang được đề xuất.
- `photos.rsrc INTEGER DEFAULT 0`: nguồn của sao. 0 = người chấm từng tấm, 1 = chấm hàng loạt từ đề xuất. Khi người dùng chấm hoặc đổi sao từng tấm thì đặt lại về 0.

**Đặc trưng đưa vào mô hình.** Chuẩn hoá **trong từng đám** (theo `catalog.root`, z-score hoặc thứ hạng phần trăm) để mỗi đám chụp dày hay thưa, sáng hay tối không làm lệch kết quả:
- độ nét (dùng `fsharp` nếu có mặt, không thì `sharp`), phơi sáng (`lum`, phần cháy và phần đen), mắt nhắm, nụ cười, số người quay mặt / số mặt, số mặt, độ tin cậy điểm nét, loại cảnh (one-hot);
- vị trí trong nhóm ảnh trùng: có phải `best` không, thứ hạng độ nét trong nhóm, cỡ nhóm;
- có cô dâu/chú rể trong khung không (hai người xuất hiện nhiều nhất, như `photos()` đang tính `couple`);
- mật độ bấm máy quanh thời điểm đó (số ảnh trong ±30 giây, khoảnh khắc quan trọng thường chụp dày);
- vector CLIP 512 chiều.

### 2. Mô hình
- Hồi quy logistic, viết bằng numpy. **Không thêm thư viện mới.**
- Đầu ra: điểm 0..1 = "khả năng người này giữ tấm này".
- **Gu mặc định:** file `app/models/taste_default.npz` gồm trọng số và tham số chuẩn hoá, đóng gói trong bộ cài.
- **Gu riêng:** luyện trên các đám của người dùng, kéo trọng số về phía gu mặc định (phạt L2 theo khoảng cách tới trọng số mặc định, không phải tới 0). Ít dữ liệu thì gần gu mặc định; nhiều dữ liệu thì theo người dùng.
- Mẫu có `rsrc=1` mang trọng số 0.3.
- Giữ cân bằng lớp, vì ảnh giữ thường chỉ chiếm 15–30%.
- Lưu ở `HOME/taste.npz`, kèm số đám, số ảnh, ngày học và độ trùng khớp.
- **Độ trùng khớp:** luyện trên mọi đám trừ đám gần nhất, rồi trên đám gần nhất lấy đúng N = số ảnh người dùng đã chọn. Độ trùng khớp = tỉ lệ ảnh app chọn trùng với ảnh người dùng chọn.
- Mục tiêu tốc độ: luyện vài chục nghìn ảnh dưới 10 giây; chấm điểm 5.000 ảnh dưới 1 giây.

### 3. Nhận biết "đám đã lọc xong"
- Một `catalog.root` được tính là xong khi có ít nhất 200 ảnh đã phân tích **và** ít nhất 3% ảnh được chấm sao ≥ 1.
- Hộp "Gu chọn ảnh" liệt kê các đám này kèm ô tick; người dùng bỏ tick được đám không muốn dùng để học. Danh sách đám bị bỏ được lưu lại.
- Tự học lại ở chế độ nền khi mở hộp đề xuất mà có đám mới đã lọc xong hoặc có thay đổi kể từ lần học trước. Có thêm nút "Học lại".

### 4. Đề xuất N tấm
- Ô nhập N, mặc định là số lần trước, hoặc khoảng 12% số ảnh. Có thể gõ theo % ("15%").
- Cách chọn (tất định):
  1. Bỏ ảnh đã ✕ và ảnh lỗi đọc.
  2. Ảnh đã chấm sao ≥ 1 luôn được chọn và tính vào N.
  3. Mỗi nhóm ảnh trùng (`grp`) chỉ lấy tối đa 1 tấm, là tấm có điểm cao nhất.
  4. Lấy lần lượt theo điểm từ cao xuống thấp, bỏ qua tấm quá giống tấm đã chọn (cos CLIP > 0.95 và cách nhau dưới 60 giây). Không có CLIP thì chỉ dùng điều kiện nhóm trùng.
  5. **Phủ dòng thời gian:** chia buổi chụp thành các đoạn tách nhau bởi khoảng trống trên 10 phút. Đoạn nào có ít nhất 20 ảnh mà chưa có tấm nào thì thêm tấm điểm cao nhất của đoạn đó, đổi lấy tấm điểm thấp nhất đang được chọn.
  6. Nếu không đủ N tấm khác nhau thì đề xuất hết số có được và báo "chỉ tìm được X tấm khác nhau".
- Kết quả: đặt `sugg=1` cho N tấm (đặt lại về 0 cho cả thư mục trước đó).

### 5. Giao diện
- Hộp **"Tự động lọc"** chia hai phần:
  - "Loại ảnh lỗi": phần hiện có, giữ nguyên.
  - **"Chọn ảnh đẹp"**: ô "Chọn khoảng [ 400 ] tấm", dòng "Đang dùng: gu mặc định / gu của bạn (học từ 12 đám, trùng khớp 78%)", nút **Đề xuất**.
- Sau khi đề xuất, lưới chuyển sang bộ lọc **"✦ Đề xuất (N)"**. Mỗi ô ảnh có dấu ✦ ở góc. Thanh trên có hai nút:
  - **"Chấm 1 sao cho tất cả đề xuất"**: chỉ chấm cho ảnh chưa có sao, đặt `rsrc=1`, hoàn tác được.
  - **"Bỏ đề xuất"**.
- Bộ lọc "✦ Đề xuất" có trong ô Lọc. Phím tắt chấm sao 1–5 trên ảnh đề xuất vẫn chạy bình thường (`rsrc=0`).
- Hộp **"Gu chọn ảnh"**, mở từ phần "Chọn ảnh đẹp":
  - danh sách đám đã lọc xong, có ô tick;
  - số ảnh, độ trùng khớp;
  - nút "Học lại" và "Dùng lại gu mặc định".
- **Xuất dữ liệu học (để làm gu mặc định):** nút ẩn trong hộp "Gu chọn ảnh" (giữ Alt hoặc Option khi mở). Ghi ra `taste_data.npz` gồm các đặc trưng đã chuẩn hoá, nhãn giữ/bỏ, mã đám và vector CLIP. **Không có ảnh và không có tên file.** Anh Thắng gửi file này để luyện `taste_default.npz` bằng `tools/train_taste.py`.

### 6. Thành phần mã
- `app/photosift/taste.py` (mới): trích đặc trưng, luyện, chấm điểm, chọn N tấm, độ trùng khớp, xuất và nạp. Không phụ thuộc `Library`; nhận dữ liệu dạng mảng.
- `library.py`: cột mới; pha nền tính CLIP; đọc dữ liệu đưa cho `taste.py`; `suggest(n)`, `suggest_clear()`, `suggest_rate()`, `taste_info()`, `taste_learn()`, `taste_export()`.
- `server.py`: route GET `/api/taste`; POST `/api/taste/learn`, `/api/suggest`, `/api/suggest/clear`, `/api/suggest/rate`, `/api/taste/export`.
- `index.html`: phần "Chọn ảnh đẹp", hộp "Gu chọn ảnh", bộ lọc và dấu ✦, hai nút trên thanh.
- `tools/train_taste.py`: luyện gu mặc định từ một hoặc nhiều file `taste_data.npz`.
- `photos()` trả thêm trường `sugg`.

## Ràng buộc
- Chạy offline, Windows và macOS (Apple Silicon, Intel). Chỉ dùng numpy cùng onnxruntime và model CLIP mà app đã có.
- Cột mới thêm theo kiểu `ALTER TABLE` như `db.py` đang làm.
- Chữ trên giao diện bằng tiếng Việt, dùng giao diện tối và các biến màu sẵn có.
- Lệnh đọc dùng GET; lệnh ghi dùng POST và luôn gửi kèm thân (bài học từ lỗi "Not Found" ở 1.2.2).
- Tác giả commit: MThanglee.

## Đọc sao từ Photo Mechanic / Lightroom (theo câu trả lời của anh Thắng)
Anh Thắng chấm sao các đám cũ trong Photo Mechanic, các đám gần đây trong Cull & Collage. Để học được cả các đám cũ (và để người mua chuyển từ Photo Mechanic sang mà vẫn giữ sao cũ), app **đọc sao có sẵn** khi quét thư mục:
- Đọc `xmp:Rating` từ file `.xmp` đi kèm (cùng tên, đuôi `.xmp`/`.XMP`, kể cả kiểu `ảnh.ARW.xmp`) hoặc XMP nhúng trong JPEG.
- Chỉ đặt sao cho ảnh đang 0 sao trong app; không ghi đè sao đã chấm trong app. Rating âm (Lightroom "rejected") → ✕.
- Sao đọc vào được coi là người chấm (`rsrc=0`).
- Muốn có dữ liệu học, mỗi đám cũ cần được **mở trong app một lần** để app đo ảnh (và tính luôn vector CLIP lúc ảnh cache còn đó). Hộp "Gu chọn ảnh" ghi rõ điều này.
- Nếu một đám chấm sao ở cả hai nơi, giữ sao trong app.

## Quyết định của Claude sau vòng đọc soát (anh Thắng xem lại)
- **CLIP cho các đám cũ:** chỉ tính khi còn ảnh cache, hoặc khi đám đó được mở lại. Không đọc lại ảnh gốc của mọi đám cũ, vì ảnh có thể nằm trên ổ đã rút. Vì vậy mô hình gồm **hai bản trong cùng một file**:
  - bản "đầy đủ" (các số đo + CLIP), dùng khi ảnh có CLIP;
  - bản "cơ bản" (chỉ các số đo), dùng khi ảnh chưa có CLIP hoặc máy không có model CLIP.
  - Cả gu mặc định lẫn gu riêng đều có đủ hai bản.
- **Khi chưa có `taste_default.npz`:** "Chọn ảnh đẹp" vẫn chạy, nhưng chấm điểm bằng `score` hiện có và ghi rõ "gu cơ bản (chưa học)". Bản phát hành đầu không phải chờ dữ liệu của anh Thắng.
- **Một "đám" = một `catalog.root`.** Thư mục lồng nhau thì mỗi ảnh chỉ thuộc một đám, là root có đường dẫn dài nhất chứa nó. Cặp đôi, nhóm trùng và mật độ bấm máy được tính lại theo từng đám khi xuất hoặc khi học, không dùng giá trị của thư mục đang mở.
- **Bản dùng thử:** có đủ tính năng này như các tính năng khác, vì đây là điểm để chốt bán.
- **Ảnh ✕:**
  - ✕ do người dùng tự bấm = bỏ, trọng số 1.
  - ✕ từ một lần "Tự động lọc" (ảnh nằm trong `cull_log`) = bỏ, trọng số 0.5, để mô hình không học lại công thức cũ.
- **Phiên bản CLIP:** ghi tên model CLIP kèm vector và kèm `taste.npz`. Model đổi thì vector cũ coi như chưa có.
- **Sao đã nhiều hơn N:** đề xuất đúng các ảnh có sao và báo "Bạn đã chọn X tấm, nhiều hơn N".

## Quy mô dữ liệu (anh Thắng nói)
- Studio làm tới **khoảng 57 đám mỗi tháng**, cả anh lẫn ekip. Một tháng có thể tới khoảng 150.000 ảnh đã chấm.
- Học gu riêng chỉ dùng **40 đám gần nhất**. Trong mỗi đám, giữ toàn bộ ảnh được chọn và lấy mẫu ảnh bỏ, tối đa 4 ảnh bỏ cho mỗi ảnh giữ. Cách này giữ thời gian học dưới 10 giây và không phình bộ nhớ.
- Gu mặc định luyện từ toàn bộ dữ liệu anh Thắng xuất ra. Không giới hạn số đám, vì việc luyện chạy trên máy dựng chứ không chạy trên máy khách.
- Hàm học phải xử lý được khoảng 200.000 dòng × khoảng 540 cột bằng numpy mà không cần thư viện khác. Dùng mini-batch và float32.

## Để người làm tự quyết
- Cách chuẩn hoá trong từng đám (z-score hay thứ hạng phần trăm) và hệ số phạt L2. Chọn theo độ trùng khớp đo được trên dữ liệu thử.
- Bố cục chi tiết của hộp và các nút. Hình dạng dấu ✦ trên ô ảnh.
- Số luồng tính CLIP nền và thứ tự ưu tiên (ảnh của thư mục đang mở trước).
