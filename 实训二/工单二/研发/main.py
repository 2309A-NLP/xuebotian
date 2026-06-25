"""
主入口文件
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

日程提醒智能体主程序
支持命令行交互和Web接口
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from datetime import datetime

from database.connection import get_db
from database.models import schedule_repo
from core.agent import ScheduleAgent, get_agent
from core.scheduler import Scheduler, get_scheduler
from services.reminder_service import ReminderService, get_reminder_service
from config.settings import get_settings


class CLIInterface:
    """命令行界面"""

    def __init__(self, agent: ScheduleAgent, reminder_service: ReminderService):
        self.agent = agent
        self.reminder_service = reminder_service

    def print_welcome(self):
        """打印欢迎信息"""
        print("\n" + "=" * 50)
        print("      日程提醒智能体")
        print("      Agent 数字人项目")
        print("=" * 50)
        print("\n您好！我是您的日程提醒助手~")
        print("我可以帮您：")
        print("  - 添加日程：添加日程：下午5点开会")
        print("  - 查看日程：我今天的日程有哪些")
        print("  - 删除日程：删除日程1")
        print("  - 完成日程：完成日程1")
        print("  - 循环日程：每天早上8点提醒我喝水")
        print("\n输入 'help' 查看更多帮助，输入 'quit' 退出")
        print("-" * 50)

    def handle_reminder(self, message: str):
        """处理提醒回调"""
        print("\n" + "=" * 50)
        print(f"[提醒] {message}")
        print("=" * 50 + "\n")

    def run(self):
        """运行交互式命令行"""
        # 设置提醒回调
        self.agent.set_reminder_callback(self.handle_reminder)

        # 启动提醒服务
        self.agent.start_reminder_service()

        self.print_welcome()

        try:
            while True:
                try:
                    user_input = input("\n您: ").strip()
                except KeyboardInterrupt:
                    print("\n\n收到退出信号，正在关闭...")
                    break

                if not user_input:
                    continue

                # 处理命令
                if user_input.lower() in ['quit', 'exit', '退出', 'q']:
                    print("再见，主人！记得按时完成任务哦~")
                    break
                elif user_input.lower() in ['help', '帮助', 'h']:
                    from nlp.templates import response_generator
                    print(response_generator.templates.HELP)
                    continue
                elif user_input.lower() in ['today', '今天的日程', '日程']:
                    user_input = "我今天的日程有哪些"

                # 处理输入
                response = self.agent.process(user_input)
                print(f"\n智能体: {response}")

        finally:
            # 停止提醒服务
            self.agent.stop_reminder_service()


class WebInterface:
    """Web接口（Flask）"""

    def __init__(self, agent: ScheduleAgent, reminder_service: ReminderService):
        self.agent = agent
        self.reminder_service = reminder_service
        self.app = None

    def _init_flask(self):
        """初始化Flask应用"""
        try:
            from flask import Flask, request, jsonify
        except ImportError:
            print("Flask 未安装，请运行: pip install flask")
            return None

        app = Flask(__name__)

        @app.route('/api/chat', methods=['POST'])
        def chat():
            """处理对话请求"""
            data = request.get_json()
            user_input = data.get('message', '')
            response = self.agent.process(user_input)
            return jsonify({
                'success': True,
                'response': response
            })

        @app.route('/api/schedules', methods=['GET'])
        def get_schedules():
            """获取日程列表"""
            result = self.agent.schedule_service.query_schedules()
            return jsonify(result)

        @app.route('/api/schedules', methods=['POST'])
        def add_schedule():
            """添加日程"""
            data = request.get_json()
            from nlp.parser import ParsedCommand
            parsed = ParsedCommand(
                intent=__import__('nlp.parser', fromlist=['Intent']).Intent.ADD,
                content=data.get('content', ''),
                schedule_date=data.get('date', datetime.now().strftime('%Y-%m-%d')),
                schedule_time=data.get('time', ''),
                recurrence=data.get('recurrence', 'none')
            )
            result = self.agent.schedule_service.add_schedule(parsed)
            return jsonify(result)

        @app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
        def delete_schedule(schedule_id):
            """删除日程"""
            result = self.agent.schedule_service.delete_schedule(schedule_id)
            return jsonify(result)

        @app.route('/health', methods=['GET'])
        def health():
            """健康检查"""
            return jsonify({'status': 'ok'})

        return app

    def run(self, host='0.0.0.0', port=5000):
        """运行Web服务"""
        self.app = self._init_flask()
        if self.app:
            # 启动提醒服务
            self.agent.set_reminder_callback(
                lambda msg: print(f"[提醒] {msg}")
            )
            self.agent.start_reminder_service()

            print(f"Web服务启动中... http://{host}:{port}")
            self.app.run(host=host, port=port, debug=False)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="日程提醒智能体")
    parser.add_argument("--web", action="store_true", help="启动Web界面")
    parser.add_argument("--host", default="0.0.0.0", help="Web服务地址")
    parser.add_argument("--port", type=int, default=5000, help="Web服务端口")
    parser.add_argument("--no-reminder", action="store_true", help="不启动提醒服务")
    args = parser.parse_args()

    # 初始化数据库
    print("正在初始化数据库...")
    schedule_repo.create_table()
    schedule_repo.create_reminder_logs_table()
    print("数据库初始化完成！\n")

    # 创建智能体
    agent = get_agent()

    # 创建提醒服务
    reminder_service = get_reminder_service()
    if args.no_reminder:
        reminder_service = None
    else:
        agent.reminder_service = reminder_service

    # 启动界面
    if args.web:
        interface = WebInterface(agent, reminder_service)
        interface.run(host=args.host, port=args.port)
    else:
        interface = CLIInterface(agent, reminder_service)
        interface.run()


if __name__ == "__main__":
    main()
