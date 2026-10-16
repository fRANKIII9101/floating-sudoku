# 悬浮窗数独 · SudokuFloat

常驻桌面、半透明、随手可玩的数独小工具。用 **Python + tkinter** 打造的真悬浮窗，工作间隙也能摸鱼来一局。

![界面预览](https://cdn.jsdelivr.net/gh/fRANKIII9101/floating-sudoku@main/preview.png)

> 图片若未显示，可点此直接查看：[界面预览](https://cdn.jsdelivr.net/gh/fRANKIII9101/floating-sudoku@main/preview.png)

## 功能特性

- **真悬浮窗**：始终置顶、半透明、可拖动，不抢键盘焦点，工作时也能随手点开
- **两种玩法**：经典普通数独 / 杀手数独（笼内求和）
- **智能提示**：一键填候选数、按难度给定提示数字
- **笔注系统**：Ctrl 切换笔注模式，Shift 多选格批量加小笔记
- **进度自动保存**：关掉再开，棋盘原样恢复
- **托盘常驻**：系统托盘图标切换模式 / 调整透明度 / 开新局

## 模式说明

### 普通模式

经典 9×9。鼠标点格 + 键盘输入，难度按挖空数量区分：

| 难度 | 给定数字 |
| -- | ---- |
| 简单 | 41   |
| 中等 | 34   |
| 困难 | 30   |
| 专家 | 27   |

### 杀手模式

棋盘被切成若干个「笼（cage）」，每笼标注内部数字之和，同一笼内数字互不相同。给定提示数字：简单 12 / 中等 8 / 困难 4 / 专家 0（专家为纯笼题）。

![候选数预览](https://cdn.jsdelivr.net/gh/fRANKIII9101/floating-sudoku@main/preview_candidates.png)

> 图片若未显示，可点此直接查看：[候选数预览](https://cdn.jsdelivr.net/gh/fRANKIII9101/floating-sudoku@main/preview_candidates.png)

## 操作

- 点击格子选中；键盘 `1`–`9` 落子，`0` / `Backspace` 擦除
- **Ctrl**：单击切换「笔注模式」；`Ctrl + 数字` 在该格写小笔记
- **Shift + 点击**：多选格子（绿框标记），多选状态下 `Ctrl + 数字` 对**所有选中格**批量加笔记
- **点击窗口空白**：取消选择，便于专注思考
- 方向键移动选中格；`Ctrl + Z` / `Ctrl + Y` 撤销 / 重做
- `Q W E` / `A S D` / `Z X C`：在 3×3 子格内快速输入对应位置的数字

## 运行方式

### 方式一：直接运行 exe（推荐）

从 Releases 下载 `SudokuFloat.exe`，双击即用，无需安装 Python 环境。

### 方式二：源码运行

需要 Python 3（自带 tkinter）：

```bash
python sudoku_floating.py
```

## 打包（开发者）

本机需标准 CPython（含 tkinter）。仓库内已附带 `build.bat`，双击即可生成单文件 exe：

```bash
pyinstaller --onefile --windowed --name SudokuFloat --hidden-import pystray._win32 sudoku_floating.py
```

产物位于 `dist/SudokuFloat.exe`。建议将 exe 作为 Release 附件发布，源码仓库不纳入 `dist/`（已由 `.gitignore` 排除）。

## 关于题库

**没有静态题库**——每一局都由算法实时生成：

- 普通模式：随机回溯生成完整解 → 按难度挖空，并用 MRV 回溯保证**唯一解**
- 杀手模式：随机完整解 + 随机连通 cage 划分 + 计算各 cage 求和，保证笼内数字互异、覆盖全部 81 格、无单格笼

## 文件结构

| 文件                   | 说明                       |
| -------------------- | ------------------------ |
| `sudoku_floating.py` | 主界面与交互                   |
| `sudoku_core.py`     | 普通数独出题与唯一解校验             |
| `killer_core.py`     | 杀手数独生成                   |
| `selftest.py`        | 自测脚本（约 60 项断言，覆盖交互与生成逻辑） |
| `build.bat`          | 一键打包脚本                   |

## 许可证

MIT

