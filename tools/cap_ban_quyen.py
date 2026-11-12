"""Cấp bản quyền VĨNH VIỄN cho một máy đã thanh toán (chỉ chủ phần mềm dùng).

Khách quét QR trả 500.000đ (nội dung chuyển khoản có sẵn mã máy, vd MTCCABCDEFGHIJKLM).
Bạn tạo key VĨNH VIỄN cho đúng mã máy đó bằng KeyGen, rồi chạy:

    python tools/cap_ban_quyen.py "ABCD-EFGH-IJKLM" "MTCC-...key vĩnh viễn..."

Lệnh ghi vào license/grants.json. Đẩy lên main là GitHub đăng danh sách lên kho phát hành;
app trên máy khách tự tải về và chuyển sang bản vĩnh viễn trong vòng ~15 phút (hoặc ngay khi
khách đang mở màn hình mua). Gỡ một máy khỏi danh sách: thêm chữ "xoa" ở cuối lệnh.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(__file__)
F = os.path.join(HERE, "..", "license", "grants.json")


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    machine = args[0].strip().upper()
    if not re.fullmatch(r"[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{5}", machine):
        print("Mã máy chưa đúng. Dạng đúng: ABCD-EFGH-IJKLM")
        sys.exit(1)
    data = {}
    if os.path.exists(F):
        data = json.load(open(F, encoding="utf-8"))
    if len(args) >= 3 and args[2].strip().lower() in ("xoa", "xóa", "remove", "del"):
        data.pop(machine, None)
        print("Đã gỡ máy khỏi danh sách cấp:", machine)
    else:
        key = args[1].strip()
        if not key.upper().startswith("MTCC"):
            print("Key chưa đúng (phải bắt đầu bằng MTCC-). Hãy dán đúng key vĩnh viễn từ KeyGen.")
            sys.exit(1)
        data[machine] = key
        print("Đã cấp VĨNH VIỄN cho máy:", machine)
    json.dump(data, open(F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Đã ghi", F, "- hiện có", len(data), "máy. Hãy git commit + push lên main.")


if __name__ == "__main__":
    main()
