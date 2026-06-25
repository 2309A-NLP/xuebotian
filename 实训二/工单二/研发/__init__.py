# Agent 数字人项目 - 日程提醒智能体
# 工单编号：人工智能 NLP-Agent 数字人项目-日程提醒智能体任务
# sk-ksjzimvagxgylxfkeyxksatdmhpkyrzfzsiwkidiryuerbuy

aioscheduler/
├── config/
│   ├── __init__.py
│   └── settings.py          # 配置文件
├── database/
│   ├── __init__.py
│   ├── connection.py        # 数据库连接
│   └── models.py             # 数据库模型
├── nlp/
│   ├── __init__.py
│   ├── parser.py             # 自然语言解析器
│   └── templates.py          # 对话模板
├── services/
│   ├── __init__.py
│   ├── schedule_service.py   # 日程服务
│   ├── reminder_service.py    # 提醒服务
│   └── response_service.py    # 响应生成服务
├── core/
│   ├── __init__.py
│   ├── agent.py              # 智能体核心
│   └── scheduler.py           # 定时调度器
├── tests/
│   ├── __init__.py
│   └── test_agent.py          # 测试代码
├── requirements.txt
├── main.py                    # 入口文件
├── init_db.py                 # 数据库初始化
└── README.md
"""
