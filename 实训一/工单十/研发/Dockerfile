# ============================================================
# RAG QA System Dockerfile
# 默认使用 Python 3.11 slim，兼容 CPU 部署；如需 GPU，可后续切换为 CUDA 基础镜像
# 外部服务 (Milvus / MySQL) 不打包，通过 .env 或 docker-compose 连接
# ============================================================

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖文件，利用缓存
COPY requirements.txt ./

# 安装依赖
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# 复制项目代码
COPY app/ ./app/
COPY frontend/ ./frontend/
COPY run.py ./
COPY .env.example ./

# 创建运行目录
RUN mkdir -p \
    /app/data/uploads \
    /app/data/parsed \
    /app/data/documents \
    /app/data/logs \
    /app/data/vision_debug \
    /app/data/images \
    /app/data/mineru_debug \
    /models/embedding \
    /models/rerank

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["python", "run.py"]
