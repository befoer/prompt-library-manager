# 词库管理器（Prompt Library Manager）

本地运行的 **Prompt / Tag 文本词库管理工具**，用于管理 ComfyUI Wildcard / 文本列表批量随机生成使用的 TXT 词库。

> **重要**：这不是训练集 caption 管理器，也不是图片标注工具。TXT 与图片无任何关联。
> **一行 = 一个随机候选项**。`Fantasy Room, messy room, Strange Plants` 是一整行，就是一个候选项，
> 绝不把行内逗号拆开，导出 TXT 时也只输出原始文本（不输出 JSON / 翻译 / ID）。

---

## 快速开始

**绿色免安装**：解压 `词库管理器.zip`，进入文件夹双击 `PromptLibraryManager.exe` 即可运行，无需安装 Python。

- 文件夹形式：`PromptLibraryManager.exe` + `_internal\` 依赖目录（整体拷贝即可）
- `Tags\` 为离线翻译词典，可直接增删修改
- `txt\` 为词库文件夹（放你的 TXT 词库，也可用菜单打开任意文件夹）

技术栈：Python 3.10+ / PySide6（Qt）。纯本地运行，无云依赖。

> **从源码运行**（开发者）：需 Python 3.10+，先 `pip install -r requirements.txt`，再 `python main.py`。

---

## 已实现功能

### Phase 1 —— 核心编辑
- 文件夹模式：打开词库目录，左侧列出全部 `*.txt`；新建 / 重命名 / 删除 / 刷新词库
- Entry 编辑：整行为一个条目；双击 / Enter 行内编辑（Enter 保存、Esc 取消）
- 新增、删除、批量删除（勾选后删除，带确认）、右键菜单（编辑 / 复制 / 删除）
- 实时搜索：**包含**（默认，不区分大小写）/ 前缀 / 精确 / 正则；命中高亮；Esc 清除搜索
- 去重（保留首次出现，先提示数量再确认）
- 排序：原始顺序（可恢复）/ A→Z / Z→A / 中文拼音 / 长度 / 随机
- 导入 TXT（自动清理：CRLF/LF/CR、UTF-8 BOM、首尾空格、空行）
- 导出 TXT（仅 text 字段，UTF-8，原子写入）；可选「原文 + 中文翻译」格式，分隔符可自定义（默认 ", "）
- 编码自动识别：UTF-8 / UTF-8 BOM / UTF-16 / GBK(GB18030)
- 🎲 随机抽取（单条 / 多条，单条显示翻译结果）
- 自动保存（每步操作后自动写盘）+ `Ctrl+S` 手动保存
- `Ctrl+Z` / `Ctrl+Shift+Z` 撤销重做
- 外部修改检测：无未保存修改时自动重载；有修改时弹出 [重新载入 / 保留当前修改 / 查看差异]
- 拖拽 TXT / 文件夹到窗口打开
- QListView 虚拟滚动：20 万行流畅加载 / 搜索 / 排序

### Phase 2 —— 批量操作
- **批量替换**：不区分大小写；可选「当前词库」（可撤销）或「所有词库」（直接写文件，先统计再确认）
- **批量复制 / 移动到其他词库**：目标词库下拉选择；移动时源词库可用 Ctrl+Z 撤销
- 复制选中条目到剪贴板

### Phase 3 —— 中文翻译
- **双语显示**：列表两栏（左英文、右中文）；状态圆点：灰=未翻译，绿=已翻译，橙=翻译需更新（原文被修改后自动标记）
- **紧凑布局**：英文紧邻中文（如 `1girl | 1女孩`），工具栏「紧凑」按钮切换
- **离线词典翻译**：自动加载 `Tags/zh-CN.txt`（约 2.4 万条英中对照）+ danbooru/e621 别名表；多 tag 条目逐项翻译后拼接
  - 数据来源：`zh-CN.txt` 为英中对照；`danbooru.csv` / `e621.csv` 别名表来自 [BooruDatasetTagManager](https://github.com/starik222/BooruDatasetTagManager)（MIT License）
- **在线翻译**：OpenAI 兼容 API（Base URL / API Key / Model 自定义）或 **百度翻译**（AppID/密钥）；并发批量请求、失败逐条重试
- **懒加载翻译**：点工具栏翻译图标只翻译可见部分，滚动到下方继续翻译，避免超大文档浪费额度
- **内联翻译按钮**：未翻译条目中文栏显示翻译按钮，点击翻译该条；部分翻译（词典只命中一部分）可用在线翻译替换
- **翻译缓存**：结果自动写入本地 JSON（AppData），下次直接命中；可一键清空
- **翻译旁车文件**：翻译不写入 TXT，单独存 `<词库名>.txt.zh.json`，重启自动恢复；修改原文不会丢旧翻译
- 翻译设置对话框：测试连接、词典目录选择、缓存管理

### Phase 4 —— CSV / 统计 / 合并 / 差异
- **CSV 导入导出**：英中对照（第一列 English、第二列 Chinese，自动跳过表头）
- **Tag 统计**：按逗号统计当前词库内 tag 频率
- **词库合并**：多选词库合并到当前词库（可撤销）或另存为新文件，可选去重
- **词库差异比较**：两个词库的增删统计 + 逐行 diff 预览

### 快捷键
| 按键 | 功能 |
| --- | --- |
| Ctrl+O / Ctrl+Shift+O | 打开 TXT / 打开文件夹 |
| Ctrl+S | 保存当前词库 |
| Ctrl+F | 聚焦搜索框 |
| Ctrl+N | 新增条目 |
| Ctrl+Z / Ctrl+Shift+Z | 撤销 / 重做 |
| Delete | 删除选中 |
| Ctrl+A | 全选（用于批量操作） |
| Enter / Esc | 行内编辑保存 / 取消 |
| Esc | 清除搜索（非编辑态） |
| Ctrl+R | 随机抽取 |

---

## 数据安全

- TXT 是唯一数据源；导出/保存永远是纯文本 `entry` 列表，ComfyUI 可直接读取
- 保存采用「临时文件 + 原子替换」，不会写坏词库
- 翻译只存在旁车文件（`*.txt.zh.json`）与缓存中，删除即可丢弃
- 程序检测外部修改，不会无提示覆盖你正在编辑的文件
- **在线翻译密钥保存在系统注册表（按用户），不在程序目录或词库文件中**

---

## 目录结构

```
词库管理器/
├── main.py                    # 入口（源码运行用）
├── requirements.txt
├── txt/                       # 词库文件夹（用户数据）
│   └── *.txt
├── Tags/                      # 离线翻译词典（用户可自行修改）
│   ├── zh-CN.txt
│   ├── danbooru.csv
│   └── e621.csv
├── assets/                    # 图标资源（icon.png / icon.ico / 翻译.svg / splash.png）
├── app/
│   ├── resources.py           # 资源定位（图标等）
│   ├── core/
│   │   ├── io.py              # 编码识别 / 行规范化 / 原子写入
│   │   ├── model.py           # Library / PromptEntry / 翻译旁车 / 脏标记
│   │   ├── commands.py        # 撤销命令
│   │   ├── dictionary.py      # 离线英中词典 + 别名归一化
│   │   ├── ai_translate.py    # 在线翻译（OpenAI/百度）+ 缓存 + 工作线程
│   │   └── library_ops.py     # 跨词库复制移动 / 文件级批量替换
│   └── ui/
│       ├── main_window.py     # 主窗口 / 菜单 / 快捷键
│       ├── entry_view.py      # 虚拟列表 + 自绘 delegate（两栏 / 复选框 / 状态点）
│       ├── entry_model.py     # 列表模型 + 过滤
│       ├── sidebar.py         # 左侧词库列表
│       ├── dialogs.py         # 随机抽取 / 差异查看 / 确认
│       ├── icons.py           # 程序化绘制的图标
│       ├── translate_dialogs.py  # 翻译设置 / 批量替换 / 复制移动
│       └── theme.py           # 深色主题样式
└── tests/smoke_test.py        # 冒烟测试（95 项）
```

---

## 测试

```bat
python tests/smoke_test.py
```

覆盖：编码识别、CRUD 与撤销、排序去重、过滤、离线词典、翻译命令与旁车、
翻译缓存、批量替换、跨词库复制移动、在线翻译接口（本地 mock 服务器）、GUI 双语流程。
