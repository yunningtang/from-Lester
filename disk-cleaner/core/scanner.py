"""只读扫描器：遍历文件夹，找出大文件。不写、不移动任何文件。"""
from __future__ import annotations

import heapq
import os
import stat
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .safety import is_protected


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    mtime: float


@dataclass
class ScanProgress:
    files: int = 0
    dirs: int = 0
    bytes: int = 0
    current: str = ""


@dataclass
class ScanResult:
    files: list[FileEntry] = field(default_factory=list)
    progress: ScanProgress = field(default_factory=ScanProgress)
    skipped: list[str] = field(default_factory=list)   # 受保护或无权限的目录
    cancelled: bool = False
    seconds: float = 0.0


def _is_link_or_junction(entry: os.DirEntry) -> bool:
    if entry.is_symlink():
        return True
    is_junction = getattr(entry, "is_junction", None)  # Python 3.12+
    if is_junction and is_junction():
        return True
    try:
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True


def scan_large_files(
    root: str,
    min_size: int = 100 * 1024 * 1024,
    limit: int = 1000,
    cancel: threading.Event | None = None,
    on_progress: Callable[[ScanProgress], None] | None = None,
    progress_every: float = 0.1,
) -> ScanResult:
    """找出 root 下大于等于 min_size 的文件，按大小从大到小，最多 limit 个。"""
    result = ScanResult()
    prog = result.progress
    heap: list[tuple[int, str, float]] = []
    start = last_report = time.monotonic()
    stack = [os.path.abspath(root)]

    while stack:
        if cancel is not None and cancel.is_set():
            result.cancelled = True
            break
        d = stack.pop()
        if is_protected(d):
            result.skipped.append(d)
            continue
        prog.dirs += 1
        prog.current = d
        try:
            it = os.scandir(d)
        except OSError:
            result.skipped.append(d)
            continue
        with it:
            for entry in it:
                try:
                    if _is_link_or_junction(entry):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        prog.files += 1
                        prog.bytes += st.st_size
                        if st.st_size >= min_size:
                            item = (st.st_size, entry.path, st.st_mtime)
                            if len(heap) < limit:
                                heapq.heappush(heap, item)
                            elif item > heap[0]:
                                heapq.heapreplace(heap, item)
                except OSError:
                    continue
        now = time.monotonic()
        if on_progress and now - last_report >= progress_every:
            last_report = now
            on_progress(prog)

    result.files = [FileEntry(p, s, m) for s, p, m in sorted(heap, reverse=True)]
    result.seconds = time.monotonic() - start
    if on_progress:
        on_progress(prog)
    return result
