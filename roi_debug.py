# -*- coding: utf-8 -*-
# 区域识别插件 - 调试日志（写入插件目录 roi_debug.log）
# 用于真机排查：任务卡住时，查看日志最后一行即可定位卡点。

import os
import threading
import time

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roi_debug.log")
_LOCK = threading.Lock()


def log(msg):
    try:
        line = "[%s] T%s %s\n" % (
            time.strftime("%H:%M:%S"),
            threading.current_thread().ident,
            msg,
        )
        with _LOCK:
            with open(_PATH, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass
