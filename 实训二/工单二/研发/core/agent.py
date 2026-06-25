"""
智能体核心
"""

from typing import Dict, Any, Optional
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nlp.parser import NLPParser, Intent, get_parser
from nlp.templates import ResponseGenerator, response_generator
from services.schedule_service import ScheduleService, schedule_service
from services.response_service import ResponseService, response_service
from services.reminder_service import ReminderService, reminder_service


class ScheduleAgent:
    """日程提醒智能体"""

    def __init__(
        self,
        nlp_parser: Optional[NLPParser] = None,
        response_gen: Optional[ResponseGenerator] = None,
        schedule_service: Optional[ScheduleService] = None,
        response_service: Optional[ResponseService] = None,
        reminder_service: Optional[ReminderService] = None
    ):
        self.nlp = nlp_parser or get_parser()
        self.response_gen = response_gen or response_generator
        self.schedule_service = schedule_service or schedule_service
        self.response_service = response_service or response_service
        self.reminder_service = reminder_service

    def process(self, user_input: str) -> str:
        """处理用户输入"""
        parsed = self.nlp.parse(user_input)

        if parsed.intent == Intent.ADD:
            return self._handle_add(parsed)
        elif parsed.intent == Intent.DELETE:
            return self._handle_delete(parsed)
        elif parsed.intent == Intent.UPDATE:
            return self._handle_update(parsed)
        elif parsed.intent == Intent.QUERY:
            return self._handle_query(parsed)
        elif parsed.intent == Intent.COMPLETE:
            return self._handle_complete(parsed)
        elif parsed.intent == Intent.HELP:
            return self._handle_help()
        else:
            return self._handle_unknown(parsed)

    def _handle_add(self, parsed) -> str:
        if parsed.clarification_needed:
            needs_time = "时间" in parsed.clarification_needed
            needs_content = "日程内容" in parsed.clarification_needed
            return self.response_gen.get_clarification(
                needs_time=needs_time,
                needs_content=needs_content
            )

        result = self.schedule_service.add_schedule(parsed)
        return result["message"]

    def _handle_delete(self, parsed) -> str:
        schedule_id = parsed.schedule_id

        if not schedule_id:
            if parsed.content:
                return f"请告诉我您想删除的日程编号，比如「删除日程1」。"
            return "请告诉我您想删除哪个日程的编号？"

        result = self.schedule_service.delete_schedule(schedule_id)
        return result["message"]

    def _handle_update(self, parsed) -> str:
        if not parsed.schedule_id:
            return "请告诉我您想修改哪个日程的编号？"

        result = self.schedule_service.update_schedule(
            schedule_id=parsed.schedule_id,
            content=parsed.content if parsed.content else None,
            schedule_date=parsed.schedule_date,
            schedule_time=parsed.schedule_time
        )
        return result["message"]

    def _handle_query(self, parsed) -> str:
        result = self.schedule_service.query_schedules(parsed.schedule_date)
        return result["message"]

    def _handle_complete(self, parsed) -> str:
        if not parsed.schedule_id:
            return "请告诉我您完成了哪个日程的编号？"

        result = self.schedule_service.complete_schedule(parsed.schedule_id)
        return result["message"]

    def _handle_help(self) -> str:
        return self.response_gen.templates.HELP

    def _handle_unknown(self, parsed) -> str:
        if self.nlp._contains_time(parsed.raw_input):
            return "我理解您想安排时间，但我没有完全理解您的意思。请试试这样跟我说：「添加日程：下午3点开会」"

        return self.response_gen.generate("ERROR")

    def start_reminder_service(self):
        if self.reminder_service and not self.reminder_service._running:
            self.reminder_service.start()

    def stop_reminder_service(self):
        if self.reminder_service and self.reminder_service._running:
            self.reminder_service.stop()


agent = ScheduleAgent()


def get_agent() -> ScheduleAgent:
    return agent
