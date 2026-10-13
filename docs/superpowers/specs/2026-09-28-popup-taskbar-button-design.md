# 到点弹窗的任务栏按钮设计

日期：2026-09-28
状态：已实施（2026-09-28，见 `plans/2026-09-28-popup-taskbar-button.md`；实施中的偏差与实测结果见本文 §9）

## 1. 背景与目标

三个窗口（便签本 / 编辑框 / 到点弹窗）都是「一张圆角纸」，靠 `overrideredirect(True)`
去系统边框（`frameless.py:25`）。副作用：Tk 会给这种窗口打上 `WS_EX_TOOLWINDOW`
—— 而 `TOOLWINDOW` 的语义就是「不在任务栏和 Alt-Tab 里出现」。所以到点弹窗
**在任务栏里没有格子**，被别的窗口盖住、或者沉到 z 序底部之后，**没有任何找回路径**
（`PopupManager` 只在 `open_popups` 里持着引用，对外只有 `close_all()`）。

目标：让到点弹窗在任务栏里有自己的一格。
点它 = 叫回最前（窗口不在最前时任务栏点击的语义就是这个）；也可以主动把它最小化。

**不改自动 z 序策略**：弹出瞬间置顶 200ms 后释放（`popup.py:5-7`、`popup.py:62-66`，
2026-09-24 用户裁决）继续有效。本次加的是**窗口系统的入口**，不是把自动行为改回去。

## 2. 实测记录（2026-09-28，Win10 19045 / Python 3.14 x64 / Tk 8.6）

一次性探针脚本 `%TEMP%\rn_taskbar_probe1..12.py` + 截图，不是交付物。逐条结论：

| # | 结论 | 证据 |
| --- | --- | --- |
| 1 | 根因：`overrideredirect` 窗口 `style=0x96000008`（`POPUP=True CAPTION=False SYSMENU=False`）、`exstyle=0x00000080`（`TOOLWINDOW=True`） | 探针 v8 |
| 2 | 它**是真顶层窗口**（`CHILD=False`、`GetParent=0`、无属主）→ 不是天生锁死 | 探针 v8 |
| 3 | **只改样式位无效**：清 `TOOLWINDOW` + 加 `APPWINDOW` + `SWP_FRAMECHANGED`，已显示后改 / 改完再隐藏显示 / 隐藏时改都不出按钮 | 探针 v7（三种时序全 `None`） |
| 4 | **首次显示之前**改样式也无效 | 探针 v9 假设A（`None`） |
| 5 | **有效配方 = 真隐藏 → 改样式 → 真显示** | 探针 v9 假设B（差分出按钮）；阳性对照（普通窗口）同格、阴性对照（不改）无 |
| 6 | 按钮图标 = exe 的图标（Tk 窗口继承），开发态是 Python 图标 | 探针 v9 裁片 |
| 7 | Tk 的 `withdraw()` 在无边框窗口上是**真隐藏**；但 Tk 的 `deiconify()` 却不会真的把窗口重新显示出来 —— 这是 v7 变体 3 与 v9 变体 B 的唯一差别，也是 v7 全 `None` 的原因 | 探针 v9 附加 |
| 8 | Tk 拒绝对 `overrideredirect` 窗口做 `iconify()`：`can't iconify ".!toplevel": override-redirect flag is set` | 探针 v4 |
| 9 | **同步**调 `ShowWindow(SW_MINIMIZE)` → 进程致命崩溃（`Fatal Python error: PyEval_RestoreThread ... the GIL is released`，换 `PyDLL` 照崩） | 探针 v2 |
| 10 | 走 `PostMessage(WM_SYSCOMMAND, SC_MINIMIZE)` → **安全**，`iconic=True`、`tk.state()` 正确变 `'iconic'` | 探针 v10 |
| 11 | 还原后**内容完好**（纸色 + 各行文字都在，两轮） | 探针 v11 截图 |
| 12 | 配方**不破视觉**：`LAYERED` / `topmost` / `transparentcolor` / 角落像素（圆角外仍透出桌面）/ 中心纸色全部不变 | 探针 v12（用项目自己的模块搭真纸验的） |

第 3、4、5 条合起来说明：**shell 只在"窗口由隐藏变为显示"这个转换上重算任务栏归属**，
所以样式必须在隐藏状态下改、改完再显示。

## 3. 设计

### 3.1 新函数 `frameless.taskbar_button(win)`

放 `frameless.py` —— 它已经是无边框窗口公共装配的归属地（`overrideredirect`、
透明色、贴纸），这条属于同一类"窗口系统层面的装配"。
（该文件目前只 import `tkinter` 和 `theme`，本次要加 `ctypes` / `ctypes.wintypes`；
文件开头"不抽出来就要在三个窗口里各踩一遍"那段理由同样适用。）

调用 `user32` 的写法与 `app.py:182-190` 一致（`ctypes.windll.user32` + 显式
`restype`/`argtypes`），不另起一套。

```python
def taskbar_button(win: tk.Toplevel) -> None:
    """给这张纸在任务栏里挣一格 —— 被别的窗口盖住时能一键叫回来。

    docstring 必须写清三件事（都是实测结论，少一条就会有人"顺手优化"回去）：
      ① 为什么必须先真隐藏：shell 只在「隐藏 → 显示」这个转换上重算任务栏归属，
         窗口还在显示时改样式、或首次显示之前改样式，都不出按钮（探针 v7 / v9-A）
      ② 为什么不能换成 Tk 的 withdraw()/deiconify()：deiconify() 对
         overrideredirect 窗口不会真的把窗口重新显示出来（探针 v9 附加）——
         只有 Win32 的 SW_HIDE / SW_SHOW 这一对能完成这个转换
      ③ 改的是哪两个样式位、为什么只动它们：清 TOOLWINDOW（它的语义就是
         "别上任务栏和 Alt-Tab"）、加 APPWINDOW；不碰 WS_POPUP / 分层透明，
         所以圆角与透明不受影响（探针 v12：LAYERED / topmost / transparentcolor
         / 角落像素全不变）
      ④ 为什么开头必须先 ``update_idletasks()``：hide/show 会让 Tk 把窗口**当前**
         那个矩形当成它的 geometry 记下来；而调用方常常刚 ``geometry()`` 完就调这里，
         那一刻 Tk 只是记下了请求、还没应用到窗口上，于是被记下的是"还没摆好的
         (0,0)"，居中请求永久丢失（2026-09-28 实施时被 test_app.py 那条
         「弹窗应居中于屏幕」抓到：弹窗全跑到屏幕左上角）
    """
    user32 = _user32()
    # 先把 Tk 挂起的 geometry 请求落实下去 —— 见 docstring ④
    win.update_idletasks()
    hwnd = user32.GetAncestor(win.winfo_id(), GA_ROOT)
    user32.ShowWindow(hwnd, SW_HIDE)          # 必须先真隐藏：shell 只在隐藏→显示时重算
    try:
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                            | SWP_FRAMECHANGED)
    finally:
        user32.ShowWindow(hwnd, SW_SHOW)
```

**`try/finally` 不是形式主义**：中间两行若抛异常而没走 `finally`，窗口会停在
「已隐藏」状态 —— 它此时已经占着用户的注意力（提醒到点了）却看不见，且没有任何
入口能把它找回来。异常本身要让上层看得见（不吞），但窗口必须先恢复显示。

异常策略：函数内部**不吞异常**，由调用方 `popup.py` 兜住 —— 拿不到任务栏按钮是
"少了个便利入口"，绝不能反过来把弹窗的创建搞崩。

### 3.2 落点与时机（`popup.py`）

调用点：`show()` 末尾，`paper_onto()` 之后、`Dragger` / `protocol` 附近。

两条理由写进注释：

1. **必须在窗口已被 map 之后**。第 2 节第 4 条：窗口还没显示时改样式无效；
   而 `show()` 里 `note.update_idletasks()`（`popup.py:140`）之后窗口就已经映射了。
2. 放在 `show()` 末尾时，`TOPMOST_HOLD_MS`（200ms）的计时器还没到期，这次
   hide/show 落在置顶窗口内；实测 hide/show 不丢 `topmost`、不丢 `LAYERED`、
   不丢 `transparentcolor`（第 12 条），所以「弹出瞬间必被看见」不受影响。

调用形如：

```python
try:
    frameless.taskbar_button(win)
except Exception:
    pass                      # 只是少了个入口，不能让提醒弹不出来
```

### 3.3 我们一行窗口状态操作都不写

按钮长出来之后，最小化/还原**全部由 Explorer 完成**：Tk 会收到消息、`state()`
正确变成 `'iconic'`、还原后内容完好（第 10、11 条）。代码里不需要挂任何东西。

**硬规矩（写进模块注释，附证据）**：

> **绝不从 Python 里同步调 `ShowWindow(SW_MINIMIZE)` / `ShowWindow(SW_RESTORE)`。**
> 那会在 Tk 事件循环里同步嵌套重入，进程直接致命崩溃
> （`Fatal Python error: PyEval_RestoreThread ... the GIL is released`，2026-09-28 探针 v2 实证；
> 换 `ctypes.PyDLL` —— 调用期间不释放 GIL —— **照样崩**，所以不是 GIL 释放本身的问题）。
> 将来若要加"自动最小化 / 自动还原"，必须走
> `PostMessage(hwnd, WM_SYSCOMMAND, SC_MINIMIZE | SC_RESTORE, 0)`：异步投递，
> 由 Tk 自己的消息泵处理，实测安全（探针 v10 / v11）。

唯一允许的同步 `ShowWindow` 是 3.1 里的那对 `SW_HIDE` / `SW_SHOW` ——
实测安全（探针 v9/v10/v11/v12 共四次），且没有替代写法（第 3、5 条要求这个转换）。

### 3.4 顺带修：托盘菜单的勾不刷新（既有 bug）

Windows 后端**不是每次弹出重建菜单**：`HMENU` 只在 `_update_menu()` 里建一次
（`pystray/_win32.py:99-111`），右键弹出时直接用缓存（`_win32.py:203-224`），
`MFS_CHECKED` 在 `_win32.py:316` 建设时烘死。重建的唯一触发器是
`Icon.update_menu()`（`_base.py:261-275`）或给 `icon.menu` 赋值 —— 全仓库没人调过。

后果：切了「开机自启」/「护眼模式」后重新打开菜单，**勾还是旧状态**。
`tray.py:53-54` 那句注释（"菜单项在每次弹出时重建，所以切换后勾会跟着动"）按代码看是错的。
既有测试 `test_app.py:1211` 只断言了取值函数 `eyecare_on()`，盖不到渲染层。

改法：

- `tray.py` 新增 `refresh_menu()`：`if self.icon is not None: self.icon.update_menu()`，
  docstring 写明上面这段原因
- `Tray._toggle_autostart()` 末尾调一次（`tray.py:61-65`）
- `App._toggle_eyecare()` 末尾调一次（`app.py:106-112`，主线程，状态已改完）
- 同时把 `tray.py:53-54` 那条错误注释改对

## 4. 副作用与已知边界

全部是"取舍"，不是待修项，都写在这里免得下次当 bug 报：

- **弹窗会出现在 Alt-Tab 列表里**。去掉 `TOOLWINDOW` 的必然结果。判断：这是好事 ——
  多一条找回路径，且弹窗本来就是"需要你处理的东西"
- **弹窗被最小化后，纸上的「知道了 / 稍后 10 分钟 / 关闭」点不到**，只能从任务栏恢复。
  它是用户自己最小化的，接受
- **最小化期间又有提醒到点**：`close_all()` 照旧销毁它（含最小化状态）并弹新的。
  行为与今天一致，不额外处理
- **便签本主窗口仍然没有任务栏按钮**（本次明确不做），它继续靠托盘菜单「打开便签本」
  （`main_window.py:209-211` 的 `deiconify + lift + focus_force`）
- **不额外设窗口图标**：按钮图标就是 exe 图标 —— 开发态是 Python 图标，打包后是
  `icon.ico`（RemindNotes 自己的）。要定制有现成素材（`tray.make_icon_image()`），本次不做
- 多显示器 / 任务栏不在底部：都用系统默认行为，不做特判

## 5. 测试（`tests/test_app.py`）

新增（复用现有 `drive_prompt` 那套「弹窗开着 → 断言 → 关掉」的驱动方式，
`wait_window()` 漏关窗会让整个文件挂死，这条坑已踩过）：

1. **弹窗建好后扩展样式正确**：ctypes 读 `GWL_EXSTYLE`，断言 `WS_EX_TOOLWINDOW` 已清、
   `WS_EX_APPWINDOW` 已置。这是"任务栏按钮会出现"的**机器可判定代理** ——
   真去看任务栏要截图，不适合进测试
2. **配方没把视觉搞坏**：断言窗口仍 `winfo_viewable()`、`-topmost` 仍为真、
   `-transparentcolor` 未变（对应第 12 条）
3. **勾刷新被触发**：给 `Tray.refresh_menu` 打计数桩 —— 切护眼 +1、切开机自启 +1
   （真正的勾渲染在 pystray 内部，测"刷新被触发"是这里能达到的最强断言）

既有断言**不改**：托盘菜单项的六项断言（`test_app.py:1197`）不受影响 ——
本次不加菜单项。

## 6. 文档

`README.md` 的「到点弹窗」段（`README.md:72-82`）加一句：它在**任务栏有自己的一格**，
被别的窗口压住时点一下就能叫回来；也可以把它最小化。

## 7. 明确不做

- 托盘菜单加「显示当前提醒」项（曾与用户确认过，2026-09-28 因任务栏按钮已覆盖该需求而**撤掉**）
- 便签本主窗口的任务栏按钮（它要额外处理"从任务栏最小化后，托盘还能不能叫回来"：
  Tk 的 `deiconify` 在 `iconify` 上已被拒，主窗口需要 `PostMessage(SC_RESTORE)` 兜底并实测）
- 全局热键、恒置顶、自动让位 / 自动抬升
- 自定义窗口图标
- 不碰 `prompt.py` / 编辑框的居中逻辑
- 不做非 Windows 平台的分支（这个项目本来就只跑 Windows）

## 8. 待实测清单（实施时逐条验，不靠"应该没事"）

1. 弹窗出现时**肉眼看不到闪**。预期不会闪：hide 和 show 在同一个回调里完成，
   期间不回到事件循环，窗口系统没有机会在中间绘制 —— 但要确认
2. 打包 exe（`build.bat`）之后，按钮图标是 RemindNotes 的图标而不是 Python 的
3. 最小化状态下又有新提醒到点 → 覆盖重建正常
4. 多显示器 / 任务栏不在底部时按钮与还原行为正常
5. 连点按钮若干次（最小化/还原反复）不崩、内容始终完好 —— 防止第 9 条那个崩溃
   以别的形态（例如 Explorer 侧触发）重新出现

## 9. 实施结果与偏差（2026-09-28）

**偏差 1：`taskbar_button()` 必须先 `win.update_idletasks()`（规格里没预料到）**

- 现象：接上之后弹窗**跑到屏幕左上角 (0,0)**，原本该居中
- 根因：`show()` 里刚 `geometry()` 完就调配方，那一刻 Tk 只是*记下*了居中请求、
  还没应用到窗口系统上；接着 hide/show 让 Tk 把窗口**当前**那个矩形（还没摆好的
  0,0）当成了它的 geometry，居中请求就此永久丢失
- 抓到它的不是新测试，而是 2026-09-15 就写下的既有断言
  `tests/test_app.py`「弹窗应居中于屏幕」—— 老测试挡住了新改动的回归
- 处置：函数内先 flush 一次（`update_idletasks()`）、docstring 补第 ④ 条、
  测试补一条"**故意不 flush** 就调配方，断言位置不丢"

**偏差 2：§8 的待实测清单只完成了一部分**，逐条如实记录：

| 项 | 结果 |
| --- | --- |
| ① 弹窗出现时肉眼看不到闪 | **未专门确认**（没观察到异常，但没盯着看） |
| ② 打包 exe 后按钮图标是 RemindNotes 的 | **未测** —— `dist/RemindNotes.exe` 还是 9/23 打的旧包，要重新打包才能验 |
| ③ 最小化期间新提醒到点 → 覆盖重建 | **未测** |
| ④ 多显示器 / 任务栏不在底部 | **未测** |
| ⑤ 连点任务栏按钮若干次不崩 | **未测** |
| 附：任务栏里确实出现了那一格 | **已由用户实测确认**（2026-09-28，重启到新代码之后） |

**排错过程里最值得记的一条**：验证"按钮到底出没出现"时，我先后用了四种自动测量
办法 —— 截图像素差分、任务栏 `TB_BUTTONCOUNT`、UI Automation 枚举按钮、点击
任务栏看是否最小化 —— **全部不可靠**（图标长得像分不清、跨进程消息被 UIPI 拦、
UIA 在本机不暴露任务栏按钮、点击只激活不最小化）。最终定案靠两条**硬判据**：

1. **进程 PID + 启动时间**：确认跑的是不是新代码。前面所有"没显示"全部是
   老进程在跑旧代码（关窗口只是 `withdraw()`，进程还在托盘里；再启动会撞单实例
   互斥体、新进程自己退出 —— 必须托盘右键「退出」才是真退出）
2. **用户肉眼看任务栏**

以后验这类"窗口系统行为"的问题，直接上这两条，别在那四种办法上再花时间。
