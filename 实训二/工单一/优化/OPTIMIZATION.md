# 小家记账本智能体 - 优化文档

## 1. 性能优化

### 1.1 LLM调用优化

#### 问题描述
每次用户请求都需要调用两次LLM：生成SQL + 格式化结果，网络延迟影响体验。

#### 优化方案

**方案A: 流式输出 (推荐)**
```python
# 使用流式输出，用户看到"打字机"效果
for chunk in self.llm.stream(prompt):
    print(chunk.content, end="", flush=True)
```

**方案B: 缓存历史结果**
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def generate_sql_cached(self, user_input: str, date_context: str) -> str:
    """缓存相似查询的SQL生成结果"""
    return self.generate_sql(user_input)
```

**方案C: 简化格式化**
```python
# 对于简单操作，直接格式化而不调用LLM
def _format_simple(self, operation: str, result: dict) -> str:
    if operation == "INSERT":
        return f"已记录：{result['message']}"
    elif operation == "DELETE":
        return f"已删除：{result['message']}"
    # 复杂查询才调用LLM格式化
    return self._llm_format(result)
```

### 1.2 数据库优化

#### 问题描述
随着数据量增长，查询性能下降。

#### 优化方案

**1. 添加复合索引**
```sql
-- 按成员+月份查询优化
CREATE INDEX idx_member_month ON money_notes(member, substr(date, 1, 7));

-- 按类别+类型查询优化
CREATE INDEX idx_category_type ON money_notes(category, type);
```

**2. 分表策略 (数据量>10000条时)**
```python
# 按年分表
def get_table_name(self, year: int = None) -> str:
    year = year or datetime.now().year
    return f"money_notes_{year}"
```

**3. 预聚合统计表**
```sql
-- 创建月度汇总表
CREATE TABLE monthly_stats (
    year_month TEXT PRIMARY KEY,
    member TEXT,
    category TEXT,
    total_income REAL,
    total_expense REAL,
    count INTEGER
);
```

---

## 2. 稳定性优化

### 2.1 LLM调用重试机制

```python
import time
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_sql_with_retry(self, user_input: str) -> str:
    """带重试的SQL生成"""
    try:
        return self.generate_sql(user_input)
    except Exception as e:
        if "rate_limit" in str(e).lower():
            raise  # 限流时重试
        raise  # 其他错误直接抛出
```

### 2.2 熔断器模式

```python
from collections import deque

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
                raise Exception("服务暂时不可用")

        try:
            result = func(*args, **kwargs)
            if self.state == "half_open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
            raise
```

### 2.3 结果缓存

```python
from datetime import datetime, timedelta

class ResultCache:
    def __init__(self, ttl_seconds=300):
        self.cache = {}
        self.ttl = ttl_seconds

    def get(self, key: str):
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["timestamp"] < self.ttl:
                return entry["value"]
            del self.cache[key]
        return None

    def set(self, key: str, value):
        self.cache[key] = {"value": value, "timestamp": time.time()}
```

---

## 3. 安全性优化

### 3.1 敏感信息脱敏

```python
import re

def sanitize_log(sql: str) -> str:
    """日志脱敏，隐藏敏感值"""
    # 脱敏金额
    sql = re.sub(r'\d+\.\d+', '***', sql)
    # 脱敏ID
    sql = re.sub(r'WHERE id\s*=\s*\d+', 'WHERE id=***', sql)
    return sql
```

### 3.2 SQL注入深度防护

```python
def _validate_sql_v2(self, sql: str) -> tuple:
    """增强版SQL校验"""
    sql_upper = sql.strip().upper()

    # 1. 检查注释注入
    if "--" in sql or "/*" in sql:
        return False, "", "禁止使用注释"

    # 2. 检查分号截断
    if ";" in sql[sql.strip().find(";")+1:].strip():
        return False, "", "只允许单条SQL"

    # 3. 检查UNION注入
    if "UNION" in sql_upper:
        return False, "", "禁止使用UNION"

    # 4. 检查条件注入
    dangerous = ["OR 1=1", "OR 1=2", "AND 1=1"]
    for pattern in dangerous:
        if pattern.upper() in sql_upper:
            return False, "", f"检测到可疑模式"

    return self._validate_sql(sql)
```

### 3.3 API Key安全存储

```python
# 方案A: 使用keyring
import keyring

keyring.set_password("account_book", "silicon_flow", api_key)

# 方案B: 使用cryptography库加密
from cryptography.fernet import Fernet

class SecureStorage:
    def __init__(self):
        self.key = Fernet.generate_key()
        self.cipher = Fernet(self.key)

    def save(self, api_key: str):
        encrypted = self.cipher.encrypt(api_key.encode())
        with open(".key", "wb") as f:
            f.write(encrypted)

    def load(self) -> str:
        with open(".key", "rb") as f:
            encrypted = f.read()
        return self.cipher.decrypt(encrypted).decode()
```

---

## 4. 用户体验优化

### 4.1 交互优化

**欢迎信息增强**
```python
def run_cli(self):
    print("=" * 50)
    print("🏠 欢迎使用小家记账本智能体")
    print(f"📅 当前时间: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}")
    print("=" * 50)

    # 显示最近记录
    recent = self.db.execute_query("""
        SELECT * FROM money_notes
        ORDER BY id DESC LIMIT 3
    """)
    if recent:
        print("\n📝 最近记录:")
        for r in recent:
            print(f"   • {r['date']} {r['member']} {r['item']} {r['amount']}元")
```

**输入提示增强**
```python
def run_cli(self):
    examples = [
        "今天女儿买了双登山鞋499元",
        "这个月女儿花了多少钱？",
        "统计本月各类别支出",
        "删除id=5的记录"
    ]

    print("\n💡 示例命令:")
    for i, ex in enumerate(examples, 1):
        print(f"   {i}. {ex}")
```

### 4.2 错误提示优化

```python
def process_message(self, user_input: str) -> str:
    try:
        # ... 业务逻辑
    except Exception as e:
        error_msg = str(e)
        if "API" in error_msg:
            return "⚠️ 网络问题，请检查API配置"
        elif "SQL" in error_msg:
            return f"⚠️ 数据库操作失败，请重试"
        elif "auth" in error_msg.lower():
            return "⚠️ API密钥无效，请检查"
        else:
            return f"⚠️ 发生错误: {error_msg}"
```

### 4.3 进度反馈

```python
def process_message(self, user_input: str) -> str:
    print("🤔 正在理解您的需求...")
    sql = self.generate_sql(user_input)
    print(f"📝 生成SQL: {sql}")

    print("💾 正在执行...")
    result = self.execute_sql(sql)

    print("✨ 整理结果...")
    return self._format_result(user_input, sql, result)
```

---

## 5. 可维护性优化

### 5.1 配置外置

```yaml
# config.yaml
llm:
  provider: siliconflow
  model: Qwen/Qwen2.5-72B-Instruct
  temperature: 0.1
  max_retries: 3

database:
  path: ./data/account_book.db
  backup_enabled: true
  backup_interval: 86400  # 每天备份

security:
  allowed_operations: [SELECT, INSERT, UPDATE, DELETE]
  forbidden_keywords: [DROP, ALTER, CREATE, TRUNCATE, EXEC]
  rate_limit: 10  # 每分钟请求数
```

```python
import yaml

class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            with open("config.yaml", "r", encoding="utf-8") as f:
                cls._instance = super().__new__(cls)
                cls._instance._config = yaml.safe_load(f)
        return cls._instance

    @property
    def llm_config(self):
        return self._config["llm"]

    @property
    def db_config(self):
        return self._config["database"]
```

### 5.2 日志系统

```python
import logging
from logging.handlers import RotatingFileHandler

def setup_logging():
    logger = logging.getLogger("account_book")
    logger.setLevel(logging.INFO)

    # 文件日志
    handler = RotatingFileHandler(
        "logs/account_book.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s"
    ))
    logger.addHandler(handler)

    return logger
```

### 5.3 单元测试

```python
import unittest

class TestSQLGenerator(unittest.TestCase):
    def setUp(self):
        self.agent = SQLAgent(api_key="test-key")

    def test_insert_expense(self):
        sql = self.agent.generate_sql("今天女儿买了双登山鞋499元")
        self.assertIn("INSERT", sql)
        self.assertIn("money_notes", sql)
        self.assertIn("女儿", sql)
        self.assertIn("购物", sql)

    def test_select_query(self):
        sql = self.agent.generate_sql("这个月女儿花了多少钱")
        self.assertIn("SELECT", sql)

    def test_date_keywords(self):
        today = datetime.now().strftime("%Y-%m-%d")
        sql = self.agent.generate_sql("今天爸爸买了书50元")
        self.assertIn(today, sql)

class TestValidator(unittest.TestCase):
    def test_allowed_operations(self):
        validator = SQLValidator()
        for op in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
            self.assertTrue(validator.validate(f"{op} * FROM test"))

    def test_forbidden_operations(self):
        validator = SQLValidator()
        for op in ["DROP", "ALTER", "CREATE"]:
            self.assertFalse(validator.validate(f"{op} TABLE test"))
```

---

## 6. 功能扩展优化

### 6.1 批量导入

```python
def import_from_csv(self, csv_path: str) -> dict:
    """从CSV批量导入"""
    import csv

    success = 0
    failed = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                sql = f"""
                INSERT INTO money_notes (date, member, category, item, amount, type)
                VALUES ('{row['日期']}', '{row['成员']}', '{row['类别']}',
                        '{row['物品']}', {row['金额']}, '{row['类型']}')
                """
                self.db.execute_update(sql)
                success += 1
            except Exception as e:
                failed.append({"row": row, "error": str(e)})

    return {"success": success, "failed": failed}
```

### 6.2 导出功能

```python
def export_to_csv(self, output_path: str, filters: dict = None):
    """导出数据到CSV"""
    import csv

    sql = "SELECT * FROM money_notes WHERE 1=1"
    params = []

    if filters.get("member"):
        sql += " AND member = ?"
        params.append(filters["member"])

    if filters.get("start_date"):
        sql += " AND date >= ?"
        params.append(filters["start_date"])

    records = self.db.execute_query(sql, tuple(params))

    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["日期", "成员", "类别", "物品", "金额", "类型", "备注"])
        writer.writeheader()
        for r in records:
            writer.writerow({
                "日期": r["date"],
                "成员": r["member"],
                "类别": r["category"],
                "物品": r["item"],
                "金额": r["amount"],
                "类型": r["type"],
                "备注": r.get("note", "")
            })
```

### 6.3 月度报告生成

```python
def generate_monthly_report(self, year: int, month: int) -> str:
    """生成月度报告"""
    year_month = f"{year}-{month:02d}"

    # 收支汇总
    summary = self.db.execute_query(f"""
        SELECT type, SUM(amount) as total, COUNT(*) as count
        FROM money_notes
        WHERE date LIKE '{year_month}%'
        GROUP BY type
    """)

    # 类别明细
    by_category = self.db.execute_query(f"""
        SELECT category, SUM(amount) as total
        FROM money_notes
        WHERE date LIKE '{year_month}%' AND type = '支出'
        GROUP BY category
        ORDER BY total DESC
    """)

    # 成员明细
    by_member = self.db.execute_query(f"""
        SELECT member, SUM(amount) as total
        FROM money_notes
        WHERE date LIKE '{year_month}%' AND type = '支出'
        GROUP BY member
        ORDER BY total DESC
    """)

    return self._format_report(summary, by_category, by_member)
```

---

## 7. 监控与运维

### 7.1 性能指标

```python
import time
from functools import wraps

def monitor(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start

        logger.info(f"{func.__name__} 耗时: {duration:.2f}s")

        # 慢查询告警
        if duration > 5:
            logger.warning(f"{func.__name__} 执行缓慢: {duration:.2f}s")

        return result
    return wrapper
```

### 7.2 使用统计

```python
class UsageStats:
    def __init__(self):
        self.stats = {
            "total_requests": 0,
            "total_sql_generated": 0,
            "error_count": 0,
            "operation_types": {}
        }

    def record(self, operation: str, success: bool):
        self.stats["total_requests"] += 1
        if success:
            self.stats["operation_types"][operation] = \
                self.stats["operation_types"].get(operation, 0) + 1
        else:
            self.stats["error_count"] += 1

    def get_report(self) -> str:
        return f"""
使用统计:
- 总请求数: {self.stats['total_requests']}
- 成功操作: {self.stats['total_requests'] - self.stats['error_count']}
- 失败次数: {self.stats['error_count']}
- 操作类型分布: {self.stats['operation_types']}
"""
```
