"""便签列表主窗口。关闭窗口只是隐藏，程序继续在托盘运行。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont
from tkinter import ttk

from . import clock, edit_dialog, frameless, prompt, store, theme
from .geometry import center_geometry

COLUMNS = (("time", "时间", 312), ("kind", "类型", 68), ("status", "状态", 78))
KIND_LABEL = {"once": "单次", "daily": "每天", "interval": "循环"}
# 内容列走 #0（树列），不放进 COLUMNS —— 只有 #0 列的内容会跟着层次缩进，
# 普通 columns 的位置是钉死的，父行子行会顶格对齐，看不出从属关系。
#
# 宽度是按实测的字符串定的，不是凑整数：
#   · 内容列 310 —— 必须压得住时间列的 312，不然「什么时候弹窗」比「弹窗内容」还宽，
#     主次就反了。
#   · 时间列 312 —— 最长的一条是循环的「周六日 20:00-23:00 每30分·处理后计时」
#     （实测 296px）。这一列窄了，被切掉的正是「处理后计时」—— 那是会改变行为
#     的一个模式，不该在列表里静默消失。（2026-09-29 这串字从「处理后计时」改
#     过来，**字数相同**，所以这个宽度不用重调。）
#   · 类型 / 状态只要装得下「记录」两三个字，多余的全让给上面两列。
TEXT_COL_WIDTH = 310
WIN_W, WIN_H = 820, 500

# 无边框窗口的版式：顶部色带就是自制的标题栏，内容整块内缩 PAD。
# PAD 必须大于主题里的圆角半径，内容才不会盖到圆角那圈透明区上。
#
# 色带高度得容得下最高的那个控件：圆角按钮外面套了一圈 Canvas，比普通按钮
# 高 2*BTN_INSET（6px）。52 的时候按钮被 pack 压扁、文字整行被裁掉过。
HEADER_H = 62
PAD = 12

def clock_fg() -> str:
    """底部时间那行字：平时低调，鼠标划过加深提示「这儿能点」。

    刻意写成函数、不写成模块级常量：换配色（护眼模式）时模块级常量是
    import 期抄下来的副本，不会跟着变，这行字就会留在旧纸色上。

    划过也不换色系（原来跳成蓝色），只在墨色里加深 —— 纸上一行灰字变清楚，
    而不是凭空冒出一个跟页面无关的蓝。
    """
    return theme.INK_SOFT


def clock_hover_fg() -> str:
    return theme.INK

# 底部快捷键提示，每条一行 —— 挤成一行时右侧位置不够会被截断
HINT_TEXT = "Ctrl/Shift 多选\nCtrl+A 全选"

# 列表显示顺序：越靠前越需要关注。没列到的状态排在最后。
STATUS_ORDER = ("已错过", "待提醒", "已完成", "已结束", "已暂停")

# 这些组装的都是「已经发生过的事」，组内按时间倒序 —— 最近发生的排最上面，
# 一打开就看到最新动态。其余组（待提醒这类「还没发生的事」）按正序 ——
# 马上就要弹窗的排最上面，不用往下翻。
DESC_STATUS = ("已错过", "已完成")


def sort_key(item, now: datetime):
    """排序键：主键是状态优先级，副键是计划触发时间。

    副键一律取 next_fire_at，**不看 done_at**。已完成组曾经按「什么时候完成的」
    排，但那个键不稳定：批量「标记已读」时各条的完成时刻只差微秒，而存盘只到
    秒（见 model.DT_FMT），于是同一次批量完成的那批顺序会随重启而变，看起来
    毫无规律。改用计划时间后，顺序只取决于「这条本来是几点的事」，跟用户何时
    点「知道了」无关，重启也一致。

    done_at 字段照旧保留（「何时处理完的」是个有意义的事实），只是不再参与排序。

    副键的方向也按状态分：已错过 / 已完成按倒序（9-17 的排在 9-15 上面，
    17:22 排在 17:20 上面），待提醒等按正序。两者方向相反，没法用
    reverse=True 一刀切，所以把时间换成时间戳、倒序组取负号 —— 主键
    rank 仍是升序，不受影响。

    只影响显示顺序，不动 items 本身的存储顺序 —— 否则保存到磁盘的顺序
    会随每次刷新变化，diff 起来很乱。
    """
    status = item.status_text(now)
    rank = (STATUS_ORDER.index(status) if status in STATUS_ORDER
            else len(STATUS_ORDER))
    stamp = item.next_fire_at.timestamp()
    return (rank, -stamp if status in DESC_STATUS else stamp)


# 折叠组的节点 id 前缀（真实便签的 id 是 8 位十六进制，撞不上）
GROUP_PREFIX = "grp-"


def one_line(text: str) -> str:
    """把便签内容压成一行，供列表显示。

    Treeview 的单元格是单行渲染的：换行符不会真的换行，一条带换行的便签从
    第二行起在列表里**根本看不见**（行高固定，多出来的部分等于消失）。折成
    空格至少每个字都还在。
    """
    return " ".join(text.split())


# 单元格内容两侧留的余量（像素）。ttk 的单元格没有内边距可设，不自己让出来的话，
# 截断后的省略号会直接贴到列线上，看着像被切掉一块。
CELL_PAD = 12


def clip_cell(text: str, font, max_px: int, pad: int = CELL_PAD) -> str:
    """按像素宽度截断文本，放不下的末尾补省略号。

    Treeview 自己是硬切 —— 切到半个字、也不给任何提示，看不出后面还有内容。
    所以先按字体量好宽度再塞进去。

    ``pad`` 是两侧要留的余量。内容列用默认的 CELL_PAD：省略号贴着列线会看着
    像被切掉一块。时间列可以少留点（它就一列数字和汉字，不怕挤），省下来的
    宽度正好让「处理后计时」这种长值不被截掉。
    """
    budget = max(24, max_px - 2 * pad)
    if font.measure(text) <= budget:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:              # 二分找最长放得下的前缀
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + ell) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell


def build_layout(items, now):
    """把便签排成 Treeview 要的两层形状。

    返回 [(折叠条目的名字 or None, [条目...]), ...]。名字是 None 表示这条平铺在
    顶层；否则是个可展开的条目，里面装着一组「循环刷出来的记录」。

    循环开着「留记录」时每弹一次窗就补一条 once 记录，一天十几条会把列表淹掉。
    这些记录身上带着 parent_id（标明是哪条循环刷的），同一个 parent_id 的收成
    一条，默认合上。

    **循环便签自己照常平铺**，该显示的状态、该点的操作一样不少 —— 它是活的，
    藏起来只会碍事。源便签被删掉之后记录仍然收着，标题退回用记录自己的文字。

    折叠条目和普通便签混在同一个序列里排序（条目取组内最靠前那条的键），于是
    它会落在「已完成」那一档里该出现的位置上。
    """
    by_id = {item.id: item for item in items}
    buckets = {}
    for item in items:
        if item.parent_id:
            buckets.setdefault(item.parent_id, []).append(item)

    rows = []
    folded = set()
    for parent_id, members in buckets.items():
        folded.update(m.id for m in members)
        # 源便签被删了也照样收着：这些记录是「已完成」的历史，跟它的死活无关，
        # 一删就把它们摊开，等于凭空把列表弄乱。标题退回用记录自己的文字 ——
        # 记录本来就是照着源便签的文字建的，名字不会变。
        parent = by_id.get(parent_id)
        rows.append((min(sort_key(m, now) for m in members),
                     parent.text if parent is not None else members[0].text,
                     members))

    for item in items:
        if item.id not in folded:
            rows.append((sort_key(item, now), None, [item]))

    rows.sort(key=lambda row: row[0])
    return [(name, members) for _, name, members in rows]


class MainWindow:
    def __init__(self, root: tk.Tk, items: list, on_changed):
        self.root = root
        self.items = items
        self.on_changed = on_changed
        self.win: tk.Toplevel | None = None
        self.tree: ttk.Treeview | None = None
        self.hint: tk.Label | None = None
        self.clock_label: tk.Label | None = None
        # 顶部那两句状态摘要（已错过 / 待提醒）
        self.missed_label: tk.Label | None = None
        self.pending_label: tk.Label | None = None
        # 无边框窗口：canvas 承载整张纸，header 是自制的标题栏（拖拽靠它）
        self.canvas: tk.Canvas | None = None
        self.header: tk.Frame | None = None
        self._paper = None              # 底图。必须持引用，否则会被 Python 回收
        self._welcome: tk.Frame | None = None
        self.welcome_pending = False    # 首次运行的欢迎页是否待显示
        self.on_welcome_done = None     # 收起欢迎页时回调（落盘交给 App）
        self._dragger = None            # 拖动窗口用（frameless.Dragger）
        # 底部显示哪一栏（auto / beijing / local），记住上次的选择
        self.time_display = self._load_time_display()
        # 本次运行期间哪些组是展开的。不落盘 —— 重启一律从收起开始；但运行期间
        # 必须记住，否则随便改条便签触发一次 refresh，刚展开的组又缩回去了。
        self.expanded_groups: set[str] = set()

    @staticmethod
    def _load_time_display() -> str:
        """从偏好里读时间显示方式。认不出的值一律退回默认，不怕手改坏 prefs.json。"""
        value = store.load_prefs().get("time_display")
        return value if value in ("auto", "beijing", "local") \
            else store.TIME_DISPLAY_DEFAULT

    def show(self) -> None:
        if self.win is None or not self.win.winfo_exists():
            self._build()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.refresh()

    def apply_palette(self, name: str) -> None:
        """换配色。窗口已经建出来就就地重建一遍。

        重建而不是逐个控件改色：颜色是建控件时写进每个 widget 的，ttk 样式
        也得重配一遍，逐个改又长又容易漏。这个窗口很小，重建一次无感。

        窗口还没建过就什么都不用做 —— 下次 _build 自然用的是新配色。
        展开状态记在实例上（expanded_groups），重建后照旧。
        """
        theme.use(name)
        if self.win is None or not self.win.winfo_exists():
            return
        was_open = bool(self.win.winfo_viewable())
        self.win.destroy()
        # 旧控件全随窗口没了，引用一并清掉 —— 留着它们会让 winfo_exists() 之类
        # 在死控件上被调用
        self.canvas = None
        self.header = None
        self._paper = None
        self._welcome = None
        self._build()
        # 新建出来的 Toplevel 是可见的，先收起来；本来就开着的再放出来，
        # 本来就收着（关窗口只是 withdraw）的就保持收着
        self.win.withdraw()
        if was_open:
            self.show()

    def _build(self) -> None:
        theme.apply(self.root)
        self.win = tk.Toplevel(self.root)
        self.win.title("便签本")        # 无边框后系统不画它了，留着只为心里有数
        # 去掉系统标题栏 —— 这是圆角的前提（带边框的窗口四角由系统画，只能是方的）。
        # 代价：拖拽和关闭得自己补（下面 _drag_start / 那个 ✕），窗口缩放没补，
        # 尺寸就此定死。
        self.win.geometry(center_geometry(self.win,
                                          *frameless.outer(WIN_W, WIN_H)))
        # 没有系统标题栏，也就没有系统那套关窗方式；Esc 收起欢迎页
        self.win.bind("<Escape>", self._maybe_dismiss_welcome)

        # 整张纸（圆角 + 顶部色带 + 印线）由 frameless 画好贴上来。
        # 图片当不了窗口背景，所以里面会建一个 Canvas 承载它。
        self.canvas, self._paper = frameless.as_paper(
            self.win, WIN_W, WIN_H, band_h=HEADER_H, rule_y=HEADER_H)

        self._build_header()

        # 表 + 底栏装进一个 Frame 整块贴到纸上。它四边都内缩了 PAD，
        # 而圆角只吃掉最外圈 CORNER_R 像素，所以不会盖住圆角。
        body = tk.Frame(self.canvas, bg=theme.PAPER)
        self.canvas.create_window(PAD, HEADER_H + 10, window=body, anchor="nw",
                                  width=WIN_W - 2 * PAD,
                                  height=WIN_H - (HEADER_H + 10) - PAD)
        self._build_tree(body)
        self._build_bar(body)
        self._tick_clock()
        if self.welcome_pending:
            self._build_welcome()

    def _build_tree(self, parent) -> None:
        """列表区。便签多了没有滚动条就没法看全。"""
        tree_wrap = tk.Frame(parent, bg=theme.PAPER)
        tree_wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_wrap, columns=[c[0] for c in COLUMNS],
                                 show="tree headings", selectmode="extended")
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                            command=self.tree.yview,
                            style="Paper.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        # 必须带 "tree"：只写 show="headings" 会把树列（#0）整个藏掉，而展开小三角
        # 和子项的层次缩进都靠那一列 —— 结果就是「抽屉能展开，但完全看不出能展开」。
        self.tree.heading("#0", text="内容", anchor="w")
        self.tree.column("#0", width=TEXT_COL_WIDTH, minwidth=160,
                         stretch=True, anchor="w")
        # 量文字宽度得按列表**实际渲染**的那个字体来，不然截断位置会偏。
        # 这里用 theme.pen_font() 现造一个可测量的字体对象，规格跟 ttk 样式里配的
        # 是同一份 —— 靠 nametofont 去查样式里的字体是不行的：样式里存的是
        # 「{楷体} 11」这种规格串，不是字体名，查不到会静默退回 Tk 默认字体，
        # 于是量出来的宽度和真正画出来的对不上。
        self.cell_font = theme.pen_font()
        # 列宽不再需要重算截断：无边框之后窗口尺寸定死，列宽不会变
        # （原来这里还挂着一个 <Configure> 重算，随窗口缩放一起撤掉了）
        for key, title, width in COLUMNS:
            # 表头也得左对齐：ttk 的表头默认居中，而单元格是左对齐的，
            # 于是「时间」两个字飘在列中间、下面的内容却贴在列首，读起来是错位的
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w")
        # 状态靠「笔迹」分，不靠色块：已错过是红笔；已完成是划掉并褪色 ——
        # 就是在纸上把做完的事划掉。已暂停只褪色不划掉，它没做完，
        # 划掉会被读成「已经处理了」。
        self.tree.tag_configure("missed", foreground=theme.PEN_RED)
        self._strike_font = theme.pen_font(overstrike=1)
        self.tree.tag_configure("done", foreground=theme.INK_SOFT,
                                font=self._strike_font)
        self.tree.tag_configure("paused", foreground=theme.INK_SOFT)
        # 折叠条目的标题不加粗 —— 小三角、类型列的「记录」字样、再加上子项缩进，
        # 已经够区分了，再来个粗体显得整个列表很重。
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Control-a>", self._select_all)
        # 点原生小三角展开/收起时也得记下来，否则随便改条便签触发 refresh，
        # 刚展开的组又缩回去了
        self.tree.bind("<<TreeviewOpen>>", self._remember_group_state)
        self.tree.bind("<<TreeviewClose>>", self._remember_group_state)

    def _build_header(self) -> None:
        """顶部色带里的内容：便签纸标记 + 一句状态摘要 + 新建 + 收起。

        色带**本身**是画在底图上的（它的上面两个角要跟着纸一起圆，Frame 是直角
        的，盖上去就把圆角填平了），这里只放控件。控件整块再内缩一个圆角半径，
        免得自己那两处方角压到角上的透明区。

        打开便签本最想知道的就是「有没有该处理的」，所以摘要放这儿，而不是让人
        自己去列表里数。措辞跟列表的状态列同源（都出自 status_text），两处对不上
        会比没有摘要更糟。
        """
        head = tk.Frame(self.canvas, bg=theme.PAPER_DEEP)
        self.header = head
        # y 从 EDGE_W 起、高度也减 EDGE_W：**别把顶上那条描边盖掉**。
        # 纸是 tag_lower 压在最底层的，而 Frame 贴在 y=0 就会盖住最上面那行像素 ——
        # 症状是"左右有边框、顶上没有"，看着像窗口没封口（2026-09-23 用户报的）。
        self.canvas.create_window(theme.CORNER_R, theme.EDGE_W, window=head,
                                  anchor="nw",
                                  width=WIN_W - 2 * theme.CORNER_R,
                                  height=HEADER_H - theme.EDGE_W)
        # 系统标题栏没了，这条色带就是标题栏：按住它拖窗口
        self._dragger = frameless.Dragger(self.win)
        self._dragger.attach(head)

        glyph = tk.Canvas(head, width=24, height=24, bg=theme.PAPER_DEEP,
                          highlightthickness=0)
        glyph.pack(side="left", padx=(14, 10), pady=11)
        theme.note_glyph(glyph, 24)

        self.missed_label = tk.Label(head, text="", bg=theme.PAPER_DEEP,
                                     fg=theme.PEN_RED, font=theme.ui(10))
        self.missed_label.pack(side="left")
        self.pending_label = tk.Label(head, text="", bg=theme.PAPER_DEEP,
                                      fg=theme.INK_SOFT, font=theme.ui(10))
        self.pending_label.pack(side="left", padx=(8, 0))

        # 顺序有讲究：先 pack 的靠最右。✕ 在最右，新建在它左边。
        # ✕ 的语义跟以前点系统关闭按钮一样：只是把窗口收起来，程序继续在托盘跑。
        frameless.close_button(head, self.win.withdraw).pack(
            side="right", padx=(0, 12), pady=12)
        frameless.primary_button(head, "新建", self._new).pack(
            side="right", padx=(0, 10), pady=8)

    def _drag_start(self, event) -> None:
        """按住顶部色带开始拖窗口。实现在 frameless.Dragger —— 三个窗口共用。

        这两层壳是给测试留的：测试拿不到真实鼠标事件，只能喂合成事件验位移
        算式，走这一层才验得到「主窗口真的接上了拖拽」。
        """
        self._dragger.start(event)

    def _drag_move(self, event) -> None:
        self._dragger.move(event)

    def _build_bar(self, parent) -> None:
        """底部条：次级动作靠左，时钟和快捷键提示靠右。

        时钟不再横在中间，跟提示一起放右边 —— 它俩都是「瞄一眼就行」的信息，
        凑在一块不打断左边那排动作。
        """
        bar = tk.Frame(parent, bg=theme.PAPER)
        bar.pack(fill="x", pady=(10, 0))
        for text, cmd in (("编辑", self._edit), ("删除", self._delete),
                          ("标记已读", self._complete)):
            frameless.quiet_button(bar, text, cmd).pack(side="left", padx=(0, 6))
        # 顺序有讲究：先 pack 提示（最右），再 pack 时钟 —— 后 pack 的靠里，
        # 于是时钟落在提示左边，读起来是「时间，然后快捷键」
        self.hint = tk.Label(bar, text=HINT_TEXT, bg=theme.PAPER,
                             fg=theme.INK_SOFT, font=theme.ui(8),
                             justify="left")
        self.hint.pack(side="right", padx=(12, 0))
        self.clock_label = tk.Label(bar, text="", bg=theme.PAPER,
                                    fg=clock_fg(), font=theme.ui(10),
                                    cursor="hand2")     # 手型光标：这儿能点
        self.clock_label.pack(side="right")
        self.clock_label.bind("<Button-1>", self._toggle_clock)
        # 划过变色，否则没人看得出这行灰字是可以点的
        self.clock_label.bind(
            "<Enter>", lambda e: self.clock_label.config(fg=clock_hover_fg()))
        self.clock_label.bind(
            "<Leave>", lambda e: self.clock_label.config(fg=clock_fg()))

    # ---- 首次运行的欢迎页 ----

    def show_welcome(self) -> None:
        """安排显示欢迎页。

        窗口还没建出来（比如开机自启只进托盘）就先记个标记，
        下次 _build 会自己带上。
        """
        self.welcome_pending = True
        if self.canvas is not None and self.canvas.winfo_exists():
            self._build_welcome()

    def _build_welcome(self) -> None:
        """欢迎页：一块盖住列表区的纸。

        为什么是「盖住」而不是另开一个窗口、或者干脆不建列表：列表必须照常
        建出来 —— 首次进来之后所有操作都落在它身上，测试也全靠它。这里只是
        先拿一张纸挡在前面，点掉就露出便签本。

        按用户要求不写标题：顶上不摆「欢迎使用」那种大字，第一行直接是正文。
        """
        if self._welcome is not None and self._welcome.winfo_exists():
            return
        page = tk.Frame(self.canvas, bg=theme.PAPER)
        self._welcome = page
        self.canvas.create_window(PAD, HEADER_H + 10, window=page, anchor="nw",
                                  width=WIN_W - 2 * PAD,
                                  height=WIN_H - (HEADER_H + 10) - PAD)
        inner = tk.Frame(page, bg=theme.PAPER)
        inner.pack(expand=True, anchor="w", padx=30)

        tk.Label(inner, text="到点会弹窗的便签本", bg=theme.PAPER, fg=theme.INK,
                 font=theme.ui(15)).pack(anchor="w")
        tk.Label(inner,
                 text="关掉窗口它会收进托盘，到点弹一个居中的提醒，"
                      "没有声音也不闪烁。",
                 bg=theme.PAPER, fg=theme.INK_SOFT, font=theme.ui(10),
                 justify="left").pack(anchor="w", pady=(8, 20))

        for name, desc in (
                ("单次", "指定的日期时间弹一次窗"),
                ("每天", "每天固定时刻弹窗"),
                ("循环", "在时段里每隔 N 分钟弹窗，可按星期或按日期区间")):
            row = tk.Frame(inner, bg=theme.PAPER)
            row.pack(anchor="w", pady=3)
            tk.Label(row, text=name, bg=theme.PAPER, fg=theme.INK, width=4,
                     anchor="w", font=theme.ui(10, "bold")).pack(side="left")
            tk.Label(row, text=desc, bg=theme.PAPER, fg=theme.INK_SOFT,
                     font=theme.ui(10)).pack(side="left", padx=(10, 0))

        tk.Label(inner, text="错过的不会补弹，只在列表里标红。",
                 bg=theme.PAPER, fg=theme.INK_SOFT,
                 font=theme.ui(9)).pack(anchor="w", pady=(18, 0))

        btns = tk.Frame(inner, bg=theme.PAPER)
        btns.pack(anchor="w", pady=(20, 0))
        frameless.primary_button(btns, "新建第一条", self._welcome_new).pack(
            side="left")
        frameless.quiet_button(btns, "开始使用", self._dismiss_welcome).pack(
            side="left", padx=(10, 0))

    def _welcome_new(self) -> None:
        """先收起欢迎页再开新建框 —— 否则编辑框弹出来时后面还盖着一张纸。"""
        self._dismiss_welcome()
        self._new()

    def _dismiss_welcome(self) -> None:
        """收起欢迎页，并告诉外面「看过了」（由 App 落盘）。"""
        self.welcome_pending = False
        if self._welcome is not None and self._welcome.winfo_exists():
            self._welcome.destroy()
        self._welcome = None
        if self.on_welcome_done is not None:
            self.on_welcome_done()

    def _maybe_dismiss_welcome(self, _event=None) -> None:
        """Esc 收起欢迎页。欢迎页没开着时什么都不做 —— 免得误报「看过了」。"""
        if self.welcome_pending:
            self._dismiss_welcome()

    def refresh(self) -> None:
        if self.tree is None or not self.tree.winfo_exists():
            return
        # 刷新是整表重建，选中会跟着没。先记下来、重建后还原 —— 否则「暂停」
        # 点完想再点一下恢复，得重新选一遍（别的按钮点完也一样）。
        keep = list(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        now = clock.now()
        for name, members in build_layout(self.items, now):
            if name is None:
                self._insert_item("", members[0], now)
                continue
            # 节点 id 直接用源便签的 id：它稳定、又天然唯一，比用序号强 ——
            # 序号会随列表顺序变，展开状态就记不住了。标题放 #0 列（跟里面的
            # 记录同一列，子项才会缩进），类型列标「记录」跟循环便签本身区分开。
            gid = f"{GROUP_PREFIX}{members[0].parent_id}"
            self.tree.insert(
                "", "end", iid=gid, tags=("group",),
                open=members[0].parent_id in self.expanded_groups,
                text=self._cell_text(name),
                values=("", "记录", f"{len(members)} 条"))
            for item in sorted(members, key=lambda i: sort_key(i, now)):
                self._insert_item(gid, item, now)

        # 还原选中：被删掉的那些自然就不在了，剩下的接着选上
        restore = [iid for iid in keep if self.tree.exists(iid)]
        if restore:
            self.tree.selection_set(restore)

        self._refresh_summary(now)

    def _refresh_summary(self, now: datetime) -> None:
        """更新顶部那句「几条已错过 / 几条待提醒」。

        只数平铺的便签本身，不管折叠组里的记录 —— 那些都是循环刷出来的
        「已完成」，本来就不该算进待办。口径跟列表的状态列完全一致。
        """
        if self.missed_label is None or not self.missed_label.winfo_exists():
            return
        missed = pending = 0
        for item in self.items:
            status = item.status_text(now)
            if status == "已错过":
                missed += 1
            elif status == "待提醒":
                pending += 1
        self.missed_label.config(text=f"{missed} 条已错过" if missed else "")
        if pending:
            self.pending_label.config(text=f"{pending} 条待提醒")
        else:
            # 一条都没有时，摘要得说清「是没事」而不是留白让人以为是出错
            self.pending_label.config(text="" if missed else "没有待提醒")

    def _cell_text(self, text: str) -> str:
        """列表单元格里要显示的内容：折成一行，按当前列宽截断加省略号。"""
        width = int(self.tree.column("#0", "width"))
        return clip_cell(one_line(text), self.cell_font, width)

    def _insert_item(self, parent: str, item, now: datetime) -> None:
        tag = ""
        if not item.enabled:
            tag = "paused"
        elif item.kind == "once" and item.done:
            tag = "done"
        elif item.is_missed(now):
            tag = "missed"
        self.tree.insert(parent, "end", iid=item.id, tags=(tag,) if tag else (),
                         text=self._cell_text(item.text),
                         values=(self._time_text(item.display_time()),
                                 KIND_LABEL.get(item.kind, item.kind),
                                 item.status_text(now)))

    def _time_text(self, text: str) -> str:
        """时间列也要按列宽截断再补省略号。

        这一列长短差得远：短的「每天 10:00」只占三分之一，长的
        「周六日 20:00-23:00 每30分·处理后计时」能顶满还要多。而 ttk 的单元格
        没有内边距、放不下就硬切 —— 切到半个字，右边还直接贴上下一列的「循环」，
        看着像两列串了。所以跟内容列走同一套「量好宽度再截」的办法。
        """
        width = int(self.tree.column("time", "width"))
        # 余量给小一点：时间列全是数字和汉字，挨着列线不算难看，
        # 而省下的每一像素都在保住「处理后计时」那截字
        return clip_cell(one_line(text), self.cell_font, width, pad=6)

    def _showing_beijing(self) -> bool:
        """这会儿该显示北京时间吗。

        auto：校准成功才显示北京时间 —— 没校准上时 clock.now() 跟本机时钟就是
        同一个数，标「北京时间」等于凭空给它安了个准头。
        beijing / local：用户手动点过，就听用户的。
        """
        if self.time_display == "auto":
            return clock.is_synced()
        return self.time_display == "beijing"

    def clock_text(self) -> str:
        """底部时间文字。

        「网络校准」只在真校准上时才写 —— 没校准上时那句提示就是骗人的；
        但用户手动切到北京时间这栏时，仍按他的选择显示（那时两个数本来就一样）。
        """
        if self._showing_beijing():
            stamp = clock.now().strftime("%H:%M:%S")
            return (f"北京时间 {stamp} · 网络校准" if clock.is_synced()
                    else f"北京时间 {stamp}")
        return f"本地时间 {clock.local_now().strftime('%H:%M:%S')}"

    def _toggle_clock(self, _event=None) -> None:
        """点底部时间：在北京时间和本地时间之间来回切，并记住这次选择。

        点过之后就不再跟着校准状态自动走了 —— 用户既然手动选过，就听他的。
        """
        self.time_display = "local" if self._showing_beijing() else "beijing"
        try:
            store.save_prefs({**store.load_prefs(),
                              "time_display": self.time_display})
        except OSError:
            pass                    # 偏好存不下不该挡住切换，这次照样生效
        self._refresh_clock()

    def _refresh_clock(self) -> None:
        if self.clock_label is not None and self.clock_label.winfo_exists():
            self.clock_label.config(text=self.clock_text())

    def _tick_clock(self) -> None:
        """每秒刷新底部时钟。窗口销毁后自动停下。"""
        if self.win is None or not self.win.winfo_exists():
            return
        self._refresh_clock()
        # **对齐到下一个整秒**再刷。裸用 after(1000) 是相对「上次刷新」的固定间隔，
        # 刷新时刻就永远卡在**启动那一刻的相位**上 —— 比如启动时是 .8 秒，这个钟
        # 就一直在整秒后 0.8 秒才跳字，看着比系统时钟慢将近一秒。
        # （注意：Tk 的 after **不会累积** —— 主线程忙完之后它会立刻补上，实测把主线程
        # 占死 2.5 秒再放开，滞后仍是 0s。所以这里修的是**相位**，不是"越跑越慢"。）
        # 对齐之后每拍落在整秒上，显示的秒数跟系统时钟同拍。
        self.win.after(1000 - datetime.now().microsecond // 1000, self._tick_clock)

    def open_new(self) -> None:
        """供托盘「新建提醒」调用：先确保窗口可见，再打开新建对话框。"""
        self.show()
        self._new()

    def _selected_items(self) -> list:
        """当前选中的所有便签（支持 Ctrl / Shift 多选）。"""
        if self.tree is None:
            return []
        ids = set(self.tree.selection())
        return [i for i in self.items if i.id in ids]

    def _require_selection(self) -> list:
        items = self._selected_items()
        if not items:
            prompt.notice(
                self.win,
                "选中的是记录条目的标题 —— 它只能展开收起，"
                "请展开后选中里面具体的记录"
                if self._has_group_selected()
                else "请先选中便签（可按住 Ctrl 或 Shift 多选）")
        return items

    def _group_key_of(self, node) -> str | None:
        """节点是折叠条目就返回它的 key（源便签 id），普通便签（或空）返回 None。"""
        if node is None or not str(node).startswith(GROUP_PREFIX):
            return None
        return str(node)[len(GROUP_PREFIX):]

    def _has_group_selected(self) -> bool:
        return any(self._group_key_of(n) is not None
                   for n in self.tree.selection())

    def _remember_group_state(self, _event=None) -> None:
        """把组的展开/收起记进 expanded_groups，供下次 refresh 还原。"""
        node = self.tree.focus()
        key = self._group_key_of(node)
        if key is None:
            return
        if self.tree.item(node, "open"):
            self.expanded_groups.add(key)
        else:
            self.expanded_groups.discard(key)

    def _toggle_group(self, node) -> None:
        opened = bool(self.tree.item(node, "open"))
        self.tree.item(node, open=not opened)
        key = self._group_key_of(node)
        if key is not None:
            (self.expanded_groups.discard if opened
             else self.expanded_groups.add)(key)

    def _on_double_click(self, event=None) -> str:
        """双击折叠条目的标题就展开/收起，双击便签才是编辑。

        行号从事件坐标取，不用 focus() —— focus 是键盘焦点，未必就是你双击的
        那一行（先点过别处、或用键盘上下移动过，它俩就对不上了）。

        返回值必须是 "break"：ttk.Treeview 自带一个 <Double-Button-1> 的 class
        绑定（ttk::treeview::DoubleClick），在树列上双击时它也会切换展开状态。
        不拦下来的话两下互相抵消，表现就是「双击毫无反应」。
        """
        iid = self.tree.identify_row(event.y) if event is not None else ""
        if not iid:
            iid = self.tree.focus()
        if self._group_key_of(iid) is not None:
            self._toggle_group(iid)
        else:
            self._edit()
        return "break"

    def _leaf_ids(self, nodes) -> list:
        """把一批节点展开成里面所有便签的 iid（组标题本身不算）。"""
        out = []
        for node in nodes:
            kids = self.tree.get_children(node)
            if kids:
                out.extend(self._leaf_ids(kids))
            elif self._group_key_of(node) is None:
                out.append(node)
        return out

    def _select_all(self, _event=None) -> str:
        """Ctrl+A 全选。返回 "break" 阻止 tkinter 的默认行为。

        只选真正的便签，跳过组标题 —— 选中组标题什么也做不了，「一键全读」
        却会因为它而漏掉组里的条目。收起的组不影响：selection 是数据层面的，
        里面的条目照样选得上。
        """
        if self.tree is not None:
            self.tree.selection_set(self._leaf_ids(self.tree.get_children()))
        return "break"

    def _new(self) -> None:
        result = edit_dialog.open_editor(self.win)
        if result is not None:
            self.items.append(result)
            self.on_changed()
            self.refresh()

    def _edit(self) -> None:
        items = self._require_selection()
        if not items:
            return
        if len(items) > 1:
            prompt.notice(self.win, "一次只能编辑一条便签")
            return
        result = edit_dialog.open_editor(self.win, reminder=items[0])
        if result is not None:
            self.on_changed()
            self.refresh()

    def _delete(self) -> None:
        """删除选中的便签。

        选中折叠条目的标题时，删的是它名下那一整组记录 —— 那堆本来就是这条循环
        刷出来的产物，一条条点太费事。源便签自己不在组里，不会被连带删掉。
        """
        if self.tree is None:
            return
        nodes = self.tree.selection()
        items = self._selected_items()
        if not nodes and not items:
            prompt.notice(self.win, "请先选中便签（可按住 Ctrl 或 Shift 多选）")
            return

        doomed = list(items)
        picked = [n for n in nodes if self._group_key_of(n) is not None]
        for node in picked:
            key = self._group_key_of(node)
            doomed.extend(i for i in self.items
                          if i.parent_id == key and i not in doomed)
        if not doomed:
            return

        if picked and not items:
            title = self.tree.item(picked[0], "values")[0]
            question = f"删除「{title}」名下的 {len(doomed)} 条记录？"
        elif len(doomed) == 1:
            question = f"删除「{doomed[0].text}」？"
        else:
            question = f"删除选中的 {len(doomed)} 条便签？"

        # 破坏性动作的确认也走自家的纸窗口。按钮标签说清动作本身（"删除"），
        # 别用"是/否" —— 用户不该为了点一个删除先去读问题句。
        if prompt.confirm(self.win, question + "\n此操作不可撤销。",
                          action="删除"):
            for item in doomed:
                self.items.remove(item)
            self.on_changed()
            self.refresh()

    def _complete(self) -> None:
        """把选中的便签标为已读（一次性便签标完成；每天/循环的不受影响）。"""
        items = self._require_selection()
        if not items:
            return
        for item in items:
            item.acknowledge(clock.now())
        self.on_changed()
        self.refresh()

