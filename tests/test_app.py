"""App 内部链路测试：setup 装配 -> 定时器 -> 弹窗 -> 按钮写回。

运行：python tests/test_app.py

这是唯一能自动发现「到点了但弹窗不出现」的检查，且不依赖屏幕状态或人工操作，
因此保留为回归测试（其余 UI 验证脚本为一次性临时脚本，已删除）。

注意：本测试会短暂创建真实窗口与托盘图标，属预期行为。
"""
import sys
import os
import time
import ctypes
import tempfile
from ctypes import wintypes
from datetime import date, datetime, timedelta

# 必须在使用 store 之前设置：隔离数据目录，避免污染真实便签数据
os.environ["REMINDNOTES_DATA_DIR"] = tempfile.mkdtemp(prefix="remindnotes_test_")
os.environ["REMINDNOTES_OFFLINE"] = "1"     # 测试套绝不联网（校时 + 节假日更新）

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from reminders.app import App, STARTUP_GRACE_TICKS, APP_ID
from reminders import autostart, clock, frameless, holidays, popup, prompt, store, theme
from reminders.model import make_once, make_daily, make_interval
from reminders.tray import make_icon_image


def collect_buttons(widget, out=None):
    out = [] if out is None else out
    for c in widget.winfo_children():
        if isinstance(c, tk.Button):
            out.append(c)
        collect_buttons(c, out)
    return out


def find_button(widget, text):
    for b in collect_buttons(widget):
        if b.cget("text") == text:
            return b
    raise AssertionError(f"找不到按钮「{text}」")


def z_index(win):
    """窗口在系统 z 序里的位置，0 = 最上（越小越靠前）。

    专门用来判断「这个窗口有没有被别的窗口盖住」：`winfo_viewable()` 对被压在
    最底下、屏幕上根本看不见的窗口**照样返回 1**，查不出这种事。

    取不到（窗口不在 z 序里）返回 None。
    """
    user32 = ctypes.windll.user32
    hwnd = user32.GetAncestor(win.winfo_id(), 2)      # GA_ROOT
    i, h = 0, user32.GetTopWindow(0)
    while h:
        if h == hwnd:
            return i
        i += 1
        h = user32.GetWindow(h, 2)                    # GW_HWNDNEXT
    return None


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


GCLP_HICON = -14


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HANDLE),
                ("hbmColor", wintypes.HANDLE)]


def class_icon_size(win):
    """窗口类图标（``GCLP_HICON``）的像素尺寸；没设过返回 None。

    任务栏那一格画的就是它，**尺寸决定清不清晰**：Explorer 只画 18px 左右，
    来源若是 32px 就会被缩糊 —— ``wm_iconbitmap`` 给的就是 32px，这是"糊"的根因；
    ``wm_iconphoto`` 保留原生尺寸。所以这条断言盯的是"喂给任务栏的图有多大"。
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetClassLongPtrW.restype = ctypes.c_void_p
    user32.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetIconInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]

    hwnd = user32.GetAncestor(win.winfo_id(), 2)
    hicon = user32.GetClassLongPtrW(hwnd, GCLP_HICON)
    if not hicon:
        return None
    info = _ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(info)):
        return None
    bm = _BITMAP()
    gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(bm), ctypes.byref(bm))
    return (bm.bmWidth, bm.bmHeight)


def explicit_app_id():
    """进程声明过的 AppUserModelID（从没声明过返回 None）。

    任务栏按钮绑的是**这个**，不是窗口图标 —— 见 app.APP_ID 与
    frameless.set_window_icon 的 docstring。
    """
    shell32 = ctypes.windll.shell32
    shell32.GetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    shell32.GetCurrentProcessExplicitAppUserModelID.argtypes = [
        ctypes.POINTER(ctypes.c_wchar_p)]
    ptr = ctypes.c_wchar_p()
    hr = shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(ptr))
    return ptr.value if hr == 0 else None


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


def main() -> int:
    assert store.DATA_DIR.startswith(tempfile.gettempdir()), \
        f"测试必须用隔离目录，实际 {store.DATA_DIR}"

    # 关掉 NTP 校准并让回调立刻以"失败"落地，这样装配顺序是确定的、可断言的。
    # 校时现在是异步的，必须替掉 sync_async 而不是 sync —— 后者启动路径已经不调了。
    from unittest import mock

    def fake_sync_async(on_done=None):
        if on_done is not None:
            on_done(False)

    sync_off = mock.patch.object(clock, "sync_async", side_effect=fake_sync_async)
    sync_off.start()
    assert clock.offset().total_seconds() == 0, "测试期间偏移必须为 0"

    results = []
    app = App()
    assert app.started is False, "校时出结果之前不该开始判定"
    app.setup()
    assert app.started is False, "setup() 只是起了校时线程，回调还没跑"
    assert app.scheduler.on_fire is not None, \
        "setup() 必须接上 on_fire，否则永远不会弹窗"
    assert app.tray is not None and app.tray.icon is not None, "托盘应已装配"

    app.root.update()            # 让 root.after(0, ...) 的 _after_clock 跑起来
    assert app.started is True, "校时回调之后必须开始判定（哪怕校时失败）"
    results.append("启动顺序：校时出结果 → startup → 开始 tick")

    # 兜底：窗口"该显示却没显示"有两种形态，都要补得回来（exe 上实测到的是第二种）
    # ① Tk 自己收着的（withdraw）—— deiconify 能救
    app.main_window.win.withdraw()
    app.root.update()
    assert not app.main_window.win.winfo_viewable(), "前提：这会儿窗口确实是收着的"
    app._ensure_window_shown()
    app.root.update()
    assert app.main_window.win.winfo_viewable(), "窗口收着的时候，兜底该把它显示出来"
    # ② Tk 认为自己是 normal、**窗口系统**那层却没映射 —— 此时 deiconify 是空操作，
    #    必须落到 Win32 的 ShowWindow。这就是 exe 上那三次的真实形态。
    _hwnd = ctypes.windll.user32.GetAncestor(app.main_window.win.winfo_id(), 2)
    ctypes.windll.user32.ShowWindow(_hwnd, 0)              # SW_HIDE：只动窗口系统
    app.root.update()
    assert not ctypes.windll.user32.IsWindowVisible(_hwnd), "前提：确实藏起来了"
    app._ensure_window_shown()
    app.root.update()
    assert ctypes.windll.user32.IsWindowVisible(_hwnd), \
        "Tk 状态正常但那层没映射时，兜底该用 ShowWindow 补上"
    results.append("兜底：窗口没被映射时（两种形态）都会自己补显示")

    # 兜底：校时回调要是丢了（后台线程在主线程进事件循环之前调 root.after 会抛
    # RuntimeError），tick 也必须自己把判定拉起来 —— 否则这一场会话一条都不弹，
    # 且界面上看不出任何异常。这里直接驱动兜底计数，不等真实定时器。
    app.started = False
    app._startup_ticks = 0
    for _ in range(STARTUP_GRACE_TICKS - 1):
        app._ensure_started()
    assert app.started is False, "还没等够就不该抢跑（会拿没校准的时钟去排期）"
    app._ensure_started()
    assert app.started is True, "等够之后必须自己开始判定，不再依赖那个回调"
    results.append("兜底：校时回调丢了也会在等够之后自己开始判定")

    # 启动就该看到便签本，而不是只留个托盘图标让人再去点
    assert app.main_window.win is not None, "启动后应创建便签本窗口"
    app.root.update()
    assert app.main_window.win.winfo_viewable(), "启动后便签本应当可见"

    now = datetime.now()

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

    # 1. 单次便签到点 -> 弹窗
    once = make_once("链路测试-单次", now - timedelta(seconds=1))
    app.scheduler.items.append(once)
    fired = app.scheduler.tick(now)
    app.root.update()
    assert fired == [once], fired
    assert len(app.popups.open_popups) == 1, app.popups.open_popups
    win = app.popups.open_popups[0]
    assert win.title() == "提醒", win.title()
    assert win.winfo_viewable(), "弹窗应当可见"
    assert win.attributes("-topmost"), "弹窗弹出瞬间应置顶在最上层"

    # 居中显示在屏幕中央
    app.root.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    cx = win.winfo_x() + win.winfo_width() // 2
    cy = win.winfo_y() + win.winfo_height() // 2
    assert abs(cx - sw // 2) <= 40 and abs(cy - sh // 2) <= 40, \
        f"弹窗应居中于屏幕，实际中心 ({cx},{cy})，屏幕中心 ({sw // 2},{sh // 2})"
    results.append(f"tick 触发弹窗，标题「{win.title()}」，可见、置顶且居中于屏幕")

    # 置顶只保留一瞬：之后不恒置顶，用户点别处就按正常层级沉下去
    time.sleep(popup.TOPMOST_HOLD_MS / 1000 + 0.2)
    app.root.update()
    assert not win.attributes("-topmost"), \
        "置顶应在弹出后释放，不能恒为最上层"
    results.append("弹出瞬间置顶一次，随后释放（不恒置顶）")

    # 2. 第二次 tick 不应重复弹
    app.scheduler.tick(datetime.now())
    app.root.update()
    assert len(app.popups.open_popups) == 1, "同一便签不应重复弹窗"
    results.append("第二次 tick 未重复弹窗")

    # 3. 多个同时到点 -> 只保留一个弹窗（后到的覆盖先到的）
    first_popup = app.popups.open_popups[0]
    daily = make_daily("链路测试-每天", now.strftime("%H:%M"),
                       now - timedelta(days=1))
    app.scheduler.items.append(daily)
    app.scheduler.tick(datetime.now())
    app.root.update()
    assert len(app.popups.open_popups) == 1, \
        f"同时到点应只留一个弹窗，实际 {len(app.popups.open_popups)} 个"
    assert not first_popup.winfo_exists(), "旧弹窗应被关掉（覆盖形式）"
    assert daily.next_fire_at > datetime.now(), daily.next_fire_at
    results.append(f"同时到点只弹一个（覆盖），daily 滚到下次 {daily.next_fire_at}")

    # 4. 弹窗按钮真的能把状态写回（现在开着的是 daily 那个）
    find_button(app.popups.open_popups[0], "知道了").invoke()
    app.root.update()
    assert daily.done is False, "daily 不该被标完成"
    assert app.popups.open_popups == [], "点完应关闭弹窗"
    # 被覆盖关掉的那个 once 并没有被处理过，仍应算「已错过」
    assert once.done is False, "被覆盖关掉 ≠ 用户已处理"
    assert once.is_missed(datetime.now()), "没处理的 once 应仍算已错过"
    results.append("「知道了」写回状态；被覆盖的弹窗不等于已处理（仍会标红）")

    # 5. 稍后 10 分钟：不应标完成，且到期能再弹
    snooze_item = make_once("链路测试-稍后", now - timedelta(seconds=1))
    app.scheduler.items.append(snooze_item)
    app.scheduler.tick(datetime.now())
    app.root.update()
    find_button(app.popups.open_popups[-1], "稍后 10 分钟").invoke()
    app.root.update()
    assert snooze_item.done is False, "稍后不应标记完成"
    assert snooze_item.snooze_until is not None
    assert snooze_item.should_fire(snooze_item.snooze_until + timedelta(seconds=1)), \
        "稍后到期后必须能再次触发（mark_fired 不设 done 的意义）"
    results.append("「稍后 10 分钟」不标完成且到期能再触发")

    # 启动时不该补弹程序没运行期间错过的单次提醒（只在列表里标红）——
    # 以前会把攒下来的过期提醒在启动后挨个弹一遍
    missed_once = make_once("昨天错过的", now - timedelta(days=1))
    app.scheduler.items.append(missed_once)
    app.scheduler.startup()                  # 相当于重启后的第一次启动
    app.root.update()
    fired = app.scheduler.tick(datetime.now())
    app.root.update()
    assert missed_once not in fired, \
        "启动后不该把程序没运行期间错过的单次提醒弹出来"
    assert missed_once.is_missed(datetime.now()), "但列表里该照常标红"
    results.append("启动时不补弹错过的单次提醒，只在列表里标红")

    # 6. 「处理后计时」的循环：弹窗上点「关闭」**或**「知道了」都算处理了这一格，
    #    下一次从点它的那一刻重新起算（2026-09-29 裁决）。
    #    对照一：固定模式的格子由时段决定，处理改变不了它。
    #    对照二：便签本的「标记已读」**不算**处理（那是事后清列表，不是"看到了那张弹窗"）。
    LO, HI = "00:00", "23:59"

    def past_interval(text, **kw):
        r = make_interval(text, list(range(7)), LO, HI, 60, True,
                          datetime.now(), **kw)
        r.next_fire_at = datetime.now() - timedelta(seconds=1)
        return r

    rolling = past_interval("链路测试-处理后计时", interval_mode="rolling")
    kept = rolling.next_fire_at
    app.popups.show(rolling)
    app.root.update()
    find_button(app.popups.open_popups[-1], "关闭").invoke()
    app.root.update()
    assert rolling.next_fire_at > kept, \
        f"rolling 循环点「关闭」该从这一刻重新起算，实际 {rolling.next_fire_at}"
    assert rolling.next_fire_at > datetime.now(), \
        f"重排后必须落在将来，实际 {rolling.next_fire_at}"

    acked = past_interval("链路测试-知道了也重排", interval_mode="rolling")
    kept = acked.next_fire_at
    app.popups.show(acked)
    app.root.update()
    find_button(app.popups.open_popups[-1], "知道了").invoke()
    app.root.update()
    assert acked.next_fire_at > kept, \
        f"rolling 循环点「知道了」该从这一刻重新起算，实际 {acked.next_fire_at}"

    # 对照一：固定模式本来就不受处理影响，下一次仍由时段决定
    fixed = past_interval("链路测试-固定对照")
    kept = fixed.next_fire_at
    app.popups.show(fixed)
    app.root.update()
    find_button(app.popups.open_popups[-1], "关闭").invoke()
    app.root.update()
    assert fixed.next_fire_at == kept, \
        f"固定模式点「关闭」不该改动下一次时间，实际 {fixed.next_fire_at}"

    # 对照二：便签本「标记已读」。用一条**还没到点**的循环，它不会在后面的 tick 里
    # 冒出来搅局（那一段在数 open_popups 的个数）
    mw_roll = make_interval("链路测试-标记已读不重排", list(range(7)), LO, HI,
                            60, True, datetime.now(), interval_mode="rolling")
    app.main_window.items.append(mw_roll)
    app.main_window.refresh()
    kept = mw_roll.next_fire_at
    assert kept > datetime.now(), f"前提：这条该是未来的，实际 {kept}"
    tree = app.main_window.tree
    tree.selection_set([mw_roll.id])
    app.main_window._complete()
    app.root.update()
    assert mw_roll.next_fire_at == kept, \
        f"「标记已读」不该挪动循环的下一次，实际 {mw_roll.next_fire_at}"
    results.append("弹窗两个按钮都重排「处理后计时」；固定模式与「标记已读」不动排期")

    # 编辑框点「已处理」得把这条循环正开着的那张弹窗收掉。不关的话用户回头
    # 再点一下那张弹窗的「知道了」，会又推一格（点两次推两次），见 spec §4。
    closing = past_interval("链路测试-手动已处理关弹窗", interval_mode="rolling")
    app.popups.show(closing)
    app.root.update()
    assert len(app.popups.open_popups) == 1, len(app.popups.open_popups)
    doomed_win = app.popups.open_popups[0]

    app.popups.close_for(closing)
    app.root.update()
    assert not doomed_win.winfo_exists(), "close_for 该把这张弹窗销毁掉"
    assert app.popups.open_popups == [], \
        f"close_for 该把它从 open_popups 摘掉，实际 {app.popups.open_popups}"

    app.popups.close_for(closing)        # 幂等：重复调用不该抛
    results.append("close_for 关掉指定便签的弹窗并摘出 open_popups（重复调用不抛）")

    # 上一张没处理时，到下一格要**再弹一张**（新弹窗会重新置顶一次），
    # 而且旧的那张被顶掉 —— 同一时刻只留一张，不叠一屏
    again = make_interval("链路测试-到点再弹", list(range(7)), LO, HI, 60, True,
                          datetime.now(), interval_mode="rolling")
    again.next_fire_at = datetime.now() - timedelta(seconds=1)
    app.scheduler.items.append(again)
    try:
        app.scheduler.tick()
        app.root.update()
        assert len(app.popups.open_popups) == 1, \
            f"该弹出一张，实际 {len(app.popups.open_popups)} 张"
        first_popup = app.popups.open_popups[-1]
        app.scheduler.tick(again.next_fire_at)      # 第一张故意不处理，等到下一格
        app.root.update()
        assert len(app.popups.open_popups) == 1, \
            "同一时刻只该留最新一张弹窗，旧的没处理也不能叠着"
        assert app.popups.open_popups[-1] is not first_popup, \
            "到下一格该弹出一张新弹窗"
        assert not first_popup.winfo_exists(), "旧弹窗该被新提醒顶掉"
    finally:
        app.popups.close_all()
        app.scheduler.items.remove(again)
    results.append("上一张没处理时到下一格会再弹一张，旧的被顶掉")

    # 6. 暂停时 tick 不弹窗
    app.scheduler.paused = True
    paused_item = make_once("暂停期间不该弹", now - timedelta(seconds=1))
    app.scheduler.items.append(paused_item)
    assert app.scheduler.tick(datetime.now()) == [], "暂停时不应触发"
    assert paused_item.last_fired_at is None
    results.append("暂停期间不弹窗且不更新记账")

    # 7. 便签本居中于屏幕；新建对话框相对主窗口居中
    from reminders import edit_dialog
    app.main_window.show()
    app.root.update()

    mw = app.main_window.win
    app.root.update_idletasks()
    mcx = mw.winfo_rootx() + mw.winfo_width() // 2
    mcy = mw.winfo_rooty() + mw.winfo_height() // 2
    assert abs(mcx - sw // 2) <= 40 and abs(mcy - sh // 2) <= 40, \
        f"便签本应居中，实际中心 ({mcx},{mcy})，屏幕中心 ({sw // 2},{sh // 2})"
    results.append("便签本主窗口居中于屏幕")

    # 把主窗口挪到左上角，用来区分「相对父窗口居中」与「居中于屏幕」：
    # 若是后者，对话框会留在屏幕中央，下面的断言就会失败
    mw.geometry("+120+90")
    app.root.update()
    app.root.update_idletasks()
    mwx, mwy = mw.winfo_rootx(), mw.winfo_rooty()
    mww, mwh = mw.winfo_width(), mw.winfo_height()

    ed = {}

    def drive_editor():
        tops = [w for w in app.main_window.win.winfo_children()
                if isinstance(w, tk.Toplevel)]
        if not tops:
            ed["err"] = "找不到新建提醒对话框"
            return
        dlg = tops[0]
        ed["title"] = dlg.title()
        app.root.update_idletasks()
        ed["pos"] = (dlg.winfo_rootx(), dlg.winfo_rooty())
        ed["size"] = (dlg.winfo_width(), dlg.winfo_height())

        # 日期掩码：只敲数字，'-' 应自动补上
        from reminders.edit_dialog import (apply_mask, DATE_MASK, DATE_LIMITS,
                                           time_key, time_display, time_parse)
        entries = []

        def walk(w):
            for c in w.winfo_children():
                if isinstance(c, tk.Entry):
                    entries.append(c)
                walk(c)

        walk(dlg)
        ed["date_initial"] = entries[0].get()
        ed["time_initial"] = entries[1].get()
        ed["bound"] = bool(entries[0].bind("<KeyRelease>"))
        # 编辑框跟主窗口一样是无边框圆角纸
        ed["frameless"] = bool(dlg.overrideredirect())
        ed["has_canvas"] = any(isinstance(c, tk.Canvas)
                               for c in dlg.winfo_children())

        # 循环模式内容最多。窗口高度现在是按内容量出来的，所以既要确认
        # 「保存」没被挤出去，也要确认窗口真的跟着长高了（写死高度是老的坑）
        def all_widgets(w, out=None):
            out = [] if out is None else out
            for c in w.winfo_children():
                out.append(c)
                all_widgets(c, out)
            return out

        ed["h_once"] = dlg.winfo_height()
        for w in all_widgets(dlg):
            if isinstance(w, tk.Radiobutton) and w.cget("text") == "循环":
                w.invoke()
        dlg.update_idletasks()
        ed["h_interval"] = dlg.winfo_height()
        save_btn = find_button(dlg, "保存")
        ed["save_bottom"] = save_btn.winfo_rooty() + save_btn.winfo_height()
        ed["dlg_bottom"] = dlg.winfo_rooty() + dlg.winfo_height()
        ed["timing_radios"] = [
            w.cget("text") for w in all_widgets(dlg)
            if isinstance(w, tk.Radiobutton)
            and w.cget("text") in ("固定时刻", "处理后计时")]
        # 时间 / 时段开始 / 时段结束三个框都该走固定格模型，绑的是 <KeyPress>
        ed["time_keypress"] = sum(1 for e in entries if e.bind("<KeyPress>"))
        entries[0].delete(0, "end")
        entries[0].insert(0, "20261231")
        apply_mask(entries[0], DATE_MASK)
        ed["date_masked"] = entries[0].get()

        # 时间固定 4 格：删哪格哪格留空，后面的数字不左移，光标停在原处
        cells, cur = time_key(time_parse("08:00"), 4, "BackSpace")
        ed["back_last"] = (time_display(cells), cur)
        cells, cur = time_key(time_parse("08:00"), 2, "BackSpace")
        ed["back_mid"] = (time_display(cells), cur)
        # 智能退格：光标左边连着空位时跳过，直接清掉上一个有数字的格
        ed["back_smart"] = time_key(["0", "", "", "5"], 4, "BackSpace")
        ed["back_smart2"] = time_key(["0", "", "", ""], 3, "BackSpace")
        # 覆盖式输入：光标停在哪格就改哪格，冒号跳过去
        ed["type_mid"] = time_key(time_parse("08:00"), 1, "9")
        ed["arrow"] = time_key(time_parse("08:00"), 1, "Right")
        # 格式只能是 xx:xx：字母吃掉，越界值打不进去
        ed["reject_letter"] = time_key(time_parse("08:00"), 4, "a") is None
        blocked = time_key(["2", "", "0", "0"], 1, "5")      # 25 点
        ed["reject_hour"] = (blocked[0][1] == "" and blocked[1] == 1)
        blocked = time_key(["2", "3", "6", ""], 3, "0")      # 23:60
        ed["reject_minute"] = (blocked[0][3] == "" and blocked[1] == 3)

        # 非法值在输入阶段就被挡住，根本打不进去
        entries[0].delete(0, "end")
        entries[0].insert(0, "2026")
        keep = {"last_ok": entries[0].get()}
        entries[0].insert(0, "45")          # 想输 45 月
        ed["reject_month"] = not apply_mask(entries[0], DATE_MASK,
                                            DATE_LIMITS, keep)
        ed["date_after_reject"] = entries[0].get()
        entries[0].delete(0, "end")
        entries[0].insert(0, "2026")
        entries[0].insert(0, "13")          # 13 月也不行
        ed["reject_month13"] = not apply_mask(entries[0], DATE_MASK,
                                              DATE_LIMITS, keep)

        # TimeMask 的接线部分（纯函数之外的那层）：按键进去，看内容和光标
        from reminders.edit_dialog import TimeMask, time_cell_at

        class FakeKey:
            def __init__(self, keysym):
                self.keysym = keysym

        probe = tk.Entry(dlg)
        probe.insert(0, "08:00")
        mask = TimeMask(probe)
        ed["mask_init"] = (probe.get(), probe.index("insert"))
        ed["mask_break"] = mask._on_key(FakeKey("BackSpace"))
        ed["mask_back"] = (probe.get(), probe.index("insert"))
        ed["mask_tab"] = (mask._on_key(FakeKey("Tab")), probe.get())
        ed["mask_letter"] = (mask._on_key(FakeKey("a")), probe.get())
        mask.set_text("23:59")              # 快捷按钮改值走的路径
        ed["mask_set"] = (probe.get(), probe.index("insert"))
        ed["pos_cells"] = [time_cell_at(p) for p in range(6)]
        probe.destroy()
        dlg.destroy()

    app.root.after(250, drive_editor)
    edit_dialog.open_editor(app.main_window.win, now=datetime.now())
    assert "err" not in ed, ed.get("err")
    assert ed["title"] == "新建提醒", ed["title"]
    ex, ey = ed["pos"]
    ew, eh = ed["size"]
    want_x, want_y = mwx + mww // 2, mwy + mwh // 2
    got_x, got_y = ex + ew // 2, ey + eh // 2
    assert abs(got_x - want_x) <= 40 and abs(got_y - want_y) <= 40, \
        f"对话框应相对主窗口居中：主窗口中心 ({want_x},{want_y})，对话框中心 ({got_x},{got_y})"
    assert abs(got_x - sw // 2) > 100, \
        f"主窗口已移到 ({mwx},{mwy})，对话框却仍在屏幕中央 ({got_x},{got_y})"
    results.append("新建提醒对话框相对主窗口居中（主窗口移开后仍跟随）")

    # 循环区多了一行「计时」二选一，对话框别被撑爆
    assert ed["timing_radios"] == ["固定时刻", "处理后计时"], \
        f"循环区应有「计时」二选一，实际 {ed['timing_radios']}"
    assert ed["save_bottom"] <= ed["dlg_bottom"], \
        f"「保存」按钮被挤出对话框了（{ed['save_bottom']} > {ed['dlg_bottom']}）"
    assert ed["frameless"], "编辑框也该是无边框圆角的（跟主窗口一套）"
    assert ed["has_canvas"], "编辑框该有承载圆角纸的 canvas"
    assert ed["h_interval"] > ed["h_once"], \
        f"切到循环后窗口该跟着长高，实际 {ed['h_once']} -> {ed['h_interval']}"
    results.append("编辑框无边框圆角，且有「计时」二选一、保存没被挤出、"
                   "切循环会跟着长高")

    # 日期默认已填今天，且只敲数字会自动补 '-'
    assert ed["date_initial"] == datetime.now().strftime("%Y-%m-%d"), \
        f"日期应默认填今天，实际 {ed['date_initial']}"
    assert ed["date_initial"].count("-") == 2 and ed["time_initial"].count(":") == 1
    assert ed["date_masked"] == "2026-12-31", f"日期掩码未生效: {ed['date_masked']}"
    assert ed["bound"], "日期框未绑定 <KeyRelease>，掩码不会在真实输入时生效"
    assert ed["time_keypress"] == 3, \
        f"时间 / 时段开始 / 时段结束三个框都该走固定格模型，实际 {ed['time_keypress']} 个"
    results.append("日期默认填今天；只敲数字自动补 '-'（20261231→2026-12-31）")

    # 时间固定 4 格：删哪格哪格留空、后面的数字不左移、光标停在原处
    assert ed["back_last"] == ("08:0 ", 3), \
        f"退格删最后一位应留空并把光标左移一格，实际 {ed['back_last']}"
    assert ed["back_mid"] == ("0 :00", 1), \
        f"删中间一位时后面的数字不该左移补位，实际 {ed['back_mid']}"
    assert ed["back_smart"] == (["0", "", "", ""], 3), \
        f"智能退格应跳过空位直达上一个数字，实际 {ed['back_smart']}"
    assert ed["back_smart2"] == (["", "", "", ""], 0), \
        f"左边连着空位时也要能一路清到第一个数字，实际 {ed['back_smart2']}"
    assert ed["type_mid"] == (["0", "9", "0", "0"], 2), \
        f"光标停在哪格就该改哪格，实际 {ed['type_mid']}"
    assert ed["arrow"] == (["0", "8", "0", "0"], 2), \
        f"右方向键应按格走一步，实际 {ed['arrow']}"
    results.append("时间框固定 4 格：删位留空不左移、智能退格、光标按格走")

    assert ed["reject_letter"], "字母不该能进时间框（格式只能是 xx:xx）"
    assert ed["reject_hour"], "25 点应该打不进去"
    assert ed["reject_minute"], "23:60 应该打不进去"
    assert ed["reject_month"] and ed["reject_month13"], \
        "45 月和 13 月应该打不进去"
    assert ed["date_after_reject"] == "2026", \
        f"被拒后应退回上一个合法状态，实际 {ed['date_after_reject']!r}"
    results.append("非法值打不进去：字母、25 点、23:60、45/13 月一律被拒")

    # TimeMask 的接线（纯函数之外那层）：Tab 放行、字母吃掉、退格后光标按格走
    assert ed["mask_init"] == ("08:00", 5), \
        f"初始应满格且光标在末尾，实际 {ed['mask_init']}"
    assert ed["mask_break"] == "break", "退格要返回 break 拦掉 tkinter 的默认编辑"
    assert ed["mask_back"] == ("08:0 ", 4), \
        f"退格后应为 '08:0 '、光标停在第 4 格后，实际 {ed['mask_back']}"
    assert ed["mask_tab"] == ("", "08:0 "), \
        f"Tab 必须放行，否则跳不到下一个控件，实际 {ed['mask_tab']}"
    assert ed["mask_letter"] == ("break", "08:0 "), \
        f"字母要吃掉且不动内容，实际 {ed['mask_letter']}"
    assert ed["mask_set"] == ("23:59", 5), \
        f"快捷按钮改值应走格模型重画，实际 {ed['mask_set']}"
    assert ed["pos_cells"] == [0, 1, 2, 2, 3, 4], \
        f"鼠标位置到格索引的映射不对，实际 {ed['pos_cells']}"
    results.append("TimeMask 接线：Tab 放行、字母吃掉、退格与改值后光标按格走")

    # 非法值必须提示，不能静默改成别的时间（只有格式问题才静默纠正）

    def open_editor_with(prepare, title="新建提醒", reminder=None, *,
                         button="保存", before=None, after=None,
                         editor_now=None):
        """开编辑框 → prepare 摆好输入 → 点 button → 返回结果。

        两条命必须保住：窗口找不到时要重试（after 可能早于窗口建出来），
        以及无论如何都得关窗 —— wait_window() 只在窗口销毁后才返回，
        driver 里漏掉 destroy 会让整个测试文件永远挂住，之前就这么挂过一次。

        button     —— 点哪个页脚按钮（"保存" / "已处理"）。
        before     —— 点之前跑一次（测"基准时刻是点击那一刻"用）。
        after      —— 点之后、销毁窗口之前跑一次（测对话框有没有自己关掉用）。
        editor_now —— 传进 open_editor 的 now；不传就是 datetime.now()（既有行为）。
                      传可调用对象可以测"打开框之后时钟还在走"。
        """
        box = {}

        def tops():
            return [w for w in app.main_window.win.winfo_children()
                    if isinstance(w, tk.Toplevel) and w.title() == title]

        def fuse():
            """保险丝：driver 出意外时兜底关窗，别让 wait_window 无限等下去。"""
            if box.get("done"):
                return
            if "err" not in box:
                box["err"] = RuntimeError("对话框一直没被关闭")
            for w in app.main_window.win.winfo_children():
                if isinstance(w, tk.Toplevel):
                    w.destroy()

        def driver(retries=6):
            found = tops()
            if not found:
                if retries > 0:          # 可能只是还没建出来，再等等
                    app.root.after(100, lambda: driver(retries - 1))
                    return
                box["err"] = RuntimeError("找不到对话框")
                fuse()
                return
            dlg = found[0]

            def walk(w, out=None):
                out = [] if out is None else out
                for c in w.winfo_children():
                    out.append(c)
                    walk(c, out)
                return out

            try:
                # 先填上内容，否则会被「内容不能为空」提前拦下，后面的校验测不到
                for c in walk(dlg):
                    if isinstance(c, tk.Text):
                        c.delete("1.0", "end")
                        c.insert("1.0", "测试")
                        break
                prepare(dlg, walk)
                app.root.update()
                if before is not None:
                    before()
                    app.root.update()
                find_button(dlg, button).invoke()
                if after is not None:
                    after(dlg)
                # 保存被校验拦下（返回 None）是不少用例故意要的结果，
                # 不是错误 —— 判定交给调用方，这里只管把窗口收干净
            except Exception as e:
                box["err"] = e
            finally:
                box["done"] = True
                if dlg.winfo_exists():
                    dlg.destroy()

        app.root.after(200, driver)
        fuse_id = app.root.after(8000, fuse)
        value = edit_dialog.open_editor(
            app.main_window.win, reminder=reminder,
            now=editor_now if editor_now is not None else datetime.now(),
            # 走 MainWindow._edit() 同一条接线 —— 不然 App 的收尾（关弹窗、
            # 按「留记录」补记录）永远收不到回调。Task 5 之前 MainWindow
            # 还没这个属性，取 None 不影响前面的任务。
            on_handled=getattr(app.main_window, "on_handled", None))
        app.root.after_cancel(fuse_id)
        if "err" in box:
            raise box["err"]
        return value

    def pick(dlg, walk, kind_label, mode_label=None):
        for w in walk(dlg):
            if isinstance(w, tk.Radiobutton) and w.cget("text") == kind_label:
                w.invoke()
        app.root.update()
        if mode_label:
            for w in walk(dlg):
                if isinstance(w, tk.Radiobutton) and w.cget("text") == mode_label:
                    w.invoke()
            app.root.update()

    def entries_of(dlg, walk):
        # 深度优先遍历，顺序由控件创建顺序决定，不是视觉顺序：
        # 0 日期, 1 时间, 2 区间起, 3 区间止, 4 时段起, 5 时段止, 6 间隔
        # 下面的索引自检用例会验证这个顺序没变
        return [c for c in walk(dlg) if isinstance(c, tk.Entry)]

    def set_entry(entry, value):
        entry.delete(0, "end")
        entry.insert(0, value)

    # 校验警告走的是自家纸窗口（prompt.notice）。替掉它只为"不阻塞地把文案记下来"——
    # 那个窗口本身长什么样另有专门用例盯着（「提示是自家的纸窗口」那条）。
    original_warn = prompt.notice
    warnings = []
    prompt.notice = lambda parent, message, title="提示": warnings.append(message)
    try:
        warnings.clear()

        # 索引自检：把「间隔」设成 30，存出来就该是 30 分钟。
        # 下面几个用例都靠这套索引定位输入框，索引错了它们会集体误判。
        def prep_sanity(dlg, walk):
            pick(dlg, walk, "循环")
            set_entry(entries_of(dlg, walk)[6], "30")

        r = open_editor_with(prep_sanity)
        assert r is not None and r.interval_minutes == 30, \
            f"间隔输入框的索引可能不对，存出来是 {r and r.interval_minutes}"

        warnings.clear()

        def prep_bad_date(dlg, walk):
            pick(dlg, walk, "循环", "按日期区间")
            set_entry(entries_of(dlg, walk)[2], "2026-45-11")

        assert open_editor_with(prep_bad_date) is None, "非法日期不该保存成功"
        assert warnings and "无效" in warnings[-1], warnings

        for bad in ("-5", "1.5", "abc"):
            warnings.clear()

            def prep_bad_interval(dlg, walk, bad=bad):
                pick(dlg, walk, "循环")
                set_entry(entries_of(dlg, walk)[6], bad)

            assert open_editor_with(prep_bad_interval) is None, \
                f"间隔「{bad}」不该保存成功"
            assert warnings and "间隔" in warnings[-1], (bad, warnings)

        warnings.clear()

        def prep_reverse(dlg, walk):
            pick(dlg, walk, "循环")
            es = entries_of(dlg, walk)
            set_entry(es[4], "18:00")
            set_entry(es[5], "08:00")

        assert open_editor_with(prep_reverse) is None, "结束早于开始不该保存成功"
        assert warnings and "晚于" in warnings[-1], warnings
        results.append("非法值会提示：日期 2026-45-11 / 间隔 -5、1.5、abc / 时段倒置")

        # 时段填一半（固定 4 格还有空格）必须提示，不能静默退回默认值 ——
        # 用户明明动了手，悄悄换成 08:00/18:00 比报错更让人困惑
        warnings.clear()

        def prep_half_time(dlg, walk):
            pick(dlg, walk, "循环")
            set_entry(entries_of(dlg, walk)[4], "08:0 ")

        assert open_editor_with(prep_half_time) is None, "时段填一半不该保存成功"
        assert warnings and "没填完整" in warnings[-1], warnings

        # 反向：整段清空仍按空值处理，退回默认时段
        warnings.clear()

        def prep_empty_time(dlg, walk):
            pick(dlg, walk, "循环")
            es = entries_of(dlg, walk)
            set_entry(es[4], "  :  ")
            set_entry(es[5], "  :  ")

        r = open_editor_with(prep_empty_time)
        assert r is not None and r.window_start == "08:00" and r.window_end == "18:00", \
            f"整段清空应退回默认时段，实际 {r and (r.window_start, r.window_end)}"
        results.append("时段填一半会提示「没填完整」；整段清空才退回默认时段")

        # 循环的「计时」二选一：选「处理后计时」要能存进去
        warnings.clear()

        def prep_rolling(dlg, walk):
            pick(dlg, walk, "循环")
            for w in walk(dlg):
                if (isinstance(w, tk.Radiobutton)
                        and w.cget("text") == "处理后计时"):
                    w.invoke()
            app.root.update()

        r = open_editor_with(prep_rolling)
        assert r is not None and r.interval_mode == "rolling", \
            f"选「处理后计时」应存出 rolling，实际 {r and r.interval_mode}"

        # 编辑已有循环便签时切换计时方式，必须就地改到原对象上 ——
        # _COPY_FIELDS 漏了字段就会「改了不生效」，这个坑犯过
        original = make_interval("原循环", [0, 1, 2, 3, 4], "08:00", "18:00",
                                 60, True, datetime.now())
        assert original.interval_mode == "fixed"

        edited = open_editor_with(prep_rolling, title="编辑提醒", reminder=original)
        assert edited is original, \
            f"编辑应就地改原对象，实际 {edited!r}，校验提示={warnings}"
        assert original.interval_mode == "rolling", \
            f"编辑时切换计时方式没生效（_COPY_FIELDS 可能漏了字段），" \
            f"实际 {original.interval_mode}"
        results.append("循环「计时」二选一：新建能存 rolling、编辑能改到原对象")

        # 编辑保存与排期：只改文案**不该**动下一次，改了间隔才重排（2026-09-29）。
        # 以前保存路径一律 make_interval(..., now) 重造再全量拷回、顺手清掉
        # last_fired_at —— 于是"什么都没改点一下保存"也会把下一次推成"现在 + 间隔"，
        # 用户报的"循环时间会因为重启而变"就是它（加上 normalize 那一处）。
        # 时段用 00:00-23:59，免得这个用例在早上/晚上跑出不同结果。
        keep = make_interval("原循环", [0, 1, 2, 3, 4], LO, HI, 60, True,
                             datetime.now(), interval_mode="rolling")
        keep.next_fire_at = datetime.now() + timedelta(minutes=17)   # 相位 :17
        keep.last_fired_at = datetime.now() - timedelta(hours=1)
        want_next, want_fired = keep.next_fire_at, keep.last_fired_at

        def prep_nothing(dlg, walk):
            pick(dlg, walk, "循环")          # 除了驱动层自动填的正文，什么都不改

        assert open_editor_with(prep_nothing, title="编辑提醒",
                                reminder=keep) is keep
        assert keep.next_fire_at == want_next, \
            f"只改文案不该重排，实际 {keep.next_fire_at}（期望 {want_next}）"
        assert keep.last_fired_at == want_fired, \
            "没重排就不该清掉上次触发记录"

        def prep_shorter(dlg, walk):
            pick(dlg, walk, "循环")
            set_entry(entries_of(dlg, walk)[6], "30")

        assert open_editor_with(prep_shorter, title="编辑提醒",
                                reminder=keep) is keep
        assert keep.interval_minutes == 30, keep.interval_minutes
        assert keep.last_fired_at is None, "重排后旧的触发记录该清掉"
        delta = keep.next_fire_at - datetime.now()
        assert timedelta(minutes=25) < delta < timedelta(minutes=35), \
            f"改了间隔该按「现在 + 30 分」重排，实际 {keep.next_fire_at}（差 {delta}）"
        results.append("编辑保存：只改文案不重排，改间隔才按「现在 + 间隔」重排")

        # 「保存」的基准时刻 = 点保存那一刻，不是打开框那一刻（2026-10-15 修）。
        # 注入 datetime 会让 _now() 恒定、验不到这个差异，所以这里给 open_editor
        # 传一个**可调用对象**当 now，由测试控制它什么时候往前走。
        drift = make_interval("漂移对照", [0, 1, 2, 3, 4], LO, HI, 60, True,
                              datetime.now(), interval_mode="rolling")
        fake_t = {"now": datetime.now()}

        def prep_drift(dlg, walk):
            pick(dlg, walk, "循环")
            set_entry(entries_of(dlg, walk)[6], "30")

        def stall():
            """打开框之后、点保存之前，把测试时钟往前拨 3 分钟。"""
            fake_t["now"] = fake_t["now"] + timedelta(minutes=3)

        assert open_editor_with(prep_drift, title="编辑提醒", reminder=drift,
                                before=stall,
                                editor_now=lambda: fake_t["now"]) is drift
        delta = drift.next_fire_at - datetime.now()
        assert timedelta(minutes=32) < delta < timedelta(minutes=34), \
            f"重排基准该是「点保存那一刻 + 30 分」，实际 {drift.next_fire_at}" \
            f"（差 {delta}）；差约 30 分说明基准是打开框那一刻（旧行为）"
        results.append("编辑保存：重排基准是点保存那一刻，不是打开框那一刻")

        # 「已处理」只在**编辑已有的「处理后计时」循环**时露脸（2026-10-15 spec §2）
        #
        # 不能用 collect_buttons 判在不在 —— 它递归 winfo_children()，而
        # pack_forget 只是"不摆出来"，控件本身还是 btns 的子节点，照样被它数到。
        # 判可见性得看 winfo_manager()（pack 好了才非空字符串）。
        def managed_buttons(widget, out=None):
            out = [] if out is None else out
            for c in widget.winfo_children():
                if isinstance(c, tk.Button) and c.winfo_manager():
                    out.append(c)
                managed_buttons(c, out)
            return out

        def buttons_seen(prepare, **kw):
            """开一次编辑框，返回这一刻**摆出来的**按钮文案集合。"""
            seen_btns = {}

            def prep(dlg, walk):
                prepare(dlg, walk)
                seen_btns["set"] = set(b.cget("text")
                                       for b in managed_buttons(dlg))

            open_editor_with(prep, **kw)
            return seen_btns["set"]

        def prep_rolling_form(dlg, walk):
            pick(dlg, walk, "循环", "处理后计时")

        def prep_noop(dlg, walk):
            pass

        # 新建：就算表单选成「处理后计时」也不给 —— 新建本来就是"保存时刻 + 间隔"，
        # 没有"已处理的上一格"可记
        assert "已处理" not in buttons_seen(prep_rolling_form, title="新建提醒"), \
            "新建时不该出现「已处理」"

        fixed_src = make_interval("可见性-固定", list(range(7)), LO, HI, 60, True,
                                  datetime.now())
        assert fixed_src.interval_mode == "fixed", fixed_src.interval_mode
        assert "已处理" not in buttons_seen(prep_noop, title="编辑提醒",
                                            reminder=fixed_src), \
            "固定时刻的循环不该出现「已处理」"

        once_src = make_once("可见性-单次", datetime.now() + timedelta(hours=1))
        assert "已处理" not in buttons_seen(prep_noop, title="编辑提醒",
                                            reminder=once_src), \
            "单次便签不该出现「已处理」"

        roll_src = make_interval("可见性-滚动", list(range(7)), LO, HI, 60, True,
                                 datetime.now(), interval_mode="rolling")
        assert "已处理" in buttons_seen(prep_noop, title="编辑提醒",
                                        reminder=roll_src), \
            "编辑「处理后计时」的循环该出现「已处理」"

        # 在框里把计时切回「固定时刻」，按钮要立刻消失
        def prep_to_fixed(dlg, walk):
            pick(dlg, walk, "循环", "固定时刻")

        fixed2 = make_interval("可见性-切走", list(range(7)), LO, HI, 60, True,
                               datetime.now(), interval_mode="rolling")
        assert "已处理" not in buttons_seen(prep_to_fixed, title="编辑提醒",
                                            reminder=fixed2), \
            "切回「固定时刻」后「已处理」该消失"
        results.append("「已处理」只在编辑已有的「处理后计时」循环时出现")

        # 点它：对话框自己关掉、排期从点击那一刻重新起算、snooze 被清
        manual = make_interval("可见性-点它", list(range(7)), LO, HI, 60, True,
                               datetime.now(), interval_mode="rolling")
        manual.next_fire_at = datetime.now() + timedelta(minutes=17)
        manual.snooze_until = datetime.now() + timedelta(minutes=5)
        kept_next = manual.next_fire_at
        closed = {}

        def note_closed(dlg):
            app.root.update()
            closed["exists"] = bool(dlg.winfo_exists())

        assert open_editor_with(prep_noop, title="编辑提醒", reminder=manual,
                                button="已处理", after=note_closed) is manual
        assert closed.get("exists") is False, "点「已处理」该把对话框也关掉"
        assert manual.next_fire_at > kept_next, \
            f"该从此刻重新起算（原格 {kept_next}），实际 {manual.next_fire_at}"
        delta = manual.next_fire_at - datetime.now()
        assert timedelta(minutes=59) < delta < timedelta(minutes=61), \
            f"该落在「点击时刻 + 60 分」，实际 {manual.next_fire_at}（差 {delta}）"
        assert manual.snooze_until is None, manual.snooze_until
        results.append("点「已处理」：关窗 + 从此刻重新起算 + 清 snooze")

        # 校验没过时点它：弹提示、**不动排期**、对话框不关（跟「保存」一样）
        guard = make_interval("可见性-校验", list(range(7)), LO, HI, 60, True,
                              datetime.now(), interval_mode="rolling")
        guard.next_fire_at = datetime.now() + timedelta(minutes=17)
        want_guard = guard.next_fire_at
        guard_closed = {}

        def prep_bad_step(dlg, walk):
            pick(dlg, walk, "循环", "处理后计时")
            set_entry(entries_of(dlg, walk)[6], "-5")

        def note_guard_closed(dlg):
            app.root.update()
            guard_closed["exists"] = bool(dlg.winfo_exists())

        warnings.clear()
        assert open_editor_with(prep_bad_step, title="编辑提醒", reminder=guard,
                                button="已处理",
                                after=note_guard_closed) is None
        assert warnings and "间隔" in warnings[-1], warnings
        assert guard.next_fire_at == want_guard, \
            f"校验没过就不该动排期，实际 {guard.next_fire_at}"
        assert guard_closed.get("exists") is True, \
            "校验没过时对话框该留着（跟「保存」一致）"
        results.append("校验没过时「已处理」被拦下：不动排期、对话框不关")

        # 端到端：App 收尾 —— 关掉那张弹窗、（勾了「留记录」才）补一条同 parent_id
        # 的已完成记录、落盘刷新
        live = make_interval("端到端-留记录开", list(range(7)), LO, HI, 60, True,
                             datetime.now(), interval_mode="rolling",
                             log_to_list=True)
        live.next_fire_at = datetime.now() + timedelta(minutes=17)
        app.main_window.items.append(live)
        app.main_window.refresh()
        app.popups.show(live)
        app.root.update()
        assert len(app.popups.open_popups) == 1, len(app.popups.open_popups)
        live_win = app.popups.open_popups[0]
        before_count = len(app.main_window.items)

        assert open_editor_with(prep_noop, title="编辑提醒", reminder=live,
                                button="已处理") is live
        app.root.update()

        assert not live_win.winfo_exists(), "点「已处理」该把这条循环的弹窗收掉"
        assert app.popups.open_popups == [], app.popups.open_popups
        logs = [i for i in app.main_window.items if i.parent_id == live.id]
        assert len(logs) == 1, f"该补一条记录，实际 {len(logs)} 条"
        assert len(app.main_window.items) == before_count + 1, \
            f"只该多一条，实际多了 {len(app.main_window.items) - before_count} 条"
        entry = logs[0]
        assert entry.text == live.text, entry.text
        assert entry.kind == "once" and entry.done is True, (entry.kind, entry.done)
        assert entry.next_fire_at > datetime.now() - timedelta(minutes=1), \
            "记录条目的时刻该是刚才那次处理"

        # 反向：没勾「留记录」就一条都不补（只有排期和弹窗动）
        quiet = make_interval("端到端-留记录关", list(range(7)), LO, HI, 60, True,
                              datetime.now(), interval_mode="rolling",
                              log_to_list=False)
        quiet.next_fire_at = datetime.now() + timedelta(minutes=17)
        app.main_window.items.append(quiet)
        app.main_window.refresh()
        kept_quiet = quiet.next_fire_at

        assert open_editor_with(prep_noop, title="编辑提醒", reminder=quiet,
                                button="已处理") is quiet
        app.root.update()

        assert [i for i in app.main_window.items if i.parent_id == quiet.id] == [], \
            "没勾「留记录」不该补记录条目"
        assert quiet.next_fire_at > kept_quiet, \
            "没勾「留记录」也照样要从此刻重新起算"
        results.append("点「已处理」端到端：关弹窗 + 勾了「留记录」才补一条同形记录")


        # 反向：可纠正的格式问题仍应静默处理，不能一起被拦下
        warnings.clear()

        def prep_slash(dlg, walk):
            pick(dlg, walk, "单次")
            set_entry(entries_of(dlg, walk)[0], "2026/9/5")

        r = open_editor_with(prep_slash)
        assert r is not None, "「2026/9/5」是可纠正的格式，不该被拦下"
        assert r.next_fire_at.date() == datetime(2026, 9, 5).date(), r.next_fire_at
        assert warnings == [], f"格式问题应静默纠正，不该弹提示：{warnings}"
        results.append("格式问题仍静默纠正（2026/9/5 直接存成 2026-09-05，不提示）")

        # 循环的「重复」现在是三个 radio：按星期 / 工作日 / 按日期区间
        WEEKDAY_TEXTS = tuple("一二三四五六日")

        def click_radio(dlg, walk, text):
            for c in walk(dlg):
                if isinstance(c, tk.Radiobutton) and c.cget("text") == text:
                    c.invoke()
                    return True
            raise AssertionError(f"找不到选项「{text}」")

        seen = {}

        def prep_workdays(dlg, walk):
            click_radio(dlg, walk, "循环")
            click_radio(dlg, walk, "工作日")
            dlg.update_idletasks()
            seen["radios"] = {c.cget("text") for c in walk(dlg)
                              if isinstance(c, tk.Radiobutton)}
            seen["labels"] = [c.cget("text") for c in walk(dlg)
                              if isinstance(c, tk.Label)]
            seen["day_checks"] = [w.winfo_ismapped() for w in walk(dlg)
                                  if isinstance(w, tk.Checkbutton)
                                  and w.cget("text") in WEEKDAY_TEXTS]
            # 本周七格：把每格的底色、描边宽度和描边色记下来待会儿对照
            # （对话框马上就销毁了，断言只能事后拿这份快照比）
            seen["week"] = [(str(c.cget("bg")).lower(),
                             int(c.cget("highlightthickness")),
                             str(c.cget("highlightbackground")).lower())
                            for c in walk(dlg) if isinstance(c, tk.Label)
                            and str(c.cget("text")) in WEEKDAY_TEXTS]

        saved = open_editor_with(prep_workdays)
        assert saved is not None, "工作日模式应当能保存成功"
        assert {"按星期", "工作日", "按日期区间"} <= seen["radios"], \
            f"重复的三个选项不齐，实际 {seen['radios']}"
        assert "本周" in seen["labels"], \
            f"选工作日时该显示本周排班，实际 {seen['labels']}"
        # 七格的深浅必须与法定节假日**逐日一致**。用当天现算对照，不写死哪几天 ——
        # 写死了换一周跑就挂（本周正好是中秋那周，实况跟常规周不一样）。
        _today = date.today()
        assert len(seen["week"]) == 7, f"该有七格，实际 {len(seen['week'])}"
        for (_bg, _ht, _edge), _d in zip(seen["week"], holidays.week_of(_today)):
            _on = holidays.is_workday(_d)
            assert _bg == str(theme.STICKY if _on else theme.PAPER).lower(), \
                f"{_d}（{'上班' if _on else '休息'}）那格的底色不对：{_bg}"
        _today_box = seen["week"][_today.weekday()]
        assert _today_box[1] > 0, "今天那格该套一圈框，否则看不出自己在哪一天"
        assert _today_box[2] == str(theme.EDGE).lower(), \
            f"今天那格的框该是墨线色（跟纸的描边同色），实际 {_today_box[2]}"
        assert seen["day_checks"] and not any(seen["day_checks"]), \
            "选工作日时那排星期勾选框要让位（星期勾选框定义在 days_line 里）"
        assert saved.repeat_mode == "workdays", saved.repeat_mode
        assert saved.weekdays == [0, 1, 2, 3, 4], saved.weekdays
        assert saved.display_time().startswith("工作日 "), saved.display_time()
        results.append("循环的重复：三个选项齐全；选工作日显示本周七格"
                       "（深浅与法定节假日逐日一致、今天那格带描边），保存为 workdays")

        # 「按星期」勾一~五 保存后显示成「周一至周五」，不再是「工作日」
        def prep_weekdays(dlg, walk):
            click_radio(dlg, walk, "循环")
            click_radio(dlg, walk, "按星期")
            dlg.update_idletasks()

        saved = open_editor_with(prep_weekdays)
        assert saved is not None, "按星期模式应当能保存成功"
        assert saved.repeat_mode == "weekdays", saved.repeat_mode
        assert saved.display_time().startswith("周一至周五 "), saved.display_time()
        results.append("按星期勾一~五 显示为「周一至周五」（文案不再骗人）")
    finally:
        prompt.notice = original_warn

    # 8. 多选后批量操作（标记已读 / 删除）
    mw_items = app.main_window.items
    mw_items.clear()
    missed1 = make_once("错过A", datetime.now() - timedelta(hours=2))
    missed2 = make_once("错过B", datetime.now() - timedelta(hours=1))
    pending = make_once("待提醒", datetime.now() + timedelta(hours=3))
    finished = make_once("已完成", datetime.now() - timedelta(hours=4))
    finished.acknowledge()
    daily_item = make_daily("每天", "09:00", datetime.now())
    mw_items.extend([missed1, missed2, pending, finished, daily_item])
    app.main_window.refresh()

    tree = app.main_window.tree
    assert str(tree.cget("selectmode")) == "extended", \
        f"列表应支持多选，实际 {tree.cget('selectmode')}"
    assert app.main_window._selected_items() == [], "没选中时应返回空"

    # 多选两条「已错过」-> 标记已读
    tree.selection_set([missed1.id, missed2.id])
    assert len(app.main_window._selected_items()) == 2
    app.main_window._complete()
    assert missed1.done and missed2.done, "选中的应被标为已读"
    assert not pending.done, "没选中的不该被动"
    assert daily_item.done is False, "daily 不该被标完成"
    results.append("多选后「标记已读」只作用于选中的行，不碰未选中的")

    # Ctrl+A 全选再标记，等同原来的「一键全读」
    app.main_window._select_all()
    assert len(app.main_window._selected_items()) == len(mw_items)
    app.main_window._complete()
    assert pending.done is True, "全选标记后待提醒的也应完成"
    results.append("Ctrl+A 全选后标记已读，等同原来的「一键全读」")

    # 删除：只删选中的
    d1 = make_once("删我", datetime.now() - timedelta(minutes=30))
    d2 = make_once("别删我", datetime.now() + timedelta(hours=1))
    mw_items.extend([d1, d2])
    app.main_window.refresh()
    tree.selection_set([d1.id])
    original_ask = prompt.confirm
    prompt.confirm = lambda *a, **k: True       # 自动确认，避免测试卡在自绘弹窗上
    try:
        app.main_window._delete()
    finally:
        prompt.confirm = original_ask
    assert d1 not in mw_items, "选中的应被删除"
    assert d2 in mw_items, "没选中的不能删"
    results.append("「删除」只删选中的，未选中的原样保留")

    # 「没选中就点删除」这条真实路径也得走自家的纸提示 —— 上面那条是直接调
    # prompt.notice 验它本身，这条验的是 _delete 有没有真的接上它（防哪天退回系统弹窗）
    tree.selection_remove(*tree.selection())
    seen_e2e = {}

    def check_e2e(dlg):
        seen_e2e["class"] = win32_class(dlg)
        seen_e2e["labels"] = " ".join(c.cget("text") for c in walk_widgets(dlg)
                                      if isinstance(c, tk.Label))
        find_button(dlg, "知道了").invoke()      # 点它就该关窗、_delete 该正常返回

    drive_prompt(app.main_window._delete, check_e2e)
    assert seen_e2e["class"] != "#32770", \
        f"「请先选中便签」还弹着系统弹窗（Win32 类名 {seen_e2e['class']}）"
    assert "请先选中便签" in seen_e2e["labels"], seen_e2e["labels"]
    results.append("没选中便签点「删除」→ 弹自家纸提示，点「知道了」能继续")

    # 确认框的**按钮接线**：原来只测了「自动确认 = True」那条路径，没碰过按钮本身
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
        seen_del["z"] = (z_index(dlg), z_index(app.main_window.win))
        find_button(dlg, "删除").invoke()

    drive_prompt(app.main_window._delete, check_del)
    assert seen_del["buttons"] == {"✕", "取消", "删除"}, seen_del["buttons"]
    assert seen_del["z"][0] < seen_del["z"][1], \
        f"确认框必须压在便签本上面，实际 z 序 {seen_del['z']}"
    assert doomed not in mw_items, "点「删除」就该真的删掉"
    results.append("删除确认：按钮是「取消/删除」，点「取消」不删、点「删除」真删")

    # 列表按「越需要关注越靠前」排序
    mw_items.clear()
    mw_items.extend([
        make_once("暂停的", datetime.now() + timedelta(hours=1)),
        make_once("待提醒的", datetime.now() + timedelta(hours=2)),
        make_once("已完成的", datetime.now() + timedelta(hours=3)),
        make_once("已错过的", datetime.now() - timedelta(hours=1)),
    ])
    mw_items[0].enabled = False
    mw_items[2].acknowledge()
    app.main_window.refresh()
    order = [tree.item(i, "text") for i in tree.get_children()]
    assert order == ["已错过的", "待提醒的", "已完成的", "暂停的"], \
        f"应按状态优先级排序，实际 {order}"
    assert mw_items[0].text == "暂停的", "排序只该影响显示，不该改动 items 本身的顺序"
    results.append("列表按 已错过→待提醒→已完成→已暂停 排序，且不改动存储顺序")

    # 已完成的按「计划提醒时间」倒序，不是按完成时间。
    # 故意让两条的计划时间顺序与完成时间顺序相反，这样才有鉴别力。
    mw_items.clear()
    planned_early = make_once("计划早-完成晚", datetime.now() - timedelta(hours=10))
    planned_late = make_once("计划晚-完成早", datetime.now() - timedelta(hours=1))
    planned_early.acknowledge(datetime.now())                    # 刚完成
    planned_late.acknowledge(datetime.now() - timedelta(hours=2))  # 两小时前完成
    assert planned_early.next_fire_at < planned_late.next_fire_at, \
        "构造失败：两条的计划时间应为反序，否则测不出用的是哪个字段"
    mw_items.extend([planned_early, planned_late])
    app.main_window.refresh()
    order = [tree.item(i, "text") for i in tree.get_children()]
    assert order == ["计划晚-完成早", "计划早-完成晚"], \
        f"已完成应按计划时间倒序，实际 {order}"
    results.append("已完成的按计划时间倒序（跟何时点「知道了」无关）")

    # 批量「标记已读」后顺序也不能乱 —— 各条完成时刻只差微秒、存盘更只剩秒，
    # 曾经就是这里让顺序退化成「存储顺序的逆序」，重启后还会再变一次
    mw_items.clear()
    batch = [make_once(f"批量{i}", datetime.now() - timedelta(hours=i + 1))
             for i in range(3)]
    mw_items.extend(batch)
    app.main_window.refresh()
    tree.selection_set([i.id for i in batch])
    app.main_window._complete()
    order = [tree.item(i, "text") for i in tree.get_children()]
    assert order == ["批量0", "批量1", "批量2"], \
        f"批量标记已读后仍应按计划时间倒序，实际 {order}"
    results.append("批量「标记已读」后顺序照旧按计划时间倒序，不会乱")

    # 已错过组同样倒序：9-17 的要排在 9-15 上面，最近错过的先看到
    mw_items.clear()
    mw_items.extend([
        make_once("错过在前", datetime.now() - timedelta(days=2)),
        make_once("错过最后", datetime.now() - timedelta(hours=1)),
        make_once("错过在中", datetime.now() - timedelta(days=1)),
    ])
    app.main_window.refresh()
    order = [tree.item(i, "text") for i in tree.get_children()]
    assert order == ["错过最后", "错过在中", "错过在前"], \
        f"已错过应按时间倒序（最近错过的在最上），实际 {order}"
    results.append("已错过的按时间倒序：最近错过的排最上")

    # 待提醒保持正序：马上要弹窗的排最上，别把「三天后」顶到头部
    mw_items.clear()
    mw_items.extend([
        make_once("晚点提醒", datetime.now() + timedelta(days=3)),
        make_once("马上提醒", datetime.now() + timedelta(minutes=30)),
        make_once("中间提醒", datetime.now() + timedelta(days=1)),
    ])
    app.main_window.refresh()
    order = [tree.item(i, "text") for i in tree.get_children()]
    assert order == ["马上提醒", "中间提醒", "晚点提醒"], \
        f"待提醒应保持正序（最先要弹窗的在最上），实际 {order}"
    results.append("待提醒保持正序：最先要弹窗的排最上")

    # 循环刷出来的记录按来源折叠成一条；循环便签自己照常平铺
    mw_items.clear()
    loop = make_interval("喝水提醒", [0, 1, 2, 3, 4], "08:00", "18:00",
                         60, True, datetime.now())
    mw_items.append(loop)
    recs = []
    for i in range(3):
        r = make_once("喝水提醒", datetime.now() - timedelta(hours=i + 1))
        r.parent_id = loop.id
        r.acknowledge(datetime.now())
        recs.append(r)
    plain = make_once("开会", datetime.now() - timedelta(minutes=30))
    plain.acknowledge(datetime.now())
    mw_items.extend(recs + [plain])
    app.main_window.refresh()

    def top_ids():
        return list(tree.get_children())

    gid = f"grp-{loop.id}"
    assert gid in top_ids(), f"同一来源的记录该收成一条，实际顶层 {top_ids()}"
    assert set(tree.get_children(gid)) == {r.id for r in recs}, \
        "条目里应正好是那 3 条记录"
    assert loop.id in top_ids(), \
        "源循环便签自己该平铺在顶层 —— 它是活的，不该被藏进条目里"
    assert plain.id in top_ids(), "没有来源的普通便签照常平铺"
    assert tree.item(gid, "text") == "喝水提醒", "标题该用源便签的文字"
    assert tree.item(gid, "values")[1] == "记录", \
        "类型列该标「记录」，跟那条循环便签区分开"
    assert "3 条" in tree.item(gid, "values")[2], tree.item(gid, "values")
    assert not bool(tree.item(gid, "open")), "默认应该是合上的"
    assert not tree.tag_configure("group", "font"), \
        "折叠条目的标题不该加粗 —— 小三角、类型列和缩进已经够区分了"

    # 展开状态在刷新后要留住，否则随便改条便签就又合回去了
    app.main_window._toggle_group(gid)
    assert bool(tree.item(gid, "open")), "点一下应该展开"
    app.main_window.refresh()
    assert bool(tree.item(gid, "open")), "刷新后不该把刚展开的条目合回去"

    # 双击条目标题也能展开/收起：走的是「事件坐标 → 行」那条路，不是键盘焦点。
    # 返回值必须是 "break" —— ttk 自带一个 DoubleClick class 绑定会再切一次，
    # 两下抵掉，表现就是「双击毫无反应」（用户报过这个）
    class FakeClick:
        def __init__(self, y):
            self.y = y

    ret = app.main_window._on_double_click(FakeClick(tree.bbox(gid)[1] + 5))
    app.root.update()
    assert ret == "break", \
        "双击处理器要返回 break，否则 ttk 的默认双击会再切一次，净效果=没反应"
    assert not bool(tree.item(gid, "open")), "双击条目标题该收起"
    app.main_window._on_double_click(FakeClick(tree.bbox(gid)[1] + 5))
    app.root.update()
    assert bool(tree.item(gid, "open")), "再双击一次该展开"

    # 展开/合上要「真的看得见 / 看不见」，不能只是内部状态变了 ——
    # 状态位全对、屏幕上却什么都没有，正是这次翻车的形态
    app.root.update()
    assert tree.bbox(recs[0].id), "此刻是展开的，里面的记录该看得见"
    app.main_window._toggle_group(gid)
    app.root.update()
    assert not tree.bbox(recs[0].id), "合上后里面的记录该收起来"
    app.main_window._toggle_group(gid)
    app.root.update()
    assert tree.bbox(recs[0].id), "再展开又该看得见"

    # Ctrl+A 只选真正的便签：条目标题跳过，合上的条目里面的记录也要选上
    app.main_window._select_all()
    picked = set(tree.selection())
    assert gid not in picked, "Ctrl+A 不该选中条目标题"
    assert {r.id for r in recs} <= picked, "合上的条目里面的记录也该被全选上"
    assert loop.id in picked, "源便签当然也要选上"

    # 选中条目标题点「删除」= 删掉它名下整组记录，源便签不受影响
    tree.selection_set([gid])
    assert app.main_window._selected_items() == [], "条目标题不是便签"
    assert app.main_window._has_group_selected(), "应能认出选中的是条目标题"
    ask = prompt.confirm
    prompt.confirm = lambda *a, **k: True
    try:
        app.main_window._delete()
    finally:
        prompt.confirm = ask
    assert all(r not in mw_items for r in recs), "整组记录该被删掉"
    assert loop in mw_items, "源循环便签不该被连带删掉"
    assert plain in mw_items, "没选中的不该被删"

    # 源便签被删掉后，记录仍然收着 —— 那已经是「已完成」的历史，跟它的死活无关，
    # 一删就摊开只会把列表弄乱；标题退回用记录自己的文字
    mw_items.clear()
    gone = make_interval("会消失的循环", [0, 1, 2, 3, 4], "08:00", "18:00",
                         60, True, datetime.now())
    orphan = make_once("留下的记录", datetime.now() - timedelta(hours=1))
    orphan.parent_id = gone.id
    orphan.acknowledge(datetime.now())
    mw_items.extend([gone, orphan])
    app.main_window.refresh()
    assert f"grp-{gone.id}" in top_ids(), "有源便签时该把记录收起来"
    mw_items.remove(gone)                     # 相当于那条循环被删了
    app.main_window.refresh()
    gid = f"grp-{gone.id}"
    assert gid in top_ids(), "源便签没了，记录也该继续收着，不能摊开"
    assert orphan.id not in top_ids(), "更不能散成平铺的一行"
    assert tree.item(gid, "text") == "留下的记录", \
        f"标题该退回用记录自己的文字，实际 {tree.item(gid, 'text')!r}"

    # 折叠条目得有地方显示小三角：Treeview 必须带 "tree" 这一项 ——
    # 只写 show="headings" 会把树列整个藏掉，箭头就没影了（踩过这个坑）
    show = str(tree.cget("show"))
    assert "tree" in show, \
        f"Treeview 要显示树列，否则看不见展开箭头，实际 show={show!r}"
    assert int(tree.column("#0", "width")) >= 16, \
        f"树列太窄也显示不出箭头，实际 {tree.column('#0', 'width')}"

    results.append("循环记录按来源折叠：源便签照旧平铺、默认合上、可整组删、孤儿散开")

    # 多行便签在列表里要折成一行 —— 不折的话，换行符不会换行，
    # 第二行起的内容在列表里根本看不见（行高固定，多出来的等于消失）
    mw_items.clear()
    multi = make_once("第一行\n第二行", datetime.now() - timedelta(minutes=5))
    multi.acknowledge(datetime.now())
    long_text = "特别长的一条内容" * 12
    long_one = make_once(long_text, datetime.now() - timedelta(minutes=4))
    long_one.acknowledge(datetime.now())
    mw_items.extend([multi, long_one])
    app.main_window.refresh()

    shown = tree.item(multi.id, "text")
    assert "\n" not in shown, f"列表单元格里不能留换行符，实际 {shown!r}"
    assert shown == "第一行 第二行", shown

    # 放不下的要截断并补省略号，而且省略号不能贴到列线上
    from reminders.main_window import CELL_PAD

    long_shown = tree.item(long_one.id, "text")
    assert long_shown.endswith("…"), \
        f"放不下的内容末尾该补省略号，实际 {long_shown!r}"
    assert long_shown.startswith(long_text[:8]), \
        f"开头该保留原文，实际 {long_shown!r}"
    assert len(long_shown) < len(long_text), "截断后该比原文短"
    col_w = int(tree.column("#0", "width"))
    used = app.main_window.cell_font.measure(long_shown)
    assert used <= col_w - CELL_PAD, \
        f"截断后要留出余量，别贴着列线：文本 {used}px，列宽 {col_w}px"

    # 折叠条目的标题同样要折行
    loop = make_interval("分组标题\n带换行", [0, 1, 2, 3, 4], "08:00", "18:00",
                         60, True, datetime.now())
    rec = make_once("分组标题\n带换行", datetime.now() - timedelta(hours=1))
    rec.parent_id = loop.id
    rec.acknowledge(datetime.now())
    mw_items.clear()
    mw_items.extend([loop, rec])
    app.main_window.refresh()
    gid = f"grp-{loop.id}"
    assert "\n" not in tree.item(gid, "text"), \
        f"条目标题也得折行，实际 {tree.item(gid, 'text')!r}"

    results.append("多行内容在列表里折成一行，不会因为换行而把后面的内容藏掉")

    # 刷新是整表重建，但选中不能跟着丢 —— 点完按钮往往还要接着操作同一行
    mw_items.clear()
    ka = make_once("甲", datetime.now() + timedelta(hours=1))
    kb = make_once("乙", datetime.now() + timedelta(hours=2))
    kc = make_once("丙", datetime.now() + timedelta(hours=3))
    mw_items.extend([ka, kb, kc])
    app.main_window.refresh()
    tree.selection_set([ka.id, kb.id])
    app.main_window.refresh()
    assert set(tree.selection()) == {ka.id, kb.id}, \
        f"刷新后选中的行该还在，实际 {tree.selection()}"
    # 被删掉的那些自然就不该再还原
    mw_items.remove(ka)
    app.main_window.refresh()
    assert set(tree.selection()) == {kb.id}, \
        f"已经删掉的行不该还在选中里，实际 {tree.selection()}"
    results.append("刷新列表后选中不丢（已删掉的行除外）")

    # 托盘菜单就这五项（「暂停全部提醒」「重启」都撤掉了 ——
    # 后者是实测启动不起来，索性不放了）。分隔符的 text 是 '- - - -'，
    # 得按对象身份排除，不能靠空判断。
    import pystray

    labels = [item.text for item in app.tray.icon.menu
              if item is not pystray.Menu.SEPARATOR]
    assert labels == ["打开便签本", "新建提醒", "开机自启", "护眼模式", "退出"], \
        f"托盘菜单项不对，实际 {labels}"
    results.append("托盘菜单：打开便签本 / 新建提醒 / 开机自启 / 护眼模式 / 退出")

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

    # 护眼模式。这是最容易「半边生效」的一类功能：窗口重建了但把自己藏起来了、
    # 或者某个模块在 import 期把颜色抄成了自己的常量没跟着变 —— 所以逐项验。
    # （theme 在文件顶部已经导入；这里**不能**再 import 一次 —— 函数内 import 会把
    # theme 变成局部名，前面用它的断言就 UnboundLocalError 了。）
    assert theme.current() == "day", f"默认该是近白纸，实际 {theme.current()}"
    day_paper = theme.PAPER
    app.toggle_eyecare()
    app.root.update()               # 托盘回调走 root.after(0)，得让主线程跑一趟
    assert theme.current() == "eye", f"该切到米黄稿纸，实际 {theme.current()}"
    assert theme.PAPER != day_paper, "切了配色纸色却没变"
    assert app.eyecare_on() is True, "托盘菜单的勾没跟上"
    assert store.load_prefs().get("palette") == "eye", "护眼模式的选择没落盘"
    assert app.main_window.win.winfo_exists() and app.main_window.win.winfo_viewable(), \
        "换配色后窗口应当还在、还开着（重建时先 withdraw 再 show，容易漏 show）"
    # 窗口本身现在是透明色（纸是画出来的底图），所以要验顶部条那层
    head_bg = str(app.main_window.header.cget("bg")).lower()
    assert head_bg == theme.PAPER_DEEP.lower(), \
        f"顶部条底色没跟上新配色，实际 {head_bg}"
    # 时钟那行是模块级常量抄副本的重灾区，单独盯一下
    mw_fg = str(app.main_window.clock_label.cget("fg")).lower()
    assert mw_fg == theme.INK_SOFT.lower(), \
        f"时钟那行没跟着换色（说明色值被抄成模块级常量了），实际 {mw_fg}"
    app.toggle_eyecare()
    app.root.update()
    assert theme.current() == "day", "应当能切回近白纸"
    assert store.load_prefs().get("palette") == "day", "切回来也要落盘"
    results.append("护眼模式：换纸、落盘、窗口重建后仍在且能切回，时钟跟着变色")

    # 换配色是把整个窗口重建的，上面那个 tree 已经随旧窗口一起销毁了 ——
    # 后面所有断言都得换成新的，否则会报 "invalid command name ...!treeview"。
    # （MainWindow 实例本身没换，所以 mw_items 那个列表还是同一个。）
    tree = app.main_window.tree

    # 无边框圆角窗口：系统标题栏去掉了，四角才圆得起来；
    # 纸（圆角 + 顶部色带 + 印线）是生成的一张底图，贴在 Canvas 上
    assert app.main_window.win.overrideredirect(), \
        "主窗口该是无边框的 —— 带边框时四角由系统画，只能是方的"
    assert app.main_window.canvas is not None, "要有 Canvas 承载纸底图"
    assert app.main_window._paper is not None, "圆角底图不该为空"
    results.append("主窗口无边框，圆角纸由 Canvas 底图承载")

    # 拖窗口：系统标题栏没了，只能按住顶部色带拖。真实鼠标事件在测试里拿不到，
    # 就喂合成事件验位移算式 —— 这类算术最容易悄悄写歪
    win = app.main_window.win
    win.geometry("+300+200")
    app.root.update()
    base_x, base_y = win.winfo_x(), win.winfo_y()

    class _Ev:
        def __init__(self, x, y):
            self.x_root, self.y_root = x, y

    app.main_window._drag_start(_Ev(base_x + 60, base_y + 12))
    app.main_window._drag_move(_Ev(base_x + 60 + 200, base_y + 12 + 150))
    app.root.update()
    assert (win.winfo_x(), win.winfo_y()) == (base_x + 200, base_y + 150), \
        f"拖拽位移对不上，实际 {(win.winfo_x(), win.winfo_y())}"
    results.append("按住顶部色带能拖窗口（位移跟随鼠标）")

    # 没有系统关闭按钮了，得自己补一个；语义跟以前一样：收起，不退出
    find_button(app.main_window.header, "✕").invoke()
    app.root.update()
    assert not app.main_window.win.winfo_viewable(), "点 ✕ 应把窗口收起来"
    assert app.running, "收起窗口不等于退出程序"
    app.main_window.show()
    app.root.update()
    assert app.main_window.win.winfo_viewable(), "收起来之后要还能叫回来"
    results.append("自绘关闭按钮：收起窗口但程序继续跑，能再叫回来")

    # 双击便签弹出来的编辑框，必须**压在便签本上面**。
    # 无边框窗口上再加 transient，Windows 会把这个对话框映射到 z 序最底：编辑框
    # 按主窗口居中、又比它小一圈，于是 100% 被盖住 —— 屏幕上什么都看不见，而它
    # 同时持着 grab 的模态抓取，整个页面就点不动了。用户报的「双击不能编辑 +
    # 页面无响应卡顿」就是这一件事。状态位全对、屏幕上什么都没有，这个测试就是
    # 为它立的，所以查的是 Win32 的真实 z 序，不是任何内部标志位。
    check = {}

    def dlg_fuse():
        """driver 出意外时兜底关窗 —— wait_window() 只在窗口销毁后才返回。"""
        if check.get("done"):
            return
        check.setdefault("err", RuntimeError("对话框一直没被关闭"))
        for w in app.main_window.win.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.destroy()

    def dlg_driver(retries=6):
        found = [w for w in app.main_window.win.winfo_children()
                 if isinstance(w, tk.Toplevel) and w.title() == "编辑提醒"]
        if not found:
            if retries > 0:              # 可能只是还没建出来，再等等
                app.root.after(100, lambda: dlg_driver(retries - 1))
                return
            check["err"] = RuntimeError("双击便签没能打开编辑框")
            dlg_fuse()
            return
        dlg = found[0]
        try:
            app.root.update()            # 等它真的映射到屏幕上再量
            check["z"] = (z_index(dlg), z_index(app.main_window.win))
        except Exception as e:
            check["err"] = e
        finally:
            check["done"] = True
            if dlg.winfo_exists():
                dlg.destroy()

    leaf = next((i for i in tree.get_children()
                 if app.main_window._group_key_of(i) is None), None)
    assert leaf is not None, "列表里该有普通便签供双击"
    tree.selection_set(leaf)             # 真实双击的第一次点击就会先选中它
    tree.focus(leaf)
    tree.see(leaf)
    app.root.update()
    row_bbox = tree.bbox(leaf)
    assert row_bbox, "这一行该在可视区里，否则量不到它被点到哪"

    app.root.after(200, dlg_driver)
    dlg_fuse_id = app.root.after(8000, dlg_fuse)
    app.main_window._on_double_click(FakeClick(row_bbox[1] + 5))
    app.root.after_cancel(dlg_fuse_id)
    if "err" in check:
        raise check["err"]

    z_dlg, z_main = check["z"]
    assert z_dlg is not None and z_main is not None, \
        f"量不到 z 序（编辑框 {z_dlg} / 便签本 {z_main}）"
    assert z_dlg < z_main, \
        f"编辑框必须压在便签本上面，实际 z 序 编辑框={z_dlg} 便签本={z_main}：\n" \
        f"沉到下面就是被完全盖住 —— 屏幕上什么都看不见，而它还持着 grab，" \
        f"整个页面会点不动（无边框窗口上不能再用 transient()）"
    results.append("双击便签弹出的编辑框压在便签本上面（量真实 z 序，不只看标志位）")

    # ---- 提示窗口：自家的纸窗口，不再是系统灰弹窗 ----
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

    # 欢迎页：首次运行露一次，收起后落盘，下次启动就不再露。
    # 它只是盖在列表前的一张纸 —— 列表必须照常存在（后面全靠它）。
    mw = app.main_window
    assert mw.welcome_pending, "头一次运行该安排欢迎页"
    assert mw._welcome is not None and mw._welcome.winfo_exists(), \
        "欢迎页该已经建出来"
    assert tree.winfo_exists(), "欢迎页只是盖上去，列表本身不能没有"
    find_button(mw._welcome, "新建第一条")
    find_button(mw._welcome, "开始使用").invoke()
    app.root.update()
    assert not mw.welcome_pending, "点了「开始使用」该把欢迎页收起"
    assert mw._welcome is None, "收起后该把引用清掉"
    assert store.load_prefs().get("welcomed") is True, \
        "该记住「看过了」，否则每次启动都会再露一遍"
    results.append("首次运行的欢迎页：露一次、可收起、落盘，且不影响列表")

    # 到点弹窗：同样是无边框圆角，只不过整张是黄便签；高度得跟着内容长短走
    short_note = make_once("交电费", datetime.now() - timedelta(seconds=1))
    app.popups.show(short_note)
    app.root.update()
    pop = app.popups.open_popups[-1]
    assert pop.overrideredirect(), "弹窗也该是无边框的"
    assert pop.title() == "提醒", pop.title()
    assert pop.winfo_viewable(), "弹窗应当可见"
    h_short = pop.winfo_height()

    long_note = make_once("给客户回电话确认上门时间，顺便问一下上次那个配件的型号对不对",
                          datetime.now() - timedelta(seconds=1))
    app.popups.show(long_note)
    app.root.update()
    h_long = app.popups.open_popups[-1].winfo_height()
    assert h_long > h_short, \
        f"长内容该把便签撑高，短 {h_short} 长 {h_long}（高度写死就会出现这种事）"
    app.popups.close_all()
    app.root.update()
    results.append("到点弹窗是无边框圆角黄便签，高度随内容长短自适应")

    # 弹窗得能拖着挪开 —— 而正文全是 Label，**Tk 的事件不冒泡给父控件**，
    # 只绑 note 那个 Frame 的话鼠标落在字上就拖不动（2026-09-24 用户报"不能移动位置"）
    drag_note = make_once("拖一下试试", datetime.now() - timedelta(seconds=1))
    app.popups.show(drag_note)
    app.root.update()
    pop = app.popups.open_popups[-1]
    labels = [w for w in walk_widgets(pop) if isinstance(w, tk.Label)]
    assert labels, "弹窗正文该有 Label"
    draggable = [w for w in labels
                 if w.bind("<Button-1>") and w.bind("<B1-Motion>")]
    assert len(draggable) == len(labels), \
        f"{len(labels) - len(draggable)} 个 Label 拖不动（事件不冒泡，得逐个绑）"
    # 按钮绝不能被当成把手：从它身上按下就会开始拖窗口，松手还会顺手点一下
    for btn in [w for w in walk_widgets(pop) if isinstance(w, tk.Button)]:
        assert not btn.bind("<Button-1>"), \
            f"按钮 {btn.cget('text')} 不该绑拖拽"
    app.popups.close_all()
    app.root.update()
    results.append("弹窗正文（Label）也能拖：拖拽把手是递归绑的，按钮除外")

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

    # 配方不能把窗口挪走。它内部要 hide/show，而 hide/show 会让 Tk 把窗口当前
    # 那个矩形当成它的 geometry —— 若那一刻挂起的 geometry 请求还没应用下去，
    # 记下来的就是"还没摆好的 (0,0)"，居中等请求永久丢失。所以这里**故意不 flush**
    # （这正是 popup.show() 的真实时序）：配方得自己先落实，位置才留得住。
    tb_win.geometry("300x150+700+400")
    frameless.taskbar_button(tb_win)
    app.root.update()
    assert (tb_win.winfo_x(), tb_win.winfo_y()) == (700, 400), \
        f"配方把挂起的位置请求弄丢了：该在 (700,400)，实际 " \
        f"{(tb_win.winfo_x(), tb_win.winfo_y())}"
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
    assert class_icon_size(pop) == (frameless.WINDOW_ICON_PX,) * 2, \
        f"弹窗喂给任务栏的图标是 {class_icon_size(pop)}，不是原生 " \
        f"{frameless.WINDOW_ICON_PX}px —— 尺寸不对就会被 Explorer 缩糊。这条" \
        f"同时也钉住了两件事：set_window_icon 在 taskbar_button **之前**跑" \
        f"（那套 hide/show 会重建按钮，图标得先就位），且走的是 iconphoto 而不是" \
        f"iconbitmap（后者永远给 32px）"
    app.popups.close_all()
    app.root.update()
    results.append("到点弹窗带任务栏按钮，且圆角/透明/置顶/无边框都没被配方破坏")

    # 任务栏图标。**两个根因**（2026-09-29 对照实测，缺一条就退回默认图标/糊图标）：
    #   ① 进程没声明 AppUserModelID → 被归到 pythonw.exe 名下，按钮画它的图标；
    #      光调 iconbitmap 没用（对照：普通 Tk 窗口调了照样画 Python 图标）
    #   ② 用 wm_iconbitmap 时 Explorer 永远只拿到 32px，而任务栏只画 18px，
    #      多一刀缩放就把三道细线糊成一块；wm_iconphoto 保留原生尺寸
    assert explicit_app_id() == APP_ID, \
        f"进程没声明自己的 app 身份（拿到 {explicit_app_id()!r}）—— 任务栏会退回 " \
        f"exe 的图标（源码版就是 Python 图标）。必须在建第一个窗口之前声明，" \
        f"见 app.declare_app_id"
    ic_win = tk.Toplevel(app.root)
    frameless.frameless_canvas(ic_win)
    app.root.update()
    frameless.set_window_icon(ic_win, make_icon_image(frameless.WINDOW_ICON_PX))
    app.root.update()
    assert class_icon_size(ic_win) == (frameless.WINDOW_ICON_PX,) * 2, \
        f"挂在窗口上的图标是 {class_icon_size(ic_win)}，应为原生 " \
        f"{frameless.WINDOW_ICON_PX}px（iconphoto 保留原生尺寸；iconbitmap 是 32px）"
    assert getattr(ic_win, "_window_icon", None) is not None, \
        "窗口没持住 PhotoImage 引用：它被回收之后图标就消失了"
    ic_win.destroy()
    app.root.update()
    results.append("任务栏图标：进程声明了 AppUserModelID（根因①）"
                   "+ 喂给 shell 的是原生 24px 而不是被缩过的 32px（根因②）")

    # 挂图标失败时必须静默降级 —— 图标只是门面，绝不能反过来挡住提醒
    def boom_icon(win, image):
        raise tk.TclError("模拟：图标挂不上")

    bad_pop = make_once("图标挂不上也要能弹", datetime.now() - timedelta(seconds=1))
    with mock.patch.object(frameless, "set_window_icon", boom_icon):
        app.popups.show(bad_pop)
    app.root.update()
    assert app.popups.open_popups and app.popups.open_popups[-1].winfo_viewable(), \
        "挂图标一失败就把弹窗搞崩了：图标缺失必须静默降级"
    app.popups.close_all()
    app.root.update()
    results.append("图标挂不上时弹窗照常弹出（静默降级，不挡提醒）")


    # 老数据没有 done_at 也不能乱
    legacy = make_once("老数据无完成时间", datetime.now() - timedelta(hours=1))
    legacy.done = True                  # 模拟旧版本写下的数据：只有 done
    assert legacy.done_at is None
    mw_items.append(legacy)
    app.main_window.refresh()
    order = [tree.item(i, "text") for i in tree.get_children()]
    assert "老数据无完成时间" in order, order
    results.append("没有 done_at 的老数据也能正常显示（退回按计划时间）")

    # 列表要有滚动条，否则便签一多就没法看全
    from tkinter import ttk

    def find_scrollbar(w):
        for c in w.winfo_children():
            if isinstance(c, ttk.Scrollbar):
                return c
            found = find_scrollbar(c)
            if found is not None:
                return found
        return None

    sb = find_scrollbar(app.main_window.win)
    assert sb is not None, "列表应有垂直滚动条"
    assert str(sb.cget("orient")) == "vertical", sb.cget("orient")
    assert app.main_window.tree.cget("yscrollcommand"), \
        "滚动条必须真的绑到列表上，光有个控件没用"
    results.append("列表带垂直滚动条且已绑定")

    # 类型列必须都有中文标签，别把内部 kind 字面量漏到界面上
    from reminders.main_window import KIND_LABEL
    for k in ("once", "daily", "interval"):
        assert k in KIND_LABEL, f"类型 {k} 没有中文标签，会直接显示英文"
        assert KIND_LABEL[k] != k, f"类型 {k} 的标签还是英文"
    results.append("类型列全部有中文标签（单次/每天/循环）")

    # 底部：时间靠左（单独一行），快捷键靠右（两行）
    text = app.main_window.clock_text()
    assert "本地时间" in text, f"没校准上应标「本地时间」，实际 {text}"
    assert "北京时间" not in text, f"没校准上不能自称北京时间，实际 {text}"
    assert "\n" not in text, f"时间应是单独一行，实际 {text!r}"

    hint = app.main_window.hint.cget("text")
    assert "多选" in hint and "全选" in hint, \
        f"快捷键提示要说清两种选择方式，实际 {hint!r}"
    assert hint.count("\n") == 1, f"快捷键应是上下两行，实际 {hint!r}"

    # 「北京时间」那一栏必须走 clock.now()（校准后的钟），不是本机读数。
    # 临时把偏移拨到 +1 小时，两者就差 3600 秒，用错了一测便知。
    import re
    from unittest import mock

    def hms(text):
        m = re.search(r"(\d{2}):(\d{2}):(\d{2})", text)
        assert m, f"应显示时分秒，实际 {text!r}"
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

    mw = app.main_window
    original_offset = clock._offset
    original_display = mw.time_display
    try:
        mw.time_display = "beijing"        # 明确指定，别让 auto 按校准状态挡回去
        clock._offset = timedelta(seconds=3600)
        mw._tick_clock()
        shown = mw.clock_label.cget("text")
        expected = clock.now()             # 必须在偏移还在时取值
    finally:
        clock._offset = original_offset
        mw.time_display = original_display
    assert abs(hms(shown) - hms(expected.strftime("%H:%M:%S"))) <= 1, \
        f"「北京时间」应走 clock.now()，显示 {shown}，应为 {expected:%H:%M:%S}"

    with mock.patch.object(clock, "is_synced", return_value=True):
        synced_text = mw.clock_text()
    assert "北京时间" in synced_text and "网络校准" in synced_text, synced_text

    # 点一下就在两栏之间来回切，并且记住选择
    mw.time_display = "auto"
    with mock.patch.object(clock, "is_synced", return_value=False):
        assert "本地时间" in mw.clock_text(), \
            f"没校准上时 auto 应显示本地时间，实际 {mw.clock_text()}"
        mw._toggle_clock()
        assert mw.time_display == "beijing", mw.time_display
        assert "北京时间" in mw.clock_text(), mw.clock_text()
        assert "网络校准" not in mw.clock_text(), \
            f"没校准上就不能自称网络校准，实际 {mw.clock_text()}"
    mw._toggle_clock()
    assert mw.time_display == "local", mw.time_display
    assert "本地时间" in mw.clock_text(), mw.clock_text()
    assert store.load_prefs().get("time_display") == "local", store.load_prefs()

    # 两栏取数来源不同：把偏移拨 +1 小时，北京时间那栏就该比本地那栏快 1 小时
    original_offset = clock._offset
    try:
        clock._offset = timedelta(seconds=3600)
        mw.time_display = "local"
        local_secs = hms(mw.clock_text())
        mw.time_display = "beijing"
        beijing_secs = hms(mw.clock_text())
    finally:
        clock._offset = original_offset
        mw.time_display = "local"
    gap = (beijing_secs - local_secs) % 86400
    assert abs(gap - 3600) <= 2, \
        f"两栏应差 1 小时（北京走 clock.now()、本地走本机读数），实际差 {gap} 秒"

    results.append("底部：时间靠左单独一行；点击在北京/本地之间切换并记住选择")

    # 9. 循环的「每次触发在便签本留一条记录」开关
    mw_items.clear()
    loud = make_interval("走动", [0, 1, 2, 3, 4], "08:00", "18:00", 60, True,
                         datetime.now(), log_to_list=True)
    quiet = make_interval("安静循环", [0, 1, 2, 3, 4], "08:00", "18:00", 60, True,
                          datetime.now(), log_to_list=False)
    mw_items.extend([loud, quiet])
    before = len(mw_items)

    silent_show = app.popups.show
    app.popups.show = lambda r: None          # 只测写入行为，不真弹窗
    try:
        app._fire_popup(loud)
        assert len(mw_items) == before + 1, "开了开关的循环应在列表里留一条记录"
        logged = mw_items[-1]
        assert logged.text == "走动"
        assert logged.done is True, \
            "记录必须直接是已完成，否则时间点已过会立刻被标红成「已错过」"
        assert logged.is_missed(datetime.now()) is False, "记录不该标红"
        assert logged.last_fired_at is not None

        app._fire_popup(quiet)
        assert len(mw_items) == before + 1, "没开开关的循环不该写入列表"
    finally:
        app.popups.show = silent_show
    results.append("循环「留记录」开关：开了才写入，且记录直接是已完成不标红")

    # 10. 真实 after 定时器循环：不手动 tick，让它自己到点
    app.scheduler.paused = False
    # 只验证「定时器确实触发了弹窗」，不验证「弹窗还开着」——
    # tkinter 按钮拿到焦点时会响应空格/回车，弹窗可能被真实按键关闭，
    # 那是正常的 UI 行为，不该让测试变红。
    shown = []
    original_show = app.popups.show

    def recording_show(reminder):
        shown.append(reminder)
        return original_show(reminder)

    app.popups.show = recording_show
    timer_item = make_once("定时器测试", datetime.now() + timedelta(seconds=2))
    app.scheduler.items.append(timer_item)
    state = {"ok": False}

    def finish():
        state["ok"] = timer_item in shown
        if not state["ok"]:
            print(f"  [调试] shown={[r.text for r in shown]} "
                  f"timer: last={timer_item.last_fired_at} "
                  f"paused={app.scheduler.paused}")
        app.root.destroy()

    try:
        app.root.after(7000, finish)
        app.root.mainloop()
    finally:
        app.popups.show = original_show
    assert state["ok"], "真实 after 定时器循环未触发弹窗"
    app.root.mainloop()
    assert state["ok"], "真实 after 定时器循环未触发弹窗"
    results.append("真实 after 定时器循环 2 秒后自动弹窗（无需手动 tick）")

    # 11. 落盘的是隔离目录，不是真实数据目录
    assert os.path.exists(store.DATA_PATH), store.DATA_PATH
    assert "AppData" not in store.DATA_PATH or "Temp" in store.DATA_PATH, \
        store.DATA_PATH
    results.append(f"数据写入隔离目录 {store.DATA_DIR}")

    print("全部通过：")
    for line in results:
        print("  -", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
