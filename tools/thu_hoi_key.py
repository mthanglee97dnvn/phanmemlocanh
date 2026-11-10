"""Thu hồi key bị lộ / bán lại (chỉ chủ phần mềm dùng).

Cách dùng:  python tools/thu_hoi_key.py "MTCC-XXXX-...."
Lệnh thêm MÃ NHẬN DIỆN của key (không phải key) vào license/revoked.txt. Đẩy file đó lên nhánh main là
GitHub tự đăng danh sách lên kho phát hành; mọi máy dùng key này sẽ bị khoá trong vòng vài giờ (khi có mạng).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from photosift.license import key_id  # noqa: E402

if len(sys.argv) < 2:
    print(__doc__)
    sys.exit(1)
kid = key_id(" ".join(sys.argv[1:]))
if not kid:
    print("Key không đúng định dạng.")
    sys.exit(1)
f = os.path.join(os.path.dirname(__file__), "..", "license", "revoked.txt")
old = open(f, encoding="utf-8").read() if os.path.exists(f) else ""
if kid in old:
    print("Key này đã có trong danh sách thu hồi:", kid)
else:
    with open(f, "a", encoding="utf-8") as fo:
        fo.write(kid + "\n")
    print("Đã thêm vào license/revoked.txt:", kid)
