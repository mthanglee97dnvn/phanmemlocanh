# Lọc kỹ thuật trên điện thoại (thay máy tính) — thiết kế

## Vì sao
Anh Thắng muốn **lọc kỹ thuật trên điện thoại để thay cho máy tính**. Lọc kỹ thuật là soi nét, bắt ảnh lỗi và chọn tấm tốt nhất trong mỗi loạt.

Trang điện thoại hiện nay (`app/photosift/web/mobile.html`, mở bằng mã QR qua cùng Wi-Fi hoặc Tailscale, cài được thành app trên iPhone) chỉ xem từng tấm: vuốt phải Giữ (1★), vuốt trái Loại, có 1–5 sao và 4 bộ lọc. Như vậy chỉ đủ để lướt cho vui, chưa đủ để lọc kỹ:
- không phóng to để soi nét;
- không thấy cảnh báo, nhóm ảnh trùng, tấm tốt nhất, ✦ đề xuất, người, highlight;
- không hoàn tác;
- màu sắc khác app máy tính.

Mục tiêu bán hàng chung: điện thoại phải là lý do để mua bản quyền, không chỉ là tính năng phụ.

## Cách đã chọn: B (anh Thắng chọn)
- A. Chỉ nâng cấp màn hình từng tấm: vẫn phải lướt 3.000 tấm một, anh vẫn sẽ quay về máy tính để quét nhanh.
- **B. Lưới để quét + màn hình từng tấm để soi.** Giống cách làm trên máy tính.
- C. Đưa nguyên giao diện máy tính lên điện thoại: nút quá nhỏ cho ngón tay, không vuốt được, không đủ chỗ. Bỏ.

## Mục tiêu
1. **Lưới** để quét nhanh hàng trăm tấm, thấy ngay ảnh lỗi, loạt trùng và ✦ đề xuất.
2. **Màn hình từng tấm** để soi nét tới 100% và chọn tấm trong một loạt trùng.
3. Có đủ các công cụ lọc chính của máy tính: Tự động lọc, ✦ Chọn ảnh đẹp, bộ lọc, hoàn tác.
4. Thao tác một tay, ngón cái với tới được. Phản hồi ngay, ảnh hiện nhanh qua Wi-Fi.
5. Màu và chữ đồng bộ với app máy tính.

## Không làm
- Không xuất ảnh, không Dàn trang, không đồng bộ máy, không đổi tên người, không hộp "Gu chọn ảnh" trên điện thoại. Mấy việc này vẫn làm trên máy tính.
- Không lưu ảnh trên điện thoại hay chạy được khi máy tính tắt. Điện thoại vẫn là màn hình từ xa của app trên máy tính.
- Không làm app native (App Store hoặc CH Play). Vẫn là trang web cài lên màn hình chính.

## Phải tránh
- Lưới giật hay nóng máy vì tải hàng nghìn ảnh cùng lúc.
- Chạm nhầm làm đổi sao hay loại ảnh mà không hoàn tác được.
- Thao tác trên điện thoại và trên máy tính lệch nhau, kiểu điện thoại hiện sao cũ.
- Hỏng các cử chỉ quen tay hiện có: vuốt phải Giữ, vuốt trái Loại, chạm mép để lùi/tới.

## Thiết kế

### Cấu trúc
- Một trang `mobile.html` có hai chế độ: **Lưới** (mở mặc định) và **Xem** (từng tấm).
- Thanh trên: ☰ chọn thư mục, tên thư mục, ô số `đã giữ · đã loại · chưa chấm`, nút ⋯ mở bảng công cụ.
- Thanh dưới (vùng ngón cái): bộ lọc nhanh dạng chip cuộn ngang:
  - Tất cả · Chưa chấm · Đã giữ · Đã loại · ✦ Đề xuất · Cảnh báo (mờ / nhắm mắt / tối / cháy sáng / quay mặt) · Highlight · từng người (tên do máy tính đặt) · File lẻ cặp RAW–JPEG.
  - Danh sách lọc và thứ tự giống `matchFilter` trên máy tính.
- Chữ: Be Vietnam Pro, giống website và máy tính. Màu: nền `#0F0F11`, màu nhấn `#E8A33D`, đỏ `#E5564B`, chữ `#EDEDEF`.

### Lưới
- 3 cột khi máy dọc, 5 cột khi xoay ngang. Có nút chuyển 2 / 3 / 4 cột, được nhớ lại.
- Ô dùng ảnh nhỏ `/thumb/<id>.jpg`, tải lười theo vùng đang thấy. Chỉ giữ ảnh trong khoảng ±3 màn hình, tức cuộn ảo hoá, để danh sách 5.000 tấm vẫn mượt.
- Trên mỗi ô:
  - sao vàng ở góc;
  - ✕ đỏ và làm tối ảnh khi đã loại;
  - chip đỏ nhỏ cho cảnh báo;
  - dấu ✦ khi được đề xuất;
  - số "×5" khi ô đại diện cho một loạt trùng.
- **Gộp loạt trùng** (mặc định bật, tắt được), giống "Xếp chồng ảnh trùng" của máy tính: mỗi `grp` hiện 1 ô bằng tấm `best`.
- Chạm ô: mở Xem tại ảnh đó. Nếu là loạt trùng thì mở ở chế độ so loạt.
- **Chạm giữ ô:** vào chế độ chọn nhiều. Chạm thêm ô khác để chọn tiếp. Thanh dưới đổi thành: ★1 · ★2 · ★3 · Loại · Bỏ chấm · Huỷ. Áp cho cả nhóm đã chọn, có hoàn tác.
- Cuộn tới đâu, thanh trên hiện giờ chụp của đoạn đó, để biết đang ở khúc nào của buổi lễ.

### Xem (từng tấm)
- Ảnh tải `/api/preview?id&s=<cạnh màn hình × devicePixelRatio, tối đa 2400>`. Khi phóng to quá 1.5×, tải thêm bản gốc `s=0` cho vùng soi.
- **Phóng to bằng hai ngón** (1×–4×, kéo để di chuyển). **Chạm đúp:** nếu có điểm lấy nét (`focus`) thì nhảy tới 100% đúng điểm đó, không có thì phóng 2.5× tại chỗ chạm; chạm đúp lần nữa để về vừa màn hình.
- Nút ◎ bật/tắt khung điểm lấy nét, như phím F trên máy tính.
- **Khi đang phóng to**, vuốt ngang để di chuyển ảnh chứ không Giữ/Loại. Chỉ ở mức vừa màn hình thì vuốt mới là Giữ/Loại như cũ.
- Hàng chip trên ảnh: cảnh báo (đỏ), "Tốt nhất" (vàng) khi là `best` của loạt, ✦ đề xuất, điểm chất lượng.
- **Dải loạt trùng:** khi ảnh thuộc một `grp`, phía dưới hiện dải ảnh nhỏ của cả loạt.
  - Chạm ảnh nhỏ để xem tấm đó. Nếu đang phóng to thì giữ nguyên mức zoom và vị trí, để so nét cùng một chỗ giữa các tấm.
  - Nút **"Chọn tấm này"**: tấm đang xem ★1 (giữ sao nếu đã có), các tấm chưa chấm khác trong loạt thành ✕. Có hoàn tác.
- Thanh dưới giữ như hiện nay: sao 1–5, ✕ Loại, ✓ Giữ, ‹ ›. Thêm nút ↶ Hoàn tác.
- Giữ chỗ khi chuyển chế độ: đóng Xem thì lưới cuộn tới đúng ô vừa xem.

### iPad / màn rộng (thêm sau khi anh Thắng xem demo và duyệt)
- Cùng trang. Khi bề ngang ≥ 900px, Lưới và Xem hiện cạnh nhau: lưới 5 cột bên trái (khoảng 44% bề ngang), ảnh lớn bên phải.
- Chạm ô nào trên lưới thì ảnh lớn đổi sang ô đó, không mở màn hình riêng.
- Tự động lọc và ✦ Chọn ảnh đẹp có nút riêng trên thanh trên.
- Demo tham khảo: canvas "Demo lọc ảnh trên điện thoại & iPad".

### Bảng công cụ (⋯)
- **Tự động lọc:** chọn mức Nhẹ / Vừa / Mạnh và các ô cảnh báo, xem trước số ảnh sẽ loại, nút "Đánh dấu loại". Gọi cùng API với máy tính (`/api/cull/apply`, `/api/cull/undo`).
- **✦ Chọn ảnh đẹp:** ô "Chọn khoảng N tấm" (số hoặc %), nút Đề xuất, dòng "Đang dùng: …". Gọi `/api/suggest`. Khi có đề xuất thì hiện thêm "Chấm 1 sao cho tất cả đề xuất" và "Bỏ đề xuất".
- Sắp xếp: Tên, Giờ chụp, Điểm, Loại file, cùng ô Đảo, giống máy tính.

### Hoàn tác
- Một ngăn hoàn tác trên điện thoại, tối đa 50 bước, cho: chấm sao hoặc loại một tấm, chấm nhiều tấm, "Chọn tấm này", Tự động lọc (dùng `/api/cull/undo`), chấm sao cho đề xuất (dùng `/api/suggest/rate/undo`).
- Sau mỗi thao tác hiện thông báo kèm nút "Hoàn tác" trong 4 giây.

### Đồng bộ với máy tính
- Lấy lại danh sách ảnh (`/api/photos`) khi trang được mở lại hoặc điện thoại mở khoá (`visibilitychange`), và định kỳ mỗi 10 giây khi đang mở. Chỉ cập nhật ô nào đổi, không vẽ lại cả lưới, không làm nhảy vị trí cuộn.
- Thao tác trên điện thoại gửi ngay, cập nhật giao diện trước (lạc quan). Lỗi thì trả lại như cũ và báo "Không lưu được".

### Tốc độ
- Mục tiêu: mở lưới 3.000 tấm hiện ô đầu tiên dưới 1 giây sau khi có danh sách; cuộn mượt 60 khung hình trên iPhone đời 11 trở lên.
- Màn hình Xem nạp trước 2 tấm kế tiếp (đã có) và 1 tấm trước.

## Quyết định của Claude sau vòng đọc soát (anh Thắng xem lại)
- **Độ nét ảnh khi Xem:**
  - Hiện ngay bản 1600px đã có sẵn trên máy, nên mở lên là thấy liền.
  - Sau đó thay bằng bản đúng cỡ màn hình (`/api/preview?…&hq=1`, máy tính dựng sẵn ở nền). Gọi `/api/view/ahead` cho vài tấm kế tiếp để máy tính dựng trước.
  - Khi phóng to quá 1.5× thì tải bản gốc `s=0`.
- **Gộp loạt trùng khi đang lọc:** theo đúng cách máy tính làm (lọc trước, rồi mới gộp những ảnh còn lại theo `grp`).
  - Ô hiện tấm tốt nhất còn lại trong loạt, sao và ✕ là của chính tấm đó.
  - Số "×N" là số ảnh của loạt đang nằm trong bộ lọc.
  - Chọn nhiều một ô gộp nghĩa là chọn cả loạt.
- **Số ảnh "sẽ loại" của Tự động lọc:** tách phần tính `cand()` của máy tính thành một file JS dùng chung (`/cull.js`), máy tính và điện thoại cùng nạp, để hai bên luôn ra cùng một con số.
- **Đồng bộ:** thêm route nhẹ `GET /api/photos/ver` trả về số thay đổi của cơ sở dữ liệu.
  - Điện thoại hỏi route này mỗi 10 giây, chỉ tải lại danh sách khi số thay đổi.
  - Thao tác đang gửi dở không bị dữ liệu mới đè lên.
- **Hoàn tác:**
  - Lưu giá trị cũ của từng ảnh.
  - Khi hoàn tác, chỉ trả lại những ảnh vẫn giữ nguyên giá trị điện thoại đã đặt. Ảnh đã bị máy tính đổi sau đó thì bỏ qua, và báo "bỏ qua X ảnh đã sửa trên máy tính".
- **Chip người:**
  - Người đã đặt tên đứng trước, sau đó tới người chưa tên có từ 20 ảnh trở lên.
  - Tối đa 10 chip, xếp theo số ảnh.
  - Thêm chip "Highlight".
- **"Tốt nhất":** vẫn là tấm app chọn. Tấm anh chọn bằng "Chọn tấm này" hiện bằng sao.
- **Chạm đúp và chạm mép:** chạm mép để lùi/tới sẽ chờ 250ms. Nếu có chạm thứ hai thì tính là chạm đúp để phóng to.

## Ràng buộc
- Một file `mobile.html`, JS thuần, không thư viện ngoài. Chạy Safari iOS 15+ và Chrome Android.
- Backend: dùng các API sẵn có. Chỉ thêm trường hoặc route khi thiếu. Mọi POST luôn gửi thân `{}`.
- Không đổi hành vi của máy tính.
- Tác giả commit: MThanglee.

## Để người làm tự quyết
- Kiểu chip, kích cỡ ô, chuyển động khi mở và đóng Xem.
- Cách cuộn ảo hoá.
- Mức zoom cụ thể và ngưỡng vuốt.
- Bố cục bảng ⋯: trượt lên từ dưới hay toàn màn hình.
