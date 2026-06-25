"""测试工具函数"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import re

CN_NUM = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

def cn_to_num(cn: str) -> int:
    if cn in CN_NUM:
        return CN_NUM[cn]
    result = 0
    for c in cn:
        if c in CN_NUM:
            result = result * 10 + CN_NUM[c]
    return result if result > 0 else 0

def extract_time(text: str):
    text = text.replace('　', ' ')

    match = re.search(r'(\d{1,2}):(\d{2})', text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        return _adjust(text, hour, minute)

    time_period = ""
    if '晚上' in text: time_period = "晚上"
    elif '下午' in text: time_period = "下午"
    elif '中午' in text: time_period = "中午"
    elif '上午' in text or '早上' in text: time_period = "上午"

    pattern = r'[上下中]?午?\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*点(\d{0,2}|[一二三四五六七八九]{0,2})\s*分?'
    match = re.search(pattern, text)
    if match:
        hour_str, minute_str = match.group(1), match.group(2) if match.group(2) else "0"
        try:
            hour = int(hour_str) if hour_str.isdigit() else cn_to_num(hour_str)
            minute = int(minute_str) if minute_str.isdigit() else cn_to_num(minute_str)
        except:
            return None
        return _adjust(text, hour, minute, time_period)

    pattern2 = r'(?<![点\d])\s*(\d{1,2}|[一二三四五六七八九十]{1,2})\s*点(?!\d)'
    match = re.search(pattern2, text)
    if match:
        hour_str = match.group(1)
        try:
            hour = int(hour_str) if hour_str.isdigit() else cn_to_num(hour_str)
        except:
            return None
        return _adjust(text, hour, 0, time_period)
    return None

def _adjust(text, hour, minute, period=""):
    if not period:
        if '晚上' in text or '下午' in text: period = "下午"
        elif '中午' in text: period = "中午"
        elif '上午' in text or '早上' in text: period = "上午"
    if period in ['晚上', '下午']:
        if hour < 12: hour += 12
    elif period == '中午':
        if hour < 12: hour = 12
    elif period in ['上午', '早上']:
        if hour == 12: hour = 0
    return f"{hour:02d}:{minute:02d}"

def extract_content(text: str):
    content = text
    for kw in ["添加日程", "新增", "加入", "创建", "安排", "提醒", "加"]:
        content = content.replace(kw, " ")
    content = re.sub(r'[上下中]?午?\s*\d{1,2}\s*点\d{0,2}\s*分?', '', content)
    content = re.sub(r'\d{1,2}:\d{2}', '', content)
    content = ' '.join(content.split())
    return content.strip()

# 测试用例
test_cases = [
    "下午 5 点开会",
    "上午八点提醒我起床",
    "上午八点三十起床",
    "上午八点三十五分起床",
    "中午12点提醒我吃饭",
    "晚上8点看电影",
    "8点起床",
    "明天上午9点开会",
    "后天晚上7点看球赛",
    "下午3点30分开会",
    "下午3点开会",
    "添加日程：下午5点开会",
]

print("=" * 60)
for text in test_cases:
    time = extract_time(text)
    content = extract_content(text)
    print(f"原文: {text}")
    print(f"  -> 时间:{time} | 内容:{content}")
