# 人工智能 NLP-Agent 数字人项目-基金问答智能体任务
"""
数据库模块 - 数据库连接和工具函数
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from config.settings import settings


class DatabaseManager:
    """
    数据库管理器 - 封装数据库操作
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path or settings.db_path

    def get_connection(self) -> sqlite3.Connection:
        """
        获取数据库连接

        Returns:
            sqlite3.Connection: 数据库连接
        """
        return sqlite3.connect(self.db_path)

    def list_tables(self) -> List[str]:
        """
        获取所有表名

        Returns:
            List[str]: 表名列表
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """)
            tables = [row[0] for row in cursor.fetchall()]
            return tables
        finally:
            conn.close()

    def get_schema(self, table_name: str) -> Dict[str, Any]:
        """
        获取指定表的结构信息

        Args:
            table_name: 表名

        Returns:
            Dict: 包含表结构和示例数据的字典
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()

            # 获取建表语句
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            result = cursor.fetchone()
            schema_sql = result[0] if result else ""

            # 获取列信息
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [
                {
                    "name": col[1],
                    "type": col[2],
                    "nullable": not col[3],
                    "default": col[4],
                    "pk": bool(col[5])
                }
                for col in cursor.fetchall()
            ]

            # 获取示例数据
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
            sample_rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]

            return {
                "table_name": table_name,
                "schema_sql": schema_sql,
                "columns": columns,
                "sample_rows": sample_rows,
                "col_names": col_names
            }
        finally:
            conn.close()

    def get_full_schema(self, table_names: Optional[List[str]] = None) -> str:
        """
        获取完整的数据库模式描述

        Args:
            table_names: 要查询的表名列表，None 表示所有表

        Returns:
            str: 格式化的模式描述
        """
        if table_names is None:
            table_names = self.list_tables()

        schemas = []
        for table_name in table_names:
            schema_info = self.get_schema(table_name)

            # 格式化列信息
            col_lines = []
            for col in schema_info["columns"]:
                pk_str = " PRIMARY KEY" if col["pk"] else ""
                nullable_str = "" if col["nullable"] else " NOT NULL"
                default_str = f" DEFAULT {col['default']}" if col["default"] else ""
                col_lines.append(
                    f"  - {col['name']}: {col['type']}{pk_str}{nullable_str}{default_str}"
                )

            # 格式化示例数据
            sample_lines = []
            if schema_info["sample_rows"]:
                sample_lines.append("  示例数据:")
                for row in schema_info["sample_rows"]:
                    row_dict = dict(zip(schema_info["col_names"], row))
                    sample_lines.append(f"    {row_dict}")

            schema_text = f"""
表名: {table_name}
列信息:
{chr(10).join(col_lines)}
{chr(10).join(sample_lines)}
"""
            schemas.append(schema_text)

        return "\n".join(schemas)

    def execute_query(self, query: str) -> Dict[str, Any]:
        """
        执行 SQL 查询

        Args:
            query: SQL 查询语句

        Returns:
            Dict: 查询结果
        """
        # 安全检查 - 禁止修改数据的操作
        dangerous_keywords = [
            "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
            "ALTER", "TRUNCATE", "REPLACE", "MERGE"
        ]
        query_upper = query.upper().strip()
        for keyword in dangerous_keywords:
            if query_upper.startswith(keyword):
                return {
                    "success": False,
                    "error": f"禁止执行: {keyword} 操作，仅支持 SELECT 查询"
                }

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query)

            # 获取列名
            col_names = [desc[0] for desc in cursor.description] if cursor.description else []

            # 获取结果
            rows = cursor.fetchall()

            return {
                "success": True,
                "columns": col_names,
                "rows": rows,
                "row_count": len(rows)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
        finally:
            conn.close()

    def describe_all_tables(self) -> str:
        """
        获取所有表的详细描述

        Returns:
            str: 所有表的描述信息
        """
        tables = self.list_tables()
        return self.get_full_schema(tables)


# 创建全局数据库管理器实例
db_manager = DatabaseManager()


# LangChain Tools
# 以下是供 LangGraph Agent 调用的工具函数

@tool
def list_tables() -> str:
    """
    列出数据库中所有表

    Returns:
        str: 表名列表，逗号分隔
    """
    tables = db_manager.list_tables()
    return ", ".join(tables) if tables else "数据库中没有表"


@tool
def get_table_schema(table_names: str) -> str:
    """
    获取指定表的结构和示例数据

    Args:
        table_names: 逗号分隔的表名列表

    Returns:
        str: 表结构描述
    """
    tables = [t.strip() for t in table_names.split(",")]
    return db_manager.get_full_schema(tables)


@tool
def execute_sql(query: str) -> str:
    """
    执行 SQL SELECT 查询并返回结果

    Args:
        query: SQL 查询语句

    Returns:
        str: 查询结果或错误信息
    """
    result = db_manager.execute_query(query)

    if not result["success"]:
        return f"错误: {result['error']}"

    if not result["rows"]:
        return "查询结果为空"

    # 格式化输出
    output = [f"查询结果 (共 {result['row_count']} 行):"]
    output.append(f"列: {', '.join(result['columns'])}")
    output.append("-" * 50)

    for row in result["rows"][:100]:  # 限制最多显示100行
        output.append(str(row))

    if result["row_count"] > 100:
        output.append(f"... 还有 {result['row_count'] - 100} 行")

    return "\n".join(output)


# 工具列表
SQL_TOOLS = [list_tables, get_table_schema, execute_sql]
