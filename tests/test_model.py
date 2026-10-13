"""RemindNotes 纯逻辑测试。运行：python tests/test_model.py"""
import sys
import os
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reminders.model import (
    Reminder, make_once, make_countdown, make_daily, make_interval,
    normalize_on_startup, fmt_dt, parse_dt,
    parse_date_text, parse_time_text,
    normalize_date_text, normalize_time_text,
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


def test_normalize_on_startup_after_days_offline():
    r = make_daily("喝水", "09:00", datetime(2026, 9, 8, 8, 0, 0))
    assert r.next_fire_at == datetime(2026, 9, 8, 9, 0, 0)
    normalize_on_startup([r], datetime(2026, 9, 15, 12, 0, 0))
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0, 0), r.next_fire_at


def test_expired_once_is_not_replayed_on_startup():
    """程序没运行时过点的单次便签：不补弹，只在列表里标红。

    以前漏了这条，攒了一晚上的错过的提醒会在启动后挨个弹一遍。
    """
    r = make_once("昨晚的事", datetime(2026, 9, 15, 21, 0, 0))
    normalize_on_startup([r], datetime(2026, 9, 16, 9, 0, 0))
    assert r.should_fire(datetime(2026, 9, 16, 9, 0, 1)) is False, \
        "启动后不该把攒下来的过期提醒弹出来"
    assert r.is_missed(datetime(2026, 9, 16, 9, 0, 0)) is True, \
        "但列表里该照常标「已错过」"
    assert r.done is False, "用户没处理过，不该被标成完成"


def test_future_once_is_untouched_on_startup():
    """还没到点的单次便签，启动时不该被动到。"""
    r = make_once("今天下午的事", datetime(2026, 9, 16, 15, 0, 0))
    normalize_on_startup([r], datetime(2026, 9, 16, 9, 0, 0))
    assert r.last_fired_at is None, "还没到点的不该被当成已弹过"
    assert r.should_fire(datetime(2026, 9, 16, 15, 0, 0)) is True, \
        "到点还是得正常弹"


def test_done_once_is_not_touched_on_startup():
    """已经处理完的单次便签，启动时更不该被动到。"""
    r = make_once("做过的事", datetime(2026, 9, 15, 21, 0, 0))
    r.acknowledge(datetime(2026, 9, 15, 21, 30, 0))
    normalize_on_startup([r], datetime(2026, 9, 16, 9, 0, 0))
    assert r.last_fired_at is None, "处理过的不该被标成已弹过"
    assert r.done is True


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


def test_parent_id_marks_which_loop_spawned_the_record():
    """记录带着 parent_id，列表才知道该把它归到哪条循环下面。"""
    rec = make_once("喝水", datetime(2026, 9, 15, 9, 0, 0))
    rec.parent_id = "abc12345"
    back = Reminder.from_dict(rec.to_dict())
    assert back.parent_id == "abc12345"

    plain = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    assert plain.parent_id == "", "不是记录就没有来源"

    old = Reminder.from_dict({"text": "老数据", "kind": "once",
                              "next_fire_at": "2026-09-15T09:00:00"})
    assert old.parent_id == "", "老数据没有这个字段时该留空，不能崩"


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


def test_prefs_roundtrip_and_tolerance():
    """偏好丢了顶多回到默认显示，绝不能因此让程序起不来。"""
    import tempfile
    from reminders import store
    tmp = os.path.join(tempfile.mkdtemp(), "prefs.json")

    assert store.load_prefs(path=tmp) == {}, "文件不存在应是空偏好"
    store.save_prefs({"time_display": "local"}, path=tmp)
    assert store.load_prefs(path=tmp) == {"time_display": "local"}

    with open(tmp, "w", encoding="utf-8") as f:
        f.write("{这不是合法 JSON")
    assert store.load_prefs(path=tmp) == {}, "坏文件当没有，不抛异常"

    with open(tmp, "w", encoding="utf-8") as f:
        f.write('["不是对象"]')
    assert store.load_prefs(path=tmp) == {}, "内容不是对象也不能让调用方拿到列表"

    assert not os.path.exists(tmp + ".tmp"), "不该留下 .tmp"


def test_store_no_tmp_file_left_behind():
    import tempfile
    from reminders import store
    d = tempfile.mkdtemp()
    tmp = os.path.join(d, "r.json")
    store.save([make_once("x", datetime(2026, 9, 15, 9, 0, 0))], path=tmp)
    assert not os.path.exists(tmp + ".tmp"), "原子写入后不应残留 .tmp"


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


def test_parse_date_text_accepts_messy_input():
    """用户随手输的日期都要认，别让人操心格式。"""
    from datetime import date
    want = date(2026, 9, 15)
    for text in ("2026-09-15", "2026/09/15", "2026.09.15", "20260915",
                 "2026年9月15日", " 2026-09-15 "):
        assert parse_date_text(text) == want, f"{text!r} 应解析为 {want}"
    assert parse_date_text("2026/9/5") == date(2026, 9, 5), "单位数月日也要认"
    assert parse_date_text("") is None
    assert parse_date_text("abc") is None
    assert parse_date_text("2026-13-45") is None, "非法月日应返回 None"
    assert parse_date_text("202609") is None, "位数不够应返回 None"


def test_parse_time_text_accepts_messy_input():
    assert parse_time_text("14:30") == (14, 30)
    assert parse_time_text("1430") == (14, 30)
    assert parse_time_text("14.30") == (14, 30)
    assert parse_time_text("14时30分") == (14, 30)
    assert parse_time_text("930") == (9, 30), "三位数按 hmm 理解"
    assert parse_time_text("9") == (9, 0)
    assert parse_time_text("09") == (9, 0)
    assert parse_time_text("") is None
    assert parse_time_text("abc") is None
    assert parse_time_text("2530") is None, "25 点非法"


def test_normalize_text_produces_standard_form():
    assert normalize_date_text("2026/9/5") == "2026-09-05"
    assert normalize_date_text("20260915") == "2026-09-15"
    assert normalize_date_text("乱码") is None
    assert normalize_time_text("930") == "09:30"
    assert normalize_time_text("9") == "09:00"
    assert normalize_time_text("1430") == "14:30"
    assert normalize_time_text("乱码") is None


WORKDAYS = [0, 1, 2, 3, 4]


def _mk_interval(now, **kw):
    opts = dict(weekdays=WORKDAYS, window_start="08:00", window_end="18:00",
                interval_minutes=60, include_end=True)
    opts.update(kw)
    return make_interval("走动", now=now, **opts)


def test_interval_first_slot_mid_window():
    """周二 10:30 建立，首次应是 11:00。"""
    now = datetime(2026, 9, 15, 10, 30)
    assert now.weekday() == 1, "2026-09-15 应是周二"
    r = _mk_interval(now)
    assert r.next_fire_at == datetime(2026, 9, 15, 11, 0), r.next_fire_at


def test_interval_window_start_itself_never_fires():
    """时段起点那一格不弹（2026-09-24 用户裁决）—— 第一声是「起点 + 一个间隔」。

    「09:00-18:00 每 60 分」一整天是 10:00、11:00…18:00 各一声，09:00 只当锚点。
    两种计时方式共用这条规则：固定时刻的锚=时段起点，处理后计时的锚=新建/上次处理那一刻。
    """
    r = _mk_interval(datetime(2026, 9, 15, 8, 0))       # 应用在窗口起点那一刻就在跑
    assert r.next_fire_at == datetime(2026, 9, 15, 9, 0), r.next_fire_at
    assert r.first_slot_time() == time(9, 0), r.first_slot_time()

    # 时段比间隔还短时退回时段起点，否则这条提醒永远等不到第一格（静默哑掉）
    short = _mk_interval(datetime(2026, 9, 15, 7, 0),
                         window_start="08:00", window_end="08:30",
                         interval_minutes=60)
    assert short.first_slot_time() == time(8, 0), short.first_slot_time()


def test_interval_first_slot_before_window():
    """应用在时段之前就在跑 → 第一声是"时段起点 + 一个间隔"，起点那格不弹。"""
    r = _mk_interval(datetime(2026, 9, 15, 7, 0))
    assert r.next_fire_at == datetime(2026, 9, 15, 9, 0), r.next_fire_at


def test_interval_after_window_goes_next_day():
    r = _mk_interval(datetime(2026, 9, 15, 19, 0))
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), r.next_fire_at


def test_interval_friday_evening_skips_to_monday():
    now = datetime(2026, 9, 18, 19, 0)
    assert now.weekday() == 4, "2026-09-18 应是周五"
    r = _mk_interval(now)
    assert r.next_fire_at == datetime(2026, 9, 21, 9, 0), r.next_fire_at
    assert r.next_fire_at.weekday() == 0


def test_interval_saturday_jumps_to_monday():
    now = datetime(2026, 9, 19, 10, 0)
    assert now.weekday() == 5, "2026-09-19 应是周六"
    r = _mk_interval(now)
    assert r.next_fire_at == datetime(2026, 9, 21, 9, 0), r.next_fire_at


def test_interval_includes_end_when_asked():
    """含结束时刻：18:00 还会再弹一次。"""
    r = _mk_interval(datetime(2026, 9, 15, 16, 30))
    assert r.next_fire_at == datetime(2026, 9, 15, 17, 0), r.next_fire_at
    r.mark_fired(datetime(2026, 9, 15, 17, 0))
    assert r.next_fire_at == datetime(2026, 9, 15, 18, 0), r.next_fire_at
    r.mark_fired(datetime(2026, 9, 15, 18, 0))
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), r.next_fire_at


def test_interval_excludes_end_when_asked():
    """不含结束时刻：17:00 弹完就收工，18:00 不再弹。"""
    r = _mk_interval(datetime(2026, 9, 15, 16, 30), include_end=False)
    assert r.next_fire_at == datetime(2026, 9, 15, 17, 0), r.next_fire_at
    r.mark_fired(datetime(2026, 9, 15, 17, 0))
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), r.next_fire_at


def test_interval_built_at_slot_does_not_fire_immediately():
    """正在格子点上建立时，下一次是下一格，不会保存完立刻弹。"""
    r = _mk_interval(datetime(2026, 9, 15, 10, 0))
    assert r.next_fire_at == datetime(2026, 9, 15, 11, 0), r.next_fire_at


def test_interval_custom_step():
    r = _mk_interval(datetime(2026, 9, 15, 10, 5), interval_minutes=30)
    assert r.next_fire_at == datetime(2026, 9, 15, 10, 30), r.next_fire_at
    r.mark_fired(datetime(2026, 9, 15, 10, 30))
    assert r.next_fire_at == datetime(2026, 9, 15, 11, 0), r.next_fire_at


def test_interval_never_missed_and_never_done():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0))
    assert r.is_missed(datetime(2026, 9, 15, 20, 0)) is False
    r.acknowledge()
    assert r.done is False, "循环提醒不该被标完成"
    assert r.status_text(datetime(2026, 9, 15, 10, 30)) == "待提醒"
    assert r.next_fire_at == datetime(2026, 9, 15, 10, 0), \
        "固定模式下用户什么时候处理都不影响格子"


# ---- rolling（处理后计时）----
# 规则一句话：下次 = 「处理这一格的时刻」+ 间隔；**没被处理**的格子按原定时刻
# 继续往前推（所以漏看不会哑）。超出时段 / 非允许日一律顺延。
#
# 2026-09-24 那次裁决改的是后半句：当时是"没人处理就一直停在那一刻"，真机表现
# "过了一小时也没再提醒"（弹窗被压在别的窗口后面没看见 → 这条循环当天永久哑了），
# 于是把锚点挪到了"触发"。2026-09-29 用户裁决把锚点挪回"处理"，同时保留"没处理就
# 按原定时刻继续推"—— 两条要求现在同时成立。

def test_rolling_first_fire_is_one_interval_later():
    """新建时不立刻弹，从现在起算一个间隔。"""
    r = _mk_interval(datetime(2026, 9, 15, 10, 30), interval_mode="rolling")
    assert r.next_fire_at == datetime(2026, 9, 15, 11, 30), r.next_fire_at


def test_rolling_keeps_firing_every_interval_even_unhandled():
    """没人处理也照常按间隔再弹 —— 这是"不断线"那一半，不能丢。

    裁决前这里是反的（没人点就一直停着），而弹窗很容易漏看，一漏看这条循环当天
    的提醒就全没了。锚点是**原定时刻**：格子不因为触发晚了而漂。
    """
    r = _mk_interval(datetime(2026, 9, 15, 10, 30), interval_mode="rolling")
    fire = datetime(2026, 9, 15, 11, 30)
    assert r.should_fire(fire) is True
    r.mark_fired(fire)
    assert r.next_fire_at == datetime(2026, 9, 15, 12, 30), r.next_fire_at
    assert r.should_fire(datetime(2026, 9, 15, 12, 29)) is False, \
        "没到间隔不该提前弹"
    assert r.should_fire(datetime(2026, 9, 15, 12, 30)) is True, \
        "到点就该再弹，不管上一次有没有被处理"
    r.mark_fired(datetime(2026, 9, 15, 12, 30))
    assert r.next_fire_at == datetime(2026, 9, 15, 13, 30), r.next_fire_at


def test_rolling_acknowledge_alone_does_not_shift_schedule():
    """`acknowledge()` 自己不排期：便签本的「标记已读」不会把下一格往后推。

    弹窗上的「知道了」是 acknowledge() **加上** handled() 两步（见 popup.py），
    重排发生在后者。这里钉的是"标记已读 ≠ 处理了那张弹窗"（2026-09-29 裁决）。
    """
    r = _mk_interval(datetime(2026, 9, 15, 10, 30), interval_mode="rolling")
    r.mark_fired(datetime(2026, 9, 15, 11, 30))
    r.acknowledge(datetime(2026, 9, 15, 11, 50))
    assert r.next_fire_at == datetime(2026, 9, 15, 12, 30), \
        f"标记已读不该把下一次往后推，实际 {r.next_fire_at}"


def test_rolling_handled_shifts_schedule_from_handling_moment():
    """用户给的例子：10:00 弹、10:05 点「知道了」→ 11:05；11:05 弹、11:10 点 → 12:10。"""
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), interval_mode="rolling")
    assert r.next_fire_at == datetime(2026, 9, 15, 10, 0), r.next_fire_at

    r.mark_fired(datetime(2026, 9, 15, 10, 0))
    assert r.next_fire_at == datetime(2026, 9, 15, 11, 0), r.next_fire_at
    r.handled(datetime(2026, 9, 15, 10, 5))
    assert r.next_fire_at == datetime(2026, 9, 15, 11, 5), r.next_fire_at

    r.mark_fired(datetime(2026, 9, 15, 11, 5))
    r.handled(datetime(2026, 9, 15, 11, 10))
    assert r.next_fire_at == datetime(2026, 9, 15, 12, 10), r.next_fire_at


def test_rolling_handled_outside_window_waits_for_next_day():
    """处理时刻算出来落在时段外 → 顺延到下一个允许日的第一格，不硬闯。"""
    r = _mk_interval(datetime(2026, 9, 15, 16, 0), interval_mode="rolling")
    r.next_fire_at = datetime(2026, 9, 15, 17, 0)
    r.handled(datetime(2026, 9, 15, 17, 30))          # + 60 分 = 18:30，出了时段
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), r.next_fire_at


def test_rolling_handled_only_touches_rolling_intervals():
    """handled 只重排 rolling 循环；别的类型一点不动。

    尤其是单次便签：弹窗上的「关闭」走的就是 handled()，而「关闭 ≠ 已处理」这条
    对单次便签必须保持（不置 done、列表里照旧标红）。
    """
    once = make_once("交电费", datetime(2026, 9, 15, 10, 0))
    once.handled(datetime(2026, 9, 15, 10, 5))
    assert once.next_fire_at == datetime(2026, 9, 15, 10, 0), once.next_fire_at
    assert once.done is False, "关闭单次便签不能被当成已处理"

    daily = make_daily("吃药", "08:00", datetime(2026, 9, 15, 6, 0))
    daily.handled(datetime(2026, 9, 15, 8, 30))
    assert daily.next_fire_at == datetime(2026, 9, 15, 8, 0), daily.next_fire_at

    fixed = _mk_interval(datetime(2026, 9, 15, 10, 30))      # 默认 fixed
    fixed.handled(datetime(2026, 9, 15, 11, 50))
    assert fixed.next_fire_at == datetime(2026, 9, 15, 11, 0), \
        f"固定时刻的格子不该被处理动作改动，实际 {fixed.next_fire_at}"


def test_rolling_snooze_does_not_shift_schedule():
    """「稍后 10 分钟」不算处理：排期不动，只是 snooze_until 把它拽到 10 分钟后。"""
    r = _mk_interval(datetime(2026, 9, 15, 10, 30), interval_mode="rolling")
    r.mark_fired(datetime(2026, 9, 15, 11, 30))
    kept = r.next_fire_at
    r.snooze(datetime(2026, 9, 15, 11, 35))
    assert r.next_fire_at == kept, r.next_fire_at
    assert r.planned_time() == datetime(2026, 9, 15, 11, 45), r.planned_time()
    assert r.should_fire(datetime(2026, 9, 15, 11, 44)) is False
    assert r.should_fire(datetime(2026, 9, 15, 11, 45)) is True


def test_rolling_overflow_goes_to_next_window():
    """算出来超出时段就顺延到下一个时段起点，不硬闯到 18:00 之后。"""
    r = _mk_interval(datetime(2026, 9, 15, 17, 30), interval_mode="rolling")
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), r.next_fire_at

    r2 = _mk_interval(datetime(2026, 9, 15, 10, 0), interval_mode="rolling",
                      include_end=False)
    # 触发晚了一大截（休眠唤醒 / 暂停恢复）时锚点是**原定时刻**：11:00 那一格到
    # 17:45 才弹完，下一格就还是格子里的 18:00 —— 不含结束的话便跨天。
    r2.mark_fired(datetime(2026, 9, 15, 17, 45))
    assert r2.next_fire_at == datetime(2026, 9, 16, 9, 0), r2.next_fire_at


def test_rolling_serialization_roundtrip():
    r = _mk_interval(datetime(2026, 9, 15, 10, 30), interval_mode="rolling")
    back = Reminder.from_dict(r.to_dict())
    assert back.interval_mode == "rolling"
    assert back.next_fire_at == r.next_fire_at


def test_old_interval_data_defaults_to_fixed():
    """老数据没有 interval_mode 字段，必须按固定时刻走，行为一点不能变。"""
    r = Reminder.from_dict({"text": "老循环", "kind": "interval",
                            "next_fire_at": "2026-09-15T11:00:00",
                            "window_start": "08:00", "window_end": "18:00",
                            "weekdays": [0, 1, 2, 3, 4], "interval_minutes": 60})
    assert r.interval_mode == "fixed"
    r.mark_fired(datetime(2026, 9, 15, 11, 0))
    assert r.next_fire_at == datetime(2026, 9, 15, 12, 0), r.next_fire_at


def test_rolling_display_marks_the_mode():
    rolling = _mk_interval(datetime(2026, 9, 15, 10, 30), interval_mode="rolling")
    assert "处理后计时" in rolling.display_time(), rolling.display_time()
    fixed = _mk_interval(datetime(2026, 9, 15, 10, 30))
    assert "处理后计时" not in fixed.display_time(), fixed.display_time()


def test_rolling_normalize_keeps_future_slot():
    """重启后还没到点 → 原定时刻保留，计时接着走，别拉回格子。"""
    r = _mk_interval(datetime(2026, 9, 15, 10, 0), interval_mode="rolling")
    r.next_fire_at = datetime(2026, 9, 15, 11, 30)
    normalize_on_startup([r], datetime(2026, 9, 15, 11, 0))
    assert r.next_fire_at == datetime(2026, 9, 15, 11, 30), r.next_fire_at


def test_rolling_normalize_overdue_same_day_keeps_its_phase():
    """同一天已过点 → 沿**自己原来的格子**往前推，相位不被启动时刻劫持。

    存 12:10、12:30 启动 → 13:10（不是 13:30）。2026-09-29 之前这里是"从现在的
    再顺延一个间隔"，于是每次重启都把相位挪到"启动时刻"——用户报的"循环提醒的
    时间会因为重启而变"就是这个。
    """
    r = _mk_interval(datetime(2026, 9, 15, 10, 0), interval_mode="rolling")
    r.mark_fired(datetime(2026, 9, 15, 11, 0))        # 11:00 弹过 → 下次 12:00
    r.next_fire_at = datetime(2026, 9, 15, 12, 10)    # 相位 :10（用户处理出来的）
    now = datetime(2026, 9, 15, 12, 30)
    normalize_on_startup([r], now)
    assert r.next_fire_at == datetime(2026, 9, 15, 13, 10), r.next_fire_at
    assert r.should_fire(now) is False, "重启那一刻不该补弹"


def test_rolling_normalize_overdue_previous_day_restarts_from_first_slot():
    """存的下一次不是今天的（关机过夜）→ 回到今天的「时段起点 + 间隔」。"""
    r = _mk_interval(datetime(2026, 9, 14, 10, 0), interval_mode="rolling")
    r.next_fire_at = datetime(2026, 9, 14, 16, 10)    # 昨天 16:10
    normalize_on_startup([r], datetime(2026, 9, 15, 9, 5))
    assert r.next_fire_at == datetime(2026, 9, 15, 10, 0), r.next_fire_at


def test_rolling_normalize_overdue_outside_window_waits_for_next_window():
    """过点但已经出了时段 → 顺延到明天的时段起点，不能半夜把人叫起来。"""
    r = _mk_interval(datetime(2026, 9, 15, 10, 0), interval_mode="rolling")
    r.next_fire_at = datetime(2026, 9, 15, 17, 0)
    normalize_on_startup([r], datetime(2026, 9, 15, 20, 30))
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), r.next_fire_at


def test_rolling_normalize_overdue_on_disallowed_day_waits_for_next_window():
    """过点且今天不是允许的日子（例如只挑工作日的循环赶上周六）→ 照常顺延。"""
    r = _mk_interval(datetime(2026, 9, 18, 10, 0), interval_mode="rolling")
    r.next_fire_at = datetime(2026, 9, 18, 17, 0)     # 周五 17:00
    normalize_on_startup([r], datetime(2026, 9, 19, 10, 0))    # 周六 10:00
    assert r.next_fire_at == datetime(2026, 9, 21, 9, 0), r.next_fire_at


def test_interval_fires_once_per_slot_then_advances():
    r = _mk_interval(datetime(2026, 9, 15, 9, 30))
    assert r.next_fire_at == datetime(2026, 9, 15, 10, 0)
    t = datetime(2026, 9, 15, 10, 0)
    assert r.should_fire(t) is True
    r.mark_fired(t)
    assert r.should_fire(datetime(2026, 9, 15, 10, 0, 1)) is False
    assert r.should_fire(datetime(2026, 9, 15, 11, 0)) is True


def test_interval_normalize_after_days_offline():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0))
    assert r.next_fire_at == datetime(2026, 9, 15, 10, 0)
    normalize_on_startup([r], datetime(2026, 9, 18, 10, 30))     # 三天后（周五）
    assert r.next_fire_at == datetime(2026, 9, 18, 11, 0), r.next_fire_at


def test_interval_normalize_on_weekend():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0))
    normalize_on_startup([r], datetime(2026, 9, 19, 10, 0))      # 周六开机
    assert r.next_fire_at == datetime(2026, 9, 21, 9, 0), r.next_fire_at


def test_interval_serialization_roundtrip():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), interval_minutes=45,
                     include_end=False)
    back = Reminder.from_dict(r.to_dict())
    assert back.kind == "interval"
    assert back.weekdays == r.weekdays
    assert back.window_start == "08:00"
    assert back.window_end == "18:00"
    assert back.interval_minutes == 45
    assert back.include_end is False
    assert back.next_fire_at == r.next_fire_at


def test_interval_display_time():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0))
    assert r.display_time() == "周一至周五 08:00-18:00 每60分", r.display_time()
    r2 = _mk_interval(datetime(2026, 9, 15, 9, 0), weekdays=[0, 2, 4])
    assert r2.display_time() == "周一三五 08:00-18:00 每60分", r2.display_time()
    r3 = _mk_interval(datetime(2026, 9, 15, 9, 0), include_end=False)
    assert r3.display_time().endswith("不含结束"), r3.display_time()


def test_interval_single_day_window():
    """只勾一天、且间隔比时段还长时，不能死循环。"""
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), weekdays=[1],
                     window_start="08:00", window_end="09:00",
                     interval_minutes=120)
    # 周二 09:00 建立：当天 08:00 已过，下一格 10:00 又超出 09:00 的窗口。
    # 这里的 08:00 是 first_slot_time 的退化分支（间隔比时段还长 → 退回时段起点）
    assert r.next_fire_at == datetime(2026, 9, 22, 8, 0), r.next_fire_at
    r.mark_fired(datetime(2026, 9, 22, 8, 0))
    assert r.next_fire_at == datetime(2026, 9, 29, 8, 0), r.next_fire_at


def _mk_range(now, **kw):
    opts = dict(weekdays=[], window_start="08:00", window_end="18:00",
                interval_minutes=60, include_end=True,
                repeat_mode="date_range",
                date_from="2026-09-16", date_to="2026-09-18")
    opts.update(kw)
    return make_interval("区间循环", now=now, **opts)


def test_range_starts_at_first_day():
    """区间开始之前建立，首次落在区间第一天。"""
    r = _mk_range(datetime(2026, 9, 15, 10, 0))       # 周二，区间前一天
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), r.next_fire_at


def test_range_inside_uses_normal_slots():
    r = _mk_range(datetime(2026, 9, 17, 10, 30))      # 周四，区间内
    assert r.next_fire_at == datetime(2026, 9, 17, 11, 0), r.next_fire_at


def test_range_ignores_weekdays():
    """两种模式互斥：date_range 下 weekdays 完全不参与判断。"""
    r = _mk_range(datetime(2026, 9, 16, 7, 0), weekdays=[5, 6])   # 只勾周末
    assert r.next_fire_at == datetime(2026, 9, 16, 9, 0), \
        f"区间模式不该看星期，实际 {r.next_fire_at}"


def test_range_ends_and_expires():
    """区间最后一格弹完就结束，之后不再触发。"""
    r = _mk_range(datetime(2026, 9, 18, 17, 0))
    assert r.next_fire_at == datetime(2026, 9, 18, 18, 0), r.next_fire_at
    r.mark_fired(datetime(2026, 9, 18, 18, 0))
    after = datetime(2026, 9, 18, 18, 30)
    assert r.is_expired(after) is True
    assert r.should_fire(after) is False, "区间结束后不该再弹"
    assert r.status_text(after) == "已结束", r.status_text(after)


def test_range_before_start_not_expired():
    r = _mk_range(datetime(2026, 9, 15, 10, 0))
    assert r.is_expired(datetime(2026, 9, 15, 10, 0)) is False
    assert r.status_text(datetime(2026, 9, 15, 10, 0)) == "待提醒"


def test_range_after_end_not_fireable():
    r = _mk_range(datetime(2026, 9, 19, 10, 0))
    assert r.is_expired(datetime(2026, 9, 19, 10, 0)) is True
    assert r.should_fire(datetime(2026, 9, 19, 10, 0)) is False


def test_range_single_day():
    """区间只有一天。"""
    r = _mk_range(datetime(2026, 9, 16, 9, 0),
                  date_from="2026-09-16", date_to="2026-09-16")
    assert r.next_fire_at == datetime(2026, 9, 16, 10, 0), r.next_fire_at
    r.mark_fired(datetime(2026, 9, 16, 18, 0))
    assert r.is_expired(datetime(2026, 9, 16, 18, 1)) is True


def test_weekday_mode_never_expires():
    """按星期模式的循环永远不过期。"""
    r = _mk_interval(datetime(2026, 9, 15, 9, 0))
    assert r.is_expired(datetime(2030, 1, 1, 0, 0)) is False


def test_workdays_mode_follows_statutory_holidays():
    """真实工作日：调休的周六要弹窗，放假的周四不弹窗。"""
    r = _mk_interval(datetime(2026, 10, 10, 9, 0), repeat_mode="workdays")
    assert r.day_allowed(date(2026, 10, 10)) is True, "10/10 是调休上班日"
    assert r.day_allowed(date(2026, 10, 1)) is False, "10/1 国庆放假"
    assert r.day_allowed(date(2026, 10, 8)) is True, "10/8 节后上班"


def test_workdays_mode_ignores_weekdays_field():
    """workdays 模式下 weekdays 不参与判断（跟 date_range 忽略它同一个约定）。"""
    r = _mk_interval(datetime(2026, 10, 10, 9, 0), weekdays=[],
                     repeat_mode="workdays")
    assert r.day_allowed(date(2026, 10, 10)) is True


def test_workdays_mode_skips_spring_festival():
    """春节 2/15-2/23 整段跳过；调休的 2/14 照样弹窗。"""
    r = _mk_interval(datetime(2026, 2, 14, 9, 0), repeat_mode="workdays")
    assert r.next_fire_at == datetime(2026, 2, 14, 10, 0), r.next_fire_at
    r.mark_fired(datetime(2026, 2, 14, 18, 0))
    assert r.next_fire_at == datetime(2026, 2, 24, 9, 0), r.next_fire_at


def test_workdays_display_time():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), repeat_mode="workdays")
    assert r.display_time() == "工作日 08:00-18:00 每60分", r.display_time()


def test_repeat_mode_is_never_guessed_from_weekdays():
    """读盘只认显式写下的 repeat_mode，绝不拿星期组合去猜（2026-09-23 用户裁决撤销迁移）。

    曾经「勾了恰好一~五」会被升级成 workdays。但 to_dict 永远写 repeat_mode，
    猜法根本分不出「老文件里的默认值」和「用户刚在界面上明确选的 按星期+一~五」，
    结果是用户的选择被一次重启静默改掉（文案变「工作日」、弹窗规则也换掉）。
    """
    d = {"kind": "interval", "text": "走动", "weekdays": [0, 1, 2, 3, 4],
         "repeat_mode": "weekdays"}
    back = Reminder.from_dict(d)
    assert back.repeat_mode == "weekdays", "用户选的按星期不该被换成工作日"
    assert back.display_time().startswith("周一至周五 "), back.display_time()


def test_weekdays_mon_fri_survives_restart():
    """真实路径的回归钉子：界面选「按星期」+ 勾一~五 → 存盘 → 重启读回还是 weekdays。"""
    r = _mk_interval(datetime(2026, 9, 15, 9, 0))
    assert r.repeat_mode == "weekdays", "前提：make_interval 默认就是按星期"
    back = Reminder.from_dict(r.to_dict())
    assert back.repeat_mode == "weekdays", "重启后不该变成「工作日」"
    assert back.display_time().startswith("周一至周五 "), back.display_time()


def test_repeat_mode_falls_back_to_weekdays():
    """三个合法值照收；认不出的值、以及**压根没有这个键**的老数据一律退回按星期。"""
    base = {"kind": "interval", "text": "走动"}
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2],
                               "repeat_mode": "weekdays"}).repeat_mode == "weekdays"
    assert Reminder.from_dict({**base, "weekdays": [5, 6],
                               "repeat_mode": "weekdays"}).repeat_mode == "weekdays"
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2, 3, 4],
                               "repeat_mode": "date_range",
                               "date_from": "2026-09-16",
                               "date_to": "2026-09-18"}).repeat_mode == "date_range"
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2, 3, 4],
                               "repeat_mode": "workdays"}).repeat_mode == "workdays"
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2, 3, 4],
                               "repeat_mode": "乱写的"}).repeat_mode == "weekdays"
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2, 3, 4]}
                              ).repeat_mode == "weekdays", "没有这个键的老数据也一样"


def test_workdays_serialization_roundtrip():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), repeat_mode="workdays")
    back = Reminder.from_dict(r.to_dict())
    assert back.repeat_mode == "workdays"
    assert back.next_fire_at == r.next_fire_at


def test_range_display_time():
    r = _mk_range(datetime(2026, 9, 16, 9, 0))
    assert r.display_time() == "09-16~09-18 08:00-18:00 每60分", r.display_time()


def test_range_serialization_roundtrip():
    r = _mk_range(datetime(2026, 9, 16, 9, 0))
    back = Reminder.from_dict(r.to_dict())
    assert back.repeat_mode == "date_range"
    assert back.date_from == "2026-09-16"
    assert back.date_to == "2026-09-18"
    assert back.next_fire_at == r.next_fire_at
    # 按星期模式往返后仍是 weekdays —— 包括恰好一~五 这种（曾有过一次迁移
    # 会把它换成 workdays，2026-09-23 已撤销，见 test_repeat_mode_is_never_guessed_from_weekdays）
    w = _mk_interval(datetime(2026, 9, 15, 9, 0), weekdays=[0, 2, 4])
    assert Reminder.from_dict(w.to_dict()).repeat_mode == "weekdays"
    w2 = _mk_interval(datetime(2026, 9, 15, 9, 0), weekdays=[0, 1, 2, 3, 4])
    assert Reminder.from_dict(w2.to_dict()).repeat_mode == "weekdays"


def test_interval_log_to_list_roundtrip():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), log_to_list=True)
    assert r.log_to_list is True
    assert Reminder.from_dict(r.to_dict()).log_to_list is True
    assert _mk_interval(datetime(2026, 9, 15, 9, 0)).log_to_list is False, \
        "默认应关闭，否则一天十几条会淹掉列表"


def test_autostart_command_when_frozen():
    """打包成 exe 后自启命令应指向 exe 本身，并带 --tray 静默启动。"""
    from unittest import mock
    from reminders import autostart
    with mock.patch.object(sys, "frozen", True, create=True), \
            mock.patch.object(sys, "executable", r"D:\Some\RemindNotes.exe"):
        cmd = autostart.command_line()
    assert cmd == '"D:\\Some\\RemindNotes.exe" --tray', cmd
    assert "run.pyw" not in cmd, "exe 版里不存在 run.pyw，写进去自启会打不开"


def test_autostart_command_when_not_frozen():
    from reminders import autostart
    cmd = autostart.command_line()
    assert "run.pyw" in cmd, cmd
    assert "pythonw.exe" in cmd.lower(), cmd
    assert cmd.endswith("--tray"), f"开机自启要静默进托盘，实际 {cmd}"


def test_tray_flag_shared_between_autostart_and_app():
    """自启写入的参数和 app 里判断的必须是同一个，否则静默启动会失效。"""
    from reminders import autostart
    from reminders import app as app_module
    assert app_module.TRAY_FLAG == autostart.TRAY_FLAG, \
        "app 判断的参数和 autostart 写入的不是同一个"


def test_clock_offset_applies():
    """校准偏移要真的作用到 now() 上。"""
    from datetime import timedelta
    from reminders import clock
    original = clock._offset
    try:
        clock._offset = timedelta(seconds=30)
        delta = (clock.now() - datetime.now()).total_seconds()
        assert abs(delta - 30) < 1, f"now() 应加上校准偏移，实际差 {delta}"
    finally:
        clock._offset = original
    delta = (clock.now() - datetime.now()).total_seconds()
    assert abs(delta) < 1, "还原后应回到本机时钟"


def test_clock_returns_naive_datetime():
    """必须是 naive —— 混入 aware datetime 会让到处都是比较异常。"""
    from reminders import clock
    assert clock.now().tzinfo is None


def test_clock_sync_network_optional():
    """真连一次 NTP。网络不通就跳过，不能因为断网让测试变红。"""
    from reminders import clock
    result = clock.fetch_beijing_time(timeout=3)
    if result is None:
        print("      (NTP 不可达，跳过)")
        return
    net_time, host = result
    assert net_time.tzinfo is None, "应转成 naive 的北京时间"
    drift = abs((net_time - datetime.now()).total_seconds())
    assert drift < 3600, f"取回的时间离谱：{net_time}（{host}）"


def test_clock_sync_failure_keeps_local_clock():
    """连不上时 sync() 返回 False 且不改变偏移，不能因此让程序不可用。"""
    from unittest import mock
    from datetime import timedelta
    from reminders import clock
    original = clock._offset
    try:
        with mock.patch.object(clock, "fetch_beijing_time", return_value=None):
            assert clock.sync(timeout=0.1) is False
        assert clock._offset == original, "校准失败不该改动偏移"
    finally:
        clock._offset = original


def test_acknowledge_records_done_at():
    """完成时刻要记下来（列表排序不再用它，但字段仍保留）。"""
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    assert r.done_at is None
    finished = datetime(2026, 9, 15, 18, 30, 0)
    r.acknowledge(finished)
    assert r.done is True
    assert r.done_at == finished, r.done_at
    assert r.done_at != r.last_fired_at, "完成时间不是弹窗弹出的时间"


def test_daily_acknowledge_does_not_set_done_at():
    """daily 不标完成，自然也不该记完成时间。"""
    r = make_daily("喝水", "09:00", datetime(2026, 9, 15, 8, 0, 0))
    r.acknowledge(datetime(2026, 9, 15, 9, 5, 0))
    assert r.done is False
    assert r.done_at is None


def test_done_at_serialization_roundtrip():
    r = make_once("开会", datetime(2026, 9, 15, 9, 0, 0))
    r.acknowledge(datetime(2026, 9, 15, 18, 30, 0))
    back = Reminder.from_dict(r.to_dict())
    assert back.done_at == r.done_at


def test_old_data_without_done_at_loads():
    """旧版本写的数据没有 done_at，不能因此崩掉。"""
    r = Reminder.from_dict({"text": "老数据", "kind": "once", "done": True,
                            "next_fire_at": "2026-09-15T09:00:00"})
    assert r.done is True
    assert r.done_at is None


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
