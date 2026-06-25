# 小家记账本智能体 - 部署文档

## 1. 环境准备

### 1.1 系统要求

| 项目 | 要求 | 说明 |
|------|------|------|
| 操作系统 | Windows 10+/macOS 10.14+/Ubuntu 18.04+ | 支持Python 3.10+即可 |
| Python | 3.10 或 3.11 | 推荐3.10稳定性最佳 |
| 内存 | 4GB+ | LLM调用需一定内存 |
| 硬盘 | 100MB+ | 程序+数据库空间 |
| 网络 | 可访问api.siliconflow.cn | 调用LLM必需 |

### 1.2 安装Python

**Windows**
1. 访问 https://www.python.org/downloads/
2. 下载 Python 3.10.x 安装包
3. 安装时勾选 "Add Python to PATH"
4. 验证：`python --version`

**macOS**
```bash
# 使用Homebrew安装
brew install python@3.10

# 或使用pyenv
pyenv install 3.10.12
```

**Ubuntu/Debian**
```bash
sudo apt update
sudo apt install python3.10 python3.10-venv python3-pip
```

---

## 2. 依赖安装

### 2.1 使用Anaconda（推荐）

```bash
# 1. 创建虚拟环境
conda create -n account_book python=3.10 -y

# 2. 激活环境
conda activate account_book

# 3. 进入项目目录
cd g:\eight_dim\课堂笔记\专高六\agent工单\gd1\agent_account_book

# 4. 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2.2 使用venv

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2.3 requirements.txt

```
langchain>=0.1.0
langchain-core>=0.1.0
langchain-openai>=0.0.5
```

---

## 3. 配置API Key

### 3.1 获取API Key

1. 访问 https://www.siliconflow.cn/
2. 注册/登录账号
3. 进入控制台 -> API Keys
4. 创建新API Key并复制

### 3.2 使用方式

**方式一：运行时输入（推荐）**
```bash
python main.py
# 程序会提示输入API Key
```

**方式二：命令行参数**
```bash
python main.py --api-key sk-xxxxxxxxxxxxx
```

**方式三：环境变量（可选）**
```bash
# Windows PowerShell
$env:SILICON_FLOW_API_KEY="sk-xxxxxxxxxxxxx"

# macOS/Linux
export SILICON_FLOW_API_KEY="sk-xxxxxxxxxxxxx"

# 然后运行
python main.py
```

---

## 4. 运行程序

### 4.1 首次运行

```bash
cd g:\eight_dim\课堂笔记\专高六\agent工单\gd1\agent_account_book
python main.py
```

首次运行会自动创建：
- `data/` 目录
- `data/account_book.db` 数据库文件

### 4.2 交互示例

```
==================================================
🔑 请输入硅基流动API Key
   （访问 https://www.siliconflow.cn/ 获取）
==================================================
API Key: sk-xxxxxxxxxxxxx

==================================================
🏠 欢迎使用小家记账本智能体
==================================================

【功能说明】
  • 记账：今天女儿买了双登山鞋499元
  • 查询：这个月女儿花了多少钱？
  • 统计：看我这个月买书花了多少
  • 删除：删除女儿报旅游团的费用
  • 退出：输入 'quit' 或 'exit' 退出

==================================================

👤 你: 今天女儿买了双登山鞋499元
🤖 智能体处理中...
   1. 生成SQL...

💰 记账本: 已记录女儿购买登山鞋支出499元

👤 你: 查询这个月花了多少钱
🤖 智能体处理中...
   1. 生成SQL...

💰 记账本: 本月共支出 499 元

👤 你: 退出

👋 感谢使用小家记账本，再见！
```

---

## 5. 目录结构

```
agent_account_book/
├── main.py                 # 主程序入口
├── requirements.txt        # Python依赖
├── DESIGN.md              # 设计方案
├── OPTIMIZATION.md        # 优化文档
├── DEPLOY.md              # 部署文档（本文件）
├── README.md              # 项目说明
└── data/                  # 数据目录（自动创建）
    └── account_book.db    # SQLite数据库
```

---

## 6. 数据库管理

### 6.1 查看数据库位置

数据库文件默认在 `data/account_book.db`，也可手动指定：

```bash
python main.py --db-path /path/to/other.db
```

### 6.2 备份数据库

```bash
# 复制数据库文件
copy data\account_book.db data\account_book_backup.db
```

### 6.3 重置数据库

```bash
# 删除数据库文件（会丢失所有数据）
del data\account_book.db

# 重新运行程序会自动创建
python main.py
```

### 6.4 查看数据

```bash
# 使用sqlite3命令行
sqlite3 data\account_book.db

# 在sqlite3交互界面查看
sqlite> SELECT * FROM money_notes;
sqlite> .quit
```

---

## 7. 常见问题

### 7.1 依赖安装失败

**问题**: `ERROR: Could not find a version that satisfies the requirement`

**解决**: 更新pip并重试
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 7.2 API调用失败

**问题**: `API调用失败` 或 `Authentication Error`

**解决**:
1. 确认API Key正确
2. 确认API Key有余额（硅基流动免费额度）
3. 检查网络是否能访问 api.siliconflow.cn

### 7.3 模拟模式

如果不想使用真实AI功能，可以直接回车跳过API Key输入，程序会进入模拟模式演示基本功能。

### 7.4 编码问题

如果遇到中文乱码，确保文件保存为UTF-8编码。PowerShell可设置：
```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

---

## 8. 卸载/清理

### 8.1 删除虚拟环境

```bash
conda remove -n account_book --all -y
```

### 8.2 删除项目目录

```bash
rm -rf g:\eight_dim\课堂笔记\专高六\agent工单\gd1\agent_account_book
```

---

## 9. 安全建议

### 9.1 保护API Key

- 不要将API Key提交到Git
- 不要在代码中硬编码API Key
- 建议使用运行时输入方式

### 9.2 数据库备份

定期备份 `data/account_book.db` 文件，防止数据丢失。

### 9.3 权限设置

```bash
# Linux/Mac 设置数据库文件权限
chmod 600 data/account_book.db
```

---

## 10. 联系方式

如有问题，请检查：
1. API Key是否有效
2. 网络是否正常
3. Python环境是否正确激活
