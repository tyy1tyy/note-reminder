"""纸与笔：全应用的视觉常量。

颜色不是随手挑的 —— 它们全部从托盘图标那张便签纸推出来
（见 tray.make_icon_image：纸 #FFD666 / 折角 #F0BE46 / 描边 #B48C1E /
横线 #967319）。窗口和托盘图标因此是同一张纸，而不是两块牌子。

字体分两个声部：

* **界面声部**（``UI_FAMILIES``）—— 顶部条、按钮、表头、时钟。机器在说话。
* **便签声部**（``PEN_FAMILIES``）—— 列表里每一行的内容。人写的字。

界面上「印上去的」和「写上去的」因此一眼分得开。
"""
from __future__ import annotations

from tkinter import font as tkfont, ttk

from PIL import Image, ImageDraw, ImageTk

# ---- 调色板 ----
# 两套配色，同一个「纸与笔」的结构，只是换了一种纸。
#
# day：近白纸（原来那套）。纸的亮度 L=0.974，接近纯白。
# eye：米黄稿纸（护眼模式）。纸的亮度压到 L=0.797。
#
# 护眼模式压的是**纸的亮度**，不是「加绿」也不是「降蓝光」—— 这套色本来就
# 是从黄色的托盘图标推出来的，蓝光占比只有 6.6%，没什么可降的；真正长时间
# 盯着累眼的是那张近白的纸。
#
# 每套配色的对比度都用 WCAG 核过（正文 ≥7:1、次要文字和红笔 ≥4.5:1、
# 图标描边这类非文字图形 ≥3:1）。换配色时**别只改背景**：纸压暗了，次要文字
# 必须同步加深，否则它反而掉到 4.5 以下 —— 第一版豆沙绿就是这么栽的。
DAY = dict(
    PAPER="#FFFCF3",       # 窗口底色：图标黄 8% 叠白
    PAPER_DEEP="#FBF2D9",  # 顶部条 / 按下态
    RULE="#E8DCB8",        # 纸上印线
    INK="#33291A",         # 正文墨色
    INK_SOFT="#7E6D4C",    # 元信息、提示、时钟（4.90:1）
    # 「不弹」那格的淡字。比 INK_SOFT 更淡（对纸约 1.8:1，低于 3:1）—— 这是有意的：
    # 那几格在七格排里只负责"占位，说明这天不弹"，不是给人读的内容。
    # 要让人看清的（哪几天要弹、今天在哪天）由墨底格子和黄描边负责。
    INK_FAINT="#C6B99B",
    PEN_RED="#B4402C",     # 「已错过」—— 红笔（5.47:1）
    STICKY="#FFD666",      # 唯一强调色：选中行、主按钮、便签本那条粘胶边
    STICKY_EDGE="#907018",  # 便签描边与横线（3.33:1，非文字图形）
    STICKY_FOLD="#F0BE46",  # 便签折角
    SHADOW="#B4A88F",      # 纸右下那条影子：无边框窗口靠它跟背后的窗口分开
    # 纸的描边。无边框之后系统那条标题栏没了，这条线就是「窗口到哪儿为止」
    # 的唯一交代 —— 光靠影子在浅色桌面上分不开两张同样的纸。
    # **用墨色（那支笔的颜色），不用纸的暗部色**：同色系的描边在白纸叠白纸时
    # 几乎看不见（编辑框压在便签本上就是那样）；而「纸与笔」里本来就有这层
    # 关系 —— 边界是勾出来的。比正文墨色浅一档：它是框线，不该抢字。
    EDGE="#5F4E34",
    # 悬停底色。**只有带形状的按钮用它**（弹窗那个描边的「稍后 10 分钟」）；
    # 只有字的按钮（关闭 / ✕ / 编辑…）悬停不铺底色，只把字加深 —— 铺底色在
    # 纸上就是糊出一块灰斑，试过一版被否了。
    HOVER="#DDD7C7",
)
EYE = dict(
    PAPER="#EFE6D4", PAPER_DEEP="#E6DAC2", RULE="#D5C4A2",
    INK="#3A3226", INK_SOFT="#756647", PEN_RED="#B4402C",
    INK_FAINT="#BCAD8E",   # 跟 day 同义：只是占位，不是给人读的
    # 纸压暗之后，便签黄也得跟着收敛 —— 不收敛的话，同一块黄在暗纸上
    # 相对更亮，选中那两行会比在近白纸上更跳
    STICKY="#EFC94F", STICKY_EDGE="#7E5F14", STICKY_FOLD="#D9B23C",
    SHADOW="#A3967B",
    EDGE="#5F4E34",        # 跟 day 同一个墨色：纸压暗后它对比度仍够（6.7:1）
    HOVER="#CFC5AF",
)
PALETTES = {"day": DAY, "eye": EYE}

_current = "day"

# 下面这些颜色名由 use() 从当前调色板刷进模块全局。用模块级常量而不是
# theme.paper() 这类取值函数，是为了让调用处保持 theme.PAPER 的读法；
# 代价只有一条：**别的模块不能在 import 期把它抄进自己的模块级常量**，
# 否则换配色时那份副本不会跟着变（CLOCK_FG 就踩过这个坑，已改成现取）。
globals().update(DAY)


def use(name: str) -> str:
    """切换到指定调色板。

    认不出的名字不生效（保持当前配色）—— 校验交给调用方，见
    ``App._load_palette``，那里是唯一读偏好文件的地方。

    只改模块级颜色常量。**已经显示在屏幕上的窗口不会自己变色**：颜色是建控件
    时写进去的，ttk 样式也得重配，所以要调用方把窗口重建一遍
    （见 ``MainWindow.apply_palette``）。
    """
    global _current
    if name in PALETTES:
        _current = name
        globals().update(PALETTES[name])
    return _current


def current() -> str:
    """当前调色板的名字。"""
    return _current

# ---- 字体 ----
# 中文 Windows 上 tkfont.families() 报的是**本地化名**（「微软雅黑」「楷体」），
# 英文名反而不在列表里。只写英文名会静默掉回 Tk 默认字体 —— 老的 popup.py
# 硬编码 "Microsoft YaHei"，在中文机器上一直没生效过。两套名字都列上，
# 按序取第一个装了的；都没装就退回 Tk 默认，保证不崩。
UI_FAMILIES = ("Microsoft YaHei UI", "微软雅黑", "Noto Sans SC", "Segoe UI")
PEN_FAMILIES = ("楷体", "KaiTi", "STKaiti", "华文楷体")

ROW_SIZE = 11              # 列表行字号
PEN_LINE_RATIOS = (0.38, 0.52, 0.66)   # 便签纸上的三条横线（照抄 tray 的比例）


def _pick(families) -> str:
    """按优先级挑第一个装了的字族。"""
    have = set(tkfont.families())
    for name in families:
        if name in have:
            return name
    return tkfont.nametofont("TkDefaultFont").actual("family")


def ui(size: int = 10, weight: str = "normal") -> tuple:
    """界面声部的字体（机器在说话）。"""
    return (_pick(UI_FAMILIES), size, weight)


def pen(size: int = ROW_SIZE, weight: str = "normal") -> tuple:
    """便签声部的字体**规格**（喂给 ttk 样式用）。

    楷体只有一个字重，``weight`` 传了也没用 —— 留这个参数是为了调用处
    形状一致，不必记住哪个声部支持粗体。
    """
    return (_pick(PEN_FAMILIES), size, weight)


def pen_font(size: int = ROW_SIZE, overstrike: int = 0):
    """便签声部的字体**对象**（给 tkfont 量宽度、给 Treeview 标签用）。

    必须写成 ``family=`` / ``size=`` 这种关键字形式：一旦写成
    ``tkfont.Font(font=("楷体", 11), overstrike=1)``，Tkinter 会把 overstrike
    悄悄丢掉（实测 ``actual()["overstrike"]`` 仍是 0），「已完成」那行的
    划掉效果就成了哑的。
    """
    return tkfont.Font(family=_pick(PEN_FAMILIES), size=size,
                       overstrike=overstrike)


# ---- 按钮 ----
# 造按钮的工厂不在这儿，在 frameless.py —— 按钮要圆角，就得在外面套一层
# Canvas 画圆角底，那属于窗口装配的活儿，跟颜色常量不是一类。

# ---- 纸上的表单控件（编辑框）----
def entry_field() -> dict:
    """输入框：直角、淡描边，聚焦时描边转琥珀。

    只用 highlight 那圈做边框，不再加额外控件 —— 输入框数量是有测试盯着的
    （`<KeyPress>` 绑定的 Entry 必须恰好 3 个），少一个控件少一处干扰。
    """
    return dict(relief="flat", bd=0, bg=PAPER, fg=INK, insertbackground=INK,
                highlightthickness=1, highlightbackground=RULE,
                highlightcolor=STICKY_EDGE,
                selectbackground=STICKY, selectforeground=INK,
                font=pen())


def segment() -> dict:
    """分段控件：把 Radiobutton / Checkbutton 放平成小方块。

    控件本身仍是 Radiobutton / Checkbutton（``indicatoron=0`` 只是不画那个
    圆点/勾），所以测试里按控件类型 + text 找它们的写法完全不受影响。
    """
    return dict(indicatoron=0, relief="flat", bd=0, highlightthickness=0,
                bg=PAPER, fg=INK_SOFT, selectcolor=STICKY,
                activebackground=PAPER_DEEP, activeforeground=INK,
                font=ui(10), padx=10, pady=3, cursor="hand2")


# ---- ttk ----
def apply(root=None) -> None:
    """把 ttk 的默认外观换成纸张外观。

    ``clam`` 是内置主题里唯一肯老实听配色的：vista 主题会忽略大部分颜色
    选项，改了半天还是系统灰。
    """
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("Treeview",
                    background=PAPER, fieldbackground=PAPER, foreground=INK,
                    font=pen(), rowheight=30,
                    borderwidth=0, relief="flat",
                    # clam 的字段区还会照 -bordercolor/-lightcolor/-darkcolor 描一圈
                    # 系统灰。只设 borderwidth 是去不掉它的，三个颜色都得按纸色抹平，
                    # 否则这张纸中间永远套着一个窗格
                    bordercolor=PAPER, lightcolor=PAPER, darkcolor=PAPER,
                    # 子项缩进要明显，一眼看出哪些是从属的记录
                    indent=28)
    # 选中一行 = 把这张便签拿起来，所以铺便签黄 —— 这是唯一让黄大面积出现的地方
    style.map("Treeview",
              background=[("selected", STICKY)],
              foreground=[("selected", INK)])

    style.configure("Treeview.Heading",
                    background=PAPER, foreground=INK_SOFT, font=ui(9),
                    relief="flat", borderwidth=0, padding=(10, 7))
    style.map("Treeview.Heading",
              background=[("active", PAPER_DEEP)])

    # 滚动条也得是纸的，否则一条系统灰贴在这张纸边上
    style.configure("Paper.Vertical.TScrollbar",
                    background=PAPER_DEEP, troughcolor=PAPER,
                    bordercolor=PAPER, arrowcolor=INK_SOFT,
                    relief="flat", borderwidth=0, arrowsize=12)
    style.map("Paper.Vertical.TScrollbar",
              background=[("active", RULE)])


# ---- 无边框圆角窗口 ----
# 透明色：窗口里凡是用这个颜色的像素都会被系统挖成透明。挑一个整张调色板
# 绝不会出现的洋红，免得误伤。
MAGIC = "#FF00FE"
CORNER_R = 8               # 窗口圆角半径
BTN_R = 7                  # 按钮圆角半径
EDGE_W = 1                 # 纸的描边宽度。1 像素，但它是"边界"这件事本身
_SUPERSAMPLE = 4           # 圆角超采样倍数
# 影子相对纸往右下偏移多少。**纸叠在纸上，区分它们靠的就是影子和那条边** ——
# 无边框之后系统那条标题栏没了，如果两张同色的纸贴在一起就完全看不出边界
# （编辑框和到点弹窗浮在便签本上时最明显）。
SHADOW_DX, SHADOW_DY = 3, 5


def rounded_rect_image(w: int, h: int, radius: int, fill: str, bg: str,
                       outline: str = None):
    """一小块圆角底板，给按钮用。

    Tk 没有 border-radius，`tk.Button` 画不出圆角，只能自己画一块垫在下面。
    ``bg`` 是父容器的底色 —— 角外那几像素要跟它一致，才看不出这块是贴上去的。
    """
    s = _SUPERSAMPLE
    mask = Image.new("L", (w * s, h * s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, w * s - 1, h * s - 1), radius=radius * s, fill=255)
    mask = mask.resize((w, h), Image.LANCZOS).point(
        lambda v: 255 if v >= 128 else 0)

    out = Image.new("RGB", (w, h), bg)
    out.paste(Image.new("RGB", (w, h), fill), (0, 0), mask)
    if outline:
        ring = Image.new("L", (w * s, h * s), 0)
        d = ImageDraw.Draw(ring)
        d.rounded_rectangle((0, 0, w * s - 1, h * s - 1), radius=radius * s,
                            fill=255)
        d.rounded_rectangle((s, s, (w - 1) * s - 1, (h - 1) * s - 1),
                            radius=max(0, radius - 1) * s, fill=0)
        ring = ring.resize((w, h), Image.LANCZOS).point(
            lambda v: 255 if v >= 128 else 0)
        out.paste(Image.new("RGB", (w, h), outline), (0, 0), ring)
    return ImageTk.PhotoImage(out)


def rounded_paper(w: int, h: int, band_h: int = 0, rule_y: int = None,
                  corner: int = CORNER_R, paper: str = None, band: str = None,
                  fold: int = 0, shadow: bool = True, edge: int = EDGE_W):
    """生成窗口的底图：一张圆角纸 + 一条描边 + 右下那条影子。

    ``w``/``h`` 是**纸**的尺寸；返回的图比它大一圈（右下各让出影子的位置），
    所以窗口尺寸要用 ``frameless.outer(w, h)``。

    **描边和影子都是「边界」这件必需品，不是装饰。** 无边框之后系统那条标题栏
    没了，两张同色的纸叠在一起就完全看不出边界（编辑框和到点弹窗浮在便签本上
    时最明显）。描边负责"这条线在哪"，影子负责"谁在上面"。

    为什么要整张生成图片、而不是拿 Frame 拼：

    * 色带的**上面两个角必须跟着纸一起圆**。Frame 是直角的，盖上去就把圆角
      填平了，所以色带不能是个 Frame，只能画进底图。
    * 角外那几像素要透明，靠窗口的 ``-transparentcolor``。

    ``-transparentcolor`` 只有 1 位透明（要么全透要么全不透），所以抗锯齿的
    中间色会变成一圈洋红描边 —— 只能先 4 倍超采样画出覆盖率，再按 50%
    阈值二值化取轮廓；描边和影子同理。放大到 8 倍能看到阶梯，正常尺寸看不出来。

    全程走 PIL 的遮罩合成：逐像素 Python 循环在 820x560 上要一两秒，
    而这个窗口每次换配色都要重建一次，扛不住。

    不做缓存：``ImageTk.PhotoImage`` 是绑在具体那个 Tk 解释器上的，
    进程里换过 root 之后复用会炸（验证脚本就会连开两个 App）。
    一次生成只有几毫秒，不值得为它冒这个险。

    ``paper`` / ``band`` 可以换整张纸的底色，``fold`` 加右上角折角
    （到点弹窗那张「从便签本上撕下来的纸」就是靠这两个参数做出来的）。
    """
    paper = paper or PAPER
    band = band or PAPER_DEEP
    s = _SUPERSAMPLE
    ow, oh = w + SHADOW_DX, h + SHADOW_DY      # 整图尺寸

    def mask(paint):
        """4 倍超采样画一张遮罩，再按覆盖率阈值二值化。"""
        big = Image.new("L", (ow * s, oh * s), 0)
        paint(ImageDraw.Draw(big), s)
        return big.resize((ow, oh), Image.LANCZOS).point(
            lambda v: 255 if v >= 128 else 0)

    def rrect(x0, y0, x1, y1, radius, fill=255):
        """往超大图上画一个圆角矩形（坐标是 1 倍图的坐标，k 是放大倍数）。"""
        def paint(d, k):
            d.rounded_rectangle((x0 * k, y0 * k, (x1 + 1) * k - 1, (y1 + 1) * k - 1),
                                radius=radius * k, fill=fill)
        return paint

    out = Image.new("RGB", (ow, oh), MAGIC)
    if shadow:
        out.paste(Image.new("RGB", (ow, oh), SHADOW), (0, 0),
                  mask(rrect(SHADOW_DX, SHADOW_DY, ow - 1, oh - 1, corner)))

    body = Image.new("RGB", (ow, oh), paper)
    d = ImageDraw.Draw(body)
    if band_h > 0:
        # 色带整条画满就行：圆角那两处会被下面的遮罩切掉
        d.rectangle((0, 0, w - 1, band_h - 1), fill=band)
    if rule_y is not None:
        d.rectangle((0, rule_y, w - 1, rule_y), fill=RULE)
    if fold > 0:
        d.polygon([(w - fold, 0), (w - 1, 0), (w - 1, fold)], fill=STICKY_FOLD)

    out.paste(body, (0, 0), mask(rrect(0, 0, w - 1, h - 1, corner)))

    if edge:
        def ring(dr, k):
            rrect(0, 0, w - 1, h - 1, corner)(dr, k)
            # 把里面抠掉，剩下的就是那一圈描边
            rrect(edge, edge, w - 1 - edge, h - 1 - edge,
                  max(0, corner - edge), fill=0)(dr, k)
        out.paste(Image.new("RGB", (ow, oh), EDGE), (0, 0), mask(ring))

    return ImageTk.PhotoImage(out)


def note_glyph(canvas, size: int = 24, x: int = 0, y: int = 0) -> None:
    """在 canvas 上按托盘图标的比例画一张便签纸。

    和 tray.make_icon_image 用同一套形状与颜色 —— 窗口里的身份标记必须
    和托盘里那颗图标是同一张纸。tk.Canvas 没有圆角矩形，但图标那个圆角
    半径只有 size//10（24 像素下约 2 像素），直角看不出来。
    """
    pad = max(1, size // 8)
    fold = size // 4
    canvas.create_rectangle(x + pad, y + pad, x + size - pad, y + size - pad,
                            fill=STICKY, outline=STICKY_EDGE)
    corner = size - pad
    canvas.create_polygon(x + corner - fold, y + pad,
                          x + corner, y + pad,
                          x + corner, y + pad + fold,
                          fill=STICKY_FOLD, outline="")
    x0, x1 = pad + size // 10, size - pad - size // 10
    for i, ratio in enumerate(PEN_LINE_RATIOS):
        yy = int(y + pad + (size - 2 * pad) * ratio)
        short = x1 - size // 8 if i == len(PEN_LINE_RATIOS) - 1 else x1
        canvas.create_line(x + x0, yy, x + short, yy, fill=STICKY_EDGE)
