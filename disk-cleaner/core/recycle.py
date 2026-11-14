"""回收站：唯一真正动文件的地方。

为什么不直接用 send2trash：
在 Windows 上，send2trash 用 FOF_NOCONFIRMATION 调用系统删除。文件放不进回收站时
（比回收站容量还大、U 盘或网络盘没有回收站、回收站被关掉），Windows 会**直接永久删除**，
不会提示。这正是本软件绝不能发生的事。

所以这里：
1. 删除前先检查：本地固定磁盘、回收站开着、单个文件不超过回收站容量。不满足就拒绝。
2. 真正删除时加上 FOF_WANTNUKEWARNING：万一 Windows 仍决定永久删除，会先弹窗问用户，
   而不是悄悄删掉。
3. 删完检查文件确实不在原处了。

非 Windows（开发和测试）用 send2trash。
"""
from __future__ import annotations

import os
import shutil

WINDOWS = os.name == "nt"

DRIVE_FIXED = 3
# Windows 默认回收站容量大约是磁盘的 5%–10%；读不到设置时按 5% 保守估计
DEFAULT_BIN_FRACTION = 0.05


# ---------------- 读回收站设置（只读） ----------------

def _volume_root(path: str) -> str:
    if not WINDOWS:
        return os.path.abspath(os.sep)
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetVolumePathNameW(os.path.abspath(path), buf, 1024):
        return buf.value
    return os.path.splitdrive(os.path.abspath(path))[0] + "\\"


def drive_type(path: str) -> int:
    """3 = 本地固定磁盘；2 = U 盘；4 = 网络盘。非 Windows 一律当作固定磁盘。"""
    if not WINDOWS:
        return DRIVE_FIXED
    import ctypes
    return int(ctypes.windll.kernel32.GetDriveTypeW(_volume_root(path)))


def _volume_guid(path: str) -> str | None:
    if not WINDOWS:
        return None
    import ctypes
    buf = ctypes.create_unicode_buffer(64)
    if ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(_volume_root(path), buf, 64):
        v = buf.value  # \\?\Volume{xxxxxxxx-...}\
        i, j = v.find("{"), v.find("}")
        if i >= 0 and j > i:
            return v[i:j + 1]
    return None


def bin_settings(path: str) -> tuple[bool, int | None]:
    """(回收站是否开着, 容量字节数或 None)。读注册表，读不到就返回默认 (True, None)。"""
    if not WINDOWS:
        return True, None
    guid = _volume_guid(path)
    if not guid:
        return True, None
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume" + "\\" + guid
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            def val(name):
                try:
                    return winreg.QueryValueEx(k, name)[0]
                except OSError:
                    return None
            nuke = val("NukeOnDelete")
            cap_mb = val("MaxCapacity")
        return (nuke != 1), (int(cap_mb) * 1024 * 1024 if cap_mb else None)
    except OSError:
        return True, None


def bin_capacity(path: str) -> int:
    enabled, cap = bin_settings(path)
    if cap:
        return cap
    try:
        return int(shutil.disk_usage(_volume_root(path)).total * DEFAULT_BIN_FRACTION)
    except OSError:
        return 0


def bin_used(path: str) -> int:
    """回收站里现在有多少（这个盘）。"""
    if not WINDOWS:
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        class SHQUERYRBINFO(ctypes.Structure):
            _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1
            _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong),
                        ("i64NumItems", ctypes.c_longlong)]
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        if ctypes.windll.shell32.SHQueryRecycleBinW(_volume_root(path), ctypes.byref(info)) == 0:
            return int(info.i64Size)
    except Exception:
        pass
    return 0


def check_recyclable(path: str, size: int) -> tuple[bool, str]:
    """这个文件能不能确定放进回收站。不能就说明原因。"""
    t = drive_type(path)
    if t != DRIVE_FIXED:
        kind = {2: "U 盘或移动硬盘", 4: "网络盘", 5: "光盘"}.get(t, "这种盘")
        return False, f"{kind}没有回收站，删了就找不回来，留白不处理"
    enabled, _ = bin_settings(path)
    if not enabled:
        return False, "这个盘的回收站被关掉了，删了就找不回来，留白不处理"
    cap = bin_capacity(path)
    if cap and size > cap:
        return False, "比回收站的容量还大，放不进回收站，留白不处理"
    return True, ""


# ---------------- 真正移到回收站 ----------------

def _recycle_windows(path: str) -> None:
    import ctypes
    from ctypes import wintypes

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO = 0x4, 0x10, 0x40
    FOF_NOERRORUI, FOF_WANTNUKEWARNING = 0x400, 0x4000

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    full = os.path.abspath(path)
    buf = ctypes.create_unicode_buffer(full + "\0")  # 双 \0 结尾
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    # 允许撤销 = 进回收站；万一要永久删除，系统会先弹窗问
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT | FOF_WANTNUKEWARNING
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        raise OSError(rc, f"Windows 返回错误 0x{rc:X}（文件可能正在使用）")
    if op.fAnyOperationsAborted:
        raise OSError(0, "操作被取消")


def _recycle_other(path: str) -> None:
    from send2trash import send2trash
    send2trash(path)


def recycle(path: str) -> None:
    """把一个文件或文件夹移到回收站；失败抛 OSError。调用前必须先过 safety.can_delete。"""
    (_recycle_windows if WINDOWS else _recycle_other)(path)
    if os.path.lexists(path):
        raise OSError(0, "移动后文件还在原处，可能有部分文件正在使用")
