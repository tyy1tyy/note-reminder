# 到点弹窗的任务栏按钮 实施计划

状态：Task 1-3 完成，测试三脚本全绿（`test_model` / `test_holidays` / `test_app` 都 exit=0）。
Task 4 只部分完成：**任务栏按钮已由用户实测确认出现**（2026-09-28），其余四条待实测项
（闪、打包图标、最小化期间覆盖重建、多屏、连点）未测，逐条见 spec §9。
**实施中的偏差**：① `taskbar_button()` 必须先 `win.update_idletasks()` —— 不然弹窗会跑到
屏幕左上角（hide/show 让 Tk 把"还没摆好的矩形"当成 geometry 记下来），这是 spec 没预料到的
缺陷，由 2026-09-15 的既有断言「弹窗应居中于屏幕」抓到，已修 + 补回归断言；
② 排错期间四种自动测量办法（像素差分 / TB_BUTTONCOUNT / UIA / 点击最小化）全部不可靠，
最终靠"进程 PID + 启动时间"和用户肉眼看任务栏定的案（详见 spec §9）。
**未提交**（本机约定：改动只留工作区）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让到点弹窗在任务栏里有自己的一格 —— 被别的窗口盖住时点一下就能叫回最前，也能主动把它最小化。

**Architecture:** 窗口系统那一层加一个 `frameless.taskbar_button(win)`（清 `WS_EX_TOOLWINDOW` + 加 `WS_EX_APPWINDOW`，配方必须是"真隐藏 → 改样式 → 真显示"）；`popup.py` 的 `show()` 末尾调它一次。最小化/还原完全交给系统，我们**一行窗口状态操作都不写**。顺带修一个既有 bug：托盘菜单的勾因为 Windows 后端把菜单烘在构造那一刻而不会刷新。

**Tech Stack:** Python 3.14 标准库 + tkinter + `ctypes`（user32）。零新依赖。

**Spec:** `docs/superpowers/specs/2026-09-28-popup-taskbar-button-design.md`

## Global Constraints

- **不执行任何 git 提交**。本机约定见 `no-unauthorized-git-commits` —— 每个任务只留工作区改动，**计划里没有 commit 步骤是有意的**。
- 三个测试脚本都要保持全绿：`python tests/test_model.py`、`python tests/test_holidays.py`、`python tests/test_app.py`。测试自带 runner（`main()` + `results.append`），**不用 pytest**。
- 测试绝不联网、且必须用隔离数据目录：`tests/` 下的文件在 import 之前就设 `REMINDNOTES_OFFLINE=1` 与隔离的 `REMINDNOTES_DATA_DIR`（`test_app.py:17-19` 已有）。
- **硬规矩（本计划的头号约束）：绝不从 Python 里同步调 `ShowWindow(SW_MINIMIZE)` / `ShowWindow(SW_RESTORE)`。** 那会在 Tk 事件循环里同步嵌套重入，进程直接致命崩溃（`Fatal Python error: PyEval_RestoreThread ... the GIL is released`；换 `ctypes.PyDLL` 照样崩）。要动窗口状态只能 `PostMessage(hwnd, WM_SYSCOMMAND, SC_MINIMIZE | SC_RESTORE, 0)`。唯一例外是配方里的 `SW_HIDE` / `SW_SHOW`，实测安全且没有替代写法。
- 注释与文案一律中文，写「为什么」不写「做了什么」；踩过的坑要把证据（哪条实测、什么报错）写进注释。
- 一律 Windows，不写平台分支；但调用侧仍要兜住异常（见 Task 2）。
- 修改位置**按内容找，不按行号** —— 前面任务会往文件里插代码，行号会漂。

---

### Task 1: `frameless.taskbar_button()` —— 给窗口挣一格任务栏

**Files:**
- Modify: `reminders/frameless.py`（顶部 import 与常量；新函数放在 `as_paper()` 之后、`class Dragger` 之前）
- Test: `tests/test_app.py`（顶部 import；新增 `ex_style()` 辅助函数；弹窗段落里加断言）

**Interfaces:**
- Consumes: 无
- Produces:
  - `frameless.taskbar_button(win: tk.Toplevel) -> None` —— 给窗口加任务栏按钮；失败时**抛异常**（不自己吞）
  - `frameless._user32()` —— 配好 `restype`/`argtypes` 的 user32（测试要 patch 它）
  - 模块级常量：`frameless.GWL_EXSTYLE`、`frameless.WS_EX_TOOLWINDOW`、`frameless.WS_EX_APPWINDOW`、`frameless.SW_HIDE`、`frameless.SW_SHOW`
  - `tests/test_app.py` 的 `ex_style(win) -> int` 辅助函数

- [ ] **Step 1: 先写测试**

`tests/test_app.py` 顶部，把 `from ctypes import wintypes` 加在 `import ctypes` 之后（`ex_style` 要用）：

```python
import ctypes
from ctypes import wintypes
```

在 `z_index()` 之后加辅助函数：

```python
def ex_style(win):
    """窗口的扩展样式位。

    用它判定"任务栏按钮会不会出现"：真去数任务栏的格子得截图，不适合进测试；
    而 `WS_EX_TOOLWINDOW` 的语义就是「别上任务栏和 Alt-Tab」，清掉它 + 加上
    `WS_EX_APPWINDOW` 才有那一格 —— 这两个位是机器可判定的代理指标。
    """
    user32 = ctypes.windll.user32
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    hwnd = user32.GetAncestor(win.winfo_id(), 2)          # GA_ROOT
    return user32.GetWindowLongW(hwnd, frameless.GWL_EXSTYLE)
```

`from reminders import clock, holidays, popup, prompt, store, theme`（`test_app.py:26`）那一行加上 `frameless`：

```python
from reminders import clock, frameless, holidays, popup, prompt, store, theme
```

然后，在弹窗那段（`results.append("弹窗正文（Label）也能拖：拖拽把手是递归绑的，按钮除外")` 之后、`# 老数据没有 done_at 也不能乱` 之前）加：

```python
    # 任务栏按钮：没有它，弹窗被别的窗口盖住之后就找不回来了（无边框窗口的
    # 任务栏和 Alt-Tab 里都没有它）。真相看任务栏得截图，这里钉的是样式位。
    tb_win = tk.Toplevel(app.root)
    frameless.frameless_canvas(tb_win)
    app.root.update()
    ex = ex_style(tb_win)
    assert ex & frameless.WS_EX_TOOLWINDOW, \
        "前提：无边框窗口刚建出来时是带 TOOLWINDOW 的（Tk 打的这个标记）"
    tc_before = tb_win.attributes("-transparentcolor")
    frameless.taskbar_button(tb_win)
    app.root.update()
    ex = ex_style(tb_win)
    assert not ex & frameless.WS_EX_TOOLWINDOW, \
        "TOOLWINDOW 没清掉，任务栏和 Alt-Tab 里都不会出现"
    assert ex & frameless.WS_EX_APPWINDOW, "没加 APPWINDOW 就不会有任务栏按钮"
    assert tb_win.winfo_viewable(), \
        "配方跑完窗口必须还看得见 —— hide 没配上 show 就是个隐形窗口，而没有任何入口能找回它"
    assert tb_win.attributes("-transparentcolor") == tc_before, \
        f"透明色被配方弄改了（{tc_before} → {tb_win.attributes('-transparentcolor')}）：圆角会变成硬角"
    tb_win.destroy()
    app.root.update()

    # try/finally 兜底：改样式那步若抛异常，窗口也必须被显示回来（否则停在
    # 「已隐藏」状态）。这里把 user32 整个换成替身：ShowWindow 只记账不动真窗口。
    calls = []

    class BoomUser32:
        def GetAncestor(self, hwnd, flags):
            return hwnd

        def ShowWindow(self, hwnd, cmd):
            calls.append(cmd)

        def GetWindowLongW(self, hwnd, idx):
            return 0

        def SetWindowLongW(self, hwnd, idx, value):
            raise OSError("模拟改样式失败")

        def SetWindowPos(self, *a):
            raise AssertionError("样式都没改成，不该走到 SetWindowPos")

    boom_win = tk.Toplevel(app.root)
    frameless.frameless_canvas(boom_win)
    app.root.update()
    raised = False
    with mock.patch.object(frameless, "_user32", lambda: BoomUser32()):
        try:
            frameless.taskbar_button(boom_win)
        except OSError:
            raised = True
    assert raised, "改样式失败必须把异常抛给调用方，不能自己吞掉"
    assert calls == [frameless.SW_HIDE, frameless.SW_SHOW], \
        f"异常路径也必须把窗口显示回来，实际调用序列 {calls}"
    boom_win.destroy()
    app.root.update()
    results.append("frameless.taskbar_button：清 TOOLWINDOW / 加 APPWINDOW，"
                   "且失败时也会把窗口显示回来")
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: `AttributeError: module 'reminders.frameless' has no attribute 'GWL_EXSTYLE'`（或 `frameless` 未导入）

- [ ] **Step 3: 实现**

`reminders/frameless.py` 顶部 import 区（现在是 `import tkinter as tk` + `from . import theme`）改成：

```python
from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes

from . import theme
```

`CORNER = theme.CORNER_R` 之后加常量（都带注释，说明它们是什么、为什么要动）：

```python
# ---- 任务栏按钮要用的窗口样式位 ----
# Tk 给 overrideredirect 窗口打了 WS_EX_TOOLWINDOW —— 那个标记的语义就是
# 「别在任务栏和 Alt-Tab 里出现」。想让它有任务栏按钮，就得把这位清掉、
# 再补上 WS_EX_APPWINDOW。用到的常量都在这里列清楚，免得散在函数体里
# 变成一串魔法数。
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SW_HIDE = 0
SW_SHOW = 5
GA_ROOT = 2
```

在 `as_paper()` 之后、`class Dragger` 之前加：

```python
def _user32():
    """配好签名的 user32。

    **不能配漏 restype**：`GetAncestor` 默认按 ``c_int`` 收，64 位下会把窗口
    句柄截断。实测环境里句柄值恰好都小到能塞进 32 位，所以不配也"看着没事"
    —— 那属于撞运气，不叫安全。
    """
    user32 = ctypes.windll.user32
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_uint]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    return user32


def taskbar_button(win: tk.Toplevel) -> None:
    """给这张纸在任务栏里挣一格 —— 被别的窗口盖住时点它就能叫回最前。

    三条都是 2026-09-28 实测出来的（探针脚本见 spec §2），少一条就会被
    "顺手优化"回去：

    ① **必须真隐藏再显示**，样式改动才生效。shell 只在「隐藏 → 显示」这个转换上
       重算任务栏归属：窗口还在显示时改样式、首次显示之前就改样式，都不出按钮
       （三种时序各测过一遍，全无）。所以顺序是 hide → 改 → show，hide 不能省。
    ② **不能用 Tk 的 withdraw()/deiconify() 代替**：`deiconify()` 对
       overrideredirect 窗口不会真的把窗口重新显示出来（`iconify()` 更直接，Tk
       会报 `can't iconify ...: override-redirect flag is set`）。只有 Win32 的
       SW_HIDE / SW_SHOW 这一对能完成这个转换 —— 这正是第一次探针没测出按钮的
       原因（它用了 deiconify，窗口其实一直藏在后台）。
    ③ **只动这两个样式位**：清 TOOLWINDOW、加 APPWINDOW。不碰 WS_POPUP 和分层
       透明，所以圆角、透明、置顶都不受影响（实测 LAYERED / topmost /
       transparentcolor / 角落像素全都没变）。

    **这里不吞异常**：拿不到任务栏按钮只是少了个便利入口，但函数内部一旦把
    异常咽掉，"为什么这台机器没有按钮"就再也查不出来了。由调用方决定怎么兜。

    **绝不在这个模块里（或任何地方）同步调 ShowWindow(SW_MINIMIZE/SW_RESTORE)**：
    那会在 Tk 事件循环里同步嵌套重入，进程直接致命崩溃（Fatal Python error:
    PyEval_RestoreThread ... the GIL is released；换 ctypes.PyDLL —— 调用期间
    不释放 GIL —— 照样崩，所以不是 GIL 释放本身的问题）。要动窗口状态就用
    PostMessage(hwnd, WM_SYSCOMMAND, SC_MINIMIZE | SC_RESTORE, 0)：异步投递、
    由 Tk 自己的消息泵处理，实测安全。下面这对 SW_HIDE/SW_SHOW 是唯一例外，
    实测安全且没有替代写法（见 ②）。
    """
    user32 = _user32()
    hwnd = user32.GetAncestor(win.winfo_id(), GA_ROOT)
    user32.ShowWindow(hwnd, SW_HIDE)
    try:
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                            | SWP_FRAMECHANGED)
    finally:
        # **必须在 finally 里**：中间那两行若抛异常而没走到这儿，窗口就停在
        # 「已隐藏」状态 —— 它此刻正占着用户的注意力（提醒到点了）却看不见，
        # 而且没有任何入口能把它找回来。
        user32.ShowWindow(hwnd, SW_SHOW)
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 末尾打印 `全部通过：` 并含新那一行 `- frameless.taskbar_button：清 TOOLWINDOW / 加 APPWINDOW，且失败时也会把窗口显示回来`；退出码 0

- [ ] **Step 5: 眼睛过一遍真窗口（这一步不能跳）**

建一个临时的无边框窗口、调用 `taskbar_button()`，然后看**任务栏里有没有多出一格、点它能不能把窗口叫到最前**：

```
python -c "import sys; sys.path.insert(0, r'D:\Tools\RemindNotes'); import tkinter as tk; from reminders import frameless; r=tk.Tk(); r.withdraw(); w=tk.Toplevel(r); frameless.frameless_canvas(w); w.geometry('300x120+700+400'); tk.Label(w, text='点我的任务栏那一格', bg='#FFFCF3').pack(pady=40); w.update(); frameless.taskbar_button(w); r.after(20000, r.destroy); r.mainloop()"
```

Expected：任务栏出现一格（开发态图标是 Python 图标，正常）；先用别的窗口把它盖住，点任务栏那一格能把它抬到最前。**看不到那一格就停下来查**，别往下走 —— 后面两个任务都建在这条上面。

---

### Task 2: 弹窗接上任务栏按钮（+ README）

**Files:**
- Modify: `reminders/popup.py`（模块 docstring 加一段；`show()` 末尾加调用）
- Modify: `README.md`（「到点弹窗」段）
- Test: `tests/test_app.py`（弹窗段落）

**Interfaces:**
- Consumes: `frameless.taskbar_button(win)`（Task 1）、`tests/test_app.py` 的 `ex_style(win)`（Task 1）
- Produces: 无对外新接口 —— `PopupManager.show()` 行为变化：弹出来的窗口带任务栏按钮

- [ ] **Step 1: 先写测试**

`tests/test_app.py`，在 Task 1 加的那段之后（`# 老数据没有 done_at 也不能乱` 之前）接着加：

```python
    # 弹窗接上任务栏按钮：真弹一张便签，钉样式位 + 钉"配方没把视觉搞坏"
    tb_pop = make_once("任务栏按钮（弹窗）", datetime.now() - timedelta(seconds=1))
    app.popups.show(tb_pop)
    app.root.update()
    pop = app.popups.open_popups[-1]
    ex = ex_style(pop)
    assert not ex & frameless.WS_EX_TOOLWINDOW, \
        "弹窗还带着 TOOLWINDOW：任务栏里不会有它，被盖住就找不回来了"
    assert ex & frameless.WS_EX_APPWINDOW, "弹窗没有 APPWINDOW，任务栏里不会有它"
    assert pop.winfo_viewable(), "配方跑完弹窗必须还看得见"
    assert pop.attributes("-topmost"), \
        "刚弹出时该是置顶的 —— 配方里的 hide/show 不能把置顶弄丢"
    assert pop.attributes("-transparentcolor"), \
        "透明色丢了圆角就变成硬角（配方只该动扩展样式位）"
    assert pop.overrideredirect(), "配方不该把无边框改掉"
    app.popups.close_all()
    app.root.update()
    results.append("到点弹窗带任务栏按钮，且圆角/透明/置顶/无边框都没被配方破坏")
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: `AssertionError: 弹窗还带着 TOOLWINDOW：任务栏里不会有它，被盖住就找不回来了`

- [ ] **Step 3: 实现**

`reminders/popup.py` 的模块 docstring：在末尾那段（`但只占一条边。`）之后追加一段：

```python
它在**任务栏里有自己的一格**（`frameless.taskbar_button`）：被别的窗口盖住时点一下
就能叫回来，用户也可以主动把它最小化。**最小化和还原全程由系统做，这里一行窗口
状态操作都不写** —— 光标停在弹窗上时 `iconify()` 会被 Tk 拒（override-redirect），
而我们自己同步调 `ShowWindow(SW_MINIMIZE)` 会直接把进程搞崩（实测：Fatal Python
error: PyEval_RestoreThread ... the GIL is released）。真需要动窗口状态时，走
`PostMessage(WM_SYSCOMMAND, SC_MINIMIZE / SC_RESTORE)`，别用 ShowWindow。
```

`show()` 末尾，`frameless.Dragger(win).attach(note)` 与 `win.protocol(...)` 之后加：

```python
        # 任务栏按钮：这张纸在任务栏里有自己的一格，被别的窗口盖住时点一下就能
        # 叫回来。**必须放在窗口已经 map 之后** —— 配方要求"先真隐藏再显示"，
        # 理由见 frameless.taskbar_button。放最后还有个好处：200ms 的置顶窗口
        # 还没到期，这次 hide/show 落在里面，「弹出必被看见」不受影响。
        try:
            frameless.taskbar_button(win)
        except Exception:
            pass        # 少一个便利入口而已，绝不能反过来让提醒弹不出来
```

`README.md` 的「到点弹窗」段，在 `同一时刻只留一个弹窗，后弹的覆盖前一个。` 之后加一行：

```markdown
它在**任务栏里有自己的一格**：被别的窗口压住时，点一下就把它叫回最前；也可以直接把它最小化。
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 退出码 0，`全部通过：` 里含新那行 `- 到点弹窗带任务栏按钮，且圆角/透明/置顶/无边框都没被配方破坏`

再跑另外两个（本次没碰它们，确认没被带坏）：

Run: `python tests/test_model.py` / `python tests/test_holidays.py`
Expected: 两个都通过

- [ ] **Step 5: 看真弹窗**

```
python -c "import sys; sys.path.insert(0, r'D:\Tools\RemindNotes'); import tkinter as tk; from datetime import datetime, timedelta; from reminders.popup import PopupManager; from reminders.model import make_once; r=tk.Tk(); r.withdraw(); pm=PopupManager(r, lambda: None); r.after(500, lambda: pm.show(make_once('看一眼任务栏', datetime.now()-timedelta(seconds=1)))); r.after(25000, r.destroy); r.mainloop()"
```

Expected：弹窗照常弹出（纸 + 黄粘胶边 + 三个按钮原样），任务栏多出一格。**盯住弹出那一瞬有没有闪一下**（这是 spec §8 第 1 条）。

---

### Task 3: 顺带修 —— 托盘菜单的勾不刷新（既有 bug）

**Files:**
- Modify: `reminders/tray.py`（新增 `refresh_menu()`；`_toggle_autostart()` 末尾调用；改一句错注释）
- Modify: `reminders/app.py`（`_toggle_eyecare()` 末尾调用）
- Test: `tests/test_app.py`（托盘段落，`test_app.py:1211` 附近）

**Interfaces:**
- Consumes: 无
- Produces: `Tray.refresh_menu() -> None` —— 重建托盘菜单（`icon.update_menu()`）

**背景（写进代码注释）**：Windows 后端的菜单**不是每次弹出重建的** —— `HMENU` 只在 `_update_menu()` 里建一次（`pystray/_win32.py:99-111`），右键弹出时直接用缓存（`_win32.py:203-224`），`MFS_CHECKED` 在 `_win32.py:316` 建设时烘死；重建的唯一触发器是 `Icon.update_menu()`（`_base.py:261-275`）。所以现在切了「开机自启」/「护眼模式」，重新打开菜单勾还是旧的 —— `tray.py:53-54` 那句注释写的"菜单项在每次弹出时重建"是错的。

- [ ] **Step 1: 先写测试**

`tests/test_app.py` 顶部 import 行加 `autostart`（**必须加在模块级那一行，不要在函数里 import** —— 函数内 import 会把它变成局部名，前面的断言就 `UnboundLocalError`，这个坑这个文件踩过）：

```python
from reminders import autostart, clock, frameless, holidays, popup, prompt, store, theme
```

在托盘菜单那一段（`results.append("托盘菜单：打开便签本 / 新建提醒 / 开机自启 / 护眼模式 / 退出")` 之后）加：

```python
    # 勾不是每次弹出重算的：Windows 后端把菜单烘在构造那一刻（HMENU 缓存在
    # _menu_handle 里），所以状态变了必须显式刷新，否则勾一直停在旧状态。
    # 真正的勾渲染在 pystray 内部，这里能测到的最强断言就是"刷新被调用了"。
    with mock.patch.object(app.tray, "refresh_menu") as refresh:
        app.toggle_eyecare()            # 托盘回调，内部走 root.after(0, ...)
        app.root.update()               # 让主线程跑那一趟
    assert refresh.call_count == 1, \
        f"切了护眼模式却刷新了 {refresh.call_count} 次菜单，勾会停在旧状态"
    app.toggle_eyecare()                # 切回来，别把后面的断言留在 eye 配色
    app.root.update()

    # 开机自启同理。真改注册表不能干，所以把两个 autostart 调用都替掉 ——
    # 这里验的是"切完之后刷新了菜单"，注册表写没写对由 test_model 管。
    with mock.patch.object(autostart, "is_enabled", return_value=False), \
            mock.patch.object(autostart, "set_enabled") as set_en, \
            mock.patch.object(app.tray, "refresh_menu") as refresh:
        app.tray._toggle_autostart()
    assert set_en.call_count == 1, "开关压根没切，这个断言就没意义了"
    assert refresh.call_count == 1, \
        f"切了开机自启却刷新了 {refresh.call_count} 次菜单，勾会停在旧状态"
    results.append("托盘菜单的勾会刷新：切护眼/开机自启后都重建一次菜单")
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: `AssertionError: 切了护眼模式却刷新了 0 次菜单，勾会停在旧状态`

- [ ] **Step 3: 实现**

`reminders/tray.py`，`_toggle_autostart()` 改成：

```python
    def _toggle_autostart(self) -> None:
        try:
            autostart.set_enabled(not autostart.is_enabled())
        except OSError:
            pass
        # 勾是构造菜单时烘进去的，不刷新就一直是旧状态（见 refresh_menu）
        self.refresh_menu()

    def refresh_menu(self) -> None:
        """状态变了之后重建菜单。

        Windows 后端的菜单**不是每次弹出重建的**：HMENU 只在 ``_update_menu()``
        里建一次（pystray/_win32.py），右键弹出时直接用缓存，勾选位在建设那一刻
        就烘死了。重建的唯一触发器是 ``Icon.update_menu()`` —— 所以切了「开机
        自启」/「护眼模式」之后必须调这里，否则勾停在旧状态。
        """
        if self.icon is not None:
            self.icon.update_menu()
```

`tray.py` 里「护眼模式」那一项的注释（现在是 `# 勾选态由取值函数给，跟「开机自启」同一个套路；菜单项在每次弹出时重建，所以切换后勾会跟着动`）改成：

```python
            # 勾选态由取值函数给，跟「开机自启」同一个套路。但**不是**每次弹出
            # 重算 —— Windows 后端把菜单烘在构造那一刻，所以切换之后必须显式
            # 刷新（见 refresh_menu），不然勾不会动。
```

`reminders/app.py` 的 `_toggle_eyecare()`，在 `self.main_window.apply_palette(self.palette)` 之后加：

```python
        # 托盘菜单的勾同理：构造时烘的，不刷新就一直显示旧状态
        if self.tray is not None:
            self.tray.refresh_menu()
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 退出码 0，含 `- 托盘菜单的勾会刷新：切护眼/开机自启后都重建一次菜单`

- [ ] **Step 5: 看真的勾**

启动程序（`python run.pyw` 或 `pythonw run.pyw`），托盘右键 → 点「护眼模式」→ **再右键打开菜单**，勾应该已经移到「护眼模式」上（改之前它会留在原地）。再点回白天配色、确认勾跟着回来。

---

### Task 4: 待实测清单逐条过（spec §8）+ 收尾

**Files:**
- Modify: `docs/superpowers/specs/2026-09-28-popup-taskbar-button-design.md`（状态行）
- Modify: 本计划（状态行）
- 一次性脚本放 `%TEMP%`，**不进仓库**

**Interfaces:**
- Consumes: Task 1-3 的全部改动
- Produces: 无代码产物；产出是"每条都实测过"的记录

- [ ] **Step 1: 反复弹窗，看会不会闪**

`%TEMP%\rn_flicker_check.py`（一次性脚本，不进仓库）：

```python
"""看一眼弹窗反复出现时会不会闪 —— 配方里有 hide/show，理论上同一回调内完成、
中途不回到事件循环，所以窗口系统没机会在中间绘制。要看一眼确认。"""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, r"D:\Tools\RemindNotes")          # 按实际仓库路径改

import tkinter as tk
from reminders.model import make_once
from reminders.popup import PopupManager

root = tk.Tk()
root.withdraw()
pm = PopupManager(root, lambda: None)
count = {"n": 0}


def again():
    count["n"] += 1
    pm.show(make_once(f"第 {count['n']} 次", datetime.now() - timedelta(seconds=1)))
    if count["n"] < 5:
        root.after(2500, again)          # 留出从任务栏点它的时间
    else:
        root.after(3000, root.destroy)


root.after(800, again)
root.mainloop()
```

Run: `python %TEMP%\rn_flicker_check.py`

Expected：每张弹窗照常出现，**看不到"先闪一下再出现"或"闪一下才稳定"**。看到闪就停下来汇报 —— 那是要改设计的信号，不是小瑕疵。

- [ ] **Step 2: 最小化 → 新提醒到点 → 覆盖重建**

跑上面的脚本，在弹窗出现后**从任务栏把它最小化**，等下一次弹（2.5 秒一张）。

Expected：新弹窗照常出现、任务栏仍有格子；最小化那张被销毁（`close_all()` 的既有行为），没有残留。

- [ ] **Step 3: 连点若干次不崩**

在弹窗的任务栏按钮上**连续点击 10 次以上**（最小化/还原来回切）。

Expected：进程活着、弹窗内容完好（纸色 + 文字 + 三个按钮都在）。这条是防"那个致命崩溃以别的形态从 Explorer 侧回来"（spec §8 第 5 条 / §2 第 9 条）。

- [ ] **Step 4: 打包后图标是 RemindNotes 自己的**

Run: `build.bat`（**结尾有个 `pause`，跑完要手敲一下回车**，否则窗口挂着不退）
Expected：双击 `dist\RemindNotes.exe` → 托盘出图标 → 等到点弹窗出现，**任务栏那一格的图标是 RemindNotes 的便签图标，不是 Python 图标**。（开发态显示 Python 图标是正常的 —— Tk 窗口继承 exe 图标。）

- [ ] **Step 5: 多显示器 / 任务栏不在底部**

有条件就测：把主屏的任务栏挪到左侧或顶部（或接第二块屏），触发一次弹窗。
Expected：按钮正常出现，点它能叫回最前。**没条件就如实记"未测"**，别写"应该没问题"。

- [ ] **Step 6: 更新状态行**

- `docs/superpowers/specs/2026-09-28-popup-taskbar-button-design.md` 的状态行改成 `状态：已实施（2026-09-28，见 plans/2026-09-28-popup-taskbar-button.md）`
- 本计划开头状态行改成实际结果，**实施中的偏差要写在这里**（这套计划文件一直是这么用的，见 `2026-09-23-workday-week-strip.md` 开头）：哪条实测没过、什么原因、最后怎么处置

- [ ] **Step 7: 报改动清单（不提交）**

`git status --short` 列出本次改动，报给用户；**按本机约定不提交**，等用户明确授权再提交。

---

## 附：本计划刻意不做的事（对应 spec §7）

- 托盘菜单加「显示当前提醒」项 —— 曾与用户讨论过，2026-09-28 因任务栏按钮已覆盖该需求而撤掉
- 便签本主窗口的任务栏按钮（它要额外处理"从任务栏最小化后托盘还能不能叫回来"：`deiconify()` 在 `iconify()` 上已被 Tk 拒，主窗口需要 `PostMessage(SC_RESTORE)` 兜底并实测）
- 全局热键、恒置顶、自动让位 / 自动抬升、自定义窗口图标
- 不碰 `prompt.py` / 编辑框的居中逻辑
