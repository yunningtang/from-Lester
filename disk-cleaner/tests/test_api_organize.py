"""第二步的完整流程：重复文件、整理下载、挪到别的盘、撤销。全部在临时文件夹里。"""
import os
import shutil
import time

import pytest

from core import recycle
from core.api import Api
from core.oplog import OpLog
from core.prefs import Prefs
from core.space import Category

MB = 1024 * 1024


def make(path, size=2 * MB, data=b"a", age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data * size)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home = tmp_path / "home"
    make(home / "Pictures" / "海边.jpg", data=b"p", age_days=50)
    make(home / "Downloads" / "IMG_001.jpg", data=b"p", age_days=40)        # 和 海边.jpg 一样
    make(home / "Downloads" / "Screenshot 1.png", 100, b"s", age_days=10)
    make(home / "Downloads" / "旧报告.pdf", 100, b"r", age_days=90)
    make(home / "Videos" / "旅行.mp4", 60 * MB, b"v", age_days=400)
    (tmp_path / "D").mkdir()
    bin_dir = tmp_path / "_bin"; bin_dir.mkdir()
    monkeypatch.setattr(recycle, "_recycle_other", lambda p: shutil.move(p, bin_dir / os.path.basename(p)))
    defs = [Category("downloads", "下载", "user", [str(home / "Downloads")]),
            Category("videos", "视频", "user", [str(home / "Videos")]),
            Category("pictures", "图片", "user", [str(home / "Pictures")])]
    api = Api(drive=str(tmp_path), log=OpLog(tmp_path / "logs"), prefs=Prefs(tmp_path / "p.json"),
              defs=defs, caches=[], home=str(home), move_targets=[str(tmp_path / "D")])
    api.scan(); assert api.wait_idle()
    return api, home, tmp_path


def run(api, plan):
    assert api.execute(plan["id"])["started"]
    assert api.wait_idle()
    return api.state()["job"]


def test_organize_summary_appears(setup):
    api, *_ = setup
    keys = {o["key"] for o in api.state()["organize"]}
    assert {"dupes", "tidy:downloads"} <= keys


def test_dupes_keep_one_copy(setup):
    api, home, _ = setup
    d = api.inspect("dupes")["dupes"][0]
    keeper = next(f for f in d["files"] if f["keeper"])
    assert keeper["name"] == "海边.jpg"                       # 图片里的那份留下
    all_ids = [f["id"] for f in d["files"]]
    pl = api.plan("dupes", all_ids)                           # 连留下的那份也选上
    assert pl["count"] == 1 and pl["refused_count"] == 1
    job = run(api, pl)
    assert job["moved"] == 1
    assert (home / "Pictures" / "海边.jpg").exists() and not (home / "Downloads" / "IMG_001.jpg").exists()


def test_change_keeper(setup):
    api, home, _ = setup
    d = api.inspect("dupes")["dupes"][0]
    other = next(f for f in d["files"] if not f["keeper"])
    api.set_keeper(d["id"], other["id"])
    d2 = api.inspect("dupes")["dupes"][0]
    assert next(f for f in d2["files"] if f["keeper"])["id"] == other["id"]


def test_tidy_and_undo(setup):
    api, home, _ = setup
    props = api.inspect("tidy:downloads")["proposals"]
    pl = api.plan("tidy", [p["id"] for p in props])
    assert pl["type"] == "move" and pl["count"] >= 2
    job = run(api, pl)
    assert job["undoable"] and not (home / "Downloads" / "Screenshot 1.png").exists()
    assert list((home / "Pictures" / "截图").rglob("Screenshot 1.png"))
    assert list((home / "Downloads" / "归档").rglob("旧报告.pdf"))
    assert api.undo(job["batch"])["started"]; api.wait_idle()
    assert (home / "Downloads" / "Screenshot 1.png").exists() and (home / "Downloads" / "旧报告.pdf").exists()
    h = api.history()
    assert h["batches"] and not h["batches"][0]["undoable"]  # 撤销过了


def test_move_your_file_to_other_drive_and_back(setup):
    api, home, tmp = setup
    d = api.inspect("videos")
    vid = next(i for g in d["groups"] for i in g["items"] if i["name"] == "旅行.mp4")
    target = api.state()["drives"][0]["root"]
    pl = api.plan("move", [vid["id"]], target)
    assert pl["count"] == 1 and any("留白挪出" in t for t in pl["then"])
    job = run(api, pl)
    moved_to = tmp / "D" / "留白挪出" / "视频" / "旅行.mp4"
    assert moved_to.exists() and not (home / "Videos" / "旅行.mp4").exists()
    api.undo(job["batch"]); api.wait_idle()
    assert (home / "Videos" / "旅行.mp4").exists() and not moved_to.exists()


def test_unknown_target_is_refused(setup):
    api, *_ = setup
    d = api.inspect("videos")
    vid = next(i for g in d["groups"] for i in g["items"])
    assert "error" in api.plan("move", [vid["id"]], "/nowhere")
