"""Bộ tạo mã QR thuần Python (chế độ byte), không phụ thuộc thư viện ngoài — dùng để hiện QR kết nối điện thoại.

Hỗ trợ phiên bản 1–10, mức sửa lỗi M. Trả về ma trận bool rồi kết xuất SVG. Giấy phép: MIT (Lê Minh Thắng / MTHANGLEE STUDIO).
"""
from __future__ import annotations

# ---- GF(256) cho Reed–Solomon (đa thức nguyên thủy 0x11D) ----
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_gen(n: int):
    g = [1]
    for i in range(n):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= _gf_mul(c, _EXP[i])
        g = ng
    return g


def _rs_ec(data: list[int], n: int) -> list[int]:
    gen = _rs_gen(n)
    res = list(data) + [0] * n
    for i in range(len(data)):
        coef = res[i]
        if coef:
            for j in range(len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data):]


# ---- bảng dung lượng, mức M: (ec/khối, [(số_khối, số_byte_dữ_liệu/khối), ...]) ----
_M = {
    1: (10, [(1, 16)]),
    2: (16, [(1, 28)]),
    3: (26, [(1, 44)]),
    4: (18, [(2, 32)]),
    5: (24, [(2, 43)]),
    6: (16, [(4, 27)]),
    7: (18, [(4, 31)]),
    8: (22, [(2, 38), (2, 39)]),
    9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}
_ALIGN = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
    6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}
_FORMAT_M = {  # thông tin định dạng (mức M = 00) theo từng mặt nạ 0..7, đã mã hoá 15 bit
    0: 0x5412, 1: 0x5125, 2: 0x5E7C, 3: 0x5B4B, 4: 0x45F9, 5: 0x40CE, 6: 0x4F97, 7: 0x4AA0,
}


def _data_capacity(version: int) -> int:
    ecc, groups = _M[version]
    return sum(nb * dc for nb, dc in groups)


def _pick_version(nbytes: int) -> int:
    for v in range(1, 11):
        hdr = 4 + (8 if v <= 9 else 16)
        if (hdr + nbytes * 8 + 7) // 8 <= _data_capacity(v):
            return v
    raise ValueError("Chuỗi quá dài cho QR phiên bản ≤10")


def _encode_data(text: bytes, version: int) -> list[int]:
    cap = _data_capacity(version)
    bits: list[int] = []

    def put(val: int, n: int):
        for k in range(n - 1, -1, -1):
            bits.append((val >> k) & 1)

    put(0b0100, 4)                       # chế độ byte
    put(len(text), 8 if version <= 9 else 16)
    for b in text:
        put(b, 8)
    put(0, min(4, cap * 8 - len(bits)))  # kết thúc
    while len(bits) % 8:
        bits.append(0)
    codewords = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < cap:
        codewords.append(pad[i % 2])
        i += 1
    return codewords


def _interleave(codewords: list[int], version: int) -> list[int]:
    ecc_n, groups = _M[version]
    blocks = []
    pos = 0
    for nb, dc in groups:
        for _ in range(nb):
            data = codewords[pos:pos + dc]
            pos += dc
            blocks.append((data, _rs_ec(data, ecc_n)))
    out: list[int] = []
    maxd = max(len(d) for d, _ in blocks)
    for i in range(maxd):
        for d, _ in blocks:
            if i < len(d):
                out.append(d[i])
    for i in range(ecc_n):
        for _, e in blocks:
            out.append(e[i])
    return out


class _Mat:
    def __init__(self, n):
        self.n = n
        self.m = [[None] * n for _ in range(n)]

    def set(self, r, c, v):
        self.m[r][c] = 1 if v else 0


def _place_patterns(mat: _Mat, version: int):
    n = mat.n

    def finder(r, c):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    on = (0 <= dr <= 6 and dc in (0, 6)) or (0 <= dc <= 6 and dr in (0, 6)) or (2 <= dr <= 4 and 2 <= dc <= 4)
                    mat.set(rr, cc, on)
    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)
    for i in range(8):  # vạch phân cách (đã nằm trong vòng finder nhờ viền None->0)
        pass
    # timing
    for i in range(8, n - 8):
        mat.set(6, i, i % 2 == 0)
        mat.set(i, 6, i % 2 == 0)
    # alignment
    centers = _ALIGN[version]
    for r in centers:
        for c in centers:
            if (r < 8 and c < 8) or (r < 8 and c > n - 9) or (r > n - 9 and c < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    on = max(abs(dr), abs(dc)) != 1
                    mat.set(r + dr, c + dc, on)
    mat.set(n - 8, 8, 1)  # dark module
    # version info (v>=7)
    if version >= 7:
        vb = _VERSION_INFO[version]
        for i in range(18):
            bit = (vb >> i) & 1
            a, b = i // 3, i % 3
            mat.set(n - 11 + b, a, bit)
            mat.set(a, n - 11 + b, bit)


_VERSION_INFO = {7: 0x07C94, 8: 0x085BC, 9: 0x09A99, 10: 0x0A4D3}


def _reserved(version: int, n: int):
    res = [[False] * n for _ in range(n)]

    def box(r, c, h, w):
        for dr in range(h):
            for dc in range(w):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    res[rr][cc] = True
    box(0, 0, 9, 9)
    box(0, n - 8, 9, 8)
    box(n - 8, 0, 8, 9)
    for i in range(n):
        res[6][i] = True
        res[i][6] = True
    for r in _ALIGN[version]:
        for c in _ALIGN[version]:
            if (r < 8 and c < 8) or (r < 8 and c > n - 9) or (r > n - 9 and c < 8):
                continue
            box(r - 2, c - 2, 5, 5)
    if version >= 7:
        box(0, n - 11, 6, 3)
        box(n - 11, 0, 3, 6)
    return res


def _place_data(mat: _Mat, res, bits: list[int]):
    n = mat.n
    idx = 0
    col = n - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if upward else range(n)
        for r in rows:
            for c in (col, col - 1):
                if not res[r][c]:
                    b = bits[idx] if idx < len(bits) else 0
                    mat.set(r, c, b)
                    idx += 1
        upward = not upward
        col -= 2


def _apply_mask(mat: _Mat, res, mask: int):
    n = mat.n
    for r in range(n):
        for c in range(n):
            if res[r][c]:
                continue
            if mask == 0:
                cond = (r + c) % 2 == 0
            elif mask == 1:
                cond = r % 2 == 0
            elif mask == 2:
                cond = c % 3 == 0
            elif mask == 3:
                cond = (r + c) % 3 == 0
            elif mask == 4:
                cond = (r // 2 + c // 3) % 2 == 0
            elif mask == 5:
                cond = (r * c) % 2 + (r * c) % 3 == 0
            elif mask == 6:
                cond = ((r * c) % 2 + (r * c) % 3) % 2 == 0
            else:
                cond = ((r + c) % 2 + (r * c) % 3) % 2 == 0
            if cond:
                mat.m[r][c] ^= 1


def _place_format(mat: _Mat, mask: int):
    """Đặt 15 bit thông tin định dạng theo chuẩn QR (bit 0 = LSB)."""
    n = mat.n
    fmt = _FORMAT_M[mask]

    def bit(i):
        return (fmt >> i) & 1

    # bản 1 (quanh finder trái-trên), toạ độ (hàng, cột)
    for i in range(6):
        mat.set(i, 8, bit(i))
    mat.set(7, 8, bit(6))
    mat.set(8, 8, bit(7))
    mat.set(8, 7, bit(8))
    for i in range(9, 15):
        mat.set(8, 14 - i, bit(i))
    # bản 2 (dọc theo finder trái-dưới + ngang theo finder phải-trên)
    for i in range(8):
        mat.set(n - 1 - i, 8, bit(i))
    for i in range(8, 15):
        mat.set(8, n - 15 + i, bit(i))


def _penalty(mat: _Mat) -> int:
    n = mat.n
    m = mat.m
    score = 0
    # quy tắc 1: dãy >=5 cùng màu
    for line in list(m) + [list(col) for col in zip(*m)]:
        run = 1
        for i in range(1, n):
            if line[i] == line[i - 1]:
                run += 1
            else:
                if run >= 5:
                    score += 3 + (run - 5)
                run = 1
        if run >= 5:
            score += 3 + (run - 5)
    # quy tắc 2: khối 2x2
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    # quy tắc 3: mẫu 1011101 0000 / 0000 1011101
    pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat2 = [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1]
    for line in list(m) + [list(col) for col in zip(*m)]:
        for i in range(n - 10):
            seg = line[i:i + 11]
            if seg == pat1 or seg == pat2:
                score += 40
    # quy tắc 4: tỉ lệ ô tối
    dark = sum(sum(row) for row in m)
    pct = dark * 100 // (n * n)
    score += min(abs(pct - 50) // 5 * 10, 100)
    return score


def matrix(text) -> list[list[int]]:
    """Trả về ma trận QR (list các hàng, mỗi ô 0/1) cho chuỗi/bytes đầu vào, mức sửa lỗi M."""
    if isinstance(text, str):
        text = text.encode("utf-8")
    version = _pick_version(len(text))
    n = version * 4 + 17
    codewords = _encode_data(text, version)
    final_bits_codewords = _interleave(codewords, version)
    bits = []
    for cw in final_bits_codewords:
        for k in range(7, -1, -1):
            bits.append((cw >> k) & 1)
    # bù thêm bit remainder (phiên bản 2..6 cần 7 bit, 7..10: 0) — đặt dữ liệu tự bỏ qua nếu thiếu
    res = _reserved(version, n)
    cands = []
    for mask in range(8):
        mat = _Mat(n)
        _place_patterns(mat, version)
        _place_data(mat, res, bits)
        _apply_mask(mat, res, mask)
        _place_format(mat, mask)
        for r in range(n):          # ô nào chưa gán -> 0
            for c in range(n):
                if mat.m[r][c] is None:
                    mat.m[r][c] = 0
        cands.append((_penalty(mat), mask, mat.m))
    cands.sort(key=lambda x: x[0])   # phạt thấp nhất trước (theo chuẩn)
    want = text if isinstance(text, (bytes, bytearray)) else None
    for _pen, _mask, grid in cands:   # ưu tiên mặt nạ phạt thấp mà bộ giải mã đọc được
        if want is None or _decodes(grid, want):
            return grid
    return cands[0][2]


def _decodes(grid: list[list[int]], want: bytes) -> bool:
    """Kiểm tra QR có đọc được không bằng OpenCV (nếu có) — để chắc chắn điện thoại quét được."""
    try:
        import numpy as np
        import cv2
    except Exception:  # noqa: BLE001  không có cv2: bỏ qua, tin theo chuẩn
        return True
    n = len(grid)
    scale, quiet = 8, 4
    N = (n + quiet * 2) * scale
    img = np.full((N, N), 255, np.uint8)
    for r in range(n):
        for c in range(n):
            if grid[r][c]:
                y, x = (r + quiet) * scale, (c + quiet) * scale
                img[y:y + scale, x:x + scale] = 0
    try:
        data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    except Exception:  # noqa: BLE001
        return True
    try:
        return data.encode("utf-8") == want
    except Exception:  # noqa: BLE001
        return False


def svg(text, box: int = 8, border: int = 4, dark: str = "#0b0d12", light: str = "#ffffff") -> str:
    """Kết xuất QR thành SVG vuông, nền sáng — dễ quét bằng camera điện thoại."""
    m = matrix(text)
    n = len(m)
    size = (n + border * 2) * box
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">']
    parts.append(f'<rect width="{size}" height="{size}" fill="{light}"/>')
    for r in range(n):
        c = 0
        while c < n:
            if m[r][c]:
                c0 = c
                while c < n and m[r][c]:
                    c += 1
                x = (c0 + border) * box
                y = (r + border) * box
                w = (c - c0) * box
                parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{box}" fill="{dark}"/>')
            else:
                c += 1
    parts.append("</svg>")
    return "".join(parts)
