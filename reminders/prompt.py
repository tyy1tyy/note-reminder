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


def confirm(parent, message: str, action: str = "删除",
            title: str = "确认") -> bool:
    """要用户做个决定。点主按钮（`action` 那个词）返回 True，取消 / ✕ / Esc 返回 False。

    **`✕` 和 Esc 一律当「否」** —— 不能把"关掉窗口"读成"同意"（原生 askyesno
    就是这个语义，换皮不能顺手把语义也换了）。
    主按钮上写什么字由调用方给（"删除" / "清空"…），不写死；按钮否在左、是在右。
    """
    return _show(parent, message, title,
                 [("取消", False, lambda: False),
                  (action, True, lambda: True)]) is True


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

    # 顶部 = 自制标题栏（素纸，跟编辑框同一套）
    # 和编辑框一样的道理：只有便签本顶着满色带（它是"一本便签"的胶口），
    # 浮在它上面的纸片都是素的，这样叠起来才分得清是几张纸。
    band = tk.Frame(canvas, bg=theme.PAPER)
    # y 从 EDGE_W 起、高度也减 EDGE_W：**别把顶上那条描边盖掉**（纸在 canvas 最底层）
    canvas.create_window(theme.CORNER_R, theme.EDGE_W, window=band, anchor="nw",
                         width=W - 2 * theme.CORNER_R,
                         height=BAND_H - theme.EDGE_W)
    tk.Label(band, text=title, bg=theme.PAPER, fg=theme.INK_SOFT,
             font=theme.ui(10)).pack(side="left", padx=(16, 0))
    frameless.close_button(band, win.destroy, bg=theme.PAPER).pack(
        side="right", padx=(0, 12), pady=8)
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
                                      band_h=BAND_H, band=theme.PAPER,
                                      rule_y=BAND_H)

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
