"""开机自启开关。写 HKCU 的 Run 项，不需要管理员权限。"""
from __future__ import annotations

import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "RemindNotes"
TRAY_FLAG = "--tray"        # 开机自启带上它 → 静默进托盘，不弹窗口


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def script_path() -> str:
    """run.pyw 的绝对路径（本文件位于 <root>/reminders/ 下）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "run.pyw")


def pythonw_path() -> str:
    """真实存在的 pythonw.exe 绝对路径。

    绝不能用 WindowsApps\\pythonw —— 那是 Microsoft Store 的应用执行别名
    （0 字节 reparse point），写进自启项后开机大概率起不来。
    """
    exe = sys.executable or ""
    if exe.lower().endswith("python.exe"):
        candidate = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(candidate) and "WindowsApps" not in candidate:
            return candidate
    if exe.lower().endswith("pythonw.exe") and "WindowsApps" not in exe:
        return exe
    return exe


def command_line() -> str:
    """开机自启要写入注册表的命令行。

    打包成 exe 之后 sys.executable 就是 exe 自己，而 run.pyw 并不存在
    （源码被塞进了 exe 内部），所以不能再拼脚本路径 —— 直接指向 exe。

    一律带 --tray：开机时静默进托盘，别一开机就弹个窗口。手动双击图标
    不带这个参数，照常显示便签本。
    """
    if is_frozen():
        return f'"{sys.executable}" {TRAY_FLAG}'
    return f'"{pythonw_path()}" "{script_path()}" {TRAY_FLAG}'


def is_enabled() -> bool:
    """注册表里存在这个值就算启用（值名固定是 APP_NAME）。

    不去解析值的命令行内容 —— 打包前后命令行格式完全不同，
    按内容判断会在 exe 版里误判成「未启用」，勾选状态跟着显示错。
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command_line())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
