# 家庭记账本智能体

## 项目概述

本项目是一个基于自然语言处理的智能家庭记账本系统，能够理解用户的日常语言输入，**由大模型动态生成SQL语句**进行数据操作。

### 工单信息

- **工单编号**：人工智能NLP-Agent数字人项目-记账本任务V1.1-20250206
- **项目方向**：人工智能NLP
- **工时预估**：2人日

## 核心特性

### SQL由大模型动态生成

本项目的最大特点是**SQL语句不是写死在代码里**，而是由大模型根据用户输入动态生成：

```
用户输入：今天女儿买了双登山鞋499元
    ↓
大模型生成SQL：INSERT INTO money_notes (date, member, category, item, amount, type)
               VALUES ('2025-07-05', '女儿', '购物', '登山鞋', 499, '支出')
    ↓
执行SQL并返回结果
```

### 技术流程

1. **自然语言理解**：大模型理解用户意图
2. **SQL生成**：大模型生成对应的SQL语句
3. **安全验证**：验证SQL安全性（防止恶意操作）
4. **执行查询**：执行SQL并返回结果
5. **结果格式化**：将结果转换为人类友好的回复

## 功能特性

### 核心功能

1. **自然语言记账**：用户可以用日常对话方式添加记账记录
   - "今天女儿买了双登山鞋499元"
   - "7月5日妈妈收到报销1000元"

2. **智能查询**：支持多种查询方式
   - 查询特定成员支出
   - 按时间范围查询
   - 按类别查询
   - 关键词搜索

3. **统计汇总**
4. **记录管理**：支持删除记账记录

### 家庭成员

- 爸爸、妈妈、女儿

## 技术架构

```
agent_account_book/
├── main.py          # 主程序入口
├── requirements.txt # 依赖包
├── README.md       # 项目文档
└── data/           # 数据目录（自动创建）
    └── account_book.db  # SQLite数据库
```

### 技术栈

- **智能体框架**：LangChain
- **大语言模型**：硅基流动 SiliconFlow（Qwen2.5-72B-Instruct / DeepSeek-V3）
- **SQL生成**：由大模型动态生成
- **数据库**：SQLite

## 安装与运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 获取硅基流动API Key

访问 [https://www.siliconflow.cn/](https://www.siliconflow.cn/) 注册并获取API Key

### 3. 设置API Key

```powershell
# Windows PowerShell
$env:SILICON_FLOW_API_KEY = "your-api-key-here"

# 或使用命令行参数
python main.py --api-key "your-api-key-here"
```

### 4. 运行程序

```bash
cd agent_account_book
python main.py
```

## SQL生成示例

### 添加记录

```
用户: 今天女儿买了双登山鞋499元
生成SQL: INSERT INTO money_notes (date, member, category, item, amount, type)
         VALUES ('2025-07-05', '女儿', '购物', '登山鞋', 499, '支出')
```

### 查询统计

```
用户: 这个月女儿花了多少钱？
生成SQL: SELECT * FROM money_notes
         WHERE member = '女儿' AND type = '支出'
         AND date >= '2025-07-01' AND date <= '2025-07-31'
```

### 删除记录

```
用户: 删除女儿报旅游团的费用
生成SQL: DELETE FROM money_notes
         WHERE member = '女儿' AND item LIKE '%旅游%'
```

## 安全机制

1. **SQL白名单**：只允许 SELECT、INSERT、UPDATE、DELETE 操作
2. **关键词过滤**：禁止 DROP、ALTER、CREATE、TRUNCATE 等危险操作
3. **参数化执行**：使用参数化查询防止SQL注入

## 数据库表结构

```sql
CREATE TABLE money_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,           -- 日期，格式：YYYY-MM-DD
    member TEXT NOT NULL,         -- 成员：爸爸、妈妈、女儿
    category TEXT NOT NULL,       -- 类别
    item TEXT NOT NULL,           -- 物品/事项名称
    amount REAL NOT NULL,         -- 金额（支出为正数）
    type TEXT NOT NULL,           -- 类型：收入、支出
    note TEXT,                    -- 备注
    created_at TEXT               -- 创建时间
);
```

## 测试用例

| 序号 | 测试语句 | 预期结果 |
|------|----------|----------|
| 1 | 今天女儿买了双登山鞋499元 | 成功记录 |
| 2 | 7月5日妈妈收到报销1000元 | 成功记录 |
| 3 | 看下这个月家里花钱明细 | 显示本月所有收支 |
| 4 | 这个月女儿花了多少钱？ | 显示女儿支出统计 |
| 5 | 删除女儿报旅游团的费用 | 找到并确认删除 |

## 验收标准

1. ✅ **开场白**：显示「您好，欢迎使用咱们小家专属记账本！...」
2. ✅ **SQL动态生成**：100%由大模型生成SQL
3. ✅ **数据库调用**：正确操作money_notes表
4. ✅ **存储准确性**：字段正确记录
5. ✅ **完整性引导**：信息不完整时询问补充
6. ✅ **流程完善性**：删除前确认

## 许可证

本项目仅用于教育目的。

## 联系方式

- 创建人：王洪荣
- 创建时间：2025年1月14日
- 北京八维信息集团
