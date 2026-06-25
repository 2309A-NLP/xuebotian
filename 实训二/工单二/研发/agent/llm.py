"""
LLM 模块 - 纯 HTTP 实现（无 LangChain 依赖）
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

from typing import Optional, Dict, Any, List
import requests


class SiliconFlowChatModel:
    """SiliconFlow ChatModel 纯 HTTP 实现，支持工具调用（bind_tools）。"""

    def __init__(
        self,
        api_key: str,
        model_name: str = "deepseek-ai/DeepSeek-V4-Flash",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        api_base: str = "https://api.siliconflow.cn/v1",
        timeout: int = 180,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_base = api_base
        self.timeout = timeout
        self._bound_tools: Optional[List[Dict]] = None
        self._tool_choice: str = "auto"

    def bind_tools(self, tools: List[Any], **kwargs: Any) -> "SiliconFlowChatModel":
        """绑定工具到模型。返回一个新实例，把工具注入到请求 payload。"""
        tool_specs = []
        for t in tools:
            tool_specs.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.args,
                },
            })

        bound = SiliconFlowChatModel(
            api_key=self.api_key,
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            api_base=self.api_base,
            timeout=self.timeout,
        )
        bound._bound_tools = tool_specs
        bound._tool_choice = kwargs.get("tool_choice", "auto")
        return bound

    def chat(self, messages: List[Dict], tools: Optional[List[Dict]] = None, tool_choice: str = "auto") -> Dict:
        """发送对话请求，返回原始响应字典。"""
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        effective_tools = tools if tools is not None else self._bound_tools
        if effective_tools:
            payload["tools"] = effective_tools
            payload["tool_choice"] = tool_choice if tool_choice != "auto" else self._tool_choice

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        session = requests.Session()
        retry = requests.adapters.Retry(
            total=3,
            backoff_factor=2,
            status_forcelist=(500, 502, 503, 504),
            allowed_methods=("POST",),
        )
        adapter = requests.adapters.HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        try:
            response = session.post(url, headers=headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout as e:
            raise ValueError(f"API 请求超时（{self.timeout}s）: {e}")
        except requests.exceptions.RequestException as e:
            raise ValueError(f"API 请求失败: {e}")


# 支持的模型列表
SUPPORTED_MODELS = {
    "deepseek-v4-flash": "deepseek-ai/DeepSeek-V4-Flash",
    "qwen2.5-7b": "Qwen/Qwen2.5-7B-Instruct",
    "qwen2.5-14b": "Qwen/Qwen2.5-14B-Instruct",
    "qwen2.5-72b": "Qwen/Qwen2.5-72B-Instruct",
    "qwen-coder": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "deepseek-v2.5": "deepseek-ai/DeepSeek-V2.5",
    "yi-lightning": "01ai/Yi-Lightning",
    "glm4": "ZhipuAI/glm4-9b-chat",
    "llama3": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "starling": "Nexusflow/Starling-LM-7B-beta",
    "kimi": "moonshotai/kimi-k2-instruct",
    "qwen-max": "qwen/qwen-max",
}


def get_chat_model(
    api_key: str,
    model: str = "deepseek-ai/DeepSeek-V4-Flash",
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> SiliconFlowChatModel:
    """获取 ChatModel 实例。"""
    if not api_key:
        raise ValueError("请先配置 API Key！")

    return SiliconFlowChatModel(
        api_key=api_key,
        model_name=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# 类型别名，兼容 agent/agent.py 的导入
LLMClient = SiliconFlowChatModel


def get_llm_client(config) -> SiliconFlowChatModel:
    """根据 AgentConfig 获取 LLM 客户端。"""
    return get_chat_model(
        api_key=config.api_key,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
