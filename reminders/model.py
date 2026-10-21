"""便签数据结构与时间计算。纯逻辑，不依赖 tkinter / pystray / 文件系统。

核心设计：单次、每天、倒计时三种便签统一归结为一个绝对时间点 next_fire_at，
使触发判定只有一套逻辑。daily 只是"弹完之后把时间点往后滚一天"。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

DT_FMT = "%Y-%m-%dT%H:%M:%S"
SNOOZE_MINUTES = 10

_DATE_RE = re.compile(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})")
_TIME_RE = re.compile(r"(\d{1,2})\D+(\d{1,2})")

WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")


def _hhmm_time(text: str) -> time:
    h, m = (int(x) for x in text.split(":"))
    return time(h, m)


def fmt_dt(value: datetime | None) -> str | None:
    return value.strftime(DT_FMT) if value else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, DT_FMT)
    except (ValueError, TypeError):
        return None


def _repeat_mode_from(d: dict) -> str:
    """读盘时取重复模式。只认显式写下的值，其余一律退回「按星期」。

    **不做「勾了一~五 就当成工作日」的猜测**（2026-09-23 用户裁决撤销）。
    to_dict 永远写 repeat_mode，所以猜法根本分不出「老文件里的默认值」和
    「用户刚在界面上明确选的 按星期 + 一~五」—— 结果是用户的选择被一次重启
    静默改掉：列表文案从「周一至周五」变「工作日」，弹窗规则也跟着换成法定
    节假日。为迁移旧数据而让新模式有这个陷阱不划算。
    """
    mode = d.get("repeat_mode")
    return mode if mode in ("date_range", "workdays") else "weekdays"


@dataclass
class Reminder:
    text: str
    kind: str
    next_fire_at: datetime
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    time_of_day: str = ""
    enabled: bool = True
    done: bool = False
    last_fired_at: datetime | None = None
    snooze_until: datetime | None = None
    done_at: datetime | None = None      # 什么时候标记完成的；排序不用它，见 main_window.sort_key
    # 以下字段仅 kind == "interval"（循环）用；weekdays 里 0=周一 … 6=周日
    weekdays: list[int] = field(default_factory=list)
    # "weekdays" 按星期 | "workdays" 真实工作日（跟随法定节假日）| "date_range" 按日期区间
    # workdays 模式下 weekdays 只写不读 —— 判断不看它，留着是为了切回按星期时有预设
    repeat_mode: str = "weekdays"
    # 循环的计时方式：
    #   "fixed"   —— 从时段起点按固定格子排（9:00 起的时段：10:00、11:00…，
    #                起点本身不弹，见 first_slot_time）。格子永不动，用户处不处理
    #                都不改变节奏。
    #   "rolling" —— **「处理后计时」**：从"处理这一格"的时刻起算间隔
    #                （14:00 弹、14:05 点「知道了」→ 下次 15:05）。
    #                没被处理的格子按**触发时刻**继续往前推（14:00 弹、没人理 →
    #                15:00 照弹，旧弹窗被新的顶掉、重新置顶），所以弹窗被压在别的
    #                窗口后面没看见也不会让这条循环哑掉 —— 2026-09-24 那次翻车就是
    #                "没人处理就一直停着"造成的，当天再无提醒。
    #                2026-09-29 用户裁决：处理 = 弹窗上「知道了」或「关闭」；
    #                便签本的「标记已读」**不算**（那是事后清列表，见 acknowledge）。
    interval_mode: str = "fixed"
    # 这条便签是由哪条循环便签刷出来的（循环开着「留记录」时每弹一次窗补一条）。
    # 列表里同一个 parent_id 的记录会收成一个可展开的条目，免得一天十几条淹掉列表。
    # 空 = 不是记录、不参与折叠。源便签被删掉后记录就失去归属，散开平铺。
    parent_id: str = ""
    date_from: str = ""                # "YYYY-MM-DD"，按日期区间模式用；与 weekdays 互斥
    date_to: str = ""
    window_start: str = ""
    window_end: str = ""
    interval_minutes: int = 60
    include_end: bool = True
    log_to_list: bool = False          # 循环：每次触发是否往便签本补一条记录

    def planned_time(self) -> datetime:
        """本次实际该弹窗的时刻。稍后提醒优先于原计划。"""
        return self.snooze_until or self.next_fire_at

    def should_fire(self, now: datetime) -> bool:
        if not self.enabled or self.done:
            return False
        if self.is_expired(now):      # 循环的日期区间已过，不再触发
            return False
        planned = self.planned_time()
        if now < planned:
            return False
        # last_fired_at 为 None 必须单独判断：Python 中 None < datetime 会抛 TypeError
        return self.last_fired_at is None or self.last_fired_at < planned

    def is_missed(self, now: datetime) -> bool:
        """单次便签已过点且未完成。仅用于主窗口标红，daily 过期不算错过。"""
        return (self.kind == "once" and self.enabled
                and not self.done and now > self.next_fire_at)

    def status_text(self, now: datetime) -> str:
        if not self.enabled:
            return "已暂停"
        if self.kind == "once" and self.done:
            return "已完成"
        if self.is_expired(now):
            return "已结束"
        if self.is_missed(now):
            return "已错过"
        return "待提醒"

    def display_time(self) -> str:
        if self.kind == "daily":
            return f"每天 {self.time_of_day}"
        if self.kind == "interval":
            if self.repeat_mode == "date_range":
                label = f"{self.date_from[5:]}~{self.date_to[5:]}"
            elif self.repeat_mode == "workdays":
                label = "工作日"
            else:
                days = sorted(set(self.weekdays))
                if days == [0, 1, 2, 3, 4]:
                    # 这里以前写的是「工作日」—— 但它只是周一到周五，不含法定节假日。
                    # 真正的「工作日」现在是 workdays 模式，所以文案让位。
                    label = "周一至周五"
                elif len(days) == 7:
                    label = "每天"
                else:
                    label = "周" + "".join(WEEKDAY_LABELS[d] for d in days)
            tail = "" if self.include_end else " 不含结束"
            rolling = "·处理后计时" if self.interval_mode == "rolling" else ""
            return (f"{label} {self.window_start}-{self.window_end} "
                    f"每{self.interval_minutes}分{rolling}{tail}")
        return self.next_fire_at.strftime("%Y-%m-%d %H:%M")

    def mark_fired(self, now: datetime) -> None:
        """tick 判定该弹窗时调用。只记"已弹过"，不代表用户已处理，故不设 done。"""
        self.last_fired_at = now
        self.snooze_until = None
        if self.kind in ("daily", "interval"):
            self.roll_forward(now)

    def roll_forward(self, now: datetime) -> None:
        """弹过之后，算出下一次弹窗时间。

        两种计时方式都从**原定时刻**（next_fire_at）往后推一格：

        - fixed：格子由时段起点决定，处理不改变节奏。
        - rolling：没人处理时按原定时刻继续往前推，所以**不断线**；用户处理了则
          由 handled() 从处理时刻重新起算（那时算出来的只会更晚）。

        锚点用 next_fire_at 而不是 now（2026-09-29 改）：now 是 tick 命中的那一拍，
        总比原定时刻晚一点点，逐格累积会把相位一路拖走（实测 10:00:00 → 11:00:01
        → 12:00:01 → 13:00:02）。跨过好几格（休眠、暂停）时 seek_next_slot 会一路
        跳到 now 之后，所以这里只补一格、不会追着补弹一串。
        """
        if self.kind == "daily":
            t = _hhmm_time(self.time_of_day)
            candidate = self.next_fire_at.replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0)
            while candidate <= now:
                candidate += timedelta(days=1)
            self.next_fire_at = candidate
        elif self.kind == "interval":
            self.next_fire_at = self.seek_next_slot(
                self.next_fire_at + self.interval_delta(), now)

    def interval_delta(self) -> timedelta:
        return timedelta(minutes=max(1, self.interval_minutes))

    def window_bounds(self) -> tuple[time, time]:
        """返回时段的 (开始, 结束)。"""
        return _hhmm_time(self.window_start), _hhmm_time(self.window_end)

    def first_slot_time(self) -> time:
        """一天里的第一格：**时段起点本身不算一格**（2026-09-24 用户裁决）。

        「09:00-18:00 每 60 分」的第一声是 **10:00**，不是 09:00 —— 时段起点只当
        锚点，"从时段开始记录、过一个间隔才响第一声"。固定时刻的格子、顺延到次日、
        处理后计时跨天，全都从这一刻起算，所以两种计时方式是同一套规则：
        **锚点 + 一个间隔**（固定时刻的锚=时段起点，处理后计时的锚=新建/上次处理那一刻）。

        时段比间隔还短（或加一个间隔会跨过午夜）时退回时段起点 —— 那种配置下
        第一格根本不在时段里，退回去总比让这条提醒静默地永远等不到要强。
        """
        start_t, end_t = self.window_bounds()
        base = datetime.combine(date.min, start_t)
        first = base + self.interval_delta()
        if first.date() != base.date() or first.time() > end_t:
            return start_t
        return first.time()

    def day_allowed(self, day: date) -> bool:
        """这一天该不该弹窗：按星期看 weekday，按真实工作日看节假日数据，按日期区间看区间。

        三种模式互斥 —— date_range 完全不看 weekdays，workdays 也完全不看它。
        """
        if self.repeat_mode == "date_range":
            if not self.date_from or not self.date_to:
                return False
            key = day.strftime("%Y-%m-%d")
            return self.date_from <= key <= self.date_to
        if self.repeat_mode == "workdays":
            # 函数内导入：store 依赖 model，model 若在顶层导入 holidays 就会成环
            # （model → holidays → store → model），在 class 定义完之前炸掉。
            from . import holidays
            return holidays.is_workday(day)
        return day.weekday() in set(self.weekdays)

    def is_expired(self, now: datetime) -> bool:
        """日期区间模式的区间已经过去，不会再有下一次触发。

        区间最后一天还要看时段：过了时段结束时刻就算结束，
        否则 18:00 弹完最后一格还会在列表里显示"待提醒"到第二天。
        """
        if self.kind != "interval" or self.repeat_mode != "date_range":
            return False
        if not self.date_to:
            return False
        today = now.strftime("%Y-%m-%d")
        if today > self.date_to:
            return True
        if today == self.date_to:
            _, end_t = self.window_bounds()
            return now.time() > end_t
        return False

    def seek_next_slot(self, candidate: datetime, now: datetime) -> datetime:
        """从 candidate 起，找第一个晚于 now、且落在允许日期与时段内的触发时刻。

        落在窗口外（当天不允许、早于时段、晚于时段）就跳到**下一天的第一格**重找
        —— 第一格是"时段起点 + 一个间隔"，不是时段起点，见 first_slot_time。
        """
        step = self.interval_delta()
        start_t, end_t = self.window_bounds()
        first = self.first_slot_time()
        for _ in range(2000):        # 上限防死循环，足以跨过数周
            day = candidate.date()
            if not self.day_allowed(day):
                candidate = datetime.combine(day + timedelta(days=1), first)
                continue
            t = candidate.time()
            if t < start_t:
                candidate = datetime.combine(day, first)
                continue
            if t > end_t or (t == end_t and not self.include_end):
                candidate = datetime.combine(day + timedelta(days=1), first)
                continue
            if candidate <= now:
                candidate += step
                continue
            return candidate
        return candidate

    def snooze(self, now: datetime, minutes: int = SNOOZE_MINUTES) -> None:
        self.snooze_until = now + timedelta(minutes=minutes)

    def acknowledge(self, now: datetime | None = None) -> None:
        """标记已处理。完成时刻记在 done_at 里。

        done_at 不再参与排序 —— 列表一律按计划时间排（见 main_window.sort_key），
        因为批量「标记已读」时各条的完成时刻几乎相同，拿它排序会随重启变化。

        注意 last_fired_at 不是完成时间：它是"弹窗弹出过"的时刻，
        用户可能过很久才点「知道了」。

        **这里不碰排期**：它只有"标记已读"这一个含义，弹窗上的「知道了」和便签本
        里的「标记已读」走的都是它。循环便签真正的重排发生在**弹窗**那条路径上 ——
        弹窗紧接着还会调 handled()（2026-09-29 裁决）。所以单独调这个函数对循环
        便签是空操作：便签本里"标记已读"不会把下一格往后推。
        """
        now = now or datetime.now()
        if self.kind == "once":
            self.done = True
            self.done_at = now
        self.snooze_until = None

    def handled(self, now: datetime) -> None:
        """弹窗上按了「知道了」或「关闭」—— 用户确实处理了这一格。

        **只有 rolling（「处理后计时」）会因此重排**：下一次 = 处理时刻 + 间隔。
        别的类型什么都不做：

        - fixed 的格子由时段起点决定，处理改变不了它；
        - 单次 / 每天没有"按处理时刻算下一格"这回事；
        - 单次便签上「关闭」**仍然 ≠ 已处理**（不置 done、列表里照旧标红）——
          这里只管循环的重排，别把它当 acknowledge 用。

        取 max(…, next_fire_at) 纯属防御：正常路径上处理时刻必然晚于触发时刻，
        算出来的格子只会更晚，但时钟回拨或旧数据不该把排期往回拨。
        """
        if self.kind != "interval" or self.interval_mode != "rolling":
            return
        candidate = max(now + self.interval_delta(), self.next_fire_at)
        self.next_fire_at = self.seek_next_slot(candidate, now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "next_fire_at": fmt_dt(self.next_fire_at),
            "time_of_day": self.time_of_day,
            "enabled": self.enabled,
            "done": self.done,
            "last_fired_at": fmt_dt(self.last_fired_at),
            "snooze_until": fmt_dt(self.snooze_until),
            "done_at": fmt_dt(self.done_at),
            "weekdays": list(self.weekdays),
            "repeat_mode": self.repeat_mode,
            "interval_mode": self.interval_mode,
            "parent_id": self.parent_id,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "interval_minutes": self.interval_minutes,
            "include_end": self.include_end,
            "log_to_list": self.log_to_list,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Reminder":
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:8]),
            text=str(d.get("text", "")),
            kind=d.get("kind", "once"),
            next_fire_at=parse_dt(d.get("next_fire_at")) or datetime.now(),
            time_of_day=str(d.get("time_of_day", "")),
            enabled=bool(d.get("enabled", True)),
            done=bool(d.get("done", False)),
            last_fired_at=parse_dt(d.get("last_fired_at")),
            snooze_until=parse_dt(d.get("snooze_until")),
            done_at=parse_dt(d.get("done_at")),
            weekdays=[int(x) for x in d.get("weekdays", [])
                      if isinstance(x, int) and 0 <= int(x) <= 6],
            repeat_mode=_repeat_mode_from(d),
            interval_mode=("rolling" if d.get("interval_mode") == "rolling"
                           else "fixed"),
            parent_id=str(d.get("parent_id", "")),
            date_from=str(d.get("date_from", "")),
            date_to=str(d.get("date_to", "")),
            window_start=str(d.get("window_start", "")),
            window_end=str(d.get("window_end", "")),
            interval_minutes=int(d.get("interval_minutes", 60) or 60),
            include_end=bool(d.get("include_end", True)),
            log_to_list=bool(d.get("log_to_list", False)),
        )


def make_once(text: str, fire_at: datetime) -> Reminder:
    return Reminder(text=text, kind="once", next_fire_at=fire_at)


def make_countdown(text: str, minutes: int, now: datetime) -> Reminder:
    """倒计时不是一种 kind，直接换算成绝对时间点的单次。"""
    return make_once(text, now + timedelta(minutes=minutes))


def make_daily(text: str, time_of_day: str, now: datetime) -> Reminder:
    hh, mm = (int(x) for x in time_of_day.split(":"))
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return Reminder(text=text, kind="daily",
                    next_fire_at=candidate, time_of_day=time_of_day)


def normalize_on_startup(items, now: datetime) -> None:
    """启动时调用一次：把各路便签的时间点收拾到"现在"这个基准上。

    核心是**程序没运行期间错过的，不补弹**：

    - daily：过期就往后滚，滚到未来为止。
    - fixed 的 interval：从"今天的第一格"（时段起点 + 一个间隔）重找 —— 一律
      重算，免得关机数天后还在按老格子逐格推进；也顺带把时段起点那格排掉。
    - rolling 的 interval：还没到点的原样保留，接着走（不能拉回格子 —— 那会把它
      "按处理时刻计时"的节奏抹掉）；已经过点的沿**自己原来的格子**往前推到未来
      第一格，同一天就接着自己那一格（存 12:10、12:30 启动 → 13:10），隔了一天
      则回到今天的「时段起点 + 一个间隔」（→ 10:00）。两种都**不补弹**。
    - once：过期又没处理的，把 last_fired_at 补上让它**不再触发**。以前漏了这
      一条，攒了一晚上的错过提醒会在启动后挨个弹一遍。列表里的「已错过」标红
      看的是 next_fire_at 和 done，不受影响，照样红着。
    """
    for r in items:
        if r.kind == "daily" and r.next_fire_at <= now:
            r.roll_forward(now)
        elif r.kind == "interval":
            try:
                first = r.first_slot_time()
            except (ValueError, AttributeError):
                continue
            if r.interval_mode == "rolling":
                if r.next_fire_at > now:
                    continue                    # 还没到点，保留原定时刻
                if r.next_fire_at.date() == now.date():
                    # 同一天已过点：沿自己原来的格子往前推（存 12:10、12:30 启动 →
                    # 13:10）。**不补弹** —— 应用刚起来就糊一张弹窗很突兀。
                    r.next_fire_at = r.seek_next_slot(
                        r.next_fire_at + r.interval_delta(), now)
                else:
                    # 存的下一次不是今天的（关机过夜/几天没开）：回到今天的
                    # 「时段起点 + 一个间隔」。按旧格子推会推出白天里一个零碎
                    # 时刻（10:10 而不是 10:00），不如从今天的起点重新算干净。
                    # 2026-09-29 之前的实现是"从现在顺延一个间隔"，相位被**启动
                    # 时刻**劫持（用户报的"循环时间会因为重启而变"就是这个）。
                    r.next_fire_at = r.seek_next_slot(
                        datetime.combine(now.date(), first), now)
            else:
                r.next_fire_at = r.seek_next_slot(
                    datetime.combine(now.date(), first), now)
        elif r.kind == "once" and not r.done and r.next_fire_at <= now:
            r.last_fired_at = now


def make_interval(text: str, weekdays, window_start: str, window_end: str,
                  interval_minutes: int, include_end: bool,
                  now: datetime, repeat_mode: str = "weekdays",
                  date_from: str = "", date_to: str = "",
                  log_to_list: bool = False,
                  interval_mode: str = "fixed") -> Reminder:
    """循环提醒：在允许的日期与时段内，每隔 N 分钟提醒一次。

    repeat_mode="weekdays" 看 weekdays（0=周一 … 6=周日）；
    repeat_mode="workdays" 看国家法定节假日（含调休），此时 weekdays 不参与；
    repeat_mode="date_range" 看 date_from ~ date_to 这个区间。三者互斥。
    log_to_list=True 时，每次触发会往便签本补一条记录（由 App 负责写入）。
    interval_mode="rolling" 时第一次也不立即弹，从现在起算一个间隔 ——
    用户要的是"从我开始计时的"节奏，设完就被弹一下会很突兀。之后的每一格由
    **处理**决定（弹窗上点「知道了」/「关闭」→ 那一刻 + 间隔，见 handled）。
    """
    r = Reminder(
        text=text, kind="interval", next_fire_at=now,
        weekdays=sorted({int(d) for d in weekdays if 0 <= int(d) <= 6}),
        repeat_mode=(repeat_mode if repeat_mode in ("date_range", "workdays")
                     else "weekdays"),
        interval_mode=("rolling" if interval_mode == "rolling" else "fixed"),
        date_from=str(date_from), date_to=str(date_to),
        window_start=window_start, window_end=window_end,
        interval_minutes=max(1, int(interval_minutes)),
        include_end=bool(include_end),
        log_to_list=bool(log_to_list),
    )
    if r.interval_mode == "rolling":
        r.next_fire_at = r.seek_next_slot(now + r.interval_delta(), now)
    else:
        r.next_fire_at = r.seek_next_slot(
            datetime.combine(now.date(), r.first_slot_time()), now)
    return r


def make_log_entry(source: Reminder, now: datetime) -> Reminder:
    """给 source 这条循环补一条"这一格处理过了"的记录。

    触发时（`app._fire_popup` → `_log_fired`）和手动点「已处理」（编辑对话框）
    补的都是它，所以**同形**：同文本、parent_id 指向源便签（列表里收成一个
    可展开的组）、直接标完成。标完成是必须的 —— 记录条目的时间点已经过去，
    不标就会被判定为「已错过」而标红，看起来像出了问题。

    只造对象：不碰 source、不入列表、不落盘，那些由调用方（App）负责。
    """
    entry = make_once(source.text, now)
    entry.parent_id = source.id
    entry.acknowledge(now)          # 标完成并记下完成时刻
    entry.last_fired_at = now
    return entry


# ---- 用户输入解析：宽进严出，别让用户操心格式 ----

def parse_date_text(text: str) -> date | None:
    """宽松解析用户随手输入的日期，认不出返回 None。

    接受 2026-09-15 / 2026/9/5 / 2026.9.15 / 20260915 / 2026年9月15日。
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    m = _DATE_RE.search(t)
    if m:
        y, mo, d = (int(g) for g in m.groups())
    else:
        digits = "".join(c for c in t if c.isdigit())
        if len(digits) != 8:
            return None
        y, mo, d = int(digits[:4]), int(digits[4:6]), int(digits[6:])
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_time_text(text: str) -> tuple[int, int] | None:
    """宽松解析用户随手输入的时间，返回 (时, 分)，认不出返回 None。

    接受 14:30 / 1430 / 14.30 / 14时30分 / 930（=09:30）/ 9（=09:00）。
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    m = _TIME_RE.search(t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        digits = "".join(c for c in t if c.isdigit())
        if len(digits) == 4:
            h, mi = int(digits[:2]), int(digits[2:])
        elif len(digits) == 3:
            h, mi = int(digits[0]), int(digits[1:])
        elif len(digits) in (1, 2):
            h, mi = int(digits), 0
        else:
            return None
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return h, mi
    return None


def normalize_date_text(text: str) -> str | None:
    """把用户输入写成标准 YYYY-MM-DD；认不出返回 None（调用方保持原样）。"""
    d = parse_date_text(text)
    return d.strftime("%Y-%m-%d") if d else None


def normalize_time_text(text: str) -> str | None:
    """把用户输入写成标准 HH:MM；认不出返回 None。"""
    hm = parse_time_text(text)
    return f"{hm[0]:02d}:{hm[1]:02d}" if hm else None
