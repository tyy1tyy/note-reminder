"""统一时间源。可用 NTP 校准到北京时间（UTC+8）。

本机时钟可能偏几秒到几分钟，而提醒是靠「当前时间 ≥ 计划时间」比较来触发的，
所以偏差会直接体现成「到点了不弹窗」或「提前弹窗」。这里把网络时间取回来算一个
偏移量，之后所有「现在几点」都走 now()。

只依赖标准库（socket + struct 手写 NTP 请求），不引入 ntplib。
"""
from __future__ import annotations

import socket
import struct
import threading
from datetime import datetime, timedelta, timezone

from . import store

NTP_SERVERS = ("ntp.aliyun.com", "cn.pool.ntp.org", "time.windows.com")
NTP_PORT = 123
NTP_EPOCH_DELTA = 2208988800        # 1900-01-01 到 1970-01-01 的秒数
BEIJING = timezone(timedelta(hours=8))

_offset = timedelta(0)
_source = "本机时钟"
_synced = False
_lock = threading.Lock()


def now() -> datetime:
    """当前时间。校准成功后就是北京时间。

    返回 naive datetime（丢掉时区），因为整个程序内部用的都是 naive 本地时间，
    混入 aware datetime 会让比较和相减到处抛异常。
    """
    return datetime.now() + _offset


def local_now() -> datetime:
    """本机时钟的原始读数 —— 没加过校准量。

    界面上「本地时间」显示的就是它，用来跟校准后的北京时间对照：本机时钟偏了
    几分钟、或本机时区不是 +8 时，两个数会明显不一样。提醒的判定一律走 now()，
    这个函数只服务于界面显示。
    """
    return datetime.now()


def offset() -> timedelta:
    return _offset


def source() -> str:
    """当前时间来源，用于界面显示。"""
    return _source


def is_synced() -> bool:
    """是否成功校准过。校准失败时会静默回退到本机时钟，界面据此提示。"""
    return _synced


def fetch_beijing_time(timeout: float = 3.0) -> tuple[datetime, str] | None:
    """逐个尝试 NTP 服务器取北京时间。全部失败返回 None。"""
    packet = b"\x1b" + 47 * b"\x00"      # LI=0 VN=3 Mode=3(client)
    for host in NTP_SERVERS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(timeout)
                s.sendto(packet, (host, NTP_PORT))
                data, _ = s.recvfrom(1024)
            fields = struct.unpack("!12I", data[:48])
            seconds = fields[10] - NTP_EPOCH_DELTA
            utc = datetime.fromtimestamp(seconds, timezone.utc)
            return utc.astimezone(BEIJING).replace(tzinfo=None), host
        except Exception:
            continue
    return None


def sync(timeout: float = 3.0) -> bool:
    """校准一次。成功返回 True。

    失败时保持原样 —— 断网、公司防火墙封 UDP 123 都很常见，
    绝不能因为连不上 NTP 就让程序不能用。
    """
    if store.offline():
        return False            # 离线开关（测试 / 排障）：不碰网络，直接当校准失败
    global _offset, _source, _synced
    result = fetch_beijing_time(timeout)
    if result is None:
        return False
    net_time, host = result
    with _lock:
        _offset = net_time - datetime.now()
        _source = f"网络({host})"
        _synced = True
    return True


def sync_async(on_done=None) -> None:
    """后台线程校准，不阻塞启动（网络请求可能要几秒）。

    on_done 会在后台线程里被调用，所以它不能直接碰 tkinter ——
    调用方需要自己用 root.after(0, ...) 调度回主线程。
    """
    def worker() -> None:
        ok = sync()
        if on_done is not None:
            on_done(ok)

    threading.Thread(target=worker, daemon=True).start()
