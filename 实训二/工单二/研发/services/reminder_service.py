"""
定时提醒服务
"""

import time
import threading
from typing import Callable, Optional, List
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Schedule, schedule_repo
from nlp.templates import ResponseGenerator, response_generator


class ReminderService:
    """定时提醒服务"""

    def __init__(self, check_interval: int = 30,
                 on_remind: Optional[Callable[[str], None]] = None,
                 response_gen: Optional[ResponseGenerator] = None):
        self.response_gen = response_gen or response_generator
        self.check_interval = check_interval
        self.on_remind_callback = on_remind
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._reminded_ids: set = set()

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
        message = self.response_gen.format_reminder(schedule.content)

        if self.on_remind_callback:
            self.on_remind_callback(message)
        else:
            print(f"[提醒] {message}")

    def set_remind_callback(self, callback: Callable[[str], None]):
        self.on_remind_callback = callback

    def check_now(self) -> List[Schedule]:
        return schedule_repo.get_upcoming(minutes=1)


reminder_service = ReminderService()


def get_reminder_service() -> ReminderService:
    return reminder_service
