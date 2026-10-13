# 便签提醒小工具（RemindNotes）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个常驻 Windows 托盘的便签提醒工具，写下备忘并设定时间，到点弹普通窗口提醒，程序未运行期间错过的在列表中标红。

**Architecture:** 主线程跑 tkinter 主循环（隐藏 root），pystray 托盘图标跑在 daemon 线程；托盘线程的一切界面动作经 `root.after(0, fn)` 调度回主线程。定时用 `root.after(1000, tick)` 在主线程内做，无需加锁。所有便签（单次/每天/倒计时）统一归结为一个绝对时间点 `next_fire_at`，触发判定只有一套逻辑。

**Tech Stack:** Python 3.14.6（标准库 tkinter/json/dataclasses/ctypes/datetime/uuid）、pystray 0.19.5（已装）、Pillow 12.3.0（已装）

**Spec:** `D:\Tools\RemindNotes\docs\superpowers\specs\2026-09-15-remind-notes-design.md`

## Global Constraints

- 项目根目录：`D:\Tools\RemindNotes\`
- **禁止执行任何 git 命令**（不 init、不 add、不 commit、不 push）。本机约定，用户明确要求。计划中原属"提交"的步骤一律跳过。
- **不引入 spec 之外的第三方依赖**。除 pystray / Pillow 外全部用标准库。测试不依赖 pytest。
- 测试运行方式固定为 `python tests/test_model.py`（直跑，非 pytest）。
- 所有时间均为 **naive datetime（本机本地时间）**，不引入时区、不用 `datetime.now(tz)`。序列化格式固定 `"%Y-%m-%dT%H:%M:%S"`。
- 源码文件一律 **UTF-8 无 BOM**。用 Write/Edit 工具写文件，不要用 PowerShell 的 `Set-Content` / `Out-File -Encoding utf8`（会产生 BOM，导致解释器报非法字符）。
- 弹窗**不置顶**（不设 `-topmost`）、**无提示音**、**不闪烁**。这是用户明确确认的取舍，不要"顺手优化"。
- 托盘图标用 Pillow 程序内绘制，不引入 `.ico` 资源文件。
- 便签数据固定存 `%APPDATA%\RemindNotes\reminders.json`，与代码目录分离。

## 与 spec 的一处修正（实施时以本计划为准）

spec 第 5 节"弹过之后 once → done = True"**有缺陷**，会让「稍后 10 分钟」失效。本计划采用的规则：

| 时机 | 动作 |
| --- | --- |
| tick 判定该弹窗 | `last_fired_at = now`；`snooze_until = None`；`daily` 立即 `roll_forward(now)`；**`once` 不设 `done`** |
| 弹窗「知道了」 | `once` 设 `done = True`；`daily` 无需操作（tick 时已滚）；清 `snooze_until` |
| 弹窗「稍后 10 分钟」 | `snooze_until = now + 10min`（此时 `done` 仍为 `False`，到期能再弹） |
| 弹窗「关闭」 | 不做任何状态变更 |

`daily` 必须在 tick 时就滚，不能等用户点「知道了」：否则弹窗被晾着不管时，`next_fire_at` 与 `last_fired_at` 会相等，`last_fired_at < planned` 不成立，第二天不再提醒。

## 文件结构

```
D:\Tools\RemindNotes\
  run.pyw                 双击启动入口（.pyw 不弹控制台）
  reminders\
    __init__.py           空文件，标记为包
    model.py              数据结构 + 时间计算（纯逻辑，无 IO 无 UI）
    store.py              JSON 读写 + 原子替换
    scheduler.py          每秒 tick 判定（纯逻辑，弹窗走回调）
    autostart.py          开机自启注册表读写
    main_window.py        便签列表窗口
    edit_dialog.py        新建 / 编辑对话框
    popup.py              到点提醒弹窗
    tray.py               pystray 托盘图标与菜单
    app.py                装配各模块 + 启动主循环
  tests\
    test_model.py         纯逻辑测试（model + store + scheduler）
```

`model.py` / `store.py` / `scheduler.py` **不得 import tkinter 或 pystray**，保证可独立测试。

## 任务依赖

Task 1 → 2 → 3 是纯逻辑层，必须按序（3 依赖 1、2）。Task 4（autostart）独立。Task 5-8（UI）依赖 Task 1-3 的接口，彼此之间无依赖。Task 9 依赖全部。Task 10 是端到端验收。

---

### Task 1: model.py — 数据结构与时间计算

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\__init__.py`（空文件）
- Create: `D:\Tools\RemindNotes\reminders\model.py`
- Create: `D:\Tools\RemindNotes\tests\test_model.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `DT_FMT: str`、`SNOOZE_MINUTES: int = 10`
  - `fmt_dt(value: datetime | None) -> str | None`
  - `parse_dt(value: str | None) -> datetime | None`
  - `Reminder` dataclass，字段 `text, kind, next_fire_at, id, time_of_day, enabled, done, last_fired_at, snooze_until`
  - `Reminder.planned_time() -> datetime`
  - `Reminder.should_fire(now: datetime) -> bool`
  - `Reminder.is_missed(now: datetime) -> bool`
  - `Reminder.status_text(now: datetime) -> str`
  - `Reminder.display_time() -> str`
  - `Reminder.mark_fired(now) -> None`
  - `Reminder.roll_forward(now) -> None`
  - `Reminder.snooze(now, minutes=SNOOZE_MINUTES) -> None`
  - `Reminder.acknowledge() -> None`
  - `Reminder.to_dict() -> dict` / `Reminder.from_dict(d: dict) -> Reminder`
  - `make_once(text, fire_at) -> Reminder`
  - `make_countdown(text, minutes, now) -> Reminder`
  - `make_daily(text, time_of_day, now) -> Reminder`
  - `normalize_daily(items, now) -> None`

- [ ] **Step 1: 建立目录与包标记**

创建空文件 `D:\Tools\RemindNotes\reminders\__init__.py`（内容为空即可）。

- [ ] **Step 2: 写失败的测试**

创建 `D:\Tools\RemindNotes\tests\test_model.py`：

```python
"""RemindNotes 纯逻辑测试。运行：python tests/test_model.py"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reminders.model import (
    Reminder, make_once, make_countdown, make_daily,
    normalize_daily, fmt_dt, parse_dt,
)


def test_daily_today_not_yet():
    now = datetime(2026, 9, 15, 8, 0, 0)
    r = make_daily("喝水", "09:00", now)
    assert r.next_fire_at == datetime(2026, 9, 15, 9, 0, 0), r.next_fire_at


def test_daily_today_already_passed():
    now = datetime(2026, 9, 15, 10, 0, 0)
    r = make_daily("喝水", "09:00", now)
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0, 0), r.next_fire_at


def test_daily_exactly_equal_now_rolls_to_tomorrow():
    now = datetime(2026, 9, 15, 9, 0, 0)
    r = make_daily("喝水", "09:00", now)
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0, 0), r.next_fire_at


def test_countdown_conversion():
    now = datetime(2026, 9, 15, 8, 0, 0)
    r = make_countdown("歇会", 30, now)
    assert r.kind == "once"
    assert r.next_fire_at == datetime(2026, 9, 15, 8, 30, 0), r.next_fire_at


def test_should_fire_false_before_time():
    now = datetime(2026, 9, 15, 8, 0, 0)
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    assert r.should_fire(now) is False


def test_should_fire_true_at_time():
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    assert r.should_fire(datetime(2026, 9, 15, 9, 0, 0)) is True


def test_last_fired_none_does_not_raise():
    """last_fired_at 为 None 时不能抛 TypeError。"""
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    assert r.last_fired_at is None
    assert r.should_fire(datetime(2026, 9, 15, 9, 0, 1)) is True


def test_two_ticks_in_same_minute_fire_once():
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    now = datetime(2026, 9, 15, 9, 0, 0)
    assert r.should_fire(now) is True
    r.mark_fired(now)
    assert r.should_fire(datetime(2026, 9, 15, 9, 0, 1)) is False


def test_once_mark_fired_does_not_set_done():
    """tick 弹了不等于用户处理完了，"稍后 10 分钟"要能继续弹。"""
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    now = datetime(2026, 9, 15, 9, 0, 0)
    r.mark_fired(now)
    assert r.done is False, "mark_fired 不能设 done，否则 snooze 失效"


def test_snooze_fires_again_ten_minutes_later():
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    now = datetime(2026, 9, 15, 9, 0, 0)
    r.mark_fired(now)
    r.snooze(now)
    assert r.should_fire(datetime(2026, 9, 15, 9, 9, 59)) is False
    assert r.should_fire(datetime(2026, 9, 15, 9, 10, 0)) is True


def test_snooze_does_not_repeat_after_second_fire():
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    now = datetime(2026, 9, 15, 9, 0, 0)
    r.mark_fired(now)
    r.snooze(now)
    later = datetime(2026, 9, 15, 9, 10, 0)
    assert r.should_fire(later) is True
    r.mark_fired(later)
    assert r.should_fire(datetime(2026, 9, 15, 9, 10, 1)) is False


def test_snooze_takes_priority_over_next_fire_at():
    r = make_daily("喝水", "09:00", datetime(2026, 9, 15, 8, 0, 0))
    now = datetime(2026, 9, 15, 9, 0, 0)
    r.mark_fired(now)
    r.snooze(now, minutes=10)
    assert r.planned_time() == datetime(2026, 9, 15, 9, 10, 0)


def test_daily_rolls_immediately_on_mark_fired():
    """tick 弹时 daily 必须立刻滚，否则用户晾着弹窗会导致第二天不再提醒。"""
    r = make_daily("喝水", "09:00", datetime(2026, 9, 15, 8, 0, 0))
    now = datetime(2026, 9, 15, 9, 0, 0)
    r.mark_fired(now)
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0, 0), r.next_fire_at
    assert r.should_fire(datetime(2026, 9, 16, 9, 0, 0)) is True


def test_daily_snooze_across_midnight_does_not_repeat():
    """23:55 的日报点稍后 10 分钟，跨到次日 00:05，不能因此重复弹。"""
    r = make_daily("日报", "23:55", datetime(2026, 9, 15, 20, 0, 0))
    now = datetime(2026, 9, 15, 23, 55, 0)
    r.mark_fired(now)
    r.snooze(now, minutes=10)
    assert r.should_fire(datetime(2026, 9, 16, 0, 5, 0)) is True
    r.mark_fired(datetime(2026, 9, 16, 0, 5, 0))
    assert r.should_fire(datetime(2026, 9, 16, 0, 5, 1)) is False


def test_normalize_daily_after_days_offline():
    r = make_daily("喝水", "09:00", datetime(2026, 9, 8, 8, 0, 0))
    assert r.next_fire_at == datetime(2026, 9, 8, 9, 0, 0)
    normalize_daily([r], datetime(2026, 9, 15, 12, 0, 0))
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0, 0), r.next_fire_at


def test_acknowledge_completes_once_but_not_daily():
    once = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    once.acknowledge()
    assert once.done is True
    daily = make_daily("喝水", "09:00", datetime(2026, 9, 15, 8, 0, 0))
    daily.acknowledge()
    assert daily.done is False, "daily 不应被标完成"


def test_is_missed_only_for_unfinished_once():
    now = datetime(2026, 9, 15, 12, 0, 0)
    past = make_once("错过", datetime(2026, 9, 15, 9, 0, 0))
    assert past.is_missed(now) is True
    past.acknowledge()
    assert past.is_missed(now) is False
    daily = make_daily("喝水", "09:00", datetime(2026, 9, 15, 8, 0, 0))
    assert daily.is_missed(now) is False, "daily 过期不算错过"


def test_disabled_never_fires():
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    r.enabled = False
    assert r.should_fire(datetime(2026, 9, 15, 9, 0, 0)) is False


def test_serialization_roundtrip():
    r = make_daily("喝水", "09:00", datetime(2026, 9, 15, 8, 0, 0))
    r.last_fired_at = datetime(2026, 9, 15, 9, 0, 1)
    back = Reminder.from_dict(r.to_dict())
    assert back.id == r.id
    assert back.text == r.text
    assert back.kind == r.kind
    assert back.next_fire_at == r.next_fire_at
    assert back.time_of_day == r.time_of_day
    assert back.last_fired_at == r.last_fired_at
    assert back.snooze_until is None


def test_parse_dt_handles_garbage():
    assert parse_dt(None) is None
    assert parse_dt("") is None
    assert parse_dt("不是时间") is None
    assert fmt_dt(None) is None
    assert parse_dt("2026-09-15T09:00:00") == datetime(2026, 9, 15, 9, 0, 0)


def _main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: 报 `ModuleNotFoundError: No module named 'reminders.model'`，全部测试失败

- [ ] **Step 4: 实现 model.py**

创建 `D:\Tools\RemindNotes\reminders\model.py`：

```python
"""便签数据结构与时间计算。纯逻辑，不依赖 tkinter / pystray / 文件系统。

核心设计：单次、每天、倒计时三种便签统一归结为一个绝对时间点 next_fire_at，
使触发判定只有一套逻辑。daily 只是"弹完之后把时间点往后滚一天"。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DT_FMT = "%Y-%m-%dT%H:%M:%S"
SNOOZE_MINUTES = 10


def fmt_dt(value: datetime | None) -> str | None:
    return value.strftime(DT_FMT) if value else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, DT_FMT)
    except (ValueError, TypeError):
        return None


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

    def planned_time(self) -> datetime:
        """本次实际该弹窗的时刻。稍后提醒优先于原计划。"""
        return self.snooze_until or self.next_fire_at

    def should_fire(self, now: datetime) -> bool:
        if not self.enabled or self.done:
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
        if self.is_missed(now):
            return "已错过"
        return "待提醒"

    def display_time(self) -> str:
        if self.kind == "daily":
            return f"每天 {self.time_of_day}"
        return self.next_fire_at.strftime("%Y-%m-%d %H:%M")

    def mark_fired(self, now: datetime) -> None:
        """tick 判定该弹窗时调用。只记"已弹过"，不代表用户已处理，故不设 done。"""
        self.last_fired_at = now
        self.snooze_until = None
        if self.kind == "daily":
            self.roll_forward(now)

    def roll_forward(self, now: datetime) -> None:
        """把下次触发时间滚到严格晚于 now 的第一个 time_of_day 时刻。"""
        if self.kind != "daily":
            return
        hh, mm = (int(x) for x in self.time_of_day.split(":"))
        candidate = self.next_fire_at.replace(
            hour=hh, minute=mm, second=0, microsecond=0)
        while candidate <= now:
            candidate += timedelta(days=1)
        self.next_fire_at = candidate

    def snooze(self, now: datetime, minutes: int = SNOOZE_MINUTES) -> None:
        self.snooze_until = now + timedelta(minutes=minutes)

    def acknowledge(self) -> None:
        if self.kind == "once":
            self.done = True
        self.snooze_until = None

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


def normalize_daily(items, now: datetime) -> None:
    """启动时调用：程序未运行期间过期的 daily 滚到未来，不视为错过。"""
    for r in items:
        if r.kind == "daily" and r.next_fire_at <= now:
            r.roll_forward(now)
```

- [ ] **Step 5: 运行测试确认全部通过**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: 每个测试打印 `PASS`，末尾 `20/20 passed`

若有失败，先修实现再重跑，不要改测试来迁就实现。

---

### Task 2: store.py — JSON 读写与原子写入

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\store.py`
- Modify: `D:\Tools\RemindNotes\tests\test_model.py`（在文件末尾 `_main()` 之前插入新测试）

**Interfaces:**
- Consumes: `reminders.model.Reminder`（Task 1）
- Produces:
  - `DATA_DIR: str`、`DATA_PATH: str`
  - `load(path: str | None = None) -> list[Reminder]`
  - `save(items: list[Reminder], path: str | None = None) -> None`

两个函数都接受可选 `path`，便于测试时指向临时文件；正常调用不传，走 `%APPDATA%`。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_model.py` 的 `def _main():` 之前插入：

```python
def test_store_roundtrip():
    import tempfile
    from reminders import store
    tmp = os.path.join(tempfile.mkdtemp(), "r.json")
    items = [make_once("开会", datetime(2026, 9, 15, 9, 0, 0)),
             make_daily("喝水", "09:00", datetime(2026, 9, 15, 8, 0, 0))]
    store.save(items, path=tmp)
    loaded = store.load(path=tmp)
    assert len(loaded) == 2
    assert loaded[0].text == "开会"
    assert loaded[1].kind == "daily"
    assert loaded[1].next_fire_at == items[1].next_fire_at


def test_store_load_missing_file_returns_empty():
    import tempfile
    from reminders import store
    tmp = os.path.join(tempfile.mkdtemp(), "nope.json")
    assert store.load(path=tmp) == []


def test_store_corrupt_json_backed_up_and_reset():
    """JSON 坏了不能让程序起不来，要备份后返回空列表。"""
    import tempfile
    from reminders import store
    tmp = os.path.join(tempfile.mkdtemp(), "bad.json")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("{这不是合法 JSON")
    result = store.load(path=tmp)
    assert result == []
    assert os.path.exists(tmp + ".bad"), "损坏文件应被备份为 .bad"


def test_store_empty_list_roundtrip():
    import tempfile
    from reminders import store
    tmp = os.path.join(tempfile.mkdtemp(), "empty.json")
    store.save([], path=tmp)
    assert store.load(path=tmp) == []


def test_store_no_tmp_file_left_behind():
    import tempfile
    from reminders import store
    d = tempfile.mkdtemp()
    tmp = os.path.join(d, "r.json")
    store.save([make_once("x", datetime(2026, 9, 15, 9, 0, 0))], path=tmp)
    assert not os.path.exists(tmp + ".tmp"), "原子写入后不应残留 .tmp"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: 5 个 store 测试报 `No module named 'reminders.store'`，其余通过

- [ ] **Step 3: 实现 store.py**

创建 `D:\Tools\RemindNotes\reminders\store.py`：

```python
"""便签数据文件的读写。写入用临时文件 + os.replace 保证原子性。"""
from __future__ import annotations

import json
import os

from .model import Reminder

APP_DIR_NAME = "RemindNotes"
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        APP_DIR_NAME)
DATA_PATH = os.path.join(DATA_DIR, "reminders.json")
SCHEMA_VERSION = 1


def load(path: str | None = None) -> list[Reminder]:
    """读取便签。文件缺失或损坏时返回空列表，绝不抛异常。

    损坏时把原文件备份为 <path>.bad，方便事后人工抢救。
    """
    path = path or DATA_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        items = raw.get("items", [])
        if not isinstance(items, list):
            raise ValueError("items 不是列表")
        return [Reminder.from_dict(d) for d in items if isinstance(d, dict)]
    except Exception:
        try:
            os.replace(path, path + ".bad")
        except OSError:
            pass
        return []


def save(items: list[Reminder], path: str | None = None) -> None:
    """原子写入：先写 .tmp，再 os.replace 覆盖。

    断电或强杀最多丢最后一次改动，不会留下半个损坏的 JSON。
    """
    path = path or DATA_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"version": SCHEMA_VERSION,
               "items": [r.to_dict() for r in items]}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: `25/25 passed`

---

### Task 3: scheduler.py — 每秒 tick 判定

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\scheduler.py`
- Modify: `D:\Tools\RemindNotes\tests\test_model.py`（同样在 `_main()` 前插入）

**Interfaces:**
- Consumes: `reminders.model`（Task 1）
- Produces:
  - `Scheduler(items, on_fire=None)`，属性 `items`、`on_fire`、`paused`
  - `Scheduler.startup(now: datetime | None = None) -> None`
  - `Scheduler.tick(now: datetime | None = None) -> list[Reminder]`

`tick` 就地修改 `items` 里的对象状态并返回本次该弹窗的列表，同时逐个调用 `on_fire(item)`。`on_fire` 为 `None` 时只更新状态不回调。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_model.py` 的 `def _main():` 之前插入：

```python
def test_scheduler_fires_due_item():
    from reminders.scheduler import Scheduler
    fired = []
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    s = Scheduler([r], on_fire=fired.append)
    result = s.tick(datetime(2026, 9, 15, 9, 0, 0))
    assert result == [r]
    assert fired == [r]
    assert r.last_fired_at == datetime(2026, 9, 15, 9, 0, 0)


def test_scheduler_does_not_fire_twice():
    from reminders.scheduler import Scheduler
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    s = Scheduler([r])
    s.tick(datetime(2026, 9, 15, 9, 0, 0))
    assert s.tick(datetime(2026, 9, 15, 9, 0, 1)) == []


def test_scheduler_paused_fires_nothing():
    from reminders.scheduler import Scheduler
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    s = Scheduler([r])
    s.paused = True
    assert s.tick(datetime(2026, 9, 15, 9, 0, 0)) == []
    assert r.last_fired_at is None, "暂停期间不应更新记账"


def test_scheduler_resumes_and_catches_up():
    from reminders.scheduler import Scheduler
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    s = Scheduler([r])
    s.paused = True
    s.tick(datetime(2026, 9, 15, 9, 0, 0))
    s.paused = False
    assert s.tick(datetime(2026, 9, 15, 9, 5, 0)) == [r]


def test_scheduler_startup_normalizes_daily():
    from reminders.scheduler import Scheduler
    r = make_daily("喝水", "09:00", datetime(2026, 9, 8, 8, 0, 0))
    s = Scheduler([r])
    s.startup(now=datetime(2026, 9, 15, 12, 0, 0))
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0, 0)


def test_scheduler_on_fire_optional():
    from reminders.scheduler import Scheduler
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    s = Scheduler([r])
    assert s.tick(datetime(2026, 9, 15, 9, 0, 0)) == [r]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: 6 个 scheduler 测试报 `No module named 'reminders.scheduler'`，其余通过

- [ ] **Step 3: 实现 scheduler.py**

创建 `D:\Tools\RemindNotes\reminders\scheduler.py`：

```python
"""每秒 tick 的调度器。纯逻辑，不依赖 UI —— 该弹窗时通过 on_fire 回调通知调用方。"""
from __future__ import annotations

from datetime import datetime

from .model import Reminder, normalize_daily


class Scheduler:
    def __init__(self, items: list[Reminder], on_fire=None):
        self.items = items
        self.on_fire = on_fire
        self.paused = False

    def startup(self, now: datetime | None = None) -> None:
        """程序启动时调用一次：滚动程序未运行期间过期的 daily。"""
        normalize_daily(self.items, now or datetime.now())

    def tick(self, now: datetime | None = None) -> list[Reminder]:
        """判定并触发该弹窗的便签，返回本次触发的列表（供测试与日志）。

        暂停期间直接返回，不更新任何状态，因此恢复后会补弹。
        """
        now = now or datetime.now()
        if self.paused:
            return []
        fired = [item for item in self.items if item.should_fire(now)]
        for item in fired:
            item.mark_fired(now)
        for item in fired:
            if self.on_fire:
                self.on_fire(item)
        return fired
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: `31/31 passed`

---

### Task 4: autostart.py — 开机自启注册表开关

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\autostart.py`
- Modify: `D:\Tools\RemindNotes\tests\test_model.py`

**Interfaces:**
- Consumes: 无（只用标准库 `winreg` / `sys` / `os`）
- Produces:
  - `RUN_KEY: str`
  - `APP_NAME: str = "RemindNotes"`
  - `pythonw_path() -> str`
  - `script_path() -> str`
  - `is_enabled() -> bool`
  - `set_enabled(on: bool) -> None`

**关键点：** 注册表项必须写真实的 `pythonw.exe` 绝对路径。本机 `which pythonw` 返回的是 `WindowsApps\pythonw`，那是 Microsoft Store 的应用别名（0 字节 reparse point），写进自启项后开机大概率起不来。`pythonw_path()` 从 `sys.executable` 推导并做存在性校验。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_model.py` 的 `def _main():` 之前插入：

```python
def test_autostart_pythonw_path_is_real_file():
    """必须是真实存在的 pythonw.exe，不能是 WindowsApps 的别名 stub。"""
    from reminders import autostart
    p = autostart.pythonw_path()
    assert p.lower().endswith("pythonw.exe"), p
    assert os.path.exists(p), p
    assert "WindowsApps" not in p, f"不能使用 Store 别名路径: {p}"


def test_autostart_script_path_exists():
    from reminders import autostart
    assert os.path.exists(autostart.script_path()), autostart.script_path()


def test_autostart_toggle_roundtrip():
    """真实读写注册表并还原原状态，避免污染用户环境。"""
    from reminders import autostart
    original = autostart.is_enabled()
    try:
        autostart.set_enabled(True)
        assert autostart.is_enabled() is True
        autostart.set_enabled(False)
        assert autostart.is_enabled() is False
    finally:
        autostart.set_enabled(original)
    assert autostart.is_enabled() is original
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: 3 个 autostart 测试报 `No module named 'reminders.autostart'`，其余通过

- [ ] **Step 3: 实现 autostart.py**

创建 `D:\Tools\RemindNotes\reminders\autostart.py`：

```python
"""开机自启开关。写 HKCU 的 Run 项，不需要管理员权限。"""
from __future__ import annotations

import os
import sys
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "RemindNotes"


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


def _command() -> str:
    return f'"{pythonw_path()}" "{script_path()}"'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return APP_NAME in value or "run.pyw" in value
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(on: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
```

- [ ] **Step 4: 运行测试确认全部通过**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: `34/34 passed`。若 `test_autostart_pythonw_path_is_real_file` 失败并提示路径含 `WindowsApps`，说明 `sys.executable` 推导有问题，修正 `pythonw_path()` 直到通过 —— **不要放宽断言**。

- [ ] **Step 5: 确认真实 pythonw 路径**

Run: `python -c "import sys; print(sys.executable)"`
Expected: 类似 `C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe`（若这里打印的是 WindowsApps 路径，说明当前 shell 用的是别名，用完整路径 `C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe` 重跑测试）

---

### Task 5: main_window.py — 便签列表主窗口

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\main_window.py`
- Create: `D:\Tools\RemindNotes\_check_main_window.py`（临时验证脚本，验证完删除）

**Interfaces:**
- Consumes: `reminders.model.Reminder`（Task 1）、`reminders.edit_dialog.open_editor`（Task 6，本任务先用一个桩函数占位，Task 6 完成后换掉）
- Produces:
  - `MainWindow(root, items, on_changed)`
  - `MainWindow.show() -> None`
  - `MainWindow.refresh() -> None`

`on_changed` 是无参回调，在任何数据变更后被调用（用于保存到磁盘、刷新托盘）。关闭窗口 = `withdraw()` 隐藏，不退出程序。

**本任务为 UI，无自动化测试兜底，验证方式是在 Step 4 跑一个临时脚本肉眼确认。** 先写一个桩 `open_editor` 避免依赖 Task 6：在本文件内定义 `from .edit_dialog import open_editor` 的 try/except 回退。Task 6 完成后此回退自然失效。

实际上为保持简单：**本任务直接 import `reminders.edit_dialog`，因此先做 Task 6 更顺**。但两者互相独立，为让本任务能单独验证，Step 3 会同时创建一个最小可用的 `edit_dialog.py` 骨架，Task 6 再把它补全。

- [ ] **Step 1: 先建立 edit_dialog 的最小骨架**

创建 `D:\Tools\RemindNotes\reminders\edit_dialog.py`（此骨架在 Task 6 会被完整替换）：

```python
"""新建 / 编辑便签对话框。"""
from __future__ import annotations


def open_editor(parent, reminder=None, now=None):
    """打开编辑对话框，返回新建或修改后的 Reminder；用户取消时返回 None。

    Task 6 实现，此处仅为让主窗口可独立验证的占位。
    """
    raise NotImplementedError("Task 6 实现")
```

- [ ] **Step 2: 实现 main_window.py**

创建 `D:\Tools\RemindNotes\reminders\main_window.py`：

```python
"""便签列表主窗口。关闭窗口只是隐藏，程序继续在托盘运行。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from . import edit_dialog

COLUMNS = (("text", "内容", 260), ("time", "时间", 150),
           ("kind", "类型", 70), ("status", "状态", 80))
KIND_LABEL = {"once": "单次", "daily": "每天"}


class MainWindow:
    def __init__(self, root: tk.Tk, items: list, on_changed):
        self.root = root
        self.items = items
        self.on_changed = on_changed
        self.win: tk.Toplevel | None = None
        self.tree: ttk.Treeview | None = None

    def show(self) -> None:
        if self.win is None or not self.win.winfo_exists():
            self._build()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.refresh()

    def _build(self) -> None:
        self.win = tk.Toplevel(self.root)
        self.win.title("便签本")
        self.win.geometry("620x420")
        self.win.protocol("WM_DELETE_WINDOW", self.win.withdraw)

        self.tree = ttk.Treeview(self.win, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="browse")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.tag_configure("missed", foreground="#c0392b")
        self.tree.tag_configure("done", foreground="#999999")
        self.tree.tag_configure("paused", foreground="#999999")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.tree.bind("<Double-1>", lambda e: self._edit())

        bar = tk.Frame(self.win)
        bar.pack(fill="x", padx=8, pady=8)
        for text, cmd in (("新建", self._new), ("编辑", self._edit),
                          ("删除", self._delete), ("标记完成", self._complete)):
            tk.Button(bar, text=text, width=10, command=cmd).pack(side="left", padx=2)

    def refresh(self) -> None:
        if self.tree is None or not self.tree.winfo_exists():
            return
        self.tree.delete(*self.tree.get_children())
        now = datetime.now()
        for item in self.items:
            tag = ""
            if not item.enabled:
                tag = "paused"
            elif item.kind == "once" and item.done:
                tag = "done"
            elif item.is_missed(now):
                tag = "missed"
            self.tree.insert("", "end", iid=item.id, tags=(tag,) if tag else (),
                             values=(item.text, item.display_time(),
                                     KIND_LABEL.get(item.kind, item.kind),
                                     item.status_text(now)))

    def _selected(self):
        if self.tree is None:
            return None
        sel = self.tree.selection()
        if not sel:
            return None
        target = sel[0]
        return next((i for i in self.items if i.id == target), None)

    def _new(self) -> None:
        result = edit_dialog.open_editor(self.win)
        if result is not None:
            self.items.append(result)
            self.on_changed()
            self.refresh()

    def _edit(self) -> None:
        item = self._selected()
        if item is None:
            messagebox.showinfo("提示", "请先选中一条便签", parent=self.win)
            return
        result = edit_dialog.open_editor(self.win, reminder=item)
        if result is not None:
            self.on_changed()
            self.refresh()

    def _delete(self) -> None:
        item = self._selected()
        if item is None:
            messagebox.showinfo("提示", "请先选中一条便签", parent=self.win)
            return
        if messagebox.askyesno("确认", f"删除「{item.text}」？", parent=self.win):
            self.items.remove(item)
            self.on_changed()
            self.refresh()

    def _complete(self) -> None:
        item = self._selected()
        if item is None:
            messagebox.showinfo("提示", "请先选中一条便签", parent=self.win)
            return
        item.acknowledge()
        self.on_changed()
        self.refresh()
```

- [ ] **Step 3: 写临时验证脚本**

创建 `D:\Tools\RemindNotes\_check_main_window.py`：

```python
"""临时验证脚本，验证完删除。用假数据跑起主窗口，肉眼确认列表与着色。"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from reminders.model import make_once, make_daily
from reminders.main_window import MainWindow

root = tk.Tk()
root.withdraw()

now = datetime.now()
items = [
    make_daily("每天喝水", "09:00", now),
    make_once("明天开会", now + timedelta(days=1)),
    make_once("已经错过的", now - timedelta(hours=2)),
    make_once("已完成的事", now + timedelta(hours=1)),
]
items[3].acknowledge()
items[2].enabled = True

win = MainWindow(root, items, on_changed=lambda: print("on_changed 被调用"))
win.show()
root.mainloop()
```

- [ ] **Step 4: 运行验证脚本肉眼确认**

Run: `cd /d/Tools/RemindNotes && python _check_main_window.py`

Expected：弹出「便签本」窗口，4 行数据，且：
- 「每天喝水」时间列显示 `每天 09:00`，类型 `每天`，状态 `待提醒`，**黑色**
- 「明天开会」显示具体日期时间，状态 `待提醒`，**黑色**
- 「已经错过的」状态 `已错过`，**红色**
- 「已完成的事」状态 `已完成`，**灰色**

点「新建」应弹出 `NotImplementedError` 报错窗口（Task 6 完成后正常）—— 这一步是确认按钮接线正确。关掉窗口应从任务栏消失但进程仍在（`Ctrl+C` 结束）。

- [ ] **Step 5: 删除临时脚本**

删除 `D:\Tools\RemindNotes\_check_main_window.py`。

---

### Task 6: edit_dialog.py — 新建 / 编辑对话框

**Files:**
- Modify: `D:\Tools\RemindNotes\reminders\edit_dialog.py`（替换 Task 5 的占位骨架）
- Create: `D:\Tools\RemindNotes\_check_edit_dialog.py`（临时验证脚本）

**Interfaces:**
- Consumes: `reminders.model`（Task 1）
- Produces: `open_editor(parent, reminder=None, now=None) -> Reminder | None`
  - `reminder=None` 时新建，返回新构造的 `Reminder`（**未加入 items 列表**，由调用方 append）
  - 传入 `reminder` 时是编辑，**就地修改该对象**并返回它
  - 用户取消时返回 `None`

- [ ] **Step 1: 实现 edit_dialog.py**

完整替换 `D:\Tools\RemindNotes\reminders\edit_dialog.py`：

```python
"""新建 / 编辑便签对话框。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

from .model import make_countdown, make_daily, make_once

DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M"


def open_editor(parent, reminder=None, now=None):
    """打开编辑对话框。新建返回新 Reminder（未入列表），编辑就地改并返回，取消返回 None。"""
    now = now or datetime.now()
    is_new = reminder is None
    base = reminder or make_once("", now)

    dlg = tk.Toplevel(parent)
    dlg.title("新建提醒" if is_new else "编辑提醒")
    dlg.geometry("380x300")
    dlg.transient(parent)
    dlg.resizable(False, False)

    tk.Label(dlg, text="内容").pack(anchor="w", padx=12, pady=(12, 2))
    text_box = tk.Text(dlg, height=4, width=42)
    text_box.pack(padx=12)
    text_box.insert("1.0", base.text)

    kind_var = tk.StringVar(value=base.kind)
    row = tk.Frame(dlg)
    row.pack(anchor="w", padx=12, pady=8)
    tk.Radiobutton(row, text="单次", variable=kind_var,
                   value="once").pack(side="left")
    tk.Radiobutton(row, text="每天", variable=kind_var,
                   value="daily").pack(side="left", padx=(10, 0))

    ref = base.next_fire_at
    date_row = tk.Frame(dlg)
    date_row.pack(anchor="w", padx=12)
    tk.Label(date_row, text="日期").pack(side="left")
    date_entry = tk.Entry(date_row, width=12)
    date_entry.insert(0, ref.strftime(DATE_FMT))
    date_entry.pack(side="left", padx=(6, 0))
    time_entry = tk.Entry(date_row, width=8)
    time_entry.insert(0, ref.strftime(TIME_FMT))
    time_entry.pack(side="left", padx=(10, 0))

    quick = tk.Frame(dlg)
    quick.pack(anchor="w", padx=12, pady=8)
    tk.Label(quick, text="快捷：").pack(side="left")

    result: list = []

    def apply_countdown(minutes: int) -> None:
        target = now + timedelta(minutes=minutes)
        kind_var.set("once")
        date_entry.delete(0, "end")
        date_entry.insert(0, target.strftime(DATE_FMT))
        time_entry.delete(0, "end")
        time_entry.insert(0, target.strftime(TIME_FMT))

    tk.Button(quick, text="30 分钟后",
              command=lambda: apply_countdown(30)).pack(side="left", padx=2)
    tk.Button(quick, text="1 小时后",
              command=lambda: apply_countdown(60)).pack(side="left", padx=2)

    def on_ok() -> None:
        text = text_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("提示", "内容不能为空", parent=dlg)
            return
        kind = kind_var.get()
        try:
            if kind == "daily":
                hh, mm = time_entry.get().strip().split(":")
                _ = datetime(2000, 1, 1, int(hh), int(mm))
                tod = f"{int(hh):02d}:{int(mm):02d}"
            else:
                fire_at = datetime.strptime(
                    f"{date_entry.get().strip()} {time_entry.get().strip()}",
                    f"{DATE_FMT} {TIME_FMT}")
        except (ValueError, TypeError):
            messagebox.showwarning(
                "提示", "时间格式不对。日期如 2026-09-16，时间如 14:30", parent=dlg)
            return

        if is_new:
            new = (make_daily(text, tod, now) if kind == "daily"
                   else make_once(text, fire_at))
            result.append(new)
        else:
            base.text = text
            base.kind = kind
            base.done = False
            base.snooze_until = None
            base.last_fired_at = None
            if kind == "daily":
                fresh = make_daily(text, tod, now)
                base.time_of_day = tod
                base.next_fire_at = fresh.next_fire_at
            else:
                base.time_of_day = ""
                base.next_fire_at = fire_at
            result.append(base)
        dlg.destroy()

    def on_cancel() -> None:
        dlg.destroy()

    btns = tk.Frame(dlg)
    btns.pack(anchor="e", padx=12, pady=12)
    tk.Button(btns, text="取消", width=10, command=on_cancel).pack(side="left")
    tk.Button(btns, text="保存", width=10, command=on_ok).pack(side="left", padx=6)

    dlg.grab_set()
    dlg.wait_window()
    return result[0] if result else None
```

- [ ] **Step 2: 写临时验证脚本**

创建 `D:\Tools\RemindNotes\_check_edit_dialog.py`：

```python
"""临时验证脚本，验证完删除。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from reminders import edit_dialog

root = tk.Tk()
root.withdraw()
print("打开新建对话框…")
r = edit_dialog.open_editor(root)
print("新建返回:", r)
if r is not None:
    print("打开编辑对话框（改上面这条）…")
    r2 = edit_dialog.open_editor(root, reminder=r)
    print("编辑返回:", r2, "对象相同:", r is r2)
root.destroy()
```

- [ ] **Step 3: 运行验证并肉眼确认**

Run: `cd /d/Tools/RemindNotes && python _check_edit_dialog.py`

逐项确认：
1. 内容留空点保存 → 弹「内容不能为空」，对话框不关
2. 时间填 `abc` 点保存 → 弹格式提示，对话框不关
3. 点「30 分钟后」→ 日期时间自动变成当前时间 +30 分钟，类型自动切回「单次」
4. 选「每天」→ 保存后打印的对象 `kind == 'daily'`，`time_of_day` 形如 `14:30`
5. 编辑模式下改完保存 → 打印「对象相同: True」，说明是就地修改

- [ ] **Step 4: 删除临时脚本**

删除 `D:\Tools\RemindNotes\_check_edit_dialog.py`。

---

### Task 7: popup.py — 到点提醒弹窗

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\popup.py`
- Create: `D:\Tools\RemindNotes\_check_popup.py`（临时验证脚本）

**Interfaces:**
- Consumes: `reminders.model.Reminder`（Task 1）
- Produces:
  - `PopupManager(root, on_changed)`
  - `PopupManager.show(reminder) -> None`

`on_changed` 是无参回调，在用户点了任意按钮后调用（用于存盘 + 刷新主窗口）。

**严格遵守：不设置 `-topmost`、不加声音、不加闪烁。** 这是用户明确确认的取舍。

- [ ] **Step 1: 实现 popup.py**

创建 `D:\Tools\RemindNotes\reminders\popup.py`：

```python
"""到点提醒弹窗。普通 Toplevel：不置顶、无提示音、不闪烁（用户明确要求）。"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime


class PopupManager:
    def __init__(self, root: tk.Tk, on_changed):
        self.root = root
        self.on_changed = on_changed
        self.open_popups: list[tk.Toplevel] = []

    def show(self, reminder) -> None:
        win = tk.Toplevel(self.root)
        win.title("提醒")
        win.geometry("360x180")
        self.open_popups.append(win)

        tk.Label(win, text="⏰ 时间到了", font=("Microsoft YaHei", 12, "bold")
                 ).pack(pady=(14, 4))
        tk.Label(win, text=reminder.text, wraplength=320,
                 font=("Microsoft YaHei", 11)).pack(pady=4)
        tk.Label(win, text=reminder.display_time(), fg="#666666"
                 ).pack(pady=(0, 10))

        def close() -> None:
            if win in self.open_popups:
                self.open_popups.remove(win)
            win.destroy()

        def on_ack() -> None:
            reminder.acknowledge()
            self.on_changed()
            close()

        def on_snooze() -> None:
            reminder.snooze(datetime.now())
            self.on_changed()
            close()

        bar = tk.Frame(win)
        bar.pack(pady=(4, 12))
        tk.Button(bar, text="知道了", width=10, command=on_ack).pack(side="left", padx=4)
        tk.Button(bar, text="稍后 10 分钟", width=12,
                  command=on_snooze).pack(side="left", padx=4)
        tk.Button(bar, text="关闭", width=8, command=close).pack(side="left", padx=4)

        win.protocol("WM_DELETE_WINDOW", close)
```

- [ ] **Step 2: 写临时验证脚本**

创建 `D:\Tools\RemindNotes\_check_popup.py`：

```python
"""临时验证脚本，验证完删除。"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from reminders.model import make_once
from reminders.popup import PopupManager

root = tk.Tk()
root.withdraw()

changed = []
pm = PopupManager(root, on_changed=lambda: changed.append(1))

once = make_once("开会", datetime.now())
daily = make_once("这是稍后要测的一条", datetime.now())
pm.show(once)
pm.show(daily)

def report():
    print("once  done =", once.done, " snooze_until =", once.snooze_until)
    print("changed 回调次数 =", len(changed))
    root.destroy()

root.after(40000, report)
root.mainloop()
```

- [ ] **Step 3: 运行验证并肉眼确认**

Run: `cd /d/Tools/RemindNotes && python _check_popup.py`

确认：
1. 同时弹出两个提醒窗口，互不遮挡阻塞
2. 窗口标题是「提醒」，有 ⏰ 时间到了 / 内容 / 时间三行
3. 在第一个窗口点「稍后 10 分钟」→ 关掉后终端打印的 `snooze_until` 约为当前时间 +10 分钟
4. 在第二个窗口点「知道了」→ 打印的 `done = True`
5. **窗口不会强行压在其他程序之上**（把记事本拉上来能盖住它）—— 这是确认没设 topmost

- [ ] **Step 4: 删除临时脚本**

删除 `D:\Tools\RemindNotes\_check_popup.py`。

---

### Task 8: tray.py — 托盘图标与菜单

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\tray.py`
- Create: `D:\Tools\RemindNotes\_check_tray.py`（临时验证脚本）

**Interfaces:**
- Consumes: `reminders.autostart`（Task 4）
- Produces:
  - `make_icon_image(size: int = 64) -> PIL.Image.Image`
  - `Tray(on_open, on_new, on_toggle_pause, on_quit, is_paused)`，属性 `paused`
  - `Tray.build() -> pystray.Icon`
  - `Tray.run_detached() -> None`（在 daemon 线程里跑 `icon.run()`）
  - `Tray.refresh_menu() -> None`（重建菜单以反映暂停状态）

托盘菜单项的「开机自启」勾选状态直接读 `autostart.is_enabled()`。菜单不缓存状态。

- [ ] **Step 1: 实现 tray.py**

创建 `D:\Tools\RemindNotes\reminders\tray.py`：

```python
"""托盘图标与菜单。跑在 daemon 线程里，所有界面动作由调用方调度回主线程。"""
from __future__ import annotations

import threading

import pystray
from PIL import Image, ImageDraw

from . import autostart

ICON_SIZE = 64


def make_icon_image(size: int = ICON_SIZE) -> Image.Image:
    """程序内画一个便签纸图标，省掉 .ico 资源文件。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 8
    body = (pad, pad, size - pad, size - pad)
    d.rounded_rectangle(body, radius=size // 10, fill=(255, 214, 102, 255),
                        outline=(180, 140, 30, 255), width=max(1, size // 32))
    corner = size - pad
    fold = size // 4
    d.polygon([(corner - fold, pad), (corner, pad), (corner, pad + fold)],
              fill=(240, 190, 70, 255))
    line_x0, line_x1 = pad + size // 10, size - pad - size // 10
    for i, ratio in enumerate((0.38, 0.52, 0.66)):
        y = int(pad + (size - 2 * pad) * ratio)
        x1 = line_x1 if i < 2 else line_x1 - size // 8
        d.line([(line_x0, y), (x1, y)], fill=(150, 115, 25, 255),
               width=max(1, size // 24))
    return img


class Tray:
    def __init__(self, on_open, on_new, on_toggle_pause, on_quit, is_paused):
        self.on_open = on_open
        self.on_new = on_new
        self.on_toggle_pause = on_toggle_pause
        self.on_quit = on_quit
        self.is_paused = is_paused
        self.icon: pystray.Icon | None = None

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("打开便签本", lambda: self.on_open(), default=True),
            pystray.MenuItem("新建提醒", lambda: self.on_new()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "暂停全部提醒",
                lambda: self.on_toggle_pause(),
                checked=lambda item: self.is_paused()),
            pystray.MenuItem(
                "开机自启",
                lambda: self._toggle_autostart(),
                checked=lambda item: autostart.is_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.on_quit()),
        )

    def _toggle_autostart(self) -> None:
        try:
            autostart.set_enabled(not autostart.is_enabled())
        except OSError:
            pass

    def build(self) -> pystray.Icon:
        self.icon = pystray.Icon("RemindNotes", make_icon_image(),
                                 "便签提醒", self._menu())
        return self.icon

    def run_detached(self) -> None:
        """在 daemon 线程里跑图标事件循环，让主线程留给 tkinter。"""
        if self.icon is None:
            self.build()
        threading.Thread(target=self.icon.run, daemon=True).start()
```

- [ ] **Step 2: 写临时验证脚本**

创建 `D:\Tools\RemindNotes\_check_tray.py`：

```python
"""临时验证脚本，验证完删除。会真的写一次注册表再还原。"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reminders.tray import Tray, make_icon_image
from reminders import autostart

img = make_icon_image(64)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_icon_preview.png")
img.save(out)
print("图标已导出:", out)

paused = {"v": False}

def toggle():
    paused["v"] = not paused["v"]
    print("暂停 ->", paused["v"])

orig = autostart.is_enabled()

tray = Tray(
    on_open=lambda: print("打开便签本"),
    on_new=lambda: print("新建提醒"),
    on_toggle_pause=toggle,
    on_quit=lambda: (autostart.set_enabled(orig), tray.icon.stop()),
    is_paused=lambda: paused["v"],
)
tray.build()
tray.run_detached()
print("托盘已启动，请查看右下角图标。左键单击应打印'打开便签本'。")
time.sleep(30)
print("自动结束。")
tray.icon.stop()
```

- [ ] **Step 3: 运行验证并肉眼确认**

Run: `cd /d/Tools/RemindNotes && python _check_tray.py`

确认：
1. 打开导出的 `_icon_preview.png`，是一个黄色便签纸图标，有折角，不是空白
2. 右下角托盘区出现同名图标，鼠标悬停显示「便签提醒」
3. **左键单击**图标 → 终端打印「打开便签本」（验证 `default=True` 生效）
4. 右键 → 菜单有 打开便签本 / 新建提醒 / 暂停全部提醒 / 开机自启 / 退出
5. 点「暂停全部提醒」→ 菜单项出现勾，终端打印「暂停 -> True」
6. 点「开机自启」→ 勾选状态翻转（脚本结束时自动还原）

- [ ] **Step 4: 删除临时文件**

删除 `D:\Tools\RemindNotes\_check_tray.py` 和 `D:\Tools\RemindNotes\_icon_preview.png`。

---

### Task 9: app.py + run.pyw — 装配与启动

**Files:**
- Create: `D:\Tools\RemindNotes\reminders\app.py`
- Create: `D:\Tools\RemindNotes\run.pyw`

**Interfaces:**
- Consumes: 全部前序模块
- Produces: `App` 类，`App.run() -> None`

本任务把前八个任务串起来，并落实两条 spec 要求：**单实例互斥体** 与 **缺 pystray 时弹 messagebox 提示**（因为 `.pyw` 双击没有控制台，`print` 看不到）。

- [ ] **Step 1: 实现 app.py**

创建 `D:\Tools\RemindNotes\reminders\app.py`：

```python
"""装配各模块并启动。主线程跑 tkinter，托盘跑 daemon 线程。"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import messagebox

from . import store
from .main_window import MainWindow
from .popup import PopupManager
from .scheduler import Scheduler

MUTEX_NAME = "Global\\RemindNotes_SingleInstance"
ERROR_ALREADY_EXISTS = 183
TICK_MS = 1000


class App:
    def __init__(self) -> None:
        self.items = store.load()
        self.root = tk.Tk()
        self.root.withdraw()
        self.scheduler = Scheduler(self.items)
        self.scheduler.startup()
        self.popups = PopupManager(self.root, self.on_changed)
        self.main_window = MainWindow(self.root, self.items, self.on_changed)
        self.tray = None
        self.running = True

    # ---- 回调（全部在主线程执行）----

    def on_changed(self) -> None:
        store.save(self.items)
        self.main_window.refresh()

    def _fire_popup(self, reminder) -> None:
        self.popups.show(reminder)

    def _tick(self) -> None:
        if not self.running:
            return
        try:
            self.scheduler.tick()
        except Exception:
            pass                      # 单次判定异常不能拖垮整个定时循环
        self.root.after(TICK_MS, self._tick)

    # ---- 托盘动作（从托盘线程调度回主线程）----

    def open_main_window(self) -> None:
        self.root.after(0, self.main_window.show)

    def new_reminder(self) -> None:
        self.root.after(0, self._new_reminder_ui)

    def _new_reminder_ui(self) -> None:
        self.main_window.show()
        self.main_window._new()

    def toggle_pause(self) -> None:
        self.scheduler.paused = not self.scheduler.paused

    def is_paused(self) -> bool:
        return self.scheduler.paused

    def quit(self) -> None:
        import datetime
        print(f"[{datetime.datetime.now():%H:%M:%S}] 退出中…")
        self.running = False
        if self.tray and self.tray.icon:
            self.tray.icon.stop()
        self.root.after(0, self.root.destroy)

    # ---- 启动 ----

    def run(self) -> None:
        from .tray import Tray
        self.scheduler.on_fire = self._fire_popup
        self.tray = Tray(
            on_open=self.open_main_window,
            on_new=self.new_reminder,
            on_toggle_pause=self.toggle_pause,
            on_quit=self.quit,
            is_paused=self.is_paused,
        )
        self.tray.build()
        self.tray.run_detached()
        self.root.after(TICK_MS, self._tick)
        self.root.mainloop()


def acquire_single_instance() -> bool:
    """取得单实例互斥体。已被占用时返回 False。"""
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def _fatal(message: str) -> None:
    """.pyw 双击运行没有控制台，print 看不到，必须用弹窗。"""
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("便签提醒", message)
        root.destroy()
    except Exception:
        print(message)


def main() -> int:
    if not acquire_single_instance():
        _fatal("RemindNotes 已在运行（请查看右下角托盘图标）。")
        return 1
    try:
        import pystray  # noqa: F401
    except ImportError:
        _fatal("缺少 pystray，请先运行：\n\npip install pystray")
        return 1
    App().run()
    return 0
```

- [ ] **Step 2: 创建 run.pyw**

创建 `D:\Tools\RemindNotes\run.pyw`：

```python
"""双击启动入口。.pyw 后缀使 Windows 用 pythonw.exe 运行，不弹控制台黑窗。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reminders.app import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: 跑全部纯逻辑测试**

Run: `cd /d/Tools/RemindNotes && python tests/test_model.py`
Expected: `34/34 passed`

- [ ] **Step 4: 启动程序**

Run: `cd /d/Tools/RemindNotes && python run.pyw`
Expected：无终端输出（`run.pyw` 在 `python` 下运行也走 `pythonw` 逻辑不弹窗），右下角托盘出现图标

- [ ] **Step 5: 验证单实例**

另开一个终端再跑一次：`cd /d/Tools/RemindNotes && python run.pyw`
Expected：弹出一个错误框「RemindNotes 已在运行（请查看右下角托盘图标）」，然后退出。托盘上仍然只有一个图标。

- [ ] **Step 6: 验证主窗口与托盘联动**

在托盘图标上左键单击。
Expected：弹出「便签本」窗口。点「新建」→ 出现编辑对话框（此时 Task 6 已实现，不再报 `NotImplementedError`）。

---

### Task 10: 端到端手动验收

**Files:** 无新增

本任务是最终验收，**必须实际等到时间弹窗**，不能只看代码。

- [ ] **Step 1: 建一条 2 分钟后的提醒**

托盘右键 →「新建提醒」→ 内容填「端到端验收测试」→ 点「30 分钟后」快捷按钮 → 手动把分钟改成当前时间 +2 分钟 → 保存。

Expected：主窗口列表中出现该条，状态「待提醒」，黑色。

- [ ] **Step 2: 等到点，确认弹窗**

等 2 分钟（可以去干别的）。
Expected：自动弹出「提醒」窗口，内容正确；**该窗口能被其他程序窗口盖住**（不置顶）。

- [ ] **Step 3: 验证「稍后 10 分钟」**

点「稍后 10 分钟」。
Expected：弹窗关闭；主窗口该条状态仍为「待提醒」（未完成）；10 分钟后再次弹窗。

若要快速验证而不等 10 分钟：在 Step 1 建一条 1 分钟后的提醒，弹窗后点「稍后 10 分钟」，然后临时把系统时间往后拨 10 分钟 —— 不推荐改系统时间，直接等即可。

- [ ] **Step 4: 验证「知道了」**

第二次弹窗出现时点「知道了」。
Expected：主窗口该条状态变为「已完成」，灰色，不再弹出。

- [ ] **Step 5: 验证「每天」重复**

新建一条「每天」类型、时间设为当前时间之后 2 分钟。到点弹窗后点「知道了」。
Expected：该条状态仍是「待提醒」（daily 不标完成），时间列显示为**明天**的同一时刻。把它的时间去改成「当前时间 +1 分钟」，确认还能再弹一次 —— 说明 `next_fire_at` 滚动正确。

- [ ] **Step 6: 验证「已错过」标红**

新建一条单次提醒，时间设为**过去**（比如今天早些时候）→ 保存。
Expected：主窗口该条状态列显示「已错过」，**红色**。

- [ ] **Step 7: 验证暂停**

托盘右键 → 勾上「暂停全部提醒」。建一条 1 分钟后的提醒，等到点。
Expected：**不弹窗**。取消勾选暂停，再等到下一次 tick。
Expected：立刻补弹（这是有意行为，暂停只是暂时静音）。

- [ ] **Step 8: 验证持久化与损坏恢复**

退出程序（托盘 →「退出」），重新 `python run.pyw` 启动。
Expected：之前建的便签全部还在。

然后：退出程序 → 用记事本把 `C:\Users\Administrator\AppData\Roaming\RemindNotes\reminders.json` 改成一段乱码 → 保存 → 重新启动。
Expected：程序正常启动（列表为空），且同目录下出现 `reminders.json.bad`。

- [ ] **Step 9: 验证开机自启**

托盘右键 → 勾上「开机自启」→ 打开注册表编辑器 `regedit`，定位到
`HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
Expected：存在名为 `RemindNotes` 的值，数据形如
`"C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" "D:\Tools\RemindNotes\run.pyw"`

**重点确认路径是 `pythoncore-3.14-64\pythonw.exe` 而不是 `WindowsApps\pythonw`。**

确认后取消勾选，再回注册表确认该值已消失。

---

## Self-Review 记录

**1. Spec 覆盖检查**

| Spec 章节 | 对应任务 |
| --- | --- |
| 3 目录结构 | Task 1-9 逐一创建（额外加 `autostart.py`，见下） |
| 4 数据模型 / 存储 / 原子写 / 容错 | Task 1（模型）、Task 2（store） |
| 5 线程模型 / 触发判定 / 防重复 / 单实例 | Task 3（判定）、Task 9（线程装配、互斥体） |
| 5 休眠补弹 | Task 3 `tick` 的绝对时间比较天然覆盖，Task 10 Step 2 间接验证 |
| 6.1 托盘 | Task 8 |
| 6.2 主窗口 + 状态着色 | Task 5 |
| 6.3 编辑对话框 + 快捷按钮 | Task 6 |
| 6.4 弹窗（不置顶/无声音/不闪烁） | Task 7 |
| 6.5 开机自启 | Task 4 |
| 7 边界情况表 | Task 2（JSON 损坏）、Task 5（标红）、Task 7（空内容在 Task 6）、Task 9（单实例） |
| 8 测试 | Task 1-4 的 34 个测试 |
| 10 前置条件 | 已完成（pystray 已装） |

**对 spec 文件结构的一处细化：** spec 未列 `autostart.py`，计划将其独立成模块（对应 spec 6.5 的开机自启）。理由：注册表读写需要真实环境验证，独立成模块才能单独测试，塞进 `tray.py` 会变成无法单独验证的代码。

**2. Placeholder 扫描**

无 TBD / TODO / 「类似 Task N」/ 「适当处理错误」。所有代码步骤都含完整可抄代码。

**3. 类型一致性检查**

- `Reminder.mark_fired(now)` 在 Task 1 定义，Task 3 `Scheduler.tick` 调用 —— 签名一致
- `Reminder.snooze(now, minutes=SNOOZE_MINUTES)` 定义于 Task 1，Task 7 `on_snooze` 调用 `reminder.snooze(datetime.now())` —— 一致
- `edit_dialog.open_editor(parent, reminder=None, now=None)` 在 Task 5 桩、Task 6 实现中签名一致，Task 5 `MainWindow._new/_edit` 调用方式一致
- `store.load(path=None)` / `store.save(items, path=None)` 在 Task 2 定义，测试用关键字 `path=` 调用 —— 一致
- `Scheduler(items, on_fire=None)` 在 Task 3 定义，Task 9 `Scheduler(self.items)` 后赋值 `self.scheduler.on_fire` —— 一致
- `MainWindow(root, items, on_changed)` 在 Task 5 定义，Task 9 调用 `MainWindow(self.root, self.items, self.on_changed)` —— 一致
- `PopupManager(root, on_changed)` 在 Task 7 定义，Task 9 调用 `PopupManager(self.root, self.on_changed)` —— 一致
- `autostart.is_enabled()` / `set_enabled(on)` 在 Task 4 定义，Task 8 托盘菜单调用 —— 一致
