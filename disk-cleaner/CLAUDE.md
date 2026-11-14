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

- `main.py`：入口。优先用 pywebview 打开 `webui/`；没装 pywebview 时退回旧的 CustomTkinter 界面（`--tk` 也可以强制用旧界面）。
- `webui/`：新界面（HTML/CSS/JS）。`ink.js` 是纸和墨的几何与纹理，`app.js` 是界面逻辑。界面只调用后端，从不直接删文件。
- `core/api.py`：界面和后端之间唯一的接口，不依赖 pywebview，可直接测试。耗时的事都在后台线程，界面轮询 `state()`。
- `devserver.py`：开发用，在浏览器里打开界面，后端是真的 `Api`（会真的移动文件，请用假的主目录）。
- `core/`：扫描（scanner、space）、建议（inspect）、安全（safety）、删除（cleaner → recycle）、日志（oplog）、偏好（prefs）。
- `ui/`：旧的 CustomTkinter 界面，作为备用。
- `tests/`：pytest。`test_safety_flow.py` 一条安全规则一个测试；`test_api.py` 是完整流程。

## 视觉风格（留白）

- 只有纸和墨，没有彩色。纸色、墨色、字号都在 `webui/app.css` 开头。
- 墨色分五级，按占用大小：40 G 以上、20–40 G、8–20 G、3–8 G、3 G 以下。
- 可用空间是纸，所有文字写在纸上。标题栏透明，右上角按钮按底下的墨色自动变深浅。
- 信息层级：全貌 = 磁盘状态 → 可放心清理（按组）→ 值得看看（最大的三块你的文件）→ 回收站；
  细看 = 这是什么、多大、在哪 → 约多少可能不再需要 → 分组的文件 → 操作。
- 文字说人话，不说路径和扩展名；每个建议都写“为什么”，后果在确认时说。

## 约定

- 耗时操作（扫描、计算哈希）必须放后台线程，通过 `queue` + `after()` 把进度送回界面，界面不能卡死，并且可以取消。
- 界面文字用中文。删除按钮写"移到回收站"，不写"删除"。
- 缓存类默认勾选；旧安装包、微信缓存和所有你的文件默认不勾选。
- 改完运行 `python -m pytest tests`。
