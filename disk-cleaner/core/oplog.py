"""操作日志：每次删除写一行 JSON 到 logs/ 文件夹。"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path


def default_log_dir() -> Path:
    """打包后写到 %LOCALAPPDATA%\\Liubai\\logs（装在 Program Files 时 exe 旁边不能写）；
    开发时写到项目根目录的 logs。"""
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Liubai" / "logs"
    return Path(__file__).resolve().parent.parent / "logs"


class OpLog:
    def __init__(self, log_dir: Path | str | None = None):
        self.dir = Path(log_dir) if log_dir else default_log_dir()
        self.unsaved: list[dict] = []  # 写不进文件的记录先留在内存里，界面可以提示

    def _file(self) -> Path:
        return self.dir / f"{_dt.date.today():%Y-%m-%d}.jsonl"

    def write(self, action: str, path: str, size: int, ok: bool, error: str = "", **extra) -> None:
        """写一条记录。写日志失败绝不能打断清理（否则会停在一半），失败的先记在内存里。
        action：trash 移到回收站 / move 移动 / undo 撤销移动。移动还会记 dst（新位置）和 batch（批次）。"""
        rec = {
            "time": _dt.datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "path": path,
            "size": size,
            "ok": ok,
            "error": error,
            **extra,
        }
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self._file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            self.unsaved.append(rec)

    def read_all(self) -> list[dict]:
        out: list[dict] = []
        if not self.dir.is_dir():
            return out
        for fp in sorted(self.dir.glob("*.jsonl")):
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            out.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        return out


def open_in_explorer(path: str) -> None:
    """在资源管理器中选中文件（只是打开窗口，不改任何东西）。"""
    if os.name == "nt":
        import subprocess
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
