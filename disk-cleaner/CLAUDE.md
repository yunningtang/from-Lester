# 磁盘清理工具（Windows）

这是一个 Windows 磁盘清理和文件整理工具，用 Python 3.10+ + CustomTkinter，最后用 PyInstaller 打包成 exe。

## 安全规则（必须遵守，任何改动都不能绕过）

### 删除只有一条路
- 只有 `core/recycle.py` 能真正动文件，只有 `core/cleaner.py` 能调用它。**禁止**在任何地方调用 `os.remove`、`os.unlink`、`shutil.rmtree`、`Path.unlink`、`send2trash` 等（测试会检查）。
- 删除分两步：`cleaner.preflight()` 只读预检，得到 Plan（能移的、不能移的和原因、提醒）→ 界面把 Plan 给用户确认（`ui/confirm.py`）→ `cleaner.execute()` 对每一项**再查一次**后移到回收站。
- 不要在 Windows 上直接用 send2trash：它带 FOF_NOCONFIRMATION，文件放不进回收站时 Windows 会**悄悄永久删除**。`recycle.py` 先检查（本地固定磁盘、回收站开着、不超过回收站容量），再带 FOF_WANTNUKEWARNING 调用系统，删完确认文件确实离开了原处。
- 移到回收站**不会**腾出空间，清空回收站后才会。界面不能写“已释放”；回收站留白不替用户清空。

### 什么不能删（`core/safety.py`，新增规则只改这个文件）
- HARD：Windows、Program Files、ProgramData、pagefile.sys 等，任何情况都不删。
- SOFT：AppData。只有 `SAFE_CACHES` 名单里的缓存目录*里面*的内容可以删。
- KEEP：主目录、桌面、文档、下载等文件夹**本身**以及它们的上级（如 C:\Users）不能删，里面的文件可以。
- CLOUD：OneDrive 里的文件不删（删除会同步到云端和其他设备）。
- 链接和目录联接本身不删，也不跟随。路径的字面形式和解析后的真实形式都要通过检查。
- 缓存目录要通过 `_sane_cache_root`：不能是磁盘根目录、主目录或重要文件夹的上级；“临时文件”目录必须叫 Temp/tmp（防止 TEMP 环境变量被改成别处）。
- 扫描后文件变了（大小或修改时间不同），这次就不删，提示重新扫描。缓存项删除前重新核对名字和时间条件。

### 其他
- 默认只扫描和预览。扫描代码只读。
- 你的文件（大文件、重复文件）从不默认选中；旧安装包只认名字像安装包的，且默认不选。
- 只读统计大小可以进入 AppData；OneDrive“仅在线”的占位文件不占硬盘，不计入。
- 每一项都写日志（JSON Lines）。打包后日志在 %LOCALAPPDATA%\Liubai\logs。写日志失败不能打断清理。
- 一项失败不影响其他项。
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
- 缓存类默认勾选；旧安装包、微信缓存和所有你的文件默认不勾选。
- 改完运行 `python -m pytest tests`。
