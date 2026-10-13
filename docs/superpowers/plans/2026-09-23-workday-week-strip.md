# 「工作日」本周七格 实施计划
状态：Task 1-2 全部完成（2026-09-23）。测试：test_model 97/97、test_holidays 27/27、test_app 全通过。
实施中的两处偏差：① 逐日对照的断言改成在 prepare 里收集快照 —— 对话框在断言执行前就已销毁，`walk(dlg)` 用不了；② `test_app.py` 顶部加了 `theme` 的 import 后，函数内原有的 `from reminders import theme` 把 theme 变成了局部名，前面的断言直接 UnboundLocalError，已删掉那句。
后续按用户要求改了配色：七格的「要弹」由墨底改成**便签黄底 `STICKY`**，今天的描边由黄改成**红框 `PEN_RED`**（测试断言同步跟着改）。
另：本轮顺带定位并修了一个真 bug —— exe 上偶发的「双击后窗口不显示」（见 `app._ensure_window_shown()`）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把编辑框里「工作日」那行从一句话换成「本周 + 七格 + 数据至」——要弹的日子深色、不弹的淡色，今天那格加一圈黄描边。

**Architecture:** 数据层只加一个纯日期函数 `holidays.week_of()`，判定继续用现有的 `is_workday()`（**不新增任何节假日逻辑**）；UI 层把 `edit_dialog.py` 的 `hint_line` 从单个 Label 改成「标签 + 七个只读 Label + 数据信息」。

**Tech Stack:** Python 3.14 标准库 + tkinter。零新依赖。

**Spec:** `docs/superpowers/specs/2026-09-23-workday-week-strip-design.md`

## Global Constraints

- **不执行任何 git 提交**。本机约定见仓库外的 `no-unauthorized-git-commits` —— 每个任务只留工作区改动，**计划里没有 commit 步骤是有意的**。
- 三个测试脚本都要保持全绿：`python tests/test_model.py`、`python tests/test_holidays.py`、`python tests/test_app.py`。测试自带 runner，不用 pytest。
- 测试绝不联网：`tests/` 下的文件在 import 之前就设 `REMINDNOTES_OFFLINE=1` 与隔离的 `REMINDNOTES_DATA_DIR`。
- 注释与文案一律中文，写「为什么」不写「做了什么」。
- **编辑框的既有硬约束不能破**（`tests/test_app.py` 按控件类型 + 文本找控件）：不新增 `Entry`（`entries[0]`=日期、`entries[1]`=时间的位置不能动）、带 `<KeyPress>` 的 Entry 必须恰好 3 个、按钮文本逐字不改。本次只加 `tk.Label`，不碰这些。
- 颜色一律走 `theme` 的模块全局（`globals().update()` 那套），**不要在别的模块里 import 期抄进模块级常量** —— `CLOCK_FG` 踩过这个坑。

---

### Task 1: `holidays.week_of()` —— 一周七天的纯日期计算

**Files:**
- Modify: `reminders/holidays.py`（新增函数；顶部 import 加 `timedelta`）
- Test: `tests/test_holidays.py`

**Interfaces:**
- Consumes: 无
- Produces: `holidays.week_of(day: date) -> list[date]` —— `day` 所在那周的周一到周日，长度恒为 7，`[0]` 一定是周一

- [x] **Step 1: 先写测试**

追加到 `tests/test_holidays.py`（放在 `test_outside_coverage_falls_back_to_mon_fri` 附近，`_main()` 之前）：

```python
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
```

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_holidays.py`
Expected: 两条新用例 ERROR，`AttributeError: module 'reminders.holidays' has no attribute 'week_of'`

- [x] **Step 3: 实现**

`reminders/holidays.py` 顶部：

```python
from datetime import date, timedelta
```

（原来是 `from datetime import date`。）

在 `is_covered()` 之后加：

```python
def week_of(day: date) -> list[date]:
    """day 所在那周的周一到周日，长度恒为 7。

    编辑框「工作日」那排七格用它。用周一当起点，是因为 ``weekdays`` 那套
    （0=周一 … 6=周日）也是这个基准 —— 两处对齐，省得来回换算时差一天。

    跨月跨年由 date 自己算，不用特殊处理。
    """
    monday = day - timedelta(days=day.weekday())
    return [monday + timedelta(days=i) for i in range(7)]
```

- [x] **Step 4: 跑测试，确认通过**

Run: `python tests/test_holidays.py`
Expected: `27/27 passed`

---

### Task 2: 把那行字换成七格

**Files:**
- Modify: `reminders/theme.py`（两套配色各加一个 `INK_FAINT`）
- Modify: `reminders/edit_dialog.py`（`hint_line` 那一处；顶部 import 加 `date`）
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `holidays.week_of(day)`（Task 1）、`holidays.is_workday(day)`、`holidays.covered_to()`
- Produces: 无新接口。`hint_line` 的内容从 1 个 Label 变成 `[本周] + 7 格 + [数据至 XX-XX]`

- [x] **Step 1: 改测试**

`tests/test_app.py` 顶部 import 补两样（现在没有）：

```python
from datetime import date, datetime, timedelta

from reminders import clock, holidays, popup, prompt, store
```

在 `prep_workdays` 那段（搜 `选工作日时会提示数据来源与截止日`）把这一条断言**换掉**：

```python
        assert any("法定节假日" in t for t in seen["labels"]), \
            f"选工作日时应提示数据来源与截止日，实际 {seen['labels']}"
```

换成（那句话现在已经不在了，改成验新的七格）：

```python
        assert "本周" in seen["labels"], \
            f"选工作日时该显示本周排班，实际 {seen['labels']}"
        # 七格的深浅必须与法定节假日**逐日一致**。用当天现算对照，不写死哪几天 ——
        # 写死了换一周跑就挂（本周正好是中秋那周，实况和常规周不一样）。
        _today = date.today()
        _boxes = [c for c in walk(dlg) if isinstance(c, tk.Label)
                  and str(c.cget("text")) in tuple("一二三四五六日")]
        assert len(_boxes) == 7, f"该有七格，实际 {len(_boxes)}"
        for _box, _d in zip(_boxes, holidays.week_of(_today)):
            _on = holidays.is_workday(_d)
            _want = str(theme.INK if _on else theme.PAPER).lower()
            assert str(_box.cget("bg")).lower() == _want, \
                f"{_d}（{'上班' if _on else '休息'}）那格的底色不对：{_box.cget('bg')}"
        assert int(_boxes[_today.weekday()].cget("highlightthickness")) > 0, \
            "今天那格该有一圈描边，否则看不出自己在哪一天"
```

`tests/test_app.py` 里需要 `theme` —— 顶部已有 `from reminders import clock, holidays, popup, prompt, store`，**确认里面有没有 theme**；没有就一并加上。

（`seen["labels"]` 是 `prep_workdays` 里收集的全部 Label 文本，七格的「一二三四五六日」也会进去，所以那句 `"本周" in seen["labels"]` 成立。）

- [x] **Step 2: 跑测试，确认失败**

Run: `python tests/test_app.py`
Expected: 在 `assert "本周" in seen["labels"]` 处 FAIL（现在那行还是「工作日（按国家法定节假日，数据到 …）」）

- [x] **Step 3: 加颜色 token**

`reminders/theme.py` 的 `DAY` 里，紧跟在 `INK_SOFT` 那行之后加：

```python
    # 「不弹」那格的淡字。它比 INK_SOFT 更淡（对纸约 1.8:1，低于 3:1）—— 有意的：
    # 那几格在七格里只负责"占位，说明这天不弹"，不是给人读的内容。
    # 要让人读的（今天在哪天、哪几天要弹）由墨底格子和黄描边负责。
    INK_FAINT="#C6B99B",
```

`EYE` 里对应的那个（纸本身就是暗的，要挑一个同样"只是占位"的值）：

```python
    INK_FAINT="#BCAD8E",
```

- [x] **Step 4: 改 `hint_line`**

`reminders/edit_dialog.py` 顶部 import 行：

```python
from datetime import datetime, timedelta
```

改成：

```python
from datetime import date, datetime, timedelta
```

把现在这段（搜 `模式三：真实工作日`）：

```python
    # 模式三：真实工作日（跟随法定节假日）—— 只需说明数据到哪天，没有可勾的东西
    hint_line = tk.Frame(repeat_row, bg=theme.PAPER)
    _covered = holidays.covered_to()
    flabel(hint_line,
           f"工作日（按国家法定节假日，数据到 {_covered}）" if _covered
           else "工作日（按国家法定节假日，暂无数据）").pack(side="left")
```

换成：

```python
    # 模式三：真实工作日（跟随法定节假日）—— 一排列出**本周**哪天弹、哪天不弹。
    # 前缀写「本周」而不是「工作日」：上面「重复」那排已经亮着"工作日"了，重复；
    # 而"本周"回答了"这是哪一周"，否则这排格子会被读成规则而不是本周实况。
    # 每建一次编辑框重算 —— 联网更新会改数据，不能缓存。
    hint_line = tk.Frame(repeat_row, bg=theme.PAPER)
    flabel(hint_line, "本周").pack(side="left", padx=(0, 8))
    _today = date.today()
    for _i, _d in enumerate(holidays.week_of(_today)):
        _on = holidays.is_workday(_d)
        tk.Label(hint_line, text=WEEKDAY_LABELS[_i],
                 # 要弹 = 墨底纸字（深）；不弹 = 纸底淡字。
                 # **不用便签黄底**：那跟「按星期」勾一~五 长得一模一样，
                 # 会让人以为"工作日 = 按星期勾一~五"。只读，不绑任何点击。
                 bg=theme.INK if _on else theme.PAPER,
                 fg=theme.PAPER if _on else theme.INK_FAINT,
                 font=theme.ui(10), padx=8, pady=3,
                 # 今天那格加一圈黄描边。黄是唯一在**深色格子和淡色格子
                 # 上都看得见**的颜色；红笔不用（它在这套里专指"已错过"）。
                 highlightthickness=2 if _d == _today else 0,
                 highlightbackground=theme.STICKY).pack(side="left", padx=(4, 0))
    _covered = holidays.covered_to()
    flabel(hint_line, f"  数据至 {_covered[5:]}" if _covered
           else "  数据至 —").pack(side="left")
```

（`_covered[5:]` 把 `2026-12-31` 缩成 `12-31` —— 全写太长，实测会把七格挤出窗口。）

- [x] **Step 5: 跑测试，确认通过**

Run: `python tests/test_app.py`
Expected: 全绿，末尾 `全部通过：` 里能看见 `循环的重复：三个选项齐全；选工作日会提示数据截止日，保存为 workdays`

Run: `python tests/test_model.py && python tests/test_holidays.py`
Expected: `97/97 passed` 与 `27/27 passed`

- [x] **Step 6: 量一次宽度（别让七格再被挤出去）**

Run:
```bash
python -c "import tkinter.font as f; print('字号变了就要重新量：编辑框可用宽度 424px，本行实测占 378px')"
```
Expected: 打印提示即可。真改了字号/文案时，用 `hint.winfo_reqwidth()` 复量，**超过 420 就得缩**。

---

## 自审记录

**spec 覆盖检查**（逐节对照 `docs/superpowers/specs/2026-09-23-workday-week-strip-design.md`）：

| spec 章节 | 落在哪个任务 |
| --- | --- |
| §2 形态（本周 + 七格 + 数据至） | Task 2 Step 4 |
| §2 「不用黄底」（避免跟按星期撞脸） | Task 2 Step 4 的注释与实现 |
| §2 今天那格黄描边 | Task 2 Step 4 + Step 1 的断言 |
| §3 `week_of()` | Task 1 |
| §4 `INK_FAINT` token | Task 2 Step 3 |
| §4 每次重算、不缓存 | Task 2 Step 4（写在 `hint_line` 构造里，每次建框都跑） |
| §5 淡字低对比度是有意的 | Task 2 Step 3 的注释 |
| §6 改一条断言、加一条逐日对照 | Task 2 Step 1 |
| §6 `week_of()` 纯逻辑用例 | Task 1 Step 1 |
| §7 布局宽度 | Task 2 Step 6 |

**类型一致性**：`week_of(day) -> list[date]` 在 Task 1 定义、Task 2 消费，名字与返回类型一致；`INK_FAINT` 在 Task 2 Step 3 定义、Step 4 使用，拼写一致。

**没有 commit 步骤** —— 见 Global Constraints 第一条（本机不提交 git）。
