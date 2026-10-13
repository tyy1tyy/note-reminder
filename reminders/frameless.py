"""无边框圆角窗口的公共装配。

三个窗口（便签本、编辑框、到点弹窗）现在都是「一张圆角纸」，共用的那部分
收在这儿：去系统边框、透明角、贴底图、拖动、右上角那个 ✕。

不抽出来的话，``overrideredirect`` / ``-transparentcolor`` / ``PhotoImage``
引用这几个坑要在三个文件里各踩一遍，而且很容易只改其中一处、另外两处慢慢
漂开 —— 那就不是「统一」了。
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes

from PIL import ImageTk

from . import theme

CORNER = theme.CORNER_R

# ---- 任务栏按钮要用的窗口样式位 ----
# Tk 给 overrideredirect 窗口打了 WS_EX_TOOLWINDOW —— 那个标记的语义就是
# 「别在任务栏和 Alt-Tab 里出现」。想让它有任务栏按钮，就得把这位清掉、
# 再补上 WS_EX_APPWINDOW。用到的常量都列在这儿，免得散在函数体里
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


def frameless_canvas(win: tk.Toplevel) -> tk.Canvas:
    """把 win 变成无边框透明窗，并给它一个空 canvas（纸还没画）。

    单拎出来是给「得先量内容才知道窗口多大」的窗口用的（到点弹窗：便签内容
    长短差得远）。量完再调 ``paper_onto`` 把纸补上。
    """
    win.overrideredirect(True)          # 去系统边框 —— 圆角的前提
    win.configure(bg=theme.MAGIC)
    win.attributes("-transparentcolor", theme.MAGIC)
    canvas = tk.Canvas(win, bg=theme.MAGIC, highlightthickness=0, bd=0)
    canvas.pack()
    return canvas


def outer(w: int, h: int) -> tuple:
    """纸是 w×h，但**窗口**要比它大一圈 —— 右下那条影子得占地方。

    所有 ``win.geometry(...)`` 都要用这个尺寸；内容坐标仍按纸的 w×h 算。
    """
    return w + theme.SHADOW_DX, h + theme.SHADOW_DY


def paper_onto(canvas: tk.Canvas, w: int, h: int, **paper):
    """把纸画进已有的 canvas，返回 photo。顺便把 canvas 调成该有的尺寸。

    画完立刻压到最底层：canvas 上后建的项盖在先建的上面，而内容往往先于纸
    建好（因为要先量高度），不压下去就会被纸糊住。

    按 tag 先删掉上一张：编辑框切类型时要重画好几次，不删就会越叠越多。

    **返回值必须由调用方持有**：``PhotoImage`` 被 Python 回收后图上内容就没了，
    而且不报错，只是白板一块。
    """
    canvas.delete("paper")
    photo = theme.rounded_paper(w, h, **paper)
    ow, oh = outer(w, h)
    canvas.configure(width=ow, height=oh)
    item = canvas.create_image(0, 0, image=photo, anchor="nw", tags=("paper",))
    canvas.tag_lower(item)
    return photo


def as_paper(win: tk.Toplevel, w: int, h: int, **paper) -> tuple:
    """把 win 变成一张圆角纸，返回 ``(canvas, photo)``。

    ``paper`` 原样透传给 ``theme.rounded_paper``（色带高度、印线、折角、
    换底色），所以「纸」和「弹窗那张撕下来的纸」是同一个函数出来的。
    """
    canvas = frameless_canvas(win)
    return canvas, paper_onto(canvas, w, h, **paper)


def _user32():
    """配好签名的 user32。

    **不能配漏 restype**：``GetAncestor`` 默认按 ``c_int`` 收，64 位下会把窗口
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

    三条都是 2026-09-28 实测出来的（探针脚本与结论见
    ``docs/superpowers/specs/2026-09-28-popup-taskbar-button-design.md`` §2），
    少一条就会被"顺手优化"回去：

    ① **必须真隐藏再显示**，样式改动才生效。shell 只在「隐藏 → 显示」这个转换上
       重算任务栏归属：窗口还在显示时改样式、首次显示之前就改样式，都不出按钮
       （三种时序各测过一遍，全无）。所以顺序是 hide → 改 → show，hide 不能省。
    ② **不能用 Tk 的 withdraw()/deiconify() 代替**：``deiconify()`` 对
       overrideredirect 窗口不会真的把窗口重新显示出来（``iconify()`` 更直接，
       Tk 会报 ``can't iconify ...: override-redirect flag is set``）。只有 Win32 的
       SW_HIDE / SW_SHOW 这一对能完成这个转换 —— 这正是第一次探针没测出按钮的
       原因（它用了 deiconify，窗口其实一直藏在后台）。
    ③ **只动这两个样式位**：清 TOOLWINDOW、加 APPWINDOW。不碰 WS_POPUP 和分层
       透明，所以圆角、透明、置顶都不受影响（实测 LAYERED / topmost /
       transparentcolor / 角落像素全都没变）。
    ④ **必须先 flush 掉 Tk 挂起的 geometry**（下面那行 ``update_idletasks()``，
       不能删）。hide/show 会让 Tk 把窗口**当前**那个矩形当成它的 geometry 记下来；
       而调用方常常是刚 ``geometry()`` 完就调这里 —— 那一刻 Tk 只是*记下*了请求、
       还没应用到窗口上（没转过事件循环），于是被记下来的是"还没摆好的 (0,0)"，
       居中请求就此永久丢失。2026-09-28 被 ``test_app.py`` 那条「弹窗应居中于屏幕」
       抓到：弹窗全跑到屏幕左上角。先 flush 一次，窗口已经在正确位置上，就只是
       藏一下再拿出来，什么都不丢。

    **这里不吞异常**：拿不到任务栏按钮只是少了个便利入口，但函数内部一旦把异常
    咽掉，"为什么这台机器没有按钮"就再也查不出来了。由调用方决定怎么兜。

    **绝不在这个模块里（或任何地方）同步调 ShowWindow(SW_MINIMIZE/SW_RESTORE)**：
    那会在 Tk 事件循环里同步嵌套重入，进程直接致命崩溃（``Fatal Python error:
    PyEval_RestoreThread ... the GIL is released``；换 ``ctypes.PyDLL`` —— 调用
    期间不释放 GIL —— 照样崩，所以不是 GIL 释放本身的问题）。要动窗口状态就用
    ``PostMessage(hwnd, WM_SYSCOMMAND, SC_MINIMIZE | SC_RESTORE, 0)``：异步投递、
    由 Tk 自己的消息泵处理，实测安全。下面这对 SW_HIDE/SW_SHOW 是唯一例外，
    实测安全且没有替代写法（见 ②）。
    """
    user32 = _user32()
    # 先把 Tk 挂起的 geometry 请求落实下去 —— 理由见 docstring ④，删了弹窗会跑到
    # 屏幕左上角
    win.update_idletasks()
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


# 窗口图标画多大。任务栏那一格实测只画 **18px 左右**，而 wm_iconbitmap 交给
# Explorer 的永远是 32px、再被缩一次 —— 那一刀缩放就是"糊"的来源。所以这里
# 按原生尺寸给：24px 画到 18px 只缩一点点，三道线分得开。
WINDOW_ICON_PX = 24


def set_window_icon(win: tk.Toplevel, image) -> None:
    """把 ``image`` 挂成窗口图标。**必须用 wm_iconphoto，不能用 wm_iconbitmap。**

    要让任务栏那一格画出带着这图案的图标，两个动作缺一不可（2026-09-29 实测）：

    ① 本函数 —— 把图标挂到窗口上
    ② ``app.declare_app_id()`` —— 在建窗口之前声明进程的 AppUserModelID

    **② 不能省**：没声明 AUMID 时，进程被归到 pythonw.exe 名下，任务栏按钮画的
    就是它的图标，窗口图标在这一层根本不参与 —— 实测**一个普通 Tk 窗口调
    ``iconbitmap()`` 照样画 Python 图标**。网上"设 iconbitmap 就行"的老配方在
    这里是不成立的，别再照抄。

    **① 为什么不能用 iconbitmap**：它内部走 ``LoadImage(LR_DEFAULTSIZE)``，交给
    Explorer 的永远是 **32px** 的 HICON；任务栏那一格只画 18px，多出来的那一刀
    缩放会把三道细线糊成一块（16 倍放大逐张对比过）。``wm_iconphoto`` **保留图片
    原生尺寸**（实测给 20/24/32 就分别装成 20/24/32），24px 画到 18px 几乎无损。

    **只传一张图**：给多张时 Tk 会把小的丢掉、只拿最大的当大图标（实测给
    32+20，无论顺序，任务栏画的都是 32）。

    只给到点弹窗设就够，别的窗口不用管：便签本 / 编辑框 / 提示框都是
    ``TOOLWINDOW``（``overrideredirect`` 的副作用），shell 压根不给它们画图标
    —— 没有任务栏格、也不进 Alt-Tab，设了也看不见。

    这里**不吞异常**：由调用方决定怎么兜。图标只是个门面，绝不能反过来让提醒
    弹不出来。
    """
    photo = ImageTk.PhotoImage(image, master=win)
    win._window_icon = photo    # 必须持住引用：PhotoImage 被回收，图标就没了
    win.wm_iconphoto(True, photo)


class Dragger:
    """按住某个控件拖动整窗。

    没有系统标题栏，就得自己造一个：窗口里那块顶部色带（或者便签本身）
    就是标题栏。

    记的是「按下时鼠标在窗口内部的哪个点」，之后按位移走 —— 而不是把窗口
    左上角直接设成鼠标位置，后者会让窗口在按下的一瞬间瞬移一下。
    """

    def __init__(self, win: tk.Toplevel) -> None:
        self.win = win
        self._at = None

    def start(self, event) -> None:
        self._at = (event.x_root - self.win.winfo_x(),
                    event.y_root - self.win.winfo_y())

    def move(self, event) -> None:
        if self._at is None:
            return
        self.win.geometry("+%d+%d" % (event.x_root - self._at[0],
                                      event.y_root - self._at[1]))

    def attach(self, handle: tk.Widget) -> None:
        """把 handle **以及它里面不接点击的控件**都当把手。

        只绑 handle 自己是无效的：Tk 把事件投给鼠标底下那个控件，**不会冒泡给
        父控件** —— 实测 Frame 上绑了 <Button-1>，鼠标落在铺满它的 Label 上时
        回调根本不触发。而弹窗那张便签正文全是 Label、便签本顶栏也几乎全是 Label，
        于是"挡着东西时能把它推开"这个设计几乎推不动（2026-09-24 用户报"不能移动
        位置"）。所以往下递归，把展示型控件一起绑上。

        按钮、输入框这类**要接点击的绝不能绑**：从它们身上按下就会开始拖窗口，
        拖完松手还会顺带把它们按一下。
        """
        for w in [handle, *self._handles(handle)]:
            w.bind("<Button-1>", self.start)
            w.bind("<B1-Motion>", self.move)

    @classmethod
    def _handles(cls, parent: tk.Widget):
        """递归挑出能当把手的控件：只认展示型（Frame / Label / Canvas）。

        按钮本体不是，但 ``rounded_button`` 的圆角底是个 Canvas、外面那圈
        ``BTN_INSET`` 的边也该能拖 —— 它里面的 Button 会被跳过，各归各位。
        """
        for child in parent.winfo_children():
            if isinstance(child, (tk.Frame, tk.Label, tk.Canvas)):
                yield child
                yield from cls._handles(child)


def _bind_text_hover(btn: tk.Button, normal_fg: str, hover_fg: str) -> None:
    """给没有填充的按钮绑「悬停只把字加深」。

    ``-activeforeground`` 是 Tk 按**真实鼠标位置**判定的，合成事件触发不了，
    所以显式再绑一份 —— 行为可预期，也测得到。
    """
    btn.bind("<Enter>", lambda e: btn.configure(fg=hover_fg))
    btn.bind("<Leave>", lambda e: btn.configure(fg=normal_fg))


def close_button(parent: tk.Widget, command, bg: str = None,
                 fg: str = None) -> tk.Button:
    """右上角那个 ✕ —— 无边框窗口没有系统关闭按钮，每个窗口都得自己摆一个。

    它平时只有字、没有形状。悬停**不铺底色，只把字加深** —— 铺底色会在纸上
    糊出一块灰斑，跟这页纸的气质不搭（试过一版，被否了）。
    """
    normal_fg = fg or theme.INK_SOFT
    btn = tk.Button(parent, text="✕", command=command, font=theme.ui(11),
                    bg=bg or theme.PAPER_DEEP, fg=normal_fg,
                    activebackground=bg or theme.PAPER_DEEP,
                    activeforeground=theme.INK,
                    relief="flat", bd=0, highlightthickness=0,
                    padx=10, pady=0, cursor="hand2")
    _bind_text_hover(btn, normal_fg, theme.INK)
    return btn


# ---- 按钮 ----
# 有填充的按钮外面要套一层 Canvas：Tk 没有 border-radius，tk.Button 画不出
# 圆角，只能自己画一块圆角底垫在下面。**没有填充的按钮不套** —— 它们平时
# 只有字，本来就没东西需要弄圆（悬停也只改字色，不铺底色）。
#
# **按钮本体必须仍然是 tk.Button** —— 测试是按 isinstance(c, tk.Button) 加
# text 找按钮的，换成 Canvas 自绘的控件，整套测试就找不到按钮了。
BTN_INSET = 3      # 按钮比圆角底内缩多少。内缩之后它的直角角落在大圆角的
                   # 直线段里，两者同色，接缝就看不出来


def rounded_button(parent: tk.Widget, text: str, command, bg: str, fg: str,
                   hover_bg: str, hover_fg: str = None, outline: str = None,
                   font=None, radius: int = theme.BTN_R, padx: int = 16,
                   pady: int = 6) -> tk.Canvas:
    """造一个圆角按钮，返回最外层那个 Canvas（要 pack 的是它）。

    ``bg`` 同时是常态底色：**无填充的按钮就把 ``bg`` 设成父容器的底色**，
    圆角底平时就看不见，只有悬停换成 ``hover_bg`` 时才浮出来 —— 编辑 / 关闭 /
    ✕ 这些都是这么做的，所以它们跟实心按钮用的是同一套代码。

    悬停时圆角底和按钮**一起**换色，两边都绑了 Enter/Leave。
    """
    under = parent.cget("bg")           # 圆角底角外要跟父容器同色
    # canvas 先建、按钮建成它的**子控件**，再量尺寸回填 canvas。
    # 顺序不能反：create_window 只负责「摆放」，它不会把控件搬到 canvas 名下 ——
    # 控件若还挂在 parent 上又没 pack，就是个永远不显示的隐形控件，
    # 结果 canvas 上只剩一块光秃秃的圆角底、文字全没了（踩过这个坑）。
    canvas = tk.Canvas(parent, bg=under, highlightthickness=0, bd=0)
    btn = tk.Button(canvas, text=text, command=command,
                    font=font or theme.ui(10),
                    bg=bg, fg=fg, activebackground=hover_bg,
                    activeforeground=hover_fg or fg,
                    relief="flat", bd=0, highlightthickness=0,
                    padx=padx, pady=pady, cursor="hand2")
    canvas.update_idletasks()
    w = btn.winfo_reqwidth() + 2 * BTN_INSET
    h = btn.winfo_reqheight() + 2 * BTN_INSET
    canvas.configure(width=w, height=h)

    normal = theme.rounded_rect_image(w, h, radius, bg, under, outline)
    hover = theme.rounded_rect_image(w, h, radius, hover_bg, under, outline)
    item = canvas.create_image(0, 0, image=normal, anchor="nw")
    canvas.create_window(BTN_INSET, BTN_INSET, window=btn, anchor="nw")
    canvas._imgs = (normal, hover)      # 必须持引用，否则图会被回收成白板

    # 悬停要**显式**改按钮底色，不能只靠 -activebackground：那是 Tk 自己按真实
    # 鼠标位置判定的，光换圆角底会在按钮边上露出一圈灰边（圆角底变了、里面没变）。
    # 两边一起改，才是一整块按钮在变色。
    def enter(_e=None):
        canvas.itemconfigure(item, image=hover)
        btn.configure(bg=hover_bg, fg=hover_fg or fg)

    def leave(_e=None):
        canvas.itemconfigure(item, image=normal)
        btn.configure(bg=bg, fg=fg)

    for widget in (btn, canvas):
        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)
    return canvas


def primary_button(parent: tk.Widget, text: str, command) -> tk.Canvas:
    """主按钮（新建 / 保存 / 新建第一条）：黄底墨字。全应用唯一那种实心黄。"""
    return rounded_button(parent, text, command, bg=theme.STICKY, fg=theme.INK,
                          hover_bg=theme.STICKY_FOLD)


def ink_button(parent: tk.Widget, text: str, command) -> tk.Canvas:
    """到点弹窗上的「知道了」：实心墨底黄字 —— 弹窗上最重的一块。"""
    return rounded_button(parent, text, command, bg=theme.INK, fg=theme.STICKY,
                          hover_bg="#1E1710", hover_fg=theme.STICKY)


def outline_button(parent: tk.Widget, text: str, command) -> tk.Canvas:
    """到点弹窗上的「稍后 10 分钟」：一圈淡描边，比主按钮轻、比「关闭」重。"""
    return rounded_button(parent, text, command, bg=theme.PAPER, fg=theme.INK,
                          hover_bg=theme.HOVER, outline=theme.RULE,
                          padx=12)


def quiet_button(parent: tk.Widget, text: str, command,
                 on_band: bool = False) -> tk.Button:
    """没有填充的次级按钮（编辑 / 删除 / 标记已读 / 取消 / 关闭 / 快捷…）。

    平时只有字、没有形状，悬停也**不铺底色，只把字从灰墨加深成浓墨**。
    底色那版试过：在纸上就是糊出一块灰斑，跟这页纸不搭。

    常态用次一级的墨色（对纸 4.90:1，够读），悬停加深到正文那个墨色 ——
    这样「有反馈」和「不铺底色」两头都占住。
    """
    normal_fg = theme.INK_SOFT
    normal_bg = theme.PAPER_DEEP if on_band else theme.PAPER
    btn = tk.Button(parent, text=text, command=command, font=theme.ui(10),
                    bg=normal_bg, fg=normal_fg,
                    activebackground=normal_bg, activeforeground=theme.INK,
                    relief="flat", bd=0, highlightthickness=0,
                    padx=10, pady=5, cursor="hand2")
    _bind_text_hover(btn, normal_fg, theme.INK)
    return btn
