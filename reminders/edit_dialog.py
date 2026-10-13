"""新建 / 编辑便签对话框。"""
from __future__ import annotations

import re
import tkinter as tk
from datetime import date, datetime, timedelta

from . import frameless, holidays, prompt, theme
from .geometry import center_on_parent
from .model import (
    WEEKDAY_LABELS, make_daily, make_interval, make_once,
    normalize_date_text, parse_date_text, parse_time_text,
)

DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M"
# 无边框圆角窗口的版式：顶部色带 = 自制标题栏，内容整块内缩 PAD。
# 窗口高度**不写死** —— 由 fit() 按当前类型的内容量出来。
DLG_W = 460
PAD = 18            # 纸四周留白，同时也是内容避开圆角的余量
# 色带高度得容得下最高的那个控件：圆角按钮外面套了一圈 Canvas，比普通按钮
# 高 2*BTN_INSET（6px）。46 的时候 ✕ 被 pack 压扁过。
BAND_H = 56         # 顶部色带高度 = 自制标题栏
DATE_MASK = "####-##-##"
# 日期各段的取值范围，配合掩码在输入时就挡住非法值（年 / 月 / 日）
DATE_LIMITS = ((1, 9999), (1, 12), (1, 31))
KINDS = (("once", "单次"), ("daily", "每天"), ("interval", "循环"))
DEFAULT_START = "08:00"
DEFAULT_END = "18:00"
DEFAULT_INTERVAL = 60

# 编辑时从"新造的便签"复制到原对象上的字段
# 注意：interval 的新字段（repeat_mode/date_from/date_to/log_to_list）必须在这里，
# 漏掉的话编辑已有循环便签时改了也不生效。
_COPY_FIELDS = ("text", "kind", "next_fire_at", "time_of_day", "weekdays",
                "repeat_mode", "interval_mode", "date_from", "date_to",
                "window_start", "window_end", "interval_minutes",
                "include_end", "log_to_list")

# 「排期」相关的字段 —— 只有这些变了才算"改了规则，需要重新计时"。
# text / log_to_list 不在此列：改文案、开关「留记录」不该动下一次的时间。
_SCHEDULE_FIELDS = ("interval_minutes", "window_start", "window_end",
                    "include_end", "repeat_mode", "date_from", "date_to",
                    "interval_mode")


def _same_schedule(base, fresh) -> bool:
    """两条循环便签的排期规则是否相同。

    weekdays **只在「按星期」模式下参与比较**：workdays / date_range 模式里它只是
    给"以后切回按星期"留的预设，而对话框每回都按默认值填（workdays 填一~五、
    date_range 填空）—— 拿它比会把"只是重开了一次对话框"误判成改了排期，白白重排。
    """
    for f in _SCHEDULE_FIELDS:
        if getattr(base, f) != getattr(fresh, f):
            return False
    if base.repeat_mode == "weekdays":
        return sorted(set(base.weekdays)) == sorted(set(fresh.weekdays))
    return True


def format_digits(digits: str, pattern: str) -> str:
    """把纯数字按 pattern 补上分隔符。'#' 是数字位，其余字符自动插入。

    format_digits('20260915', '####-##-##') -> '2026-09-15'
    """
    out, i = [], 0
    for ch in pattern:
        if i >= len(digits):
            break
        if ch == "#":
            out.append(digits[i])
            i += 1
        else:
            out.append(ch)
    return "".join(out)


def _within_limits(raw: str, pattern: str, limits) -> bool:
    """检查每段已填满的数字是否落在范围内。

    只校验"填满的段"：月份段只输了 "4" 时不能判它非法（用户可能接着输 0
    凑成 04），但输满 "45" 就可以直接拒掉。
    """
    lens = [len(m.group()) for m in re.finditer(r"#+", pattern)]
    pos = 0
    for length, (lo, hi) in zip(lens, limits):
        seg = raw[pos:pos + length]
        pos += length
        if len(seg) == length and not (lo <= int(seg) <= hi):
            return False
    return True


def apply_mask(entry: tk.Entry, pattern: str, limits=None, state=None) -> bool:
    """按 pattern 重新格式化输入框内容：只保留数字，自动补上分隔符。

    给了 limits 时还会挡非法值：输了 45 月就直接不受，输入框留在上一个
    合法状态，让用户当场发现打不进去，而不是等保存时才被提示。

    独立成函数而不内联在事件回调里，是为了能被测试直接调用 ——
    event_generate("<KeyRelease>") 需要 widget 持有键盘焦点，测试环境里拿不到。
    返回 False 表示这次输入被拒。
    """
    raw = "".join(c for c in entry.get() if c.isdigit())
    if limits is not None and not _within_limits(raw, pattern, limits):
        prev = (state or {}).get("last_ok", "")
        entry.delete(0, "end")
        entry.insert(0, prev)
        entry.icursor("end")
        return False
    text = format_digits(raw, pattern)
    if text != entry.get():
        entry.delete(0, "end")
        entry.insert(0, text)
        entry.icursor("end")
    if state is not None:
        state["last_ok"] = entry.get()
    return True


def _attach_input_mask(entry: tk.Entry, pattern: str, limits=None) -> None:
    """让输入框只敲数字，分隔符自动补上 —— 用户不必手打 '-'。"""
    state = {"last_ok": entry.get()}
    entry.bind("<KeyRelease>",
               lambda _e: apply_mask(entry, pattern, limits, state))


# ---- 时间输入：固定 4 个数字格 ----
# 时间框永远是 xx:xx 这个形状：冒号钉死，4 个数字格各自独立。删掉中间一位时那
# 一位留空（显示成空格），后面的数字不左移、光标也不甩到末尾 —— 删哪改哪。
#
# 为什么不跟日期框共用 apply_mask：那套是「抠出数字重新排版」，中间删一位会让
# 后面的数字整体前移补位，光标还只能落回末尾。时间只有 4 位、改中间某位是常事，
# 窜位比日期难受得多，所以单独做成格模型。
TIME_CELLS = 4
TIME_SHOW = (0, 1, 3, 4)      # 格索引 → 在 "xx:xx" 里的字符位置（第 2 位是冒号）
_POS_CELL = {0: 0, 1: 1, 2: 2, 3: 2, 4: 3, 5: 4}   # 显示位置 → 格，点冒号算右边那格
# 每组的 (十位格, 个位格, 上限)，用来当场挡住 25 点 / 23:60
TIME_GROUPS = ((0, 1, 23), (2, 3, 59))
# 放行的按键：Tab 要能跳到下一个控件，回车 / Esc 留给对话框自己处理
PASSTHROUGH_KEYS = ("Tab", "ISO_Left_Tab", "Return", "KP_Enter", "Escape")


def time_display(cells) -> str:
    """4 个格 → 固定 5 字符的 xx:xx，没填的格显示成空格。"""
    ch = [c or " " for c in cells]
    return f"{ch[0]}{ch[1]}:{ch[2]}{ch[3]}"


def time_parse(text: str) -> list[str]:
    """把输入框内容读回 4 个格。位置对不上的内容（外部塞进来的）留空。"""
    cells = [""] * TIME_CELLS
    for i, show in enumerate(TIME_SHOW):
        ch = text[show:show + 1]
        if ch.isdigit():
            cells[i] = ch
    return cells


def time_cell_at(pos: int) -> int:
    """显示位置 → 格索引。点到末尾（冒号右边空着）就是「没格子」，返回 4。"""
    return _POS_CELL.get(pos, TIME_CELLS)


def _time_value_ok(cells, cursor: int, digit: str) -> bool:
    """把 digit 写进 cursor 格后，它所在的两位组会不会越界。

    这一组还没填满时一律放行 —— 用户刚敲下 "2"，不能因为一时凑不出合法值就拒收。
    """
    for ten, one, limit in TIME_GROUPS:
        if cursor not in (ten, one):
            continue
        trial = list(cells)
        trial[cursor] = digit
        if not trial[ten] or not trial[one]:
            return True
        return int(trial[ten] + trial[one]) <= limit
    return True


def time_key(cells, cursor: int, key: str):
    """把一次按键作用到 4 个格上，返回 (新格, 新光标)。

    纯逻辑、不碰 widget，测试才能直接喂按键序列 —— event_generate 需要真实键盘
    焦点，测试环境里拿不到。返回 None 表示这个键不归格模型管（由调用方吃掉）。

    BackSpace 是智能退格：光标左边若是空位就一路跳过，直接清掉上一个有数字的格。
    删一整段时间不用一格一格磨。
    """
    cells = list(cells)
    if len(key) == 1 and key.isdigit():
        if cursor >= TIME_CELLS:
            return cells, cursor          # 已经填满，没格子可写
        if not _time_value_ok(cells, cursor, key):
            return cells, cursor          # 25 点 / 23:60 这种当场不收
        cells[cursor] = key
        return cells, min(cursor + 1, TIME_CELLS)
    if key == "BackSpace":
        j = cursor - 1
        while j >= 0 and not cells[j]:
            j -= 1                        # 空位连成一段时直接跳到上一个数字
        if j < 0:
            return cells, 0
        cells[j] = ""
        return cells, j
    if key == "Delete":
        if cursor < TIME_CELLS:
            cells[cursor] = ""
        return cells, cursor
    if key == "Left":
        return cells, max(0, cursor - 1)
    if key == "Right":
        return cells, min(TIME_CELLS, cursor + 1)
    if key == "Home":
        return cells, 0
    if key == "End":
        return cells, TIME_CELLS
    return None


class TimeMask:
    """把 Entry 变成固定 4 格的 xx:xx 输入框。

    用 <KeyPress> 而不是旧的 <KeyRelease>+重排：覆盖语义要自己接管，否则
    tkinter 会先把字插进选区/中间，格模型当场错位。
    """

    def __init__(self, entry: tk.Entry) -> None:
        self.entry = entry
        self.cells = time_parse(entry.get())
        self.cursor = TIME_CELLS          # 一进来光标在末尾：接着退格就是删最后一位
        entry.bind("<KeyPress>", self._on_key)
        entry.bind("<Button-1>", self._on_click)
        self.render()

    def render(self) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, time_display(self.cells))
        self.entry.icursor(TIME_SHOW[self.cursor] if self.cursor < TIME_CELLS
                           else TIME_CELLS + 1)

    def set_text(self, text: str) -> None:
        """外部改值用（「30 分钟后」这类快捷按钮），否则格模型不知道内容变了。"""
        self.cells = time_parse(text)
        self.cursor = TIME_CELLS
        self.render()

    def _apply(self, cells, cursor) -> str:
        self.cells, self.cursor = cells, cursor
        self.render()
        return "break"

    def _on_key(self, event) -> str:
        key = event.keysym
        if key.startswith("KP_") and key[3:].isdigit():
            key = key[3:]                 # 小键盘数字
        if key in PASSTHROUGH_KEYS:
            return ""                     # 让 Tab / 回车正常走
        if self.entry.selection_present() and len(key) == 1 and key.isdigit():
            # 有选区时按下数字就是「整段重来」，不是替换 —— 固定格里没有「选区」
            # 这个概念。不理会的话 tkinter 会把数字插到选区位置，格模型当场错位。
            return self._apply([""] * TIME_CELLS, 0)
        handled = time_key(self.cells, self.cursor, key)
        if handled is None:
            return "break"                # 字母之类：格式只能是 xx:xx，一律吃掉
        return self._apply(*handled)

    def _on_click(self, event) -> str:
        """点哪一格光标就落在哪一格（点冒号算它右边那格）。"""
        pos = int(self.entry.index(f"@{event.x}"))
        self.cursor = time_cell_at(pos)
        self.entry.focus_set()            # 返回 break 会拦掉默认的取焦点动作
        self.render()
        return "break"


def _attach_time_mask(entry: tk.Entry) -> TimeMask:
    """给时间输入框装上固定格模型。

    返回控制器，是因为「30 分钟后」这类快捷按钮要拿它改值 —— 直接写 Entry
    内容的话格模型不知道，光标的格索引会和显示脱节。
    """
    return TimeMask(entry)


def _attach_normalize(entry: tk.Entry, normalizer) -> None:
    """失焦时把内容自动改成标准写法。

    用户输 2026/9/5 会变成 2026-09-05 —— 自动纠正，而不是弹窗告诉他"格式不对"。
    """
    def handler(_event=None) -> None:
        raw = entry.get()
        if " " in raw:
            # 时间框是固定格的，带空格说明还没填完。这里不能去猜 ——
            # parse_time_text("0 :00") 会把空格当分隔符读出 00:00，纯属瞎编。
            return
        text = normalizer(raw)
        if text and text != entry.get():
            entry.delete(0, "end")
            entry.insert(0, text)
    entry.bind("<FocusOut>", handler)


def open_editor(parent, reminder=None, now=None):
    """打开编辑对话框。新建返回新 Reminder（未入列表），编辑就地改并返回，取消返回 None。

    外观上是「便签本上的一张单子」：跟主窗口同一套圆角纸，顶部那条色带就是
    自制标题栏（能拖、右边有 ✕）。

    高度**不写死**：三种类型的内容行数差很多（循环最多，光星期就一行），写死了
    不是底部留一大块空白、就是把「保存」挤出窗口。每次切类型重新量一遍，
    并且只改高度、不动左上角 —— 否则切一下窗口就跳一下。
    """
    now = now or datetime.now()
    is_new = reminder is None
    base = reminder or make_once("", now)

    dlg = tk.Toplevel(parent)
    # 无边框之后系统不画标题了，但这里必须照设：测试靠 title() 找这个对话框
    dlg.title("新建提醒" if is_new else "编辑提醒")
    # 这里**不能**调 dlg.transient(parent)。无边框（overrideredirect）窗口上，
    # Windows 会把 transient 的窗口映射到 z 序最底：编辑框按主窗口居中、又比它
    # 小一圈，于是 100% 被盖住（屏幕上什么都看不见），而它下面还持着 grab_set
    # 的模态抓取 —— 表现就是「双击没反应 + 整个页面点不动」。
    # 而且这个 transient 在无边框窗口上本来就是空转：Win32 查 owner 是 0，
    # 只剩「把窗口丢到最底」这一个副作用。去掉之后新窗口正常压在主人上面。

    canvas = frameless.frameless_canvas(dlg)

    # ---- 顶部 = 自制标题栏（素纸）----
    # **底色和纸一样**，只在下面那条印线处收口（见底图那处的 rule_y）。
    # 便签本顶上是满色带 —— 它是「一本便签」的胶口；编辑框是一张抽出来的素纸。
    # 两边同色带同纸色时，叠在一起就分不清是几个窗口（2026-09-23 用户反馈）。
    band = tk.Frame(canvas, bg=theme.PAPER)
    # y 从 EDGE_W 起、高度也减 EDGE_W：**别把顶上那条描边盖掉**（纸在 canvas 最底层，
    # Frame 贴 y=0 就会盖住最上面那行像素）。素纸之后顶上再没线，就真看不出封口了。
    canvas.create_window(theme.CORNER_R, theme.EDGE_W, window=band, anchor="nw",
                         width=DLG_W - 2 * theme.CORNER_R,
                         height=BAND_H - theme.EDGE_W)
    tk.Label(band, text="新建提醒" if is_new else "编辑提醒",
             bg=theme.PAPER, fg=theme.INK_SOFT,
             font=theme.ui(10)).pack(side="left", padx=(16, 0))
    frameless.close_button(band, dlg.destroy, bg=theme.PAPER).pack(
        side="right", padx=(0, 12), pady=10)
    frameless.Dragger(dlg).attach(band)

    # 表单整块贴在纸上。四边内缩 PAD，不会盖到圆角那圈透明区。
    body = tk.Frame(canvas, bg=theme.PAPER)
    canvas.create_window(PAD, BAND_H + PAD, window=body, anchor="nw",
                         width=DLG_W - 2 * PAD)

    def flabel(master, text):
        """字段名。用次一级的墨色 —— 它们是机器标的，不是便签内容。"""
        return tk.Label(master, text=text, bg=theme.PAPER, fg=theme.INK_SOFT,
                        font=theme.ui(10))

    def fentry(master, width, value):
        entry = tk.Entry(master, width=width, **theme.entry_field())
        entry.insert(0, value)
        return entry

    flabel(body, "内容").pack(anchor="w")
    text_box = tk.Text(body, height=3, bg=theme.PAPER, fg=theme.INK,
                       insertbackground=theme.INK, relief="flat", bd=0,
                       highlightthickness=1, highlightbackground=theme.RULE,
                       highlightcolor=theme.STICKY_EDGE,
                       selectbackground=theme.STICKY, selectforeground=theme.INK,
                       font=theme.pen(), wrap="word", padx=6, pady=4)
    text_box.pack(fill="x", pady=(4, 0))
    text_box.insert("1.0", base.text)

    kind_var = tk.StringVar(value=base.kind)
    kind_row = tk.Frame(body, bg=theme.PAPER)
    kind_row.pack(anchor="w", pady=(14, 0))
    for value, label in KINDS:
        tk.Radiobutton(kind_row, text=label, variable=kind_var, value=value,
                       command=lambda: sync_kind(),
                       **theme.segment()).pack(side="left", padx=(0, 6))

    form = tk.Frame(body, bg=theme.PAPER)
    form.pack(anchor="w", fill="x", pady=(12, 0))

    # ---- 单次 / 每天 ----
    when_row = tk.Frame(form, bg=theme.PAPER)
    ref = base.next_fire_at
    date_label = flabel(when_row, "日期")
    date_label.grid(row=0, column=0, sticky="w")
    date_entry = fentry(when_row, 12, ref.strftime(DATE_FMT))
    date_entry.grid(row=0, column=1, padx=(6, 18))
    flabel(when_row, "时间").grid(row=0, column=2, sticky="w")
    time_entry = fentry(when_row, 8, ref.strftime(TIME_FMT))
    time_entry.grid(row=0, column=3, padx=(6, 0))
    _attach_input_mask(date_entry, DATE_MASK, DATE_LIMITS)
    time_mask = _attach_time_mask(time_entry)
    _attach_normalize(date_entry, normalize_date_text)

    # ---- 循环 ----
    repeat_row = tk.Frame(form, bg=theme.PAPER)

    line1 = tk.Frame(repeat_row, bg=theme.PAPER)
    line1.pack(anchor="w")
    flabel(line1, "重复").pack(side="left", padx=(0, 8))
    mode_var = tk.StringVar(
        value=base.repeat_mode if base.kind == "interval" else "weekdays")
    tk.Radiobutton(line1, text="按星期", variable=mode_var, value="weekdays",
                   command=lambda: sync_mode(),
                   **theme.segment()).pack(side="left")
    tk.Radiobutton(line1, text="工作日", variable=mode_var, value="workdays",
                   command=lambda: sync_mode(),
                   **theme.segment()).pack(side="left", padx=(6, 0))
    tk.Radiobutton(line1, text="按日期区间", variable=mode_var,
                   value="date_range", command=lambda: sync_mode(),
                   **theme.segment()).pack(side="left", padx=(6, 0))

    # 模式一：勾选星期
    days_line = tk.Frame(repeat_row, bg=theme.PAPER)
    preset_days = set(base.weekdays) if base.kind == "interval" else {0, 1, 2, 3, 4}
    day_vars = []
    flabel(days_line, "星期").pack(side="left", padx=(0, 8))
    for d, label in enumerate(WEEKDAY_LABELS):
        var = tk.BooleanVar(value=d in preset_days)
        day_vars.append(var)
        tk.Checkbutton(days_line, text=label, variable=var,
                       **theme.segment()).pack(side="left", padx=(0, 4))

    # 模式二：日期区间（与勾选星期互斥）
    range_line = tk.Frame(repeat_row, bg=theme.PAPER)
    flabel(range_line, "日期").pack(side="left", padx=(0, 8))
    from_entry = fentry(range_line, 12,
                        base.date_from or now.strftime(DATE_FMT))
    from_entry.pack(side="left")
    flabel(range_line, "到").pack(side="left", padx=6)
    to_entry = fentry(range_line, 12,
                      base.date_to
                      or (now + timedelta(days=6)).strftime(DATE_FMT))
    to_entry.pack(side="left")
    for e in (from_entry, to_entry):
        _attach_input_mask(e, DATE_MASK, DATE_LIMITS)
        _attach_normalize(e, normalize_date_text)

    # 模式三：真实工作日（跟随法定节假日）—— 一排列出**本周**哪天弹、哪天不弹。
    # 前缀写「本周」而不是「工作日」：上面「重复」那排已经亮着"工作日"了，写它就是重复；
    # 而"本周"回答了"这是哪一周"，否则这排格子会被读成规则而不是本周实况。
    # 每建一次编辑框重算一次 —— 联网更新会改数据，不能缓存。
    hint_line = tk.Frame(repeat_row, bg=theme.PAPER)
    flabel(hint_line, "本周").pack(side="left", padx=(0, 8))
    _today = date.today()
    for _i, _d in enumerate(holidays.week_of(_today)):
        _on = holidays.is_workday(_d)
        tk.Label(hint_line, text=WEEKDAY_LABELS[_i],
                 # 要弹 = 便签黄底（2026-09-23 用户指定：跟「按星期」的选中态用同一个黄）。
                 # 不弹 = 纸底淡字。只读，不绑任何点击 —— 它是按数据算出来的状态，
                 # 不是让你勾的。
                 bg=theme.STICKY if _on else theme.PAPER,
                 fg=theme.INK if _on else theme.INK_FAINT,
                 font=theme.ui(10), padx=8, pady=3,
                 # 今天那格套一圈**墨框** —— "用笔圈一下"，用的是纸的描边色（EDGE）。
                 # 先用过红框，用户觉得怪（红笔在这套里专管"已错过"），换成墨线就落回体系里了。
                 highlightthickness=2 if _d == _today else 0,
                 highlightbackground=theme.EDGE).pack(side="left", padx=(4, 0))
    _covered = holidays.covered_to()
    flabel(hint_line, f"  数据至 {_covered[5:]}" if _covered
           else "  数据至 —").pack(side="left")

    line2 = tk.Frame(repeat_row, bg=theme.PAPER)
    line2.pack(anchor="w", pady=(10, 0))
    flabel(line2, "时段").pack(side="left", padx=(0, 8))
    win_start = fentry(line2, 6, base.window_start or DEFAULT_START)
    win_start.pack(side="left")
    flabel(line2, "到").pack(side="left", padx=6)
    win_end = fentry(line2, 6, base.window_end or DEFAULT_END)
    win_end.pack(side="left")
    include_var = tk.BooleanVar(
        value=base.include_end if base.kind == "interval" else True)
    tk.Checkbutton(line2, text="包含结束时刻", variable=include_var,
                   bg=theme.PAPER, fg=theme.INK_SOFT,
                   activebackground=theme.PAPER, activeforeground=theme.INK,
                   selectcolor=theme.PAPER, highlightthickness=0,
                   font=theme.ui(10), cursor="hand2"
                   ).pack(side="left", padx=(16, 0))
    for e in (win_start, win_end):
        _attach_time_mask(e)

    line3 = tk.Frame(repeat_row, bg=theme.PAPER)
    line3.pack(anchor="w", pady=(10, 0))
    flabel(line3, "间隔").pack(side="left", padx=(0, 8))
    interval_entry = fentry(
        line3, 6,
        str(base.interval_minutes if base.kind == "interval"
            else DEFAULT_INTERVAL))
    interval_entry.pack(side="left")
    flabel(line3, "分钟").pack(side="left", padx=6)

    line_timing = tk.Frame(repeat_row, bg=theme.PAPER)
    line_timing.pack(anchor="w", pady=(10, 0))
    flabel(line_timing, "计时").pack(side="left", padx=(0, 8))
    timing_var = tk.StringVar(
        value=base.interval_mode if base.kind == "interval" else "fixed")
    tk.Radiobutton(line_timing, text="固定时刻", variable=timing_var,
                   value="fixed", **theme.segment()).pack(side="left")
    tk.Radiobutton(line_timing, text="处理后计时", variable=timing_var,
                   value="rolling", **theme.segment()).pack(side="left",
                                                            padx=(6, 0))

    line4 = tk.Frame(repeat_row, bg=theme.PAPER)
    line4.pack(anchor="w", pady=(10, 0))
    log_var = tk.BooleanVar(
        value=base.log_to_list if base.kind == "interval" else False)
    tk.Checkbutton(line4, text="每次触发在便签本里留一条记录",
                   variable=log_var, bg=theme.PAPER, fg=theme.INK_SOFT,
                   activebackground=theme.PAPER, activeforeground=theme.INK,
                   selectcolor=theme.PAPER, highlightthickness=0,
                   font=theme.ui(10), cursor="hand2").pack(side="left")

    quick = tk.Frame(body, bg=theme.PAPER)
    quick.pack(anchor="w", pady=(16, 0))
    flabel(quick, "快捷").pack(side="left", padx=(0, 8))

    result: list = []

    def sync_mode() -> None:
        """三种重复模式互斥显示。

        用 before=line2 插到「时段」行之前 —— 否则 pack 会追加到末尾，
        「星期」复选框会掉到间隔和留记录开关下面去。
        """
        days_line.pack_forget()
        range_line.pack_forget()
        hint_line.pack_forget()
        mode = mode_var.get()
        if mode == "date_range":
            range_line.pack(anchor="w", pady=(10, 0), before=line2)
        elif mode == "workdays":
            hint_line.pack(anchor="w", pady=(10, 0), before=line2)
        else:
            days_line.pack(anchor="w", pady=(10, 0), before=line2)
        fit()

    def sync_kind() -> None:
        """按类型显示对应的输入区。"""
        kind = kind_var.get()
        when_row.pack_forget()
        repeat_row.pack_forget()
        if kind == "interval":
            repeat_row.pack(anchor="w", fill="x")
            sync_mode()
        else:
            when_row.pack(anchor="w", fill="x")
            if kind == "daily":       # 每天不需要日期
                date_label.grid_remove()
                date_entry.grid_remove()
            else:
                date_label.grid()
                date_entry.grid()
        fit()

    def apply_countdown(minutes: int) -> None:
        target = now + timedelta(minutes=minutes)
        kind_var.set("once")
        date_entry.delete(0, "end")
        date_entry.insert(0, target.strftime(DATE_FMT))
        # 时间框必须走格模型改值：直接写 Entry 内容它不知道，光标和格子会脱节
        time_mask.set_text(target.strftime(TIME_FMT))
        sync_kind()

    frameless.quiet_button(quick, "30 分钟后",
                           lambda: apply_countdown(30)).pack(side="left",
                                                             padx=(0, 6))
    frameless.quiet_button(quick, "1 小时后",
                           lambda: apply_countdown(60)).pack(side="left")

    def warn(message: str) -> None:
        prompt.notice(dlg, message)

    def read_time(entry, default: str, label: str):
        """空 → 用默认值；能认 → 规范化成 HH:MM；认不出来 → 提示并返回 None。

        时间框是固定 4 格的，中间带空格就是「填了一半」。这种要提示，不能
        当空值退回默认值 —— 用户明明动了手，静默换掉比报错更让人困惑。
        只有整段都清空（"  :  "）才按空值处理。
        """
        raw = entry.get()
        if not raw.replace(":", "").strip():
            return default
        if " " in raw:
            warn(f"{label}没填完整，请补齐成 08:00 这样的格式")
            return None
        raw = raw.strip()
        hm = parse_time_text(raw)
        if hm is None:
            warn(f"{label}「{raw}」无效，请填 08:00 这样的时间")
            return None
        return f"{hm[0]:02d}:{hm[1]:02d}"

    def read_date(entry, default, label: str):
        """空 → 用默认值；能认 → date；认不出来 → 提示并返回 None。"""
        raw = entry.get().strip()
        if not raw:
            return default
        d = parse_date_text(raw)
        if d is None:
            warn(f"{label}「{raw}」无效，请填 2026-09-15 这样的日期")
            return None
        return d

    def read_interval(entry, default: int):
        """间隔必须是正整数 —— 负数、小数、字母都拦下来。

        不能像日期那样"猜"：-5 和 1.5 都能从中抠出数字来，
        但抠出来的 5 和 15 跟用户想填的完全不是一回事，静默改掉更糟。
        """
        raw = entry.get().strip()
        if not raw:
            return default
        if not raw.isdigit():
            warn(f"间隔「{raw}」无效，请填正整数分钟数，比如 60\n"
                 f"不能是负数或小数")
            return None
        n = int(raw)
        if n <= 0:
            warn("间隔必须大于 0 分钟")
            return None
        return n

    def on_ok() -> None:
        text = text_box.get("1.0", "end").strip()
        if not text:
            warn("内容不能为空")
            return
        kind = kind_var.get()

        # 原则：能自动纠正的格式问题（2026/9/5、930）静默修好；
        # 猜不出意图的非法值（2026-45-11、间隔 -5）必须提示。
        if kind == "interval":
            start = read_time(win_start, DEFAULT_START, "时段开始时间")
            if start is None:
                return
            end = read_time(win_end, DEFAULT_END, "时段结束时间")
            if end is None:
                return
            if end <= start:
                warn(f"时段结束时间（{end}）要晚于开始时间（{start}）\n"
                     f"否则这个时段永远找不到能触发的时间点")
                return
            step = read_interval(interval_entry, DEFAULT_INTERVAL)
            if step is None:
                return

            if mode_var.get() == "date_range":
                d1 = read_date(from_entry, now.date(), "开始日期")
                if d1 is None:
                    return
                d2 = read_date(to_entry, d1 + timedelta(days=6), "结束日期")
                if d2 is None:
                    return
                if d2 < d1:
                    d1, d2 = d2, d1        # 起止填反了自动换回来，不弹提示
                fresh = make_interval(text, [], start, end, step,
                                      include_var.get(), now,
                                      repeat_mode="date_range",
                                      date_from=d1.isoformat(),
                                      date_to=d2.isoformat(),
                                      log_to_list=log_var.get(),
                                      interval_mode=timing_var.get())
            elif mode_var.get() == "workdays":
                # weekdays 传一~五 只是留个预设：workdays 模式的判定完全不看它，
                # 但用户以后切回「按星期」时这排勾选框会预勾好
                fresh = make_interval(text, [0, 1, 2, 3, 4], start, end, step,
                                      include_var.get(), now,
                                      repeat_mode="workdays",
                                      log_to_list=log_var.get(),
                                      interval_mode=timing_var.get())
            else:
                days = [d for d, var in enumerate(day_vars) if var.get()]
                if not days:
                    warn("请至少选择一天")
                    return
                fresh = make_interval(text, days, start, end, step,
                                      include_var.get(), now,
                                      log_to_list=log_var.get(),
                                      interval_mode=timing_var.get())
        elif kind == "daily":
            now_hm = f"{now.hour:02d}:{now.minute:02d}"
            tod = read_time(time_entry, now_hm, "时间")
            if tod is None:
                return
            fresh = make_daily(text, tod, now)
        else:
            now_hm = f"{now.hour:02d}:{now.minute:02d}"
            d = read_date(date_entry, now.date(), "日期")
            if d is None:
                return
            hm = read_time(time_entry, now_hm, "时间")
            if hm is None:
                return
            hh, mm = int(hm[:2]), int(hm[3:])
            fresh = make_once(text, datetime(d.year, d.month, d.day, hh, mm))

        if is_new:
            result.append(fresh)
        else:
            # 「处理后计时」的循环：**只改文案（或「留记录」开关）时不许动排期**
            # （2026-09-29）。以前一律 `make_interval(..., now)` 重造再全量拷回、
            # 顺手清掉 last_fired_at —— 于是"什么都没改、点一下保存"也会把下一次
            # 推成"现在 + 间隔"。用户报的"循环时间会因为重启而变"就是这个 +
            # normalize_on_startup 那两处。
            keep_schedule = (base.kind == "interval"
                             and base.interval_mode == "rolling"
                             and _same_schedule(base, fresh))
            for f in _COPY_FIELDS:
                if keep_schedule and f == "next_fire_at":
                    continue
                setattr(base, f, getattr(fresh, f))
            base.done = False
            base.snooze_until = None
            if not keep_schedule:
                base.last_fired_at = None
            base.enabled = True
            result.append(base)
        dlg.destroy()

    def on_cancel() -> None:
        dlg.destroy()

    btns = tk.Frame(body, bg=theme.PAPER)
    btns.pack(anchor="e", pady=(20, 0))
    frameless.quiet_button(btns, "取消", on_cancel).pack(side="left")
    frameless.primary_button(btns, "保存", on_ok).pack(side="left", padx=(10, 0))

    first_fit = [True]

    def fit() -> None:
        """把窗口收到内容刚好装下。

        只改高度、不动左上角 —— 切一下类型窗口就跳一下会很难受；
        但头一次要居中，所以第一次走另一条路。
        """
        dlg.update_idletasks()
        height = BAND_H + PAD + body.winfo_reqheight() + PAD
        outer_w, outer_h = frameless.outer(DLG_W, height)
        if first_fit[0]:
            dlg.geometry(center_on_parent(dlg, parent, outer_w, outer_h))
            first_fit[0] = False
        else:
            dlg.geometry(f"{outer_w}x{outer_h}"
                         f"+{dlg.winfo_x()}+{dlg.winfo_y()}")
        # 纸最后画（要等高度定下来），它会自己压到内容底下。
        # band 传纸色 = 顶上不存在"一条色带"，只留 rule_y 那条印线（标题栏的收口）。
        dlg._paper = frameless.paper_onto(canvas, DLG_W, height,
                                          band_h=BAND_H, band=theme.PAPER,
                                          rule_y=BAND_H)

    sync_kind()
    dlg.grab_set()
    dlg.wait_window()
    return result[0] if result else None
