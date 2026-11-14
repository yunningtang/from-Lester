"""只读的文件系统小工具。"""
from __future__ import annotations

import os
import stat
import threading


def is_link_or_junction(entry: os.DirEntry) -> bool:
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


def folder_size(path: str, cancel: threading.Event | None = None,
                exclude: set[str] | frozenset[str] = frozenset()) -> int:
    """统计文件夹大小（只读）。不跟随链接；exclude 里是 normcase 后的绝对路径。

    统计大小可以进入程序数据目录，因为它只是读文件大小，不列出也不删除任何东西。
    """
    if os.path.isfile(path):
        try:
            return os.stat(path).st_size
        except OSError:
            return 0
    total = 0
    stack = [path]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        d = stack.pop()
        if exclude and os.path.normcase(os.path.abspath(d)) in exclude:
            continue
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if is_link_or_junction(e):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        total += e.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    return total
