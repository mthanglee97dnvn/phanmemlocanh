T0 = 1_790_000_000.0


def test_ver_changes_on_rating(lib_with):
    L, ids = lib_with([("A", T0), ("A", T0 + 1)])
    v1 = L.photos_ver()["ver"]
    assert L.photos_ver()["ver"] == v1          # gọi lại không đổi gì → giữ nguyên
    L.set_rating([ids[0]], 3)
    assert L.photos_ver()["ver"] != v1
