# 人工智能 NLP-Agent 数字人项目-基金问答智能体任务
"""
LangGraph SQL Agent 核心模块

基于 LangGraph 实现 NL2SQL 的问答智能体
"""

import json
import re
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from config.settings import settings
from core.db import SQL_TOOLS, db_manager, execute_sql, get_table_schema, list_tables
from core.llm import create_llm
from prompts.prompts import (
    ANSWER_GENERATION_PROMPT,
    ERROR_HANDLING_PROMPT,
    SCHEMA_PROMPT,
    SQL_CHECK_PROMPT,
    SQL_GENERATION_PROMPT,
)


def get_content(response: Any) -> str:
    """
    统一获取响应内容

    Args:
        response: LLM 或工具的响应

    Returns:
        str: 响应内容字符串
    """
    if hasattr(response, 'content'):
        return response.content
    return str(response)


def fix_table_and_column_names(sql: str) -> str:
    """
    修复 SQL 中的表名和列名，映射 LLM 生成的名称到实际数据库名称

    Args:
        sql: 原始 SQL 语句

    Returns:
        str: 修复后的 SQL 语句
    """
    if not sql:
        return sql

    # LLM表名 -> 实际数据库表名 映射
    table_mappings = {
        "A股股票日行情表": "A股票日行情表",
        "A股公司行业划分表": "A股公司行业划分表",
        "港股股票日行情表": "港股票日行情表",
        "基金基本信息": "基金基本信息",
        "基金股票持仓明细": "基金股票持仓明细",
        "基金债券持仓明细": "基金债券持仓明细",
        "基金可转债持仓明细": "基金可转债持仓明细",
        "基金日行情表": "基金日行情表",
        "基金规模变动表": "基金规模变动表",
        "基金份额持有人结构": "基金份额持有人结构",
    }

    # 处理表名
    for llm_name, db_name in table_mappings.items():
        quoted_db_name = f'"{db_name}"'
        quoted_llm_name = f'"{llm_name}"'
        if quoted_llm_name in sql:
            sql = sql.replace(quoted_llm_name, quoted_db_name)
        elif llm_name in sql:
            sql = sql.replace(llm_name, quoted_db_name)

    # 列名映射：LLM列名 -> 实际列名
    column_mappings = [
        ("交易日期", "交易日"),
        ("前收", "昨收盘(元)"),
        ("前收盘", "昨收盘(元)"),
        ("开盘价", "今开盘(元)"),
        ("今开盘", "今开盘(元)"),
        ("收盘价", "收盘价(元)"),
        ("最高价", "最高价(元)"),
        ("最低价", "最低价(元)"),
        ("成交量", "成交量(股)"),
        ("成交金额", "成交金额(元)"),
    ]

    # 处理列名
    for llm_col, db_col in column_mappings:
        # 替换 a.列名 形式
        sql = sql.replace(f'.{llm_col}', f'.{db_col}')
        # 替换 "列名" 形式
        sql = sql.replace(f'"{llm_col}"', f'"{db_col}"')
        # 替换 `列名` 形式
        sql = sql.replace(f'`{llm_col}`', f'"{db_col}"')
        # 替换 空格列名 形式
        sql = sql.replace(f' {llm_col}', f' "{db_col}"')
        # 替换括号内的列名 (列名)
        sql = sql.replace(f'({llm_col})', f'("{db_col}")')
        # 替换函数内的列名 ROUND(收盘价, 3) -> ROUND("收盘价(元)", 3)
        sql = sql.replace(f'{llm_col},', f'"{db_col}",')
        sql = sql.replace(f'{llm_col})', f'"{db_col}")')
        sql = sql.replace(f'{llm_col} ', f'"{db_col}" ')

    # 给含括号的列名加引号
    columns_with_parens = [
        "昨收盘(元)", "今开盘(元)", "收盘价(元)", "最高价(元)", "最低价(元)",
        "成交量(股)", "成交金额(元)"
    ]
    for col in columns_with_parens:
        # 替换 a.昨收盘(元) -> a."昨收盘(元)"
        pattern = f'.{col}"'
        if pattern not in sql:
            sql = sql.replace(f'.{col}', f'."{col}"')

    return sql


class AgentState(TypedDict):
    """
    Agent 状态定义

    包含对话历史和执行状态信息
    """
    messages: Annotated[List[Any], "消息列表，包含用户问题和Agent回复"]
    question: str                    # 当前问题
    generated_sql: Optional[str]      # 生成的 SQL
    query_result: Optional[str]      # 查询结果
    retry_count: int                 # 重试次数
    error_message: Optional[str]     # 错误信息
    selected_tables: Optional[List[str]]  # 选择的表
    schema_info: Optional[str]       # 表结构信息
    final_answer: Optional[str]      # 最终答案


def create_sql_agent():
    """
    创建 SQL Agent 工作流

    Returns:
        CompiledStateGraph: 编译后的状态图
    """
    # 创建 LLM
    llm = create_llm()

    # 获取工具
    run_query_tool = next(tool for tool in SQL_TOOLS if tool.name == "execute_sql")
    get_schema_tool = next(tool for tool in SQL_TOOLS if tool.name == "get_table_schema")

    # 创建工具节点
    run_query_node = ToolNode([run_query_tool], name="run_query")
    get_schema_node = ToolNode([get_schema_tool], name="get_schema")

    # ===== 节点定义 =====

    def list_tables_node(state: AgentState) -> AgentState:
        """列出数据库表节点"""
        tables_result = list_tables.invoke({})
        tables_str = get_content(tables_result)
        state["selected_tables"] = [t.strip() for t in tables_str.split(",") if t.strip()]
        return state

    def select_tables(state: AgentState) -> AgentState:
        """
        根据问题选择相关表节点

        使用 LLM 分析问题，选择需要查询的表
        """
        tables = state.get("selected_tables", [])
        if not tables:
            tables = db_manager.list_tables()

        prompt = SCHEMA_PROMPT.format(available_tables=", ".join(tables))
        response = llm.invoke([HumanMessage(content=prompt)])

        # 处理不同的返回类型
        response_content = response.content if hasattr(response, 'content') else str(response)

        # 解析 LLM 返回的表名
        selected = []
        for table in tables:
            if table in response_content:
                selected.append(table)

        # 如果 LLM 没有正确选择，根据关键词智能选择
        if not selected:
            question = state.get("question", "")
            question_lower = question.lower()

            # 关键词匹配选择表
            if any(k in question_lower for k in ["股票", "涨跌幅", "收盘价", "开盘价", "成交量", "成交金额", "最高价", "最低价"]):
                for t in ["A股股票日行情表", "港股股票日行情表"]:
                    if t in tables and t not in selected:
                        selected.append(t)

            if any(k in question_lower for k in ["行业", "中信行业", "一级行业", "二级行业"]):
                for t in ["A股公司行业划分表"]:
                    if t in tables and t not in selected:
                        selected.append(t)
                # 行业查询通常也需要行情数据
                for t in ["A股股票日行情表"]:
                    if t in tables and t not in selected:
                        selected.append(t)

            if any(k in question_lower for k in ["基金", "管理人", "赎回", "成立日期"]):
                for t in ["基金基本信息"]:
                    if t in tables and t not in selected:
                        selected.append(t)

            if any(k in question_lower for k in ["持仓"]):
                for t in ["基金股票持仓明细"]:
                    if t in tables and t not in selected:
                        selected.append(t)

            if not selected:
                selected = tables[:5]  # 默认选择前5张表

        state["selected_tables"] = selected
        return state

    def get_schema(state: AgentState) -> AgentState:
        """
        获取选定表的结构信息
        """
        tables = state.get("selected_tables", [])
        if not tables:
            state["schema_info"] = "无法获取表结构"
            return state

        tables_str = ", ".join(tables)
        schema_result = get_schema_tool.invoke({"table_names": tables_str})

        # 缓存表结构
        state["schema_info"] = get_content(schema_result)
        return state

    def generate_sql(state: AgentState) -> AgentState:
        """
        生成 SQL 查询节点

        使用 LLM 根据问题生成 SQL 语句
        """
        question = state.get("question", "")
        schema_info = state.get("schema_info", "")

        # 构建提示词
        prompt = SQL_GENERATION_PROMPT.format(
            dialect_description=schema_info
        )

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"用户问题: {question}\n\n请生成 SQL 查询语句:")
        ]

        response = llm.invoke(messages)

        # 从内容中提取 SQL
        content = get_content(response)

        # 提取 SQL - 尝试多种方式
        sql = None

        # 方式1: 查找代码块中的 SQL
        code_block_match = re.search(
            r"```(?:sql)?\s*\n?(SELECT[\s\S]+?)\n?```",
            content,
            re.IGNORECASE
        )
        if code_block_match:
            sql = code_block_match.group(1).strip()
        else:
            # 方式2: 查找完整的 SELECT 语句（支持子查询）
            # 匹配 SELECT 到最后的分号或语句结束
            select_start = re.search(r"SELECT", content, re.IGNORECASE)
            if select_start:
                # 从 SELECT 开始提取到文件末尾或最后一个分号
                potential_sql = content[select_start.start():].strip()
                # 移除可能的后续解释文字
                end_markers = ["\n\n", "\n用户", "\n以下是", "用户问题", "下面是"]
                for marker in end_markers:
                    if marker in potential_sql:
                        potential_sql = potential_sql.split(marker)[0]
                sql = potential_sql.strip()
                # 确保以分号结尾就添加
                if not sql.endswith(';'):
                    sql = sql.rstrip(';') + ';' if sql else sql

        if not sql:
            sql = content.strip()

        state["generated_sql"] = sql

        # 添加 SQL 到消息历史
        if state["generated_sql"]:
            # 修复表名和列名
            state["generated_sql"] = fix_table_and_column_names(state["generated_sql"])
            state["messages"].append(
                AIMessage(content=f"生成的 SQL:\n{state['generated_sql']}")
            )

        return state

    def check_sql(state: AgentState) -> AgentState:
        """
        SQL 检查节点

        检查生成的 SQL 是否正确
        """
        sql = state.get("generated_sql", "")
        if not sql:
            state["error_message"] = "没有生成 SQL 语句"
            return state

        # 获取 schema 信息
        schema_info = state.get("schema_info", "")

        # 构建检查提示词
        prompt = SQL_CHECK_PROMPT.format(schema_info=schema_info)

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"请检查以下 SQL:\n{sql}")
        ]

        response = llm.invoke(messages)

        # 从内容中提取 SQL
        content = get_content(response)

        # 提取 SQL - 尝试多种方式
        sql = None

        # 方式1: 查找代码块中的 SQL
        code_block_match = re.search(
            r"```(?:sql)?\s*\n?(SELECT[\s\S]+?)\n?```",
            content,
            re.IGNORECASE
        )
        if code_block_match:
            sql = code_block_match.group(1).strip()
        else:
            # 方式2: 查找完整的 SELECT 语句
            select_start = re.search(r"SELECT", content, re.IGNORECASE)
            if select_start:
                potential_sql = content[select_start.start():].strip()
                end_markers = ["\n\n", "\n用户", "\n以下是", "用户问题", "下面是"]
                for marker in end_markers:
                    if marker in potential_sql:
                        potential_sql = potential_sql.split(marker)[0]
                sql = potential_sql.strip()
                if not sql.endswith(';'):
                    sql = sql.rstrip(';') + ';' if sql else sql

        if not sql:
            sql = sql  # 保留原始 SQL

        state["generated_sql"] = sql
        return state

    def execute_query(state: AgentState) -> AgentState:
        """
        执行 SQL 查询节点
        """
        sql = state.get("generated_sql", "")
        if not sql:
            state["query_result"] = "没有可执行的 SQL 语句"
            return state

        # 修复表名和列名：添加引号包裹
        sql = fix_table_and_column_names(sql)

        # 执行查询
        result = db_manager.execute_query(sql)

        if not result["success"]:
            state["error_message"] = result["error"]
            state["retry_count"] = state.get("retry_count", 0) + 1
        else:
            state["query_result"] = format_query_result(result)
            state["error_message"] = None

        return state

    def retry_with_fix(state: AgentState) -> AgentState:
        """
        错误重试节点

        根据错误信息修正 SQL
        """
        if state.get("retry_count", 0) >= settings.max_retries:
            state["final_answer"] = "经过多次尝试仍无法正确回答您的问题，请简化问题或检查数据库是否包含相关信息。"
            return state

        error_msg = state.get("error_message", "")
        sql = state.get("generated_sql", "")
        schema = state.get("schema_info", "")

        prompt = ERROR_HANDLING_PROMPT.format(
            original_sql=sql,
            error_message=error_msg,
            schema_info=schema
        )

        messages = [
            SystemMessage(content=f"数据库 Schema:\n{schema}"),
            HumanMessage(content=prompt)
        ]

        response = llm.invoke(messages)

        # 提取修正后的 SQL
        content = get_content(response)

        sql = None

        # 方式1: 查找代码块
        code_block_match = re.search(
            r"```(?:sql)?\s*\n?(SELECT[\s\S]+?)\n?```",
            content,
            re.IGNORECASE
        )
        if code_block_match:
            sql = code_block_match.group(1).strip()
        else:
            # 方式2: 查找 SELECT 开始到结束
            select_start = re.search(r"SELECT", content, re.IGNORECASE)
            if select_start:
                potential_sql = content[select_start.start():].strip()
                end_markers = ["\n\n", "\n用户", "\n以下是"]
                for marker in end_markers:
                    if marker in potential_sql:
                        potential_sql = potential_sql.split(marker)[0]
                sql = potential_sql.strip()
                if sql and not sql.endswith(';'):
                    sql = sql.rstrip(';') + ';'

        if not sql:
            sql = content.strip()

        state["generated_sql"] = sql
        state["error_message"] = None
        return state

    def generate_answer(state: AgentState) -> AgentState:
        """
        生成最终答案节点
        """
        question = state.get("question", "")
        query_result = state.get("query_result", "无法获取查询结果")
        schema = state.get("schema_info", "")

        prompt = ANSWER_GENERATION_PROMPT.format(
            question=question,
            query_result=query_result
        )

        messages = [
            SystemMessage(content="你是一个专业的金融数据分析师。"),
            HumanMessage(content=prompt)
        ]

        response = llm.invoke(messages)
        state["final_answer"] = get_content(response)

        # 添加到消息历史
        state["messages"].append(AIMessage(content=get_content(response)))

        return state

    # ===== 条件边定义 =====

    def should_retry(state: AgentState) -> Literal["retry", "generate_answer", "generate_sql"]:
        """
        决定是否重试或结束

        Returns:
            str: 下一个节点名称
        """
        if state.get("error_message"):
            retry_count = state.get("retry_count", 0)
            if retry_count < settings.max_retries:
                return "retry"
            else:
                return "generate_answer"
        return "generate_answer"

    def should_check_sql(state: AgentState) -> Literal["check_sql", "generate_answer"]:
        """
        决定是否需要检查 SQL

        Returns:
            str: 下一个节点名称
        """
        if state.get("generated_sql"):
            return "check_sql"
        return "generate_answer"

    # ===== 构建工作流 =====

    builder = StateGraph(AgentState)

    # 添加节点
    builder.add_node("list_tables", list_tables_node)
    builder.add_node("select_tables", select_tables)
    builder.add_node("get_schema", get_schema)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("check_sql", check_sql)
    builder.add_node("run_query", execute_query)
    builder.add_node("retry", retry_with_fix)
    builder.add_node("generate_answer", generate_answer)

    # 添加边
    builder.add_edge(START, "list_tables")
    builder.add_edge("list_tables", "select_tables")
    builder.add_edge("select_tables", "get_schema")
    builder.add_edge("get_schema", "generate_sql")

    # generate_sql 条件边
    builder.add_conditional_edges(
        "generate_sql",
        should_check_sql,
    )

    # check_sql 条件边（检查后执行查询或直接生成答案）
    builder.add_conditional_edges(
        "check_sql",
        lambda s: "run_query" if s.get("generated_sql") else "generate_answer"
    )

    # run_query 条件边（执行后根据错误决定重试或生成答案）
    builder.add_conditional_edges(
        "run_query",
        should_retry,
    )

    builder.add_edge("retry", "generate_sql")
    builder.add_edge("generate_answer", END)

    # 编译工作流
    return builder.compile()


def format_query_result(result: Dict[str, Any]) -> str:
    """
    格式化查询结果

    Args:
        result: 查询结果字典

    Returns:
        str: 格式化后的字符串
    """
    if not result.get("rows"):
        return "查询结果为空"

    columns = result.get("columns", [])
    rows = result.get("rows", [])

    lines = [f"查询结果 (共 {len(rows)} 行):"]
    lines.append(f"列: {', '.join(columns)}")
    lines.append("-" * 60)

    for row in rows[:50]:  # 限制显示行数
        values = [str(v) for v in row]
        lines.append(" | ".join(values))

    if len(rows) > 50:
        lines.append(f"... 还有 {len(rows) - 50} 行")

    return "\n".join(lines)


class FundQAAgent:
    """
    基金问答智能体

    对外接口类，提供问答功能
    """

    def __init__(self):
        """初始化 Agent"""
        self.graph = create_sql_agent()

    def ask(self, question: str) -> Dict[str, Any]:
        """
        回答用户问题

        Args:
            question: 用户问题

        Returns:
            Dict: 包含答案和其他信息的字典
        """
        initial_state = AgentState(
            messages=[HumanMessage(content=question)],
            question=question,
            generated_sql=None,
            query_result=None,
            retry_count=0,
            error_message=None,
            selected_tables=None,
            schema_info=None,
            final_answer=None
        )

        result = self.graph.invoke(initial_state)

        return {
            "question": question,
            "sql": result.get("generated_sql"),
            "query_result": result.get("query_result"),
            "answer": result.get("final_answer"),
            "retry_count": result.get("retry_count", 0),
            "error": result.get("error_message")
        }

    def ask_stream(self, question: str):
        """
        流式回答（需要时可以扩展）

        Args:
            question: 用户问题
        """
        # 流式实现可以后续添加
        result = self.ask(question)
        yield result
