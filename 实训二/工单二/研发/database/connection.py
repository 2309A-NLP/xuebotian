"""
数据库连接管理
"""

import sqlite3
import os
from typing import Optional, List, Tuple
from contextlib import contextmanager


class DatabaseConnection:
    """数据库连接管理类"""

    _instance: Optional['DatabaseConnection'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._connection = None
        return cls._instance

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._connection is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "aioscheduler.db")
            self._connection = sqlite3.connect(db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self):
        """关闭数据库连接"""
        if self._connection:
            self._connection.close()
            self._connection = None

    @contextmanager
    def cursor(self):
        """上下文管理器，获取游标"""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    def execute(self, sql: str, params: Tuple = ()) -> sqlite3.Cursor:
        """执行SQL语句"""
        conn = self.get_connection()
        return conn.execute(sql, params)

    def fetch_all(self, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """查询所有结果"""
        with self.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def fetch_one(self, sql: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        """查询单条结果"""
        with self.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def execute_many(self, sql: str, params_list: List[Tuple]) -> None:
        """批量执行"""
        with self.cursor() as cursor:
            cursor.executemany(sql, params_list)


# 全局数据库连接实例
db = DatabaseConnection()


def get_db() -> DatabaseConnection:
    """获取数据库连接实例"""
    return db
