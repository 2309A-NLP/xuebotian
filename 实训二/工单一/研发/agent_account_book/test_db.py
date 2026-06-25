# 人工智能NLP-Agent数字人项目-记账本任务
# 工单编号：人工智能NLP-Agent数字人项目-记账本任务V1.1-20250206

"""
数据库测试脚本 - 验证数据库功能
"""

import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import AccountBookDB


def test_database():
    """测试数据库功能"""
    print("=" * 50)
    print("🗄️ 数据库功能测试")
    print("=" * 50)
    print()

    # 初始化数据库
    db = AccountBookDB()
    print("✅ 数据库初始化成功")
    print()

    # 测试1: 添加记录
    print("📝 测试1: 添加记账记录")
    print("-" * 30)

    test_records = [
        ("2025-07-05", "女儿", "购物", "登山鞋", 499, "支出"),
        ("2025-07-05", "妈妈", "报销", "工作报销", 1000, "收入"),
        ("2025-07-06", "女儿", "旅游", "报旅游团", 2000, "支出"),
        ("2025-07-06", "爸爸", "餐饮", "朋友聚餐", 350, "支出"),
        ("2025-07-07", "妈妈", "工资", "月薪", 8000, "收入"),
    ]

    for record in test_records:
        result = db.add_record(*record)
        print(f"   ✅ {result['message']}")

    print()

    # 测试2: 查询所有记录
    print("📋 测试2: 查询所有记录")
    print("-" * 30)
    all_records = db.get_all_records()
    print(f"   共 {len(all_records)} 条记录")
    for r in all_records:
        print(f"   [{r['id']}] {r['date']} {r['member']} {r['category']} {r['item']} {r['type']} {r['amount']}元")
    print()

    # 测试3: 按成员查询
    print("👤 测试3: 查询女儿的支出")
    print("-" * 30)
    daughter_records = db.query_records(member="女儿")
    print(f"   女儿共 {len(daughter_records)} 笔记录")
    for r in daughter_records:
        print(f"   - {r['date']} {r['category']} {r['item']} {r['type']} {r['amount']}元")
    print()

    # 测试4: 统计成员支出
    print("📊 测试4: 统计女儿的总支出")
    print("-" * 30)
    total = db.get_member_total("女儿")
    print(f"   收入: {total['收入']['count']}笔，共 {total['收入']['total']} 元")
    print(f"   支出: {total['支出']['count']}笔，共 {total['支出']['total']} 元")
    print()

    # 测试5: 搜索关键词
    print("🔍 测试5: 搜索关键词'旅游'")
    print("-" * 30)
    search_results = db.query_records(keyword="旅游")
    print(f"   找到 {len(search_results)} 条相关记录")
    for r in search_results:
        print(f"   - [{r['id']}] {r['date']} {r['member']} {r['item']} {r['type']} {r['amount']}元")
    print()

    # 测试6: 删除记录
    print("🗑️ 测试6: 删除记录 (ID=3)")
    print("-" * 30)
    result = db.delete_record(3)
    print(f"   {result['message']}")
    print()

    # 测试7: 月度汇总
    print("📅 测试7: 月度汇总 (2025年7月)")
    print("-" * 30)
    summary = db.get_month_summary(2025, 7)
    print(f"   时间范围: {summary['start_date']} 至 {summary['end_date']}")
    print(f"   家庭成员数据: {summary['details']}")
    print()

    # 最终记录数
    print("📈 最终统计")
    print("-" * 30)
    final_records = db.get_all_records()
    print(f"   数据库中共有 {len(final_records)} 条记录")
    print()

    print("=" * 50)
    print("✅ 所有测试完成!")
    print("=" * 50)


if __name__ == "__main__":
    test_database()
