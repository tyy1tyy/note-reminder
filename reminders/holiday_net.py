"""节假日数据的联网更新。

一层薄壳，只做：推导年份 → 取数 → 交给 holidays 校验与落盘。
判定、合并、解析的纯逻辑全在 holidays.py，这里不重复实现。

**不做单元测试**（真实网络不进测试套）。手工验证：
    python -c "from reminders import holiday_net as n; print(n.update())"
"""
from __future__ import annotations

import json
import threading
import urllib.request
from datetime import date, datetime, timedelta

from . import holidays, store

# 两个源互为备份：jsDelivr 快，raw.githubusercontent 在 jsDelivr 抽风时兜底。
# 2026-09-22 实测两者在本机都通（注意 github.com 不通，raw 这个域名是通的）。
URL_TEMPLATES = (
    "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
)
TIMEOUT = 5.0
MAX_BYTES = 1_000_000        # 防拿到一个巨大的东西；正常一年 5KB 上下
UPDATE_DAYS = 7              # 联网尝试的最小间隔
EXPIRE_DAYS = 45             # 数据剩余不足这么多天就该更新了
PREF_LAST_ATTEMPT = "holidays_checked_at"


def years_to_fetch(today: date) -> list[int]:
    """要拉的年份：去年、今年、明年。

    带上去年是因为跨年后那几天、以及关机很久后重启时，判定会从过去的日期开始走，
    手上有去年的数据就不用退回周一至五猜。
    """
    return [today.year - 1, today.year, today.year + 1]


def _days_left(covered_to: str, today: date):
    """现有数据还剩多少天。没数据时返回 None（调用方当成"立刻要更新"）。"""
    if not covered_to:
        return None
    try:
        return (date.fromisoformat(covered_to) - today).days
    except ValueError:
        return None


def need_update(today: date | None = None) -> bool:
    """该不该更新 —— 纯本地判断，不联网、零成本，所以每次启动都可以跑。"""
    left = _days_left(holidays.covered_to(), today or date.today())
    return left is None or left < EXPIRE_DAYS


def should_attempt(now: datetime | None = None) -> bool:
    """现在该不该真去联网：数据不够用了，且距上次尝试够久。

    两种失败都要记账（见 mark_attempt），所以断网期间不会每次启动都撞一次。
    """
    now = now or datetime.now()
    if not need_update(now.date()):
        return False
    last = store.load_prefs().get(PREF_LAST_ATTEMPT)
    if not isinstance(last, str):
        return True
    try:
        previous = datetime.fromisoformat(last)
    except ValueError:
        return True
    return now - previous >= timedelta(days=UPDATE_DAYS)


def mark_attempt(now: datetime) -> None:
    """记下这次尝试的时刻（成功失败都记）。"""
    try:
        store.save_prefs({**store.load_prefs(),
                          PREF_LAST_ATTEMPT: now.isoformat(timespec="seconds")})
    except OSError:
        pass                # 偏好存不下不该挡住这次更新


def accept_years(years: list[int], today: date) -> bool:
    """拿到的年份够不够新 —— 全是旧年份就拒绝覆盖现有数据。"""
    return bool(years) and max(years) >= today.year


def fetch_year(year: int):
    """按年份取一份数据集原文。多源逐个试，全失败返回 None。"""
    for template in URL_TEMPLATES:
        try:
            with urllib.request.urlopen(template.format(year=year),
                                        timeout=TIMEOUT) as resp:
                raw = resp.read(MAX_BYTES)
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            continue        # 断网、404、限流、返回的不是 JSON —— 一律换下一个源
        return data if isinstance(data, dict) else None
    return None


def update(now: datetime | None = None) -> bool:
    """拉一次并落盘。成功返回 True。任何一步失败都保持现有数据不动。"""
    now = now or datetime.now()
    mark_attempt(now)           # 失败也记账，否则下次启动会立刻再撞一次

    layers, got_years = [], []
    for year in years_to_fetch(now.date()):
        raw = fetch_year(year)
        if raw is None:
            continue
        parsed = holidays.parse_dataset(raw, year)
        if parsed is None:
            continue            # 年份不符、空壳、解析后一条不剩 —— 都当这一年没有
        layers.append(parsed)
        got_years.append(year)

    if not accept_years(got_years, now.date()):
        return False            # 全是旧年份，别把好数据换掉

    payload = {
        "version": layers[-1].get("version", 1),
        "source": " + ".join(layer.get("source", "") for layer in layers),
        "updated": now.date().isoformat(),
        "covered_from": f"{min(got_years)}-01-01",
        "covered_to": f"{max(got_years)}-12-31",
        "holidays": sorted({d for layer in layers for d in layer["holidays"]}),
        "makeup_workdays": sorted({d for layer in layers
                                   for d in layer["makeup_workdays"]}),
    }
    try:
        holidays.save_net_layer(payload)
    except Exception:
        return False            # 磁盘写不了、内容序列化不了：保持现状
    return True


def update_async(on_done=None) -> None:
    """后台跑一次更新，不阻塞启动。

    on_done 在**后台线程**里被调用，所以它不能直接碰 tkinter ——
    调用方需要自己用 root.after(0, ...) 调度回主线程（跟 clock.sync_async 同一条规矩）。
    """
    if store.offline():
        if on_done is not None:
            on_done(False)
        return

    def worker() -> None:
        ok = False
        try:
            if should_attempt():
                ok = update()
        except Exception:
            ok = False          # 更新失败不能影响程序，静默保持现状
        if on_done is not None:
            on_done(ok)

    threading.Thread(target=worker, daemon=True).start()
