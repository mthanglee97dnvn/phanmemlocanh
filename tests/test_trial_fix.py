"""Sửa sau đợt soát cuối nhánh dung-thu-3-ngay."""
import json
import os
import re

from test_trial import EXPIRED, L, MACH, env, make_key  # noqa: F401  (fixture env)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_wrangler_keeps_workers_dev():   # C1: thêm routes mà không có workers_dev=true → webhook SePay chết
    s = open(os.path.join(ROOT, "sales-worker", "wrangler.toml"), encoding="utf-8").read()
    assert re.search(r"(?m)^workers_dev\s*=\s*true\s*$", s)


def test_server_day_sets_seen(env):      # I3a: đồng hồ máy lùi lúc nhận key → seen theo ngày máy chủ
    worker, _ = env
    day = L.today_num()
    worker({"ok": True, "key": make_key(day + 1, day + 3), "today": day + 3})
    lic = L.License(); lic.start_trial()
    assert json.loads(L.FILE.read_text(encoding="utf-8"))["seen"] == day + 3
    assert not lic.ok()   # đồng hồ máy lùi 3 ngày so với máy chủ → bị chặn


def test_trial_before_issued_rejected(env):   # I3b: đồng hồ lùi xa trước ngày cấp key thử
    day = L.today_num()
    lic = L.License()
    r = lic.activate(make_key(day + 5, day + 7))
    assert r["ok"] is False and "Đồng hồ" in r["reason"]


def test_paid_key_issued_future_still_ok(env):   # key trả tiền không bị luật trên ảnh hưởng
    day = L.today_num()
    assert L.License().activate(make_key(day + 5, L.PERMANENT, serial=0))["ok"]


def test_remove_keeps_marker_no_new_trial(env):   # M6: Gỡ key → không tự xin thử lại
    worker, calls = env
    day = L.today_num()
    worker({"ok": True, "key": make_key(day, day + 2)})
    lic = L.License(); lic.start_trial(); lic.remove()
    assert lic.has_key() and not lic.ok()
    assert lic.start_trial()["ok"] is False and len(calls) == 1


def test_concurrent_start_trial_single_call(env):   # M5
    import threading
    worker, calls = env
    day = L.today_num()
    worker({"ok": True, "key": make_key(day, day + 2)})
    lic = L.License(); res = []
    th = [threading.Thread(target=lambda: res.append(lic.start_trial())) for _ in range(4)]
    [t.start() for t in th]; [t.join() for t in th]
    assert len(calls) == 1 and sum(1 for r in res if r.get("ok")) == 1 and lic.ok()
