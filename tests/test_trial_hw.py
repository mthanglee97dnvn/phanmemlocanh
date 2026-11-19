"""Key dùng thử gắn mã phần cứng (không đổi khi sửa MachineGuid trong Registry)."""
import json

import photosift.license as L
from test_trial import MACH, env, make_key  # noqa: F401

HW = bytes([7, 7, 7, 7, 1, 2, 3, 4])


def test_trial_key_bound_to_hw(env, monkeypatch):
    worker, calls = env
    monkeypatch.setattr(L, "hw_bytes", lambda: HW)
    day = L.today_num()
    worker({"ok": True, "key": make_key(day, day + 2, mach=HW)})
    lic = L.License(); assert lic.start_trial()["ok"] and lic.ok()
    assert calls[0]["hw"] == L.hw_code() and calls[0]["machine"] == L.machine_code()


def test_trial_key_with_machine_code_rejected(env, monkeypatch):
    monkeypatch.setattr(L, "hw_bytes", lambda: HW)
    day = L.today_num()
    assert L.License().activate(make_key(day, day + 2, mach=MACH))["ok"] is False


def test_machineguid_edit_does_not_revive(env, monkeypatch):
    """Sửa MachineGuid: mã máy đổi nhưng mã phần cứng giữ → key thử cũ vẫn là của máy này (và vẫn hết hạn)."""
    worker, _ = env
    monkeypatch.setattr(L, "hw_bytes", lambda: HW)
    day = L.today_num()
    old = make_key(day - 5, day - 3, mach=HW)
    monkeypatch.setattr(L, "machine_bytes", lambda: bytes(8 * [5]))   # MachineGuid mới
    worker({"ok": True, "key": old, "again": True})                    # máy chủ trả lại key cũ theo mã phần cứng
    lic = L.License(); r = lic.start_trial()
    assert r["ok"] is False and r.get("expired") and not lic.ok()


def test_paid_key_still_machine_bound(env, monkeypatch):
    monkeypatch.setattr(L, "hw_bytes", lambda: HW)
    assert L.License().activate(make_key(L.today_num(), L.PERMANENT, serial=0, mach=MACH))["ok"]
    assert L.License().activate(make_key(L.today_num(), L.PERMANENT, serial=0, mach=HW))["ok"] is False


def test_hw_ids_windows(monkeypatch):
    monkeypatch.setattr(L, "_hw_ids", lambda: ["uuid-1", "vol-2"])
    L._HW_CACHE.clear()
    a = L.hw_bytes()
    monkeypatch.setattr(L, "_hw_ids", lambda: ["uuid-1", "vol-3"])
    L._HW_CACHE.clear()
    assert len(a) == 8 and a != L.hw_bytes()


def test_hw_fallback_to_machine(monkeypatch):
    monkeypatch.setattr(L, "_hw_ids", lambda: [])
    monkeypatch.setattr(L, "machine_bytes", lambda: MACH)
    L._HW_CACHE.clear()
    assert L.hw_bytes() == MACH
