"""Đổi lỗi hệ thống (tiếng Anh, có mã errno) thành câu tiếng Việt nói rõ nguyên nhân và cách xử lý."""
from __future__ import annotations

import errno

_MSG = {
    errno.ENOENT: "Không tìm thấy thư mục hoặc file. Có thể ổ đĩa chưa cắm, hoặc thư mục đã đổi tên.",
    errno.ENOTDIR: "Đường dẫn này là một file, không phải thư mục.",
    errno.EISDIR: "Đường dẫn này là thư mục, không phải file.",
    errno.EACCES: "Windows không cho phép truy cập. Hãy chọn thư mục khác hoặc kiểm tra quyền của thư mục.",
    errno.EPERM: "Windows không cho phép thao tác này. Hãy chọn thư mục khác hoặc kiểm tra quyền của thư mục.",
    errno.ENOSPC: "Ổ đĩa đã đầy. Hãy giải phóng dung lượng hoặc chọn ổ khác.",
    errno.EROFS: "Ổ đĩa chỉ cho đọc, không ghi được. Hãy chọn ổ khác.",
    errno.EEXIST: "Đã có file hoặc thư mục cùng tên.",
    errno.ENAMETOOLONG: "Tên hoặc đường dẫn quá dài. Hãy rút ngắn tên thư mục.",
    errno.EBUSY: "File đang được chương trình khác dùng. Hãy đóng chương trình đó rồi thử lại.",
}
_WIN = {2: errno.ENOENT, 3: errno.ENOENT, 5: errno.EACCES, 32: errno.EBUSY, 112: errno.ENOSPC, 53: None, 67: None, 1326: None}


def friendly(e: BaseException) -> str:
    if isinstance(e, OSError):
        w = getattr(e, "winerror", None)
        if w in (53, 67):
            return "Không kết nối được máy trong mạng LAN. Hãy kiểm tra máy kia đang bật và chia sẻ thư mục."
        if w == 1326:
            return "Sai tài khoản hoặc mật khẩu của máy trong mạng LAN."
        code = _WIN.get(w) or e.errno
        if code in _MSG:
            return _MSG[code]
        return f"Lỗi đọc ghi ổ đĩa ({e.strerror or e})."
    if isinstance(e, (KeyError, ValueError, TypeError)):
        return "Dữ liệu gửi lên chưa đúng. Hãy thử lại."
    return str(e) or "Có lỗi không rõ nguyên nhân. Hãy thử lại."
