"""统计磁盘空间都用在哪里（只读）。结果给概览页的石头地图用。"""
from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .fs import folder_size
from .safety import _norm

# kind：user 你的文件 / app 程序和应用数据 / cache 缓存 / system 系统和其他 / free 可用


@dataclass
class Category:
    key: str
    name: str
    kind: str
    paths: list[str] = field(default_factory=list)
    size: int = 0
    note: str = ""


def system_drive() -> str:
    if os.name == "nt":
        return (os.environ.get("SystemDrive") or "C:") + "\\"
    return "/"


def _home(*p) -> str:
    return str(Path.home().joinpath(*p))


def _env(name: str, *p) -> str:
    v = os.environ.get(name)
    return os.path.join(v, *p) if v else ""


def _windows_defs() -> list[Category]:
    docs = _home("Documents")
    return [
        Category("wechat", "微信聊天文件", "user",
                 [os.path.join(docs, "WeChat Files"), os.path.join(docs, "xwechat_files")]),
        Category("qq", "QQ 聊天文件", "user", [os.path.join(docs, "Tencent Files")]),
        Category("documents", "文档", "user", [docs]),
        Category("downloads", "下载", "user", [_home("Downloads")]),
        Category("desktop", "桌面", "user", [_home("Desktop")]),
        Category("pictures", "图片", "user", [_home("Pictures")]),
        Category("videos", "视频", "user", [_home("Videos")]),
        Category("music", "音乐", "user", [_home("Music")]),
        Category("onedrive", "OneDrive", "user", [_home("OneDrive")]),
        Category("projects", "代码项目", "user",
                 [_home(n) for n in ("source", "repos", "projects", "Projects", "code", "dev")]),
        Category("devtools", "开发工具缓存", "app",
                 [_home(".gradle"), _home(".m2"), _home(".nuget"), _home(".cargo"),
                  _home(".rustup"), _home(".conda"), _home("anaconda3"), _home("miniconda3")]),
        Category("roaming", "应用数据", "app", [_env("APPDATA")]),
        Category("local", "本地应用数据", "app", [_env("LOCALAPPDATA")]),
        Category("programs", "已安装的程序", "app",
                 [_env("ProgramFiles"), _env("ProgramFiles(x86)")]),
    ]


def _generic_defs() -> list[Category]:
    """非 Windows（开发测试用）：主目录下每个文件夹一类。"""
    home = Path.home()
    out = [Category("cache", "应用缓存", "app", [_home(".cache")])]
    hidden = []
    try:
        for e in os.scandir(home):
            if not e.is_dir(follow_symlinks=False) or e.name == ".cache":
                continue
            if e.name.startswith("."):
                hidden.append(e.path)
            else:
                out.append(Category(e.name.lower(), e.name, "user", [e.path]))
    except OSError:
        pass
    out.append(Category("dotfiles", "应用数据", "app", hidden))
    return out


def _same_drive(path: str, drive: str) -> bool:
    if os.name == "nt":
        return os.path.splitdrive(os.path.abspath(path))[0].lower() == \
            os.path.splitdrive(drive)[0].lower()
    try:
        return os.stat(path).st_dev == os.stat(drive).st_dev
    except OSError:
        return False


def category_defs(drive: str | None = None) -> list[Category]:
    drive = drive or system_drive()
    defs = _windows_defs() if os.name == "nt" else _generic_defs()
    out = []
    for c in defs:
        c.paths = [p for p in c.paths if p and os.path.isdir(p) and _same_drive(p, drive)]
        if c.paths:
            out.append(c)
    return out


@dataclass
class SpaceReport:
    drive: str
    total: int
    used: int
    free: int
    categories: list[Category]
    recycle_bin: int = 0

    def blocks(self, cleanable_total: int = 0) -> list[Category]:
        """地图上的所有块：各类 + 可清理缓存 + 回收站 + 系统和其他 + 可用。"""
        blocks = [c for c in self.categories if c.size > 0]
        if cleanable_total:
            blocks.append(Category("safe", "可放心清理", "cache", size=cleanable_total))
        if self.recycle_bin:
            blocks.append(Category("trash", "回收站", "cache", size=self.recycle_bin,
                                   note="在桌面右键回收站 →“清空回收站”"))
        known = sum(b.size for b in blocks)
        rest = self.used - known
        if rest > 0:
            blocks.append(Category("system", "系统和其他", "system", size=rest,
                                   note="Windows、页面文件、休眠文件和其他用户的文件"))
        blocks.append(Category("free", "可用", "free", size=self.free))
        return blocks


def recycle_bin_size(drive: str) -> int:
    if os.name != "nt":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        if ctypes.windll.shell32.SHQueryRecycleBinW(drive, ctypes.byref(info)) == 0:
            return int(info.i64Size)
    except Exception:
        pass
    return 0


def measure(
    drive: str | None = None,
    cancel: threading.Event | None = None,
    on_category: Callable[[Category], None] | None = None,
    subtract: list[tuple[str, int]] = (),
    defs: list[Category] | None = None,
) -> SpaceReport:
    """统计各类大小。嵌套的类（文档里的微信文件夹）不重复计算；
    subtract 里的 (路径, 大小)（可清理项目）从包含它的类里扣掉，单独显示。"""
    drive = drive or system_drive()
    u = shutil.disk_usage(drive)
    cats = defs if defs is not None else category_defs(drive)
    all_paths = [(_norm(p), c) for c in cats for p in c.paths]
    for c in cats:
        if cancel is not None and cancel.is_set():
            break
        size = 0
        for p in c.paths:
            np_ = _norm(p)
            nested = {q for q, _ in all_paths if q != np_ and q.startswith(np_ + os.sep)}
            size += folder_size(p, cancel, frozenset(nested))
        c.size = size
        if on_category:
            on_category(c)
    for path, sz in subtract:
        np_ = _norm(path)
        owners = [(q, c) for q, c in all_paths if np_.startswith(q + os.sep)]
        if owners:
            _, owner = max(owners, key=lambda x: len(x[0]))  # 最内层的类
            owner.size = max(0, owner.size - sz)
    return SpaceReport(drive, u.total, u.used, u.free, cats, recycle_bin_size(drive))
