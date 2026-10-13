"""真实工作日：法定节假日数据的加载、合并与判定。

三层数据，优先级从高到低：
    手写层  %APPDATA%/RemindNotes/holidays.local.json   只有用户写，程序永不覆盖
    联网层  %APPDATA%/RemindNotes/holidays.json         联网更新时整体替换
    内置层  reminders/data/holidays.json                随发版走，保底

本模块是纯逻辑 + 本地文件读取，**不联网**（联网在 holiday_net.py）。
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import date, timedelta

from . import store

BUILTIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "holidays.json")
LOCAL_PATH = os.path.join(store.DATA_DIR, "holidays.local.json")
NET_PATH = os.path.join(store.DATA_DIR, "holidays.json")

HOLIDAYS_VERSION = 1


def _is_iso_date(value) -> bool:
    """是不是一个合法的 YYYY-MM-DD 字符串。"""
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_dataset(raw, year: int):
    """把 holiday-cn 的数据集解析成自家 schema；拿不准就返回 None（整份丢弃）。

    **isOffDay 的语义是 true = 这天放假**（2026-01-01 元旦就是 true）。
    这个字段极易读反 —— 改这里之前先看 tests/test_holidays.py 的语义钉子。

    三种"没有可用数据"都返回 None，让调用方统一按失败处理：
    year 字段与请求不符（镜像串档）、days 为空（次年的空壳）、解析后一条不剩。
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("year") != year:
        return None
    days = raw.get("days")
    if not isinstance(days, list) or not days:
        return None

    off_days, work_days = [], []
    for item in days:
        if not isinstance(item, dict):
            continue
        key = item.get("date")
        if not _is_iso_date(key) or key[:4] != str(year):
            continue                    # 数据集内部串档，单条丢弃
        if item.get("isOffDay") is True:
            off_days.append(key)
        elif item.get("isOffDay") is False:
            work_days.append(key)

    if not off_days and not work_days:
        return None
    return {
        "version": HOLIDAYS_VERSION,
        "source": f"holiday-cn 数据集 {year}",
        "updated": date.today().isoformat(),
        "covered_from": f"{year}-01-01",
        "covered_to": f"{year}-12-31",
        "holidays": sorted(off_days),
        "makeup_workdays": sorted(work_days),
    }


_lock = threading.Lock()
_layers = None            # 三层缓存；None = 还没读过盘


def _read_json(path: str):
    """读一个 JSON 文件，读不到或坏掉都返回 None（调用方当成"这层没有"）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _date_set(value) -> set:
    """只保留合法的 ISO 日期字符串，其余条目一条条丢掉，不牵连同层其它条目。"""
    if not isinstance(value, list):
        return set()
    return {item for item in value if _is_iso_date(item)}


def _parse_layer(raw):
    """把一层 JSON 解成 {holidays, makeup, covered_to}；不是对象就返回 None。"""
    if not isinstance(raw, dict):
        return None
    covered = raw.get("covered_to")
    return {
        "holidays": frozenset(_date_set(raw.get("holidays"))),
        "makeup": frozenset(_date_set(raw.get("makeup_workdays"))),
        "covered_to": covered if _is_iso_date(covered) else "",
    }


def _builtin_path() -> str:
    """内置数据的位置。打包后资源被解到 sys._MEIPASS 下的临时目录。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "reminders", "data", "holidays.json")
    return BUILTIN_PATH


def _load_layers() -> tuple:
    """读三层，顺序就是优先级：手写层、联网层、内置层。"""
    return (_parse_layer(_read_json(LOCAL_PATH)),
            _parse_layer(_read_json(NET_PATH)),
            _parse_layer(_read_json(_builtin_path())))


def _snapshot() -> tuple:
    """当前三层。首次用到才读盘 —— 不在导入期做 I/O，省得和 import 顺序纠缠。"""
    global _layers
    with _lock:
        if _layers is None:
            _layers = _load_layers()
        return _layers


def reload() -> None:
    """重新读盘。联网更新落盘后必须调用，否则要等下次启动才生效。"""
    global _layers
    with _lock:
        _layers = _load_layers()


def is_workday(day: date) -> bool:
    """这一天算不算工作日。手写层 > 联网层 > 内置层，先命中先返回。

    哪一层都没提到这一天，就按周一至周五算 —— 数据没覆盖到的年份也是这条兜底。
    注意兜底是"两不靠"：放假的周中不会白弹，但调休上班的周六（那本来是周末）
    也认不出来，会漏。所以数据过期时要尽快更新，别让兜底长期顶班。
    调用方不需要知道"有没有数据"。
    """
    key = day.isoformat()
    for layer in _snapshot():
        if layer is None:
            continue
        if key in layer["makeup"]:
            return True
        if key in layer["holidays"]:
            return False
    return day.weekday() < 5


def covered_to() -> str:
    """现有数据覆盖到哪天（各层取最大）。给编辑框写提示用；完全没数据时返回空串。"""
    values = [layer["covered_to"] for layer in _snapshot()
              if layer is not None and layer["covered_to"]]
    return max(values) if values else ""


def is_covered(day: date) -> bool:
    """这一天是不是有权威数据（而不是靠周一至周五兜底）。给测试钉边界用。"""
    limit = covered_to()
    return bool(limit) and day.isoformat() <= limit


def week_of(day: date) -> list[date]:
    """day 所在那周的周一到周日，长度恒为 7。

    编辑框「工作日」那排七格用它。起点取周一，是因为 ``weekdays`` 那套
    （0=周一 … 6=周日）也是这个基准 —— 两处对齐，省得来回换算时差一天。
    跨月跨年由 date 自己算，不用特殊处理。
    """
    monday = day - timedelta(days=day.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def save_net_layer(payload: dict) -> None:
    """把联网取回的数据写进联网层，并立刻刷新缓存。

    原子写入，照 store.save 的套路：先写临时文件再 os.replace。中途失败就把
    临时文件清掉并抛出去 —— 调用方（update）会接住它保持现状，原文件始终是好的。
    """
    os.makedirs(store.DATA_DIR, exist_ok=True)
    tmp = NET_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, NET_PATH)
    reload()
