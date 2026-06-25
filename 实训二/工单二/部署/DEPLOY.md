# AIOScheduler Linux 部署指南

> 本文档介绍如何在一台 Linux 服务器上部署 AIOScheduler，支持 CLI 和 Web 两种模式，以及 systemd 开机自启配置。

---

## 一、环境准备

### 1.1 推荐配置

| 项目 | 要求 |
|------|------|
| 系统 | Ubuntu 20.04+ / CentOS 8+ / Debian 11+ |
| CPU | 1 核即可 |
| 内存 | 512 MB 以上 |
| 磁盘 | 2 GB 可用空间 |
| 网络 | 可访问 SiliconFlow API（国内可直连） |

### 1.2 安装 Python 3.10+

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# CentOS / RHEL
sudo yum install -y python310 python310-pip git
# 若无 python310：sudo dnf install -y python3.10

# 验证
python3 --version
# 输出应为 Python 3.10.x 或更高
```

### 1.3 克隆项目

```bash
# 如果已有项目，直接上传到服务器即可
# 首次克隆（假设项目在 Git 仓库）
git clone <your-repo-url> /opt/aioscheduler
cd /opt/aioscheduler
```

---

## 二、依赖安装

### 2.1 创建虚拟环境（推荐）

```bash
cd /opt/aioscheduler/aioscheduler
python3 -m venv venv
source venv/bin/activate

# 升级 pip
pip install --upgrade pip
```

### 2.2 安装 Python 依赖

```bash
pip install requests flask
```

> **说明**：项目仅依赖 `requests` 和 `flask` 两个外部库，其余均为 Python 标准库，无需其他依赖。

### 2.3 验证安装

```bash
python3 -c "import requests; import flask; print('依赖检查通过')"
```

---

## 三、配置 API Key

### 3.1 方式一：环境变量（推荐用于生产环境）

```bash
# 写入 bashrc（永久生效）
echo 'export SILICONFLOW_API_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc

# 或写入系统环境变量
sudo tee /etc/profile.d/aioscheduler.sh << 'EOF'
export SILICONFLOW_API_KEY="your-api-key-here"
EOF
sudo chmod +x /etc/profile.d/aioscheduler.sh
```

### 3.2 方式二：config.txt 文件

```bash
echo "your-api-key-here" > /opt/aioscheduler/aioscheduler/config.txt
chmod 600 /opt/aioscheduler/aioscheduler/config.txt   # 防止其他人读取
```

### 3.3 验证 Key 生效

```bash
source venv/bin/activate
python3 -c "import os; print('API Key:', os.environ.get('SILICONFLOW_API_KEY', 'NOT SET'))"
```

---

## 四、运行测试

启动前先快速验证基本功能是否正常：

```bash
cd /opt/aioscheduler/aioscheduler
source venv/bin/activate

# 测试数据库初始化
python3 -c "
from database.models import schedule_repo
schedule_repo.create_table()
print('数据库初始化成功')
"

# 测试 Agent 加载（无 API Key 时会交互式要求输入）
python3 main_agent.py --help
```

---

## 五、运行模式

### 5.1 模式一：命令行交互（CLI）

```bash
cd /opt/aioscheduler/aioscheduler
source venv/bin/activate
python3 main_agent.py
```

**示例会话**：

```
初始化 Agent (模型: deepseek-ai/DeepSeek-V4-Flash)...
✅ Agent 初始化完成！

助理思考中...
助理: 您好！我是日程提醒智能体，有什么可以帮您？

你: 下午5点开会
助理思考中...
助理: 17:00 提醒您开会
```

### 5.2 模式二：Web 服务（推荐生产使用）

```bash
cd /opt/aioscheduler/aioscheduler
source venv/bin/activate

# 默认端口 5000
python3 main_agent.py --web

# 自定义端口
python3 main_agent.py --web --host 0.0.0.0 --port 8080
```

启动后访问：`http://your-server-ip:5000`

### 5.3 后台运行（nohup）

```bash
cd /opt/aioscheduler/aioscheduler
source venv/bin/activate

nohup python3 main_agent.py --web --port 8080 > /var/log/aioscheduler.log 2>&1 &

# 查看进程是否启动
ps aux | grep main_agent
# 应该看到 python3 main_agent.py --web --port 8080

# 查看日志
tail -f /var/log/aioscheduler.log
```

### 5.4 使用 screen（推荐，适合长期运行）

```bash
# 创建名为 scheduler 的 screen 会话
screen -S scheduler

# 在 screen 内执行
cd /opt/aioscheduler/aioscheduler
source venv/bin/activate
python3 main_agent.py --web --port 8080

# 分离 screen（不关闭程序）：按 Ctrl+A，然后按 D
# 重新进入：screen -r scheduler
```

---

## 六、systemd 服务配置（推荐）

使用 systemd 管理进程，可实现开机自启、自动重启、日志管理。

### 6.1 创建服务文件

```bash
sudo nano /etc/systemd/system/aioscheduler.service
```

写入以下内容：

```ini
[Unit]
Description=AIOScheduler - AI Schedule Reminder Agent
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME                    ; 替换为实际用户名
WorkingDirectory=/opt/aioscheduler/aioscheduler
Environment="SILICONFLOW_API_KEY=your-api-key-here"   ; 替换为实际 Key
ExecStart=/opt/aioscheduler/aioscheduler/venv/bin/python3 main_agent.py --web --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10

# 日志配置
StandardOutput=append:/var/log/aioscheduler/stdout.log
StandardError=append:/var/log/aioscheduler/stderr.log

[Install]
WantedBy=multi-user.target
```

### 6.2 创建日志目录

```bash
sudo mkdir -p /var/log/aioscheduler
sudo chown YOUR_USERNAME:YOUR_USERNAME /var/log/aioscheduler  # 替换用户名
```

### 6.3 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl start aioscheduler
sudo systemctl status aioscheduler   # 查看状态
```

### 6.4 开机自启

```bash
sudo systemctl enable aioscheduler
```

### 6.5 常用命令

```bash
# 启动
sudo systemctl start aioscheduler

# 停止
sudo systemctl stop aioscheduler

# 重启
sudo systemctl restart aioscheduler

# 查看日志
sudo journalctl -u aioscheduler -f

# 查看应用日志
tail -f /var/log/aioscheduler/stdout.log
```

### 6.6 常见问题排查

```bash
# 服务启动失败？查看详细错误
sudo systemctl status aioscheduler
sudo journalctl -u aioscheduler -n 50

# 常见错误：
# - Permission denied：检查文件/目录权限
# - ModuleNotFoundError：确认 venv 已正确创建
# - API Key 未配置：检查环境变量是否正确设置
```

---

## 七、反向代理配置（Nginx）

生产环境建议用 Nginx 做反向代理，并配置 HTTPS。

### 7.1 安装 Nginx

```bash
# Ubuntu/Debian
sudo apt install -y nginx

# CentOS
sudo yum install -y nginx
```

### 7.2 配置反向代理

```bash
sudo nano /etc/nginx/sites-available/aioscheduler
```

写入：

```nginx
server {
    listen 80;
    server_name your-domain.com;   ; 替换为你的域名或 IP

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持（Flask-SocketIO 扩展时需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 7.3 启用配置

```bash
sudo ln -s /etc/nginx/sites-available/aioscheduler /etc/nginx/sites-enabled/
sudo nginx -t                    # 检查配置语法
sudo systemctl reload nginx
```

### 7.4 配置 HTTPS（Let's Encrypt 免费证书）

```bash
# 安装 certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书（需域名，IP 无法申请）
sudo certbot --nginx -d your-domain.com

# 自动续期（certbot 会写入 cron/systemd timer）
sudo certbot renew --dry-run
```

---

## 八、飞书/钉钉通知接入（可选）

提醒触发时除了打印到终端，还可以推送到飞书或钉钉。

### 8.1 飞书 WebHook 接入

修改 `main_agent.py` 中的 `ReminderService._trigger_reminder` 方法：

```python
def _trigger_reminder(self, schedule):
    reminder = self._get_warm_reminder(schedule.content)
    time_str = schedule.schedule_time.replace(":", "点") + "分"
    reminder_text = f"[提醒] {time_str}，{reminder}"

    # ========== 飞书通知 ==========
    import requests
    feishu_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/你的webhook地址"
    requests.post(feishu_webhook, json={
        "msg_type": "text",
        "content": {"text": reminder_text}
    }, timeout=5)
    # ==============================

    print(f"\n{'='*50}\n{reminder_text}\n{'='*50}\n")
```

### 8.2 钉钉自定义机器人接入

```python
import requests, hashlib, time, hmac, base64

def dingtalk_notify(content: str, secret: str, webhook: str):
    timestamp = str(round(time.time() * 1000))
    sign = base64.b64encode(
        hmac.new(secret.encode(), (timestamp + '\n' + secret).encode(), digestmod=hashlib.sha256).digest()
    ).decode()
    url = f"{webhook}&timestamp={timestamp}&sign={sign}"
    requests.post(url, json={
        "msgtype": "text",
        "text": {"content": content}
    }, timeout=5)
```

---

## 九、数据备份

### 9.1 备份数据库

```bash
# 手动备份
cp /opt/aioscheduler/aioscheduler/aioscheduler.db /opt/aioscheduler/aioscheduler/aioscheduler.db.bak.$(date +%Y%m%d)

# 定期备份（crontab）
crontab -e
# 添加：每天凌晨3点备份
0 3 * * * cp /opt/aioscheduler/aioscheduler/aioscheduler.db /opt/backup/aioscheduler-$(date +\%Y\%m\%d).db
```

### 9.2 恢复数据

```bash
# 停止服务
sudo systemctl stop aioscheduler

# 恢复
cp /opt/backup/aioscheduler-20260625.db /opt/aioscheduler/aioscheduler/aioscheduler.db

# 重启
sudo systemctl start aioscheduler
```

---

## 十、快速部署脚本（懒人版）

将以下内容保存为 `deploy.sh`，一键完成所有部署步骤：

```bash
#!/bin/bash
set -e

PROJECT_DIR="/opt/aioscheduler"
API_KEY="${SILICONFLOW_API_KEY:-}"

if [ -z "$API_KEY" ]; then
    echo "错误：请先设置环境变量 SILICONFLOW_API_KEY"
    echo "  export SILICONFLOW_API_KEY='your-key'"
    exit 1
fi

echo "==> 1. 安装系统依赖..."
apt update && apt install -y python3 python3-venv python3-pip git nginx certbot

echo "==> 2. 创建目录..."
mkdir -p /var/log/aioscheduler /opt/backup/aioscheduler

echo "==> 3. 安装 Python 依赖..."
cd "$PROJECT_DIR/aioscheduler"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install requests flask

echo "==> 4. 配置 API Key..."
echo "$API_KEY" > config.txt
chmod 600 config.txt

echo "==> 5. 创建 systemd 服务..."
sudo tee /etc/systemd/system/aioscheduler.service << EOF
[Unit]
Description=AIOScheduler
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR/aioscheduler
Environment="SILICONFLOW_API_KEY=$API_KEY"
ExecStart=$PROJECT_DIR/aioscheduler/venv/bin/python3 main_agent.py --web --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10
StandardOutput=append:/var/log/aioscheduler/stdout.log
StandardError=append:/var/log/aioscheduler/stderr.log

[Install]
WantedBy=multi-user.target
EOF

echo "==> 6. 启动服务..."
sudo systemctl daemon-reload
sudo systemctl start aioscheduler
sudo systemctl enable aioscheduler

echo ""
echo "=== 部署完成 ==="
echo "Web 地址: http://$(hostname -I | awk '{print $1}'):8080"
echo "查看状态: sudo systemctl status aioscheduler"
echo "查看日志: sudo journalctl -u aioscheduler -f"
```

使用方法：

```bash
chmod +x deploy.sh
SILICONFLOW_API_KEY="your-key" ./deploy.sh
```

---

## 十一、排错清单

| 问题 | 解决方案 |
|------|---------|
| `ModuleNotFoundError: No module named 'requests'` | 确认已激活 venv：`source venv/bin/activate` |
| `sqlite3.OperationalError: database is locked` | 关闭所有连接后重试，或重启 Python 进程 |
| 提醒不触发 | 检查 `schedule.id` 是否为 None（已修复，参考 OPTIMIZATION.md） |
| Web 页面无法访问 | 检查防火墙：`sudo ufw allow 8080` |
| systemd 启动失败 | 查看日志：`sudo journalctl -u aioscheduler -n 50` |
| API 返回 401 | 检查 API Key 是否正确、是否过期 |
| 启动很慢（>10秒） | LLM 初始化超时，SiliconFlow 服务器可能延迟较高 |
