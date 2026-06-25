"""
单元测试
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

测试NLP解析器、日程服务等功能
"""

import sys
import os
import unittest
from datetime import date, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nlp.parser import NLPParser, Intent, ParsedCommand
from nlp.templates import ResponseGenerator
from database.models import Schedule, RecurrenceType
from database.connection import DatabaseConnection


class TestNLPParser(unittest.TestCase):
    """NLP解析器测试"""

    def setUp(self):
        self.parser = NLPParser()

    def test_detect_add_intent(self):
        """测试添加意图识别"""
        test_cases = [
            "添加日程：下午5点开会",
            "新增明天上午9点有会议",
            "安排下午3点去健身房",
            "加一个日程 明天早上8点起床"
        ]

        for text in test_cases:
            result = self.parser.parse(text)
            self.assertEqual(result.intent, Intent.ADD, f"Failed for: {text}")

    def test_detect_delete_intent(self):
        """测试删除意图识别"""
        test_cases = [
            "删除日程1",
            "取消第2个日程",
            "删掉日程3",
            "移除第1个"
        ]

        for text in test_cases:
            result = self.parser.parse(text)
            self.assertEqual(result.intent, Intent.DELETE, f"Failed for: {text}")

    def test_detect_query_intent(self):
        """测试查询意图识别"""
        test_cases = [
            "我今天的日程有哪些",
            "查看明天的安排",
            "今天的日程",
            "有什么日程"
        ]

        for text in test_cases:
            result = self.parser.parse(text)
            self.assertEqual(result.intent, Intent.QUERY, f"Failed for: {text}")

    def test_extract_time_with_colon(self):
        """测试提取带冒号的时间"""
        result = self.parser.parse("添加日程：14:30开会")
        self.assertEqual(result.schedule_time, "14:30")

    def test_extract_time_with_dian(self):
        """测试提取带"点"的时间"""
        result = self.parser.parse("添加日程：下午3点开会")
        self.assertEqual(result.schedule_time, "15:00")

    def test_extract_time_with_minutes(self):
        """测试提取带分钟的时间"""
        result = self.parser.parse("添加日程：下午3点30分开会")
        self.assertEqual(result.schedule_time, "15:30")

    def test_extract_date_today(self):
        """测试提取今天日期"""
        result = self.parser.parse("今天下午5点开会")
        self.assertEqual(result.schedule_date, date.today().strftime("%Y-%m-%d"))

    def test_extract_date_tomorrow(self):
        """测试提取明天日期"""
        result = self.parser.parse("明天下午5点开会")
        tomorrow = date.today() + timedelta(days=1)
        self.assertEqual(result.schedule_date, tomorrow.strftime("%Y-%m-%d"))

    def test_extract_date_day_after_tomorrow(self):
        """测试提取后天日期"""
        result = self.parser.parse("后天上午9点开会")
        day_after = date.today() + timedelta(days=2)
        self.assertEqual(result.schedule_date, day_after.strftime("%Y-%m-%d"))

    def test_extract_recurrence_daily(self):
        """测试提取每日循环"""
        result = self.parser.parse("每天早上8点提醒我喝水")
        self.assertEqual(result.recurrence, "daily")

    def test_extract_recurrence_weekly(self):
        """测试提取每周循环"""
        result = self.parser.parse("每周一上午9点开会")
        self.assertEqual(result.recurrence, "weekly")

    def test_extract_recurrence_workday(self):
        """测试提取工作日循环"""
        result = self.parser.parse("工作日上午9点上班")
        self.assertEqual(result.recurrence, "workday")

    def test_extract_content(self):
        """测试提取日程内容"""
        result = self.parser.parse("添加日程：下午5点开会")
        self.assertIn("开会", result.content)

    def test_clarification_needed(self):
        """测试需要澄清的情况"""
        result = self.parser.parse("添加日程")
        self.assertIn("时间", result.clarification_needed)
        self.assertIn("日程内容", result.clarification_needed)


class TestResponseGenerator(unittest.TestCase):
    """响应生成器测试"""

    def setUp(self):
        self.generator = ResponseGenerator()

    def test_add_success_response(self):
        """测试添加成功响应"""
        response = self.generator.generate(
            "ADD_SUCCESS",
            content="开会",
            date="今天",
            time="17:00"
        )
        self.assertIn("开会", response)
        self.assertIn("17:00", response)

    def test_delete_success_response(self):
        """测试删除成功响应"""
        response = self.generator.generate(
            "DELETE_SUCCESS",
            id=1,
            time="08:00",
            content="起床"
        )
        self.assertIn("1", response)
        self.assertIn("起床", response)

    def test_query_empty_response(self):
        """测试查询为空响应"""
        response = self.generator.generate("QUERY_EMPTY")
        self.assertTrue(len(response) > 0)

    def test_format_schedule_list(self):
        """测试日程列表格式化"""
        schedules = [
            {"schedule_time": "09:00", "content": "开会"},
            {"schedule_time": "14:00", "content": "健身"}
        ]
        result = self.generator.format_schedule_list(schedules)
        self.assertIn("09:00", result)
        self.assertIn("开会", result)
        self.assertIn("14:00", result)
        self.assertIn("健身", result)

    def test_format_reminder(self):
        """测试提醒格式化"""
        reminder = self.generator.format_reminder("开会")
        self.assertIn("开会", reminder)


class TestScheduleModel(unittest.TestCase):
    """日程模型测试"""

    def test_schedule_to_dict(self):
        """测试日程转字典"""
        schedule = Schedule(
            id=1,
            content="开会",
            schedule_date="2025-01-15",
            schedule_time="17:00",
            recurrence="none"
        )
        data = schedule.to_dict()
        self.assertEqual(data["id"], 1)
        self.assertEqual(data["content"], "开会")
        self.assertEqual(data["schedule_time"], "17:00")

    def test_recurrence_type_enum(self):
        """测试循环类型枚举"""
        self.assertEqual(RecurrenceType.NONE.value, "none")
        self.assertEqual(RecurrenceType.DAILY.value, "daily")
        self.assertEqual(RecurrenceType.WEEKLY.value, "weekly")


class TestDatabase(unittest.TestCase):
    """数据库测试"""

    @classmethod
    def setUpClass(cls):
        """设置测试数据库"""
        cls.db = DatabaseConnection()
        # 使用内存数据库进行测试
        cls.db._connection = None

    def test_connection(self):
        """测试数据库连接"""
        conn = self.db.get_connection()
        self.assertIsNotNone(conn)


def run_tests():
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试
    suite.addTests(loader.loadTestsFromTestCase(TestNLPParser))
    suite.addTests(loader.loadTestsFromTestCase(TestResponseGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestScheduleModel))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabase))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
