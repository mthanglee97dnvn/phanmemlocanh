"""Nhúng giao diện (đã làm rối) vào module photosift/_webpack.py để biên dịch cùng lõi — bản phát hành không còn file HTML rời.
Cách chạy: python tools/pack_web.py <thư mục web đã làm rối> app/photosift/_webpack.py"""
import os
import secrets
import sys
import zlib

src, out = sys.argv[1], sys.argv[2]
key = secrets.token_bytes(32)
items = {}
for f in sorted(os.listdir(src)):
    p = os.path.join(src, f)
    if os.path.isfile(p) and not f.startswith(".") and " " not in f and f.split(".")[-1] in ("html", "png", "css", "js"):
        z = zlib.compress(open(p, "rb").read(), 9)
        items[f] = bytes(b ^ key[i % len(key)] for i, b in enumerate(z))
with open(out, "w", encoding="ascii") as fo:
    fo.write('"""Generated at build time."""\nimport zlib\n\n')
    fo.write(f"_K = {key!r}\n_D = {{\n")
    for k, v in items.items():
        fo.write(f"    {k!r}: {v!r},\n")
    fo.write("}\n\n\ndef get(name):\n    d = _D.get(name)\n    if d is None:\n        return None\n"
             "    k = _K\n    n = len(k)\n    return zlib.decompress(bytes(b ^ k[i % n] for i, b in enumerate(d)))\n")
print("packed", len(items), "files ->", out, os.path.getsize(out), "bytes")
