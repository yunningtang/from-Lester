"""找内容一模一样的文件（只读）。

怎么判断“一模一样”：大小相同 → 开头和结尾各 1 MB 相同 → 完整 SHA-256 相同。三步都过才算。
同一个文件通过硬链接或两条路径被看到两次，不算重复。

每组留哪一份（keeper），按这个顺序：
1. 所在位置：图片、文档、视频、音乐 > 桌面 > 下载 > 微信、QQ（越靠前越像“正式存放的地方”）
2. 更早的那份（通常是原件）
3. 路径更短的那份
其余的才是“副本”，可以移走。留下的那份绝不会被移走。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable

from .fs import is_cloud_placeholder, is_link_or_junction, stamp
from .inspect import REGEN, _full_hash, _quick_key
from .safety import is_protected

MIN_SIZE = 1024 * 1024
HASH_BUDGET = 30 * 1024 ** 3
MAX_GROUPS = 500


@dataclass
class DupeFile:
    id: str
    path: str
    size: int
    mtime: float
    where: str                      # 给人看的位置，比如“图片 › 旅行”
    stamp: tuple | None = None


@dataclass
class DupeGroup:
    id: str
    size: int
    files: list[DupeFile] = field(default_factory=list)
    keeper: str = ""                # 留下的那份的路径

    @property
    def copies(self) -> list[DupeFile]:
        return [f for f in self.files if f.path != self.keeper]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.files) - 1)


def _where(path: str, roots: list[tuple[str, str]]) -> tuple[int, str]:
    """(优先级, 给人看的位置)。取包含它的、最靠里的那个根目录（微信在文档里面，算微信）。"""
    np = os.path.normcase(os.path.abspath(path))
    best_i, best_root, best_label = len(roots), "", ""
    for i, (label, root) in enumerate(roots):
        r = os.path.normcase(os.path.abspath(root))
        if np.startswith(r.rstrip(os.sep) + os.sep) and len(r) > len(best_root):
            best_i, best_root, best_label = i, root, label
    if not best_root:
        return len(roots), os.path.dirname(path)
    rel = os.path.relpath(os.path.dirname(path), best_root)
    return best_i, best_label if rel == "." else f"{best_label} › {rel.replace(os.sep, ' › ')}"


def find(roots: list[tuple[str, str]], min_size: int = MIN_SIZE, cancel: threading.Event | None = None,
         budget: int = HASH_BUDGET, on_progress: Callable[[str], None] | None = None) -> list[DupeGroup]:
    """roots：[(名字, 路径)]，按“正式程度”从高到低排。"""
    by_size: dict[int, list[tuple[str, os.stat_result]]] = {}
    seen: set[str] = set()
    for _, root in roots:
        stack = [root] if os.path.isdir(root) else []
        while stack:
            if cancel is not None and cancel.is_set():
                return []
            d = stack.pop()
            if is_protected(d):
                continue
            try:
                entries = list(os.scandir(d))
            except OSError:
                continue
            for e in entries:
                try:
                    if is_link_or_junction(e):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if not e.name.startswith(".") and e.name not in REGEN:
                            stack.append(e.path)
                        continue
                    st = e.stat(follow_symlinks=False)
                    if st.st_size < min_size or is_cloud_placeholder(st):
                        continue
                    key = os.path.normcase(os.path.realpath(e.path))
                    if key in seen:                      # 两个根目录有重叠（比如文档里的微信文件夹）
                        continue
                    seen.add(key)
                    by_size.setdefault(st.st_size, []).append((e.path, st))
                except OSError:
                    continue

    groups: list[DupeGroup] = []
    candidates = sorted(((s, fs) for s, fs in by_size.items() if len(fs) > 1), key=lambda x: -x[0])
    for size, files in candidates:
        if cancel is not None and cancel.is_set() or budget <= 0:
            break
        # 硬链接：同一个文件的两个名字，不算重复
        inodes: dict[tuple, tuple[str, os.stat_result]] = {}
        for p, st in files:
            try:
                full = os.stat(p, follow_symlinks=False)
                ident = (full.st_dev, full.st_ino) if full.st_ino else (p,)
            except OSError:
                continue
            inodes.setdefault(ident, (p, st))
        files = list(inodes.values())
        if len(files) < 2:
            continue
        quick: dict[str, list[tuple[str, os.stat_result]]] = {}
        for p, st in files:
            k = _quick_key(p, size)
            if k:
                quick.setdefault(k, []).append((p, st))
        for same in quick.values():
            if len(same) < 2:
                continue
            full: dict[str, list[tuple[str, os.stat_result]]] = {}
            for p, st in same:
                if budget <= 0:
                    break
                if on_progress:
                    on_progress(os.path.basename(p))
                budget -= size
                h = _full_hash(p, cancel)
                if h:
                    full.setdefault(h, []).append((p, st))
            for twins in full.values():
                if len(twins) < 2:
                    continue
                gid = f"dup:{len(groups) + 1}"
                g = DupeGroup(gid, size)
                ranked = []
                for j, (p, st) in enumerate(twins):
                    rank, where = _where(p, roots)
                    g.files.append(DupeFile(f"{gid}:{j + 1}", p, size, st.st_mtime, where, stamp(p)))
                    ranked.append(((rank, st.st_mtime, len(p)), p))
                g.keeper = min(ranked)[1]
                groups.append(g)
    groups.sort(key=lambda g: -g.wasted)
    return groups[:MAX_GROUPS]


def default_roots(home: str | None = None) -> list[tuple[str, str]]:
    """Windows 上常见的个人文件夹，按“正式程度”排序。"""
    from pathlib import Path
    h = Path(home) if home else Path.home()
    docs = h / "Documents"
    roots = [("图片", h / "Pictures"), ("文档", docs), ("视频", h / "Videos"), ("音乐", h / "Music"),
             ("桌面", h / "Desktop"), ("下载", h / "Downloads"),
             ("微信", docs / "WeChat Files"), ("微信", docs / "xwechat_files"), ("QQ", docs / "Tencent Files")]
    return [(label, str(p)) for label, p in roots if p.is_dir()]
