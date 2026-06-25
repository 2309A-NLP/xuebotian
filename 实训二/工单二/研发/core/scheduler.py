"""
定时调度器
"""

import threading
import time
from typing import Callable, Optional, List
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import schedule_repo


class Scheduler:
    """定时调度器"""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[调度器] 已启动")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        print("[调度器] 已停止")

    def _run(self):
        while self._running:
            self._log_status()
            time.sleep(60)

    def _log_status(self):
        now = datetime.now()
        active_count = len(schedule_repo.get_all())
        print(f"[调度器] {now.strftime('%H:%M:%S')} - 活动日程数: {active_count}")

    def is_running(self) -> bool:
        return self._running


scheduler = Scheduler()


def get_scheduler() -> Scheduler:
    return scheduler
