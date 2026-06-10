#!/bin/bash
# ============================================================
# RAG QA System - Docker 构建和运行脚本
# ============================================================

set -e

echo "============================================================"
echo "RAG QA System - Docker 构建和运行脚本"
echo "============================================================"
echo ""

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "[错误] 未检测到 Docker，请先安装 Docker"
    echo "安装指南: https://docs.docker.com/engine/install/"
    exit 1
fi

# 检查 Docker Compose 是否可用
if ! docker compose version &> /dev/null; then
    echo "[错误] 未检测到 Docker Compose，请安装或更新 Docker"
    exit 1
fi

echo "[1/4] 准备环境配置..."
if [ ! -f .env ]; then
    if [ -f .env.docker ]; then
        cp .env.docker .env
        echo "      已从 .env.docker 创建 .env"
        echo "      请编辑 .env 文件配置 LLM_API_KEY 等参数"
    else
        echo "[警告] 未找到 .env 配置文件"
    fi
else
    echo "      .env 文件已存在"
fi

echo ""
echo "[2/4] 构建 Docker 镜像..."
echo "      这可能需要 10-30 分钟，取决于网络速度"
echo ""
docker compose build --no-cache

echo ""
echo "[3/4] 镜像构建完成！"
echo ""

echo "[4/4] 启动服务..."
echo ""
docker compose up -d

echo ""
echo "============================================================"
echo "启动成功！"
echo ""
echo "访问地址: http://localhost:8000"
echo ""
echo "常用命令:"
echo "  查看日志: docker compose logs -f"
echo "  停止服务: docker compose down"
echo "  重启服务: docker compose restart"
echo "  查看状态: docker compose ps"
echo "============================================================"
