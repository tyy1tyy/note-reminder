"""装配各模块并启动。主线程跑 tkinter，托盘跑 daemon 线程。"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import messagebox

from . import clock, holiday_net, store, theme
from .autostart import TRAY_FLAG
from .main_window import MainWindow
from .model import make_log_entry
from .popup import PopupManager
from .scheduler import Scheduler

MUTEX_NAME = "Global\\RemindNotes_SingleInstance"
ERROR_ALREADY_EXISTS = 183
TICK_MS = 1000
# 等校时的耐心：几拍之内结果没到就自己开始判定，见 _ensure_started
STARTUP_GRACE_TICKS = 5

# 进程自己的 app 身份。**任务栏那一格绑的是这个，不是窗口图标** —— 2026-09-29
# 对照实测：不声明 AUMID 时窗口被归到 pythonw.exe 名下，任务栏按钮画的就是
# Python 的图标；**连一个普通 Tk 窗口调 iconbitmap() 也照样画 Python 图标**
# （所以"设 WM_GETICON 就够了"是错的，窗口图标在这一层根本不参与）。声明之后
# 同一份代码立刻变成 RemindNotes 自己的图标。
#
# **只源码版需要，打包版不要**：打包后进程就是 RemindNotes.exe，exe 里嵌的图标
# 本来就是 icon.ico，按"没声明 AUMID 就用 exe 图标"的规矩画出来已经是对的；
# 而给 exe 安一个显式 AUMID，反而可能跟用户手动 pin 出来的快捷方式对不上号、
# 在任务栏多出一格。所以下面按 sys.frozen 分流。
APP_ID = "RemindNotes.Desktop.App"


def declare_app_id() -> None:
    """在建**任何**窗口之前声明进程身份 —— 理由见 APP_ID 的注释。

    必须早于 ``tk.Tk()``：shell 是在第一次创建 UI 时把进程归到某个 app 名下的，
    晚了这一手就白做（实测：窗口都建好之后再调，任务栏不受影响）。
    """
    if getattr(sys, "frozen", False):
        return                      # 打包版靠 exe 自己的图标，见 APP_ID 注释
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass        # 拿不到 app 身份只是任务栏退回 exe 图标，不该挡住启动


class App:
    def __init__(self) -> None:
        # 必须在建窗口之前 —— 见 declare_app_id 的 docstring
        declare_app_id()
        # 校时不再在这里同步做 —— 它是网络请求，最坏要白等 3 × 1.5 秒（三个源各一次
        # 超时），表现就是"双击图标后好几秒没反应"。改成 setup() 里异步跑。
        # 但排期（normalize）必须等校时出结果，见 _after_clock 的注释。
        self.items = store.load()
        # 配色得在建任何窗口之前定下来 —— 颜色是建控件时写进去的，
        # 窗口建好了再改就只剩重建一条路（见 MainWindow.apply_palette）
        self.palette = self._load_palette()
        theme.use(self.palette)
        # 欢迎页只在头一次运行时露一次，之后启动直接进便签本
        self.first_run = not store.load_prefs().get("welcomed")
        self.root = tk.Tk()
        self.root.withdraw()
        self.scheduler = Scheduler(self.items)
        self.popups = PopupManager(self.root, self.on_changed)
        self.main_window = MainWindow(self.root, self.items, self.on_changed,
                                      self.handle_now)
        self.tray = None
        self.running = True
        self.started = False        # 校时出结果后才开始判定，见 _after_clock
        self._startup_ticks = 0     # 兜底计数：等不到校时结果时自己开始，见 _ensure_started

    @staticmethod
    def _load_palette() -> str:
        """从偏好里读配色。认不出的值一律退回默认，不怕手改坏 prefs.json。"""
        value = store.load_prefs().get("palette")
        return value if value in theme.PALETTES else store.PALETTE_DEFAULT

    # ---- 回调（全部在主线程执行）----

    def on_changed(self) -> None:
        store.save(self.items)
        self.main_window.refresh()

    def _fire_popup(self, reminder) -> None:
        self.popups.show(reminder)
        if reminder.kind == "interval" and reminder.log_to_list:
            self._log_fired(reminder)

    def _log_fired(self, reminder) -> None:
        """循环提醒触发时，往便签本补一条「已完成」记录。

        条目长什么样见 `model.make_log_entry` —— 手动「已处理」补的是同一个形，
        所以那个函数两边共用。
        """
        self.items.append(make_log_entry(reminder, clock.now()))
        store.save(self.items)
        self.main_window.refresh()

    def handle_now(self, reminder, at) -> None:
        """编辑框点了「已处理」：把这一格当已处理，从 at 重新起算。

        排期重排已经在对话框里做完了（它得按表单里那些刚改过的字段算），这里
        只收尾三件事：关掉这条循环正开着的那张弹窗（不关的话用户回头再点一下
        它的「知道了」，会又推一格 —— 点两次推两次）、按「留记录」开关补一条
        记录、落盘刷新。

        「留记录」开关管这里：没勾就不补 —— 勾了的话**触发那一刻**已经补过一条，
        处理时再补会让同一格出两条。
        """
        self.popups.close_for(reminder)
        if reminder.log_to_list:
            self.items.append(make_log_entry(reminder, at))
        self.on_changed()

    def _tick(self) -> None:
        if not self.running:
            return
        self._ensure_started()        # 校时结果还没到（或回调丢了）时的兜底
        try:
            self.scheduler.tick()
        except Exception:
            pass                      # 单次判定异常不能拖垮整个定时循环
        self.root.after(TICK_MS, self._tick)

    # ---- 托盘动作（从托盘线程调度回主线程）----

    def open_main_window(self) -> None:
        self.root.after(0, self.main_window.show)

    def new_reminder(self) -> None:
        self.root.after(0, self.main_window.open_new)

    def toggle_eyecare(self) -> None:
        """托盘「护眼模式」：在近白纸（day）和米黄稿纸（eye）之间切。

        托盘回调跑在 daemon 线程里，必须调度回主线程再碰界面 ——
        跟 open_main_window / new_reminder 同一条规矩。
        """
        self.root.after(0, self._toggle_eyecare)

    def _toggle_eyecare(self) -> None:
        self.palette = "day" if self.palette == "eye" else "eye"
        try:
            store.save_prefs({**store.load_prefs(), "palette": self.palette})
        except OSError:
            pass                    # 偏好存不下不该挡住这次切换，本次照样生效
        self.main_window.apply_palette(self.palette)
        # 托盘菜单的勾同理：构造时烘的，不刷新就一直显示旧状态
        if self.tray is not None:
            self.tray.refresh_menu()

    def eyecare_on(self) -> bool:
        """给托盘菜单的 checked 用：返回是否正处在护眼配色。"""
        return self.palette == "eye"

    def quit(self) -> None:
        self.running = False
        try:
            store.save(self.items)
        except Exception:
            pass
        if self.tray and self.tray.icon:
            self.tray.icon.stop()
        self.root.after(0, self.root.destroy)

    # ---- 启动 ----

    def setup(self, show_window: bool = True) -> None:
        """装配托盘与定时器。与 mainloop 分开，便于在测试里验证装配结果。

        show_window=True 时直接显示便签本 —— 双击启动就该看到界面，
        而不是只留个托盘图标让人再去点一下。关掉窗口仍然只是收起来，
        程序继续在托盘里跑。
        """
        from .tray import Tray
        self.scheduler.on_fire = self._fire_popup
        self.tray = Tray(
            on_open=self.open_main_window,
            on_new=self.new_reminder,
            on_quit=self.quit,
            on_toggle_eyecare=self.toggle_eyecare,
            eyecare_on=self.eyecare_on,
        )
        self.tray.build()
        self.tray.run_detached()
        # 校时是网络请求，放后台；出结果（成功或失败）后立刻收拾时间点、开始判定。
        clock.sync_async(on_done=lambda ok: self.root.after(0, self._after_clock))
        # 节假日数据：先本地判断（零成本），只有数据快不够用且距上次尝试够久才联网。
        # 它不影响界面（编辑框那句"数据到哪天"下次打开自然是最新的），所以不接回调。
        holiday_net.update_async()
        # tick 循环从这儿起就一直续下去（_tick 自己排下一拍），校时结果只决定
        # 第一拍排期有没有真的开始 —— 这样即使回调丢了也还有 _ensure_started 兜底。
        self.root.after(TICK_MS, self._tick)
        self.main_window.on_welcome_done = self._mark_welcomed
        if self.first_run:
            # 只挂个标记：这会儿窗口还没建出来（开机自启只进托盘），
            # 等 show() 触发 _build 时会自己带上
            self.main_window.show_welcome()
        if show_window:
            self.main_window.show()
            # 兜底：deiconify() 是在 mainloop 之前调的，偶尔不生效 —— 见 _ensure_window_shown
            self.root.after(800, self._ensure_window_shown)

    def _ensure_window_shown(self) -> None:
        """便签本该显示却没显示时，补一次。

        ``MainWindow.show()`` 里的 ``deiconify()`` 是在 mainloop 之前调的，绝大多数
        时候没问题；但 2026-09-23 在 exe 上实测到两次「窗口有 HWND、位置尺寸都对，
        WS_VISIBLE 却没设上」—— 手动 ``ShowWindow`` 立刻就能出来，说明只是没被映射，
        不是窗口或数据出了问题。表现就是**双击之后屏幕上什么都没有**。

        进事件循环之后再检查一次，**确实没显示才补** —— 免得平白抢一次焦点
        （``show()`` 里有 ``focus_force``）。
        """
        win = self.main_window.win
        if win is None or not win.winfo_exists():
            return
        # 判据用 Win32 的 IsWindowVisible（窗口系统的权威答案），不用 winfo_viewable()
        # —— 后者对"沉到 z 序最底"的窗口照样返回 1，这个项目踩过这个坑。
        hwnd = ctypes.windll.user32.GetAncestor(win.winfo_id(), 2)      # GA_ROOT
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            return
        # **两层都得补**。出问题的那一层是**窗口系统**：Tk 自己认为窗口早已是 normal，
        # 所以 `deiconify()` 是个空操作，光调 Tk 层的 `show()` 救不回来（2026-09-23
        # 实测：加了 show() 兜底之后照样不显示，手动 ShowWindow 立刻见效）。
        # 先把 Tk 侧的状态对齐，再用 SW_SHOW 落到窗口系统那层。
        self.main_window.show()
        ctypes.windll.user32.ShowWindow(hwnd, 5)                        # SW_SHOW

    def _after_clock(self) -> None:
        """校时出结果后的第一件事：把便签时间点收拾到最终确定的 now 上，再开始判定。

        顺序不能反 —— normalize_on_startup 会把过点的 daily 往后滚，用的是"此刻"。
        要是先用偏快的本机时钟跑一遍，09:00 的每天会在真实 08:50 就被滚到明天，
        校准回来也补不回来（漏弹一次）。所以这里只负责"开始"，tick 由 setup() 起。

        幂等：并发路径（校时回调 / _ensure_started 兜底）谁先到谁算。
        """
        if self.started:
            return
        self.started = True
        self.scheduler.startup()
        self.main_window.refresh()

    def _ensure_started(self) -> None:
        """兜底：等够 STARTUP_GRACE_TICKS 拍还没等到校时结果，就自己开始判定。

        为什么需要 —— 校时回调是整场判定**唯一**的启动开关，而它来自后台线程：
        主线程若还没进事件循环，跨线程 root.after 会抛 RuntimeError，这个回调
        就此丢失，再没人来开这个开关。表现是**这一场会话一条提醒都不弹**，而
        界面上看不出任何异常（windowed 打包下连堆栈都没地方看）。
        多等几拍等价于原来「校时超时也照常跑」的行为，代价只是一个 tick 粒度。
        """
        if self.started:
            return
        self._startup_ticks += 1
        if self._startup_ticks >= STARTUP_GRACE_TICKS:
            self._after_clock()

    def _mark_welcomed(self) -> None:
        """欢迎页看过了，落盘。下次启动直接进便签本。"""
        self.first_run = False
        try:
            store.save_prefs({**store.load_prefs(), "welcomed": True})
        except OSError:
            pass                # 存不下不该挡住「收起欢迎页」这个动作

    def run(self, show_window: bool = True) -> None:
        self.setup(show_window=show_window)
        self.root.mainloop()


def acquire_single_instance() -> bool:
    """取得单实例互斥体。已被占用时返回 False。"""
    ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _fatal(message: str) -> None:
    """.pyw 双击运行没有控制台，print 看不到，必须用弹窗。"""
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("便签提醒", message)
        root.destroy()
    except Exception:
        print(message)


def main() -> int:
    if not acquire_single_instance():
        _fatal("RemindNotes 已在运行（请查看右下角托盘图标）。")
        return 1
    try:
        import pystray  # noqa: F401
    except ImportError:
        _fatal("缺少 pystray，请先运行：\n\npip install pystray")
        return 1
    # 开机自启带 --tray → 静默进托盘；手动双击图标不带参数 → 直接显示便签本
    App().run(show_window=TRAY_FLAG not in sys.argv)
    return 0
