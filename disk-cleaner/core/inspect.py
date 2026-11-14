"""看看一类空间里面有什么，给出建议（只读，不动任何文件）。

每一项建议都有：
- lvl：maybe 可能不再需要 / mine 你的作品 / keep 最近还在用 / lock 留白不会动
- why：用一句人话说为什么这样建议
- then：如果移走，会怎样（确认时给用户看）

判断都在本地完成：
- 能重新生成的文件夹（node_modules、build、dist、target 等）
- 内容一模一样的文件（先比大小，再比开头和结尾，最后比完整哈希）
- 安装包、系统镜像
- 已经解压过的压缩包（旁边有同名文件夹）
- 很久没打开或修改过的文件
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import heapq
import os
import threading
import time
from dataclasses import dataclass, field

from .fs import folder_size, is_cloud_placeholder, is_link_or_junction, stamp
from .safety import can_delete, is_protected

REGEN = {
    "node_modules": ("项目的依赖包", "下次打开项目时运行 npm install，会自动装回来。"),
    "bower_components": ("项目的依赖包", "需要时重新安装依赖即可。"),
    ".next": ("网站构建缓存", "重新运行就会生成。"),
    ".nuxt": ("网站构建缓存", "重新运行就会生成。"),
    "dist": ("构建出来的文件", "重新构建就会生成，不影响源代码。"),
    "build": ("构建出来的文件", "重新构建就会生成，不影响源代码。"),
    "target": ("编译出来的文件", "重新编译就会生成，不影响源代码。"),
    "__pycache__": ("Python 缓存", "运行时会自动重新生成。"),
    ".pytest_cache": ("测试缓存", "运行测试时会重新生成。"),
}
# build / dist / target 这类名字很普通，只有在“像项目”的文件夹里才算
PROJECT_MARKERS = ("package.json", "pyproject.toml", "setup.py", "Cargo.toml", "pom.xml",
                   "build.gradle", "build.gradle.kts", "go.mod", ".git", "CMakeLists.txt")
WEAK_REGEN = {"dist", "build", "target"}

INSTALLER_EXT = (".msi",)
INSTALLER_WORDS = ("setup", "install", "installer")
IMAGE_EXT = (".iso", ".img")
ARCHIVE_EXT = (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz")
MEDIA_EXT = (".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov", ".mkv", ".avi", ".raw", ".cr2", ".nef", ".arw")

# 每类空间的口吻：哪些建议可以给，删了会怎样
TONE = {
    "downloads": {"old_days": 365, "old_lvl": "maybe", "then": "删了以后，需要时得重新下载。"},
    "desktop": {"old_days": 365, "old_lvl": "mine", "then": ""},
    "wechat": {"old_days": 365, "old_lvl": "maybe",
               "then": "删了以后，在聊天里点开会提示文件已过期或被清理。"},
    "qq": {"old_days": 365, "old_lvl": "maybe", "then": "删了以后，在聊天里就打不开这个文件了。"},
    "videos": {"old_days": 0, "old_lvl": "mine", "then": ""},
    "pictures": {"old_days": 0, "old_lvl": "mine", "then": ""},
    "documents": {"old_days": 0, "old_lvl": "mine", "then": ""},
    "projects": {"old_days": 0, "old_lvl": "mine", "then": ""},
}
DEFAULT_TONE = {"old_days": 0, "old_lvl": "mine", "then": ""}

MAX_LISTED = 40          # 一类最多列出多少条建议
MAX_FILES = 400          # 最多看多少个大文件
MIN_FILE = 50 * 1024 * 1024
HASH_BUDGET = 8 * 1024 ** 3   # 比较重复文件时最多读多少字节，避免卡太久


@dataclass
class Suggestion:
    id: str
    name: str
    path: str
    size: int
    lvl: str
    why: str
    then: str = ""
    stamp: tuple | None = None
    is_dir: bool = False
    twin_of: str = ""        # 重复文件：留下的那一份的路径


@dataclass
class Inspection:
    key: str
    items: list[Suggestion] = field(default_factory=list)
    rest_count: int = 0
    rest_size: int = 0
    seconds: float = 0.0

    @property
    def maybe_size(self) -> int:
        return sum(s.size for s in self.items if s.lvl == "maybe")


def _month(ts: float) -> str:
    d = _dt.datetime.fromtimestamp(ts)
    return f"{d.year} 年 {d.month} 月"


def _last_used(st: os.stat_result) -> float:
    # Windows 默认可能不更新“访问时间”，所以取访问和修改里更晚的那个
    return max(st.st_mtime, getattr(st, "st_atime", 0))


def _quick_key(path: str, size: int) -> str | None:
    """开头 1 MB + 结尾 1 MB + 大小。不一样的文件几乎都能在这一步分开。"""
    try:
        with open(path, "rb") as f:
            h = hashlib.sha256()
            h.update(f.read(1 << 20))
            if size > 2 << 20:
                f.seek(-(1 << 20), os.SEEK_END)
                h.update(f.read(1 << 20))
        return f"{size}:{h.hexdigest()}"
    except OSError:
        return None


def _full_hash(path: str, cancel: threading.Event | None) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                b = f.read(4 << 20)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except OSError:
        return None


def _is_installer(name: str) -> bool:
    n = name.lower()
    return n.endswith(INSTALLER_EXT) or (n.endswith(".exe") and any(w in n for w in INSTALLER_WORDS))


def inspect(key: str, paths: list[str], cancel: threading.Event | None = None,
            keep: set[str] | frozenset[str] = frozenset(), now: float | None = None,
            skip: set[str] | frozenset[str] = frozenset()) -> Inspection:
    """看一类空间。paths 是这一类的文件夹；keep 是用户说过“留着”的路径；
    skip 是已经在“可放心清理”里的路径（不重复建议，也不重复计算）。"""
    t0 = time.monotonic()
    now = now or time.time()
    tone = TONE.get(key, DEFAULT_TONE)
    out = Inspection(key)
    files: list[tuple[int, str, os.stat_result]] = []   # 小顶堆，只留最大的
    regen: list[tuple[str, str]] = []                    # (路径, 名字)
    dirs_seen: dict[str, set[str]] = {}                  # 文件夹 → 里面的子文件夹名（找“已解压”用）

    stack = [p for p in paths if os.path.isdir(p)]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        d = stack.pop()
        if is_protected(d):
            continue
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        names = {e.name for e in entries}
        is_project = any(m in names for m in PROJECT_MARKERS)
        subdirs = set()
        for e in entries:
            try:
                if is_link_or_junction(e):
                    continue
                if e.is_dir(follow_symlinks=False):
                    subdirs.add(e.name.lower())
                    if e.name in REGEN and (e.name not in WEAK_REGEN or is_project):
                        regen.append((e.path, e.name))
                        continue           # 不往里走，整个当一项
                    if e.name.startswith(".") and e.name not in (".", ".."):
                        continue           # .git 等隐藏文件夹不看
                    stack.append(e.path)
                else:
                    st = e.stat(follow_symlinks=False)
                    if is_cloud_placeholder(st) or st.st_size < MIN_FILE or e.path in skip:
                        continue
                    item = (st.st_size, e.path, st)
                    if len(files) < MAX_FILES:
                        heapq.heappush(files, item)
                    elif st.st_size > files[0][0]:
                        heapq.heapreplace(files, item)
            except OSError:
                continue
        dirs_seen[d] = subdirs

    sugg: list[Suggestion] = []
    n = 0

    def add(path, size, lvl, why, then="", is_dir=False, twin_of=""):
        nonlocal n
        n += 1
        if path in keep:
            lvl, why, then = "keep", "你说过留着。", ""
        sugg.append(Suggestion(f"{key}:{n}", os.path.basename(path) or path, path, size, lvl, why, then,
                               None if is_dir else stamp(path), is_dir, twin_of))

    # 1. 能重新生成的文件夹
    for path, name in regen:
        if cancel is not None and cancel.is_set():
            break
        size = folder_size(path, cancel)
        if size < 20 * 1024 * 1024:
            continue
        what, then = REGEN[name]
        parent = os.path.basename(os.path.dirname(path))
        add(path, size, "maybe", f"“{parent}”的{what}，可以重新生成。", then, is_dir=True)

    # 2. 重复文件：大小相同 → 开头结尾相同 → 完整哈希相同
    big = sorted(files, reverse=True)
    by_size: dict[int, list[tuple[str, os.stat_result]]] = {}
    for size, path, st in big:
        by_size.setdefault(size, []).append((path, st))
    dup_of: dict[str, str] = {}
    budget = HASH_BUDGET
    for size, group in by_size.items():
        if len(group) < 2 or budget <= 0:
            continue
        quick: dict[str, list[tuple[str, os.stat_result]]] = {}
        for path, st in group:
            k = _quick_key(path, size)
            if k:
                quick.setdefault(k, []).append((path, st))
        for same in quick.values():
            if len(same) < 2:
                continue
            full: dict[str, list[tuple[str, os.stat_result]]] = {}
            for path, st in same:
                if budget <= 0:
                    break
                budget -= size
                h = _full_hash(path, cancel)
                if h:
                    full.setdefault(h, []).append((path, st))
            for twins in full.values():
                if len(twins) < 2:
                    continue
                # 留最早的那份，其余的算重复
                twins.sort(key=lambda x: x[1].st_mtime)
                for path, _ in twins[1:]:
                    dup_of[path] = twins[0][0]

    kept_twins = set(dup_of.values())

    # 3. 逐个大文件下判断
    rest_count = rest_size = 0
    for size, path, st in big:
        name = os.path.basename(path)
        low = name.lower()
        used = _last_used(st)
        age_days = (now - used) / 86400
        if path in dup_of:
            other = dup_of[path]
            add(path, size, "maybe", f"和“{os.path.basename(other)}”一模一样，留一份就够。",
                "另一份还在，不会丢东西。", twin_of=other)
        elif path in kept_twins:
            # 重复文件里要留下的那一份：绝不建议移走，否则可能两份都没了
            add(path, size, "mine", "有一模一样的副本，这一份留着。")
        elif _is_installer(name):
            add(path, size, "maybe", f"安装文件，{_month(st.st_mtime)}下载。",
                "不影响已经装好的程序。")
        elif low.endswith(IMAGE_EXT):
            add(path, size, "maybe", "系统或软件的安装镜像，一般只在重装时用得上。",
                "需要时可以从官网重新下载。")
        elif low.endswith(ARCHIVE_EXT) and os.path.splitext(low)[0] in dirs_seen.get(os.path.dirname(path), set()):
            add(path, size, "maybe", "已经解压过了，旁边有同名的文件夹。", "解压出来的文件还在。")
        elif age_days < 30:
            add(path, size, "keep", f"最近还在用（{_month(used)}）。")
        elif tone["old_days"] and age_days > tone["old_days"]:
            add(path, size, tone["old_lvl"], f"最近一次打开或修改是 {_month(used)}。", tone["then"])
        elif low.endswith(MEDIA_EXT) or tone["old_lvl"] == "mine":
            add(path, size, "mine", f"你的文件，最近一次打开或修改是 {_month(used)}。",
                "如果 C 盘紧，可以挪到别的盘，不用删。")
        else:
            rest_count += 1
            rest_size += size

    # 安全：凡是不能删的，一律不给“移走”的建议
    for s in sugg:
        if s.lvl == "maybe" and not can_delete(s.path)[0]:
            s.lvl, s.why, s.then = "lock", s.why + "（这个位置留白不会动。）", ""

    order = {"maybe": 0, "mine": 1, "keep": 2, "lock": 3}
    sugg.sort(key=lambda s: (order[s.lvl], -s.size))
    out.items = sugg[:MAX_LISTED]
    for s in sugg[MAX_LISTED:]:
        rest_count += 1
        rest_size += s.size
    out.rest_count, out.rest_size = rest_count, rest_size
    out.seconds = time.monotonic() - t0
    return out
