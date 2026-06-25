"""
日程管理服务
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, date

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Schedule, ScheduleRepository, RecurrenceType, schedule_repo
from nlp.parser import ParsedCommand, Intent
from nlp.templates import ResponseGenerator, response_generator


class ScheduleService:
    """日程管理服务"""

    def __init__(self, repo: Optional[ScheduleRepository] = None,
                 response_gen: Optional[ResponseGenerator] = None):
        self.repo = repo or schedule_repo
        self.response_gen = response_gen or response_generator

    def add_schedule(self, parsed: ParsedCommand) -> Dict[str, Any]:
        if not parsed.content:
            return {
                "success": False,
                "message": self.response_gen.get_clarification(needs_content=True),
                "schedule_id": None
            }

        if not parsed.schedule_time:
            return {
                "success": False,
                "message": self.response_gen.get_clarification(needs_time=True),
                "schedule_id": None
            }

        schedule = Schedule(
            content=parsed.content,
            schedule_date=parsed.schedule_date,
            schedule_time=parsed.schedule_time,
            recurrence=parsed.recurrence
        )

        schedule_id = self.repo.add(schedule)

        if parsed.recurrence != RecurrenceType.NONE.value:
            recurrence_text = self.response_gen.get_recurrence_text(parsed.recurrence)
            message = self.response_gen.generate(
                "ADD_RECURRENCE_SUCCESS",
                content=parsed.content,
                recurrence_text=recurrence_text,
                time=parsed.schedule_time
            )
        else:
            message = self.response_gen.generate(
                "ADD_SUCCESS",
                content=parsed.content,
                date=self._format_date(parsed.schedule_date),
                time=parsed.schedule_time
            )

        return {
            "success": True,
            "message": message,
            "schedule_id": schedule_id
        }

    def delete_schedule(self, schedule_id: int) -> Dict[str, Any]:
        schedule = self.repo.get_by_id(schedule_id)
        if not schedule:
            return {
                "success": False,
                "message": self.response_gen.generate("DELETE_NOT_FOUND", id=schedule_id)
            }

        success = self.repo.delete(schedule_id)
        if success:
            message = self.response_gen.generate(
                "DELETE_SUCCESS",
                id=schedule_id,
                time=schedule.schedule_time,
                content=schedule.content
            )
            return {"success": True, "message": message}
        else:
            return {"success": False, "message": "删除失败，请稍后重试。"}

    def update_schedule(self, schedule_id: int, content: Optional[str] = None,
                        schedule_date: Optional[str] = None,
                        schedule_time: Optional[str] = None) -> Dict[str, Any]:
        schedule = self.repo.get_by_id(schedule_id)
        if not schedule:
            return {
                "success": False,
                "message": f"找不到日程 {schedule_id}，请确认编号是否正确。"
            }

        if content:
            schedule.content = content
        if schedule_date:
            schedule.schedule_date = schedule_date
        if schedule_time:
            schedule.schedule_time = schedule_time

        success = self.repo.update(schedule)
        if success:
            return {
                "success": True,
                "message": self.response_gen.generate("UPDATE_SUCCESS", id=schedule_id)
            }
        else:
            return {"success": False, "message": "修改失败，请稍后重试。"}

    def query_schedules(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        if target_date:
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
        else:
            target = date.today()

        schedules = self.repo.get_by_date(target)
        schedule_list = [s.to_dict() for s in schedules]

        if schedule_list:
            message = self.response_gen.format_schedule_list(schedule_list, target_date)
        else:
            message = self.response_gen.generate("QUERY_EMPTY")

        return {
            "success": True,
            "message": message,
            "schedules": schedule_list
        }

    def complete_schedule(self, schedule_id: int) -> Dict[str, Any]:
        schedule = self.repo.get_by_id(schedule_id)
        if not schedule:
            return {
                "success": False,
                "message": f"找不到日程 {schedule_id}。"
            }

        success = self.repo.mark_completed(schedule_id)
        if success:
            return {
                "success": True,
                "message": self.response_gen.generate("COMPLETE_SUCCESS", content=schedule.content)
            }
        else:
            return {"success": False, "message": "标记完成失败，请稍后重试。"}

    def get_schedule_by_id(self, schedule_id: int) -> Optional[Schedule]:
        return self.repo.get_by_id(schedule_id)

    def get_all_schedules(self) -> List[Schedule]:
        return self.repo.get_all()

    def _format_date(self, date_str: str) -> str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            today = date.today()

            if d == today:
                return "今天"
            elif d == today + __import__('datetime').timedelta(days=1):
                return "明天"
            elif d == today + __import__('datetime').timedelta(days=2):
                return "后天"
            else:
                return f"{d.month}月{d.day}日"
        except:
            return date_str


schedule_service = ScheduleService()


def get_schedule_service() -> ScheduleService:
    return schedule_service
