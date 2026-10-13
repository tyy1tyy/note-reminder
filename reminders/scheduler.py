"""每秒 tick 的调度器。纯逻辑，不依赖 UI —— 该弹窗时通过 on_fire 回调通知调用方。"""
from __future__ import annotations

from datetime import datetime

from . import clock
from .model import Reminder, normalize_on_startup


class Scheduler:
    def __init__(self, items: list[Reminder], on_fire=None):
        self.items = items
        self.on_fire = on_fire
        self.paused = False

    def startup(self, now: datetime | None = None) -> None:
        """程序启动时调用一次：滚动程序未运行期间过期的 daily。"""
        normalize_on_startup(self.items, now or clock.now())

    def tick(self, now: datetime | None = None) -> list[Reminder]:
        """判定并触发该弹窗的便签，返回本次触发的列表（供测试与日志）。

        暂停期间直接返回，不更新任何状态，因此恢复后会补弹。
        """
        now = now or clock.now()
        if self.paused:
            return []
        fired = [item for item in self.items if item.should_fire(now)]
        for item in fired:
            item.mark_fired(now)
        for item in fired:
            if self.on_fire:
                self.on_fire(item)
        return fired
