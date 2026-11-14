"""删除流程的安全测试：每一条规则一个测试。全部在临时文件夹里进行。"""
import os
import time

import pytest

from core import cleanables, cleaner, recycle, safety
from core.cleaner import Entry
from core.fs import is_cloud_placeholder, stamp
from core.oplog import OpLog
from core.safety import SafeCache

MB = 1024 * 1024


def make(path, size=1000, age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


@pytest.fixture
def fake_bin(monkeypatch, tmp_path):
    import shutil
    bin_dir = tmp_path / "_bin"
    bin_dir.mkdir()
    moved = []
    def fake(p):
        moved.append(p)
        shutil.move(p, bin_dir / f"{len(moved)}_{os.path.basename(p)}")
    monkeypatch.setattr(recycle, "_recycle_other", fake)
    return moved


@pytest.fixture
def lists(monkeypatch):
    """在测试里临时改保护名单，结束后自动还原。"""
    for name in ("_KEEP", "_CLOUD", "_EXTRA", "_EXTRA_SAFE", "_SOFT"):
        monkeypatch.setattr(safety, name, list(getattr(safety, name)))
    return safety


def log(tmp_path):
    return OpLog(tmp_path / "logs")


# ---------- 回收站：放不进去就不删 ----------

def test_refuses_drive_without_recycle_bin(tmp_path, monkeypatch, fake_bin):
    f = make(tmp_path / "a.bin")
    monkeypatch.setattr(recycle, "drive_type", lambda p: 2)  # U 盘
    plan = cleaner.preflight([str(f)])
    assert not plan.go and "U 盘" in plan.refused[0][1]
    assert cleaner.move_to_trash([str(f)], log=log(tmp_path)).moved == []
    assert f.exists() and fake_bin == []


def test_refuses_when_recycle_bin_is_off(tmp_path, monkeypatch, fake_bin):
    f = make(tmp_path / "a.bin")
    monkeypatch.setattr(recycle, "bin_settings", lambda p: (False, None))
    assert cleaner.move_to_trash([str(f)], log=log(tmp_path)).moved == []
    assert f.exists()


def test_refuses_file_bigger_than_recycle_bin(tmp_path, monkeypatch, fake_bin):
    big, small = make(tmp_path / "big.bin", 5 * MB), make(tmp_path / "small.bin", MB)
    monkeypatch.setattr(recycle, "bin_capacity", lambda p: 2 * MB)
    plan = cleaner.preflight([str(big), str(small)])
    assert [e.path for e in plan.go] == [str(small)]
    assert "回收站的容量" in plan.refused[0][1]


def test_warns_when_recycle_bin_will_overflow(tmp_path, monkeypatch):
    f = make(tmp_path / "a.bin", MB)
    monkeypatch.setattr(recycle, "bin_capacity", lambda p: 2 * MB)
    monkeypatch.setattr(recycle, "bin_used", lambda p: int(1.5 * MB))
    plan = cleaner.preflight([str(f)])
    assert plan.go and any("回收站快满了" in w for w in plan.warnings)


def test_always_says_space_comes_back_after_emptying(tmp_path):
    plan = cleaner.preflight([str(make(tmp_path / "a.bin"))])
    assert any("清空回收站以后" in w for w in plan.warnings)


def test_recycle_checks_file_really_left(tmp_path, monkeypatch):
    f = make(tmp_path / "a.bin")
    monkeypatch.setattr(recycle, "_recycle_other", lambda p: None)  # 假装成功，其实没动
    rep = cleaner.move_to_trash([str(f)], log=log(tmp_path))
    assert rep.moved == [] and "还在原处" in rep.failed[0][1]


# ---------- 重要文件夹、OneDrive、链接 ----------

def test_keep_roots_and_their_parents(tmp_path, lists):
    home = tmp_path / "Users" / "me"
    dl = home / "Downloads"
    f = make(dl / "a.zip")
    lists._KEEP += [safety._norm(home), safety._norm(dl)]
    assert not safety.can_delete(dl)[0]                 # 文件夹本身不行
    assert not safety.can_delete(home)[0]
    assert not safety.can_delete(tmp_path / "Users")[0]  # 上级也不行
    assert safety.can_delete(f)[0]                      # 里面的文件可以


def test_onedrive_is_never_deleted(tmp_path, lists):
    od = tmp_path / "OneDrive"
    f = make(od / "photo.jpg")
    lists._CLOUD.append(safety._norm(od))
    ok, why = safety.can_delete(f)
    assert not ok and "OneDrive" in why


def test_links_are_not_deleted(tmp_path):
    target = make(tmp_path / "real.txt")
    link = tmp_path / "link.txt"
    os.symlink(target, link)
    ok, why = safety.can_delete(link)
    assert not ok and "链接" in why


def test_link_into_protected_folder_is_refused(tmp_path, lists):
    prot = tmp_path / "prot"
    make(prot / "secret.txt")
    lists._EXTRA.append(safety._norm(prot))
    os.symlink(prot, tmp_path / "door")
    # 通过链接指进受保护目录的路径：真实路径被保护，所以拒绝
    assert not safety.can_delete(tmp_path / "door" / "secret.txt")[0]


# ---------- 缓存目录必须像缓存目录 ----------

def test_temp_pointing_at_home_is_ignored(tmp_path, lists):
    home = tmp_path / "me"
    make(home / "thesis.docx", age_days=10)
    lists._KEEP.append(safety._norm(home))
    bad = SafeCache("temp", "临时文件", (str(home),), min_age_days=1)
    assert safety.safe_cache_roots(bad) == []
    assert cleanables.find_one(bad).items == []


def test_temp_must_be_named_temp(tmp_path):
    d = tmp_path / "notes"
    make(d / "x.txt", age_days=10)
    assert safety.safe_cache_roots(SafeCache("temp", "临时文件", (str(d),))) == []
    t = tmp_path / "Temp"
    make(t / "x.tmp", age_days=10)
    assert safety.safe_cache_roots(SafeCache("temp", "临时文件", (str(t),))) == [safety._norm(t)]


def test_cache_root_cannot_be_parent_of_keep_root(tmp_path, lists):
    lists._KEEP.append(safety._norm(tmp_path / "me" / "Documents"))
    assert safety.safe_cache_roots(SafeCache("x", "x", (str(tmp_path / "me"),))) == []


def test_drive_root_is_never_a_cache():
    assert safety.safe_cache_roots(SafeCache("x", "x", (os.path.abspath(os.sep),))) == []


def test_installers_only_match_installer_names():
    inst = next(c for c in safety.SAFE_CACHES if c.key == "installers")
    assert inst.default is False
    names = ["portable-tool.exe", "Setup_v2.exe", "foo-installer.exe", "x.msi"]
    hits = [n for n in names if cleanables._matches(inst, n, 0, time.time())]
    assert hits == ["Setup_v2.exe", "foo-installer.exe", "x.msi"]


# ---------- 扫描之后有变化，就不动 ----------

def test_changed_file_is_not_deleted(tmp_path, fake_bin):
    f = make(tmp_path / "movie.mkv", MB)
    e = Entry(str(f), MB, stamp(str(f)))
    with open(f, "ab") as h:
        h.write(b"new")
    rep = cleaner.move_to_trash([e], log=log(tmp_path))
    assert rep.moved == [] and "改动过" in rep.failed[0][1] and f.exists()


def test_execute_rechecks_after_confirm(tmp_path, lists, fake_bin):
    f = make(tmp_path / "a.bin")
    plan = cleaner.preflight([str(f)])
    assert plan.go
    lists._EXTRA.append(safety._norm(tmp_path))   # 确认之后、执行之前，它变成了受保护的
    rep = cleaner.execute(plan, log=log(tmp_path))
    assert rep.moved == [] and f.exists()


def test_cache_item_used_after_scan_is_skipped(tmp_path, fake_bin):
    t = tmp_path / "Temp"
    old = make(t / "old.tmp", age_days=5)
    cache = SafeCache("temp", "临时文件", (str(t),), min_age_days=1)
    found = cleanables.find_all([cache])
    os.utime(old, None)                           # 扫描之后被程序用了
    rep = cleanables.clean(found, log=log(tmp_path))
    assert rep.moved == [] and old.exists()


def test_nested_selection_moves_parent_once(tmp_path, fake_bin):
    d = tmp_path / "proj" / "node_modules"
    make(d / "a" / "x.js")
    rep = cleaner.move_to_trash([str(d / "a"), str(d), str(d / "a" / "x.js")], log=log(tmp_path))
    assert fake_bin == [str(d)] and rep.failed == []


# ---------- 日志写不进去也不能停在一半 ----------

def test_log_failure_does_not_stop_cleaning(tmp_path, fake_bin):
    blocker = make(tmp_path / "not_a_dir")             # 日志目录被一个文件占着
    files = [make(tmp_path / f"{i}.bin") for i in range(3)]
    lg = OpLog(blocker / "logs")
    rep = cleaner.move_to_trash([str(f) for f in files], log=lg)
    assert len(rep.moved) == 3 and len(lg.unsaved) == 3


def test_one_failure_does_not_stop_others(tmp_path, monkeypatch):
    import shutil
    files = [make(tmp_path / f"{i}.bin") for i in range(3)]
    def flaky(p):
        if p.endswith("1.bin"):
            raise OSError(32, "正在使用")
        shutil.move(p, p + ".gone")
    monkeypatch.setattr(recycle, "_recycle_other", flaky)
    rep = cleaner.move_to_trash([str(f) for f in files], log=log(tmp_path))
    assert len(rep.moved) == 2 and len(rep.failed) == 1


# ---------- OneDrive 占位文件不算占用 ----------

def test_cloud_placeholder_detection():
    class St:
        st_file_attributes = 0x400000
    class Local:
        st_file_attributes = 0x20
    assert is_cloud_placeholder(St()) and not is_cloud_placeholder(Local())
