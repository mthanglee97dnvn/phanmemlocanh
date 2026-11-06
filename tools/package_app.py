"""Gói thư mục PyInstaller + model + tài liệu thành build/installer/payload/app.zip (bộ cài sẽ nhúng file này)."""
import os, sys, zipfile

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
core = os.path.join(root, "dist", "PhotoSiftCore")
out = os.path.join(root, "build", "installer", "payload", "app.zip")
if not os.path.isfile(os.path.join(core, "PhotoSiftCore.exe")):
    sys.exit("Không thấy dist/PhotoSiftCore/PhotoSiftCore.exe")
n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for base, _, files in os.walk(core):
        for f in files:
            p = os.path.join(base, f)
            z.write(p, "core/" + os.path.relpath(p, core).replace(os.sep, "/")); n += 1
    for f in os.listdir(os.path.join(root, "app", "models")):
        if f.endswith((".onnx", ".yaml")):
            z.write(os.path.join(root, "app", "models", f), "models/" + f); n += 1
    for f in ("README.md", "HUONG_DAN.txt"):
        z.write(os.path.join(root, "app", f), f); n += 1
print(f"{n} file -> {out} ({os.path.getsize(out)/1e6:.0f} MB)")
