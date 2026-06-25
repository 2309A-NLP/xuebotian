"""
Tools 模块 - 日程管理工具（无 LangChain 依赖）
工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
"""

from typing import Optional, List, Callable, Any
from datetime import datetime, date, timedelta
import random
import re
import inspect


class BaseTool:
    """工具基类"""
    name: str = ""
    description: str = ""
    args: dict = {}

    def invoke(self, **kwargs) -> Any:
        raise NotImplementedError

    def execute(self, **kwargs) -> Any:
        return self.invoke(**kwargs)


class Tool(BaseTool):
    """工具类，兼容 agent.py"""

    def to_openai_format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args,
            },
        }


class ToolResult:
    """工具执行结果"""
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message

    def to_message(self) -> str:
        return self.message


def tool(func: Callable) -> Tool:
    """
    装饰器：将函数转为 Tool 对象。
    自动从函数签名生成 name、description、args。
    """
    tool_name = func.__name__
    tool_desc = func.__doc__ or ""

    sig = inspect.signature(func)
    properties = {}
    required = []
    for pname, param in sig.parameters.items():
        if param.annotation != inspect.Parameter.empty:
            type_str = "string"
            if param.annotation in (int, "int"):
                type_str = "integer"
            elif param.annotation in (bool, "bool"):
                type_str = "boolean"
            elif param.annotation in (float, "float"):
                type_str = "number"
            properties[pname] = {"type": type_str}
        else:
            properties[pname] = {"type": "string"}
        if param.default == inspect.Parameter.empty:
            required.append(pname)

    args_schema = {
        "type": "object",
        "properties": properties,
        "required": required,
    }

    # 保存原函数引用
    _func = func

    class ToolInstance(Tool):
        name = tool_name
        description = tool_desc.strip()
        args = args_schema

        def invoke(self, **kwargs):
            result = _func(**kwargs)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(success=True, message=str(result))

        def execute(self, **kwargs):
            return self.invoke(**kwargs)

    return ToolInstance()


import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import Schedule, schedule_repo

# 提醒服务（由 main_agent.py 注入）
_reminder_service = None


def set_reminder_service(service):
    global _reminder_service
    _reminder_service = service


# ============ 辅助函数 ============

CN_NUM = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def cn_to_num(cn: str) -> int:
    if cn in CN_NUM:
        return CN_NUM[cn]
    if cn == '十':
        return 10
    result = 0
    for c in cn:
        if c in CN_NUM:
            result = result * 10 + CN_NUM[c]
    return result if result > 0 else 0


def extract_time(text: str) -> Optional[str]:
    if not text:
        return None

    work = text.replace('\u3000', ' ').replace('：', ':')

    period = ""
    if '下午' in work or '晚上' in work:
        period = "pm"
    elif '上午' in work or '早上' in work or '早晨' in work or '清晨' in work:
        period = "am"
    elif '中午' in work or '正午' in work:
        period = "noon"

    m = re.search(r'(\d{1,2})\s*[:：]\s*(\d{1,2})', work)
    hour, minute = 0, 0
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
    else:
        idx = work.find('点')
        if idx >= 0:
            i = idx - 1
            while i >= 0 and work[i] == ' ':
                i -= 1
            num_str = ""
            while i >= 0 and work[i].isdigit():
                num_str = work[i] + num_str
                i -= 1
            if num_str:
                hour = int(num_str)

            if '分' in work[idx:]:
                fen_idx = work.find('分', idx)
                seg = work[idx + 1:fen_idx]
                seg_digits = re.findall(r'\d+', seg)
                if seg_digits:
                    minute = int(seg_digits[0])

    if hour == 0 and minute == 0:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None

    if period == "pm" and hour < 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0
    elif period == "noon" and hour < 12:
        hour = 12

    return f"{hour:02d}:{minute:02d}"


def extract_date(text: str) -> str:
    today = date.today()
    if '明天' in text or '明日' in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif '后天' in text or '后日' in text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    elif '大后天' in text:
        return (today + timedelta(days=3)).strftime("%Y-%m-%d")
    return today.strftime("%Y-%m-%d")


def _llm_parse_schedule(user_input: str, llm_client) -> Optional[dict]:
    """
    使用 LLM 把自然语言输入解析为结构化日程字段。
    返回 {"time": "HH:MM", "date": "YYYY-MM-DD", "content": "..."}
    失败返回 None。
    """
    import json
    import re as _re
    from datetime import date as _date

    today_str = _date.today().strftime("%Y-%m-%d")

    prompt = f"""你是日程解析助手。请从用户的输入中精确提取出日程的「时间」「日期」「事项内容」。
当前日期: {today_str}

严格按以下 JSON 格式输出（不要输出其它内容，不要加 markdown 代码块）：
{{"time": "HH:MM", "date": "YYYY-MM-DD", "content": "事项内容"}}

规则：
1. time 必须是 24 小时制的 HH:MM（如 17:00、12:30、08:00）。
   - "下午 5 点" → 17:00；"上午 8 点" → 08:00；"中午 12 点" → 12:00；"晚上 7 点" → 19:00
   - "8 点半" → 08:30；"下午3点15分" → 15:15
2. date 必须是 YYYY-MM-DD。
   - "今天/今晚" → {today_str}
   - "明天/明日" → 明天的日期
   - "后天/后日" → 后天的日期
3. content 是去除时间/日期/指令词后剩余的事项内容（如"下午 5 点开会"→"开会"）。
   - 不要包含"添加日程"、"提醒"、"今天"、"明天"、"上午"等无关词
4. 如果时间或事项缺失，content/time 留空字符串。

用户输入：{user_input}"""

    try:
        result = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
        )
        text = result["choices"][0]["message"]["content"].strip()

        # 去掉 markdown 代码块包裹
        text = _re.sub(r'^```(?:json)?\s*', '', text)
        text = _re.sub(r'\s*```$', '', text)
        text = text.strip()

        data = json.loads(text)
        return {
            "time": str(data.get("time", "")).strip(),
            "date": str(data.get("date", "")).strip() or today_str,
            "content": str(data.get("content", "")).strip(),
        }
    except Exception as e:
        print(f"[LLM 解析失败] {e}")
        return None


# LLM 客户端（由 set_llm_client 注入）
_llm_client = None


def set_llm_client(client):
    """注入 LLM 客户端，供工具内部调用做语义解析"""
    global _llm_client
    _llm_client = client


# ============ 工具实现 ============

@tool
def add_schedule(time: str, date: str, content: str) -> str:
    """
    当用户想添加/安排/提醒一个日程时调用。
    注意：本工具要求调用者（即 LLM）已经完成自然语言到三字段的提取：
      - time: 24小时制 HH:MM（如 17:00、08:30）
      - date: YYYY-MM-DD（如 2026-06-25）
      - content: 事项内容（如 "开会"、"起床"、"吃饭"，不含时间/日期/指令词）
    如果用户输入没传这三字段（例如其它 Agent 把整个 user_input 透传进来），
    工具内部会用 LLM 再解析一次。
    """
    try:
        from datetime import date as _date, datetime as _dt

        schedule_time = (time or "").strip()
        schedule_date = (date or "").strip()
        schedule_content = (content or "").strip()

        # 兜底：如果三个字段都为空，说明调用者直接把原始 user_input 传进来了
        # 这种情况下用 LLM 解析
        if not schedule_time and not schedule_content and _llm_client:
            # 没办法从一个字段里区分出来（time/date/content 都为空）
            # 这种调用方式应该用 add_schedule_from_text
            return "缺少必要参数：time 和 content"

        # 兜底：如果只有 content 看起来像原始输入（含有时间词），用 LLM 解析
        if schedule_content and not schedule_time and _llm_client:
            looks_like_raw = any(kw in schedule_content for kw in (
                "点", "上午", "下午", "中午", "晚上", "早上", "凌晨", "今天", "明天", "后天"
            ))
            if looks_like_raw:
                parsed = _llm_parse_schedule(schedule_content, _llm_client)
                if parsed:
                    schedule_time = parsed["time"] or schedule_time
                    schedule_date = parsed["date"] or schedule_date
                    schedule_content = parsed["content"] or schedule_content

        if not schedule_content:
            return "请问需要提醒您做什么呢？"
        if not schedule_time:
            return "请问您想安排在什么时间呢？比如「下午5点」"

        # 日期兜底
        if not schedule_date:
            schedule_date = _date.today().strftime("%Y-%m-%d")

        # 时间格式校验
        try:
            _dt.strptime(schedule_time, "%H:%M")
        except ValueError:
            return f"时间格式不正确：{schedule_time}，请用 HH:MM 格式如 17:00"

        schedule = Schedule(
            content=schedule_content,
            schedule_date=schedule_date,
            schedule_time=schedule_time,
            recurrence="none"
        )
        schedule_id = schedule_repo.add(schedule)
        schedule.id = schedule_id

        if _reminder_service:
            _reminder_service.schedule_now(schedule)

        return f"{schedule_time} 提醒您{schedule_content}"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"添加日程失败: {str(e)}"


@tool
def add_schedule_from_text(user_input: str) -> str:
    """
    当用户输入是自然语言（如「下午5点开会」、「明天上午10点提醒我买咖啡」），
    且 LLM 解析不出三字段时，调用本工具。内部用 LLM 二次解析为 time/date/content，
    再调用 add_schedule 入库。
    """
    try:
        if not _llm_client:
            return "系统未配置 LLM，无法解析自然语言输入"

        parsed = _llm_parse_schedule(user_input, _llm_client)
        if not parsed:
            return "抱歉，没能理解您说的时间和事项，请换种说法试试"

        schedule_time = parsed["time"]
        schedule_date = parsed["date"]
        schedule_content = parsed["content"]

        if not schedule_content:
            return "请问需要提醒您做什么呢？"
        if not schedule_time:
            return "请问您想安排在什么时间呢？比如「下午5点」"

        return add_schedule.invoke(
            time=schedule_time,
            date=schedule_date,
            content=schedule_content,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"添加日程失败: {str(e)}"


@tool
def set_recurring_schedule(time_str: str, recurrence_rule: str, content: str) -> str:
    """
    设置循环日程。
    参数：
    - time_str: 时间，格式 HH:MM
    - recurrence_rule: 循环规则，7位二进制字符串如 1000100（周一至周日，1表示循环）
    - content: 日程内容
    """
    try:
        time_match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if not time_match:
            return '时间格式错误！请使用 24 小时制，如 15:15'
        hour, minute = int(time_match.group(1)), int(time_match.group(2))
        if hour > 23 or minute > 59:
            return '时间超出范围！小时0-23，分钟0-59'

        if not re.match(r'^[01]{7}$', recurrence_rule):
            return '循环规则格式错误！需要7位二进制，如 1000100'

        days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        active_days = [days[i] for i in range(7) if recurrence_rule[i] == '1']

        if not active_days:
            return '循环规则错误！至少要选择一天'

        clean_content = (content or "").strip()
        # 兜底：去掉"提醒我/记得"等前缀
        for prefix in ("提醒我", "记得", "记得提醒我", "提醒"):
            if clean_content.startswith(prefix):
                clean_content = clean_content[len(prefix):].strip()
                break
        if not clean_content:
            return '无法提取日程内容，请换一种说法'

        schedule = Schedule(
            content=clean_content,
            schedule_date=date.today().strftime("%Y-%m-%d"),
            schedule_time=time_str,
            recurrence="weekly",
            recurrence_rule=recurrence_rule
        )
        schedule_id = schedule_repo.add(schedule)
        schedule.id = schedule_id

        if _reminder_service:
            _reminder_service.schedule_now(schedule)

        days_str = '、'.join(active_days)
        return f'好的，已经设置循环日程：{time_str} {clean_content}，循环日期：{days_str}'

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f'设置循环日程失败：{str(e)}'


@tool
def query_schedules(query_date: str = "") -> str:
    """查询日程"""
    try:
        if not query_date or "今天" in query_date or "今日" in query_date:
            target_date = date.today()
        elif "明天" in query_date or "明日" in query_date:
            target_date = date.today() + timedelta(days=1)
        elif "后天" in query_date or "后日" in query_date:
            target_date = date.today() + timedelta(days=2)
        else:
            try:
                target_date = datetime.strptime(query_date, "%Y-%m-%d").date()
            except:
                target_date = date.today()

        schedules = schedule_repo.get_by_date(target_date)

        if not schedules:
            return f"您今天的日程已经完成啦，好好休息一下吧~" if target_date == date.today() else f"{target_date.strftime('%Y-%m-%d')}暂时没有安排任何日程~"

        if target_date == date.today():
            header = "您今天的日程包括："
        elif target_date == date.today() + timedelta(days=1):
            header = "您明天的日程包括："
        else:
            header = f"{target_date.strftime('%Y-%m-%d')}的日程包括："

        items = []
        for i, s in enumerate(schedules, 1):
            item = f"{i}、{s.schedule_time}提醒您{s.content}"
            if s.recurrence == "weekly" and s.recurrence_rule:
                days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
                active = [days[j] for j in range(7) if s.recurrence_rule[j] == '1']
                if active:
                    item += f"（{'/'.join(active)}）"
            items.append(item)

        return header + "，".join(items)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"查询日程失败: {str(e)}"


@tool
def delete_schedule(schedule_id: int = None, position: int = None) -> str:
    """删除日程。
    参数：
    - schedule_id: 日程ID（可选）
    - position: 日程序号（可选，如"第1个"）
    两个都不指定时，删除今天时间最早的日程。
    """
    try:
        deleted_content = ""
        deleted_time = ""

        if position is not None:
            schedules = schedule_repo.get_by_date(date.today())
            if 1 <= position <= len(schedules):
                target_schedule = schedules[position - 1]
                schedule_id = target_schedule.id
                deleted_content = target_schedule.content
                deleted_time = target_schedule.schedule_time
            else:
                return f"找不到第 {position} 个日程"
        elif schedule_id is not None:
            schedule = schedule_repo.get_by_id(schedule_id)
            if schedule:
                deleted_content = schedule.content
                deleted_time = schedule.schedule_time
            else:
                return f"找不到日程 {schedule_id}"
        else:
            schedules = schedule_repo.get_by_date(date.today())
            if not schedules:
                return "您今天还没有日程可以删除哦~"
            target_schedule = schedules[0]
            schedule_id = target_schedule.id
            deleted_content = target_schedule.content
            deleted_time = target_schedule.schedule_time

        if position is not None:
            deleted_position = position
        else:
            deleted_position = schedule_id  # 按id删除时用id
        schedule_repo.delete(schedule_id)

        if _reminder_service:
            stub = type(
                "S",
                (),
                {
                    "id": schedule_id,
                    "schedule_date": date.today().strftime("%Y-%m-%d"),
                    "schedule_time": deleted_time,
                },
            )()
            _reminder_service.cancel(stub)

        return f"已经删除日程 {deleted_position}，删除的日程内容是：{deleted_time} 提醒您{deleted_content}"

    except Exception as e:
        return f"删除日程失败: {str(e)}"


@tool
def complete_schedule(schedule_id: int = None, position: int = None) -> str:
    """标记日程完成。
    参数：
    - schedule_id: 日程ID（可选）
    - position: 日程序号（可选，如"第1个"）
    两个都不指定时，标记今天时间最早的日程为完成。
    """
    try:
        if position is not None:
            deleted_position = position
        else:
            deleted_position = schedule_id

        if position is not None:
            schedules = schedule_repo.get_by_date(date.today())
            if 1 <= position <= len(schedules):
                target_schedule = schedules[position - 1]
                schedule_id = target_schedule.id
                completed_content = target_schedule.content
            else:
                return f"找不到第 {position} 个日程"
        elif schedule_id is not None:
            schedule = schedule_repo.get_by_id(schedule_id)
            if schedule:
                completed_content = schedule.content
            else:
                return f"找不到日程 {schedule_id}"
        else:
            schedules = schedule_repo.get_by_date(date.today())
            if not schedules:
                return "您今天还没有日程可以标记完成哦~"
            target_schedule = schedules[0]
            schedule_id = target_schedule.id
            completed_content = target_schedule.content

        schedule_repo.mark_completed(schedule_id)
        return f"太棒了！【{completed_content}】（第{deleted_position}条）已完成~"

    except Exception as e:
        return f"标记完成失败: {str(e)}"
