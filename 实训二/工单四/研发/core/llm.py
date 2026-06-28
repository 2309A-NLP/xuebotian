# 人工智能 NLP-Agent 数字人项目-基金问答智能体任务
"""
LLM 模块 - 硅基流动 API 调用封装
"""

import json
from typing import Any, Dict, List, Optional, Union

import requests
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class SiliconFlowChatModel(BaseChatModel):
    """
    硅基流动 API Chat Model 封装

    用于对接 Silicon Flow 平台的大模型 API
    模型: deepseek-ai/DeepSeek-V4-Flash
    """

    api_key: str = Field(default="")
    base_url: str = Field(default="https://api.siliconflow.cn/v1")
    model_name: str = Field(default="deepseek-ai/DeepSeek-V4-Flash")
    temperature: float = Field(default=0.1)
    max_tokens: int = Field(default=4096)
    timeout: int = Field(default=120)

    def _convert_messages_to_openai_format(
        self, messages: List[BaseMessage]
    ) -> List[Dict[str, Any]]:
        """
        将 LangChain 消息格式转换为 OpenAI 格式

        Args:
            messages: LangChain 消息列表

        Returns:
            List[Dict]: OpenAI 格式的消息列表
        """
        formatted_messages = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "user"
            elif isinstance(msg, AIMessage):
                role = "assistant"
            elif isinstance(msg, SystemMessage):
                role = "system"
            else:
                role = "user"

            content = msg.content
            if isinstance(content, list):
                # 处理复杂内容格式
                text_content = ""
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_content += item.get("text", "")
                        elif item.get("type") == "tool_use":
                            text_content += f"\n[TOOL_CALL: {item.get('name')}]\n{json.dumps(item.get('args', {}), ensure_ascii=False)}\n"
                    else:
                        text_content += str(item)
                content = text_content

            formatted_messages.append({
                "role": role,
                "content": content
            })

        return formatted_messages

    def _call_api(
        self, messages: List[BaseMessage], tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        调用硅基流动 API

        Args:
            messages: 消息列表
            tools: 工具定义列表

        Returns:
            Dict: API 响应
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model_name,
            "messages": self._convert_messages_to_openai_format(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        if tools:
            payload["tools"] = tools

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout
        )

        if response.status_code != 200:
            raise Exception(f"API 调用失败: {response.status_code} - {response.text}")

        return response.json()

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs
    ) -> ChatResult:
        """
        生成聊天回复

        Args:
            messages: 消息列表
            stop: 停止词列表
            **kwargs: 其他参数

        Returns:
            ChatResult: 聊天结果
        """
        tools = kwargs.get("tools", None)

        try:
            response = self._call_api(messages, tools)

            # 解析响应
            choice = response["choices"][0]
            message = choice["message"]

            # 构建 AIMessage
            ai_message = AIMessage(content=message.get("content", ""))

            # 处理工具调用
            if "tool_calls" in message:
                ai_message.tool_calls = [
                    {
                        "name": tc["function"]["name"],
                        "args": json.loads(tc["function"]["arguments"]),
                        "id": tc["id"]
                    }
                    for tc in message["tool_calls"]
                ]

            return ChatResult(generations=[ChatGeneration(message=ai_message)])

        except Exception as e:
            # 返回错误消息
            error_msg = AIMessage(content=f"API 调用错误: {str(e)}")
            return ChatResult(generations=[ChatGeneration(message=error_msg)])

    def _llm_type(self) -> str:
        """返回模型类型"""
        return "siliconflow"


def create_llm(
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 4096
) -> SiliconFlowChatModel:
    """
    创建 LLM 实例的工厂函数

    Args:
        api_key: API 密钥
        model_name: 模型名称
        temperature: 温度参数
        max_tokens: 最大 token 数

    Returns:
        SiliconFlowChatModel: LLM 实例
    """
    from config.settings import settings

    return SiliconFlowChatModel(
        api_key=api_key or settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model_name=model_name or settings.model_name,
        temperature=temperature,
        max_tokens=max_tokens
    )
