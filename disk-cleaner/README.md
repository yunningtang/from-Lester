# 磁盘清理（Windows）

用 Python + CustomTkinter 做的磁盘清理和文件整理工具。第一版：**概览**、**大文件**、**操作日志** 三个页面可以用，其他页面是占位。

![大文件页面](docs/large-files.png)

## 安全设计

- 扫描只读，不改动任何文件
- 删除一律用 `send2trash` **移到回收站**，可以恢复；代码里没有任何永久删除调用（有测试检查这一点）
- 删除前弹窗确认，写明数量、总大小和文件列表
- 不扫描、不删除系统目录：`C:\Windows`、`Program Files`、`ProgramData`、`AppData`、`pagefile.sys` 等（见 `core/safety.py`）
- 不跟随符号链接和目录联接（junction）
- 每次删除都写日志到 `logs/YYYY-MM-DD.jsonl`，在“操作日志”页面可以查看

## 在 Windows 上运行

1. 安装 [Python 3.10+](https://www.python.org/downloads/)，安装时勾选 “Add python.exe to PATH”
2. 在这个文件夹里打开终端（PowerShell）：

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

```bash
python main.py
```

命令行版本（只读，方便排查）：

```bash
python cli.py large D:\Downloads --min 100MB --top 50
```

运行测试：

```bash
pip install pytest
```

```bash
python -m pytest tests
```

## 打包成 exe

```bash
pip install pyinstaller
```

```bash
pyinstaller --noconfirm --windowed --name 磁盘清理 --collect-data customtkinter main.py
```

生成的程序在 `dist\磁盘清理\磁盘清理.exe`，整个 `dist\磁盘清理` 文件夹可以拷给别人用。日志写在 exe 旁边的 `logs` 文件夹。

## 项目结构

```
core/            界面无关的逻辑，可单独测试
  safety.py      受保护目录判断（扫描和删除都要经过这里）
  scanner.py     只读扫描器（后台线程、可取消、进度回调）
  cleaner.py     唯一的删除入口：移到回收站 + 写日志
  oplog.py       操作日志
  utils.py       大小、时间格式化
ui/
  app.py         主窗口：左侧 150px 导航 + 右侧内容区，NAV 列表里加一项就多一个页面
  theme.py       颜色和字体
  pages/         每个页面一个类
cli.py           命令行版本
main.py          图形界面入口
tests/           pytest 测试
CLAUDE.md        给 Claude Code 的规则（安全规则写在这里）
```

## 下一步（建议按顺序让 Claude Code 做）

1. **重复文件**：先按大小分组 → 比较前 64KB 的哈希 → 再比较完整 SHA-256；每组默认保留最早的一份
2. **文件整理**：下载文件夹按类型或月份分类，先预览，确认后移动，记录日志以便撤销
3. **临时文件**：`%TEMP%`、Chrome / Edge 缓存、旧安装包，默认勾选，跳过被占用的文件
4. **内存占用**：用 psutil 列出占内存最多的程序，由用户决定是否关闭
5. **设置**：外观、排除目录、日志保留天数

给 Claude Code 的示例指令：

```
按 CLAUDE.md 的规则实现"重复文件"页面：新建 core/duplicates.py（只读，后台线程，可取消），
再新建 ui/pages/duplicates.py 替换 ui/app.py 里的占位。先写 tests/ 里的测试，再写界面。
```
