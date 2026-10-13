# 提示窗口（提示 / 警告 / 确认）设计

日期：2026-09-21
状态：已实施（2026-09-23，见 plans/2026-09-21-prompt-windows.md）

## 1. 背景与目标

主窗口、编辑框、到点弹窗都已经统一成「纸与笔」那一套无边框圆角纸，但**应用内的提示仍然是系统灰弹窗**（原生 `#32770`），跟这套纸放在一起像两个软件。

本次把应用内的 5 处系统弹窗换成自家的纸窗口。

现状清单：

| 位置 | 现在 | 文案 |
| --- | --- | --- |
| `main_window.py:624` | `messagebox.showinfo` | 选中的是记录条目标题 / 请先选中便签 |
| `main_window.py:715` | `messagebox.showinfo` | 一次只能编辑一条便签 |
| `main_window.py:733` | `messagebox.showinfo` | 请先选中便签（删除路径） |
| `main_window.py:755` | `messagebox.askyesno` | 删除「XX」？此操作不可撤销。 |
| `edit_dialog.py:517` | `messagebox.showwarning` | 输入校验的 7 种文案 |

**不在范围内**：`app.py:178` 启动失败的致命报错保持系统弹窗 —— 那时主题和主窗口都还没装配起来，它必须能在「已经坏掉」的环境里弹出来。

## 2. 形态（已与用户确认）

用户在渲染图（真实主题搭出来的候选窗口）里选定：**色带窗口版形态 + 墨底主按钮**。

新窗口 = 编辑框那一族的缩小版：

- **纸宽固定 400**，高度按内容自适应：先建内容 → `update_idletasks()` 量高 → 最后 `paper_onto` 补纸（跟 `edit_dialog.open_editor` 的 `fit()` 同一套，抄它不要重写）
- **顶部色带 46px = 自制标题栏**：左边一个词（`提示` / `确认`），右边 ✕（`frameless.close_button`）
- `win.title(title)` 必须照设 —— 无边框之后系统不画它，但测试靠 `title()` 找这个窗口（编辑框里已经写着同一条理由）
- **正文**：雅黑 10pt、墨色 `theme.INK`、`wraplength = W - 2*PAD - 6` 折行
- **按钮**（右下角，右对齐）：
  - 提示：墨底 `frameless.ink_button`「知道了」
  - 确认：只有字 `frameless.quiet_button`「取消」+ 墨底「删除」（动作名由参数传入，不写死）
- **位置**：`center_on_parent(win, parent, ...)` —— 编辑框里弹的校验警告就居中在编辑框上
- **模态**：`grab_set()` + `wait_window()`
- **键盘**：`Enter` = 主按钮，`Esc` = 取消/关闭，外加 `focus_force()`
- 色带同时挂 `frameless.Dragger`（跟另外三个窗口一致：挡着东西时能推开）

### 2.1 两个必须写进注释的坑

1. **不调 `transient(parent)`**。无边框窗口上加 transient，Windows 会把窗口映射到 z 序最底 —— 提示框比父窗口小、又是居中的，会被 100% 盖住，而它还持着 grab，整个页面点不动。这正是 2026-09-21 编辑框那个 bug。
2. **关窗后要把 grab 还给原来那个窗口**。从编辑框里弹提示时，编辑框自己的 grab 会被提示框抢走；提示关掉后如果不管，编辑框就失去了模态（点主窗口会有反应）。做法：开窗前记 `prev = win.grab_current()`，`wait_window()` 返回后若 `prev` 还活着就 `prev.grab_set()`。

## 3. 接口

新增 `reminders/prompt.py`，只暴露两个入口：

```python
def notice(parent, message: str, title: str = "提示") -> None
    """机器贴上来的一句话：提示 / 校验警告。看完点「知道了」。"""

def confirm(parent, message: str, action: str = "删除", title: str = "确认") -> bool
    """要用户做个决定。点主按钮（动作名）返回 True，点取消/✕/Esc 返回 False。"""
```

`parent` 是定位与模态的基准窗口（主窗口或编辑框）。

内部共用一个 `_show(parent, message, title, buttons)`：`buttons` 是 `[(标签, 是否主按钮, 回调)]`，返回**被点中那个按钮的回调返回值**；用 ✕ / Esc 关掉（没有任何按钮被点）时返回 `None`，`confirm` 把它当 `False`。两个公开入口只是它的两种按钮组合 —— 别写两遍窗口装配。

## 4. 调用侧改动

| 位置 | 改成 |
| --- | --- |
| `main_window.py:624` | `prompt.notice(self.win, msg)`（原来那段「条目标题 / 请先选中」的三元表达式照留，只换外面这层调用） |
| `main_window.py:715` | `prompt.notice(self.win, "一次只能编辑一条便签")` |
| `main_window.py:733` | `prompt.notice(self.win, "请先选中便签（可按住 Ctrl 或 Shift 多选）")` |
| `main_window.py:755` | `if prompt.confirm(self.win, question + "\n此操作不可撤销。", action="删除"):` |
| `edit_dialog.py:517` | `prompt.notice(dlg, message)`（`warn()` 的函数体） |

`main_window.py` / `edit_dialog.py` 里的 `from tkinter import messagebox` 一并删掉（`app.py` 的 `_fatal` 保留，它还在用）。

## 5. 视觉规则（本次定下的规矩）

- **实心黄只给「提交」动作**（新建 / 保存）。提示、确认这类**关闭/收回去**的动作一律墨底 —— 黄是「这是页面上唯一要动起来的东西」，删除用黄是在说反话。
- **不引入红笔**。红笔在这套体系里专指「已错过」（有件事你还没处理），校验错误再用红笔会把它稀释掉。提示与警告的区别放在**文案**上，现在的文案已经足够具体（「日期「2026-45-11」无效，请填 2026-09-15 这样的日期」）。
- **不做内联批注**（曾讨论过把「请先选中便签」改成底栏那行灰字就地变红、几秒后褪回）：那行 8pt 灰字在最右边，视线不在那儿就注意不到；而且删除确认和校验警告本来就必须弹窗。

## 6. 测试

`tests/test_app.py`：

- 4 处 monkeypatch 改到新入口：`mb.showwarning`（§517 附近，取警告文案用）→ `prompt.notice`；`mb.askyesno`（2 处 3 行，自动确认用）→ `prompt.confirm`。`notice(parent, message)` 的签名跟 `mb.showwarning` 一致，所以 `warnings.append(a[1])` 那行不用动。
- **新增断言**（防的是「哪天又退回 messagebox」）：
  1. 提示框**压在父窗口上面**（复用刚加的 `z_index()` 量真实 z 序）
  2. 弹出来的**是自家的纸窗口，不是系统弹窗**：`overrideredirect()` 为真、Win32 类名不是 `#32770`、找得到「知道了」按钮
  3. 点「知道了」能真的把窗口关掉（`wait_window()` 会因此返回，测试本身就证明了这一点 —— 关不掉就是整个测试挂死）
  4. 删除确认点「删除」要真的删掉那条便签（现有用例只测了「自动确认=True」这条路径，没有测按钮接线）

  驱动方式抄现有 `open_editor_with` 那套：`after` 回调里找窗口 → 断言 → 点按钮 → 兜底 fuse 关窗。**`wait_window()` 只在窗口销毁后才返回，driver 里漏掉关窗会让整个测试文件永远挂住**（这个坑踩过一次）。

`tests/test_model.py` 不受影响。

## 7. 风险 / 待实测

- **grab 归还**（§2.1 第 2 条）：Tk 是否自动恢复上一个 grab 需要实测确认；不恢复就按设计显式还回去。
- **z 序**：新窗口一律不调 `transient`，并由 §6 的断言盯着。
- **高度自适应**：长文案（校验警告里有带换行的长句）必须完整显示，不能被裁掉 —— 直接复用编辑框量高的那套，不写死高度。
- 渲染图（真实主题搭的候选窗口，含 A–E 五个方案）在 `C:\Users\Administrator\AppData\Local\Temp\rn_prompt_candidates.png`，是一次性的对比材料，不是交付物。

## 8. 明确不做

- 启动失败的致命报错（保持系统弹窗）
- 非模态 toast / 内联批注
- 红笔的第二层语义
- 编辑框自身「弹出来不抢焦点」的问题（现状如此，另有其事）
