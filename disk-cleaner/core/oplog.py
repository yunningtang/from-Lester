"""操作日志：每次删除写一行 JSON 到 logs/ 文件夹。"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path


def default_log_dir() -> Path:
    # 打包成 exe 后写到 exe 旁边，开发时写到项目根目录
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "logs"


class OpLog:
    def __init__(self, log_dir: Path | str | None = None):
        self.dir = Path(log_dir) if log_dir else default_log_dir()

    def _file(self) -> Path:
        return self.dir / f"{_dt.date.today():%Y-%m-%d}.jsonl"

    def write(self, action: str, path: str, size: int, ok: bool, error: str = "") -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        rec = {
            "time": _dt.datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "path": path,
            "size": size,
            "ok": ok,
            "error": error,
        }
        with open(self._file(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

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
