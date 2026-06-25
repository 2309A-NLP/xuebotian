# 人工智能NLP-Agent数字人项目-记账本任务
# 工单编号：人工智能NLP-Agent数字人项目-记账本任务V1.1-20250206

"""
家庭记账本智能体主程序
功能：自然语言记账、查询、统计、删除家庭支出收入
成员：爸爸、妈妈、女儿
API：硅基流动 SiliconFlow
SQL：由大模型动态生成
"""

import os
import sqlite3
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, AIMessage

# 硅基流动API配置
SILICON_FLOW_API_URL = "https://api.siliconflow.cn/v1"
SILICON_FLOW_MODEL = "Qwen/Qwen2.5-72B-Instruct"  # 可选: Pro/deepseek-ai/DeepSeek-V3, Qwen/Qwen2.5-72B-Instruct 等

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "account_book.db")


class AccountBookDB:
    """家庭记账本数据库操作类（仅负责初始化）"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库，创建表"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建记账表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS money_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                member TEXT NOT NULL,
                category TEXT NOT NULL,
                item TEXT NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('收入', '支出')),
                note TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建索引优化查询
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_member ON money_notes(member)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON money_notes(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_type ON money_notes(type)")

        conn.commit()
        conn.close()

    def get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def execute_query(self, sql: str, params: tuple = ()) -> List[Dict]:
        """执行查询SQL，返回结果列表"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(sql, params)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            conn.close()

            result = []
            for row in rows:
                result.append(dict(zip(columns, row)))
            return result
        except Exception as e:
            conn.close()
            raise Exception(f"SQL执行错误：{str(e)}\nSQL: {sql}\n参数: {params}")

    def execute_update(self, sql: str, params: tuple = ()) -> dict:
        """执行更新SQL（INSERT/UPDATE/DELETE），返回执行结果"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(sql, params)
            conn.commit()

            if sql.strip().upper().startswith("INSERT"):
                record_id = cursor.lastrowid
                conn.close()
                return {"success": True, "message": f"添加成功，记录ID: {record_id}", "id": record_id}
            elif sql.strip().upper().startswith("DELETE"):
                affected = cursor.rowcount
                conn.close()
                return {"success": True, "message": f"删除成功，影响 {affected} 条记录"}
            else:
                affected = cursor.rowcount
                conn.close()
                return {"success": True, "message": f"更新成功，影响 {affected} 条记录"}

        except Exception as e:
            conn.close()
            raise Exception(f"SQL执行错误：{str(e)}\nSQL: {sql}\n参数: {params}")

    def get_all_records(self) -> List[Dict]:
        """获取所有记录"""
        return self.execute_query("""
            SELECT id, date, member, category, item, amount, type, note, created_at
            FROM money_notes
            ORDER BY date DESC, id DESC
        """)


class SQLAgent:
    """SQL生成与执行智能体"""

    # 允许执行的SQL类型（安全限制）
    ALLOWED_OPERATIONS = ["SELECT", "INSERT", "UPDATE", "DELETE"]
    # 禁止的SQL关键词
    FORBIDDEN_KEYWORDS = ["DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC", "EXECUTE"]

    def __init__(self, api_key: str = None):
        """初始化智能体"""
        self.db = AccountBookDB()
        self.api_key = api_key or os.environ.get("SILICON_FLOW_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")

        if self.api_key:
            # 使用硅基流动API
            self.llm = ChatOpenAI(
                model=SILICON_FLOW_MODEL,
                api_key=self.api_key,
                base_url=SILICON_FLOW_API_URL,
                temperature=0.1  # 降低温度以获得更稳定的SQL生成
            )
        else:
            self.llm = None

        self.conversation_history: List[Dict] = []

    def _validate_sql(self, sql: str) -> tuple:
        """
        验证SQL语句安全性
        返回: (是否安全, 操作类型, 错误信息)
        """
        sql_upper = sql.strip().upper()

        # 提取SQL首词进行检查
        first_word = sql_upper.split()[0] if sql_upper.split() else ""

        # 检查禁止的操作（必须是SQL开头）
        for keyword in self.FORBIDDEN_KEYWORDS:
            if first_word == keyword:
                return False, "", f"禁止使用 {keyword} 操作"

        # 检查允许的操作（必须是SQL开头）
        for op in self.ALLOWED_OPERATIONS:
            if first_word == op:
                return True, op, ""

        return False, "", f"只允许使用: {', '.join(self.ALLOWED_OPERATIONS)}"

    def generate_sql(self, user_input: str) -> str:
        """
        使用大模型根据用户输入生成SQL语句
        """
        if not self.llm:
            raise Exception("未设置API Key，无法生成SQL")

        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")

        sql_generation_prompt = f"""你是SQL生成专家，根据用户需求生成SQL语句。

当前时间：{current_time}
数据库表结构：
```sql
CREATE TABLE money_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,           -- 日期，格式：YYYY-MM-DD
    member TEXT NOT NULL,         -- 成员：爸爸、妈妈、女儿
    category TEXT NOT NULL,       -- 类别
    item TEXT NOT NULL,           -- 物品/事项名称
    amount REAL NOT NULL,         -- 金额（支出为正数）
    type TEXT NOT NULL,           -- 类型：收入、支出
    note TEXT,                    -- 备注
    created_at TEXT               -- 创建时间
);
```

家庭成员：爸爸、妈妈、女儿

支出类别：餐饮、交通、购物、娱乐、教育、医疗、旅游、服装、日用品、通讯、居住、书籍、其他

收入类别：工资、奖金、报销、投资收益、兼职、补贴、其他

【重要规则】
1. 日期处理：
   - "今天" -> {datetime.now().strftime("%Y-%m-%d")}
   - "昨天" -> {datetime.now().replace(day=datetime.now().day - 1).strftime("%Y-%m-%d")}
   - "本月" -> {datetime.now().strftime("%Y-%m")} 的第一天到最后一天
   - "上月" -> 上个月的第一天到最后一天
   - "X月X日" -> 今年对应的日期，如 "7月5日" -> {datetime.now().year}-07-05

2. 类型判断：
   - 买东西、消费、支出、花了 -> type = '支出'
   - 收到、发工资、报销、收入、赚钱 -> type = '收入'

3. 金额：只提取数字，如"499元" -> 499

4. 类别匹配：
   - 买书、书 -> 书籍
   - 旅游、报团 -> 旅游
   - 吃饭、餐厅 -> 餐饮
   - 工资、月薪 -> 工资

5. 只生成 SELECT、INSERT、UPDATE、DELETE 语句

6. 严格遵循用户输入，不要推测

请生成SQL语句：

用户输入：{user_input}

只返回SQL语句，不要其他内容："""

        response = self.llm.invoke(sql_generation_prompt)
        sql = response.content.strip()

        # 清理SQL（移除可能的markdown代码块标记）
        if sql.startswith("```"):
            lines = sql.split("\n")
            sql = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        return sql.strip()

    def execute_sql(self, sql: str) -> str:
        """
        执行SQL语句并返回结果
        SQL由大模型动态生成
        """
        # 验证SQL安全性
        is_safe, operation, error_msg = self._validate_sql(sql)
        if not is_safe:
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)

        try:
            if operation == "SELECT":
                result = self.db.execute_query(sql)
                return json.dumps({
                    "success": True,
                    "operation": "SELECT",
                    "count": len(result),
                    "data": result
                }, ensure_ascii=False, indent=2)
            else:
                result = self.db.execute_update(sql)
                return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False, indent=2)

    def process_message(self, user_input: str) -> str:
        """处理用户消息：生成SQL -> 执行 -> 返回结果"""
        if not self.llm:
            return "错误：请设置SILICON_FLOW_API_KEY或OPENAI_API_KEY环境变量"

        # 1. 生成SQL
        try:
            sql = self.generate_sql(user_input)
        except Exception as e:
            return f"SQL生成失败：{str(e)}"

        # 2. 执行SQL
        try:
            result = self.execute_sql(sql)
            result_data = json.loads(result)

            if not result_data.get("success", False):
                return f"SQL执行失败：{result_data.get('error', '未知错误')}\n生成的SQL：{sql}"

            # 3. 格式化结果返回给用户
            return self._format_result(user_input, sql, result_data)

        except Exception as e:
            return f"执行出错：{str(e)}\nSQL: {sql}"

    def _format_result(self, user_input: str, sql: str, result: dict) -> str:
        """格式化SQL执行结果为友好的人类语言"""
        if not self.llm:
            return "未设置API Key"

        format_prompt = f"""将SQL执行结果转换为人类友好的回复。

原始用户输入：{user_input}
执行的SQL：{sql}
执行结果：{json.dumps(result, ensure_ascii=False)}

【回复要求】
1. 简洁友好
2. 涉及金额说明单位（元）
3. 查询结果要清晰列出
4. 如果是添加成功，说明记录了什么
5. 如果是删除成功，说明删除了什么
6. 如果没有数据，说明情况

只返回回复内容，不要说明SQL或过程："""

        try:
            response = self.llm.invoke(format_prompt)
            return response.content.strip()
        except Exception:
            # 如果格式化失败，返回原始结果
            return f"操作完成，结果：{json.dumps(result, ensure_ascii=False)}"

    def run_cli(self):
        """命令行交互"""
        print("=" * 50)
        print("🏠 欢迎使用小家记账本智能体")
        print("=" * 50)
        print()
        print("【功能说明】")
        print("  • 记账：今天女儿买了双登山鞋499元")
        print("  • 查询：这个月女儿花了多少钱？")
        print("  • 统计：看我这个月买书花了多少")
        print("  • 删除：删除女儿报旅游团的费用")
        print("  • 退出：输入 'quit' 或 'exit' 退出")
        print()
        print("=" * 50)
        print()

        # 如果没有API Key，提供模拟模式
        if not self.api_key:
            print("⚠️  未检测到 SILICON_FLOW_API_KEY，进入模拟模式")
            print("   模拟模式仅演示基本功能")
            print()
            self._run_simulated_cli()
            return

        while True:
            try:
                user_input = input("👤 你: ").strip()

                if user_input.lower() in ["quit", "exit", "退出"]:
                    print("\n👋 感谢使用小家记账本，再见！")
                    break

                if not user_input:
                    continue

                print("\n🤖 智能体处理中...")
                print(f"   1. 生成SQL...")
                response = self.process_message(user_input)
                print(f"\n💰 记账本: {response}\n")

            except KeyboardInterrupt:
                print("\n\n👋 已退出")
                break
            except Exception as e:
                print(f"\n❌ 出错：{str(e)}\n")

    def _run_simulated_cli(self):
        """模拟命令行交互（无API Key时）"""
        print("💡 模拟模式示例：")
        print()

        # 模拟添加记录
        print("📝 模拟添加记录（直接使用SQL）：")
        sql = """
        INSERT INTO money_notes (date, member, category, item, amount, type)
        VALUES ('2025-07-05', '女儿', '购物', '登山鞋', 499, '支出')
        """
        result = self.db.execute_update(sql)
        print(f"   SQL: {sql.strip()}")
        print(f"   结果: {result['message']}")

        sql = """
        INSERT INTO money_notes (date, member, category, item, amount, type)
        VALUES ('2025-07-05', '妈妈', '报销', '工作报销', 1000, '收入')
        """
        result = self.db.execute_update(sql)
        print(f"   SQL: {sql.strip()}")
        print(f"   结果: {result['message']}")
        print()

        # 模拟查询
        print("📊 模拟查询（直接使用SQL）：")
        sql = """
        SELECT * FROM money_notes
        WHERE member = '女儿' AND type = '支出'
        ORDER BY date DESC
        """
        result = self.db.execute_query(sql)
        print(f"   SQL: {sql.strip()}")
        print(f"   结果: 找到 {len(result)} 条记录")
        for r in result:
            print(f"   - {r['date']} {r['item']} {r['amount']}元")
        print()

        # 显示所有记录
        print("📋 所有记账记录：")
        all_records = self.db.get_all_records()
        for r in all_records:
            print(f"   [{r['id']}] {r['date']} {r['member']} {r['category']} {r['item']} {r['type']} {r['amount']}元")
        print()

        # 模拟删除
        print("🗑️ 模拟删除记录（ID=1）")
        sql = "DELETE FROM money_notes WHERE id = 1"
        result = self.db.execute_update(sql)
        print(f"   SQL: {sql}")
        print(f"   结果: {result['message']}")
        print()

        print("✅ 模拟模式演示完成！")
        print("💡 如需启用真实AI功能，请重新运行程序并输入API Key")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="小家记账本智能体")
    parser.add_argument("--api-key", "-k", help="硅基流动API Key")
    parser.add_argument("--db-path", "-d", help="数据库路径")

    args = parser.parse_args()

    if args.db_path:
        global DB_PATH
        DB_PATH = args.db_path

    # 获取API Key：优先命令行参数，其次提示用户输入
    api_key = args.api_key
    if not api_key:
        print("=" * 50)
        print("🔑 请输入硅基流动API Key")
        print("   （访问 https://www.siliconflow.cn/ 获取）")
        print("=" * 50)
        api_key = input("API Key: ").strip()

    if not api_key:
        print("❌ 未提供API Key，无法启动")
        return

    agent = SQLAgent(api_key=api_key)
    agent.run_cli()


if __name__ == "__main__":
    main()
