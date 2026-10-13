"""为「处理后计时」的实机验证临时加/删一条循环便签。

直接走项目自己的 store.load/save（不手改 JSON），保证格式与原子写入跟 App 一致。
用法：
    python _e2e/tmp_interval.py add    加一条（全天窗口、每 1 分钟、处理后计时）
    python _e2e/tmp_interval.py del    按 id 删掉那条
    python _e2e/tmp_interval.py show   打印它的当前排期
必须在 App **没运行**时执行 add/del —— 否则 App 会拿内存里的旧状态把它覆盖掉。
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["REMINDNOTES_OFFLINE"] = "1"

from reminders import store                       # noqa: E402
from reminders.model import make_interval         # noqa: E402

TEXT = "【临时验证】处理后计时"
ID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp_interval_id")


def find(items):
    return next((r for r in items if r.text == TEXT), None)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    items = store.load()
    if cmd == "add":
        if find(items) is not None:
            print("已存在，先 del 再加")
            return 1
        now = datetime.now()
        r = make_interval(TEXT, list(range(7)), "00:00", "23:59", 1, True, now,
                          interval_mode="rolling", log_to_list=False)
        items.append(r)
        store.save(items)
        with open(ID_FILE, "w", encoding="utf-8") as f:
            f.write(r.id)
        print(f"已加：id={r.id} now={now:%H:%M:%S} next_fire_at={r.next_fire_at:%H:%M:%S}")
    elif cmd == "del":
        r = find(items)
        if r is None:
            print("没找到，无需删除")
            return 0
        items.remove(r)
        store.save(items)
        print(f"已删：id={r.id}")
    r = find(store.load())
    if r is None:
        print("当前：不存在")
    else:
        print(f"当前：id={r.id} next_fire_at={r.next_fire_at:%Y-%m-%d %H:%M:%S} "
              f"last_fired_at={r.last_fired_at} "
              f"now={datetime.now():%H:%M:%S}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
