"""抓 RemindNotes 的可见窗口，验证跑起来的是新代码（列表时间列该显示「·处理后计时」）。

memory 里的两条经验：
- 非前台进程抢不到焦点 → SetForegroundWindow 会被挡，必须用
  SetWindowPos(HWND_TOPMOST) 才截得到目标窗口；
- ctypes 必须声明 argtypes，否则 HWND_TOPMOST(-1) 会被当 32 位 int 传、调用静默失效。
"""
import ctypes
import ctypes.wintypes as wintypes
import sys
import time

from PIL import ImageGrab

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                            ctypes.POINTER(ctypes.c_ulong)]
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]

HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_NOMOVE, SWP_NOSIZE = 0x0002, 0x0001

target_pid = int(sys.argv[1])
prefix = sys.argv[2]
found = []


def cb(hwnd, _):
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value != target_pid or not user32.IsWindowVisible(hwnd):
        return True
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title, 256)
    found.append((hwnd, cls.value, title.value))
    return True


user32.EnumWindows(WNDENUMPROC(cb), None)
print("可见窗口:", [(hex(h), c, t) for h, c, t in found])

for i, (hwnd, cls, title) in enumerate(
        [f for f in found if f[1] == "TkTopLevel"]):
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.5)
    box = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(box))
    w, h = box.right - box.left, box.bottom - box.top
    if w < 50 or h < 50:
        print(f"窗口{i} 尺寸异常，跳过: {w}x{h}")
        continue
    path = f"{prefix}{i}.png"
    ImageGrab.grab(bbox=(box.left, box.top, box.right, box.bottom)).save(path)
    print(f"窗口{i} 标题={title!r} 尺寸={w}x{h} -> {path}")
