"""
日程提醒智能体 - 入口文件 (LangChain 版本)
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

支持两种模式：
1. 命令行模式：直接交互
2. Web 模式：提供 HTTP 接口
"""

import os
import sys
import argparse
import threading
import time
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.agent import ScheduleAgent as CustomScheduleAgent, AgentConfig
from agent.llm import SUPPORTED_MODELS
from agent.tools import set_reminder_service
from database.models import schedule_repo
from nlp.templates import response_generator


def create_agent(api_key: str, model: str = "deepseek-ai/DeepSeek-V4-Flash") -> CustomScheduleAgent:
    """工厂函数：创建并初始化一个日程提醒 Agent。"""
    config = AgentConfig(api_key=api_key, model=model)
    return CustomScheduleAgent(config)


# ============ 提醒服务 ============

class ReminderService:
    """定时提醒服务"""

    def __init__(self, check_interval: int = 10):
        self.check_interval = check_interval
        self._running = False
        self._thread: threading.Thread = None
        self._timers: dict[str, threading.Timer] = {}  # schedule_key -> Timer
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[提醒服务] 已启动，定时器模式")

    def stop(self):
        self._running = False
        for t in list(self._timers.values()):
            t.cancel()
        self._timers.clear()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        print("[提醒服务] 已停止")

    def _run(self):
        while self._running:
            try:
                self._check_and_schedule()
            except Exception as e:
                print(f"[提醒服务] 出错: {e}")
            time.sleep(self.check_interval)

    def _check_and_schedule(self):
        """扫描数据库，为所有未来日程设置定时器"""
        now = datetime.now()
        now_ts = now.timestamp()

        for schedule in schedule_repo.get_all():
            key = f"{schedule.id}_{schedule.schedule_date}_{schedule.schedule_time}"
            with self._lock:
                if key in self._timers:
                    continue

            if schedule.is_completed or schedule.reminded:
                continue

            sched_dt_str = f"{schedule.schedule_date} {schedule.schedule_time}:00"
            try:
                sched_dt = datetime.strptime(sched_dt_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if sched_dt.timestamp() <= now_ts:
                continue

            self._schedule_timer(schedule, sched_dt)

    def _schedule_timer(self, schedule, sched_dt: datetime):
        key = f"{schedule.id}_{schedule.schedule_date}_{schedule.schedule_time}"
        delay = sched_dt.timestamp() - datetime.now().timestamp()
        if delay <= 0:
            return

        def fire():
            with self._lock:
                if key not in self._timers:
                    return
                del self._timers[key]

            reminder = self._get_warm_reminder(schedule.content)
            time_str = schedule.schedule_time.replace(":", "点") + "分"
            reminder_text = f"[提醒] {time_str}，{reminder}"
            print(f"\n{'='*50}\n{reminder_text}\n{'='*50}\n")

            try:
                schedule_repo.mark_reminded(schedule.id)
            except Exception:
                pass

        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
            self._timers[key] = threading.Timer(delay, fire)
            self._timers[key].start()

    def schedule_now(self, schedule):
        """添加日程时立即设置定时器"""
        now_ts = datetime.now().timestamp()
        sched_dt_str = f"{schedule.schedule_date} {schedule.schedule_time}:00"
        try:
            sched_dt = datetime.strptime(sched_dt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return
        if sched_dt.timestamp() <= now_ts:
            return
        self._schedule_timer(schedule, sched_dt)

    def cancel(self, schedule):
        """取消某日程的定时器"""
        key = f"{schedule.id}_{schedule.schedule_date}_{schedule.schedule_time}"
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
                del self._timers[key]

    def _get_warm_reminder(self, content: str) -> str:
        """生成温馨提醒"""
        import random
        templates = [
            f"温馨提醒：（{content}）的时间到啦，主人！",
            f"主人！是时候（{content}）了喔~",
            f"亲爱的主人，现在是（{content}）的时候啦！",
            f"嘿，主人，该（{content}）了哦~"
        ]
        return random.choice(templates)


# ============ 配置 ============

def load_api_key() -> str:
    """加载 API Key"""
    api_key = os.environ.get("SILICONFLOW_API_KEY", "")

    if not api_key:
        config_file = os.path.join(os.path.dirname(__file__), "config.txt")
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                api_key = f.read().strip()

    if not api_key:
        api_key = input("请输入 SiliconFlow API Key: ").strip()

    return api_key


def get_model() -> str:
    """获取模型名称"""
    models = list(SUPPORTED_MODELS.values())

    print("\n可用模型:")
    for i, (key, model) in enumerate(SUPPORTED_MODELS.items(), 1):
        print(f"  {i}. {key} -> {model}")

    print(f"\n[默认选择] Qwen/Qwen2.5-7B-Instruct")

    choice = input("选择模型 (直接回车使用默认): ").strip()
    if not choice:
        return "Qwen/Qwen2.5-7B-Instruct"

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(models):
            return models[idx]
    except ValueError:
        pass

    # 检查直接输入的模型名
    for model in models:
        if choice.lower() in model.lower():
            return model

    return "Qwen/Qwen2.5-7B-Instruct"


# ============ 命令行模式 ============

def run_cli(agent, reminder_service=None):
    """命令行交互模式"""
    print("\n" + "=" * 50)
    print("  日程提醒智能体 (LangChain 版本)")
    print("  输入 'quit' 或 'exit' 退出")
    print("=" * 50 + "\n")

    while True:
        try:
            user_input = input("你: ").strip()

            if user_input.lower() in ["quit", "exit", "q", "退出"]:
                print("\n再见！祝您生活愉快~")
                break

            if not user_input:
                continue

            # 调试命令
            if user_input.lower() in ["status", "状态", "debug"]:
                from database.models import schedule_repo
                from datetime import datetime
                now = datetime.now()
                print(f"\n[调试] 当前时间: {now.strftime('%H:%M:%S')}")

                schedules = schedule_repo.get_upcoming(minutes=60)
                print(f"[调试] 即将到来的日程 ({len(schedules)}个):")
                for s in schedules:
                    print(f"  - [{s.schedule_time}] {s.content}")
                continue

            print("\n助理思考中...")
            response = agent.run(user_input)
            print(f"\n助理: {response}\n")

        except KeyboardInterrupt:
            print("\n\n已退出")
            break
        except Exception as e:
            print(f"\n错误: {e}\n")


# ============ Web 模式 ============

def run_web(agent, reminder_service=None, host="0.0.0.0", port=5000):
    """Web 服务模式"""
    from flask import Flask, request, jsonify, render_template_string

    app = Flask(__name__)

    # HTML 模板
    HTML_TEMPLATE = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>日程提醒智能体</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
            }
            .card {
                background: white;
                border-radius: 16px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                overflow: hidden;
            }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 24px;
                text-align: center;
            }
            .header h1 { font-size: 24px; margin-bottom: 8px; }
            .header p { opacity: 0.9; font-size: 14px; }
            .chat {
                height: 400px;
                overflow-y: auto;
                padding: 20px;
                background: #f8f9fa;
            }
            .message {
                margin-bottom: 16px;
                animation: fadeIn 0.3s ease;
            }
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }
            .user-msg {
                background: #007bff;
                color: white;
                padding: 12px 16px;
                border-radius: 16px 16px 4px 16px;
                max-width: 80%;
                margin-left: auto;
            }
            .bot-msg {
                background: white;
                color: #333;
                padding: 12px 16px;
                border-radius: 16px 16px 16px 4px;
                max-width: 80%;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            .input-area {
                display: flex;
                padding: 16px;
                background: white;
                border-top: 1px solid #eee;
            }
            .input-area input {
                flex: 1;
                padding: 12px 16px;
                border: 2px solid #e0e0e0;
                border-radius: 24px;
                font-size: 16px;
                outline: none;
                transition: border-color 0.3s;
            }
            .input-area input:focus {
                border-color: #667eea;
            }
            .input-area button {
                margin-left: 12px;
                padding: 12px 24px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 24px;
                font-size: 16px;
                cursor: pointer;
                transition: transform 0.2s, box-shadow 0.2s;
            }
            .input-area button:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(102,126,234,0.4);
            }
            .loading {
                text-align: center;
                padding: 20px;
                color: #666;
            }
            .loading::after {
                content: '...';
                animation: dots 1.5s steps(4, end) infinite;
            }
            @keyframes dots {
                0%, 20% { content: '.'; }
                40% { content: '..'; }
                60%, 100% { content: '...'; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <div class="header">
                    <h1>日程提醒智能体</h1>
                    <p>基于 LangChain + SiliconFlow</p>
                </div>
                <div class="chat" id="chat">
                    <div class="message bot-msg">
                        你好！我是日程提醒智能体，有什么可以帮你的吗？
                    </div>
                </div>
                <div class="input-area">
                    <input type="text" id="userInput" placeholder="输入你的问题..." onkeypress="handleKeyPress(event)">
                    <button onclick="sendMessage()">发送</button>
                </div>
            </div>
        </div>

        <script>
            function addMessage(text, isUser) {
                const chat = document.getElementById('chat');
                const msg = document.createElement('div');
                msg.className = `message ${isUser ? 'user-msg' : 'bot-msg'}`;
                msg.textContent = text;
                chat.appendChild(msg);
                chat.scrollTop = chat.scrollHeight;
            }

            function showLoading() {
                const chat = document.getElementById('chat');
                const loading = document.createElement('div');
                loading.id = 'loading';
                loading.className = 'loading';
                loading.textContent = '助理思考中';
                chat.appendChild(loading);
                chat.scrollTop = chat.scrollHeight;
            }

            function hideLoading() {
                const loading = document.getElementById('loading');
                if (loading) loading.remove();
            }

            async function sendMessage() {
                const input = document.getElementById('userInput');
                const text = input.value.trim();
                if (!text) return;

                addMessage(text, true);
                input.value = '';
                showLoading();

                try {
                    const response = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message: text })
                    });
                    const data = await response.json();
                    hideLoading();
                    addMessage(data.response, false);
                } catch (error) {
                    hideLoading();
                    addMessage('抱歉，服务出错了', false);
                }
            }

            function handleKeyPress(event) {
                if (event.key === 'Enter') sendMessage();
            }
        </script>
    </body>
    </html>
    """

    @app.route("/")
    def index():
        """首页"""
        return render_template_string(HTML_TEMPLATE)

    @app.route("/api/chat", methods=["POST"])
    def chat():
        """对话接口"""
        data = request.get_json()
        user_input = data.get("message", "")

        if not user_input:
            return jsonify({"error": "请输入内容"})

        try:
            response = agent.run(user_input)
            return jsonify({"response": response})
        except Exception as e:
            return jsonify({"error": str(e)})

    print(f"\n🚀 Web 服务已启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)


# ============ 主函数 ============

def main():
    parser = argparse.ArgumentParser(description="日程提醒智能体")
    parser.add_argument("--web", action="store_true", help="启动 Web 模式")
    parser.add_argument("--host", default="0.0.0.0", help="Web 服务地址")
    parser.add_argument("--port", type=int, default=5000, help="Web 服务端口")
    parser.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash", help="模型名称")
    parser.add_argument("--no-reminder", action="store_true", help="禁用提醒服务")

    args = parser.parse_args()

    # 加载配置
    api_key = load_api_key()
    model = args.model

    if not api_key:
        print("错误: 请配置 SiliconFlow API Key")
        sys.exit(1)

    # 创建 Agent
    print(f"\n初始化 Agent (模型: {model})...")
    agent = create_agent(api_key=api_key, model=model)
    print("✅ Agent 初始化完成！\n")

    # 启动提醒服务
    reminder_service = None
    if not args.no_reminder:
        reminder_service = ReminderService(check_interval=30)
        reminder_service.start()
        set_reminder_service(reminder_service)

    # 启动模式
    try:
        if args.web:
            run_web(agent, reminder_service, host=args.host, port=args.port)
        else:
            run_cli(agent, reminder_service)
    finally:
        if reminder_service:
            reminder_service.stop()


if __name__ == "__main__":
    main()
