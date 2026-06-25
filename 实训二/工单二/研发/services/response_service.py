"""
响应生成服务
"""

from typing import Dict, Any, List, Optional
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nlp.templates import ResponseGenerator, response_generator


class ResponseService:
    """响应生成服务"""

    def __init__(self, response_gen: Optional[ResponseGenerator] = None):
        self.response_gen = response_gen or response_generator

    def format_success(self, message: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        response = {"success": True, "message": message, "code": 200}
        if data:
            response["data"] = data
        return response

    def format_error(self, message: str, code: int = 400) -> Dict[str, Any]:
        return {"success": False, "message": message, "code": code}

    def format_schedule_list_response(self, schedules: List[Dict]) -> Dict[str, Any]:
        if not schedules:
            message = self.response_gen.generate("QUERY_EMPTY")
        else:
            message = self.response_gen.format_schedule_list(schedules)
        return self.format_success(message, {"schedules": schedules})

    def format_help(self) -> Dict[str, Any]:
        help_text = self.response_gen.templates.HELP
        return self.format_success(help_text)


response_service = ResponseService()


def get_response_service() -> ResponseService:
    return response_service
