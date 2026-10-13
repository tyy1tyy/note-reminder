"""窗口位置计算。三个界面（便签本、编辑对话框、到点弹窗）统一居中于屏幕。

不 import tkinter —— 只接收窗口对象并调用其方法，因此可脱离 GUI 使用。
"""
from __future__ import annotations


def center_geometry(win, w: int, h: int, dx: int = 0, dy: int = 0) -> str:
    """返回居中于屏幕的 geometry 字符串，如 '620x420+650+330'。

    dx/dy 用于额外偏移（到点弹窗同时出现多个时靠它层叠错开）。
    """
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    return f"{w}x{h}+{(sw - w) // 2 + dx}+{(sh - h) // 2 + dy}"


def center_on_parent(win, parent, w: int, h: int) -> str:
    """相对父窗口居中。

    主窗口若本身居中于屏幕，结果与 center_geometry 相同；差别在于用户把主窗口
    拖到别处（或拖到另一块屏幕）时，对话框会跟着父窗口走，而不是留在屏幕中央。
    父窗口尚未映射（尺寸不可信）时退回屏幕居中。
    """
    parent.update_idletasks()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    if pw <= 1 or ph <= 1:
        return center_geometry(win, w, h)
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    return f"{w}x{h}+{px + (pw - w) // 2}+{py + (ph - h) // 2}"
