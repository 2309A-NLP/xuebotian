"""
数据库初始化脚本
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.connection import get_db
from database.models import schedule_repo


def init_database():
    """初始化数据库"""
    print("正在初始化数据库...")

    db = get_db()

    try:
        # 创建日程表
        print("创建日程表...")
        schedule_repo.create_table()
        print("日程表创建成功！")

        # 创建提醒日志表
        print("创建提醒日志表...")
        schedule_repo.create_reminder_logs_table()
        print("提醒日志表创建成功！")

        print("\n数据库初始化完成！")
        return True

    except Exception as e:
        print(f"数据库初始化失败: {e}")
        return False


def reset_database():
    """重置数据库（慎用）"""
    print("警告：即将重置数据库，所有数据将被删除！")
    confirm = input("确定要继续吗？(yes/no): ")

    if confirm.lower() == 'yes':
        db = get_db()
        try:
            db.execute("DROP TABLE IF EXISTS schedules")
            db.execute("DROP TABLE IF EXISTS reminder_logs")
            db.get_connection().commit()
            print("数据库已重置，正在重新初始化...")
            return init_database()
        except Exception as e:
            print(f"重置失败: {e}")
            return False
    else:
        print("已取消")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="数据库初始化工具")
    parser.add_argument("--reset", action="store_true", help="重置数据库")
    args = parser.parse_args()

    if args.reset:
        reset_database()
    else:
        init_database()
