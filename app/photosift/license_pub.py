# Khóa công khai của MThanglee Cull&Collage.
# Dán chuỗi lấy từ app MThanglee KeyGen (mục Khóa & sao lưu) vào giữa hai dấu ngoặc kép.
PUB_HEX = "6aab40578a6cc19a165a9bd1881ebab5299461f3f912f72ac1e60810ea43e0a9"

# Khóa công khai BÁN HÀNG (máy chủ tự cấp key khi khách thanh toán tự động).
# Chỉ là khóa CÔNG KHAI — an toàn khi để công khai. Khóa bí mật tương ứng nằm trên máy chủ Cloudflare
# (Worker mtcc-sales tự tạo, giữ trong KV mtcc-trials; xem lại ở https://api.cullcollage.com/pub).
# Thu hồi khi cần: xoá chuỗi này (đặt "") rồi phát hành bản mới.
SALES_PUB_HEX = "d16676102afb31378fdff5c16988c83c3238e56904c100973fd1357b8ae6d993"
