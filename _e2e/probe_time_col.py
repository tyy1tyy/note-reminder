"""查时间列到底够不够宽 —— 用真实字体量「工作日 09:00-18:00 每60分·处理后计时」，
并跟旧词「·提醒后计时」对照，判断截断是不是 2026-09-29 这次改文案引入的。

用隔离数据目录，不碰真实便签。
"""
import os
import sys
import tempfile

os.environ["REMINDNOTES_DATA_DIR"] = tempfile.mkdtemp(prefix="rn_width_probe_")
os.environ["REMINDNOTES_OFFLINE"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from datetime import datetime

from reminders import main_window as mw
from reminders.model import make_interval

root = tk.Tk()
root.withdraw()
item = make_interval("久坐提醒", [0, 1, 2, 3, 4], "09:00", "18:00", 60, False,
                     datetime.now(), repeat_mode="workdays",
                     interval_mode="rolling")
win = mw.MainWindow(root, [item], lambda: None)
win.show()                 # 窗口是懒建的（app.py 里也是 show() 才建），不 show 就没有 tree
root.update_idletasks()

tree = win.tree
col_w = int(tree.column("time", "width"))
font = win.cell_font

new_text = item.display_time()
old_text = new_text.replace("·处理后计时", "·提醒后计时")
print("时间列宽        =", col_w, "px")
print("display_time()  =", new_text)
for label, text in (("新词", new_text), ("旧词", old_text)):
    px = font.measure(text)
    print(f"{label} 文本宽     = {px}px  -> 截断成 {mw.clip_cell(text, font, col_w, pad=6)!r}")
print("列宽余量        =", col_w - 6 * 2 - font.measure(new_text), "px（负数 = 装不下）")
root.destroy()
