"""
配置管理
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

import os
import json
from dataclasses import dataclass, asdict
from typing import Optional, List


@dataclass
class AgentConfig:
    """Agent 配置"""
    name: str = "日程提醒助手"
    description: str = "您的智能日程管理助手"
    model: str = "deepseek-ai/DeepSeek-V4-Flash"
    temperature: float = 0.7
    max_tokens: int = 2048
    api_key: str = ""
    api_base: str = "https://api.siliconflow.cn/v1"


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config = AgentConfig()
        self._load()

    def _load(self):
        """从文件加载配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.config = AgentConfig(**data)
            except Exception as e:
                print(f"加载配置失败: {e}")

    def save(self):
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(asdict(self.config), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存配置失败: {e}")
            return False

    def get(self) -> AgentConfig:
        """获取配置"""
        return self.config

    def update(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def setup_api_key(self, api_key: str):
        """设置 API Key"""
        self.config.api_key = api_key
        self.save()

    def setup_model(self, model: str):
        """设置模型"""
        self.config.model = model
        self.save()


# 全局配置管理器
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取配置管理器"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def setup_api_key(api_key: str):
    """快速设置 API Key"""
    manager = get_config_manager()
    manager.setup_api_key(api_key)
    print("API Key 设置成功！")
