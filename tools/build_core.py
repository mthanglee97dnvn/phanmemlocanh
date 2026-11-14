"""Build phần lõi đã bảo vệ (chạy trên GitHub Actions, Windows hoặc macOS).

1. Làm rối giao diện (JS) và nhúng vào module photosift/_webpack.py — không còn file HTML rời.
2. Biên dịch cả gói photosift sang mã máy bằng Nuitka (--module): bản phát hành không còn mã Python / bytecode.
3. Đóng gói bằng PyInstaller chỉ với bản đã biên dịch + thư viện bên thứ ba.

Cách chạy:  python tools/build_core.py win   |   python tools/build_core.py mac
"""
import glob
import os
import shutil
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):   # máy build Windows dùng bảng mã cũ: in tiếng Việt không được làm hỏng build
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = sys.argv[1] if len(sys.argv) > 1 else ("win" if os.name == "nt" else "mac")
PY = sys.executable
SEP = ";" if os.name == "nt" else ":"


def run(*a, **kw):
    print(">", " ".join(a), flush=True)
    subprocess.check_call(list(a), cwd=ROOT, **kw)


def rm(p):
    p = os.path.join(ROOT, p)
    if os.path.isdir(p):
        shutil.rmtree(p)
    elif os.path.exists(p):
        os.remove(p)


for d in ("build/webobf", "build/core", "build/entry", "dist", "app/photosift/_webpack.py"):
    rm(d)

# 1. giao diện: làm rối + nhúng
run("node", "tools/obfuscate_web.mjs", "app/photosift/web", "build/webobf")
run(PY, "tools/pack_web.py", "build/webobf", "app/photosift/_webpack.py")

# 2. lõi sang mã máy
nk = [PY, "-m", "nuitka", "--module", "app/photosift", "--include-package=photosift",
      "--output-dir=build/core", "--remove-output", "--assume-yes-for-downloads", "--no-pyi-file",
      "--nofollow-imports", "--python-flag=no_docstrings", "--python-flag=no_asserts"]
if os.name == "nt":
    nk.append("--msvc=latest")
run(*nk)
ext = glob.glob(os.path.join(ROOT, "build", "core", "photosift*.pyd" if os.name == "nt" else "photosift*.so"))
if len(ext) != 1:
    sys.exit(f"Không thấy file lõi đã biên dịch: {ext}")
os.remove(os.path.join(ROOT, "app", "photosift", "_webpack.py"))   # không để bản giao diện nhúng nằm lại trong mã nguồn

entry_dir = os.path.join(ROOT, "build", "entry")
os.makedirs(entry_dir)
shutil.copy2(ext[0], entry_dir)
entry = "run.py" if TARGET == "win" else "mac_main.py"
shutil.copy2(os.path.join(ROOT, "app", entry), entry_dir)

# 3. đóng gói: PyInstaller không nhìn thấy import bên trong lõi đã biên dịch → khai báo đủ
HIDDEN = ["photosift", "cv2", "numpy", "rawpy", "PIL", "PIL.Image", "PIL.ImageOps", "pillow_heif", "sqlite3",
          "http.server", "xml.sax.saxutils", "concurrent.futures", "urllib.request", "urllib.error", "urllib.parse",
          "webbrowser", "secrets", "random", "string", "struct", "socket", "ctypes", "platform", "errno", "io",
          "shutil", "subprocess", "base64", "hashlib", "json", "datetime", "pathlib", "zlib", "email", "html",
          "ssl", "certifi", "onnxruntime"]
if os.name == "nt":
    HIDDEN += ["winreg", "ctypes.wintypes"]
args = [PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--paths", "build/entry",
        "--collect-all", "pillow_heif", "--collect-all", "onnxruntime", "--collect-binaries", "rawpy", "--collect-data", "certifi",
        "--exclude-module", "tkinter", "--exclude-module", "matplotlib", "--exclude-module", "scipy",
        "--exclude-module", "pandas"]
for h in HIDDEN:
    args += ["--hidden-import", h]
if TARGET == "win":
    args += ["--name", "PhotoSiftCore", f"build/entry/{entry}"]
else:
    app = os.environ.get("APP", "MThanglee CullCollage")
    args += ["--windowed", "--name", app, "--osx-bundle-identifier", "vn.mthanglee.cullcollage",
             "--icon", "build/mac/app.icns", "--add-data", f"app/models{SEP}models", "--add-data", f"version.json{SEP}.",
             "--collect-all", "webview", "--hidden-import", "webview",
             "--exclude-module", "PyQt5", "--exclude-module", "PyQt6", "--exclude-module", "PySide6", "--exclude-module", "gi",
             f"build/entry/{entry}"]
run(*args)

# kiểm tra: gói phát hành không được chứa mã nguồn / giao diện dạng chữ
leak = []
for base, _, files in os.walk(os.path.join(ROOT, "dist")):
    for f in files:
        if f.endswith((".html", ".py")) and ("photosift" in base or f in ("index.html", "layout.html", "shell.html")):
            leak.append(os.path.join(base, f))
if leak:
    sys.exit("Gói phát hành còn lộ mã nguồn / giao diện: " + ", ".join(leak[:5]))
print("OK: lõi đã biên dịch, giao diện đã nhúng, không lộ file nguồn")
