# 基金问答智能体设计文档

## 一、项目概述

### 1.1 项目背景
本项目是一个基于自然语言处理的基金数据问答智能体，能够将用户用自然语言提出的问题转换为 SQL 查询语句，从基金数据库中获取数据并生成回答。

### 1.2 核心功能
- **NL2SQL（自然语言转SQL）**：使用大语言模型理解用户问题并生成精确的 SQL 查询
- **智能表选择**：根据问题内容自动选择需要查询的数据库表
- **错误自愈**：SQL 执行失败时自动修正重试
- **多轮对话**：支持交互式问答模式

### 1.3 技术架构
```
┌─────────────────────────────────────────────────────────────────┐
│                        用户层                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ 命令行   │  │ Flask API │  │ 批量测试 │  │ Web界面  │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      LangGraph Agent 层                          │
│  ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌───────┐ │
│  │列表表  │──▶│选择表  │──▶│获取结构│──▶│生成SQL │──▶│检查SQL│ │
│  └────────┘   └────────┘   └────────┘   └────────┘   └───────┘ │
│       │                                        │                │
│       │         ┌──────────────────────┐       │                │
│       └────────▶│   错误重试机制       │◀──────┘                │
│                 └──────────────────────┘                        │
│                         │                                       │
│                 ┌────────▼────────┐                             │
│                 │   生成最终答案   │                             │
│                 └─────────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                        LLM 层                                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │              SiliconFlow API (DeepSeek-V4-Flash)           │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                       数据层                                     │
│  ┌──────────────────┐        ┌──────────────────────────────────┐│
│  │   SQLite 数据库  │        │  博金杯基金数据 (10张表)         ││
│  └──────────────────┘        └──────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、模块设计

### 2.1 核心模块架构

```
fund-qa-agent/
├── config/                    # 配置模块
│   └── settings.py           # 配置加载 (.env)
├── core/                      # 核心模块
│   ├── agent.py             # LangGraph 工作流
│   ├── db.py                # 数据库操作
│   └── llm.py               # LLM API 调用
├── prompts/                   # 提示词模板
│   └── prompts.py           # SQL 生成、检查、答案生成提示词
├── data/                      # 数据目录
│   ├── question.json        # 测试问题
│   └── 博金杯比赛数据.db    # SQLite 数据库
├── main.py                    # 命令行入口
├── test.py                    # 测试脚本
└── api.py                     # Flask API 服务
```

### 2.2 各模块详细说明

#### 2.2.1 配置模块 (`config/settings.py`)

**功能**：统一管理系统配置

**配置项**：
| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `SILICONFLOW_API_KEY` | 硅基流动 API 密钥 | - |
| `MODEL_NAME` | 模型名称 | deepseek-ai/DeepSeek-V4-Flash |
| `TEMPERATURE` | 温度参数 | 0.1 |
| `MAX_TOKENS` | 最大 token 数 | 4096 |
| `DB_PATH` | 数据库路径 | ./data/博金杯比赛数据.db |
| `MAX_RETRIES` | 最大重试次数 | 3 |

**核心代码**：
```python
class Settings(BaseModel):
    siliconflow_api_key: str
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    model_name: str = "deepseek-ai/DeepSeek-V4-Flash"
    temperature: float = 0.1
    max_tokens: int = 4096
    db_path: str = "./data/博金杯比赛数据.db"
    max_retries: int = 3
```

---

#### 2.2.2 数据库模块 (`core/db.py`)

**功能**：封装所有数据库操作

**核心类**：`DatabaseManager`

**主要方法**：

| 方法 | 说明 |
|------|------|
| `list_tables()` | 获取所有表名 |
| `get_schema(table_name)` | 获取指定表的结构信息 |
| `get_full_schema(table_names)` | 获取多个表的完整模式描述 |
| `execute_query(query)` | 执行 SQL 查询 |
| `describe_all_tables()` | 获取所有表的描述 |

**SQL 注入防护**：
```python
dangerous_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", ...]
for keyword in dangerous_keywords:
    if query_upper.startswith(keyword):
        return {"success": False, "error": "禁止执行修改操作"}
```

**LangChain 工具**：
```python
@tool
def list_tables() -> str: ...

@tool
def get_table_schema(table_names: str) -> str: ...

@tool
def execute_sql(query: str) -> str: ...
```

---

#### 2.2.3 LLM 模块 (`core/llm.py`)

**功能**：封装 SiliconFlow API 调用

**核心类**：`SiliconFlowChatModel`

**继承关系**：`BaseChatModel` (LangChain)

**关键方法**：

| 方法 | 说明 |
|------|------|
| `_convert_messages_to_openai_format()` | 转换消息格式 |
| `_call_api()` | 调用 API |
| `_generate()` | 生成回复 |

**工厂函数**：
```python
def create_llm() -> SiliconFlowChatModel:
    return SiliconFlowChatModel(
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        model_name=settings.model_name,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens
    )
```

---

#### 2.2.4 Agent 模块 (`core/agent.py`)

**功能**：实现 LangGraph 工作流

**核心概念**：`AgentState`

```python
class AgentState(TypedDict):
    messages: Annotated[List[Any], "消息列表"]
    question: str                    # 当前问题
    generated_sql: Optional[str]      # 生成的 SQL
    query_result: Optional[str]      # 查询结果
    retry_count: int                 # 重试次数
    error_message: Optional[str]      # 错误信息
    selected_tables: Optional[List[str]]  # 选择的表
    schema_info: Optional[str]       # 表结构信息
    final_answer: Optional[str]      # 最终答案
```

---

## 三、工作流程详解

### 3.1 完整工作流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户提问                                      │
│                    "2021年1月5日综合金融行业涨幅最大的股票是什么？"      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         list_tables 节点                                │
│                         列出所有数据库表                                  │
│  ┌─────────────┬─────────────┬─────────────┬─────────────┐            │
│  │基金基本信息│基金股票持仓│基金债券持仓│基金日行情 │ ...          │
│  └─────────────┴─────────────┴─────────────┴─────────────┘            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         select_tables 节点                              │
│                    根据问题关键词选择相关表                                │
│                                                                          │
│  关键词: ["股票", "涨跌幅", "收盘价"] → 选择 "A股股票日行情表"          │
│  关键词: ["行业", "中信行业"] → 选择 "A股公司行业划分表"                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          get_schema 节点                                │
│                      获取选定表的详细结构                                 │
│                                                                          │
│  表: A股票日行情表                                                       │
│  列: 股票代码, 交易日, 昨收盘(元), 今开盘(元), 收盘价(元)...             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        generate_sql 节点                                 │
│                       LLM 生成 SQL 语句                                  │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ SELECT a.股票代码, ROUND((a."收盘价(元)" - a."昨收盘(元)") /    │   │
│  │        a."昨收盘(元)" * 100, 2) AS 涨跌幅                        │   │
│  │ FROM "A股票日行情表" a                                          │   │
│  │ JOIN "A股公司行业划分表" b ON a.股票代码 = b.股票代码            │   │
│  │ WHERE a.交易日 = '20210105' AND b.一级行业名称 = '综合金融'      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       fix_table_and_column_names                         │
│                    修复表名和列名（关键步骤）                              │
│                                                                          │
│  LLM表名 → 实际表名:                                                    │
│    "A股股票日行情表" → "A股票日行情表"                                  │
│                                                                          │
│  LLM列名 → 实际列名:                                                    │
│    "交易日期" → "交易日"                                                 │
│    "收盘价" → "收盘价(元)" (加引号)                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         check_sql 节点                                   │
│                       验证 SQL 语法正确性                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         run_query 节点                                   │
│                        执行 SQL 查询                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
            ┌──────────────┐               ┌──────────────┐
            │  执行成功    │               │   执行失败    │
            └──────────────┘               └──────────────┘
                    │                               │
                    ▼                               ▼
            ┌──────────────┐               ┌──────────────┐
            │generate_answer│              │ retry 节点   │
            │  生成答案    │               │ 修正 SQL     │
            └──────────────┘               └──────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    ▼
                        ┌──────────────────┐
                        │   最终答案输出    │
                        └──────────────────┘
```

### 3.2 各节点详细说明

#### 节点 1: `list_tables`
```python
def list_tables_node(state: AgentState) -> AgentState:
    """列出数据库表节点"""
    tables_result = list_tables.invoke({})
    tables_str = get_content(tables_result)
    state["selected_tables"] = [t.strip() for t in tables_str.split(",")]
    return state
```

**输出**：`["基金基本信息", "基金股票持仓明细", "基金债券持仓明细", ...]`

---

#### 节点 2: `select_tables`
```python
def select_tables(state: AgentState) -> AgentState:
    """
    根据问题选择相关表
    1. 使用 LLM 分析问题
    2. 关键词匹配兜底
    """
    # 关键词匹配
    if any(k in question_lower for k in ["股票", "涨跌幅", "收盘价"]):
        selected.append("A股股票日行情表")
    if any(k in question_lower for k in ["行业", "中信行业"]):
        selected.append("A股公司行业划分表")
    # ...
```

**关键词映射表**：
| 关键词 | 选择的表 |
|--------|----------|
| 股票、涨跌幅、收盘价、开盘价、成交量、成交金额 | A股股票日行情表 |
| 行业、中信行业、一级行业、二级行业 | A股公司行业划分表 |
| 基金、管理人、赎回、成立日期 | 基金基本信息 |
| 持仓 | 基金股票持仓明细 |

---

#### 节点 3: `get_schema`
```python
def get_schema(state: AgentState) -> AgentState:
    """获取选定表的结构"""
    schema_result = get_schema_tool.invoke({"table_names": tables_str})
    state["schema_info"] = get_content(schema_result)
    return state
```

**输出示例**：
```
表名: A股票日行情表
列信息:
  - 股票代码: TEXT PRIMARY KEY
  - 交易日: TEXT NOT NULL
  - 昨收盘(元): REAL
  - 今开盘(元): REAL
  - 收盘价(元): REAL
  - 最高价(元): REAL
  - 最低价(元): REAL
  - 成交量(股): REAL
  - 成交金额(元): REAL
```

---

#### 节点 4: `generate_sql`
```python
def generate_sql(state: AgentState) -> AgentState:
    """使用 LLM 生成 SQL"""
    prompt = SQL_GENERATION_PROMPT.format(dialect_description=schema_info)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=f"用户问题: {question}\n\n请生成 SQL 查询语句:")
    ]
    response = llm.invoke(messages)
    # 提取 SQL（支持代码块和纯文本）
    sql = extract_sql(response.content)
    state["generated_sql"] = sql
    return state
```

**SQL 提取逻辑**：
1. 优先匹配代码块 ` ```sql ... ``` `
2. 其次匹配 `SELECT` 开头的语句
3. 移除后续解释文字

---

#### 节点 5: `fix_table_and_column_names` (关键)

**问题背景**：
LLM 生成的 SQL 与实际数据库Schema存在差异：
- 表名差异：`A股股票日行情表` → `A股票日行情表`
- 列名差异：`交易日期` → `交易日`，`收盘价` → `收盘价(元)`
- 引号缺失：含括号的列名需要双引号包裹

**实现代码**：
```python
def fix_table_and_column_names(sql: str) -> str:
    # 1. 表名映射
    table_mappings = {
        "A股股票日行情表": "A股票日行情表",
        "A股公司行业划分表": "A股公司行业划分表",
        ...
    }

    # 2. 列名映射
    column_mappings = [
        ("交易日期", "交易日"),
        ("前收", "昨收盘(元)"),
        ("开盘价", "今开盘(元)"),
        ("收盘价", "收盘价(元)"),
        ...
    ]

    # 3. 替换逻辑
    for llm_name, db_name in table_mappings.items():
        sql = sql.replace(llm_name, f'"{db_name}"')

    for llm_col, db_col in column_mappings:
        sql = sql.replace(f'.{llm_col}', f'.{db_col}')
        sql = sql.replace(f'"{llm_col}"', f'"{db_col}"')
        sql = sql.replace(f'{llm_col},', f'"{db_col}",')

    # 4. 给含括号的列名加引号
    for col in ["昨收盘(元)", "今开盘(元)", "收盘价(元)", ...]:
        sql = sql.replace(f'.{col}', f'."{col}"')

    return sql
```

**映射表**：

| LLM表名 | 实际表名 |
|---------|----------|
| A股股票日行情表 | A股票日行情表 |
| A股公司行业划分表 | A股公司行业划分表 |
| 港股股票日行情表 | 港股票日行情表 |

| LLM列名 | 实际列名 |
|---------|----------|
| 交易日期 | 交易日 |
| 收盘价 | 收盘价(元) |
| 开盘价 | 今开盘(元) |
| 成交量 | 成交量(股) |
| 成交金额 | 成交金额(元) |

---

#### 节点 6: `check_sql`
```python
def check_sql(state: AgentState) -> AgentState:
    """验证 SQL 正确性"""
    prompt = SQL_CHECK_PROMPT.format(schema_info=schema_info)
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=f"请检查以下 SQL:\n{sql}")
    ]
    response = llm.invoke(messages)
    # 提取修正后的 SQL
    return state
```

---

#### 节点 7: `run_query`
```python
def execute_query(state: AgentState) -> AgentState:
    """执行 SQL 查询"""
    sql = fix_table_and_column_names(state["generated_sql"])
    result = db_manager.execute_query(sql)

    if result["success"]:
        state["query_result"] = format_query_result(result)
    else:
        state["error_message"] = result["error"]
        state["retry_count"] += 1

    return state
```

---

#### 节点 8: `retry`
```python
def retry_with_fix(state: AgentState) -> AgentState:
    """错误重试"""
    if state["retry_count"] >= settings.max_retries:
        state["final_answer"] = "经过多次尝试仍无法正确回答..."
        return state

    prompt = ERROR_HANDLING_PROMPT.format(
        original_sql=sql,
        error_message=error_msg,
        schema_info=schema
    )
    response = llm.invoke(messages)
    # 提取修正后的 SQL
    return state
```

---

#### 节点 9: `generate_answer`
```python
def generate_answer(state: AgentState) -> AgentState:
    """生成最终答案"""
    prompt = ANSWER_GENERATION_PROMPT.format(
        question=question,
        query_result=query_result
    )
    response = llm.invoke(messages)
    state["final_answer"] = get_content(response)
    return state
```

---

## 四、关键技术点

### 4.1 LangGraph 状态机

**节点定义**：
```python
builder = StateGraph(AgentState)
builder.add_node("list_tables", list_tables_node)
builder.add_node("select_tables", select_tables)
builder.add_node("get_schema", get_schema)
builder.add_node("generate_sql", generate_sql)
builder.add_node("check_sql", check_sql)
builder.add_node("run_query", execute_query)
builder.add_node("retry", retry_with_fix)
builder.add_node("generate_answer", generate_answer)
```

**边定义**：
```python
builder.add_edge(START, "list_tables")
builder.add_edge("list_tables", "select_tables")
builder.add_edge("select_tables", "get_schema")
builder.add_edge("get_schema", "generate_sql")
```

**条件边**：
```python
def should_retry(state: AgentState) -> Literal["retry", "generate_answer"]:
    if state.get("error_message"):
        if state.get("retry_count", 0) < settings.max_retries:
            return "retry"
    return "generate_answer"

builder.add_conditional_edges("run_query", should_retry)
```

### 4.2 SQL 提取正则表达式

```python
# 匹配代码块中的 SQL
code_block_match = re.search(
    r"```(?:sql)?\s*\n?(SELECT[\s\S]+?)\n?```",
    content,
    re.IGNORECASE
)

# 匹配 SELECT 开头的语句
select_start = re.search(r"SELECT", content, re.IGNORECASE)
potential_sql = content[select_start.start():].strip()
```

### 4.3 提示词工程

**SQL 生成提示词**：
```python
SQL_GENERATION_PROMPT = """
你是一个 SQL 专家。请根据以下数据库结构生成 SQL 查询语句。

数据库 Schema:
{dialect_description}

要求：
1. 只使用 SELECT 语句
2. 表名和列名必须与上述 Schema 一致
3. 股票涨跌幅计算公式: (收盘价-昨收)/昨收*100
...
"""
```

### 4.4 安全机制

**只读防护**：
```python
dangerous_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER"]
for keyword in dangerous_keywords:
    if query_upper.startswith(keyword):
        return {"success": False, "error": "禁止执行"}
```

---

## 五、数据模型

### 5.1 数据库表结构

| 表名 | 说明 | 主要列 |
|------|------|--------|
| 基金基本信息 | 基金基本信息 | 基金代码, 基金全称, 管理人, 成立日期 |
| 基金股票持仓明细 | 基金持仓股票 | 基金代码, 持仓日期, 股票代码, 数量, 市值 |
| 基金债券持仓明细 | 基金持仓债券 | 基金代码, 持仓日期, 债券名称, 持债数量 |
| 基金可转债持仓明细 | 基金持仓可转债 | 基金代码, 对应股票代码, 数量, 市值 |
| 基金日行情表 | 基金每日行情 | 基金代码, 交易日期, 单位净值 |
| A股票日行情表 | A股日行情 | 股票代码, 交易日, 收盘价(元), 成交量(股) |
| 港股票日行情表 | 港股日行情 | 股票代码, 交易日, 收盘价, 成交量 |
| A股公司行业划分表 | 行业分类 | 股票代码, 行业划分标准, 一级行业名称 |
| 基金规模变动表 | 基金规模变化 | 基金代码, 申购份额, 赎回份额 |
| 基金份额持有人结构 | 持有人结构 | 机构持有比例, 个人持有比例 |

---

## 六、接口设计

### 6.1 对外接口类

```python
class FundQAAgent:
    def __init__(self):
        self.graph = create_sql_agent()

    def ask(self, question: str) -> Dict[str, Any]:
        """
        回答用户问题
        Returns: {
            "question": str,      # 原问题
            "sql": str,           # 生成的 SQL
            "query_result": str,  # 查询结果
            "answer": str,        # 最终答案
            "retry_count": int,   # 重试次数
            "error": str          # 错误信息
        }
        """
        result = self.graph.invoke(initial_state)
        return {...}
```

### 6.2 返回格式

```json
{
    "question": "2021年1月5日综合金融行业涨幅最大的股票是什么？",
    "sql": "SELECT ... FROM ...",
    "query_result": "查询结果 (共 1 行):\n股票代码 | 涨跌幅\n600120 | 0.84%",
    "answer": "在2021年1月5日，中信行业分类一级行业为综合金融行业中，涨跌幅最大的股票代码是600120，涨跌幅为0.84%",
    "retry_count": 0,
    "error": null
}
```

---

## 七、测试用例

### 7.1 功能测试

| ID | 问题 | 预期结果 |
|----|------|----------|
| 0 | 20210105综合金融涨跌幅最大股票 | 600120, 0.84% |
| 1 | 长远锂科发起人法人 | 数据库无此数据 |
| 2 | 建筑材料涨幅>5%股票数量 | 1只 |
| 3 | 688338涨停天数 | 0天 |
| 4 | 非银金融成交量合计 | 2.67万亿股 |
| 5 | 嘉实2019年成立基金数 | 55只 |

### 7.2 边界测试

- 空查询结果
- SQL 执行超时
- LLM API 调用失败
- 数据库连接失败

---

## 八、部署架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Nginx (反向代理)                          │
│                        端口: 80/443                              │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      Gunicorn/Uvicorn                           │
│                      (Python WSGI Server)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      Flask API Server                            │
│                      (api.py)                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      FundQAAgent                                 │
│                      (LangGraph Agent)                          │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  SQLite DB    │    │ SiliconFlow   │    │    Redis      │
│  (本地文件)   │    │    API        │    │  (可选缓存)    │
└───────────────┘    └───────────────┘    └───────────────┘
```
