# 便签提醒小工具（RemindNotes）设计

日期：2026-09-15
状态：已与用户确认，待实施

## 1. 目标

一个常驻 Windows 托盘的便签提醒工具。用户写下备忘并设定时间，到点自动弹窗提醒。

已确认的核心需求：

- 常驻后台 + 托盘图标，平时不占屏幕
- 一个便签列表主窗口用于增删改查
- 定时类型：**单次定点**、**每天固定时间重复**、**快速倒计时**、**循环**（勾选星期 + 时段 + 间隔，如「工作日 8:00-18:00 每小时」）
- 到点弹窗为**普通窗口**：不置顶、无提示音、不闪烁
- 程序未运行期间错过的提醒**不补弹**，在列表中标红
- 开机自启可选，默认关闭

## 2. 技术选型

- Python 3.14.6（本机已装，`tkinter` 可用）
- `tkinter` 作 GUI
- `pystray` 作托盘图标（需 `pip install pystray`，纯 Python，不需要 C 编译）
- `Pillow` 画托盘图标（本机已装 12.3.0）
- 其余全部用标准库（`json` / `threading` / `ctypes` / `datetime` / `uuid`）

不引入 `schedule`、`plyer`、`win10toast` 等额外依赖 —— 所需能力标准库都能覆盖。

## 3. 目录结构

项目根目录：`D:\Tools\RemindNotes\`

```
RemindNotes/
  run.pyw             双击启动（.pyw 不弹控制台黑窗）
  reminders/
    __init__.py
    model.py          便签数据结构 + 时间计算（纯逻辑，无 UI 无 IO）
    store.py          JSON 读写 + 原子替换
    scheduler.py      每秒 tick，判断谁该弹窗
    tray.py           pystray 托盘图标与菜单
    main_window.py    便签列表窗口
    edit_dialog.py    新建 / 编辑对话框
    popup.py          到点提醒弹窗
    app.py            装配各模块 + 启动 tkinter 主循环
  tests/
    test_model.py     纯逻辑测试，直接 python tests/test_model.py 运行
  docs/superpowers/specs/2026-09-15-remind-notes-design.md
```

`model.py` 与 `scheduler.py` 不 import tkinter / pystray，保证可独立测试。

## 4. 数据模型

存储位置：`%APPDATA%\RemindNotes\reminders.json`
（即 `C:\Users\Administrator\AppData\Roaming\RemindNotes\reminders.json`）

与代码分离，重装/移动程序不丢数据。

```json
{
  "version": 1,
  "items": [
    {
      "id": "8f3c1a2b",
      "text": "开会",
      "kind": "once",
      "next_fire_at": "2026-09-16T14:00:00",
      "enabled": true,
      "done": false,
      "last_fired_at": null,
      "snooze_until": null
    },
    {
      "id": "a71b9e04",
      "text": "喝水",
      "kind": "daily",
      "time_of_day": "09:00",
      "next_fire_at": "2026-09-16T09:00:00",
      "enabled": true,
      "done": false,
      "last_fired_at": "2026-09-15T09:00:01",
      "snooze_until": null
    }
  ]
}
```

### 关键设计：一切归结为「一个绝对时间点」

**`daily` 不是靠每次重算「今天的 HH:MM」来触发的**，而是维护一个和 `once` 完全相同的 `next_fire_at` 绝对时间戳。`daily` 便签弹过之后，把 `next_fire_at` 往后滚一天；滚到超过当前时间为止。

这样做的好处：

1. 触发判断对两种类型**只有一套逻辑**，不会出现"两个分支各自算错"
2. 天然处理跨午夜。若 23:55 的日报弹后点「稍后 10 分钟」，`snooze_until` 落到次日 00:05，而 `next_fire_at` 已滚到次日 23:55，两者不会打架导致重复弹窗 —— 按「今天的 HH:MM」实时重算的写法在这里会重复触发
3. `daily` 便签在程序关闭一周后重开，只需把 `next_fire_at` 向前滚到未来即可，不需要补弹逻辑

`time_of_day` 字段保留，仅用于滚动的基准和界面显示。

`done` 字段只对 `once` 有意义，`daily` 忽略它 —— `daily` 的"完成"语义就是滚到下一次。

### 快速倒计时

**倒计时不是一种 `kind`。** 用户点「30 分钟后提醒」时，直接计算 `now + 30min`，作为 `once` 写入 `next_fire_at`。少一整套类型和分支。

### 循环（`kind == "interval"`）

对应「工作日 8:00-18:00 每小时提醒我走动」这类需求。字段：

```json
{ "kind": "interval", "repeat_mode": "weekdays", "weekdays": [0,1,2,3,4],
  "date_from": "", "date_to": "",
  "window_start": "08:00", "window_end": "18:00",
  "interval_minutes": 60, "include_end": true, "log_to_list": false }
```

「哪一天算数」有两种**互斥**模式：

- `repeat_mode == "weekdays"`：看 `weekdays`（0=周一 … 6=周日）
- `repeat_mode == "date_range"`：看 `date_from` ~ `date_to` 这个闭区间，**完全不看 `weekdays`**（`day_allowed()` 是唯一的判断入口，两种模式的分支只在这里）

`include_end` 决定时段结束时刻那一格要不要也弹。

`log_to_list`（默认 `false`）开启后，每次触发会往便签本补一条 `once` 记录，**并且直接标成已完成** —— 若留成未完成，它的时间点已过，会被立刻判为「已错过」标红，看起来像出错。默认关闭是因为一天十几次会淹掉列表。写入动作在 `App._log_fired()`，不在 `Scheduler` 里 —— 调度器只管判定与回调，不负责往列表里加东西。

日期区间跑完就结束：`is_expired()` 为真（跨过 `date_to`，或就在 `date_to` 当天但已过时段结束时刻 —— 否则 18:00 弹完最后一格还会一直显示"待提醒"），此后 `should_fire()` 恒为假，列表状态显示「已结束」。按星期模式永远不过期。

**它同样归结为 `next_fire_at` 绝对时间点**，所以 `should_fire`、防重复、snooze、暂停这些逻辑一行都不用改 —— 只需实现「弹完之后怎么算下一格」（`seek_next_slot`）：从当前时刻按间隔前进，落在窗口外（星期不对、早于时段、晚于时段或超出结束）就跳到下一天的时段起点重找，上限 2000 步防死循环。

两个容易踩的点：

- 建成/重开时从「今天的时段起点」开始找第一个**严格晚于** now 的格子，而不是从「当前时刻 + 间隔」推 —— 否则在 17:00 建立、间隔 1 小时、窗口到 18:00 的情况下会算出 18:00 之外的死格子
- 程序关了好几天后重开时，`interval` 一律重算而不是逐格推进，否则关机一周要空转上百次循环

`interval` 既不算「已错过」（`is_missed` 只对 `once` 成立），也不会被标「已完成」（`acknowledge` 只对 `once` 生效）—— 跟 `daily` 一样。

### 写入的原子性

每次保存：写 `reminders.json.tmp` → `os.replace()` 覆盖正式文件。断电或强杀最多丢失最后一次改动，绝不会留下半个损坏的 JSON。

### 读取容错

`json.load` 失败或结构不符合预期时，把原文件改名备份为 `reminders.json.bad`，然后以空列表启动。程序永远不能因为数据文件坏了而起不来。

## 5. 调度与线程模型

这是本工具最容易出错的地方，规则定死。

### 主线程归属

Windows 上 tkinter 只能在主线程创建窗口；pystray 的 `icon.run()` 会阻塞。

- **主线程**：创建一个隐藏的 tkinter `root`，运行 `root.mainloop()`
- **daemon 线程**：运行 `icon.run()`

### 跨线程规矩

托盘线程中任何需要操作界面的动作，一律通过 `root.after(0, callback)` 调度回主线程执行。**绝不在托盘线程里直接调用 tkinter**。

### 定时检查

使用 `root.after(1000, tick)` 每秒检查，**不另开线程** —— `tick` 本身运行在主线程，与界面操作同线程，无需加锁。

### 触发判定（防止重复弹窗）

每秒 tick，必须保证 14:00:00 弹过之后 14:00:01 不再弹。

判定条件是「`last_fired_at` 早于本次该弹窗的时刻」，而不是「当前时间是否已过计划时刻」：

```
planned   = item.snooze_until or item.next_fire_at
should_fire = (
    item.enabled
    and not item.done                                  # once 完成后不再弹
    and now >= planned
    and (item.last_fired_at is None or item.last_fired_at < planned)
)
```

注意 `last_fired_at is None` 必须单独判断，Python 中 `None < datetime` 会抛 `TypeError`。

弹过之后：
- `once` → `done = True`
- `daily` → 将 `next_fire_at` 向后滚一天，循环直到大于当前时间
- 两者都 → `last_fired_at = now`，`snooze_until = None`

### 休眠与关机

Windows 睡眠期间 `after` 定时器停止。醒来后 tick 恢复，靠「绝对时间比较」自然补弹一次，不需要专门处理。

程序未运行期间错过的 `once` 便签：启动时不做任何补弹，由主窗口标红呈现（见 7.2）。

程序未运行期间过期的 `daily` 便签：启动时把 `next_fire_at` 滚到未来，不视为错过、不标红。

### 单实例

用 `ctypes` 调用 Windows 命名互斥体：

```python
handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\RemindNotes_SingleInstance")
already_running = (ctypes.windll.kernel32.GetLastError() == 183)  # ERROR_ALREADY_EXISTS
```

已存在实例时提示「RemindNotes 已在运行」并退出，避免开两份导致每个提醒弹两次。

## 6. 界面

### 6.1 托盘图标

图标用 Pillow 在程序内绘制生成（便签纸造型 + 折角），不依赖外部 `.ico` 文件，省掉一个资源文件。

- **左键单击** → 打开便签本（将该菜单项设为 `default=True`，pystray 在 Windows 上左键单击即触发默认项）
- **右键菜单**：
  - 打开便签本
  - 新建提醒
  - 暂停全部提醒（切换，暂停时不触发任何提醒）

「暂停全部提醒」的状态只存在内存中，程序重启后自动恢复为"不暂停"。这是临时静音（开会、演示时用），不写进数据文件，也不做成跨重启的持久状态。

另外：`import pystray` 失败时（未安装或被环境拦截），不要直接崩掉。因为 `run.pyw` 双击运行没有控制台，`print` 看不到，所以要用 tkinter 的 `messagebox` 弹一个提示框（tkinter 是标准库，此时必然可用），内容是「缺少 pystray，请运行 pip install pystray」。避免双击后毫无反应、无从排查。
  - 开机自启（可勾选）
  - 退出

### 6.2 便签列表主窗口

tkinter `Treeview`，列为：内容 / 时间 / 类型 / 状态。**带垂直滚动条**（`tree.configure(yscrollcommand=vsb.set)`）—— 便签一多没有滚动条就没法看全。

- **启动即显示**便签本（`App.setup(show_window=True)`）—— 双击启动就该看到界面，不用再去托盘点一下
- **开机自启时静默进托盘**：注册表里的自启命令带 `--tray` 参数（`autostart.TRAY_FLAG`），`main()` 认到就不显示窗口。手动双击不带参数，照常弹出便签本。参数常量放在 `autostart.py` 里被 `app.py` 引用，防止两边写不一致导致静默启动失效（有测试盯着）
- 关闭窗口 = 隐藏到托盘，不退出程序（拦截 `WM_DELETE_WINDOW`）
- 状态列着色：
  - 正常 → 默认色
  - **已错过** → 红色（`once` 且 `next_fire_at` 已过且未完成）
  - 已完成 → 灰色
  - 已暂停 → 灰色
  - 已结束（循环的日期区间跑完）→ 灰色
- 底部按钮：新建 / 编辑 / 删除 / 标记已读
- 列表**支持多选**：`selectmode="extended"`，Ctrl / Shift 多选，Ctrl+A 全选。「标记已读」和「删除」作用于全部选中行；「编辑」只接受单条，多选时提示
- 双击某行 = 编辑
- 批量清掉「已错过」的做法就是 Ctrl+A 全选后点「标记已读」，**不单独做批量按钮**
- **列表按状态优先级排序**：已错过 → 待提醒 → 已完成 → 已结束 → 已暂停，同组内按触发时间正序。只影响显示顺序，`items` 的存储顺序不变 —— 否则每次刷新都会改写磁盘上的条目顺序

### 6.3 新建 / 编辑对话框

- 位置：**相对便签本窗口居中**（不是屏幕居中）。主窗口本身居中于屏幕时两者结果相同，区别在于把主窗口拖走后对话框会跟随，多显示器时也会出现在主窗口所在的那块屏；父窗口未映射时退回屏幕居中
- 内容输入框（多行，留空不允许保存）
- 类型选择：单次 / 每天 / 循环。选「循环」时再选「按星期」或「按日期区间」（互斥），前者显示星期勾选框，后者显示起止日期输入，两者下面共用时段（起-止）+「包含结束时刻」勾选框 + 间隔分钟数；选「每天」时隐藏日期框（每天用不到日期）
- 循环的日期区间起止**填反了自动换回来**，不弹提示
- 循环还有一个「每次触发在便签本里留一条记录」勾选框，默认不勾
- 时间选择：单次用日期 + 时分，每天用时分
- 输入校验分三层，各管各的：
  1. **输入阶段就挡非法值**：日期/时间框带掩码 + 范围校验（`DATE_LIMITS`/`TIME_LIMITS`），`45` 月、`13` 月、`25` 点、`23:60` 根本打不进去 —— 输入框退回上一个合法状态，用户当场就发现，而不是等点保存才被告知。只校验"填满的段"，月份段只输了 `4` 时不判非法（用户可能接着输 0 凑成 04）
  2. **格式可纠正的静默规范化**：`2026/9/5` → `2026-09-05`、`930` → `09:30`，不弹任何提示
  3. **猜不出意图的非法值在保存时提示**：内容为空、间隔填 `-5` / `1.5` / `abc`、时段结束早于开始、循环一天都没勾。这些没法"自动纠正"——比如 `-5` 抠出数字是 `5`、`1.5` 是 `15`，跟用户想填的完全不是一回事，静默改掉比报错更糟
- 日期**默认填好今天**，用户通常不用动它；日期与时间框带输入掩码，**只敲数字会自动补上分隔符**（`20261231` → `2026-12-31`，`1430` → `14:30`），用户不必手打 `-` 和 `:`
- 快捷按钮：「30 分钟后」「1 小时后」→ 自动填成单次定点

### 6.4 到点提醒弹窗

一个非模态 `Toplevel`，**弹出瞬间置顶一次，随后立刻释放**（不恒置顶）：

- 弹出时 `attributes("-topmost", True)`，200ms 后（`TOPMOST_HOLD_MS`）设为 `False`。这一瞬足够窗口管理器把它抬到最前，保证不会被漏看
- 取消置顶**不会改变窗口当前的 Z 序** —— 窗口仍留在最前，直到用户点击别处才按正常层级沉下去。这正是想要的：既不会被漏看，又不会一直杵在所有窗口上面碍事
- 不能用 0 作为保持时长：那样窗口可能还没被抬起来就已经释放了

**同一时刻只保留一个窗口**（覆盖形式）：新提醒来时先 `close_all()` 关掉旧的再显示。同时到点好几个的话，叠加多个窗口会把屏幕糊满，反而看不清是哪个提醒。

- 位置：居中于屏幕
- 显示便签内容与时间
- 按钮：
  - **知道了** → `once` 标完成；`daily` / `interval` 无需操作（tick 时已滚好）
  - **稍后 10 分钟** → 设 `snooze_until = now + 10min`，10 分钟后再弹一次
  - **关闭** → 仅关闭弹窗，`once` 保持未完成。不会再次弹出（`last_fired_at` 已更新），但会因 `next_fire_at` 已过且未完成而在列表中**标红「已错过」**
- **被覆盖关掉的弹窗不等于用户已处理**：那条便签仍按未完成算，会在列表里标红。覆盖只是腾出窗口，不是替用户做了决定

### 6.5 开机自启

写注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，值为
`"<pythonw.exe 绝对路径>" "<run.pyw 绝对路径>"`。

托盘菜单勾选切换，默认关闭。勾选状态直接从注册表读取，不用单独存配置。

## 7. 边界情况

| 情况 | 行为 |
| --- | --- |
| 程序未运行时错过的 `once` | 不补弹，主窗口标红「已错过」 |
| 程序未运行时过期的 `daily` | `next_fire_at` 滚到未来，不标红 |
| 电脑休眠期间到点 | 醒来后由绝对时间比较补弹一次 |
| JSON 损坏 | 备份为 `.bad` 后以空列表启动 |
| 内容为空 | 不允许保存 |
| 已完成的 `once` | 不再触发；在列表中显示为已完成 |
| 循环的日期区间跑完 | 显示「已结束」，不再触发 |
| `snooze` 跨午夜 | 由 `next_fire_at` 绝对时间模型自然处理 |
| 重复启动程序 | 互斥体拦截，提示后退出 |

## 8. 测试

`tests/test_model.py`，纯函数测试，直接 `python tests/test_model.py` 运行，无需 pytest。覆盖：

1. `daily` 的下次触发时间滚动：今天未到 / 今天已过 / 正好等于当前分钟
2. 同一分钟内连续两次 tick 只触发一次
3. 倒计时换算（`now + 30min`）正确
4. `snooze_until` 优先于 `next_fire_at`
5. `snooze` 后重复 tick 不重复触发
6. `last_fired_at is None` 时不抛 `TypeError`
7. `daily` 过期多天后滚动到未来
8. `interval` 首次触发落在窗口内 / 早于窗口 / 晚于窗口 / 落在周末
9. `interval` 含与不含结束时刻的差别
10. `interval` 自定义间隔、关程序数天后重算、间隔比时段长时不死循环
11. `interval` 按日期区间：开始前建立 / 区间内 / 区间跑完后不再触发 / 与 `weekdays` 互斥
12. `interval` 的「留记录」开关：开了才写入列表，记录直接是已完成因而不会标红
13. 日期与时间的宽松解析及规范化（`2026/9/5`、`930`、非法输入返回 `None`）

## 9. 明确的非目标（YAGNI）

以下均已排除，实施时不要顺手加上：

- 每月 / 每年 / 跳过节假日等更复杂的重复规则（「按星期 + 时段 + 固定间隔」的循环现已支持，见 4.3）
- 程序重启后补弹错过的提醒
- 提示音、窗口闪烁、置顶强提醒
- ~~打包成 exe~~ —— 已实现，见第 11 节
- 云同步 / 多设备 / 账号
- 富文本、图片、附件便签
- 分类、标签、优先级、搜索
- 稍后提醒时间自定义（固定 10 分钟）

## 10. 实施前置条件

- `pystray` 已装（0.19.5）；打包另需 `pip install pyinstaller`
- 不初始化 git 仓库、不做任何提交（本机约定）

## 11. 打包分发（exe）

给没装 Python 的人用：`build.bat` → `dist\RemindNotes.exe`（约 19 MB，单文件）。

```
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name RemindNotes --icon icon.ico ^
  --hidden-import pystray._win32 ^
  run.pyw
```

**`--hidden-import pystray._win32` 是必须的**：pystray 用 `importlib.import_module()` 动态加载 Windows 后端，PyInstaller 的静态分析扫不到。漏掉的话 exe 一运行就崩，而且因为 `--windowed` 没有控制台，崩了什么提示都看不到。

### 打包后必须改变的行为

`sys.executable` 在 exe 里指向 **exe 自己**，且 `run.pyw` 并不存在（源码被塞进了 exe 内部）。所以：

- `autostart.command_line()` 在 `sys.frozen` 时直接返回 `"<exe 路径>"`，不再拼「pythonw + run.pyw」
- `autostart.is_enabled()` 改成「注册表里存在这个值就算启用」，不再解析值的命令行内容 —— 打包前后命令行格式完全不同，按内容判断会在 exe 版里误判成未启用，托盘菜单的勾选状态跟着显示错

两条都有测试锁住（`test_autostart_command_when_frozen` / `_when_not_frozen`）。

### 分发给别人时要知道的

- 只需要给 `RemindNotes.exe` 这一个文件
- 对方的数据存在**他自己的** `%APPDATA%\RemindNotes\`，与你的互不干扰
- 「开机自启」要对方自己勾（注册表项是每用户一份）
- **杀软误报**：PyInstaller 单文件 exe 被 SmartScreen 或国产杀软拦下是常见现象（提示「未知发布者」，甚至直接被删）。不是程序有问题，但对方可能会被吓到 —— 提前说一声，或改用 `--onedir` 打成文件夹（误报率低些，但要把整个文件夹一起给）

## 12. 时间校准（对齐北京时间）

本机时钟不准会直接让提醒不准 —— 实测这台机器**快 8.4 秒**。`reminders/clock.py` 在**启动时**用 NTP 校准一次（在 `App.__init__` 里、读数据之前），此后所有「现在几点」都走 `clock.now()`。

- **只校准一次**（用户明确要求）。不做定期重校，也就不需要额外线程，连带没有线程安全问题
- 用 `socket` + `struct` 手写 NTP 请求，不引入 `ntplib`
- 服务器按序试：`ntp.aliyun.com` → `cn.pool.ntp.org` → `time.windows.com`，单个超时 1.5 秒
- **失败就静默用本机时钟** —— 断网、公司防火墙封 UDP 123 都很常见，绝不能因此让程序不能用
- 取回的时间转成北京时间并**丢掉时区**（返回 naive datetime）。整个程序内部都用 naive 时间，混入 aware datetime 会让比较和相减到处抛异常
- 便签本底部**每秒刷新**，横向分三栏、互不叠在一起：
  - **按钮靠左**（新建 / 编辑 / 删除 / 标记已读）
  - **时间在中间**，占掉按钮与快捷键之间的剩余空间并居中（`pack(side="left", expand=True)`），不要紧贴着快捷键
  - **快捷键靠右，上下两行**：`Ctrl/Shift 多选` / `Ctrl+A 全选`
  - 时间走 `clock.now()` 而非 `datetime.now()`：校准成功 → `北京时间 16:28:30 · 网络校准`；校准失败 → `本地时间 16:23:55`。**校准不上就不写「北京时间」**，提示词不能比实际情况说得更满，否则本机时钟不准时会误导
- 为什么快捷键要两行：三栏布局下右侧空间有限，挤成一行时两个操作写不全（实测 49 字符就溢出被截断）

**一致性要求**：产品内部所有「现在几点」都必须走 `clock.now()`，不能再出现 `datetime.now()`。测试同理 —— `tests/test_app.py` 会 patch 掉 `clock.sync`，否则偏移非 0 时，测试里用 `datetime.now()` 造的时间点和产品用 `clock.now()` 判断的时间点会错开 8 秒多，秒级断言（「2 秒后触发」）就会失准。NTP 本身由 `test_model.py` 里那几条单独验证（网络不通会跳过而不是失败）。
