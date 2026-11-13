# 磁盘清理工具（Windows）

这是一个 Windows 磁盘清理和文件整理工具，用 Python 3.10+ + CustomTkinter，最后用 PyInstaller 打包成 exe。

## 安全规则（必须遵守，任何改动都不能绕过）

- 所有删除都通过 `core/cleaner.py` 的 `move_to_trash()`，它用 send2trash 移到回收站。**禁止**在任何地方调用 `os.remove`、`os.unlink`、`shutil.rmtree`、`Path.unlink` 等永久删除函数。
- 任何删除前必须先显示列表让用户确认（UI 里弹确认框，写明数量和总大小）。
- 默认只扫描和预览（dry run）。扫描代码只读，不写、不移动任何文件。
- 禁止操作系统目录：判断统一用 `core/safety.py` 的 `is_protected()`，扫描时跳过、删除时再检查一次。新增受保护目录只改 `safety.py`。
- 每次删除操作写日志到 `logs/` 文件夹（JSON Lines，一行一个文件），记录时间、路径、大小、结果。
- 不跟随符号链接和目录联接（junction），避免扫到别处或循环。
- 测试只在临时文件夹里进行，不要拿真实磁盘开刀。

## 结构

- `core/`：不依赖界面的逻辑（扫描、安全检查、删除、日志、格式化），可单独测试
- `ui/app.py`：主窗口，左侧 150px 导航 + 右侧内容区
- `ui/pages/`：每个页面一个类，继承 `BasePage`
- `cli.py`：命令行版本，方便排查
- `tests/`：pytest 测试

## 约定

- 耗时操作（扫描、计算哈希）必须放后台线程，通过 `queue` + `after()` 把进度送回界面，界面不能卡死，并且可以取消。
- 界面文字用中文。删除按钮写"移到回收站"，不写"删除"。
- 安全的项目（临时文件、旧安装包）默认勾选；有风险的（大文件、重复文件）默认不勾选。
- 改完运行 `python -m pytest tests`。
