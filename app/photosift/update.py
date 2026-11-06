"""Cập nhật app trong một nút bấm: hỏi GitHub Releases của kho phát hành, tải file cài rồi chạy nó ở chế độ cập nhật.

version.json do tools/package_app.py ghi lúc build trên GitHub, gồm số phiên bản và tên kho, nên không cần sửa tay.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__
from .db import HOME

API = "https://api.github.com"
AGENT = "MThanglee-CullCollage-updater"
DIR = HOME / "update"


def build_info() -> dict:
    try:
        d = json.loads((Path(os.environ.get("PHOTOSIFT_APPDIR", ".")) / "version.json").read_text(encoding="utf-8"))
        return dict(version=str(d.get("version") or __version__), repo=str(d.get("repo") or ""))
    except (OSError, ValueError):
        return dict(version=__version__, repo="")


def _key(v: str):
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        parts.append(int(p) if p.isdigit() else 0)
    return tuple(parts)


class Updater:
    def __init__(self):
        self.info = build_info()
        self.lock = threading.Lock()
        self.last = None
        self.when = 0.0
        self.state = dict(state="idle", got=0, total=0, error="")
        self.file = None

    def _get(self, url: str, timeout=15):
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=timeout)

    def check(self, force=False) -> dict:
        cur, repo = self.info["version"], self.info["repo"]
        base = dict(current=cur, available=False, latest=cur, notes="", size=0, error="")
        if not repo:
            return dict(base, error="Bản này chưa gắn nơi cập nhật.")
        with self.lock:
            if self.last and not force and time.time() - self.when < 3600:
                return self.last
        try:
            with self._get(f"{API}/repos/{repo}/releases/latest") as r:
                rel = json.loads(r.read())
            prefix = f"https://github.com/{repo}/releases/download/"
            asset = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".exe")
                          and a["browser_download_url"].startswith(prefix)), None)
            tag = str(rel.get("tag_name", "")).lstrip("vV")
            out = dict(base, latest=tag or cur, notes=str(rel.get("body") or "")[:2000])
            if asset and tag and _key(tag) > _key(cur):
                out.update(available=True, size=asset.get("size", 0), asset=asset["browser_download_url"],
                           name=os.path.basename(asset["name"]), digest=str(asset.get("digest") or ""))
        except Exception as e:  # noqa: BLE001  mất mạng hay GitHub lỗi không được ảnh hưởng tới app
            print("update check:", e)
            return dict(base, error="Chưa kiểm tra được. Hãy kiểm tra mạng rồi thử lại.")
        with self.lock:
            self.last, self.when = out, time.time()
        return out

    def public(self, r: dict) -> dict:
        return {k: v for k, v in r.items() if k in ("current", "available", "latest", "notes", "size", "error")}

    def start(self) -> dict:
        r = self.check()
        if not r.get("available"):
            return dict(error="Bạn đang dùng bản mới nhất.")
        with self.lock:
            if self.state["state"] == "downloading":
                return dict(ok=True)
            self.state = dict(state="downloading", got=0, total=r["size"], error="")
        threading.Thread(target=self._download, args=(r,), daemon=True).start()
        return dict(ok=True)

    def _download(self, r: dict):
        DIR.mkdir(parents=True, exist_ok=True)
        part = DIR / (r["name"] + ".part")
        try:
            h = hashlib.sha256()
            with self._get(r["asset"], 60) as src, open(part, "wb") as out:
                while True:
                    b = src.read(1 << 18)
                    if not b:
                        break
                    out.write(b)
                    h.update(b)
                    self.state["got"] += len(b)
            if r["size"] and part.stat().st_size != r["size"]:
                raise ValueError("thiếu dữ liệu")
            d = r["digest"]
            if d.startswith("sha256:") and d[7:].lower() != h.hexdigest():
                raise ValueError("file tải về không khớp")
            final = DIR / r["name"]
            os.replace(part, final)
            self.file = final
            self.state["state"] = "ready"
        except Exception as e:  # noqa: BLE001
            print("update download:", e)
            part.unlink(missing_ok=True)
            self.state.update(state="error", error="Tải bản mới không thành công. Hãy thử lại.")

    def install(self) -> dict:
        """Chạy file cài ở chế độ cập nhật. Người gọi phải tắt máy chủ ngay sau đó."""
        d = os.environ.get("PHOTOSIFT_APPDIR", "")
        if not self.file or not self.file.exists() or not d:
            return dict(error="Chưa có file cài để chạy.")
        self._spawn([str(self.file), "--update-dir", d])
        return dict(ok=True)

    @staticmethod
    def _spawn(args):
        subprocess.Popen(args, close_fds=True, creationflags=0x00000208 if os.name == "nt" else 0)
