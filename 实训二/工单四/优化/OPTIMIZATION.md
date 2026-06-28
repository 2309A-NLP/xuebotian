# 基金问答智能体优化文档

## 一、性能优化

### 1.1 LLM 调用优化

#### 1.1.1 批量请求优化
当前问题：每个问题单独调用 LLM API，延迟高
优化方案：实现批量处理和请求合并

```python
# 优化前：逐个调用
for question in questions:
    agent.ask(question)

# 优化后：批量调用
async def batch_ask(questions: List[str], batch_size: int = 5):
    """批量处理问题，减少 API 调用开销"""
    results = []
    for i in range(0, len(questions), batch_size):
        batch = questions[i:i + batch_size]
        # 并行处理批次
        batch_results = await asyncio.gather(*[
            agent.ask(q) for q in batch
        ])
        results.extend(batch_results)
    return results
```

#### 1.1.2 缓存机制
**方案 A：Redis 缓存 Schema 信息**
```python
import redis
from functools import lru_cache

redis_client = redis.Redis(host='localhost', port=6379, db=0)

def get_cached_schema(table_name: str) -> str:
    """缓存表结构，减少数据库查询"""
    cache_key = f"schema:{table_name}"
    cached = redis_client.get(cache_key)

    if cached:
        return cached.decode('utf-8')

    schema = db_manager.get_full_schema([table_name])
    redis_client.setex(cache_key, 3600, schema)  # 缓存1小时
    return schema
```

**方案 B：内存缓存**
```python
from functools import lru_cache

@lru_cache(maxsize=128)
def get_schema_cached(table_name: str) -> str:
    """LRU 缓存表结构"""
    return db_manager.get_full_schema([table_name])
```

#### 1.1.3 模型选择优化
```python
# 根据问题复杂度选择模型
def select_model_by_complexity(question: str) -> str:
    """根据问题复杂度选择合适的模型"""
    # 简单查询使用轻量模型
    simple_keywords = ["有多少", "统计", "总和"]
    if any(k in question for k in simple_keywords):
        return "deepseek-ai/DeepSeek-V2.5"  # 更快更便宜

    # 复杂查询使用强模型
    return "deepseek-ai/DeepSeek-V4-Flash"
```

### 1.2 数据库优化

#### 1.2.1 连接池
当前问题：每次查询创建新连接
```python
# 优化前
def execute_query(self, query: str):
    conn = sqlite3.connect(self.db_path)  # 每次新建
    # ...
    conn.close()

# 优化后：连接池
from queue import Queue
import threading

class ConnectionPool:
    def __init__(self, db_path, pool_size=5):
        self.pool = Queue(maxsize=pool_size)
        self.db_path = db_path
        for _ in range(pool_size):
            conn = sqlite3.connect(db_path)
            self.pool.put(conn)

    def get_connection(self):
        return self.pool.get()

    def return_connection(self, conn):
        self.pool.put(conn)
```

#### 1.2.2 索引优化
```sql
-- 为常用查询添加索引
CREATE INDEX IF NOT EXISTS idx_stock_date ON "A股票日行情表"(股票代码, 交易日);
CREATE INDEX IF NOT EXISTS idx_industry_stock ON "A股公司行业划分表"(股票代码, 交易日);
CREATE INDEX IF NOT EXISTS idx_fund_date ON "基金股票持仓明细"(基金代码, 持仓日期);
```

#### 1.2.3 查询优化
```python
def execute_query_optimized(self, query: str, timeout: int = 30):
    """带超时控制的查询"""
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError("Query timeout")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)  # 30秒超时

    try:
        result = self._execute_query(query)
        signal.alarm(0)  # 取消超时
        return result
    except TimeoutError:
        return {"success": False, "error": "查询超时"}
```

### 1.3 工作流优化

#### 1.3.1 并行表选择
```python
# 优化前：串行选择表
def select_tables(state: AgentState) -> AgentState:
    tables = db_manager.list_tables()
    # ... 逐个匹配

# 优化后：并行处理
async def select_tables_async(state: AgentState) -> AgentState:
    tables = db_manager.list_tables()

    # 并行获取关键词匹配和 LLM 分析
    keyword_task = asyncio.to_thread(keyword_based_selection, state["question"])
    llm_task = llm.invoke_async(select_tables_prompt)

    keyword_result, llm_result = await asyncio.gather(keyword_task, llm_task)
    # 合并结果
    return state
```

#### 1.3.2 Schema 预加载
```python
class FundQAAgent:
    def __init__(self):
        self.graph = create_sql_agent()
        self._schema_cache = {}

    def preload_schema(self):
        """启动时预加载所有表的 Schema"""
        tables = db_manager.list_tables()
        for table in tables:
            self._schema_cache[table] = db_manager.get_full_schema([table])

    def get_schema(self, tables: List[str]) -> str:
        """从缓存获取 Schema"""
        schemas = [self._schema_cache.get(t, "") for t in tables]
        return "\n".join(s for s in schemas if s)
```

#### 1.3.3 SQL 验证优化
```python
# 优化前：每次都调用 LLM 验证
def check_sql(state: AgentState) -> AgentState:
    response = llm.invoke([...])  # LLM 调用
    # ...

# 优化后：规则预检 + LLM 复检
def check_sql_optimized(state: AgentState) -> AgentState:
    sql = state["generated_sql"]

    # 规则预检
    errors = validate_sql_rules(sql)
    if errors:
        state["generated_sql"] = None
        state["error_message"] = "; ".join(errors)
        return state

    # LLM 复检（仅对复杂查询）
    if is_complex_query(sql):
        response = llm.invoke([...])
        # ...

    return state

def validate_sql_rules(sql: str) -> List[str]:
    """SQL 规则验证"""
    errors = []
    sql_upper = sql.upper()

    # 检查 SELECT
    if not sql_upper.strip().startswith("SELECT"):
        errors.append("仅支持 SELECT 查询")

    # 检查危险关键字
    dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]
    for kw in dangerous:
        if kw in sql_upper:
            errors.append(f"禁止使用 {kw}")

    # 检查引号匹配
    if sql.count('"') % 2 != 0:
        errors.append("引号不匹配")

    return errors
```

---

## 二、准确率优化

### 2.1 提示词优化

#### 2.1.1 Few-shot 示例
```python
SQL_GENERATION_PROMPT = """
你是一个 SQL 专家。请根据以下数据库结构生成 SQL 查询语句。

数据库 Schema:
{dialect_description}

示例：
1. 问题：查询2021年涨跌幅最大的股票
    SQL: SELECT 股票代码, MAX((收盘价-昨收)/昨收*100) as 涨跌幅
         FROM "A股票日行情表"
         WHERE 交易日 LIKE '2021%'
         GROUP BY 股票代码 ORDER BY 涨跌幅 DESC LIMIT 1

2. 问题：统计每个行业的股票数量
    SQL: SELECT 一级行业名称, COUNT(*) as 数量
         FROM "A股公司行业划分表"
         GROUP BY 一级行业名称

现在请回答：
用户问题: {question}
SQL:
"""
```

#### 2.1.2 Chain-of-Thought
```python
COT_SQL_PROMPT = """
你是一个 SQL 专家。请分步骤思考并生成 SQL：

1. 理解问题：
   - 提取关键实体（股票、行业、基金）
   - 确定需要查询的日期范围
   - 明确计算需求（涨跌幅、统计、排序）

2. 规划查询：
   - 确定需要的表
   - 确定表之间的连接条件
   - 确定 WHERE 条件

3. 生成 SQL：

数据库 Schema:
{schema}

用户问题: {question}
"""
```

### 2.2 SQL 修复优化

#### 2.2.1 错误分类与修复
```python
def classify_and_fix_error(error: str, sql: str, schema: str) -> str:
    """根据错误类型选择修复策略"""

    if "no such table" in error:
        # 表名错误
        return fix_table_name(sql)

    if "no such column" in error:
        # 列名错误
        return fix_column_name(sql, schema)

    if "syntax error" in error:
        # 语法错误
        return fix_syntax(sql)

    if "ambigous" in error:
        # 列名歧义
        return fix_ambiguous(sql)

    # 通用修复
    return llm_fix(sql, error, schema)
```

#### 2.2.2 增量修复
```python
def incremental_fix(state: AgentState) -> AgentState:
    """增量修复 SQL"""

    error = state["error_message"]
    sql = state["generated_sql"]
    history = state.get("fix_history", [])

    # 记录修复历史，避免重复尝试
    if sql in history:
        return state  # 已尝试过，放弃

    history.append(sql)
    state["fix_history"] = history

    # 根据错误类型选择修复策略
    if "no such column" in error:
        # 提取列名，查询正确列名
        col_match = re.search(r'no such column: (.+)', error)
        if col_match:
            wrong_col = col_match.group(1)
            correct_col = find_closest_column(wrong_col, schema)
            sql = sql.replace(wrong_col, correct_col)

    # ...
    return state
```

### 2.3 表选择优化

#### 2.3.1 语义相似度匹配
```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class SemanticTableSelector:
    def __init__(self):
        self.vectorizer = TfidfVectorizer()
        self.table_descriptions = self._load_table_descriptions()

    def select_tables(self, question: str) -> List[str]:
        """基于语义相似度选择表"""
        question_vec = self.vectorizer.fit_transform([question])
        table_vecs = self.vectorizer.transform(self.table_descriptions)

        similarities = cosine_similarity(question_vec, table_vecs)[0]
        top_k = min(3, len(similarities))
        top_indices = similarities.argsort()[-top_k:]

        return [self.tables[i] for i in top_indices if similarities[i] > 0.1]
```

#### 2.3.2 动态 Schema 注入
```python
def generate_sql_dynamic_schema(state: AgentState) -> AgentState:
    """根据问题动态选择 Schema"""

    question = state["question"]

    # 识别需要的表类型
    table_types = []
    if any(k in question for k in ["股票", "行情", "涨跌幅"]):
        table_types.append("行情表")
    if any(k in question for k in ["行业", "分类"]):
        table_types.append("行业表")
    if any(k in question for k in ["基金", "持仓"]):
        table_types.append("基金表")

    # 只获取相关表的 Schema
    relevant_tables = []
    for t in db_manager.list_tables():
        if any(tp in t for tp in table_types):
            relevant_tables.append(t)

    schema = db_manager.get_full_schema(relevant_tables)

    # 生成 SQL
    prompt = SQL_GENERATION_PROMPT.format(schema=schema)
    # ...
```

---

## 三、可靠性优化

### 3.1 错误处理

#### 3.1.1 熔断器模式
```python
from functools import wraps
import time

class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half_open

    def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "half_open"
            else:
                raise CircuitOpenException()

        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise e

    def on_success(self):
        self.failure_count = 0
        self.state = "closed"

    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

# 使用
llm_circuit_breaker = CircuitBreaker(failure_threshold=3, timeout=300)

def call_llm(messages):
    return llm_circuit_breaker.call(llm.invoke, messages)
```

#### 3.1.2 重试策略
```python
import random
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(APIError)
)
def call_llm_with_retry(messages):
    """带指数退避的 LLM 调用"""
    response = llm.invoke(messages)

    # 检查是否需要重试
    if is_rate_limit_error(response):
        raise RateLimitError()

    return response
```

### 3.2 日志与监控

#### 3.2.1 结构化日志
```python
import logging
import json
from datetime import datetime

class StructuredLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

    def log(self, level: str, event: str, **kwargs):
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            **kwargs
        }
        getattr(self.logger, level)(json.dumps(log_data, ensure_ascii=False))

# 使用
logger = StructuredLogger("fund_qa_agent")
logger.log("info", "query_completed",
           question=question,
           sql=sql,
           duration=duration,
           success=success)
```

#### 3.2.2 指标收集
```python
from prometheus_client import Counter, Histogram, Gauge

# 指标定义
query_counter = Counter('fund_qa_queries_total', 'Total queries', ['status'])
query_duration = Histogram('fund_qa_query_duration_seconds', 'Query duration')
sql_error_counter = Counter('fund_qa_sql_errors_total', 'SQL errors', ['error_type'])
llm_call_counter = Counter('fund_qa_llm_calls_total', 'LLM calls', ['model'])

def track_query(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            query_counter.labels(status="success").inc()
            return result
        except Exception as e:
            query_counter.labels(status="error").inc()
            raise
        finally:
            query_duration.observe(time.time() - start)

    return wrapper
```

### 3.3 健康检查

```python
class HealthChecker:
    def __init__(self):
        self.checks = []

    def register_check(self, name: str, check_func):
        self.checks.append({"name": name, "func": check_func})

    async def check_all(self) -> Dict[str, Any]:
        results = await asyncio.gather(*[
            asyncio.to_thread(c["func"]) for c in self.checks
        ], return_exceptions=True)

        status = "healthy" if all(r for r in results) else "unhealthy"

        return {
            "status": status,
            "checks": {
                c["name"]: results[i]
                for i, c in enumerate(self.checks)
            }
        }

# 注册检查项
health_checker = HealthChecker()
health_checker.register_check("database", check_database)
health_checker.register_check("llm_api", check_llm_api)
health_checker.register_check("disk_space", check_disk_space)
```

---

## 四、扩展性优化

### 4.1 多数据库支持

```python
class DatabaseAdapter:
    """数据库适配器，支持多种数据库"""

    def __init__(self, db_type: str, connection_params: Dict):
        self.db_type = db_type
        self.params = connection_params

    def create_connection(self):
        if self.db_type == "sqlite":
            return sqlite3.connect(self.params["path"])
        elif self.db_type == "postgresql":
            import psycopg2
            return psycopg2.connect(**self.params)
        elif self.db_type == "mysql":
            import pymysql
            return pymysql.connect(**self.params)

    def execute_query(self, query: str):
        conn = self.create_connection()
        # 根据数据库类型调整 SQL
        if self.db_type == "postgresql":
            query = self._to_postgresql_syntax(query)
        # ...
        return conn.execute(query)
```

### 4.2 多模型支持

```python
class ModelRouter:
    """模型路由，支持多个 LLM"""

    MODELS = {
        "deepseek": "deepseek-ai/DeepSeek-V4-Flash",
        "qwen": "qwen/qwen-plus",
        "gpt": "gpt-4o-mini",
    }

    def __init__(self):
        self.llms = {
            name: create_llm(model)
            for name, model in self.MODELS.items()
        }

    def select_model(self, question: str, context: Dict) -> str:
        """根据问题选择合适的模型"""
        complexity = self.estimate_complexity(question)

        if complexity == "low":
            return "deepseek"  # 简单问题用快速模型
        elif complexity == "high":
            return "gpt"  # 复杂问题用强模型
        else:
            return "qwen"  # 中等复杂度

    def estimate_complexity(self, question: str) -> str:
        """评估问题复杂度"""
        complexity_indicators = {
            "high": ["计算", "分析", "对比", "统计", "趋势"],
            "low": ["查询", "多少", "有没有", "是什么"]
        }

        for indicator in complexity_indicators["high"]:
            if indicator in question:
                return "high"
        return "low"
```

### 4.3 插件系统

```python
class Plugin:
    """插件基类"""

    def preprocess(self, state: AgentState) -> AgentState:
        """预处理问题"""
        return state

    def postprocess(self, result: Dict) -> Dict:
        """后处理结果"""
        return result

class MathPlugin(Plugin):
    """数学计算插件"""

    def postprocess(self, result: Dict) -> Dict:
        # 添加额外计算
        if "涨跌幅" in result.get("question", ""):
            # 计算更多统计指标
            result["extra_metrics"] = self.calculate_metrics(
                result["query_result"]
            )
        return result

class CachePlugin(Plugin):
    """缓存插件"""

    def preprocess(self, state: AgentState) -> AgentState:
        question = state["question"]
        cached = self.cache.get(question)
        if cached:
            state["cached_result"] = cached
        return state
```

---

## 五、安全优化

### 5.1 SQL 注入防护

```python
class SQLSanitizer:
    """SQL 净化器"""

    DANGEROUS_PATTERNS = [
        r";\s*DROP",
        r";\s*DELETE",
        r"UNION\s+SELECT\s+NULL",
        r"--\s*$",
        r"/\*.*\*/",
    ]

    def sanitize(self, sql: str) -> str:
        """检查并净化 SQL"""
        sql_upper = sql.upper()

        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, sql_upper, re.IGNORECASE):
                raise SecurityError(f"危险模式 detected: {pattern}")

        # 检查注释
        if "--" in sql or "/*" in sql:
            raise SecurityError("SQL 注释不被允许")

        return sql

    def validate_table_name(self, name: str) -> bool:
        """验证表名"""
        # 只允许字母、数字、中文、下划线
        return bool(re.match(r'^[\w\u4e00-\u9fa5]+$', name))
```

### 5.2 速率限制

```python
from collections import defaultdict
import time

class RateLimiter:
    """速率限制器"""

    def __init__(self, requests_per_minute: int = 60):
        self.rate = requests_per_minute
        self.requests = defaultdict(list)

    def check(self, client_id: str) -> bool:
        """检查是否允许请求"""
        now = time.time()
        self.requests[client_id] = [
            t for t in self.requests[client_id]
            if now - t < 60
        ]

        if len(self.requests[client_id]) >= self.rate:
            return False

        self.requests[client_id].append(now)
        return True
```

---

## 六、总结

### 优化优先级

| 优先级 | 优化项 | 预期收益 | 实施难度 |
|--------|--------|----------|----------|
| P0 | Schema 缓存 | 延迟 -50% | 低 |
| P0 | 连接池 | 延迟 -30% | 中 |
| P1 | SQL 验证规则预检 | 准确率 +20% | 中 |
| P1 | 错误分类修复 | 准确率 +15% | 中 |
| P2 | 熔断器模式 | 可用性 +99% | 低 |
| P2 | 多模型路由 | 成本 -40% | 高 |
| P3 | 插件系统 | 扩展性 | 高 |

### 性能指标目标

| 指标 | 当前 | 目标 |
|------|------|------|
| 平均响应时间 | ~30s | <10s |
| 准确率 | ~80% | >95% |
| 可用性 | 99% | 99.9% |
| 成本/请求 | ¥0.5 | <¥0.2 |
