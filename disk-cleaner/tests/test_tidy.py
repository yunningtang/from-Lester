import os
import time

from core import mover, tidy
from core.oplog import OpLog


def make(path, age_days=0, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data * 100)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(path, (t, t))
    return path


def test_downloads_proposals(tmp_path):
    h = tmp_path
    dl = h / "Downloads"
    make(dl / "Screenshot 2024-05-01.png", 40)
    make(dl / "屏幕录制 1.mp4", 40)
    make(dl / "report.pdf", 60)
    (dl / "old-folder").mkdir(); make(dl / "old-folder" / "a.txt", 45)
    t = time.time() - 45 * 86400; os.utime(dl / "old-folder", (t, t))   # 文件夹本身也很久没动
    (dl / "just-unzipped").mkdir(); make(dl / "just-unzipped" / "b.txt", 400)  # 刚解压：里面的文件很旧，但文件夹是新的
    make(dl / "new.zip", 2)                       # 最近的，不动
    make(dl / "movie.mkv.crdownload", 90)         # 正在下载，不动
    make(dl / ".hidden", 90)                      # 隐藏，不动
    os.symlink(dl / "report.pdf", dl / "link.pdf")
    ps = {p.id.split(":")[-1]: p for p in tidy.propose("downloads", str(dl), str(h / "Pictures"), str(h / "Videos"))}
    shots = {os.path.basename(s): d for s, d in ps["shots"].moves}
    assert set(shots) == {"Screenshot 2024-05-01.png", "屏幕录制 1.mp4"}
    assert os.sep.join(["Pictures", "截图"]) in shots["Screenshot 2024-05-01.png"]
    assert os.sep.join(["Videos", "录屏"]) in shots["屏幕录制 1.mp4"]
    old = {os.path.basename(s) for s, _ in ps["old"].moves}
    assert old == {"report.pdf", "old-folder"}
    assert all(os.sep.join(["Downloads", "归档"]) in d for _, d in ps["old"].moves)


def test_desktop_keeps_folders_and_shortcuts(tmp_path):
    d = tmp_path / "Desktop"
    make(d / "旧笔记.txt", 120)
    make(d / "微信.lnk", 400)
    (d / "项目").mkdir(); make(d / "项目" / "x.txt", 400)
    make(d / "新文件.txt", 10)
    ps = tidy.propose("desktop", str(d), str(tmp_path / "Pictures"), str(tmp_path / "Videos"))
    assert [os.path.basename(s) for p in ps for s, _ in p.moves] == ["旧笔记.txt"]


def test_tidy_then_undo_restores_everything(tmp_path):
    dl = tmp_path / "Downloads"
    files = [make(dl / f"f{i}.pdf", 60) for i in range(5)] + [make(dl / "截图 1.png", 10)]
    ps = tidy.propose("downloads", str(dl), str(tmp_path / "Pictures"), str(tmp_path / "Videos"))
    pairs = [m for p in ps for m in p.moves]
    log = OpLog(tmp_path / "logs")
    rep = mover.execute_moves(mover.plan_moves(pairs), log)
    assert len(rep.moved) == 6 and not any(f.exists() for f in files)
    mover.execute_undo(mover.plan_undo(log, rep.batch), rep.batch, log)
    assert all(f.exists() for f in files)
    assert not (dl / "归档").exists() and not (tmp_path / "Pictures").exists()   # 自己建的空文件夹也清掉了


def test_undo_keeps_folders_that_got_new_files(tmp_path):
    dl = tmp_path / "Downloads"
    f = make(dl / "a.pdf", 60)
    ps = tidy.propose("downloads", str(dl), str(tmp_path / "Pictures"), str(tmp_path / "Videos"))
    log = OpLog(tmp_path / "logs")
    rep = mover.execute_moves(mover.plan_moves([m for p in ps for m in p.moves]), log)
    month = next((dl / "归档").iterdir())
    (month / "用户自己放的.txt").write_text("x")          # 用户后来往归档里放了东西
    mover.execute_undo(mover.plan_undo(log, rep.batch), rep.batch, log)
    assert f.exists() and (month / "用户自己放的.txt").exists()


def test_reading_a_file_does_not_make_it_recent(tmp_path):
    dl = tmp_path / "Downloads"
    s = make(dl / "Screenshot 1.png", 40)
    s.read_bytes()                                          # 找重复文件时读过一遍（访问时间变了）
    ps = tidy.propose("downloads", str(dl), str(tmp_path / "Pictures"), str(tmp_path / "Videos"))
    assert [os.path.basename(x) for p in ps for x, _ in p.moves] == ["Screenshot 1.png"]
