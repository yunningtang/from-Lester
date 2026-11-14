"""移动和撤销：同盘改名、跨盘复制核对、同名、各种拒绝、撤销不覆盖。全部在临时文件夹里。"""
import os
import shutil

import pytest

from core import mover, safety
from core.fs import stamp
from core.oplog import OpLog

MB = 1024 * 1024


def make(path, size=1000, data=b"a"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data * size)
    return path


@pytest.fixture
def log(tmp_path):
    return OpLog(tmp_path / "logs")


@pytest.fixture
def lists(monkeypatch):
    for name in ("_KEEP", "_CLOUD", "_EXTRA", "_SOFT"):
        monkeypatch.setattr(safety, name, list(getattr(safety, name)))
    return safety


def test_same_volume_move_and_undo(tmp_path, log):
    a = make(tmp_path / "Downloads" / "a.zip", 100)
    dst = tmp_path / "Downloads" / "归档" / "2024-05" / "a.zip"
    plan = mover.plan_moves([(str(a), str(dst))])
    rep = mover.execute_moves(plan, log)
    assert rep.moved == [(str(a), str(dst))] and dst.exists() and not a.exists()
    assert mover.undoable(log, rep.batch)
    u = mover.execute_undo(mover.plan_undo(log, rep.batch), rep.batch, log)
    assert len(u.moved) == 1 and a.exists() and not dst.exists()
    assert not mover.undoable(log, rep.batch)          # 撤销过一次，不能再撤


def test_name_collision_gets_new_name(tmp_path, log):
    a = make(tmp_path / "in" / "x.jpg", 10, b"1")
    b = make(tmp_path / "in2" / "x.jpg", 10, b"2")
    make(tmp_path / "out" / "x.jpg", 10, b"0")         # 目标已经有一个
    plan = mover.plan_moves([(str(a), str(tmp_path / "out" / "x.jpg")), (str(b), str(tmp_path / "out" / "x.jpg"))])
    dsts = sorted(os.path.basename(m.dst) for m in plan.go)
    assert dsts == ["x (2).jpg", "x (3).jpg"]
    mover.execute_moves(plan, log)
    assert (tmp_path / "out" / "x.jpg").read_bytes() == b"0" * 10   # 原有的没被覆盖


def test_cross_volume_copy_verifies_then_removes_source(tmp_path, log, monkeypatch):
    monkeypatch.setattr(mover, "same_volume", lambda a, b: False)
    f = make(tmp_path / "C" / "movie.mkv", 3 * MB, b"m")
    d = tmp_path / "C" / "trip"
    make(d / "1.jpg", 1000, b"1"); make(d / "sub" / "2.jpg", 1000, b"2")
    plan = mover.plan_moves([(str(f), str(tmp_path / "D" / "movie.mkv")), (str(d), str(tmp_path / "D" / "trip"))])
    rep = mover.execute_moves(plan, log)
    assert len(rep.moved) == 2 and not f.exists() and not d.exists()
    assert (tmp_path / "D" / "movie.mkv").read_bytes() == b"m" * 3 * MB
    assert (tmp_path / "D" / "trip" / "sub" / "2.jpg").read_bytes() == b"2" * 1000
    assert not list((tmp_path / "D").glob("*" + mover.PART))


def test_cross_volume_mismatch_keeps_source(tmp_path, log, monkeypatch):
    monkeypatch.setattr(mover, "same_volume", lambda a, b: False)
    f = make(tmp_path / "C" / "a.bin", 1000, b"z")
    real_open = open
    def corrupting_copy(src, tmp, cancel):
        shutil.copyfile(src, tmp)
        with real_open(tmp, "r+b") as h:
            h.write(b"X")                               # 模拟写坏
        raise OSError(0, "复制后核对不一致")
    monkeypatch.setattr(mover, "_copy_file_verified", corrupting_copy)
    rep = mover.execute_moves(mover.plan_moves([(str(f), str(tmp_path / "D" / "a.bin"))]), log)
    assert rep.moved == [] and "不一致" in rep.failed[0][1]
    assert f.read_bytes() == b"z" * 1000                 # 原件完好
    assert not (tmp_path / "D" / "a.bin").exists() and not (tmp_path / "D" / ("a.bin" + mover.PART)).exists()


def test_cross_volume_refuses_when_target_full(tmp_path, log, monkeypatch):
    monkeypatch.setattr(mover, "same_volume", lambda a, b: False)
    f = make(tmp_path / "C" / "a.bin", 1000)
    monkeypatch.setattr(mover.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 5, 500))
    plan = mover.plan_moves([(str(f), str(tmp_path / "D" / "a.bin"))])
    assert not plan.go and "空间不够" in plan.refused[0][1]


def test_refuses_protected_cloud_and_keep_roots(tmp_path, lists, log):
    prot, cloud, home = tmp_path / "sys", tmp_path / "OneDrive", tmp_path / "me"
    make(prot / "x.dll"); make(cloud / "y.jpg"); make(home / "Downloads" / "z.zip")
    lists._EXTRA.append(safety._norm(prot)); lists._CLOUD.append(safety._norm(cloud))
    lists._KEEP.append(safety._norm(home / "Downloads"))
    plan = mover.plan_moves([
        (str(prot / "x.dll"), str(tmp_path / "out" / "x.dll")),           # 系统文件不动
        (str(cloud / "y.jpg"), str(tmp_path / "out" / "y.jpg")),           # OneDrive 不动
        (str(home / "Downloads"), str(tmp_path / "out" / "Downloads")),    # 个人文件夹本身不动
        (str(home / "Downloads" / "z.zip"), str(cloud / "z.zip")),         # 不往 OneDrive 里放
        (str(home / "Downloads" / "z.zip"), str(prot / "z.zip")),          # 不往系统目录放
    ])
    assert plan.go == [] and len(plan.refused) == 5                       # 每一项都有自己的原因


def test_refuses_moving_folder_into_itself(tmp_path):
    d = tmp_path / "a"
    make(d / "f.txt")
    plan = mover.plan_moves([(str(d), str(d / "归档" / "a"))])
    assert not plan.go and "自己里面" in plan.refused[0][1]


def test_file_changed_after_plan_is_skipped(tmp_path, log):
    f = make(tmp_path / "a.txt", 10)
    plan = mover.plan_moves([(str(f), str(tmp_path / "b" / "a.txt"))], stamps={str(f): stamp(str(f))})
    f.write_bytes(b"changed!")
    rep = mover.execute_moves(plan, log)
    assert rep.moved == [] and f.exists()


def test_undo_never_overwrites(tmp_path, log):
    a = make(tmp_path / "x" / "a.txt", 10, b"o")
    rep = mover.execute_moves(mover.plan_moves([(str(a), str(tmp_path / "y" / "a.txt"))]), log)
    make(tmp_path / "x" / "a.txt", 10, b"n")            # 原位置又出现了新文件
    plan = mover.plan_undo(log, rep.batch)
    assert not plan.go and "不覆盖" in plan.refused[0][1]
    assert (tmp_path / "x" / "a.txt").read_bytes() == b"n" * 10


def test_links_are_not_moved(tmp_path, log):
    t = make(tmp_path / "real.txt")
    os.symlink(t, tmp_path / "link.txt")
    plan = mover.plan_moves([(str(tmp_path / "link.txt"), str(tmp_path / "o" / "link.txt"))])
    assert not plan.go
