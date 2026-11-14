import os
import time

from core import dupes

MB = 1024 * 1024


def make(path, data, size=2 * MB, age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data * size)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


def roots(h):
    return [("图片", str(h / "Pictures")), ("文档", str(h / "Documents")), ("下载", str(h / "Downloads")),
            ("微信", str(h / "Documents" / "WeChat Files"))]


def test_finds_identical_and_picks_keeper_by_location(tmp_path):
    h = tmp_path
    make(h / "Downloads" / "IMG_1.jpg", b"a", age_days=1)
    make(h / "Pictures" / "旅行" / "海边.jpg", b"a", age_days=1)
    make(h / "Documents" / "WeChat Files" / "wx" / "微信图片.jpg", b"a", age_days=5)   # 最早，但在微信里
    make(h / "Downloads" / "other.jpg", b"b")                                          # 大小一样，内容不同
    gs = dupes.find(roots(h))
    assert len(gs) == 1
    g = gs[0]
    assert g.keeper.endswith("海边.jpg")                     # 图片里的那份留下
    assert sorted(os.path.basename(f.path) for f in g.copies) == ["IMG_1.jpg", "微信图片.jpg"]
    where = {os.path.basename(f.path): f.where for f in g.files}
    assert where["微信图片.jpg"].startswith("微信") and where["海边.jpg"] == "图片 › 旅行"


def test_same_size_different_middle_is_not_duplicate(tmp_path):
    a = make(tmp_path / "Downloads" / "a.bin", b"x", size=4 * MB)
    b = make(tmp_path / "Downloads" / "b.bin", b"x", size=4 * MB)
    with open(b, "r+b") as f:
        f.seek(2 * MB)
        f.write(b"Y")                                         # 开头结尾一样，中间不同
    assert dupes.find(roots(tmp_path)) == []


def test_hardlinks_are_not_duplicates(tmp_path):
    a = make(tmp_path / "Downloads" / "a.bin", b"q")
    os.link(a, tmp_path / "Downloads" / "a-link.bin")
    assert dupes.find(roots(tmp_path)) == []


def test_small_files_ignored_and_node_modules_skipped(tmp_path):
    make(tmp_path / "Downloads" / "s1.txt", b"t", size=100)
    make(tmp_path / "Downloads" / "s2.txt", b"t", size=100)
    make(tmp_path / "Documents" / "proj" / "node_modules" / "a.js", b"n")
    make(tmp_path / "Documents" / "proj" / "node_modules" / "b.js", b"n")
    assert dupes.find(roots(tmp_path)) == []


def test_keeper_ties_broken_by_age(tmp_path):
    make(tmp_path / "Downloads" / "new.zip", b"z", age_days=1)
    make(tmp_path / "Downloads" / "old.zip", b"z", age_days=100)
    g = dupes.find(roots(tmp_path))[0]
    assert g.keeper.endswith("old.zip")
