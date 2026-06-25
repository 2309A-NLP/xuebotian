# AIOScheduler 日程提醒智能体 — 设计文档

> 本文档面向有一定编程基础的读者，解释系统的整体架构、各模块职责、数据流向与核心设计决策。
> 小白读者建议从「一、什么是 AIOScheduler」开始，按顺序阅读。

---

## 一、系统概述

**AIOScheduler** 是一个基于大语言模型（LLM）的智能日程管理助手。用户可以用自然语言（中文）与它对话，完成以下操作：

- 添加日程（"明天下午3点开会"）
- 查询日程（"今天有什么安排？"）
- 删除日程（"删除第2个"）
- 标记完成（"第1个搞定了"）
- 设置循环日程（"每天早上8点提醒我喝水"）

**核心特性**：
- 纯 Python 实现，不依赖 LangChain 等重型框架
- 基于 SiliconFlow API 调用 LLM（支持 DeepSeek、Qwen、GLM 等12种模型）
- SQLite 数据库持久化存储
- 后台线程精确触发定时提醒
- 支持命令行（CLI）和 Web 两种交互界面

---

## 二、整体架构

系统采用经典的 **LLM Agent 架构**：「LLM（大脑）+ Tools（手脚）+ Memory（记忆）」三组件协同工作。

```
┌─────────────────────────────────────────────────────────┐
│                        用户                             │
│            "明天下午3点开会"                             │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / CLI
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   Flask Web / CLI                        │
│              (main_agent.py / main.py)                  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  ScheduleAgent（核心）                    │
│                   (agent/agent.py)                      │
│                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────┐ │
│  │   Memory     │ + │  LLM Client   │ + │   Tools   │ │
│  │ 对话记忆     │   │ SiliconFlow   │   │ 5个工具   │ │
│  └──────────────┘   └──────────────┘   └───────────┘ │
└────────────────────────┬────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
┌─────────────────┐ ┌─────────┐ ┌──────────────────────┐
│  SQLite 数据库   │ │LLM API  │ │ ReminderService      │
│  (aioscheduler  │ │(Silicon │ │ (后台定时器线程)       │
│    .db)         │ │ Flow)   │ │                      │
└─────────────────┘ └─────────┘ └──────────────────────┘
```

### 各层职责

| 层次 | 文件 | 职责 |
|------|------|------|
| 入口层 | `main_agent.py` | 加载配置、创建 Agent、启动提醒服务、提供 CLI/Web 接口 |
| Agent 核心 | `agent/agent.py` | 协调 Memory + LLM + Tools；解析工具调用；管理对话状态 |
| LLM 层 | `agent/llm.py` | 封装 SiliconFlow API；处理工具调用协议；3次重试+超时 |
| Tools 层 | `agent/tools.py` | 5个日程管理工具的实现；LLM二次解析兜底 |
| Memory 层 | `agent/memory.py` | 对话历史管理；支持滑窗截断 |
| 数据层 | `database/models.py` | Schedule数据模型；ScheduleRepository仓库；表结构管理 |
| 提醒层 | `main_agent.py` (内置) | threading.Timer 定时器；温馨提醒模板；取消/注册 |
| NLP 旧版 | `nlp/parser.py` | 规则匹配意图识别（旧版备用，不依赖LLM） |

---

## 三、Agent 核心流程（请求生命周期）

当用户说"明天下午3点开会"时，系统内部经历了以下步骤：

```
① 用户输入
  │
  ▼
② ScheduleAgent.process("明天下午3点开会")
  │
  ├─ Memory.add_message(user)          // 记录用户说的话
  │
  ├─ _build_messages()                 // 构造发给LLM的消息列表
  │    [
  │      {"role": "system", "content": "你是一个日程助手..."},
  │      {"role": "user",   "content": "明天下午3点开会"},
  │    ]
  │
  ├─ LLMClient.chat(messages, tools=[...])
  │    │
  │    └─ LLM 返回：
  │        {
  │          "tool_calls": [{
  │            "function": {
  │              "name": "add_schedule",
  │              "arguments": "{\"time\":\"15:00\",\"date\":\"2026-06-26\",\"content\":\"开会\"}"
  │            }
  │          }]
  │        }
  │
  ├─ _handle_tool_calls(tool_calls)
  │    │
  │    ├─ tool = self.tools["add_schedule"]     // 找到工具
  │    ├─ tool.execute(time="15:00", date="2026-06-26", content="开会")
  │    │    │
  │    │    └─ ScheduleRepo.add(schedule)       // 写入数据库
  │    │        └─ ReminderService.schedule_now(schedule)  // 注册定时器
  │    │
  │    └─ 返回工具结果
  │
  └─ 返回 "15:00 提醒您开会"
```

**关键设计点**：
- LLM 根据 System Prompt 自动决定调用哪个工具，无需人工写 if/else
- 工具返回结果后，Agent 可以再次调用 LLM 整合多条工具的输出
- 全程**无硬编码规则**，扩展新工具只需添加一个 `@tool` 装饰的函数

---

## 四、工具详解

所有工具通过 `@tool` 装饰器自动注册为 OpenAI Function Calling 格式：

### 4.1 add_schedule — 添加日程

```
用户："明天下午3点开会"
LLM 解析 → add_schedule(time="15:00", date="2026-06-26", content="开会")
```

**内部处理**：
1. 时间格式校验（`HH:MM`）
2. 兜底：如果 `content` 看起来像原始输入（含"点/上午/下午"），自动调 LLM 二次解析
3. 写入 SQLite
4. 调用 `ReminderService.schedule_now()` 立即注册定时器
5. 返回 `"15:00 提醒您开会"`

### 4.2 query_schedules — 查询日程

```
用户："今天有什么安排？"
LLM 解析 → query_schedules(query_date="今天")
```

**内部处理**：
- 日期映射："今天"→ 今天日期；"明天"→ 明天日期；支持 YYYY-MM-DD
- 联合查询：当天非循环日程 + 所有循环日程（按 `recurrence_rule` 过滤今天是周几）
- 循环日程展示星期标签（如"周一/周二/周三"）
- 按时间排序，附带序号

### 4.3 delete_schedule — 删除日程

```
用户："删除第2个"
LLM 解析 → delete_schedule(position=2)
```

**内部处理**：
1. 查出今天所有日程，按时间排序
2. 用序号（position）定位到具体日程，取出数据库 ID
3. 软删除：`UPDATE schedules SET is_active=0 WHERE id=?`
4. 取消对应的定时器：`ReminderService.cancel()`
5. 返回 "已经删除日程 2，删除的日程内容是：12:00 提醒您吃饭"

**注意**：序号是用户看到的顺序（按时间排序），不是数据库 ID。

### 4.4 complete_schedule — 标记完成

```
用户："第1个搞定了"
LLM 解析 → complete_schedule(position=1)
```

**内部处理**：
- 非循环日程：直接标记 `is_completed=1`
- 循环日程：调用 `_generate_next_recurrence()` 自动生成下周/明天的新日程
- 返回 "太棒了！【开会】（第1条）已完成~"

### 4.5 set_recurring_schedule — 设置循环日程

```
用户："每天早上8点提醒我喝水"
LLM 解析 → set_recurring_schedule(time_str="08:00", recurrence_rule="1111111", content="喝水")
```

**循环规则**：`recurrence_rule` 是7位二进制字符串，每位代表周一到周日：
- `1111111` = 每天
- `1000001` = 周末（周六、周日）
- `1111100` = 工作日（周一到周五）

**内部处理**：
1. 解析时间、校验循环规则格式
2. 清理内容前缀（去掉"提醒我/记得"等）
3. 写入数据库，设置 `recurrence="weekly"`, `recurrence_rule="1111111"`
4. 调用 `schedule_now()` 注册定时器

---

## 五、数据库设计

### 5.1 表结构

```sql
CREATE TABLE schedules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    content             TEXT    NOT NULL,          -- 日程内容
    schedule_date       TEXT    NOT NULL,          -- 日期 YYYY-MM-DD
    schedule_time       TEXT    NOT NULL,          -- 时间 HH:MM
    recurrence          TEXT    DEFAULT 'none',    -- none/daily/weekly/monthly/workday
    recurrence_rule     TEXT,                      -- 7位二进制，如 1111111
    is_completed        INTEGER DEFAULT 0,         -- 0=未完成 1=已完成
    is_active           INTEGER DEFAULT 1,          -- 0=已删除 1=活跃
    reminded            INTEGER DEFAULT 0,         -- 0=未提醒 1=已提醒
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
```

### 5.2 关键查询逻辑

**查询某日日程（含循环）**：
```sql
SELECT * FROM schedules
WHERE is_active=1 AND is_completed=0
AND (
    (schedule_date = '2026-06-25' AND recurrence = 'none')
    OR (recurrence = 'weekly')
)
ORDER BY schedule_time
```

然后在 Python 层用 `recurrence_rule[weekday]` 过滤今天是周几，weekday=0是周一。

**循环日程去重**：`get_by_date()` 用 `(content, schedule_time, recurrence)` 三元组去重，防止同一循环日程被显示多次。

### 5.3 循环日程的"滚动"机制

循环日程触发后，`_generate_next_recurrence()` 会：
- **daily**：日期 +1 天
- **weekly**：日期 +7 天，`recurrence_rule` 整体左移一位（保持"今天"指向新一周）
- **monthly**：月份 +1（跨年处理）
- **workday**：日期 +1 天，如果是周末则继续跳到下周一

这样循环日程可以**永远不用重新创建**，系统自动维护下一次触发时间。

---

## 六、提醒服务（定时器机制）

### 6.1 为什么用 Timer 而不是简单轮询？

如果只是每 30 秒查一次数据库，就会有**最多 30 秒的延迟误差**。本系统采用 `threading.Timer` 为每个日程**精确设置倒计时**，误差在毫秒级。

### 6.2 工作流程

```
ReminderService.start()
  │
  ├─ 启动后台线程，每 30 秒执行 _check_and_schedule()
  │
  └─ _check_and_schedule():
       │
       ├─ 遍历 schedule_repo.get_all()
       ├─ 计算每个未来日程的触发时间戳
       ├─ 跳过已过期 / 已完成 / 已提醒的日程
       ├─ 调用 _schedule_timer(schedule, target_datetime)
       │    │
       │    └─ threading.Timer(delay_seconds, fire)
       │         │
       │         └─ fire():
       │              ├─ 输出温馨提醒（随机模板）
       │              └─ schedule_repo.mark_reminded(id)
       │
       └─ 新日程添加时：add_schedule 内部立即调用 schedule_now()
                            └─ 直接注册定时器，无需等待 30 秒轮询
```

### 6.3 温馨提醒模板

```python
"温馨提醒：（{content}）的时间到啦，主人！"
"主人！是时候（{content}）了喔~"
"亲爱的主人，现在是（{content}）的时候啦！"
"嘿，主人，该（{content}）了哦~"
```

### 6.4 定时器 key 设计

每个定时器用唯一 key 标识：`"{id}_{schedule_date}_{schedule_time}"`，确保：
- 添加时不会重复注册同一个日程的定时器
- 删除时能准确定位并取消对应的定时器

---

## 七、System Prompt 设计

System Prompt 是整个 Agent 的"灵魂"，决定了 LLM 的行为边界。关键设计：

### 7.1 强制工具调用规则（示例）

```
【工具调用规则】当你收到以下类型的用户请求时，必须立即调用对应的工具，禁止自行回答：
- **查询日程**（如"日程有哪些/有什么安排/查看日程/今天的日程"）
  → 必须调用 query_schedules(query_date="今天")
- 用户说"添加/新建/安排日程" → 必须调用一次 add_schedule(...)
- 用户说"删除/取消/删掉 日程 第X个" → 必须调用 delete_schedule(position=序号)
```

### 7.2 禁止行为

| 禁止行为 | 原因 |
|---------|------|
| 禁止编造日程数据 | LLM 可能"幻觉"，必须从数据库获取 |
| 禁止重复调用工具 | 防止无限循环 |
| 禁止在工具结果前加前缀 | 保持回复简洁 |
| 禁止询问日期 | LLM 从上下文自行推断，不追问用户 |

---

## 八、LLM 集成细节

### 8.1 SiliconFlow API 调用

```python
POST https://api.siliconflow.cn/v1/chat/completions
Authorization: Bearer <api_key>

{
    "model": "deepseek-ai/DeepSeek-V4-Flash",
    "messages": [...],
    "tools": [...],          # OpenAI function calling 格式
    "tool_choice": "auto",   # LLM自己决定是否调用工具
    "temperature": 0.7,
    "max_tokens": 2048
}
```

### 8.2 工具调用协议（Tool Calls）

当 LLM 判断需要调用工具时，返回格式：

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "tool_calls": [{
        "id": "call_abc123",
        "type": "function",
        "function": {
          "name": "add_schedule",
          "arguments": "{\"time\":\"15:00\",\"date\":\"2026-06-26\",\"content\":\"开会\"}"
        }
      }]
    }
  }]
}
```

Agent 解析出函数名和参数 JSON，调用对应工具，将工具结果作为一条新消息再发给 LLM，让 LLM 生成最终回复。

### 8.3 API Key 加载优先级

```
环境变量 SILICONFLOW_API_KEY
    ↓ （不存在则）
config.txt 文件
    ↓ （不存在则）
交互式输入（启动时提示）
```

---

## 九、项目文件树

```
aioscheduler/
├── agent/
│   ├── agent.py          # ScheduleAgent 核心类
│   ├── tools.py          # 5个工具定义 + 辅助函数
│   ├── llm.py            # SiliconFlow API 客户端
│   ├── memory.py          # 对话历史管理
│   ├── config.py          # 配置管理器
│   ├── core.py            # 旧版 LangChain Agent（已废弃）
│   └── reminder.py        # 增强版提醒服务（备用）
├── database/
│   ├── models.py          # Schedule 数据模型 + Repository
│   └── connection.py       # SQLite 连接管理（单例）
├── services/
│   ├── reminder_service.py # 轮询版提醒服务（备用）
│   ├── schedule_service.py # 日程服务层
│   └── response_service.py # 响应格式化
├── nlp/
│   ├── parser.py          # 规则匹配 NLP 解析（旧版）
│   └── templates.py       # 回复模板管理
├── core/
│   ├── agent.py           # NLP版 Agent（旧版）
│   └── scheduler.py       # 后台状态日志调度器
├── config/
│   └── settings.py         # 应用配置
├── tests/
│   ├── test_agent.py       # 单元测试
│   └── test_integration.py  # 集成测试
├── main_agent.py           # Agent版入口（生产使用）
├── main.py                 # NLP版入口（旧版）
├── init_db.py              # 数据库初始化
└── aioscheduler.db         # SQLite 数据库文件（运行后生成）
```

---

## 十、扩展指南

### 10.1 添加新工具

只需三步：

```python
# 1. 在 agent/tools.py 添加新工具
@tool
def my_new_tool(param1: str, param2: int) -> str:
    """当用户想XXX时调用。"""
    # 业务逻辑
    return "操作结果"

# 2. 在 agent/agent.py 的 _register_builtin_tools() 中注册
self.register_tool(my_new_tool)

# 3. 在 System Prompt 中添加工具调用规则
"- 用户说"XXX" → 必须调用 my_new_tool(...)"
```

### 10.2 切换 LLM 模型

```python
# 方法1：启动参数
python main_agent.py --model "Qwen/Qwen2.5-14B-Instruct"

# 方法2：修改代码
agent = create_agent(api_key, model="deepseek-ai/DeepSeek-V4-Flash")
```

### 10.3 对接飞书/钉钉/微信通知

在 `ReminderService._trigger_reminder()` 中增加 HTTP POST 调用：

```python
def _trigger_reminder(self, schedule):
    message = self._get_warm_reminder(schedule.content)
    # 飞书 WebHook 示例
    requests.post("https://open.feishu.cn/open-apis/bot/v2/hook/xxx", json={
        "msg_type": "text",
        "content": {"text": message}
    })
```
