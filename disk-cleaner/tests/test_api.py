"""后端接口的完整流程测试：扫描 → 看看里面 → 预检 → 执行。全部在临时文件夹里。"""
import os
import shutil
import time

import pytest

from core import recycle, safety
from core.api import Api
from core.oplog import OpLog
from core.prefs import Prefs
from core.safety import SafeCache
from core.space import Category

MB = 1024 * 1024


def make(path, size, age_days=0, fill=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        if fill is None:
            f.truncate(size)
        else:
            f.write(fill * size)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    dl, proj, cache = home / "Downloads", home / "projects", home / "AppCache" / "Temp"
    make(dl / "movie.mkv", 80 * MB, age_days=500)                 # 很久没用
    make(dl / "AppSetup.exe", 60 * MB, age_days=40)               # 安装包
    make(dl / "photos.zip", 70 * MB, age_days=40)                 # 已经解压过
    (dl / "photos").mkdir()
    make(dl / "a.bin", 55 * MB, age_days=40, fill=b"x")           # 两份一样的
    make(dl / "b.bin", 55 * MB, age_days=40, fill=b"x")
    make(dl / "new.pdf", 52 * MB)                                 # 最近还在用
    make(proj / "web" / "package.json", 10)
    make(proj / "web" / "node_modules" / "lib" / "big.js", 30 * MB)
    make(cache / "old.tmp", 5 * MB, age_days=3)
    bin_dir = tmp_path / "_bin"
    bin_dir.mkdir()
    moved = []
    def fake(p):
        moved.append(p)
        shutil.move(p, bin_dir / f"{len(moved)}_{os.path.basename(p)}")
    monkeypatch.setattr(recycle, "_recycle_other", fake)
    defs = [Category("downloads", "下载", "user", [str(dl)]), Category("projects", "代码项目", "user", [str(proj)])]
    caches = [SafeCache("temp", "临时文件", (str(cache),), min_age_days=1, group="系统")]
    api = Api(drive=str(tmp_path), log=OpLog(tmp_path / "logs"), prefs=Prefs(tmp_path / "prefs.json"),
              defs=defs, caches=caches)
    return api, dl, moved, tmp_path


def test_scan_reports_blocks_cleanables_and_suggestions(world):
    api, dl, _, _ = world
    assert api.scan()["started"]
    assert api.wait_idle()
    st = api.state()
    keys = {b["key"] for b in st["blocks"]}
    assert {"downloads", "projects", "c:temp"} <= keys
    assert [c["key"] for c in st["cleanables"]] == ["temp"]
    assert st["suggest"][0]["key"] == "downloads" and st["suggest"][0]["maybe"] > 0
    assert not st["scanning"] and st["phase"] == ""


def test_inspect_explains_each_file(world):
    api, dl, _, _ = world
    api.scan(); api.wait_idle()
    d = api.inspect("downloads")
    items = {i["name"]: (g["lvl"], i["why"]) for g in d["groups"] for i in g["items"]}
    assert items["AppSetup.exe"][0] == "maybe" and "安装" in items["AppSetup.exe"][1]
    assert items["photos.zip"][0] == "maybe" and "解压" in items["photos.zip"][1]
    assert items["b.bin"][0] == "maybe" and "一模一样" in items["b.bin"][1]
    assert items.get("a.bin", ("rest",))[0] != "maybe"      # 留最早的一份，不建议移走
    assert items["movie.mkv"][0] == "maybe" and "打开或修改" in items["movie.mkv"][1]
    assert items["new.pdf"][0] == "keep"
    p = api.inspect("projects")
    nm = [i for g in p["groups"] for i in g["items"] if i["name"] == "node_modules"]
    assert nm and nm[0]["dir"] and "重新生成" in nm[0]["why"]


def test_plan_is_read_only_and_execute_moves(world):
    api, dl, moved, _ = world
    api.scan(); api.wait_idle()
    d = api.inspect("downloads")
    ids = [i["id"] for g in d["groups"] if g["lvl"] == "maybe" for i in g["items"] if i["name"] in ("AppSetup.exe", "b.bin")]
    pl = api.plan("files", ids)
    assert pl["count"] == 2 and moved == []                 # 预检不动文件
    assert any("清空回收站" in w for w in pl["warnings"])
    assert api.execute(pl["id"])["started"]
    api.wait_idle()
    st = api.state()
    assert st["job"]["done"] and st["job"]["moved"] == 2
    assert sorted(os.path.basename(m) for m in moved) == ["AppSetup.exe", "b.bin"]
    assert (dl / "a.bin").exists()                          # 另一份还在
    names = {i["name"] for g in api.inspect("downloads")["groups"] for i in g["items"]}
    assert "AppSetup.exe" not in names


def test_plan_expires_and_cannot_run_twice(world):
    api, *_ = world
    api.scan(); api.wait_idle()
    pl = api.plan("caches", ["temp"])
    assert api.execute(pl["id"])["started"]
    api.wait_idle()
    assert not api.execute(pl["id"])["started"]             # 同一份确认只能用一次


def test_only_maybe_items_can_be_planned(world):
    api, dl, moved, _ = world
    api.scan(); api.wait_idle()
    d = api.inspect("downloads")
    keep_ids = [i["id"] for g in d["groups"] if g["lvl"] != "maybe" for i in g["items"]]
    assert api.plan("files", keep_ids)["count"] == 0         # “还在用”“你的文件”不能被移走


def test_file_changed_after_inspect_is_refused(world):
    api, dl, moved, _ = world
    api.scan(); api.wait_idle()
    d = api.inspect("downloads")
    sid = next(i["id"] for g in d["groups"] for i in g["items"] if i["name"] == "movie.mkv")
    with open(dl / "movie.mkv", "ab") as f:
        f.write(b"changed")
    pl = api.plan("files", [sid])
    assert pl["count"] == 0 and "改动过" in pl["refused"][0][1]


def test_keep_is_remembered(world):
    api, dl, _, tmp = world
    api.scan(); api.wait_idle()
    d = api.inspect("downloads")
    sid = next(i["id"] for g in d["groups"] for i in g["items"] if i["name"] == "movie.mkv")
    api.set_keep(sid, True)
    api2 = Api(drive=api.drive, log=api.log, prefs=Prefs(tmp / "prefs.json"), defs=api._defs, caches=api._caches)
    api2.scan(); api2.wait_idle()
    lvl = {i["name"]: g["lvl"] for g in api2.inspect("downloads")["groups"] for i in g["items"]}
    assert lvl["movie.mkv"] == "keep"


def test_history_lists_moves(world):
    api, *_ = world
    api.scan(); api.wait_idle()
    api.execute(api.plan("caches", ["temp"])["id"]); api.wait_idle()
    recs = api.history()["records"]
    assert recs and recs[0]["ok"]


def test_duplicates_never_both_removed(tmp_path, monkeypatch):
    """两份一样的旧文件：一份标“重复”，另一份不能也被建议移走；同时选了也只移一份。"""
    dl = tmp_path / "home" / "Downloads"
    make(dl / "毕业照.rar", 60 * MB, age_days=500, fill=b"y")
    make(dl / "毕业照副本.rar", 60 * MB, age_days=498, fill=b"y")
    moved = []
    monkeypatch.setattr(recycle, "_recycle_other", lambda p: (moved.append(p), shutil.move(p, p + ".x")))
    api = Api(drive=str(tmp_path), log=OpLog(tmp_path / "logs"), prefs=Prefs(tmp_path / "p.json"),
              defs=[Category("downloads", "下载", "user", [str(dl)])], caches=[])
    api.scan(); api.wait_idle()
    d = api.inspect("downloads")
    lvl = {i["name"]: g["lvl"] for g in d["groups"] for i in g["items"]}
    assert lvl["毕业照副本.rar"] == "maybe" and lvl["毕业照.rar"] != "maybe"
    # 即使有人把两份的 id 都传进来，也只会移一份
    all_ids = [i["id"] for g in d["groups"] for i in g["items"]]
    pl = api.plan("files", all_ids)
    assert pl["count"] == 1


def test_cleanable_items_not_suggested_twice(world):
    api, dl, _, tmp = world
    api._caches = api._caches + [SafeCache("installers", "旧安装包", (str(dl),), patterns=("*setup*.exe",), min_age_days=30)]
    api.scan(); api.wait_idle()
    names = {i["name"] for g in api.inspect("downloads")["groups"] for i in g["items"]}
    assert "AppSetup.exe" not in names
