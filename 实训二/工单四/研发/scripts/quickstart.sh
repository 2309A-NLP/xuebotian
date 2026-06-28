#!/bin/bash

#===============================================================================
# 基金问答智能体 - 快速部署脚本 (Ubuntu/Debian)
# 一键安装并运行
#===============================================================================

set -e

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}  基金问答智能体 - 快速部署${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""

# 检查 root
if [[ $EUID -ne 0 ]]; then
    echo -e "${YELLOW}[提示]${NC} 建议使用 root 运行: sudo $0"
    echo ""
fi

# 1. 安装系统依赖
echo -e "${GREEN}[1/6]${NC} 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl > /dev/null 2>&1
echo -e "${GREEN}完成${NC}"

# 2. 创建虚拟环境
echo -e "${GREEN}[2/6]${NC} 创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
echo -e "${GREEN}完成${NC}"

# 3. 安装 Python 依赖
echo -e "${GREEN}[3/6]${NC} 安装 Python 依赖..."
pip install -r requirements.txt -q
echo -e "${GREEN}完成${NC}"

# 4. 创建配置
echo -e "${GREEN}[4/6]${NC} 创建配置文件..."
if [ ! -f .env ]; then
    cat > .env << 'EOF'
# SiliconFlow API Key (请替换为你的 API Key)
SILICONFLOW_API_KEY=your_api_key_here

# 模型配置
MODEL_NAME=deepseek-ai/DeepSeek-V4-Flash
TEMPERATURE=0.1
MAX_TOKENS=4096

# 数据库配置
DB_PATH=./data/博金杯比赛数据.db

# Agent 配置
MAX_RETRIES=3
EOF
    echo -e "${YELLOW}已创建 .env 配置文件，请编辑填入 API Key${NC}"
fi
echo -e "${GREEN}完成${NC}"

# 5. 准备数据目录
echo -e "${GREEN}[5/6]${NC} 准备数据目录..."
mkdir -p data
if [ ! -f "data/博金杯比赛数据.db" ]; then
    echo -e "${YELLOW}[提示]${NC} 请将数据库文件放入 data/ 目录"
fi
echo -e "${GREEN}完成${NC}"

# 6. 启动服务
echo -e "${GREEN}[6/6]${NC} 启动服务..."
echo ""
echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}  部署完成！${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""
echo "使用说明:"
echo "  1. 编辑 .env 文件填入你的 SiliconFlow API Key"
echo "  2. 将数据库文件放入 data/ 目录"
echo "  3. 运行以下命令启动:"
echo ""
echo "  source venv/bin/activate"
echo "  python main.py --interactive"
echo ""
echo "  或启动 API 服务:"
echo "  source venv/bin/activate"
echo "  python api.py"
echo ""
