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
        # 藏得深的大块头：单独列出来，用户才知道空间去哪了（只统计，不清理）
        Category("iphone", "iPhone 备份", "user",
                 [_env("APPDATA", "Apple Computer", "MobileSync", "Backup"),
                  _home("Apple", "MobileSync", "Backup")],
                 note="iTunes / 苹果设备备份。旧手机的备份可以在 iTunes 或“Apple 设备”里删除"),
        Category("vm", "虚拟机和 WSL", "app",
                 [_env("LOCALAPPDATA", "Packages", "*Canonical*", "LocalState", "ext4.vhdx"),
                  _env("LOCALAPPDATA", "Docker", "wsl"),
                  _home("VirtualBox VMs"), _home("Documents", "Virtual Machines"),
                  _home(".android", "avd")],
                 note="WSL、Docker、VirtualBox、VMware 和安卓模拟器的虚拟磁盘。请在对应软件里清理"),
        Category("steam", "Steam 游戏", "app",
                 [_env("ProgramFiles(x86)", "Steam", "steamapps")],
                 note="请在 Steam 里卸载不玩的游戏"),
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
                zh = {"downloads": "下载", "documents": "文档", "videos": "视频", "pictures": "图片",
                      "music": "音乐", "desktop": "桌面", "projects": "代码项目"}
                out.append(Category(e.name.lower(), zh.get(e.name.lower(), e.name), "user", [e.path]))
    except OSError:
        pass
    out.append(Category("dotfiles", "应用数据", "app", hidden))
    return out


def _expand(p: str) -> list[str]:
    if any(ch in p for ch in "*?["):
        import glob
        return glob.glob(p)
    return [p]


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
        c.paths = [q for p in c.paths if p for q in _expand(p)
                   if os.path.exists(q) and not os.path.islink(q) and _same_drive(q, drive)]
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
    system_files: dict = field(default_factory=dict)

    def blocks(self, cleanable_total: int = 0) -> list[Category]:
        """地图上的所有块：各类 + 可清理缓存 + 回收站 + 系统和其他 + 可用。"""
        blocks = [c for c in self.categories if c.size > 0]
        if cleanable_total:
            blocks.append(Category("safe", "可放心清理", "cache", size=cleanable_total))
        if self.recycle_bin:
            blocks.append(Category("trash", "回收站", "cache", size=self.recycle_bin,
                                   note="在桌面右键回收站 →“清空回收站”"))
        for key, name, note in (
                ("pagefile", "页面文件", "内存不够时 Windows 用的硬盘空间。大小由系统管理，不要手动删"),
                ("hiberfil", "休眠文件", "电脑休眠时保存内存用的。不用休眠的话，可以用管理员命令 powercfg /h off 关掉"),
        ):
            size = self.system_files.get(key, 0)
            if size:
                blocks.append(Category(key, name, "system", size=size, note=note))
        known = sum(b.size for b in blocks)
        rest = self.used - known
        if rest > 0:
            blocks.append(Category("system", "Windows 和其他", "system", size=rest,
                                   note="Windows 本身、系统还原点、其他用户的文件，以及没有权限查看的地方。"
                                        "请交给系统自带的“存储感知”：设置 → 系统 → 存储"))
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
            nested = {os.path.normcase(os.path.abspath(q)) for q, _ in all_paths
                      if q != np_ and q.startswith(np_ + os.sep)}
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
    return SpaceReport(drive, u.total, u.used, u.free, cats, recycle_bin_size(drive), system_files(drive))


def system_files(drive: str) -> dict:
    """页面文件、休眠文件的大小。只读文件属性，不打开文件。"""
    out = {}
    for key, name in (("pagefile", "pagefile.sys"), ("hiberfil", "hiberfil.sys"), ("swapfile", "swapfile.sys")):
        try:
            out[key] = os.stat(os.path.join(drive, name)).st_size
        except OSError:
            pass
    if "swapfile" in out:
        out["pagefile"] = out.get("pagefile", 0) + out.pop("swapfile")
    return out
