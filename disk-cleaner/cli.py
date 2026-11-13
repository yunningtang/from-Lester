"""命令行版本：扫描大文件（只读）。

用法：
    python cli.py large D:\\Downloads --min 100MB --top 50
"""
from __future__ import annotations

import argparse
import sys

from core.scanner import scan_large_files
from core.utils import format_time, human_size, parse_size


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="磁盘清理工具（命令行，只读）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("large", help="列出大文件")
    lg.add_argument("folder")
    lg.add_argument("--min", default="100MB", help="最小大小，如 100MB、1GB（默认 100MB）")
    lg.add_argument("--top", type=int, default=50, help="最多显示多少个（默认 50）")
    args = ap.parse_args(argv)

    if args.cmd == "large":
        res = scan_large_files(args.folder, parse_size(args.min), args.top)
        print(f"扫描 {res.progress.files} 个文件，用时 {res.seconds:.1f} 秒，"
              f"找到 {len(res.files)} 个 ≥ {args.min} 的文件：\n")
        for f in res.files:
            print(f"{human_size(f.size):>10}  {format_time(f.mtime)}  {f.path}")
        if res.skipped:
            print(f"\n跳过 {len(res.skipped)} 个受保护或无权限的目录")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
