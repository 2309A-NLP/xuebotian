"""
提醒服务（增强版）
"""

import time
import threading
from typing import Callable, Optional, List
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Schedule, schedule_repo


class EnhancedReminderService:
    """增强版提醒服务"""

    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._reminded_ids: set = set()
        self._callbacks: List[Callable] = []
        self.reminder_templates = [
            "温馨提醒：（{content}）的时间到啦，主人！",
            "主人！是时候（{content}）了喔~",
            "亲爱的主人，现在是（{content}）的时候啦！",
            "嘿，主人，该（{content}）了哦~"
        ]

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[提醒服务] 已启动，检查间隔 {self.check_interval} 秒")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        print("[提醒服务] 已停止")

    def add_callback(self, callback: Callable):
        self._callbacks.append(callback)

    def _run(self):
        while self._running:
            try:
                self._check_and_remind()
            except Exception as e:
                print(f"[提醒服务] 检查出错: {e}")
            time.sleep(self.check_interval)

    def _check_and_remind(self):
        now = datetime.now()
        upcoming = schedule_repo.get_upcoming(minutes=1)

        for schedule in upcoming:
            reminder_key = f"{schedule.id}_{schedule.schedule_date}_{schedule.schedule_time}"
            if reminder_key in self._reminded_ids:
                continue

            today = now.strftime("%Y-%m-%d")
            if schedule.schedule_date != today and schedule.recurrence == "none":
                continue

            self._trigger_reminder(schedule)
            self._reminded_ids.add(reminder_key)

    def _trigger_reminder(self, schedule: Schedule):
        import random
        template = random.choice(self.reminder_templates)
        message = template.format(content=schedule.content)

        print(f"\n{'='*50}")
        print(f"[提醒] {message}")
        print(f"{'='*50}\n")

        for callback in self._callbacks:
            try:
                callback(message)
            except Exception as e:
                print(f"[提醒服务] 回调执行失败: {e}")

    def is_running(self) -> bool:
        return self._running


_reminder_service: Optional[EnhancedReminderService] = None


def get_reminder_service() -> EnhancedReminderService:
    global _reminder_service
    if _reminder_service is None:
        _reminder_service = EnhancedReminderService()
    return _reminder_service
