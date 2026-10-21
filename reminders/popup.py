"""到点提醒弹窗。

同一时刻只保留一个：新的提醒直接覆盖旧的，不叠加多个窗口。
弹出瞬间置顶一次（确保压在其他程序上面能被看到），随后立刻释放置顶——
**不恒置顶**：用户切到别的窗口时，系统会把它按正常层级压下去。释放之后我们自己
**不挪它、也不抢焦点**（点"正在用的那个程序"系统不会有动作，它那时会留在最上层）
—— 这是 2026-09-24 用户明确选的"什么都不做"，别再顺手加让位逻辑。

外观上它是**从便签本上撕下来的一张纸**：跟主窗口同一套纸色，顶上留着一条
黄色的粘胶边（就是从便签本上撕下来的那个痕迹），右上角翻着折角。

一开始做成了整张铺满便签黄，太吵 —— 黄在这套设计里是「唯一那块要动的东西」
（列表选中行、新建按钮），铺满一整张就把强调用滥了，而且小字压在饱和黄上
也不好读。改成「纸 + 一条黄边」之后两头都保住了：纸是可读的，黄还在，
但只占一条边。

它在**任务栏里有自己的一格**（见 ``frameless.taskbar_button``）：被别的窗口盖住时
点一下就能叫回来，用户也可以主动把它最小化。**那一格画的是 RemindNotes 自己的
图标**（``frameless.set_window_icon``）—— 不设的话是进程 exe 的图标（开发态就是
Python 图标），Tk 的窗口类图标那一级 shell 并不用。**最小化和还原全程由系统做，这里一行
窗口状态操作都不写** —— 光标停在弹窗上时 ``iconify()`` 会被 Tk 拒（override-redirect
标记），而我们自己同步调 ``ShowWindow(SW_MINIMIZE)`` 会直接把进程搞崩（2026-09-28
实测：``Fatal Python error: PyEval_RestoreThread ... the GIL is released``）。真需要
动窗口状态时走 ``PostMessage(WM_SYSCOMMAND, SC_MINIMIZE / SC_RESTORE)``，别用
ShowWindow。
"""
from __future__ import annotations

import tkinter as tk

from . import clock, frameless, theme
from .geometry import center_geometry
from .tray import make_icon_image

POPUP_W = 380
PAD = 18            # 纸左右和底部的留白，同时也是内容避开圆角的余量
STRIP_H = 13        # 顶上那条黄色粘胶边
TOP_GAP = 14        # 粘胶边和正文之间再空一点
INNER = 8           # 纸内部再留一点，免得字贴着边
FOLD = 26           # 右上角折角（跟托盘图标同一个意思）
POPUP_R = 10        # 比窗口那张纸略大 —— 这张是撕下来的，边角随意些
CONTENT_W = POPUP_W - 2 * PAD

# 弹出瞬间保持置顶的时长：够窗口管理器把它抬到最前，之后交还给正常层级。
# 不能用 0——那样窗口可能还没被抬起来就已经释放了。
TOPMOST_HOLD_MS = 200


class PopupManager:
    def __init__(self, root: tk.Tk, on_changed):
        self.root = root
        self.on_changed = on_changed
        self.open_popups: list[tk.Toplevel] = []
        # reminder.id -> 那张弹窗。open_popups 只有窗口、认不出是哪条便签，
        # 编辑框的「已处理」要按便签关单张，所以另挂一张表。
        self._windows: dict[str, tk.Toplevel] = {}

    def close_all(self) -> None:
        """关掉当前所有弹窗。

        同时到点时如果叠加好几个窗口，屏幕会被糊满反而看不清是哪个提醒，
        所以只留最新那个。
        """
        for w in list(self.open_popups):
            if w.winfo_exists():
                w.destroy()
        self.open_popups.clear()
        self._windows.clear()

    def close_for(self, reminder) -> None:
        """关掉某条便签当前开着的那张弹窗（编辑框「已处理」用）。

        直接 destroy，**不走 dismiss()** —— 会触发排期副作用的只有弹窗上那三个
        按钮，这里跟"被新弹窗顶掉"（close_all 的 destroy）同性质，不该替用户
        留下任何"已处理"。
        """
        win = self._windows.pop(reminder.id, None)
        if win is None:
            return
        if win in self.open_popups:
            self.open_popups.remove(win)
        if win.winfo_exists():
            win.destroy()

    @staticmethod
    def _release_topmost_later(win: tk.Toplevel) -> None:
        """弹出时的置顶只保留一瞬，之后不再恒置顶。

        释放置顶**不会**改变窗口当前的 Z 序 —— 窗口仍留在最前，直到用户切到
        别的窗口（激活别的窗口）时，系统才把它按正常层级压下去。

        **已知且被接受的两个边界**（2026-09-24 用户裁决：什么都不做）：
        ① 点"正在用的那个程序"不产生激活事件，所以那时没有任何东西把它压下去，
          它会一直压在人家窗口上面 —— 除非用户先点一下别的窗口（或 alt-tab）。
        ② 因此这里**不**自己挪窗口，也**不**抢焦点：后台进程抢焦点通常会被系统
          拒掉，而"主动让位"是另一个取舍，用户明确否了。别再"顺手优化"回来。
        """
        def release() -> None:
            try:
                if win.winfo_exists():
                    win.attributes("-topmost", False)
            except tk.TclError:
                pass                        # 窗口已被关掉

        win.after(TOPMOST_HOLD_MS, release)

    @staticmethod
    def _fill_note(note: tk.Widget, reminder, actions: dict) -> None:
        """把这张便签的内容填进 note。

        内容顺序就是读的顺序：**为什么现在弹窗**（时间/周期，小字在最上）→
        **要做什么**（正文，最大的那行，楷体）→ **怎么处理**（三个按钮，
        由重到轻）。

        正文用楷体、而且明显大于其它字：这是「人写的那句话」，其余都是机器的
        标注。便签本窗口里也是这个分法。
        """
        tk.Label(note, text=reminder.display_time(), bg=theme.PAPER,
                 fg=theme.INK_SOFT, font=theme.ui(9),
                 anchor="w").pack(fill="x", padx=INNER)
        tk.Label(note, text=reminder.text, bg=theme.PAPER, fg=theme.INK,
                 font=theme.pen(14), justify="left", anchor="w",
                 wraplength=CONTENT_W - 2 * INNER).pack(
                     fill="x", padx=INNER, pady=(8, 0))

        bar = tk.Frame(note, bg=theme.PAPER)
        bar.pack(fill="x", padx=INNER, pady=(20, 0))
        frameless.ink_button(bar, "知道了", actions["ack"]).pack(side="left")
        frameless.outline_button(bar, "稍后 10 分钟",
                                 actions["snooze"]).pack(side="left", padx=(8, 0))
        frameless.quiet_button(bar, "关闭",
                               actions["close"]).pack(side="left", padx=(6, 0))

    def show(self, reminder) -> None:
        self.close_all()                    # 覆盖：旧弹窗给新提醒让位
        win = tk.Toplevel(self.root)
        win.title("提醒")                   # 无边框后系统不画它了，留着只为心里有数
        win.attributes("-topmost", True)    # 弹出瞬间抬到最前，保证不会被漏看
        self._release_topmost_later(win)    # 只是这一瞬置顶，不恒置顶
        self.open_popups.append(win)
        self._windows[reminder.id] = win

        def dismiss() -> None:
            """只把这张纸收掉 —— 不带任何排期副作用。

            拆出来是因为"处理"和"收窗口"现在是两件事：`on_ack` 已经自己做过一遍
            handled()，若再走一遍带副作用的关闭逻辑，同一个时刻会被重排两次
            （第二次的 clock.now() 晚一两秒，白白把下一次推后）。
            """
            if win in self.open_popups:
                self.open_popups.remove(win)
            self._windows.pop(reminder.id, None)   # 跟 open_popups 同增同减
            win.destroy()

        def on_close() -> None:
            # 「关闭」= 处理了这一格（2026-09-29 裁决）：循环便签从这一刻重新起算，
            # 见 handled()。单次便签上它**仍然 ≠ 已处理** —— 不置 done、列表里照旧
            # 标红，等着被真正处理。
            # 被新弹窗顶掉的那张不走这里（close_all() 直接 destroy），所以"顶掉"
            # 不会替用户留下一个"已处理"，循环照原格子继续往前推。
            reminder.handled(clock.now())
            self.on_changed()
            dismiss()

        def on_ack() -> None:
            now = clock.now()
            reminder.acknowledge(now)      # 单次便签：标完成
            reminder.handled(now)          # 循环便签：从这一刻重新起算
            self.on_changed()
            dismiss()

        def on_snooze() -> None:
            reminder.snooze(clock.now())
            self.on_changed()
            dismiss()

        canvas = frameless.frameless_canvas(win)
        note = tk.Frame(canvas, bg=theme.PAPER)
        canvas.create_window(PAD, STRIP_H + TOP_GAP, window=note, anchor="nw",
                             width=CONTENT_W)
        self._fill_note(note, reminder,
                        {"ack": on_ack, "snooze": on_snooze, "close": on_close})

        # 量完内容再定窗口大小。正文长短差得远（「交电费」到一整句话），高度
        # 写死了不是留一大块空白、就是把字挤出纸外面。
        note.update_idletasks()
        height = STRIP_H + TOP_GAP + note.winfo_reqheight() + PAD
        win.geometry(center_geometry(win, *frameless.outer(POPUP_W, height)))
        # 纸最后画（要等高度定下来），它会自己压到内容底下。
        # 挂在窗口对象上是为了持住引用 —— PhotoImage 被回收图就没了
        win._paper = frameless.paper_onto(canvas, POPUP_W, height,
                                          paper=theme.PAPER,
                                          band_h=STRIP_H, band=theme.STICKY,
                                          corner=POPUP_R, fold=FOLD)

        # 无边框之后也能拖着挪开 —— 挡着东西时用户总得能把它推开
        frameless.Dragger(win).attach(note)
        win.protocol("WM_DELETE_WINDOW", on_close)

        # 窗口图标：不设的话任务栏那一格画的是别的图标（源码版是进程 exe 的
        # Python 图标）。**必须走 iconphoto + 原生尺寸**，理由与实测见
        # frameless.set_window_icon。放在 taskbar_button 之前 —— 那套 hide/show
        # 会重建任务栏按钮，图标得在转换之前就位。
        try:
            frameless.set_window_icon(win,
                                      make_icon_image(frameless.WINDOW_ICON_PX))
        except Exception:
            pass        # 少个图标而已，绝不能反过来让提醒弹不出来

        # 任务栏按钮：这张纸在任务栏里有自己的一格，被别的窗口盖住时点一下就能
        # 叫回来。**必须放在窗口已经 map 之后** —— 配方要求「先真隐藏再显示」，
        # 理由见 frameless.taskbar_button。放最后还有个好处：200ms 的置顶窗口
        # 还没到期，这次 hide/show 落在里面，「弹出必被看见」不受影响。
        try:
            frameless.taskbar_button(win)
        except Exception:
            pass        # 少一个便利入口而已，绝不能反过来让提醒弹不出来
