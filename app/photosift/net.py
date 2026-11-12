"""HTTPS helper: gắn sẵn bộ chứng chỉ gốc (certifi) cho mọi kết nối ra GitHub.

Trên bản macOS đóng gói, Python không có sẵn file CA của hệ thống nên ssl báo lỗi
"CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate". Dùng certifi
(được nhúng kèm app) để sửa dứt điểm; Windows vẫn chạy bình thường như trước.
"""
from __future__ import annotations

import ssl
import urllib.request

_CTX = False  # False = chưa dựng; sau đó là SSLContext hoặc None


def _context():
    global _CTX
    if _CTX is not False:
        return _CTX
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        try:
            ctx = ssl.create_default_context()
        except Exception:
            ctx = None
    _CTX = ctx
    return ctx


def urlopen(url, timeout: float = 15):
    """Như urllib.request.urlopen nhưng kèm sẵn CA của certifi (chỉ dùng cho https)."""
    return urllib.request.urlopen(url, timeout=timeout, context=_context())
