# 人工智能 NLP-Agent 数字人项目-基金问答智能体任务
"""
主程序入口 - 基金数据问答智能体

使用方法:
    python main.py "你的问题"
    python main.py --interactive  # 交互模式
"""

import argparse
import json
import sys
from pathlib import Path

from core.agent import FundQAAgent
from core.db import db_manager
from config.settings import settings


def print_header():
    """打印程序头部信息"""
    print("=" * 60)
    print("基金数据问答智能体")
    print("基于 LangGraph + LangChain 实现 NL2SQL")
    print("=" * 60)
    print()


def check_environment():
    """
    检查运行环境

    Returns:
        bool: 环境是否就绪
    """
    print("[检查] 正在检查运行环境...")

    # 检查 API Key
    if not settings.siliconflow_api_key:
        print("[错误] 未设置硅基流动 API Key")
        print("请在 .env 文件中设置 SILICONFLOW_API_KEY")
        return False

    # 检查数据库
    db_path = Path(settings.db_path)
    if not db_path.exists():
        print(f"[警告] 数据库文件不存在: {settings.db_path}")
        print("系统将尝试连接数据库，但可能无法执行查询")
    else:
        print(f"[检查] 数据库文件: {settings.db_path}")

        # 检查表
        try:
            tables = db_manager.list_tables()
            print(f"[检查] 数据库包含 {len(tables)} 张表:")
            for table in tables:
                print(f"       - {table}")
        except Exception as e:
            print(f"[警告] 无法连接数据库: {e}")

    print()
    return True


def ask_question(question: str, show_details: bool = False):
    """
    提问并获取回答

    Args:
        question: 问题
        show_details: 是否显示详细信息
    """
    print(f"[问题] {question}")
    print("-" * 60)

    agent = FundQAAgent()
    result = agent.ask(question)

    if show_details:
        print(f"[SQL] {result.get('sql', 'N/A')}")
        print(f"[查询结果] {result.get('query_result', 'N/A')}")
        print(f"[重试次数] {result.get('retry_count', 0)}")

    if result.get("answer"):
        print(f"[回答]\n{result['answer']}")
    elif result.get("error"):
        print(f"[错误] {result['error']}")
    else:
        print("[回答] 无法生成回答")

    if result.get("error"):
        print(f"[注意] {result['error']}")

    print()


def interactive_mode():
    """交互式问答模式"""
    print("[模式] 进入交互模式，输入 'quit' 或 'exit' 退出")
    print()

    agent = FundQAAgent()

    while True:
        try:
            question = input("请输入您的问题: ").strip()

            if question.lower() in ["quit", "exit", "q"]:
                print("感谢使用，再见！")
                break

            if not question:
                continue

            result = agent.ask(question)

            print("-" * 60)
            print(f"[SQL] {result.get('sql', 'N/A')}")
            print(f"[查询结果] {result.get('query_result', 'N/A')}")
            print()
            print(f"[回答]\n{result.get('answer', '无法生成回答')}")
            print()

            if result.get("error"):
                print(f"[注意] {result['error']}")
            print()

        except KeyboardInterrupt:
            print("\n\n已退出交互模式")
            break
        except Exception as e:
            print(f"\n[错误] {e}\n")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="基金数据问答智能体",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python main.py "2021年涨跌幅最大的股票代码是什么？"
    python main.py -i
    python main.py --interactive
        """
    )

    parser.add_argument(
        "question",
        nargs="?",
        help="要提问的问题"
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="进入交互模式"
    )
    parser.add_argument(
        "-d", "--details",
        action="store_true",
        help="显示详细信息（SQL、查询结果等）"
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="显示数据库表结构"
    )

    args = parser.parse_args()

    print_header()

    # 显示表结构
    if args.schema:
        print("[信息] 数据库表结构:")
        print("-" * 60)
        schema = db_manager.describe_all_tables()
        print(schema)
        print()
        return

    # 检查环境
    if not check_environment():
        sys.exit(1)

    # 根据参数选择模式
    if args.interactive:
        interactive_mode()
    elif args.question:
        ask_question(args.question, args.details)
    else:
        # 默认进入交互模式
        interactive_mode()


if __name__ == "__main__":
    main()
