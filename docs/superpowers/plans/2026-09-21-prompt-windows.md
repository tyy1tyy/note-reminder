# 提示窗口（提示 / 警告 / 确认）实施计划
状态：已实施（2026-09-23）。实施说明：调用点实际切了 5 处（spec 列的是 5 处，测试的 monkeypatch 换了 6 处靶子）；`confirm` 的签名按 spec 用 `action=`；spec §6 的 4 条断言全部落地（前 3 条原有，第 4 条「点取消不删 / 点删除真删」本次补上，并另加一条走 `_delete` 真实路径的防退回断言）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把应用内 5 处系统灰弹窗换成自家「纸与笔」的提示窗口（提示 / 确认）。

**Architecture:** 新增 `reminders/prompt.py`，内部一个 `_show()` 负责全部窗口装配（复用 `frameless` 那套无边框圆角纸），对外只暴露 `notice()` 和 `confirm()`。调用方从 `messagebox` 切到 `prompt`，测试里 4 处 monkeypatch 跟着换靶子。

**Tech Stack:** Python 3.14 + tkinter（无新依赖）+ Pillow（只在既有的 `frameless`/`theme` 里用）。

**设计文档:** `docs/superpowers/specs/2026-09-21-prompt-windows-design.md`

## Global Constraints

- **全程不提交 git**（本机约定）：改动只留工作区，任何任务里都**不要** `git add` / `git commit` / `git push`。
- 测试是手写的，用 `python tests/test_model.py` 和 `python tests/test_app.py` 跑，**不用 pytest**。
- **不换控件类型**：测试按「控件类型 + 文本」找控件。按钮必须是 `tk.Button`，窗口必须是 `tk.Toplevel`。
- **现有文案逐字不改**（`请先选中便签（可按住 Ctrl 或 Shift 多选）`、`一次只能编辑一条便签`、`此操作不可撤销。` 等）。
- 新增的按钮文案只有三个：`知道了`、`取消`，以及由 `action` 参数传入的动作名（当前只有 `删除`）。
- **无边框窗口禁止 `transient()`** —— 会把窗口映射到 z 序最底，被父窗口盖住，而它还持着 grab，整个页面点不动（编辑框 2026-09-21 踩过）。
- 视觉常量：纸宽 `W = 400`、色带 `BAND_H = 46`、留白 `PAD = 16`。
- 实心黄（`frameless.primary_button`）只给「新建 / 保存」这类**提交**动作；提示/确认里的按钮一律 `ink_button`（墨底）或 `quiet_button`（只有字）。
- 颜色/字体一律现取 `theme.XXX`（模块级常量会被换配色刷掉，不能在 import 期抄进别的模块）。

---

### Task 1: `prompt.py` 骨架 + `notice()`

**Files:**
- Create: `reminders/prompt.py`
- Modify: `tests/test_app.py`（模块级加三个小工具；`main()` 里加 `drive_prompt` 和提示窗口的断言）

**Interfaces:**
- Consumes: `frameless.frameless_canvas / paper_onto / outer / close_button / ink_button / quiet_button / Dragger`（已存在）、`theme.CORNER_R / PAPER / PAPER_DEEP / INK / INK_SOFT / ui()`（已存在）、`geometry.center_on_parent`（已存在）。
- Produces:
  - `prompt.notice(parent, message: str, title: str = "提示") -> None`
  - `prompt._show(parent, message: str, title: str, buttons: list) -> object | None`，`buttons` 是 `[(标签: str, 是否主按钮: bool, 回调: Callable[[], object])]`，返回被点中按钮的回调返回值，✕/Esc 关掉时返回 `None`
  - 测试工具：`walk_widgets(widget) -> list`、`find_toplevel(widget, title) -> tk.Toplevel | None`、`win32_class(win) -> str`、`drive_prompt(action, check, wait=200, fuse_ms=8000)`

- [x] **Step 1: 写失败测试（先加三个模块级小工具）**

在 `tests/test_app.py` 里 `z_index()` 后面加：

```python
def walk_widgets(widget, out=None):
    """递归列出所有子控件 —— 提示框的正文和按钮都藏在 canvas 底下。"""
    out = [] if out is None else out
    for c in widget.winfo_children():
        out.append(c)
        walk_widgets(c, out)
    return out


def find_toplevel(widget, title):
    """按标题找 Toplevel。

    **必须从 root 往下递归**：对话框挂在主窗口名下，但编辑框里弹出的提示是挂在
    编辑框名下的 —— 只扫主窗口的子控件会漏掉它。
    """
    for c in widget.winfo_children():
        if isinstance(c, tk.Toplevel) and c.title() == title:
            return c
        found = find_toplevel(c, title)
        if found is not None:
            return found
    return None


def win32_class(win):
    """窗口的 Win32 类名。系统弹窗是 ``#32770``，Tk 的顶层窗口是 ``TkTopLevel``
    —— 用来钉死「这不再是系统弹窗了」。"""
    user32 = ctypes.windll.user32
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(user32.GetAncestor(win.winfo_id(), 2), buf, 256)
    return buf.value
```

在 `tests/test_app.py` 顶部导入里加 `prompt`：

```python
from reminders import clock, popup, prompt, store
```

- [x] **Step 2: 写失败测试（提示窗口的断言）**

在 `tests/test_app.py` 的 `main()` 里，紧接在「双击便签弹出的编辑框压在便签本上面」那段 `results.append(...)` 之后插入：

```python
    # ---- 提示窗口：自家的纸窗口，不再是系统灰弹窗 ----
    def drive_prompt(action, check, wait=200, fuse_ms=8000):
        """跑一个会阻塞的自家弹窗：action() 里发起，check(dlg) 里断言。

        **check 必须自己把窗口关掉** —— wait_window() 只在窗口销毁后才返回，
        check 里漏掉关窗会让整个测试文件永远挂住（这个坑踩过一次）。
        返回 action() 的返回值（比如 confirm 的 True / False）。
        """
        box = {}

        def driver(retries=6):
            dlg = find_toplevel(app.root, "提示") or find_toplevel(app.root, "确认")
            if dlg is None:
                if retries > 0:              # 可能只是还没建出来，再等等
                    app.root.after(100, lambda: driver(retries - 1))
                    return
                box["err"] = RuntimeError("弹窗没出现")
                return
            try:
                app.root.update()            # 等它真的映射到屏幕上再量
                check(dlg)
            except Exception as e:
                box["err"] = e
            finally:
                box["done"] = True
                if dlg.winfo_exists():
                    dlg.destroy()

        def fuse():
            """保险丝：driver 出意外时兜底关窗，别让 wait_window 无限等下去。"""
            if box.get("done"):
                return
            box.setdefault("err", RuntimeError("弹窗一直没被关掉"))
            for w in walk_widgets(app.root):
                if isinstance(w, tk.Toplevel) and w.title() in ("提示", "确认"):
                    w.destroy()

        app.root.after(wait, driver)
        fid = app.root.after(fuse_ms, fuse)
        result = action()
        app.root.after_cancel(fid)
        if "err" in box:
            raise box["err"]
        return result

    seen = {}

    def check_notice(dlg):
        seen["class"] = win32_class(dlg)
        seen["frameless"] = bool(dlg.overrideredirect())
        seen["canvas"] = any(isinstance(c, tk.Canvas) for c in walk_widgets(dlg))
        seen["labels"] = " ".join(c.cget("text") for c in walk_widgets(dlg)
                                  if isinstance(c, tk.Label))
        seen["buttons"] = set(b.cget("text") for b in collect_buttons(dlg))
        seen["z"] = (z_index(dlg), z_index(app.main_window.win))
        find_button(dlg, "知道了").invoke()      # 点它就该关窗

    drive_prompt(lambda: prompt.notice(app.main_window.win,
                                       "请先选中便签（可按住 Ctrl 或 Shift 多选）"),
                 check_notice)
    assert seen["class"] != "#32770", \
        f"提示还是系统弹窗（Win32 类名 {seen['class']}）"
    assert seen["frameless"], "提示窗口该是无边框圆角纸"
    assert seen["canvas"], "提示窗口该有承载圆角纸的 canvas"
    assert "请先选中便签" in seen["labels"], seen["labels"]
    assert seen["buttons"] == {"✕", "知道了"}, seen["buttons"]
    assert seen["z"][0] < seen["z"][1], \
        f"提示必须压在父窗口上面，实际 z 序 提示={seen['z'][0]} 便签本={seen['z'][1]}"
    results.append("提示是自家的纸窗口：无边框纸 + 「知道了」，压在父窗口上面，不是系统弹窗")

    # 长文案（校验警告里有带换行的长句）不能被裁掉 —— 高度得跟着内容走
    sizes = {}

    def check_h(dlg, key):
        sizes[key] = dlg.winfo_height()
        find_button(dlg, "知道了").invoke()

    drive_prompt(lambda: prompt.notice(app.main_window.win, "请先选中便签"),
                 lambda dlg: check_h(dlg, "short"))
    drive_prompt(lambda: prompt.notice(
        app.main_window.win,
        "间隔「abc」无效，请填正整数分钟数，比如 60\n不能是负数或小数"),
        lambda dlg: check_h(dlg, "long"))
    assert sizes["long"] > sizes["short"], \
        f"长文案该把提示框撑高（写死高度就会把字裁掉），实际 {sizes}"
    results.append("提示窗口高度随文案长短自适应（写死高度会裁字）")
```

- [x] **Step 3: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: `ModuleNotFoundError: No module named 'reminders.prompt'`（导入就炸）

- [x] **Step 4: 写 `reminders/prompt.py`**

```python
"""机器贴上来的一句话：提示 / 确认。

三个窗口（便签本 / 编辑框 / 到点弹窗）都是「一张纸」，可提示原来还是系统灰
弹窗 —— 放在这套纸旁边像另一个软件。这里把提示也做成同一族的纸窗口：

* 形态跟**编辑框**同族（纸 + 顶部色带当自制标题栏 + 右上 ✕）。不跟「到点弹窗」
  同族是有意的：那张撕下来的黄边纸条的意思是「你自己写的那条提醒」，而提示是
  机器贴上来的一句话，两者不该长得一样。
* 按钮走**墨底**：实心黄只留给「新建 / 保存」那种提交动作，关闭类的动作
  一律墨底 —— 黄在这套里是「这是页面上唯一要动起来的东西」。

**无边框窗口不许调 transient()**：Windows 会把 transient 的窗口映射到 z 序
最底，提示比父窗口小又是居中的，会被 100% 盖住，而它还持着 grab，整个页面
就点不动了（编辑框 2026-09-21 正是这么翻的车）。
"""
from __future__ import annotations

import tkinter as tk

from . import frameless, theme
from .geometry import center_on_parent

W = 400              # 纸宽固定，高度按内容自适应
BAND_H = 46          # 顶部色带 = 自制标题栏（编辑框那套缩小版）
PAD = 16


def notice(parent, message: str, title: str = "提示") -> None:
    """提示 / 校验警告：一句机器写的话 + 一个「知道了」。"""
    _show(parent, message, title, [("知道了", True, lambda: True)])


def _show(parent, message: str, title: str, buttons: list):
    """造窗、摆内容、按内容定高、模态等一个答案。

    返回**被点中那个按钮的回调返回值**；用 ✕ / Esc 关掉（没有按钮被点）时
    返回 None。
    """
    win = tk.Toplevel(parent)
    # 无边框之后系统不画它了，但测试靠 title() 找这个窗口，必须照设
    win.title(title)
    # 这里不能调 win.transient(parent) —— 理由见模块开头
    canvas = frameless.frameless_canvas(win)

    # 顶部色带 = 自制标题栏：左边一个词，右边 ✕
    band = tk.Frame(canvas, bg=theme.PAPER_DEEP)
    canvas.create_window(theme.CORNER_R, 0, window=band, anchor="nw",
                         width=W - 2 * theme.CORNER_R, height=BAND_H)
    tk.Label(band, text=title, bg=theme.PAPER_DEEP, fg=theme.INK_SOFT,
             font=theme.ui(10)).pack(side="left", padx=(16, 0))
    frameless.close_button(band, win.destroy).pack(side="right",
                                                   padx=(0, 12), pady=8)
    frameless.Dragger(win).attach(band)      # 挡着东西时能把它推开

    body = tk.Frame(canvas, bg=theme.PAPER)
    canvas.create_window(PAD, BAND_H + PAD, window=body, anchor="nw",
                         width=W - 2 * PAD)
    tk.Label(body, text=message, bg=theme.PAPER, fg=theme.INK,
             font=theme.ui(10), justify="left", anchor="w",
             wraplength=W - 2 * PAD - 6).pack(fill="x")

    answer: list = []

    def pick(value) -> None:
        answer.append(value)
        win.destroy()

    bar = tk.Frame(body, bg=theme.PAPER)
    bar.pack(anchor="e", pady=(16, 0))
    for text, primary, callback in buttons:
        maker = frameless.ink_button if primary else frameless.quiet_button
        maker(bar, text, lambda cb=callback: pick(cb())).pack(side="left",
                                                              padx=(6, 0))

    # 量完内容再定高度：校验警告里有带换行的长句，写死高度就会把字裁掉
    body.update_idletasks()
    height = BAND_H + PAD + body.winfo_reqheight() + PAD
    win.geometry(center_on_parent(win, parent, *frameless.outer(W, height)))
    # 纸最后画（要等高度定下来），它会自己压到内容底下。
    # 挂在窗口上是为了持住引用 —— PhotoImage 被回收图就没了
    win._paper = frameless.paper_onto(canvas, W, height,
                                      band_h=BAND_H, rule_y=BAND_H)

    # 键盘：原生弹窗本来就有这两下，换成自绘不能反而少一个
    win.bind("<Return>", lambda _e: pick(buttons[-1][2]()))
    win.bind("<Escape>", lambda _e: win.destroy())
    win.protocol("WM_DELETE_WINDOW", win.destroy)

    # 从编辑框里弹提示时，编辑框自己的 grab 会被这个窗口抢走 —— 关掉之后要
    # 还给它，否则编辑框就不是模态了（点主窗口会有反应）
    prev = win.grab_current()
    win.grab_set()
    win.focus_force()
    win.update_idletasks()
    win.wait_window()
    if prev is not None and prev.winfo_exists():
        prev.grab_set()
    return answer[0] if answer else None
```

- [x] **Step 5: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 全绿，末尾多出两行「提示是自家的纸窗口…」「提示窗口高度随文案长短自适应…」

- [x] **Step 6: 截图核对形态**

写个一次性脚本（放 `%TEMP%`，不进仓库），起 App 后从 `after` 回调里弹提示、另一个回调里截屏裁图：

```python
import os, sys, tempfile
os.environ["REMINDNOTES_DATA_DIR"] = tempfile.mkdtemp(prefix="rn_shot_")
sys.path.insert(0, r"D:\Tools\RemindNotes")
import tkinter as tk
from unittest import mock
from reminders import clock
mock.patch.object(clock, "sync", return_value=False).start()
from reminders import prompt
from reminders.app import App
from PIL import ImageGrab

app = App(); app.setup()
root = app.root
root.update()
if app.main_window.welcome_pending:
    app.main_window._dismiss_welcome()
    root.update()
app.main_window.win.attributes("-topmost", True)      # 保证截到的是它，别被别的窗口压住
SHOT = r"C:\Users\Administrator\AppData\Local\Temp\rn_prompt_real.png"

def open_it():
    prompt.notice(app.main_window.win, "请先选中便签（可按住 Ctrl 或 Shift 多选）")

def grab():
    w = [x for x in app.root.winfo_children() if isinstance(x, tk.Toplevel)
         and x.title() == "提示"]
    dlg = w[0]
    x, y = dlg.winfo_rootx(), dlg.winfo_rooty()
    ImageGrab.grab().crop((x - 26, y - 26, x + dlg.winfo_width() + 26,
                           y + dlg.winfo_height() + 26)).save(SHOT)
    print("截图:", SHOT)
    dlg.destroy(); root.update(); root.destroy()

root.after(400, open_it)
root.after(1500, grab)
root.mainloop()
```

打开这张 PNG，跟设计文档里选定的那张候选图（`%TEMP%\rn_prompt_candidates.png` 的 **A** 图）比对：色带高度与位置、✕ 的大小、正文起始位置、墨底「知道了」的右下角位置，都要一致。

- [x] **Step 7: 记一行台账（不提交）**

在回复里写一行：`Task 1 完成：prompt.notice 可用，test_app 新增 2 条断言通过`。**不要** `git add` / `git commit`。

---

### Task 2: `confirm()` + grab 归还

**Files:**
- Modify: `reminders/prompt.py`（加 `confirm()`）
- Modify: `tests/test_app.py`（加确认框与 grab 归还的断言）

**Interfaces:**
- Consumes: Task 1 的 `prompt._show(parent, message, title, buttons)`、测试里的 `drive_prompt`。
- Produces: `prompt.confirm(parent, message: str, action: str = "删除", title: str = "确认") -> bool`（点主按钮 `True`，取消 / ✕ / Esc `False`）。

- [x] **Step 1: 写失败测试**

在 Task 1 新增的那段 `results.append("提示窗口高度随文案长短自适应（写死高度会裁字）")` 之后插入：

```python
    # ---- 确认框：主按钮 = 同意，取消 / ✕ / Esc = 不同意 ----
    seen_c = {}

    def check_cancel(dlg):
        seen_c["class"] = win32_class(dlg)
        seen_c["buttons"] = set(b.cget("text") for b in collect_buttons(dlg))
        seen_c["z"] = (z_index(dlg), z_index(app.main_window.win))
        find_button(dlg, "取消").invoke()

    answer = drive_prompt(
        lambda: prompt.confirm(app.main_window.win, "要删掉它吗？", action="删除"),
        check_cancel)
    assert answer is False, f"点「取消」该返回 False，实际 {answer!r}"
    assert seen_c["buttons"] == {"✕", "取消", "删除"}, seen_c["buttons"]
    assert seen_c["class"] != "#32770", \
        f"确认框还是系统弹窗（Win32 类名 {seen_c['class']}）"
    assert seen_c["z"][0] < seen_c["z"][1], \
        f"确认框必须压在父窗口上面，实际 z 序 {seen_c['z']}"

    answer = drive_prompt(
        lambda: prompt.confirm(app.main_window.win, "要删掉它吗？", action="删除"),
        lambda dlg: find_button(dlg, "删除").invoke())
    assert answer is True, f"点主按钮该返回 True，实际 {answer!r}"

    answer = drive_prompt(
        lambda: prompt.confirm(app.main_window.win, "要删掉它吗？", action="删除"),
        lambda dlg: dlg.event_generate("<Escape>"))
    assert answer is False, f"按 Esc 关闭该返回 False，实际 {answer!r}"
    results.append("确认框：主按钮 = 同意、取消 / Esc = 不同意，且压在父窗口上面")

    # 从已经持有 grab 的窗口里弹提示（编辑框里弹校验警告就是这个情形）：
    # 关掉之后 grab 必须还回去，否则那个窗口就不是模态了
    holder = app.main_window.win
    holder.grab_set()
    try:
        drive_prompt(lambda: prompt.notice(holder, "抢 grab 测试"),
                     lambda dlg: find_button(dlg, "知道了").invoke())
        assert str(app.root.grab_current()) == str(holder), \
            f"关掉提示后 grab 该还给原来的窗口，实际 {app.root.grab_current()}"
    finally:
        holder.grab_release()
    results.append("从持有 grab 的窗口里弹提示，关掉后模态还回去")
```

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: `AttributeError: module 'reminders.prompt' has no attribute 'confirm'`

- [x] **Step 3: 加 `confirm()`**

在 `reminders/prompt.py` 的 `notice()` 之后、`_show()` 之前插入：

```python
def confirm(parent, message: str, action: str = "删除", title: str = "确认") -> bool:
    """要用户做个决定。

    点主按钮（上面的动作名，比如「删除」）算同意，点「取消」/ ✕ / Esc 算不同意。
    按钮文案由调用方给：说「删除」比说「是」清楚 —— 用户读的是动作，不是语法。
    """
    return bool(_show(parent, message, title,
                      [("取消", False, lambda: False),
                       (action, True, lambda: True)]))
```

- [x] **Step 4: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 全绿，多出「确认框：主按钮 = 同意…」「从持有 grab 的窗口里弹提示…」两条。

> 如果 Esc 那条断言失败（合成事件打不进绑定），先确认 `dlg.event_generate("<Escape>")` 是否真的触发了 `win.bind("<Escape>")` 里的回调：在回调里加一句 `print` 跑一次即可判断。合成事件进不去绑定的话，改测「绑定存在且能关窗」——即断言 `dlg.bind("<Escape>")` 非空，并在 driver 里手工 `dlg.destroy()`；同时**保留**一条注释说明为什么没测到按键路径。

- [x] **Step 5: 记一行台账（不提交）**

`Task 2 完成：prompt.confirm 可用，grab 归还实测通过`。

---

### Task 3: 五个调用点切到 `prompt`

**Files:**
- Modify: `reminders/main_window.py`（导入行 + `_require_selection` / `_edit` / `_delete` 里共 4 处 `messagebox` 调用）
- Modify: `reminders/edit_dialog.py`（导入行 + `warn()`）
- Modify: `tests/test_app.py`（4 处 monkeypatch 换靶子 + 2 组端到端断言）

> 计划里一律**按内容找位置**，不写行号 —— 前面任务会往文件里插代码，行号会漂。

**Interfaces:**
- Consumes: `prompt.notice(parent, message, title="提示")`、`prompt.confirm(parent, message, action="删除", title="确认") -> bool`。
- Produces: 无新接口；应用内不再有 `messagebox` 调用（除 `app.py` 的 `_fatal`）。

- [x] **Step 1: 先改测试里的 4 处 monkeypatch（换靶子）**

`tests/test_app.py` 里这 4 处原来盯的是 `tkinter.messagebox`，现在要盯 `reminders.prompt`：

① 编辑框校验警告那段（找 `original_warn = mb.showwarning`）：

```python
    original_warn = mb.showwarning
    warnings = []
    mb.showwarning = lambda *a, **k: warnings.append(a[1] if len(a) > 1 else str(a))
```
换成：
```python
    original_warn = prompt.notice
    warnings = []
    # notice(parent, message, title=...) —— 第 2 个位置参数就是文案
    prompt.notice = lambda *a, **k: warnings.append(a[1] if len(a) > 1 else str(a))
```

② 那个 `try` 块末尾的 `mb.showwarning = original_warn` → `prompt.notice = original_warn`

③ 删除的自动确认（找 `original_ask = mb.askyesno`）：

```python
    original_ask = mb.askyesno
    mb.askyesno = lambda *a, **k: True          # 自动确认，避免测试卡在弹窗上
```
换成：
```python
    original_ask = prompt.confirm
    prompt.confirm = lambda *a, **k: True       # 自动确认，避免测试卡在弹窗上
```

④ 紧随其后的 `mb.askyesno = original_ask` → `prompt.confirm = original_ask`

⑤ 整组删除的自动确认（找 `ask = mb.askyesno`）：

```python
    ask = mb.askyesno
    mb.askyesno = lambda *a, **k: True
```
→
```python
    ask = prompt.confirm
    prompt.confirm = lambda *a, **k: True
```
以及同段末尾的 `mb.askyesno = ask` → `prompt.confirm = ask`

⑥ 删掉两处已经没人用的导入：`from tkinter import messagebox as mb`（文件里有两处，一处紧挨着 ① 上面，一处在「8. 多选后批量操作」小标题下面）。
（先全局搜一遍 `mb.`，确认没有漏掉的调用点再删。）

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: 与弹窗有关的断言失败 —— `prompt.notice` / `prompt.confirm` 还没被调用方用上（弹出来的是真的模态系统弹窗或断言对不上），提示 `AssertionError`。

- [x] **Step 3: 改 `main_window.py`**

导入行：
```python
from tkinter import messagebox, ttk
```
→
```python
from tkinter import ttk
```
```python
from . import clock, edit_dialog, frameless, store, theme
```
→
```python
from . import clock, edit_dialog, frameless, prompt, store, theme
```

四个调用点：

`_require_selection()` 里那句 `messagebox.showinfo(`：
```python
            messagebox.showinfo(
                "提示",
                "选中的是记录条目的标题 —— 它只能展开收起，"
                "请展开后选中里面具体的记录"
                if self._has_group_selected()
                else "请先选中便签（可按住 Ctrl 或 Shift 多选）",
                parent=self.win)
```
→
```python
            prompt.notice(
                self.win,
                "选中的是记录条目的标题 —— 它只能展开收起，"
                "请展开后选中里面具体的记录"
                if self._has_group_selected()
                else "请先选中便签（可按住 Ctrl 或 Shift 多选）")
```

`_edit()` 里那句 `messagebox.showinfo("提示", "一次只能编辑一条便签"`：
```python
            messagebox.showinfo("提示", "一次只能编辑一条便签", parent=self.win)
```
→
```python
            prompt.notice(self.win, "一次只能编辑一条便签")
```

`_delete()` 开头那句 `messagebox.showinfo(`：
```python
            messagebox.showinfo(
                "提示", "请先选中便签（可按住 Ctrl 或 Shift 多选）",
                parent=self.win)
```
→
```python
            prompt.notice(self.win, "请先选中便签（可按住 Ctrl 或 Shift 多选）")
```

`_delete()` 末尾那句 `if messagebox.askyesno(`：
```python
        if messagebox.askyesno("确认", question + "\n此操作不可撤销。",
                               parent=self.win):
```
→
```python
        if prompt.confirm(self.win, question + "\n此操作不可撤销。", action="删除"):
```

- [x] **Step 4: 改 `edit_dialog.py`**

`from tkinter import messagebox` 这一行 → 整行删掉
`from . import frameless, theme` → `from . import frameless, prompt, theme`

`warn()`（`open_editor` 里定义的那个闭包）：
```python
    def warn(message: str) -> None:
        messagebox.showwarning("提示", message, parent=dlg)
```
→
```python
    def warn(message: str) -> None:
        prompt.notice(dlg, message)
```

- [x] **Step 5: 加端到端断言（真触发路径）**

在 `tests/test_app.py` 的「「删除」只删选中的，未选中的原样保留」那条 `results.append(...)` 之后插入：

```python
    # 真触发路径：没选中便签时点「删除」，弹的必须是自家的纸提示
    tree.selection_remove(*tree.selection())
    seen_e2e = {}

    def check_e2e(dlg):
        seen_e2e["class"] = win32_class(dlg)
        seen_e2e["labels"] = " ".join(c.cget("text") for c in walk_widgets(dlg)
                                      if isinstance(c, tk.Label))
        find_button(dlg, "知道了").invoke()

    drive_prompt(app.main_window._delete, check_e2e)
    assert seen_e2e["class"] != "#32770", \
        f"「请先选中便签」还弹着系统弹窗（{seen_e2e['class']}）"
    assert "请先选中便签" in seen_e2e["labels"], seen_e2e["labels"]
    results.append("没选中便签点「删除」→ 弹自家纸提示，点「知道了」能继续")

    # 点「取消」什么都不动、点「删除」真的删掉（原来那条只测了「自动确认」）
    doomed = make_once("真删我", datetime.now() + timedelta(hours=5))
    mw_items.append(doomed)
    app.main_window.refresh()
    tree.selection_set([doomed.id])
    drive_prompt(app.main_window._delete,
                 lambda dlg: find_button(dlg, "取消").invoke())
    assert doomed in mw_items, "点「取消」不该删掉"

    seen_del = {}

    def check_del(dlg):
        seen_del["buttons"] = set(b.cget("text") for b in collect_buttons(dlg))
        find_button(dlg, "删除").invoke()

    drive_prompt(app.main_window._delete, check_del)
    assert seen_del["buttons"] == {"✕", "取消", "删除"}, seen_del["buttons"]
    assert doomed not in mw_items, "点「删除」就该真的删掉"
    results.append("删除确认：点「取消」不删、点「删除」真删")
```

- [x] **Step 6: 跑两个测试套件**

Run: `python tests/test_model.py`
Expected: `89/89 passed`

Run: `python tests/test_app.py`
Expected: 全绿。特别注意这两条**必须仍然是绿的**（说明文案和校验没被改坏）：
- 「非法值会提示：日期 2026-45-11 / 间隔 -5、1.5、abc / 时段倒置」
- 「格式问题仍静默纠正（2026/9/5 直接存成 2026-09-05，不提示）」

- [x] **Step 7: 确认没有漏网的 `messagebox`**

Run: `grep -rn "messagebox" reminders/`
Expected: 只剩 `reminders/app.py`（`_fatal` 那处，按设计保留）。

- [x] **Step 8: 记一行台账（不提交）**

`Task 3 完成：5 处调用点切到 prompt，两个测试套件全绿`。

---

### Task 4: 真机验收

**Files:**
- 不改代码。只运行与核对。

- [x] **Step 1: 确认应用已重启到最新源码**

```powershell
Get-Process pythonw -ErrorAction SilentlyContinue
```
如果没有进程，起一个：`Start-Process -FilePath "pythonw" -ArgumentList "run.pyw" -WorkingDirectory "D:\Tools\RemindNotes"`。
（`dist\RemindNotes.exe` 是旧的手工打包产物，跟这次改动无关，别拿它测。）

- [x] **Step 2: 逐条触发 5 个弹窗**

| # | 怎么触发 | 该看到 |
| --- | --- | --- |
| 1 | 不选中任何行 → 点底栏「删除」 | 纸提示「请先选中便签（可按住 Ctrl 或 Shift 多选）」 |
| 2 | 选中 2 条 → 点「编辑」 | 纸提示「一次只能编辑一条便签」 |
| 3 | 选中 1 条 → 点「删除」→ 点「取消」 | 确认框带「取消 / 删除」；点取消后那条还在 |
| 4 | 同上去点「删除」 | 那条真的被删掉 |
| 5 | 打开编辑框 → 日期填 `2026-45-11` → 点「保存」 | 纸提示「日期「2026-45-11」无效…」 |

（第 6 处「选中的是记录条目标题」需要先有循环记录，可跳过。）

- [x] **Step 3: 验互动细节**

- 每个提示/确认框都**居中压在便签本（或编辑框）上面**，看得见、点得动
- 提示框出现时按 `Esc` 能关掉它；确认框按 `Esc` = 取消
- 第 5 条关掉提示后，**编辑框仍然点得动**（grab 还回去了），并且能继续改日期再保存
- 点「知道了」/「删除」/「取消」都能立刻关窗，没有卡住不动的

- [x] **Step 4: 有问题就回到对应任务**

哪一条不对就回到 Task 1 / 2 / 3 对应步骤改，改完重跑两个测试套件。
