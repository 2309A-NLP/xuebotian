from contextlib import contextmanager
import traceback

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import (
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
)
from app.core.logging_utils import get_logger


logger = get_logger(__name__)


def _create_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


@contextmanager
def get_db():
    conn = _create_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        logger.error("数据库事务执行失败，准备回滚。\n%s", traceback.format_exc())
        conn.rollback()
        raise
    finally:
        conn.close()
