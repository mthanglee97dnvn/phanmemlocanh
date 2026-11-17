import os

from photosift.update import _changes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD = open(os.path.join(ROOT, "tests", "data", "whatsnew_1_2.txt"), encoding="utf-8").read() + "\n<!-- src:abc -->"


def R(t, b):
    return {"tag_name": t, "body": b}


def test_old_long_body_trimmed_to_4_titles():
    c = _changes([R("v1.2", OLD)], "1.1.100", "1.2")
    assert c[0]["ver"] == "1.2" and len(c[0]["lines"]) == 4
    assert c[0]["lines"][0].startswith("🖼️")
    assert not any(l.startswith(("•", "Cảm ơn", "©", "<!--")) for x in c for l in x["lines"])


def test_only_newer_than_cur_newest_first_and_fixes_merged():
    rels = [R("v1.2.1", "🍎 Sửa nhập ảnh Mac\r\n🔄 Sửa lỗi ảnh dọc\r\nSửa lỗi và chạy ổn định hơn."),
            R("v1.2.2", "Sửa lỗi và chạy ổn định hơn."),
            R("v1.2.3", "🗂 Đếm cặp RAW–JPEG"), R("v1.2", OLD)]
    c = _changes(rels, "1.2", "1.2.3")
    assert [x["ver"] for x in c] == ["1.2.3", "1.2.1", ""]
    assert c[1]["lines"] == ["🍎 Sửa nhập ảnh Mac", "🔄 Sửa lỗi ảnh dọc"]
    assert c[-1]["lines"] == ["Sửa lỗi và chạy ổn định hơn."]


def test_cap_six_versions():
    rels = [R(f"v1.3.{i}", f"✨ Tính năng {i}") for i in range(1, 9)]
    c = _changes(rels, "1.2", "1.3.8")
    assert len([x for x in c if x["ver"]]) == 6 and c[-1]["lines"] == ["…và 2 bản trước nữa"]
    assert c[0]["ver"] == "1.3.8"


def test_up_to_date_is_empty():
    assert _changes([R("v1.2.2", "✨ x")], "1.2.2", "1.2.2") == []


def test_markdown_lines_not_highlights():
    body = "## Có gì mới\n- gạch đầu dòng\n* sao\n**Full Changelog**: v1...v2\n> trích\n[link](x)\n(chú thích)\n🍎 Sửa nhập ảnh Mac"
    assert _changes([R("v1.2.5", body)], "1.2.4", "1.2.5") == [{"ver": "1.2.5", "lines": ["🍎 Sửa nhập ảnh Mac"]}]
