@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 打包成单文件 exe，给没装 Python 的人用。
REM --hidden-import pystray._win32 是必须的：pystray 用 importlib 动态加载
REM Windows 后端，PyInstaller 静态分析扫不到，漏了会让 exe 一运行就崩。
REM --add-data 把内置的法定节假日数据带进 exe（holidays._builtin_path() 在
REM sys._MEIPASS 下按这个相对路径找）。漏了的话工作日就只剩"联网层 + 手写层"，
REM 断网时退化成周一至周五。三个 .spec 里带的也是同一份，改一处别忘了另一处。
REM
REM 注意 icon.ico 只在**打包时**用（--icon，嵌进 exe 当 exe 自己的图标），
REM 运行时不需要它 —— 到点弹窗的窗口图标是程序内画的（frameless.set_window_icon
REM 走 wm_iconphoto + tray.make_icon_image），所以**不要**给它加 --add-data。

python -m PyInstaller --noconfirm --onefile --windowed ^
  --name RemindNotes ^
  --icon icon.ico ^
  --hidden-import pystray._win32 ^
  --add-data "reminders/data/holidays.json;reminders/data" ^
  run.pyw

echo.
echo 产物: dist\RemindNotes.exe
pause
