# 磁盘清理工具（Windows）

这是一个 Windows 磁盘清理和文件整理工具，用 Python 3.10+ + CustomTkinter，最后用 PyInstaller 打包成 exe。

## 安全规则（必须遵守，任何改动都不能绕过）

- 所有删除都通过 `core/cleaner.py` 的 `move_to_trash()`，它用 send2trash 移到回收站。**禁止**在任何地方调用 `os.remove`、`os.unlink`、`shutil.rmtree`、`Path.unlink` 等永久删除函数。
- 任何删除前必须先显示列表让用户确认（UI 里弹确认框，写明数量和总大小）。
- 默认只扫描和预览（dry run）。扫描代码只读，不写、不移动任何文件。
- 禁止操作系统目录：判断统一用 `core/safety.py`，扫描时跳过、删除时 `can_delete()` 再检查一次。三层规则：
  - HARD（Windows、Program Files、ProgramData、pagefile.sys 等）：任何情况都不删。
  - SOFT（AppData）：默认不删，只有 `SAFE_CACHES` 名单里的缓存目录 *里面* 的内容可以移到回收站，缓存目录本身保留。
  - 新增受保护目录、新增可清理缓存，都只改 `safety.py`。
- 只读统计大小（`core/fs.py` 的 `folder_size`）可以进入 AppData 等目录，因为它只读文件大小，不列出也不删除。
- 回收站只显示大小，不提供"清空"（那是永久删除）。
- 每次删除操作写日志到 `logs/` 文件夹（JSON Lines，一行一个文件），记录时间、路径、大小、结果。
- 不跟随符号链接和目录联接（junction），避免扫到别处或循环。
- 测试只在临时文件夹里进行，不要拿真实磁盘开刀。

## 结构

- `core/`：不依赖界面的逻辑（扫描、安全检查、删除、日志、格式化），可单独测试
- `ui/app.py`：主窗口，左侧 150px 导航 + 右侧内容区
- `ui/pages/`：每个页面一个类，继承 `BasePage`
- `ui/pebble_layout.py`：石头地图的几何（不依赖 tk，可测试）；`ui/pebble_map.py`：画在 Canvas 上
- `core/space.py`：统计空间分类；`core/cleanables.py`：查找和清理可放心清理的项目
- `cli.py`：命令行版本，方便排查
- `tests/`：pytest 测试

## 视觉风格

日式极简：墨黑、石灰、米色，颜色都在 `ui/theme.py` 和 `ui/stone_theme.json`。
- 不加新颜色。唯一的强调色是危险操作的暗红 `DANGER`。
- 石头颜色按类别：你的文件=墨黑，程序=深灰，缓存=浅灰，系统=米灰，可用空间=等高线。
- tk.Canvas 不认 (浅色, 深色) 元组，用 `theme.pick()` 取颜色。
- 大数字用细字重，正文 12–13 号，界面上不用图标和 emoji。

## 约定

- 耗时操作（扫描、计算哈希）必须放后台线程，通过 `queue` + `after()` 把进度送回界面，界面不能卡死，并且可以取消。
- 界面文字用中文。删除按钮写"移到回收站"，不写"删除"。
- 安全的项目（临时文件、旧安装包）默认勾选；有风险的（大文件、重复文件）默认不勾选。
- 改完运行 `python -m pytest tests`。
