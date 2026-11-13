"""受保护目录判断。所有扫描和删除都必须经过这里。

新增受保护目录只改这个文件。
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    return Path(v) if v else None


def _windows_protected() -> list[Path]:
    system_drive = os.environ.get("SystemDrive", "C:") + "\\"
    candidates = [
        _env_path("SystemRoot") or Path(system_drive, "Windows"),
        _env_path("ProgramFiles") or Path(system_drive, "Program Files"),
        _env_path("ProgramFiles(x86)") or Path(system_drive, "Program Files (x86)"),
        _env_path("ProgramW6432"),
        _env_path("ProgramData") or Path(system_drive, "ProgramData"),
        Path(system_drive, "$Recycle.Bin"),
        Path(system_drive, "System Volume Information"),
        Path(system_drive, "Recovery"),
        Path(system_drive, "Boot"),
        Path(system_drive, "pagefile.sys"),
        Path(system_drive, "hiberfil.sys"),
        Path(system_drive, "swapfile.sys"),
    ]
    # AppData 只允许清理缓存类子目录，其余全部保护（后续"临时文件"页面单独放行 %TEMP%）
    appdata = _env_path("APPDATA")
    local = _env_path("LOCALAPPDATA")
    candidates += [p for p in (appdata, local) if p]
    return [p for p in candidates if p]


def _posix_protected() -> list[Path]:
    # 方便在 macOS / Linux 上开发测试
    names = ["/System", "/Library", "/bin", "/sbin", "/usr", "/etc", "/var",
             "/boot", "/dev", "/proc", "/sys", "/lib", "/lib64", "/opt", "/Applications"]
    return [Path(n) for n in names]


def _norm(p: Path | str) -> str:
    try:
        resolved = Path(p).resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = Path(os.path.abspath(p))
    return os.path.normcase(str(resolved)).rstrip("\\/")


_PROTECTED: list[str] = [
    _norm(p) for p in (_windows_protected() if os.name == "nt" else _posix_protected())
]
_EXTRA: list[str] = []


def add_protected(path: Path | str) -> None:
    """额外加入受保护路径（设置页或测试用）。"""
    _EXTRA.append(_norm(path))


def is_drive_root(path: Path | str) -> bool:
    p = Path(_norm(path) or os.sep)
    return p.parent == p or str(p) in ("", os.sep)


def is_protected(path: Path | str) -> bool:
    """path 是受保护目录本身或在其内部时返回 True。"""
    target = _norm(path)
    for base in _PROTECTED + _EXTRA:
        if target == base or target.startswith(base + os.sep):
            return True
    return False


def can_delete(path: Path | str) -> tuple[bool, str]:
    """删除前的最终检查。返回 (是否允许, 原因)。"""
    if is_drive_root(path):
        return False, "不能删除磁盘根目录"
    if is_protected(path):
        return False, "系统受保护目录"
    if not os.path.lexists(path):
        return False, "文件已不存在"
    return True, ""
