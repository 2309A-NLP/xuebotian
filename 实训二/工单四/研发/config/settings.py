# 人工智能 NLP-Agent 数字人项目-基金问答智能体任务
"""
配置模块 - 加载和管理系统配置
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel


class Settings(BaseModel):
    """系统配置"""
    # 硅基流动 API 配置
    siliconflow_api_key: str
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"

    # 模型配置
    model_name: str = "deepseek-ai/DeepSeek-V4-Flash"
    temperature: float = 0.1
    max_tokens: int = 4096

    # 数据库配置
    db_path: str = "./data/博金杯比赛数据.db"

    # Agent 配置
    max_retries: int = 3
    top_k: int = 10
    enable_human_review: bool = False


def load_settings() -> Settings:
    """
    加载配置文件

    Returns:
        Settings: 配置对象
    """
    # 查找 .env 文件
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    return Settings(
        siliconflow_api_key=os.getenv("SILICONFLOW_API_KEY", ""),
        siliconflow_base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        model_name=os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V4-Flash"),
        temperature=float(os.getenv("TEMPERATURE", "0.1")),
        max_tokens=int(os.getenv("MAX_TOKENS", "4096")),
        db_path=os.getenv("DB_PATH", "./data/博金杯比赛数据.db"),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        top_k=int(os.getenv("TOP_K", "10")),
        enable_human_review=os.getenv("ENABLE_HUMAN_REVIEW", "false").lower() == "true",
    )


# 全局配置实例
settings = load_settings()
