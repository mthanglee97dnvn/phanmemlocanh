import os
from photosift.xmpsync import merge_xmp, read_sidecar, sidecar, write_atomic

PM = (b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
      b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
      b'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmp:Rating="2">'
      b'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">Le vu quy</rdf:li></rdf:Alt></dc:description>'
      b'</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>')


def read_back(data, tmp_path):
    (tmp_path / "R.xmp").write_bytes(data)
    r, lab, _ = read_sidecar(str(tmp_path / "R.JPG"))
    return r, lab


def test_merge_attr_keeps_rest():
    out = merge_xmp(PM, 5, "")
    assert b'xmp:Rating="5"' in out and b'xmp:Rating="2"' not in out and b"Le vu quy" in out
    assert out.count(b"xmp:Rating") == 1


def test_merge_element_form():
    src = PM.replace(b' xmp:Rating="2">', b'><xmp:Rating>2</xmp:Rating>')
    out = merge_xmp(src, -1, "")
    assert b"<xmp:Rating>-1</xmp:Rating>" in out and out.count(b"xmp:Rating") == 2


def test_merge_label_add_replace_remove():
    a = merge_xmp(PM, 3, "red"); assert b'xmp:Label="Red"' in a
    b = merge_xmp(a, 3, "green"); assert b'xmp:Label="Green"' in b and b"Red" not in b
    c = merge_xmp(b, 3, ""); assert b"xmp:Label" not in c and b"Le vu quy" in c


def test_merge_label_element_form():
    src = PM.replace(b'">\n', b'">').replace(b'xmp:Rating="2">', b'xmp:Rating="2"><xmp:Label>Winner</xmp:Label>')
    out = merge_xmp(src, 2, "blue")
    assert b"<xmp:Label>Blue</xmp:Label>" in out and b"Winner" not in out


def test_merge_new_and_nothing(tmp_path):
    assert merge_xmp(None, 0, "") is None
    n = merge_xmp(None, 4, "blue"); assert b'xmp:Rating="4"' in n and b'xmp:Label="Blue"' in n
    assert read_back(n, tmp_path) == (4, "blue")
    assert read_back(merge_xmp(None, -1, ""), tmp_path) == (-1, None)


def test_merge_missing_rating_inserted():
    src = PM.replace(b' xmp:Rating="2"', b"")
    out = merge_xmp(src, 3, "")
    assert b'xmp:Rating="3"' in out and b"Le vu quy" in out


def test_merge_missing_xmp_namespace():
    src = PM.replace(b' xmlns:xmp="http://ns.adobe.com/xap/1.0/"', b"").replace(b' xmp:Rating="2"', b"")
    out = merge_xmp(src, 1, "")
    assert b'xmlns:xmp="http://ns.adobe.com/xap/1.0/"' in out and b'xmp:Rating="1"' in out


def test_sidecar_prefers_existing_case(tmp_path):
    img = tmp_path / "IMG_1.ARW"; img.write_bytes(b"x"); (tmp_path / "IMG_1.XMP").write_bytes(PM)
    p, ex = sidecar(str(img))
    assert ex and os.path.basename(p) == "IMG_1.XMP"
    assert sidecar(str(tmp_path / "IMG_2.JPG")) == (str(tmp_path / "IMG_2.xmp"), False)


def test_read_unknown_label(tmp_path):
    (tmp_path / "A.xmp").write_bytes(merge_xmp(PM, 3, "").replace(b"xmp:Rating", b'xmp:Label="Winner" xmp:Rating', 1))
    r, lab, mt = read_sidecar(str(tmp_path / "A.JPG"))
    assert (r, lab) == (3, None) and mt


def test_read_missing(tmp_path):
    assert read_sidecar(str(tmp_path / "none.JPG")) == (None, None, None)


def test_write_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "B.xmp"; write_atomic(str(p), b"abc")
    assert p.read_bytes() == b"abc" and not list(tmp_path.glob("*.tmp"))
