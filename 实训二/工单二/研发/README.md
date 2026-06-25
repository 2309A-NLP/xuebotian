# 日程提醒智能体 (Agent 版)

> Agent 数字人项目 - 日程提醒智能体
> 工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务

## 项目简介

这是一个基于 **Agent 架构**的智能日程管理助手。区别于传统的规则匹配方式，本项目采用真正的 Agent 架构实现。

## 核心架构

```
┌─────────────────────────────────────────────────────┐
│                   Schedule Agent                     │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌─────────────┐                                    │
│  │     LLM     │  ← 硅基流动 API (Qwen2.5-7B)       │
│  │  (大脑)     │    理解意图、规划任务、生成回复        │
│  └──────┬──────┘                                    │
│         │                                            │
│  ┌──────▼──────┐                                    │
│  │   Tools     │  ← 日程增删改查工具                  │
│  │  (工具)     │    Agent 自主决定何时调用            │
│  └──────┬──────┘                                    │
│         │                                            │
│  ┌──────▼──────┐                                    │
│  │   Memory    │  ← 对话历史记忆                     │
│  │  (记忆)     │    支持多轮对话                     │
│  └─────────────┘                                    │
│                                                      │
└─────────────────────────────────────────────────────┘
```

## 项目结构

```
aioscheduler/
├── agent/                    # Agent 核心模块 ⭐
│   ├── agent.py             # Agent 主类
│   ├── llm.py               # LLM 客户端 (SiliconFlow)
│   ├── memory.py            # 记忆管理
│   ├── tools.py             # 工具定义
│   ├── config.py            # 配置管理
│   └── reminder.py          # 提醒服务
├── database/                # 数据库模块
│   ├── connection.py
│   └── models.py
├── nlp/                     # NLP模块 (备用)
├── services/                # 服务层
├── main_agent.py            # Agent 版本入口 ⭐
├── main.py                  # 原版本入口
├── requirements.txt
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
pip install requests flask pytest
```

### 2. 配置 API Key

访问 [硅基流动](https://cloud.siliconflow.cn) 注册账号获取 API Key

首次运行会提示输入 API Key，或手动配置：

```python
from agent.config import setup_api_key
setup_api_key("your-api-key-here")
```

### 3. 运行

```bash
# 命令行模式（推荐）
python main_agent.py

# Web 模式
python main_agent.py --web
```

## 功能演示

```
您: 下午5点开会
智能体: 好的主人！已经记录好日程啦：【开会】在 今天 17:00

您: 我今天还有哪些日程？
智能体: 主人，今天的日程有这些：
  1. 17:00 - 开会
共 1 个日程

您: 删除第1个
智能体: 已经删除日程 1，删除的是 17:00 的【开会】
```

## 支持的模型

| 模型 | 说明 | 推荐度 |
|------|------|--------|
| Qwen/Qwen2.5-7B-Instruct | 阿里通义千问，免费额度充足 | ⭐⭐⭐⭐⭐ |
| Qwen/Qwen2.5-14B-Instruct | 更大模型，效果更好 | ⭐⭐⭐⭐ |
| deepseek-ai/DeepSeek-V2.5 | DeepSeek 模型 | ⭐⭐⭐⭐ |
| 01ai/Yi-Lightning | 零一万物模型 | ⭐⭐⭐ |

## Agent 执行流程

```
用户输入: "下午5点开会"

┌─────────────────────────────────────────┐
│ 1. LLM 理解意图                          │
│    → 识别为添加日程请求                   │
├─────────────────────────────────────────┤
│ 2. LLM 决定调用工具                       │
│    → 调用 add_schedule(content="开会",   │
│         schedule_time="17:00")          │
├─────────────────────────────────────────┤
│ 3. Tool 执行并返回结果                    │
│    → 数据库存储成功                       │
├─────────────────────────────────────────┤
│ 4. LLM 整合结果生成回复                   │
│    → "好的主人，已经记录好日程啦~"        │
└─────────────────────────────────────────┘
```

## 数据库设计

### schedules 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| content | TEXT | 日程内容 |
| schedule_date | TEXT | 日期 (YYYY-MM-DD) |
| schedule_time | TEXT | 时间 (HH:MM) |
| recurrence | TEXT | 循环类型 |
| is_active | INTEGER | 是否启用 |
| created_at | TEXT | 创建时间 |

## 开发指南

### 自定义工具

```python
from agent import Tool, ToolResult

def my_tool(param1: str, param2: int) -> ToolResult:
    # 工具逻辑
    return ToolResult(success=True, message="操作成功")

# 创建工具
my_tool_def = Tool(
    name="my_tool",
    description="我的自定义工具",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "参数1"},
            "param2": {"type": "integer", "description": "参数2"}
        },
        "required": ["param1"]
    }
)
my_tool_def.execute_func = my_tool

# 注册到 Agent
agent = get_agent()
agent.register_tool(my_tool_def)
```

### 自定义记忆模块

```python
from agent import Memory, Message, get_memory, SlidingWindowMemory

# 使用滑动窗口记忆
memory = SlidingWindowMemory(window_size=20)
agent = get_agent(memory=memory)
```

## 与原版对比

| 特性 | 原版 (main.py) | Agent 版 (main_agent.py) |
|------|----------------|--------------------------|
| 理解方式 | 正则匹配 | LLM 理解 |
| 意图识别 | 固定关键词 | 智能泛化 |
| 扩展性 | 需修改代码 | 工具注册 |
| 上下文 | 无 | 多轮对话 |
| API 依赖 | 无 | SiliconFlow |

## 依赖

- Python 3.8+
- requests
- flask (可选)
- pytest (可选)

---

北京八维信息集团 - 2025
