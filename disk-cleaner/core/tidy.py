"""整理下载和桌面：只给“挪到哪里”的建议，不删除任何东西（只读）。执行走 mover，可以撤销。

一个简单、能坚持的规则，而不是一套复杂的分类：
- 截图和录屏 → 图片 › 截图 › 年-月 / 视频 › 录屏 › 年-月
- 下载里 30 天没碰过的东西 → 下载 › 归档 › 年-月
- 桌面上 90 天没碰过的文件 → 桌面 › 归档 › 年-月（文件夹和快捷方式不动）

不碰：正在下载的文件、快捷方式、隐藏文件、desktop.ini、最近用过的东西。
"""
from __future__ import annotations

import datetime as _dt
import os
import time
from dataclasses import dataclass, field

from .fs import folder_size, is_link_or_junction, stamp

ARCHIVE = "归档"
SHOT_WORDS = ("screenshot", "screen shot", "屏幕截图", "截图", "qq截图", "微信图片", "微信截图",
              "snipaste", "screen recording", "录屏", "屏幕录制", "screencast", "capture")
IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
VIDEO = (".mp4", ".mkv", ".mov", ".webm", ".avi")
PARTIAL = (".crdownload", ".part", ".partial", ".download", ".tmp", ".liubai-part", ".!ut", ".td")
SKIP_NAMES = ("desktop.ini", "thumbs.db")
SHORTCUT = (".lnk", ".url")


@dataclass
class Proposal:
    id: str
    title: str
    how: str
    moves: list[tuple[str, str]] = field(default_factory=list)
    sizes: dict = field(default_factory=dict)
    stamps: dict = field(default_factory=dict)

    @property
    def count(self) -> int:
        return len(self.moves)

    @property
    def size(self) -> int:
        return sum(self.sizes.values())

    @property
    def samples(self) -> list[str]:
        return [os.path.basename(s) for s, _ in self.moves[:5]]


def _month(ts: float) -> str:
    d = _dt.datetime.fromtimestamp(ts)
    return f"{d.year}-{d.month:02d}"


def _last_used(path: str, st: os.stat_result, is_dir: bool) -> float:
    # 只看修改时间。访问时间不可靠：Windows 常常不记录，而且我们自己找重复文件时读一遍就会把它刷新。
    t = st.st_mtime
    if is_dir:  # 文件夹看里面最新的文件（最多看 2000 个）
        n = 0
        for root, dirs, files in os.walk(path):
            for f in files:
                n += 1
                try:
                    t = max(t, os.stat(os.path.join(root, f), follow_symlinks=False).st_mtime)
                except OSError:
                    pass
                if n > 2000:
                    return t
    return t


def is_shot(name: str) -> bool:
    n = name.lower()
    return n.endswith(IMAGE + VIDEO) and any(w in n for w in SHOT_WORDS)


def propose(where: str, folder: str, pictures: str, videos: str, now: float | None = None) -> list[Proposal]:
    """where = "downloads" 或 "desktop"。"""
    now = now or time.time()
    label = "下载" if where == "downloads" else "桌面"
    shots = Proposal(f"tidy:{where}:shots", "截图和录屏", "放进 图片 › 截图、视频 › 录屏，按月份分好")
    old_days = 30 if where == "downloads" else 90
    old = Proposal(f"tidy:{where}:old", f"{old_days} 天没碰过的{'东西' if where == 'downloads' else '文件'}",
                   f"收进 {label} › {ARCHIVE}，按月份分好")
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []
    for e in entries:
        try:
            name, low = e.name, e.name.lower()
            if is_link_or_junction(e) or name.startswith(".") or low in SKIP_NAMES or low.endswith(PARTIAL):
                continue
            if name == ARCHIVE:
                continue
            is_dir = e.is_dir(follow_symlinks=False)
            st = e.stat(follow_symlinks=False)
            if getattr(st, "st_file_attributes", 0) & 0x2:    # 隐藏文件
                continue
            used = _last_used(e.path, st, is_dir)
            age = (now - used) / 86400
            if not is_dir and is_shot(name) and age > 1:
                base = os.path.join(videos, "录屏") if low.endswith(VIDEO) else os.path.join(pictures, "截图")
                dst = os.path.join(base, _month(st.st_mtime), name)
                shots.moves.append((e.path, dst))
                shots.sizes[e.path] = st.st_size
                shots.stamps[e.path] = stamp(e.path)
                continue
            if age < old_days:
                continue
            if where == "desktop" and (is_dir or low.endswith(SHORTCUT)):
                continue                                    # 桌面上的文件夹和快捷方式是用户摆好的
            dst = os.path.join(folder, ARCHIVE, _month(used), name)
            old.moves.append((e.path, dst))
            old.sizes[e.path] = folder_size(e.path) if is_dir else st.st_size
            old.stamps[e.path] = None if is_dir else stamp(e.path)
        except OSError:
            continue
    for p in (shots, old):
        p.moves.sort(key=lambda m: -p.sizes.get(m[0], 0))
    return [p for p in (shots, old) if p.moves]
