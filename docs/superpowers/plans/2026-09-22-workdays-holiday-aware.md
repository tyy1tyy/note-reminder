# 真实工作日与节假日数据更新 实施计划
状态：Task 1-8 全部完成（2026-09-23）。测试：test_model 97/97、test_holidays 25/25、test_app 全通过。
实施后更正（2026-09-23）：Task 4 的「勾一~五 自动升级成 workdays」迁移**已撤销**（会把用户明确选的「按星期＋一~五」静默改掉，见 spec 顶部更正小节）；Task 7 的启动流程补了 `STARTUP_GRACE_TICKS` 兜底；Slim spec 去掉了 `ssl` 排除。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「循环」里的「工作日」按国家法定节假日（含调休）判断，并让这份数据在不用重新发版的前提下自动更新。

**Architecture:** 新增三层节假日数据（用户手写层 > 联网更新层 > 内置层）+ 一个纯判定的 `holidays.py`；`model.py` 的 `day_allowed()` 加第三路分支接上它；联网更新单独放 `holiday_net.py`（薄壳，不测网络），按「本地判断 → 必要时 7 天一次联网」的节奏跑。顺带把 NTP 校时从同步阻塞改成异步，并把启动排期挪到校时出结果之后。

**Tech Stack:** Python 3.14（标准库 `json`/`os`/`threading`/`urllib`，**零新依赖**）、tkinter、pystray。测试是自带 runner 的脚本（`python tests/xxx.py`），不用 pytest。

**Spec:** `docs/superpowers/specs/2026-09-22-workdays-holiday-aware-design.md`

## Global Constraints

- **不执行任何 git 提交**。每个任务只留工作区改动，不要 `git add` / `git commit` —— 本机约定见仓库外的 `no-unauthorized-git-commits`；要提交时由用户单独授权。
- **测试绝不联网**：联网动作一律尊重环境变量 `REMINDNOTES_OFFLINE=1`；测试文件在 import 之前就把它设上。
- **数据目录用 `REMINDNOTES_DATA_DIR` 隔离**，且在 `import reminders.store` 之前设置（`DATA_DIR` 是模块级常量）。
- **零新依赖**：只用标准库 + 已有的 PIL / pystray。不引入 requests、chinesecalendar 等。
- 注释与文案一律中文，写「为什么」不写「做了什么」—— 跟现有代码同一个风格（看 `clock.py` 的开头注释）。
- 日期一律用 `YYYY-MM-DD` 字符串；`weekdays` 里 0=周一 … 6=周日。
- 三个测试脚本都要保持全绿：`python tests/test_model.py`、`python tests/test_holidays.py`、`python tests/test_app.py`。

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `reminders/data/holidays.json`（新） | 内置的 2026 年放假安排（33 放假 + 6 调休） |
| `reminders/holidays.py`（新） | **纯逻辑**：解析数据集、三层加载与合并、`is_workday` 判定、原子落盘。不联网 |
| `reminders/holiday_net.py`（新） | **联网薄壳**：年份推导、本地判断、取数、校验接线、更新协调。不含判定逻辑 |
| `reminders/model.py`（改） | 第三个 `repeat_mode="workdays"`、`day_allowed` 分支、文案、读盘迁移 |
| `reminders/edit_dialog.py`（改） | 「重复」三个 radio + 工作日提示行 + 保存分支 |
| `reminders/app.py`（改） | 启动顺序：异步校时 → normalize → tick；挂上节假日更新 |
| `reminders/clock.py`（改） | `sync()` 尊重离线开关 |
| `reminders/store.py`（改） | 新增 `offline()` |
| `tests/test_holidays.py`（新） | 数据文件 + 解析 + 三层合并 + 更新判断，全部离线 |
| `tests/test_model.py`（改） | workdays 模式行为、迁移、文案（含改现有断言） |
| `tests/test_app.py`（改） | 装配顺序、三 radio、菜单五项不变 |
| `RemindNotes*.spec`（改）×3 | 把数据文件打进包 |
| `README.md`（改） | 五段说明 |

**为什么要拆 `holidays.py` / `holiday_net.py`**：spec §9 要求"网络层只留一层薄壳不测"，拆开之后这条边界才是真的 —— 判定与合并 100% 可测，联网那半只做接线和手工验证。

**一个必须知道的导入陷阱**：`store.py` 顶部 `from .model import Reminder`，而 `model.py` 要用 `holidays.is_workday`。所以 **`model.py` 里必须用函数内导入**（写在 `day_allowed` 里），顶层 `from . import holidays` 会构成 `model → holidays → store → model` 的循环导入，在 `class Reminder` 定义之前炸掉。Task 4 有具体写法和注释。

---

### Task 1: 内置数据文件

**Files:**
- Create: `reminders/data/holidays.json`
- Create: `tests/test_holidays.py`（本任务先放 runner + 数据文件断言）

**Interfaces:**
- Consumes: 无
- Produces: 数据文件路径 `reminders/data/holidays.json`；字段 `version` / `source` / `updated` / `covered_from` / `covered_to` / `holidays` / `makeup_workdays`

- [x] **Step 1: 先写测试（数据必须被钉住，不能悄悄变）**

创建 `tests/test_holidays.py`：

```python
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

- [x] **Step 2: 跑测试，确认它失败**

Run: `python tests/test_holidays.py`
Expected: 两条都 ERROR，信息里有 `AttributeError: module 'reminders.holidays' has no attribute 'BUILTIN_PATH'`。这一步同时也验证了"测试先红"。

- [x] **Step 3: 写下数据文件**

创建 `reminders/data/holidays.json`（目录也要建）：

```json
{
  "version": 1,
  "source": "国办发明电〔2025〕7号《国务院办公厅关于2026年部分节假日安排的通知》",
  "updated": "2026-09-22",
  "covered_from": "2026-01-01",
  "covered_to": "2026-12-31",
  "holidays": [
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07"
  ],
  "makeup_workdays": [
    "2026-01-04", "2026-02-14", "2026-02-28",
    "2026-05-09", "2026-09-20", "2026-10-10"
  ]
}
```

- [x] **Step 4: 加最小的 `holidays.py` 让路径可用**

创建 `reminders/holidays.py`（本任务只放路径常量，逻辑在 Task 2/3 补）：

```python
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
from datetime import date

from . import store

BUILTIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "holidays.json")
LOCAL_PATH = os.path.join(store.DATA_DIR, "holidays.local.json")
NET_PATH = os.path.join(store.DATA_DIR, "holidays.json")
```

- [x] **Step 5: 跑测试，确认通过**

Run: `python tests/test_holidays.py`
Expected: `2/2 passed`

---

### Task 2: 数据集解析（防 `isOffDay` 读反、防串年份、防空壳）

**Files:**
- Modify: `reminders/holidays.py`（追加 `parse_dataset` 及其私有辅助）
- Test: `tests/test_holidays.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `HOLIDAYS_VERSION` 位置（本任务新增常量）
- Produces: `parse_dataset(raw: dict, year: int) -> dict | None` —— 返回自家 schema 的 dict（含 `holidays` / `makeup_workdays` / `covered_from` / `covered_to`），拿不准时返回 `None`

- [x] **Step 1: 写失败测试**

在 `tests/test_holidays.py` 的 `test_builtin_data_weekday_annotations` 之后追加：

```python
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
```

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_holidays.py`
Expected: 5 条新用例全部 ERROR：`AttributeError: module 'reminders.holidays' has no attribute 'parse_dataset'`；原 2 条仍 PASS。

- [x] **Step 3: 实现**

在 `reminders/holidays.py` 末尾追加：

```python
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
```

- [x] **Step 4: 跑测试，确认通过**

Run: `python tests/test_holidays.py`
Expected: `7/7 passed`

---

### Task 3: 三层加载、合并与判定

**Files:**
- Modify: `reminders/holidays.py`（追加 `_parse_layer` / `_load_layers` / `_snapshot` / `reload` / `is_workday` / `covered_to` / `is_covered` / `save_net_layer`）
- Test: `tests/test_holidays.py`

**Interfaces:**
- Consumes: Task 1 的 `BUILTIN_PATH` / `LOCAL_PATH` / `NET_PATH`
- Produces:
  - `is_workday(day: date) -> bool`
  - `covered_to() -> str`
  - `is_covered(day: date) -> bool`
  - `reload() -> None`
  - `save_net_layer(payload: dict) -> None`

- [x] **Step 1: 写失败测试**

追加到 `tests/test_holidays.py`：

```python
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
    """数据没覆盖到的年份：按周一至周五算（宁可多弹也别漏）。"""
    _clear_user_layers()
    assert holidays.is_workday(date(2027, 3, 1)) is True, "2027-03-01 是周一"
    assert holidays.is_workday(date(2027, 3, 6)) is False, "2027-03-06 是周六"


def test_save_net_layer_writes_and_reloads():
    _clear_user_layers()
    holidays.save_net_layer({"version": 1, "covered_to": "2028-12-31",
                             "holidays": ["2028-01-03"],
                             "makeup_workdays": []})
    assert holidays.covered_to() == "2028-12-31", "落盘后要立刻生效，不用重启"
    assert holidays.is_workday(date(2028, 1, 3)) is False


def test_save_net_layer_replaces_file_and_leaves_no_tmp():
    _clear_user_layers()
    holidays.save_net_layer({"version": 1, "covered_to": "2028-12-31",
                             "holidays": [], "makeup_workdays": []})
    assert not os.path.exists(holidays.NET_PATH + ".tmp"), "临时文件不该留下"


def test_save_net_layer_failure_keeps_old_file():
    """写盘失败不能破坏原文件 —— 这正是"先临时文件再替换"的意义。

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
```

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_holidays.py`
Expected: 新用例 ERROR（`no attribute 'is_workday'` / `'reload'` 等），前 7 条仍 PASS。

- [x] **Step 3: 实现**

在 `reminders/holidays.py` 末尾追加：

```python
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

    哪一层都没提到这一天，就按周一至周五算 —— 数据没覆盖到的年份也是这条兜底
    （宁可多弹一次，也别在该上班的日子不弹）。所以调用方不需要知道"有没有数据"。
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
```

- [x] **Step 4: 跑测试，确认通过**

Run: `python tests/test_holidays.py`
Expected: `17/17 passed`

---

### Task 4: 模型层接入（第三个重复模式）

**Files:**
- Modify: `reminders/model.py:52-54`（字段注释）、`:102-120`（`display_time`）、`:170-180`（`day_allowed`）、`:271-298`（`from_dict`）、`:356-380`（`make_interval`）
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: `holidays.is_workday(day: date) -> bool`（Task 3）
- Produces: `Reminder.repeat_mode` 新取值 `"workdays"`；`make_interval(..., repeat_mode="workdays")` 可用

- [x] **Step 1: 写失败测试**

追加到 `tests/test_model.py`（放在 `test_weekday_mode_never_expires` 附近）：

```python
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
    assert r.next_fire_at == datetime(2026, 2, 24, 8, 0), r.next_fire_at


def test_workdays_display_time():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), repeat_mode="workdays")
    assert r.display_time() == "工作日 08:00-18:00 每60分", r.display_time()


def test_migration_upgrades_mon_fri_to_workdays():
    """旧数据迁移：一~五 曾被当成「工作日」，现在升级成真实的法定工作日。"""
    d = {"kind": "interval", "text": "走动", "weekdays": [0, 1, 2, 3, 4],
         "repeat_mode": "weekdays"}
    assert Reminder.from_dict(d).repeat_mode == "workdays"


def test_migration_leaves_other_sets_alone():
    base = {"kind": "interval", "text": "走动"}
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2],
                               "repeat_mode": "weekdays"}).repeat_mode == "weekdays"
    assert Reminder.from_dict({**base, "weekdays": [5, 6],
                               "repeat_mode": "weekdays"}).repeat_mode == "weekdays"
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2, 3, 4],
                               "repeat_mode": "date_range",
                               "date_from": "2026-09-16",
                               "date_to": "2026-09-18"}).repeat_mode == "date_range"
    # 已经是 workdays 的幂等
    assert Reminder.from_dict({**base, "weekdays": [0, 1, 2, 3, 4],
                               "repeat_mode": "workdays"}).repeat_mode == "workdays"


def test_workdays_serialization_roundtrip():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0), repeat_mode="workdays")
    back = Reminder.from_dict(r.to_dict())
    assert back.repeat_mode == "workdays"
    assert back.next_fire_at == r.next_fire_at
```

同时**改掉一条现有断言**（`tests/test_model.py:618`）：一~五 从此显示成「周一至周五」：

```python
def test_interval_display_time():
    r = _mk_interval(datetime(2026, 9, 15, 9, 0))
    assert r.display_time() == "周一至周五 08:00-18:00 每60分", r.display_time()
    r2 = _mk_interval(datetime(2026, 9, 15, 9, 0), weekdays=[0, 2, 4])
    assert r2.display_time() == "周一三五 08:00-18:00 每60分", r2.display_time()
    r3 = _mk_interval(datetime(2026, 9, 15, 9, 0), include_end=False)
    assert r3.display_time().endswith("不含结束"), r3.display_time()
```

还有 `tests/test_model.py` 顶部要加 `date` 到 datetime 的导入：

```python
from datetime import date, datetime, timedelta
```

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_model.py`
Expected: 新增的 7 条 FAIL/ERROR（例如 `test_workdays_mode_follows_statutory_holidays` 断言失败、`repeat_mode` 不是 workdays），改过的那条 `test_interval_display_time` 也 FAIL（仍返回「工作日 …」）。

- [x] **Step 3: 实现 —— 字段注释**

`reminders/model.py:52-54` 改成：

```python
    # 以下字段仅 kind == "interval"（循环）用；weekdays 里 0=周一 … 6=周日
    weekdays: list[int] = field(default_factory=list)
    # "weekdays" 按星期 | "workdays" 真实工作日（跟随法定节假日）| "date_range" 按日期区间
    # workdays 模式下 weekdays 只写不读 —— 判断不看它，留着是为了切回按星期时有预设
    repeat_mode: str = "weekdays"
```

- [x] **Step 4: 实现 —— `day_allowed`（注意函数内导入）**

`reminders/model.py:170-180` 改成：

```python
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
```

- [x] **Step 5: 实现 —— `display_time`**

`reminders/model.py:105-119` 改成：

```python
        if self.kind == "interval":
            if self.repeat_mode == "date_range":
                label = f"{self.date_from[5:]}~{self.date_to[5:]}"
            elif self.repeat_mode == "workdays":
                label = "工作日"
            else:
                days = sorted(set(self.weekdays))
                if days == [0, 1, 2, 3, 4]:
                    # 这里以前写的是「工作日」—— 但它只是周一到周五，不含法定节假日，
                    # 真正的「工作日」现在是 workdays 模式，所以文案让位
                    label = "周一至周五"
                elif len(days) == 7:
                    label = "每天"
                else:
                    label = "周" + "".join(WEEKDAY_LABELS[d] for d in days)
```

- [x] **Step 6: 实现 —— 读盘迁移**

在 `Reminder.from_dict` 之前加一个模块级辅助：

```python
def _repeat_mode_from(d: dict) -> str:
    """读旧数据时的迁移：一~五 曾被当成「工作日」，升级成真实的法定工作日。

    只认这一种组合。别的星期组合、以及 date_range 都是用户明确的意图，一律照旧。
    """
    mode = d.get("repeat_mode")
    if mode in ("date_range", "workdays"):
        return mode
    days = [int(x) for x in d.get("weekdays", [])
            if isinstance(x, int) and 0 <= int(x) <= 6]
    return "workdays" if sorted(set(days)) == [0, 1, 2, 3, 4] else "weekdays"
```

并把 `from_dict` 里的 `repeat_mode=(...)`（`reminders/model.py:286-287`）换成：

```python
            repeat_mode=_repeat_mode_from(d),
```

- [x] **Step 7: 实现 —— `make_interval` 白名单**

`reminders/model.py:373` 的：

```python
        repeat_mode=("date_range" if repeat_mode == "date_range" else "weekdays"),
```

换成：

```python
        repeat_mode=(repeat_mode if repeat_mode in ("date_range", "workdays")
                     else "weekdays"),
```

顺手把 docstring（`:364-365`）补一句：

```
    repeat_mode="weekdays" 看 weekdays（0=周一 … 6=周日）；
    repeat_mode="workdays" 看国家法定节假日（含调休），此时 weekdays 不参与；
    repeat_mode="date_range" 看 date_from ~ date_to 这个区间。三者互斥。
```

- [x] **Step 8: 跑测试，确认通过**

Run: `python tests/test_model.py`
Expected: 全部 PASS，最后一行形如 `N/N passed`

---

### Task 5: 编辑框的第三个选项

**Files:**
- Modify: `reminders/edit_dialog.py:372-396`（radio 行 + 提示行）、`:469-481`（`sync_mode`）、`:593-617`（保存分支）
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `holidays.covered_to() -> str`（Task 3）、`make_interval(..., repeat_mode="workdays")`（Task 4）
- Produces: 界面可用；`mode_var` 取值多了 `"workdays"`

- [x] **Step 1: 写失败测试**

在 `tests/test_app.py` 的 `main()` 里，紧跟现有的"编辑框三种类型都能建出来"那段之后追加。

**必须复用文件里已有的 `open_editor_with(prepare, ...)` 助手**（`tests/test_app.py:503`）：编辑框是模态的（内部 `wait_window()`），自己用 `app.root.update()` 点按钮的写法会让这个测试文件**永远挂住** —— 文件里的注释专门警告过这个坑。`prepare(dlg, walk)` 会拿到对话框和递归遍历函数，正好用来切 radio。

```python
    # 循环的「重复」现在是三个 radio：按星期 / 工作日 / 按日期区间
    WEEKDAY_TEXTS = tuple("一二三四五六日")

    def click_radio(dlg, walk, text):
        for c in walk(dlg):
            if isinstance(c, tk.Radiobutton) and c.cget("text") == text:
                c.invoke()
                return True
        raise AssertionError(f"找不到选项「{text}」")

    seen = {}

    def prep_workdays(dlg, walk):
        click_radio(dlg, walk, "循环")
        click_radio(dlg, walk, "工作日")
        dlg.update_idletasks()
        seen["radios"] = {c.cget("text") for c in walk(dlg)
                          if isinstance(c, tk.Radiobutton)}
        seen["labels"] = [c.cget("text") for c in walk(dlg)
                          if isinstance(c, tk.Label)]
        seen["day_checks"] = [w.winfo_ismapped() for w in walk(dlg)
                              if isinstance(w, tk.Checkbutton)
                              and w.cget("text") in WEEKDAY_TEXTS]

    saved = open_editor_with(prep_workdays)
    assert saved is not None, "工作日模式应当能保存成功"
    assert {"按星期", "工作日", "按日期区间"} <= seen["radios"], \
        f"重复的三个选项不齐，实际 {seen['radios']}"
    assert any("法定节假日" in t for t in seen["labels"]), \
        f"选工作日时应提示数据来源与截止日，实际 {seen['labels']}"
    assert seen["day_checks"] and not any(seen["day_checks"]), \
        "选工作日时那排星期勾选框要让位（星期勾选框定义在 days_line 里）"
    assert saved.repeat_mode == "workdays", saved.repeat_mode
    assert saved.weekdays == [0, 1, 2, 3, 4], saved.weekdays
    assert saved.display_time().startswith("工作日 "), saved.display_time()
    results.append("循环的重复：三个选项齐全；选工作日会提示数据截止日，保存为 workdays")

    # 「按星期」勾一~五 保存后显示成「周一至周五」，不再是「工作日」
    def prep_weekdays(dlg, walk):
        click_radio(dlg, walk, "循环")
        click_radio(dlg, walk, "按星期")
        dlg.update_idletasks()

    saved = open_editor_with(prep_weekdays)
    assert saved is not None, "按星期模式应当能保存成功"
    assert saved.repeat_mode == "weekdays", saved.repeat_mode
    assert saved.display_time().startswith("周一至周五 "), saved.display_time()
    results.append("按星期勾一~五 显示为「周一至周五」（文案不再骗人）")
```

顺带核对过的事实（不是猜的）：编辑框标题是 `"新建提醒"`（`edit_dialog.py:301`），保存按钮文字是 `"保存"`（`edit_dialog.py:653`），而 `find_button` 能找到它 —— 圆角按钮是个 Canvas，内部包着一个真的 `tk.Button` 子控件（`frameless.py:156-162`）。

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: 在这些新断言处 FAIL，信息形如 `重复的三个选项不齐，实际 {'按星期', '按日期区间'}`。

- [x] **Step 3: 实现 —— 三个 radio + 提示行**

`reminders/edit_dialog.py:380-396` 一段改成（`days_line` / `range_line` 之间插入 `hint_line`）：

```python
    tk.Radiobutton(line1, text="按星期", variable=mode_var, value="weekdays",
                   command=lambda: sync_mode(),
                   **theme.segment()).pack(side="left")
    tk.Radiobutton(line1, text="工作日", variable=mode_var, value="workdays",
                   command=lambda: sync_mode(),
                   **theme.segment()).pack(side="left", padx=(6, 0))
    tk.Radiobutton(line1, text="按日期区间", variable=mode_var,
                   value="date_range", command=lambda: sync_mode(),
                   **theme.segment()).pack(side="left", padx=(6, 0))
```

紧跟 `range_line` 的定义（`:399-411`）之后加：

```python
    # 模式三：真实工作日（跟随法定节假日）—— 只需说明数据到哪天，没有可勾的东西
    hint_line = tk.Frame(repeat_row, bg=theme.PAPER)
    _covered = holidays.covered_to()
    flabel(hint_line,
           f"工作日（按国家法定节假日，数据到 {_covered}）" if _covered
           else "工作日（按国家法定节假日，暂无数据）").pack(side="left")
```

文件顶部的导入（`:12` 附近）加上：

```python
from . import holidays
```

- [x] **Step 4: 实现 —— `sync_mode` 三分支**

`reminders/edit_dialog.py:469-481` 改成：

```python
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
```

- [x] **Step 5: 实现 —— 保存分支**

`reminders/edit_dialog.py:609-617` 的 `else:` 之前插入一路：

```python
            elif mode_var.get() == "workdays":
                # weekdays 传一~五 只是留个预设：workdays 模式的判定完全不看它，
                # 但用户以后切回「按星期」时这排勾选框会预勾好
                fresh = make_interval(text, [0, 1, 2, 3, 4], start, end, step,
                                      include_var.get(), now,
                                      repeat_mode="workdays",
                                      log_to_list=log_var.get(),
                                      interval_mode=timing_var.get())
```

- [x] **Step 6: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 全部通过，末尾打印 `全部通过：` 加一串结果行

---

### Task 6: 联网更新（判断 + 取数 + 校验 + 落盘）

**Files:**
- Create: `reminders/holiday_net.py`
- Test: `tests/test_holidays.py`

**Interfaces:**
- Consumes: `holidays.parse_dataset(raw, year)` / `holidays.save_net_layer(payload)` / `holidays.covered_to()`（Task 2/3）；`store.load_prefs` / `store.save_prefs` / `store.offline()`（Task 7 加 `offline`，本任务先按名字用上）
- Produces:
  - `years_to_fetch(today: date) -> list[int]`
  - `need_update(today: date | None = None) -> bool`
  - `should_attempt(now: datetime | None = None) -> bool`
  - `mark_attempt(now: datetime) -> None`
  - `accept_years(years: list[int], today: date) -> bool`
  - `fetch_year(year: int) -> dict | None`
  - `update(now: datetime | None = None) -> bool`
  - `update_async(on_done=None) -> None`

- [x] **Step 1: 写失败测试**

追加到 `tests/test_holidays.py`：

```python
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
```

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_holidays.py`
Expected: 新用例 ERROR：`module 'reminders' has no attribute 'holiday_net'`（`tests/test_holidays.py` 顶部的导入会直接失败，这是预期的红）

- [x] **Step 3: 实现 `holiday_net.py`**

```python
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
```

- [x] **Step 4: 跑测试，确认通过**

Run: `python tests/test_holidays.py`
Expected: 全部 PASS（26 条左右）。注意 `store.offline()` 还没实现时这里会 ERROR —— 那就先在 `reminders/store.py` 末尾补上（Task 7 Step 3 的内容，本任务可提前做）：

```python
def offline() -> bool:
    """离线开关：REMINDNOTES_OFFLINE 置上就不联网。

    给测试用（保证测试套绝对离线），也给排障用。不做成界面开关 ——
    本来就没为 NTP 校时做过，多一个开关只是多一个可能被误解的状态。
    """
    return bool(os.environ.get("REMINDNOTES_OFFLINE"))
```

- [x] **Step 5: 手工联网验证一次（唯一允许真联网的一步）**

Run:
```bash
python -c "from reminders import holidays, holiday_net; print('before', holidays.covered_to()); print('need', holiday_net.need_update(__import__('datetime').date(2026,12,20))); print('ok', holiday_net.update(__import__('datetime').datetime(2026,12,20,9,0))); print('after', holidays.covered_to())"
```
Expected: `before 2026-12-31` → `need True` → `ok True` → `after 2027-12-31`（此时 2027 数据已由数据集提供时；若数据集仍是空壳，则 `after 2026-12-31` 且 `ok False`，这也是正确行为 —— 说明空壳被挡住了）
检查落盘文件存在且内容合理：

Run: `python -c "import os,json;from reminders import store;print(open(os.path.join(store.DATA_DIR,'holidays.json'),encoding='utf-8').read()[:300])"`

**注意**：这一步会在真实数据目录写下 `holidays.json`。验证完把它删掉，别留下测试痕迹：
Run: `python -c "import os;from reminders import store;p=os.path.join(store.DATA_DIR,'holidays.json');os.path.exists(p) and os.remove(p)"`

---

### Task 7: 启动流程（校时异步 + 挂上节假日更新）

**Files:**
- Modify: `reminders/store.py`（`offline()`，若 Task 6 已加则跳过）
- Modify: `reminders/clock.py:78-93`（`sync()` 尊重离线）
- Modify: `reminders/app.py:19-41`（`__init__`）、`:127-152`（`setup`）、新增 `_after_clock`
- Modify: `tests/test_app.py`（顶部加离线开关；`sync_off` 改成 patch `sync_async`；追加装配顺序用例）

**Interfaces:**
- Consumes: `clock.sync_async(on_done)`（已有）、`holiday_net.update_async(on_done=None)`（Task 6）、`store.offline()`（Task 6/7）
- Produces: `App.started: bool`；`App._after_clock() -> None`；`App.scheduler.startup()` 从此在校时之后调用

- [x] **Step 1: 写失败测试**

`tests/test_app.py` 顶部（`REMINDNOTES_DATA_DIR` 那一行旁边）加：

```python
os.environ["REMINDNOTES_OFFLINE"] = "1"     # 测试套绝不联网（校时 + 节假日更新）
```

`main()` 里 `tests/test_app.py:104-118` 那一整段（从 `sync_off = ...` 到 `assert app.main_window.win.winfo_viewable()`）替换成：

```python
    # 关掉 NTP 校准并让回调立刻以"失败"落地，这样装配顺序是确定的、可断言的。
    # 校时现在是异步的，必须替掉 sync_async 而不是 sync —— 后者启动路径已经不调了。
    def fake_sync_async(on_done=None):
        if on_done is not None:
            on_done(False)

    sync_off = mock.patch.object(clock, "sync_async", side_effect=fake_sync_async)
    sync_off.start()
    assert clock.offset().total_seconds() == 0, "测试期间偏移必须为 0"

    app = App()
    assert app.started is False, "校时出结果之前不该开始判定"
    app.setup()
    assert app.started is False, "setup() 只是起了校时线程，回调还没跑"
    assert app.scheduler.on_fire is not None, \
        "setup() 必须接上 on_fire，否则永远不会弹窗"
    assert app.tray is not None and app.tray.icon is not None, "托盘应已装配"

    app.root.update()            # 让 root.after(0, ...) 的 _after_clock 跑起来
    assert app.started is True, "校时回调之后必须开始判定（哪怕校时失败）"
    results.append("启动顺序：校时出结果 → startup → 开始 tick")

    # 启动就该看到便签本，而不是只留个托盘图标让人再去点
    assert app.main_window.win is not None, "启动后应创建便签本窗口"
    app.root.update()
    assert app.main_window.win.winfo_viewable(), "启动后便签本应当可见"
```

（`results = []` 的定义在这段之后，所以 `results.append` 那行按实际位置调整：要么把这行挪到 `results` 初始化之后，要么把 `results = []` 提到 `app = App()` 之前。以文件现状为准。）

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: `AssertionError: 校时出结果之前不该开始判定`（`App` 还没有 `started` 属性 → 实际会是 `AttributeError: 'App' object has no attribute 'started'`，两者都算预期失败）

- [x] **Step 3: 实现 —— `store.offline()`**

若 Task 6 未加，则在 `reminders/store.py` 末尾追加：

```python
def offline() -> bool:
    """离线开关：REMINDNOTES_OFFLINE 置上就不联网。

    给测试用（保证测试套绝对离线），也给排障用。不做成界面开关 ——
    本来就没为 NTP 校时做过，多一个开关只是多一个可能被误解的状态。
    """
    return bool(os.environ.get("REMINDNOTES_OFFLINE"))
```

- [x] **Step 4: 实现 —— 校时尊重离线**

`reminders/clock.py` 顶部导入加 `from . import store`，`sync()`（`:78-83`）开头加：

```python
def sync(timeout: float = 3.0) -> bool:
    """校准一次。成功返回 True。

    失败时保持原样 —— 断网、公司防火墙封 UDP 123 都很常见，
    绝不能因为连不上 NTP 就让程序不能用。
    """
    if store.offline():
        return False            # 离线开关（测试 / 排障）：不碰网络，直接当校准失败
    global _offset, _source, _synced
```

- [x] **Step 5: 实现 —— `app.py` 的启动顺序**

`reminders/app.py` 顶部导入加 `from . import holiday_net`。

`__init__`（`:23-41`）改成：

```python
    def __init__(self) -> None:
        # 校时不再在这里同步做 —— 它是网络请求，最坏要白等 3 × 1.5 秒（三个源各一次
        # 超时），表现就是"双击图标后好几秒没反应"。改成 setup() 里异步跑。
        # 但排期（normalize）必须等校时出结果，见 _after_clock 的注释。
        self.items = store.load()
        # 配色得在建任何窗口之前定下来 —— 颜色是建控件时写进去的，
        # 窗口建好了再改就只剩重建一条路（见 MainWindow.apply_palette）
        self.palette = self._load_palette()
        theme.use(self.palette)
        # 欢迎页只在头一次运行时露一次，之后启动直接进便签本
        self.first_run = not store.load_prefs().get("welcomed")
        self.root = tk.Tk()
        self.root.withdraw()
        self.scheduler = Scheduler(self.items)
        self.popups = PopupManager(self.root, self.on_changed)
        self.main_window = MainWindow(self.root, self.items, self.on_changed)
        self.tray = None
        self.running = True
        self.started = False        # 校时出结果后才开始判定，见 _after_clock
```

`setup()`（`:134-145`）里的 `self.root.after(TICK_MS, self._tick)` 那一行**删掉**，替换成：

```python
        # 校时是网络请求，放后台；出结果（成功或失败）后再收拾时间点、开始判定。
        clock.sync_async(on_done=lambda ok: self.root.after(0, self._after_clock))
        # 节假日数据：先本地判断（零成本），只有数据快不够用且距上次尝试够久才联网。
        # 它不影响界面（编辑框那句"数据到哪天"下次打开自然是最新的），所以不接回调。
        holiday_net.update_async()
```

并在 `setup()` 之后新增方法：

```python
    def _after_clock(self) -> None:
        """校时出结果后的第一件事：把便签时间点收拾到最终确定的 now 上，再开始判定。

        顺序不能反 —— normalize_on_startup 会把过点的 daily 往后滚，用的是"此刻"。
        要是先用偏快的本机时钟跑一遍，09:00 的每天会在真实 08:50 就被滚到明天，
        校准回来也补不回来（漏弹一次）。
        """
        if self.started:
            return
        self.started = True
        self.scheduler.startup()
        self.root.after(TICK_MS, self._tick)
        self.main_window.refresh()
```

- [x] **Step 6: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 全部通过（末尾 `全部通过：`）。跑两遍确认不 flaky。

再跑另外两个，确认没被牵连：

Run: `python tests/test_model.py && python tests/test_holidays.py`
Expected: 两个都 `N/N passed`

- [x] **Step 7: 手工看一次启动速度**

Run: `python -c "import time,os;os.environ['REMINDNOTES_OFFLINE']='1';from reminders.app import App;t=time.time();a=App();a.setup();print('setup 耗时 %.2fs'%(time.time()-t));a.quit()"`
Expected: `setup 耗时` 明显小于 1 秒（离线开关下校时直接返回；真实断网时它也不再阻塞启动）

---

### Task 8: 打包与 README

**Files:**
- Modify: `RemindNotes.spec:8`、`RemindNotesDir.spec:8`、`RemindNotesSlim.spec:8`（三个 `datas=[]`）
- Modify: `README.md`

**Interfaces:**
- Consumes: `reminders/data/holidays.json`（Task 1）、`holidays._builtin_path()` 的 `sys._MEIPASS` 兜底（Task 3）
- Produces: 打包后的 exe 里带上数据文件；README 说清玩法

- [x] **Step 1: 三个 spec 都加 datas**

`RemindNotes.spec` / `RemindNotesDir.spec` / `RemindNotesSlim.spec` 里的：

```python
    datas=[],
```

统一改成：

```python
    datas=[("reminders/data/holidays.json", "reminders/data")],
```

- [x] **Step 2: 验证打包确实带上了**

Run: `python -c "import re,glob; [print(p, re.search(r'datas=\[(.*?)\]', open(p,encoding='utf-8').read(), re.S).group(1)) for p in glob.glob('RemindNotes*.spec')]"`
Expected: 三行都打印出 `("reminders/data/holidays.json", "reminders/data")`

（可选，若本机装了 PyInstaller、且不介意几分钟：`python -m PyInstaller RemindNotes.spec` 后从 dist 里的 exe 启动一次，确认「工作日」选项正常。跑不动就跳过，别卡在这里。）

- [x] **Step 3: README 补五段**

在 `README.md` 的「循环还带这几项」列表里加一条，并在其后新增一节：

```markdown
- **工作日** —— 跟随国家法定节假日（含调休）：调休上班的周六照样弹窗，春节国庆放假的工作日不弹窗
```

在「循环还带这几项」之后插入：

```markdown
### 「工作日」的数据从哪来

内置一份 2026 年的放假安排（随程序走）。之后的数据会自动更新，**平时不联网**：
只有当现有数据快用完（剩余不足 45 天）才会去拉一次，且一周最多试一次。
更新完就断网也能正常用 —— 数据落在磁盘上。

如果某年数据没跟上（你看到编辑框里「数据到 XXXX-XX-XX」已经过期），
工作日会退回成"周一至周五"：放假的周中不会白弹，但调休上班的周六会漏。

### 想自己加一天假 / 调休

国家安排管不着的个人例外（公司提前放假、你请了年假），写在：

    %APPDATA%\RemindNotes\holidays.local.json

内容就十来行，`holidays` 是放假、`makeup_workdays` 是上班：

```json
{
  "holidays": ["2026-10-10"],
  "makeup_workdays": ["2026-10-01"]
}
```

意思是：10-10 全国调休要上班，但我休息；10-01 全国放假，但我要上班。
**这个文件程序永远不会动**，自动更新不会把它冲掉。

### 作息不是跟随法定怎么办

- 固定作息（单休、双休、休周三…）：直接用「按星期」勾一~六，不需要新功能
- 大小周这种交替作息：暂时得靠上面那个手写文件，把单休周的那些周六写进
  `makeup_workdays`。麻烦，但不动程序
```

- [x] **Step 4: 收尾回归**

Run: `python tests/test_model.py && python tests/test_holidays.py && python tests/test_app.py`
Expected: 三个都是全绿

- [x] **Step 5: 交付说明（不提交）**

把改动清单列给用户（`git status --porcelain` 看不见 —— 这个仓库只跟踪 README.md），由用户决定是否提交：

Run: `git status --porcelain | head -20`
Expected: 能列出新增/修改的文件；**不要 `git add` / `git commit`**

---

## 自审记录

**spec 覆盖检查**（逐节对照 spec）：

| spec 章节 | 落在哪个任务 |
| --- | --- |
| §2.1 2026 数据表 | Task 1（数据文件 + 两重核对断言） |
| §2.2 三层数据与文件 | Task 3（路径 + 三层加载 + 原子落盘） |
| §2.3 判定顺序（7 步） | Task 3（`is_workday` 实现 + 双向覆盖用例） |
| §2.4 加载与容错 | Task 3（坏层只丢那层、非法条目单条丢弃） |
| §3.1 数据源与实测 | Task 6（`URL_TEMPLATES`） |
| §3.2 `isOffDay` 语义 | Task 2（语义钉子用例） |
| §3.3 按需更新 45/7 天 | Task 6（`need_update` / `should_attempt`）+ Task 7（挂载） |
| §3.4 校验与落盘 | Task 2（年份三校验）+ Task 6（`accept_years` / `save_net_layer`） |
| §3.5 失败处理 | Task 6（每步失败都 return False / 静默） |
| §3.6 照抄 clock.py 形状 | Task 6（`update_async`）+ Task 7（接线） |
| §3.7 隐私与离线开关 | Task 7（`store.offline()` + 测试前提） |
| §4 `holidays.py` 接口 | Task 1/2/3 |
| §5 `model.py` 改动 | Task 4（六处全改） |
| §6 `edit_dialog.py` 改动 | Task 5（radio + 提示行 + 保存分支） |
| §7 校时异步 | Task 7（含 `_after_clock` 的"为什么必须延后"注释） |
| §8 打包与 README | Task 8 |
| §9 测试清单 | Task 2/3/4/5/6/7 各自的用例 |
| §10 明确不做 | 计划里没有任何菜单项、没有界面开关、没有轮班规则 |
| §11 风险 | Task 3 坏层容错、Task 6 空壳拒绝、Task 7 顺序注释 |

**类型/命名一致性**：`parse_dataset(raw, year)`、`is_workday(day)`、`covered_to()`、`is_covered(day)`、`reload()`、`save_net_layer(payload)`、`need_update(today=None)`、`should_attempt(now=None)`、`mark_attempt(now)`、`accept_years(years, today)`、`years_to_fetch(today)`、`fetch_year(year)`、`update(now=None)`、`update_async(on_done=None)`、`store.offline()`、`App.started`、`App._after_clock()` —— 全计划同一套名字，没有别名。

**占位符扫描**：没有 TBD/TODO；每个代码步骤都是可粘贴的完整实现。计划里引用的 UI 事实（编辑框标题 `"新建提醒"`、保存按钮 `"保存"`、`find_button` 能穿透到圆角按钮内部的真 Button、测试驱动要走模态的 `open_editor_with`）全部核对过源码，不是猜的。

**已知的实现期注意点**（都写进对应任务了）：

1. `model.py` 里 `from . import holidays` **必须在函数内**（顶层会成环：model → holidays → store → model）。Task 4 Step 4 有注释。
2. 三层缓存**首次用到才读盘**，不在导入期做 I/O —— 同样是为了避开导入顺序。
3. `tests/test_app.py` 的 `sync_off` 必须从 patch `clock.sync` 改成 patch `clock.sync_async`，否则新启动路径下那个 mock 是空的，测试会真的去连网络。
4. 编辑框是模态的：**不要**用 `app.main_window.open_new()` + `update()` 点按钮的写法，那会让测试文件永远挂住 —— 用现成的 `open_editor_with(prepare, ...)`（`tests/test_app.py:503`）。Task 5 的用例就是这么写的。
5. `holidays.save_net_layer()` 失败时会抛异常（并清掉临时文件），`update()` 用 `except Exception` 接住并保持现状 —— 别收窄成 `OSError`，JSON 序列化失败是 `TypeError`。
6. Task 6 会往真实数据目录写文件，Step 5 末尾给了删除命令。
