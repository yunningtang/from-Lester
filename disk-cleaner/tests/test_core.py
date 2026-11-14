import json
import os
import threading

import pytest

from core import cleaner, safety
from core.oplog import OpLog
from core.scanner import scan_large_files
from core.utils import human_size, parse_size

MB = 1024 * 1024


def make(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)  # 稀疏文件，不占真实空间
    return path


def test_human_and_parse_size():
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(3 * 1024 ** 3) == "3.0 GB"
    assert parse_size("100MB") == 100 * MB
    assert parse_size("1.5 GB") == int(1.5 * 1024 ** 3)
    assert parse_size("200") == 200 * MB


def test_scan_finds_large_sorted_and_is_read_only(tmp_path):
    make(tmp_path / "a.bin", 5 * MB)
    make(tmp_path / "sub" / "b.bin", 20 * MB)
    make(tmp_path / "sub" / "deep" / "c.bin", 12 * MB)
    make(tmp_path / "small.txt", 1000)
    before = sorted(p for p in tmp_path.rglob("*"))
    res = scan_large_files(str(tmp_path), min_size=10 * MB)
    assert [os.path.basename(f.path) for f in res.files] == ["b.bin", "c.bin"]
    assert res.progress.files == 4
    assert sorted(p for p in tmp_path.rglob("*")) == before


def test_scan_limit_keeps_biggest(tmp_path):
    for i in range(1, 6):
        make(tmp_path / f"{i}.bin", i * MB)
    res = scan_large_files(str(tmp_path), min_size=0, limit=2)
    assert [f.size for f in res.files] == [5 * MB, 4 * MB]


def test_scan_skips_protected_and_symlinks(tmp_path):
    make(tmp_path / "keep" / "x.bin", 2 * MB)
    make(tmp_path / "sys" / "y.bin", 2 * MB)
    outside = tmp_path.parent / (tmp_path.name + "_outside")
    make(outside / "z.bin", 2 * MB)
    try:
        os.symlink(outside, tmp_path / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    safety.add_protected(tmp_path / "sys")
    res = scan_large_files(str(tmp_path), min_size=MB)
    names = [os.path.basename(f.path) for f in res.files]
    assert names == ["x.bin"]


def test_scan_cancel(tmp_path):
    make(tmp_path / "a.bin", MB)
    ev = threading.Event()
    ev.set()
    res = scan_large_files(str(tmp_path), min_size=0, cancel=ev)
    assert res.cancelled and res.files == []


def test_safety_rules(tmp_path):
    assert safety.is_drive_root(os.path.abspath(os.sep))
    ok, _ = safety.can_delete(os.path.abspath(os.sep))
    assert not ok
    sysdir = r"C:\Windows\System32" if os.name == "nt" else "/usr/bin"
    assert safety.is_protected(sysdir)
    assert not safety.is_protected(tmp_path)
    # 前缀相同但不是子目录，不能误判
    safety.add_protected(tmp_path / "prot")
    assert safety.is_protected(tmp_path / "prot" / "a")
    assert not safety.is_protected(tmp_path / "protect_me_not")


def fake_bin(monkeypatch, tmp_path):
    """测试用回收站：把文件挪到临时目录里，记录挪了什么。"""
    import shutil
    from core import recycle
    bin_dir = tmp_path / "_bin"
    bin_dir.mkdir(exist_ok=True)
    moved = []
    def fake(p):
        moved.append(p)
        shutil.move(p, bin_dir / (str(len(moved)) + "_" + os.path.basename(p)))
    monkeypatch.setattr(recycle, "_recycle_other", fake)
    return moved


def test_move_to_trash_uses_send2trash_and_logs(tmp_path, monkeypatch):
    trashed = fake_bin(monkeypatch, tmp_path)
    f = make(tmp_path / "big.bin", 3 * MB)
    safety.add_protected(tmp_path / "locked")
    g = make(tmp_path / "locked" / "nope.bin", MB)
    log = OpLog(tmp_path / "logs")
    rep = cleaner.move_to_trash([str(f), str(g), str(tmp_path / "missing")], log=log)
    assert trashed == [str(f)]
    assert rep.trashed == 3 * MB
    assert sorted(p for p, _ in rep.failed) == sorted([str(g), str(tmp_path / "missing")])
    assert g.exists()
    recs = log.read_all()
    assert len(recs) == 3 and recs[0]["ok"] and not recs[1]["ok"]
    json.dumps(recs)


def test_no_permanent_delete_in_source():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    banned = ["os.remove(", "os.unlink(", "shutil.rmtree(", ".unlink(", "os.rmdir(", "send2trash("]
    for d in ("core", "ui"):
        for dirpath, _, files in os.walk(os.path.join(root, d)):
            for name in files:
                if name.endswith(".py") and name != "recycle.py":  # 只有 recycle.py 可以真正动文件
                    text = open(os.path.join(dirpath, name), encoding="utf-8").read()
                    for b in banned:
                        assert b not in text, f"{name} 包含永久删除调用 {b}"


def test_soft_protected_needs_safe_cache(tmp_path):
    from core import safety
    appdata = tmp_path / "AppData"
    cache = appdata / "SomeApp" / "Cache"
    f = make(cache / "blob.bin", 10)
    other = make(appdata / "SomeApp" / "settings.json", 10)
    safety._SOFT.append(safety._norm(appdata))
    try:
        assert not safety.can_delete(f)[0]
        safety.add_safe_root(cache)
        assert safety.can_delete(f)[0]
        assert not safety.can_delete(other)[0]   # 同一个程序的其他文件仍然受保护
        assert not safety.can_delete(cache)[0]   # 缓存目录本身不删
    finally:
        safety._SOFT.pop()


def test_cleanables_find_and_clean(tmp_path, monkeypatch):
    import time
    from core import cleanables
    from core.safety import SafeCache
    cache = tmp_path / "cache"
    make(cache / "a" / "x.bin", 2 * MB)
    make(cache / "b.bin", MB)
    dl = tmp_path / "dl"
    old = make(dl / "old.exe", MB)
    make(dl / "new.exe", MB)
    make(dl / "keep.pdf", MB)
    t = time.time() - 40 * 86400
    os.utime(old, (t, t))
    defs = [SafeCache("c", "缓存", (str(cache),)),
            SafeCache("i", "旧安装包", (str(dl),), patterns=("*.exe",), min_age_days=30)]
    found = cleanables.find_all(defs)
    assert [(c.key, c.size) for c in found] == [("c", 3 * MB), ("i", MB)]
    trashed = fake_bin(monkeypatch, tmp_path)
    rep = cleanables.clean(found, log=OpLog(tmp_path / "logs"))
    assert sorted(os.path.basename(p) for p in trashed) == ["a", "b.bin", "old.exe"]
    assert rep.trashed == 4 * MB


def test_measure_no_double_count(tmp_path):
    from core import space
    from core.space import Category
    docs = tmp_path / "Documents"
    make(docs / "a.bin", 5 * MB)
    make(docs / "WeChat" / "chat.bin", 3 * MB)
    make(docs / "cache" / "junk.bin", MB)
    defs = [Category("wechat", "微信", "user", [str(docs / "WeChat")]),
            Category("docs", "文档", "user", [str(docs)])]
    rep = space.measure(str(tmp_path), defs=defs, subtract=[(str(docs / "cache"), MB)])
    sizes = {c.key: c.size for c in rep.categories}
    assert sizes == {"wechat": 3 * MB, "docs": 5 * MB}
    keys = [b.key for b in rep.blocks(MB)]
    assert keys[-1] == "free" and "safe" in keys
