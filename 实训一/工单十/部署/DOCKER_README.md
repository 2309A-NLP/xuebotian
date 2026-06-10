# RAG QA System - Docker 部署指南

## 部署原则

当前 Docker 方案只做一件事：

- **只打包并运行你的项目应用本身**

以下服务**不会**被打进镜像，也**不会**由 `docker-compose.yml` 启动：

- `MySQL`
- `Redis`
- `Milvus`

这些都按**外部服务**方式连接，你可以继续使用宿主机上已有的服务，或者连接到局域网 / 云服务器上的现成服务。

## 现在包含的文件

- `Dockerfile`：应用镜像构建文件
- `docker-compose.yml`：只启动 `rag-app`
- `.env.docker`：环境变量模板
- `docker-start.bat`：Windows 启动脚本
- `docker-start.sh`：Linux / macOS 启动脚本

## 你的部署前提

启动前请确认下面这些外部依赖已经可用：

- `MySQL`
- `Redis`
- `Milvus`

同时确认本地模型目录存在：

- `G:/eight_dim/model/BGE-m3`
- `G:/eight_dim/model/bge-reranker-base`

如果模型目录不在这里，请修改 `docker-compose.yml` 中的挂载路径。

## 外部服务如何连接

当前默认通过 `host.docker.internal` 访问宿主机服务：

- `MILVUS_URI=http://host.docker.internal:19530`
- `MYSQL_HOST=host.docker.internal`
- `REDIS_URL=redis://host.docker.internal:6379/0`

如果你的服务不在本机，而是在别的机器上，把这些值改成对应的 IP 或域名即可。

## 你现在该怎么做

### 1）复制环境文件

如果项目里还没有 `.env`，先从模板复制：

```bash
cp .env.docker .env
```

Windows 下也可以直接复制改名。

### 2）修改 `.env`

重点确认这些配置：

- `LLM_API_KEY`
- `MINERU_API_TOKEN`
- `MINERU_API_BASE_URL`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_PASSWORD`
- `REDIS_URL`
- `MILVUS_URI`
- `AUTH_SECRET_KEY`

### 3）构建镜像

```bash
docker compose build
```

### 4）启动应用容器

```bash
docker compose up -d
```

### 5）查看日志

```bash
docker compose logs -f rag-app
```

### 6）访问页面

```text
http://localhost:8000
```

## 当前 compose 的行为

现在的 `docker-compose.yml` 只会启动一个服务：

- `rag-app`

它不会创建：

- `mysql`
- `redis`
- `milvus`

所以镜像里没有这些服务，容器启动时只会去连接你外部已经运行好的实例。

## 常用命令

```bash
# 构建镜像
docker compose build

# 启动应用
docker compose up -d

# 查看状态
docker compose ps

# 查看日志
docker compose logs -f rag-app

# 停止服务
docker compose down

# 重建并启动
docker compose up -d --build
```

## 常见问题

### 1. Redis / MySQL / Milvus 连不上

优先检查：

- 外部服务是否真的已经启动
- 地址和端口是否正确
- 容器能否访问宿主机服务
- Windows 防火墙是否拦截了端口

### 2. 模型挂载失败

检查这些目录是否真实存在：

- `G:/eight_dim/model/BGE-m3`
- `G:/eight_dim/model/bge-reranker-base`

### 3. 端口冲突

如果 `8000` 被占用，把 `docker-compose.yml` 里的：

```yaml
ports:
  - "8000:8000"
```

改成例如：

```yaml
ports:
  - "8001:8000"
```

## 结论

你现在的部署方式已经变成：

- 镜像里只有你的项目
- 容器里只运行你的应用
- `MySQL / Redis / Milvus` 全部走外部服务连接

如果你愿意，我下一步可以继续直接帮你：

- 检查你当前 `.env` 该怎么填
- 帮你核对外部 `MySQL / Redis / Milvus` 地址
- 直接执行 `docker compose build` 和 `docker compose up -d`
