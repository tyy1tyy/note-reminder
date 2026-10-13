"""双击启动入口。.pyw 后缀使 Windows 用 pythonw.exe 运行，不弹控制台黑窗。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reminders.app import main

if __name__ == "__main__":
    sys.exit(main())
