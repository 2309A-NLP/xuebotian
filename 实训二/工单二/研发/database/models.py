"""
数据库模型定义
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, List
from enum import Enum

from .connection import get_db


class RecurrenceType(Enum):
    """循环类型枚举"""
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    WORKDAY = "workday"


@dataclass
class Schedule:
    """日程数据模型"""
    id: Optional[int] = None
    content: str = ""
    schedule_date: str = ""
    schedule_time: str = ""
    recurrence: str = "none"
    recurrence_rule: Optional[str] = None
    is_completed: bool = False
    is_active: bool = True
    reminded: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "schedule_date": self.schedule_date,
            "schedule_time": self.schedule_time,
            "recurrence": self.recurrence,
            "recurrence_rule": self.recurrence_rule,
            "is_completed": self.is_completed,
            "is_active": self.is_active,
            "reminded": self.reminded,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_row(cls, row) -> 'Schedule':
        if row is None:
            return None
        return cls(
            id=row['id'],
            content=row['content'],
            schedule_date=row['schedule_date'],
            schedule_time=row['schedule_time'],
            recurrence=row['recurrence'],
            recurrence_rule=row['recurrence_rule'],
            is_completed=bool(row['is_completed']),
            is_active=bool(row['is_active']),
            reminded=bool(row['reminded']) if 'reminded' in row and row['reminded'] is not None else False,
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )


class ScheduleRepository:
    """日程数据仓库"""

    def __init__(self):
        self.db = get_db()
        self._init_tables()

    def _init_tables(self):
        """初始化表"""
        sql = """
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            schedule_date TEXT NOT NULL,
            schedule_time TEXT NOT NULL,
            recurrence TEXT DEFAULT 'none',
            recurrence_rule TEXT,
            is_completed INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            reminded INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
        self.db.execute(sql)
        self.db.get_connection().commit()

        # 迁移：已有数据库补充 reminded 列
        try:
            self.db.execute("ALTER TABLE schedules ADD COLUMN reminded INTEGER DEFAULT 0")
            self.db.get_connection().commit()
        except Exception:
            pass

    def add(self, schedule: Schedule) -> int:
        """添加日程"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        schedule.created_at = now
        schedule.updated_at = now

        sql = """
        INSERT INTO schedules (content, schedule_date, schedule_time, recurrence,
                                recurrence_rule, is_completed, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        cursor = self.db.execute(sql, (
            schedule.content,
            schedule.schedule_date,
            schedule.schedule_time,
            schedule.recurrence,
            schedule.recurrence_rule,
            int(schedule.is_completed),
            int(schedule.is_active),
            schedule.created_at,
            schedule.updated_at
        ))
        self.db.get_connection().commit()
        return cursor.lastrowid

    def get_by_id(self, schedule_id: int) -> Optional[Schedule]:
        sql = "SELECT * FROM schedules WHERE id = ?"
        row = self.db.fetch_one(sql, (schedule_id,))
        return Schedule.from_row(row) if row else None

    def get_all(self, include_completed: bool = True) -> List[Schedule]:
        if include_completed:
            sql = "SELECT * FROM schedules WHERE is_active = 1 ORDER BY schedule_date, schedule_time"
        else:
            sql = "SELECT * FROM schedules WHERE is_active = 1 AND is_completed = 0 ORDER BY schedule_date, schedule_time"
        rows = self.db.fetch_all(sql)
        return [Schedule.from_row(row) for row in rows]

    def get_by_date(self, target_date: date) -> List[Schedule]:
        date_str = target_date.strftime("%Y-%m-%d")
        weekday = target_date.weekday()  # 0=周一, 6=周日

        # 查询当天日程（非循环的指定日期 + 循环规则中包含今天的）
        sql = """
        SELECT * FROM schedules
        WHERE is_active = 1 AND is_completed = 0
        AND (
            (schedule_date = ? AND recurrence = 'none')
            OR (recurrence = 'weekly')
        )
        ORDER BY schedule_time, id
        """
        rows = self.db.fetch_all(sql, (date_str,))
        schedules = [Schedule.from_row(row) for row in rows]

        # 过滤循环日程：只保留今天在循环规则中的，并去重
        result = []
        seen_content_time = set()
        for s in schedules:
            # 构造唯一键去重
            key = (s.content, s.schedule_time, s.recurrence)
            if key in seen_content_time:
                continue
            seen_content_time.add(key)

            if s.recurrence == "weekly" and s.recurrence_rule:
                if len(s.recurrence_rule) > weekday and s.recurrence_rule[weekday] == '1':
                    result.append(s)
            else:
                result.append(s)

        return result

    def update(self, schedule: Schedule) -> bool:
        schedule.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        UPDATE schedules
        SET content = ?, schedule_date = ?, schedule_time = ?, recurrence = ?,
            recurrence_rule = ?, is_completed = ?, is_active = ?, updated_at = ?
        WHERE id = ?
        """
        cursor = self.db.execute(sql, (
            schedule.content,
            schedule.schedule_date,
            schedule.schedule_time,
            schedule.recurrence,
            schedule.recurrence_rule,
            int(schedule.is_completed),
            int(schedule.is_active),
            schedule.updated_at,
            schedule.id
        ))
        self.db.get_connection().commit()
        return cursor.rowcount > 0

    def delete(self, schedule_id: int) -> bool:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = "UPDATE schedules SET is_active = 0, updated_at = ? WHERE id = ?"
        cursor = self.db.execute(sql, (now, schedule_id))
        self.db.get_connection().commit()
        return cursor.rowcount > 0

    def mark_completed(self, schedule_id: int) -> bool:
        schedule = self.get_by_id(schedule_id)
        if not schedule:
            return False

        if schedule.recurrence != RecurrenceType.NONE.value:
            self._generate_next_recurrence(schedule)
        else:
            schedule.is_completed = True
            self.update(schedule)
        return True

    def mark_reminded(self, schedule_id: int) -> bool:
        """标记日程已提醒（非循环日程不再重复提醒）"""
        db = get_db()
        db.execute("UPDATE schedules SET reminded = 1 WHERE id = ?", (schedule_id,))
        db.commit()
        return True

    def _generate_next_recurrence(self, schedule: Schedule):
        from datetime import timedelta
        current_date = datetime.strptime(schedule.schedule_date, "%Y-%m-%d").date()

        if schedule.recurrence == RecurrenceType.DAILY.value:
            next_date = current_date + timedelta(days=1)

        elif schedule.recurrence == RecurrenceType.WEEKLY.value:
            next_date = current_date + timedelta(weeks=1)
            # 把 recurrence_rule 往前挪一位，保持"今天"指向下一周的新日期
            if schedule.recurrence_rule and len(schedule.recurrence_rule) == 7:
                schedule.recurrence_rule = (
                    schedule.recurrence_rule[-1]
                    + schedule.recurrence_rule[:-1]
                )

        elif schedule.recurrence == RecurrenceType.MONTHLY.value:
            month = current_date.month + 1 if current_date.month < 12 else 1
            year = current_date.year if current_date.month < 12 else current_date.year + 1
            next_date = current_date.replace(year=year, month=month)

        elif schedule.recurrence == RecurrenceType.WORKDAY.value:
            next_date = current_date + timedelta(days=1)
            while next_date.weekday() >= 5:
                next_date += timedelta(days=1)
        else:
            schedule.is_completed = True
            self.update(schedule)
            return

        schedule.schedule_date = next_date.strftime("%Y-%m-%d")
        self.update(schedule)

    def get_upcoming(self, minutes: int = 60) -> List[Schedule]:
        from datetime import timedelta
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        weekday = now.weekday()  # 0=周一, 6=周日

        # 查询当天所有日程
        sql = """
        SELECT * FROM schedules
        WHERE is_active = 1 AND is_completed = 0
        AND (
            (schedule_date = ? AND recurrence = 'none')
            OR (recurrence = 'weekly')
        )
        ORDER BY schedule_time
        """
        rows = self.db.fetch_all(sql, (today,))
        schedules = [Schedule.from_row(row) for row in rows]

        # 过滤：保留今天在循环规则中的 + 非循环日程
        result = []
        for s in schedules:
            if s.recurrence == "weekly" and s.recurrence_rule:
                if len(s.recurrence_rule) > weekday and s.recurrence_rule[weekday] == '1':
                    result.append(s)
            else:
                result.append(s)

        now_time = now.time()
        # 用整分钟判断：日程分钟 == 当前分钟+N 且 N 在 [1, minutes] 范围内
        now_minute = now_time.hour * 60 + now_time.minute

        result = [
            s for s in result
            if self._is_within_window_minutes(s.schedule_time, now_minute, minutes)
        ]

        return result

    def _is_within_window_minutes(self, schedule_time_str: str, now_minute: int, minutes: int) -> bool:
        """判断日程是否在 N 分钟窗口内（按整分钟比较）

        设计：当 N=1 时窗口为「当前分钟整点之后到下分钟整点」，
        即 diff in [0, minutes-1]，配合每30秒检查一次
        可在 20:41:00~20:41:30 之间精确触发 20:41 的提醒。
        """
        t = datetime.strptime(schedule_time_str, "%H:%M")
        sched_minute = t.hour * 60 + t.minute
        diff = sched_minute - now_minute
        # diff in [0, minutes-1]: 仅当日程正好在当前这一分钟触发（或下N-1分钟内，但配合秒级检查锁住）
        return 0 <= diff <= minutes - 1


# 全局数据仓库实例
schedule_repo = ScheduleRepository()
