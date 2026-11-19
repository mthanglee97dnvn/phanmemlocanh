"""Dùng thử tự động 3 ngày: app xin key thử từ Worker bán hàng (tests chạy offline, Worker giả)."""
import base64
import io
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

import photosift.license as L

PRIV = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
PUB = PRIV.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
MACH = bytes([9, 8, 7, 6, 5, 4, 3, 2])
EXPIRED = "Đã hết 3 ngày dùng thử — mua bản quyền vĩnh viễn 500.000đ để dùng tiếp"
OFFLINE = "Cần kết nối mạng để bắt đầu dùng thử 3 ngày"


def make_key(issued, exp, serial=0x54, mach=MACH, priv=PRIV):
    body = bytes([1, serial]) + issued.to_bytes(2, "big") + exp.to_bytes(2, "big") + mach
    sig = priv.sign(b"MTCC1" + body)
    return "MTCC-" + base64.b32encode(body + sig).decode().rstrip("=")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "PUB_HEX", "")
    monkeypatch.setattr(L, "SALES_PUB_HEX", PUB)
    monkeypatch.setattr(L, "HOME", tmp_path)
    monkeypatch.setattr(L, "FILE", tmp_path / "license.json")
    monkeypatch.setattr(L, "REVOKED_FILE", tmp_path / "revoked.txt")
    monkeypatch.setattr(L, "machine_bytes", lambda: MACH)
    calls = []

    def worker(reply):
        def urlopen(req, timeout=15):
            calls.append(json.loads(req.data.decode()))
            if isinstance(reply, Exception):
                raise reply
            return io.BytesIO(reply if isinstance(reply, bytes) else json.dumps(reply).encode())
        monkeypatch.setattr(L.net, "urlopen", urlopen)
    return worker, calls


def test_trial_activates(env):
    worker, calls = env
    day = L.today_num()
    worker({"ok": True, "key": make_key(day, day + 2)})
    lic = L.License()
    assert not lic.ok() and not lic.has_key()
    r = lic.start_trial()
    assert r["ok"] and lic.ok() and lic.has_key()
    assert calls[0]["machine"] == L.machine_code() and calls[0]["day"] == day


def test_trial_flag_and_days_left(env):
    worker, _ = env
    day = L.today_num()
    worker({"ok": True, "key": make_key(day, day + 2)})
    lic = L.License(); lic.start_trial()
    i = lic.info()
    assert i["trial"] is True and i["days_left"] == 2 and i["has_key"] is True and not i["permanent"]


def test_permanent_not_trial(env):
    worker, _ = env
    lic = L.License()
    assert lic.activate(make_key(L.today_num(), L.PERMANENT, serial=0))["ok"]
    assert lic.info()["trial"] is False


def test_offline_message(env):
    worker, _ = env
    worker(OSError("no network"))
    lic = L.License(); r = lic.start_trial()
    assert r == dict(ok=False, reason=OFFLINE, offline=True) and not lic.has_key()


@pytest.mark.parametrize("reply", [b"<html>404</html>", {"ok": False, "error": "trial not configured"}, {"ok": True}])
def test_worker_html_or_error_is_offline(env, reply):
    worker, _ = env
    worker(reply)
    r = L.License().start_trial()
    assert r["ok"] is False and r["reason"] == OFFLINE


def test_bad_signature_rejected(env):
    worker, _ = env
    other = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    worker({"ok": True, "key": make_key(L.today_num(), L.today_num() + 2, priv=other)})
    lic = L.License(); r = lic.start_trial()
    assert r["ok"] is False and not lic.has_key()


def test_wrong_machine_rejected(env):
    worker, _ = env
    worker({"ok": True, "key": make_key(L.today_num(), L.today_num() + 2, mach=bytes(8 * [1]))})
    lic = L.License(); assert lic.start_trial()["ok"] is False and not lic.has_key()


def test_has_key_never_calls_network(env):
    worker, calls = env
    day = L.today_num()
    L.FILE.write_text(json.dumps(dict(key=make_key(day - 10, day - 8), seen=day)), encoding="utf-8")   # key thử cũ đã hết hạn
    lic = L.License()
    worker({"ok": True, "key": make_key(day, day + 2)})
    r = lic.start_trial()
    assert r["ok"] is False and calls == [] and not lic.ok()


def test_expired_trial_reason(env):
    day = L.today_num()
    L.FILE.write_text(json.dumps(dict(key=make_key(day - 5, day - 3), seen=day)), encoding="utf-8")
    i = L.License().info()
    assert i["ok"] is False and i["expired"] is True and i["reason"] == EXPIRED and i["has_key"] is True


def test_expired_paid_key_reason_unchanged(env):
    day = L.today_num()
    L.FILE.write_text(json.dumps(dict(key=make_key(day - 40, day - 3, serial=0), seen=day)), encoding="utf-8")
    assert L.License().info()["reason"].startswith("Key đã hết hạn")


def test_day4_locked(env, monkeypatch):
    worker, _ = env
    day = L.today_num()
    worker({"ok": True, "key": make_key(day, day + 2)})
    lic = L.License(); lic.start_trial()
    monkeypatch.setattr(L, "today_num", lambda: day + 2)
    lic._day0 = 0; assert lic.ok()          # ngày thứ 3 vẫn dùng
    monkeypatch.setattr(L, "today_num", lambda: day + 3)
    lic._day0 = 0; assert not lic.ok()      # ngày thứ 4 khoá
