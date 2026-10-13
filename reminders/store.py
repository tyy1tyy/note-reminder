"""便签数据文件的读写。写入用临时文件 + os.replace 保证原子性。"""
from __future__ import annotations

import json
import os

from .model import Reminder

APP_DIR_NAME = "RemindNotes"


def _data_dir() -> str:
    """数据目录。REMINDNOTES_DATA_DIR 可覆盖 —— 测试用它隔离，避免污染真实数据。"""
    override = os.environ.get("REMINDNOTES_DATA_DIR")
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DIR_NAME)


DATA_DIR = _data_dir()
DATA_PATH = os.path.join(DATA_DIR, "reminders.json")
PREFS_PATH = os.path.join(DATA_DIR, "prefs.json")
SCHEMA_VERSION = 1

# 界面偏好存单独一个文件，不塞进 reminders.json —— 那个文件的结构（items 列表）
# 已经很稳，为一个小开关去改它的顶层格式不划算，还容易在兼容上出岔子。
# 底部时间默认显示哪一栏：auto 跟着校准状态走，beijing / local 是用户点过指定。
TIME_DISPLAY_DEFAULT = "auto"

# 配色：day 是近白纸，eye 是米黄稿纸（护眼模式）。两套的定义都在 theme.py。
PALETTE_DEFAULT = "day"


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


def load_prefs(path: str | None = None) -> dict:
    """读界面偏好。文件缺失、损坏、内容不是对象，一律返回空 dict。

    偏好丢了顶多是回到默认显示，不值得为它让程序起不来 —— 所以这里连
    「备份成 .bad」都省了，直接当没有。
    """
    path = path or PREFS_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(prefs: dict, path: str | None = None) -> None:
    """原子写入，跟便签同一个套路：先写 .tmp 再 os.replace。"""
    path = path or PREFS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def offline() -> bool:
    """离线开关：REMINDNOTES_OFFLINE 置上就不联网。

    给测试用（保证测试套绝对离线），也给排障用。不做成界面开关 ——
    本来就没为 NTP 校时做过，多一个开关只是多一个可能被误解的状态。
    """
    return bool(os.environ.get("REMINDNOTES_OFFLINE"))
