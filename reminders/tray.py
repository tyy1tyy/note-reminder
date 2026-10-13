"""托盘图标与菜单。跑在 daemon 线程里，所有界面动作由调用方调度回主线程。"""
from __future__ import annotations

import threading

import pystray
from PIL import Image, ImageDraw

from . import autostart

ICON_SIZE = 64


def make_icon_image(size: int = ICON_SIZE) -> Image.Image:
    """程序内画一个便签纸图标，省掉 .ico 资源文件。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 8
    body = (pad, pad, size - pad, size - pad)
    d.rounded_rectangle(body, radius=size // 10, fill=(255, 214, 102, 255),
                        outline=(180, 140, 30, 255), width=max(1, size // 32))
    corner = size - pad
    fold = size // 4
    d.polygon([(corner - fold, pad), (corner, pad), (corner, pad + fold)],
              fill=(240, 190, 70, 255))
    line_x0, line_x1 = pad + size // 10, size - pad - size // 10
    for i, ratio in enumerate((0.38, 0.52, 0.66)):
        y = int(pad + (size - 2 * pad) * ratio)
        x1 = line_x1 if i < 2 else line_x1 - size // 8
        d.line([(line_x0, y), (x1, y)], fill=(150, 115, 25, 255),
               width=max(1, size // 24))
    return img


class Tray:
    def __init__(self, on_open, on_new, on_quit, on_toggle_eyecare, eyecare_on):
        self.on_open = on_open
        self.on_new = on_new
        self.on_quit = on_quit
        self.on_toggle_eyecare = on_toggle_eyecare
        self.eyecare_on = eyecare_on        # 取值函数，返回 bool
        self.icon: pystray.Icon | None = None

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("打开便签本", lambda: self.on_open(), default=True),
            pystray.MenuItem("新建提醒", lambda: self.on_new()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "开机自启",
                lambda: self._toggle_autostart(),
                checked=lambda item: autostart.is_enabled()),
            # 勾选态由取值函数给，跟「开机自启」同一个套路。但**不是**每次弹出
            # 重算 —— Windows 后端把菜单烘在构造那一刻，所以切换之后必须显式
            # 刷新（见 refresh_menu），不然勾不会动。
            pystray.MenuItem("护眼模式", lambda: self.on_toggle_eyecare(),
                             checked=lambda item: self.eyecare_on()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.on_quit()),
        )

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

    def build(self) -> pystray.Icon:
        self.icon = pystray.Icon("RemindNotes", make_icon_image(),
                                 "便签提醒", self._menu())
        return self.icon

    def run_detached(self) -> None:
        """在 daemon 线程里跑图标事件循环，让主线程留给 tkinter。"""
        if self.icon is None:
            self.build()
        threading.Thread(target=self.icon.run, daemon=True).start()
