"""节假日数据与真实工作日的测试。运行：python tests/test_holidays.py

全部离线：不碰网络；数据文件写在 REMINDNOTES_DATA_DIR 隔离目录里。
"""
import sys
import os
import json
import tempfile

# 必须在 import reminders.store 之前设好 —— DATA_DIR 是模块级常量
os.environ["REMINDNOTES_DATA_DIR"] = tempfile.mkdtemp(prefix="remindnotes_test_")
os.environ["REMINDNOTES_OFFLINE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta

from reminders import holidays, holiday_net, store

# 2026 年国务院安排（国办发明电〔2025〕7号），照 spec §2.1 逐日落库。
# 这份清单已经两重核对过：① 与通知原文的星期标注一致；② 与 holiday-cn 公开数据集逐条比对差异为 0。
BUILTIN_HOLIDAYS = {
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}
BUILTIN_MAKEUP = {"2026-01-04", "2026-02-14", "2026-02-28",
                  "2026-05-09", "2026-09-20", "2026-10-10"}


def test_builtin_data_file_matches_official_notice():
    """内置数据文件必须与国务院通知核对过的清单完全一致（33 + 6，不多不少）。"""
    with open(holidays.BUILTIN_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert set(raw["holidays"]) == BUILTIN_HOLIDAYS, \
        f"放假日对不上：多了 {set(raw['holidays']) - BUILTIN_HOLIDAYS}，" \
        f"少了 {BUILTIN_HOLIDAYS - set(raw['holidays'])}"
    assert set(raw["makeup_workdays"]) == BUILTIN_MAKEUP, \
        f"调休日对不上：多了 {set(raw['makeup_workdays']) - BUILTIN_MAKEUP}，" \
        f"少了 {BUILTIN_MAKEUP - set(raw['makeup_workdays'])}"
    assert raw["covered_from"] == "2026-01-01" and raw["covered_to"] == "2026-12-31"


def test_builtin_data_weekday_annotations():
    """抽查几个日期的星期，跟通知原文的标注对齐（防手抄串行）。"""
    with open(holidays.BUILTIN_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    by_date = {d: date.fromisoformat(d) for d in raw["holidays"]}
    assert by_date["2026-01-01"].weekday() == 3, "元旦 1/1 应是周四"
    assert by_date["2026-02-15"].weekday() == 6, "春节 2/15 应是周日"
    assert by_date["2026-10-07"].weekday() == 2, "国庆最后一天 10/7 应是周三"
    makeup = {d: date.fromisoformat(d) for d in raw["makeup_workdays"]}
    assert makeup["2026-01-04"].weekday() == 6, "调休 1/4 应是周日"
    assert makeup["2026-10-10"].weekday() == 5, "调休 10/10 应是周六"


def test_parse_dataset_isoffday_true_means_off():
    """isOffDay 的语义钉子：true = 这天放假。

    这个字段极易读反（起草设计时第一遍就读反了），所以钉死两条已知事实：
    2026-01-01 元旦放假、2026-01-04 调休上班。
    """
    raw = {"year": 2026, "days": [
        {"name": "元旦", "date": "2026-01-01", "isOffDay": True},
        {"name": "元旦", "date": "2026-01-02", "isOffDay": True},
        {"name": "元旦", "date": "2026-01-04", "isOffDay": False},
    ]}
    parsed = holidays.parse_dataset(raw, 2026)
    assert "2026-01-01" in parsed["holidays"], "元旦应被当成放假日"
    assert "2026-01-01" not in parsed["makeup_workdays"]
    assert "2026-01-04" in parsed["makeup_workdays"], "1/4 应被当成调休上班日"
    assert "2026-01-04" not in parsed["holidays"]
    assert parsed["covered_to"] == "2026-12-31"


def test_parse_dataset_rejects_wrong_year():
    """year 字段与请求年份不符 → 整份丢弃（防镜像串档 / CDN 缓存串号）。"""
    raw = {"year": 2025, "days": [{"date": "2025-01-01", "isOffDay": True}]}
    assert holidays.parse_dataset(raw, 2026) is None


def test_parse_dataset_drops_entry_of_other_year():
    """条目日期与 year 不符 → 单条丢弃，同份其它条目仍生效。"""
    raw = {"year": 2026, "days": [
        {"date": "2026-01-01", "isOffDay": True},
        {"date": "2027-01-01", "isOffDay": True},
    ]}
    parsed = holidays.parse_dataset(raw, 2026)
    assert parsed["holidays"] == ["2026-01-01"]


def test_parse_dataset_rejects_empty_shell():
    """次年文件是「空壳」不是 404：HTTP 200 但 days 为空。必须当成没有数据。"""
    assert holidays.parse_dataset({"year": 2027, "days": []}, 2027) is None


def test_parse_dataset_rejects_garbage():
    assert holidays.parse_dataset(None, 2026) is None
    assert holidays.parse_dataset([], 2026) is None
    assert holidays.parse_dataset({"year": 2026}, 2026) is None
    assert holidays.parse_dataset({"year": 2026, "days": [{"x": 1}]}, 2026) is None


def _clear_user_layers():
    """每例开头清掉两层用户文件并重载，让判定回落到内置层。"""
    for path in (holidays.LOCAL_PATH, holidays.NET_PATH):
        if os.path.exists(path):
            os.remove(path)
    holidays.reload()


def _write_layer(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def test_builtin_makeup_day_is_workday_and_holiday_is_not():
    _clear_user_layers()
    assert holidays.is_workday(date(2026, 10, 10)) is True, "调休的周六要上班"
    assert holidays.is_workday(date(2026, 10, 1)) is False, "国庆当天不该弹窗"
    assert holidays.is_workday(date(2026, 3, 4)) is True, "普通周三上班"
    assert holidays.is_workday(date(2026, 3, 7)) is False, "普通周六不上班"


def test_local_layer_beats_builtin_both_directions():
    _clear_user_layers()
    _write_layer(holidays.LOCAL_PATH, {
        "holidays": ["2026-10-10"],          # 把内置的调休上班日改成放假
        "makeup_workdays": ["2026-10-01"],   # 把内置的放假日改成上班
    })
    holidays.reload()
    assert holidays.is_workday(date(2026, 10, 10)) is False
    assert holidays.is_workday(date(2026, 10, 1)) is True


def test_net_layer_beats_builtin():
    _clear_user_layers()
    _write_layer(holidays.NET_PATH, {"holidays": ["2026-03-04"]})
    holidays.reload()
    assert holidays.is_workday(date(2026, 3, 4)) is False


def test_local_layer_beats_net_layer():
    _clear_user_layers()
    _write_layer(holidays.NET_PATH, {"holidays": ["2026-03-04"]})
    _write_layer(holidays.LOCAL_PATH, {"makeup_workdays": ["2026-03-04"]})
    holidays.reload()
    assert holidays.is_workday(date(2026, 3, 4)) is True


def test_broken_local_layer_does_not_lose_builtin():
    """用户手抖写坏了手写层，绝不能连内置的 33 天一起丢。"""
    _clear_user_layers()
    with open(holidays.LOCAL_PATH, "w", encoding="utf-8") as f:
        f.write("{ 这不是合法 JSON")
    holidays.reload()
    assert holidays.is_workday(date(2026, 10, 1)) is False, "内置的放假日仍要生效"
    assert holidays.is_workday(date(2026, 10, 10)) is True


def test_illegal_date_entries_are_dropped_one_by_one():
    _clear_user_layers()
    _write_layer(holidays.LOCAL_PATH, {"holidays": ["2026-02-30", "2026/03/04", 5,
                                                   "2026-03-05"]})
    holidays.reload()
    assert holidays.is_workday(date(2026, 3, 5)) is False, "合法的那条要生效"
    assert holidays.is_workday(date(2026, 3, 4)) is True, "非法条目不能生效"


def test_covered_to_takes_max_and_is_covered_boundary():
    _clear_user_layers()
    assert holidays.covered_to() == "2026-12-31"
    assert holidays.is_covered(date(2026, 12, 31)) is True
    assert holidays.is_covered(date(2027, 1, 1)) is False
    _write_layer(holidays.NET_PATH, {"covered_to": "2027-12-31"})
    holidays.reload()
    assert holidays.covered_to() == "2027-12-31"
    assert holidays.is_covered(date(2027, 1, 1)) is True


def test_outside_coverage_falls_back_to_mon_fri():
    """数据没覆盖到的年份：按周一至周五算。"""
    _clear_user_layers()
    assert holidays.is_workday(date(2027, 3, 1)) is True, "2027-03-01 是周一"
    assert holidays.is_workday(date(2027, 3, 6)) is False, "2027-03-06 是周六"


def test_week_of_starts_monday_and_is_always_seven():
    """七格那排的数据来源：一定从周一起、一定是七天。"""
    w = holidays.week_of(date(2026, 9, 23))       # 周三
    assert len(w) == 7
    assert w[0] == date(2026, 9, 21), "必须从周一起（weekdays 那套 0=周一，两边对齐）"
    assert w[-1] == date(2026, 9, 27)
    # 周一那天自己、周日那天自己，都要归到同一周
    assert holidays.week_of(date(2026, 9, 21))[0] == date(2026, 9, 21)
    assert holidays.week_of(date(2026, 9, 27))[0] == date(2026, 9, 21)


def test_week_of_crosses_month_and_year():
    """跨月、跨年都不能断 —— 七格是连着排的，不是按自然月切的。"""
    # 2027-01-01 是周五，那周从 2026-12-28 起
    w = holidays.week_of(date(2027, 1, 1))
    assert w[0] == date(2026, 12, 28), w[0]
    assert w[-1] == date(2027, 1, 3), w[-1]
    assert (w[-1] - w[0]).days == 6


def test_save_net_layer_replaces_file_and_leaves_no_tmp():
    _clear_user_layers()
    holidays.save_net_layer({"version": 1, "covered_to": "2028-12-31",
                             "holidays": [], "makeup_workdays": []})
    assert not os.path.exists(holidays.NET_PATH + ".tmp"), "临时文件不该留下"


def test_save_net_layer_failure_keeps_old_file():
    """写盘失败不能破坏原文件 —— 这正是「先临时文件再替换」的意义。

    set 不能 JSON 序列化，拿它制造一次中途失败。
    """
    _clear_user_layers()
    holidays.save_net_layer({"version": 1, "covered_to": "2028-12-31",
                             "holidays": [], "makeup_workdays": []})
    before = holidays.covered_to()
    raised = False
    try:
        holidays.save_net_layer({"holidays": {1, 2, 3}})
    except TypeError:
        raised = True
    assert raised, "非法内容应当抛错（update() 会接住它并保持现状）"
    assert os.path.exists(holidays.NET_PATH), "原文件必须还在"
    assert not os.path.exists(holidays.NET_PATH + ".tmp"), "失败的临时文件要清掉"
    holidays.reload()
    assert holidays.covered_to() == before, "内容仍是上一次那份"


def test_years_to_fetch_is_derived_from_today():
    assert holiday_net.years_to_fetch(date(2026, 9, 22)) == [2025, 2026, 2027]
    assert holiday_net.years_to_fetch(date(2027, 1, 3)) == [2026, 2027, 2028]


def test_need_update_window_is_45_days():
    """边界：数据到 2026-12-31，剩余 45 天是分界。

    用注入的"今天"扫过边界，不动数据本身。
    """
    _clear_user_layers()
    assert holiday_net.need_update(date(2026, 11, 1)) is False, "还剩 60 天，不用更新"
    assert holiday_net.need_update(date(2026, 11, 16)) is False, "还剩 45 天，还不够急"
    assert holiday_net.need_update(date(2026, 11, 17)) is True, "只剩 44 天，该更新了"
    assert holiday_net.need_update(date(2027, 1, 1)) is True, "已经过期"


def test_need_update_true_when_no_data():
    """一层数据都没有（covered_to 为空）→ _days_left 返回 None，调用方据此当成"立刻要更新"。"""
    assert holiday_net._days_left("", date(2026, 9, 22)) is None
    assert holiday_net._days_left("2026-09-22", date(2026, 9, 22)) == 0


def test_should_attempt_throttles_to_7_days():
    _clear_user_layers()        # 别让前面用例写下的联网层把 covered_to 顶到明年
    now = datetime(2026, 12, 20, 9, 0)
    assert holiday_net.need_update(now.date()) is True, "前提：这时确实该更新"
    store.save_prefs({holiday_net.PREF_LAST_ATTEMPT:
                      (now - timedelta(days=3)).isoformat()})
    assert holiday_net.should_attempt(now) is False, "3 天前试过，还不到 7 天"
    store.save_prefs({holiday_net.PREF_LAST_ATTEMPT:
                      (now - timedelta(days=8)).isoformat()})
    assert holiday_net.should_attempt(now) is True, "8 天前试过，可以再试"
    store.save_prefs({})
    assert holiday_net.should_attempt(now) is True, "从没试过，可以试"


def test_should_attempt_false_when_not_needed():
    """数据还够用 → 连尝试都不该发起。"""
    _clear_user_layers()
    now = datetime(2026, 9, 22, 9, 0)
    store.save_prefs({})
    assert holiday_net.should_attempt(now) is False


def test_mark_attempt_writes_prefs():
    store.save_prefs({"palette": "day"})
    holiday_net.mark_attempt(datetime(2026, 12, 20, 9, 30))
    prefs = store.load_prefs()
    assert prefs[holiday_net.PREF_LAST_ATTEMPT].startswith("2026-12-20T09:30")
    assert prefs["palette"] == "day", "不能把别的偏好冲掉"


def test_accept_years_refuses_stale_data():
    """拿到的全是旧年份 → 拒绝覆盖，防镜像回退把好数据换掉。"""
    assert holiday_net.accept_years([2025, 2026], date(2026, 9, 22)) is True
    assert holiday_net.accept_years([2025], date(2026, 9, 22)) is False
    assert holiday_net.accept_years([], date(2026, 9, 22)) is False


def test_update_async_respects_offline_switch():
    """离线开关：不碰网络，直接回调失败。"""
    seen = []
    holiday_net.update_async(on_done=lambda ok: seen.append(ok))
    assert seen == [False], f"离线时应当立刻回调 False，实际 {seen}"


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
