"""
集成测试
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

测试完整的对话流程
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent import ScheduleAgent
from database.models import schedule_repo
from database.connection import get_db


class TestAgentConversation(unittest.TestCase):
    """智能体对话集成测试"""

    @classmethod
    def setUpClass(cls):
        """初始化测试环境"""
        # 初始化数据库
        db = get_db()
        # 创建测试数据库
        db._connection = None

        # 创建表
        schedule_repo.create_table()
        schedule_repo.create_reminder_logs_table()

        # 创建智能体
        cls.agent = ScheduleAgent()

    @classmethod
    def tearDownClass(cls):
        """清理测试环境"""
        # 清理测试数据
        db = get_db()
        db.execute("DELETE FROM schedules")
        db.get_connection().commit()

    def test_add_schedule_conversation(self):
        """测试添加日程对话"""
        response = self.agent.process("添加日程：下午5点开会")
        self.assertTrue(len(response) > 0)
        self.assertTrue(any(keyword in response for keyword in ["记录", "安排", "日程", "开会"]))

    def test_query_conversation(self):
        """测试查询日程对话"""
        # 先添加一个日程
        self.agent.process("添加日程：下午3点去健身房")

        # 查询
        response = self.agent.process("我今天的日程有哪些")
        self.assertTrue(len(response) > 0)

    def test_delete_conversation(self):
        """测试删除日程对话"""
        # 先添加一个日程
        self.agent.process("添加日程：明天上午9点有会议")

        # 删除
        response = self.agent.process("删除日程1")
        self.assertTrue(len(response) > 0)
        self.assertTrue(any(keyword in response for keyword in ["删除", "取消", "移除"]))

    def test_help_conversation(self):
        """测试帮助对话"""
        response = self.agent.process("help")
        self.assertIn("添加日程", response)
        self.assertIn("查询", response)

    def test_clarification_conversation(self):
        """测试澄清对话"""
        response = self.agent.process("添加日程")
        self.assertTrue(len(response) > 0)
        # 应该提示用户补充信息

    def test_recurrence_conversation(self):
        """测试循环日程对话"""
        response = self.agent.process("每天早上8点提醒我喝水")
        self.assertTrue(len(response) > 0)
        self.assertTrue(any(keyword in response for keyword in ["每天", "记录", "安排"]))


class TestEndToEnd(unittest.TestCase):
    """端到端测试"""

    @classmethod
    def setUpClass(cls):
        """初始化环境"""
        db = get_db()
        schedule_repo.create_table()
        schedule_repo.create_reminder_logs_table()

        # 清理
        db.execute("DELETE FROM schedules")
        db.get_connection().commit()

        cls.agent = ScheduleAgent()

    def test_full_workflow(self):
        """测试完整工作流"""
        # 1. 添加多个日程
        self.agent.process("添加日程：今天上午9点开会")
        self.agent.process("添加日程：今天下午2点健身")
        self.agent.process("添加日程：明天上午10点拜访客户")

        # 2. 查询今天的日程
        response = self.agent.process("我今天的日程有哪些")
        self.assertIn("9", response)  # 9:00
        self.assertIn("14", response)  # 14:00

        # 3. 删除一个日程
        self.agent.process("删除日程1")

        # 4. 再次查询
        response = self.agent.process("我今天的日程有哪些")
        self.assertIn("14", response)  # 健身


if __name__ == "__main__":
    unittest.main(verbosity=2)
