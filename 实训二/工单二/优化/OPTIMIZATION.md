# AIOScheduler 优化文档

> 本文档记录系统开发过程中遇到的问题、根因分析、修复方案以及未来可进一步优化的方向。

---

## 一、已修复问题汇总

### 问题 1：定时器 key 是 `None_xxx`，提醒完全不触发

**发现时间**：2026-06-25
**影响版本**：所有使用 `main_agent.py` 提醒服务的版本
**严重程度**：⚠️ 严重 — 功能完全失效

#### 现象

用户添加日程后，到达设定时间没有任何提醒输出。

#### 根因分析

`add_schedule` 工具的执行路径：

```python
# tools.py
schedule = Schedule(content=..., schedule_date=..., schedule_time=...)
schedule_repo.add(schedule)           # ← 返回自增 ID（如 2），但丢弃了
                                       # schedule.id 仍是 None

if _reminder_service:
    _reminder_service.schedule_now(schedule)  # ← schedule.id 是 None！
```

`schedule_repo.add()` 虽然返回了数据库自增 ID，但 `schedule` 对象的 `id` 属性从未被赋值。传给 `schedule_now()` 时 `schedule.id` 仍是 `None`，定时器 key 变成 `"None_2026-06-25_17:00"`，每次添加都覆盖同一个"空 key"，实际定时器从未正确注册。

#### 修复方案

```python
# tools.py - add_schedule()
schedule = Schedule(...)
schedule_id = schedule_repo.add(schedule)  # 捕获返回值
schedule.id = schedule_id                  # 回填 id
```

同样修复了 `set_recurring_schedule` 中的相同问题，并补充了 `schedule_now()` 调用。

#### 修复文件

- `aioscheduler/agent/tools.py`：`add_schedule()` 第 318-324 行；`set_recurring_schedule()` 第 407-414 行

---

### 问题 2：循环日程根本不触发提醒

**发现时间**：2026-06-25
**影响版本**：所有版本
**严重程度**：⚠️ 严重 — 功能完全失效

#### 根因分析

`set_recurring_schedule()` 添加日程后**没有调用** `schedule_now()` 注册定时器，导致循环日程永远无法在精确时间触发。

#### 修复方案

在 `schedule_repo.add()` 后添加：

```python
if _reminder_service:
    _reminder_service.schedule_now(schedule)
```

---

### 问题 3：删除后返回的序号是数据库 ID

**发现时间**：2026-06-25
**影响版本**：所有版本
**严重程度**：🟡 中等 — 信息误导用户

#### 现象

```
用户：删除日程 1
助手：已经删除日程 2，删除的日程内容是：08:00 提醒您起床
```

用户说的是序号 1，但返回的是数据库 ID 2。

#### 根因分析

```python
# tools.py - delete_schedule()
if position is not None:
    schedules = schedule_repo.get_by_date(date.today())
    target_schedule = schedules[position - 1]
    schedule_id = target_schedule.id    # ← schedule_id 被重新赋值
    ...

return f"已经删除日程 {schedule_id}，..."  # ← 用的是 id，不是 position
```

`schedule_id` 变量被复用（先接收 `position`，后来又被赋值为数据库 ID），最后返回时用了数据库 ID 而不是用户原始输入的 `position`。

#### 修复方案

```python
if position is not None:
    deleted_position = position
else:
    deleted_position = schedule_id

schedule_repo.delete(schedule_id)
return f"已经删除日程 {deleted_position}，..."
```

同样修复了 `complete_schedule()` 中的相同问题。

---

### 问题 4：查询日程时 LLM 错误调用删除工具

**发现时间**：2026-06-25
**影响版本**：所有版本
**严重程度**：🟡 中等 — 功能混乱

#### 现象

用户连续发送"我今天的日程有哪些？"时，第二次调用了 `delete_schedule` 而非 `query_schedules`。

#### 根因分析

System Prompt 中"查询日程"和"删除日程"两条规则的描述文本高度相似，LLM 在受到前一条"删除日程1"操作的上下文干扰后，优先匹配了相似度更高的删除规则。

#### 修复方案

1. 将查询规则**移到最前面**，作为第一优先匹配项
2. 加重查询规则的描述，明确限制"只有明确说了日程才查询"
3. 在禁止行为中补充：禁止因上一条消息的影响而调用第二次

```markdown
【工具调用规则】
- **查询日程**（如"日程有哪些/有什么安排/查看日程/今天的日程"）
  → 必须调用 query_schedules(query_date="今天")
  **注意**：只有明确说了"日程"才查询，不要和其他操作混淆
- 用户说"添加/新建/安排日程" → ...
- 用户说"删除/取消/删掉/去掉 日程 第X个" → ...
```

---

## 二、数据库层优化记录

### 优化 A：循环日程的"滚动"机制

**问题**：循环日程（如"每天8点喝水"）触发后，需要自动生成下一次触发时间，不能靠人工重新创建。

**方案**：`_generate_next_recurrence()` 在标记完成时自动计算下一周期：

| 循环类型 | 逻辑 |
|---------|------|
| daily | `date + 1` 天 |
| weekly | `date + 7` 天，`recurrence_rule` 左移一位 |
| monthly | 月份 +1（跨年处理） |
| workday | `date + 1`，跳到下周一 |

### 优化 B：定时器 key 去重设计

**问题**：每次 `_check_and_schedule()` 被调用，都要检查是否已经为某日程注册过定时器，避免重复。

**方案**：用 `"{id}_{schedule_date}_{schedule_time}"` 作为 key 注册到 `self._timers` 字典中，每次注册前先检查 key 是否存在，已存在则跳过。

### 优化 C：查询时用元组去重

**问题**：循环日程存一条记录，但可能在多天被查到，导致同一条日程重复显示。

**方案**：`get_by_date()` 用 `(content, schedule_time, recurrence)` 三元组做去重：

```python
seen = set()
for s in schedules:
    key = (s.content, s.schedule_time, s.recurrence)
    if key in seen:
        continue
    seen.add(key)
    result.append(s)
```

---

## 三、未来优化方向

以下问题暂未修复，供参考或后续迭代：

### 3.1 并发安全：SQLite WAL 模式

**现状**：SQLite 连接使用默认的 DELETE 日志模式，在高并发写入时有锁竞争风险。

**建议**：
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

### 3.2 提醒服务的跨进程持久化

**现状**：`threading.Timer` 是进程内对象，程序重启后所有定时器丢失，重启前未触发的日程不会在重启后继续提醒。

**建议**：
- 方案 A：将待触发日程写入一张 `pending_reminders` 表，启动时扫描并重新注册定时器
- 方案 B：用 `APScheduler` 替代手写 Timer，支持持久化
- 方案 C：用 Redis Sorted Set 存储触发时间，实现分布式定时

### 3.3 LLM 解析兜底的健壮性

**现状**：`add_schedule` 的 LLM 二次解析兜底只在 `content` 字段看起来像原始输入时才触发，可能遗漏一些边界情况。

**建议**：统一使用 `add_schedule_from_text(user_input)` 工具，让 LLM 在单次调用中完成"理解意图 + 提取参数"，而不是让 LLM 先调 `add_schedule` 再由工具内部二次解析。

### 3.4 System Prompt 的工程化

**现状**：System Prompt 是硬编码在 `agent.py` 中的长字符串，难以维护和测试。

**建议**：
- 将 System Prompt 提取到单独文件（如 `prompts/scheduler_prompt.md`）
- 按模块拆分为 `system_base.md`、`tool_rules.md`、`forbidden_rules.md`
- 用模板引擎（如 Jinja2）注入日期等动态变量

### 3.5 单元测试覆盖率

**现状**：仅有基础测试用例（`tests/test_agent.py`），无 mock LLM 的集成测试。

**建议**：
- 使用 `unittest.mock.patch` mock LLM API 响应
- 补充边界测试：时间格式错误、日期越界、空 content、空时间等
- 用 `pytest` + `pytest-cov` 生成覆盖率报告

### 3.6 多端通知支持

**现状**：提醒仅输出到终端/日志。

**建议**：在 `ReminderService._trigger_reminder()` 中增加通知插件：

| 平台 | 实现方式 |
|------|---------|
| 飞书 | WebHook POST |
| 钉钉 | 自定义机器人 WebHook |
| 微信 | 企业微信机器人 / Server酱 |
| 邮件 | SMTP |
| 短信 | 阿里云/腾讯云 SMS API |

### 3.7 Web 模式的身份认证

**现状**：`main_agent.py` 的 Web 模式没有任何身份验证，任何人都可以访问。

**建议**：
- 基础方案：Flask HTTP Basic Auth 或 Token 认证
- 进阶方案：JWT + OAuth2

### 3.8 日程冲突检测

**现状**：系统允许同一时间创建多个日程，无冲突警告。

**建议**：在 `add_schedule` 中检查同一日期时间是否已有未完成日程，如有则返回警告提示用户。
