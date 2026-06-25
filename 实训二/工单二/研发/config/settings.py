"""
配置文件
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

import os
from dataclasses import dataclass
from typing import List


@dataclass
class Settings:
    """应用配置"""

    # 数据库配置
    DB_TYPE: str = "sqlite"  # sqlite, mysql, postgresql
    DB_PATH: str = "aioscheduler.db"
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "aioscheduler"
    DB_USER: str = "root"
    DB_PASSWORD: str = ""

    # 应用配置
    APP_NAME: str = "日程提醒智能体"
    APP_VERSION: str = "1.0"

    # 提醒配置
    REMINDER_ADVANCE_MINUTES: int = 0  # 提前提醒分钟数
    CHECK_INTERVAL_SECONDS: int = 30   # 检查提醒间隔（秒）

    # 温馨提醒模板
    REMINDER_TEMPLATES: List[str] = None

    def __post_init__(self):
        if self.REMINDER_TEMPLATES is None:
            self.REMINDER_TEMPLATES = [
                "温馨提醒：（{content}）的时间到啦，主人！",
                "主人！是时候（{content}）了喔~",
                "亲爱的主人，现在是（{content}）的时候啦！",
                "嘿，主人，该（{content}）了哦~"
            ]

    def get_reminder_template(self, content: str) -> str:
        """获取随机温馨提醒模板"""
        import random
        template = random.choice(self.REMINDER_TEMPLATES)
        return template.format(content=content)


# 全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置"""
    return settings
