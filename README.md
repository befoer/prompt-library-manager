# Prompt Library Manager — Phase 1

一个**本地桌面应用**（PySide6 / Qt），用于管理 ComfyUI Wildcard / 文本列表随机生成使用的
**TXT Prompt 词库**。

> 本项目**不是**训练集 caption 管理器，也不是图片标注工具。TXT 与图片没有任何关联。

## 核心原则

- **一行 = 一个随机候选项**。`Fantasy Room, messy room, Strange Plants` 是一个 Entry，
  绝不会拆开，也绝不自动加逗号。
- 最终文件始终是 ComfyUI 可直接读取的**普通 TXT**，不转 JSON / YAML / 数据库。
- 导出 TXT 时**只输出 text 字段**（中文翻译等内部字段不会混入）。

## 运行

```bash
# 1) 安装依赖（首次）
pip install -r requirements.txt

# 2) 启动
python main.py
```

Windows 下也可以直接双击 `run.bat`（会自动补装依赖再启动）。

> 示例词库在 `txt/` 文件夹（表情 / 场景 / 角色）。`Tags/` 里的中英对照文件留给后续
> 翻译阶段（Phase 3）使用。

## Phase 1 已实现功能

| 功能 | 说明 |
| --- | --- |
| 打开词库文件夹 | 左侧自动列出目录下所有 `.txt`，启动时自动恢复上次文件夹 |
| 打开 / 新建 / 重命名 / 删除 TXT | 侧栏按钮 + 右键菜单；新建自动补 `.txt` 后缀 |
| 显示全部条目 | QListView 虚拟滚动，10 万行不卡顿 |
| 实时搜索 | 默认"包含"（不区分大小写）；支持前缀 / 精确 / 正则 |
| 新增条目 | `Ctrl+N`，底部新增空行，Enter 保存 / Esc 取消 |
| 编辑条目 | 双击或 Enter 进入编辑，回车保存、Esc 取消 |
| 删除 / 批量删除 | `Delete` 删除选中；批量有确认提示，均可 Ctrl+Z 撤销 |
| 去重 | 整行精确匹配、保留首次出现，先报数量再确认 |
| 排序 | 原始顺序（可恢复）/ A→Z / Z→A / 中文拼音 / 长度 / 随机 |
| 拖拽排序 | 直接拖动条目调整顺序；有筛选时自动禁用避免冲突 |
| 导入 TXT | 追加到当前词库，自动清理首尾空格与空行 |
| 导出 TXT | 只输出 text 字段，UTF-8，原子写入 |
| 随机抽取 | 🎲 单条 / 多条（带"再抽一次"、复制） |
| 编码识别 | 自动识别 UTF-8 / UTF-8 BOM / UTF-16 / GBK(GB18030) |
| 保存 | `Ctrl+S`；未保存修改在关闭/切换时提示 [保存并继续/放弃修改/取消] |
| 撤销 / 重做 | `Ctrl+Z` / `Ctrl+Shift+Z`，覆盖增删改、排序、拖拽、去重、导入 |
| 外部修改检测 | 词库文件被其他程序修改时提示 [重新载入/保留当前修改/查看差异] |
| 拖拽文件到窗口 | 拖入 `.txt` 直接打开，拖入文件夹直接切换词库文件夹 |
| 自动保存设置 | 记住上次文件夹、窗口大小、侧栏宽度 |

## 快捷键

| 快捷键 | 功能 |
| --- | --- |
| `Ctrl+O` | 打开 TXT |
| `Ctrl+Shift+O` | 打开词库文件夹 |
| `Ctrl+S` | 保存当前词库 |
| `Ctrl+F` | 聚焦搜索 |
| `Ctrl+N` | 新增条目 |
| `Ctrl+Z` / `Ctrl+Shift+Z` | 撤销 / 重做 |
| `Ctrl+A` | 全选条目 |
| `Ctrl+R` | 随机抽取 1 条 |
| `Ctrl+I` / `Ctrl+E` | 导入 / 导出 TXT |
| `Delete` | 删除选中 |
| `Enter` | 编辑选中条目 |
| `Esc` | 取消编辑 |

所有功能都有可见的按钮或菜单（快捷键不是唯一入口）。

## 数据安全

- TXT 文件是**唯一数据源**：修改先发生在内存中（标题显示 `●` 未保存），
  `Ctrl+S` 才写盘；写盘采用"临时文件 + 原子替换"，不会写坏词库。
- 保存/导出统一为 UTF-8（无 BOM），读取时兼容 UTF-8 / UTF-8 BOM / GBK。
- 外部程序（ComfyUI / 编辑器）改了文件会检测到并提示，不会无提示覆盖。

## 目录结构

```
main.py                 # 入口
app/
  core/
    io.py               # 编码识别、行规范化、原子写入
    model.py            # Library / PromptEntry 数据模型
    commands.py         # 撤销/重做命令
  ui/
    theme.py            # 深色主题 QSS
    entry_model.py      # 虚拟列表模型 + 过滤 + 拖拽
    entry_view.py       # 列表视图 + 自绘 delegate
    sidebar.py          # 左侧词库列表
    dialogs.py          # 随机抽取 / 差异 / 确认对话框
    main_window.py      # 主窗口
tests/smoke_test.py     # 冒烟测试（无界面模式运行）
```

## 路线图

- **Phase 2**：批量替换、CSV 导入导出、统计信息增强
- **Phase 3**：中文翻译、中英双语显示、AI API 配置（OpenAI 兼容 + 百度翻译 + 翻译缓存）、
  翻译状态标记
- **Phase 4**：Tag 分类、词库合并、词库差异比较
- **Phase 5**：性能优化、桌面打包（PyInstaller）
