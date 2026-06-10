# Docker 部署设计文档

## 1. 文档目的

本文档用于说明本项目当前 Docker 部署方案的设计边界、架构组成、运行流程、配置要求、风险点与验收标准，便于后续实施、交接与运维。

## 2. 设计范围

本次设计基于仓库当前实现，部署对象是 `RAG QA System` 应用本身，不包含将 `MySQL`、`Redis`、`Milvus` 一并编排进同一个 `docker-compose.yml`。

当前方案的范围包括：

- 构建并运行应用容器 `rag-app`
- 通过挂载方式向容器提供本地 Embedding / Rerank 模型
- 通过环境变量连接外部 `MySQL`、`Redis`、`Milvus`
- 通过环境变量连接外部 `LLM API` 与 `MinerU API`
- 持久化项目运行期间产生的上传文件、解析结果、日志和调试数据

当前方案不包含：

- 外部基础设施的自动安装与初始化
- 容器内置 GPU 运行镜像
- Kubernetes 编排
- 完整 CI/CD 发布流水线

## 3. 当前实现基线

仓库内现有 Docker 相关文件如下：

- `Dockerfile`
- `docker-compose.yml`
- `.env.docker`
- `docker-start.bat`
- `docker-start.sh`
- `DOCKER_README.md`

当前 `docker-compose.yml` 只定义了一个服务：

- 服务名：`rag-app`
- 镜像名：`rag-gd10:latest`
- 容器名：`rag-gd10-app`
- 暴露端口：`8000`

应用启动入口为：

```bash
python run.py
```

健康检查接口为：

```text
GET /api/health
```

## 4. 总体架构

### 4.1 架构概览

```text
浏览器
  |
  v
Docker 容器: rag-app
  |- FastAPI API
  |- 前端静态页面
  |- 文档解析 / 清洗 / 分块
  |- BGE-M3 Embedding
  |- BGE Reranker
  |- RAG 检索与问答流程
  |
  +----> MySQL       (外部服务)
  +----> Redis       (外部服务)
  +----> Milvus      (外部服务)
  +----> LLM API     (外部服务)
  +----> MinerU API  (外部服务)

宿主机目录挂载
  |- ./data/uploads
  |- ./data/parsed
  |- ./data/documents
  |- ./data/logs
  |- ./data/vision_debug
  |- G:/eight_dim/model/BGE-m3
  |- G:/eight_dim/model/bge-reranker-base
```

### 4.2 架构原则

- 应用容器化，基础设施外部化
- 模型不打包进镜像，采用宿主机只读挂载
- 业务运行数据不写入镜像层，统一走数据卷
- 配置通过 `.env` 和 `docker-compose.yml` 注入
- 容器启动后即对关键依赖做连通性与预热校验

## 5. 组件设计

### 5.1 应用容器

| 项目 | 设计 |
| --- | --- |
| 基础镜像 | `python:3.11-slim` |
| 工作目录 | `/app` |
| 启动命令 | `python run.py` |
| Web 框架 | `FastAPI` + `uvicorn` |
| 对外端口 | `8000` |
| 健康检查 | `curl -f http://localhost:8000/api/health` |
| 重启策略 | `unless-stopped` |

### 5.2 外部依赖

| 依赖 | 作用 | 当前接入方式 |
| --- | --- | --- |
| MySQL | 用户认证、用户表初始化 | 通过 `MYSQL_*` 环境变量连接 |
| Redis | 会话历史缓存 | 通过 `REDIS_URL` 连接 |
| Milvus | 向量检索 | 通过 `MILVUS_URI` 连接 |
| LLM API | 问答、改写、视觉描述、语音转写 | 通过 `LLM_*`、`VISION_*`、`SPEECH_*` 连接 |
| MinerU API | PDF 解析 | 通过 `MINERU_*` 连接 |

### 5.3 模型挂载

当前设计不把大模型文件放入镜像，而是从宿主机挂载：

- `G:/eight_dim/model/BGE-m3 -> /models/embedding/BGE-m3:ro`
- `G:/eight_dim/model/bge-reranker-base -> /models/rerank/bge-reranker-base:ro`

这样可以缩短镜像构建时间，避免模型文件重复打包，并支持模型独立升级。

## 6. 存储设计

### 6.1 持久化目录

当前已挂载的数据目录如下：

| 宿主机目录 | 容器目录 | 用途 |
| --- | --- | --- |
| `./data/uploads` | `/app/data/uploads` | 原始上传文件 |
| `./data/parsed` | `/app/data/parsed` | 解析结果 |
| `./data/documents` | `/app/data/documents` | 文档元数据与数据库文件 |
| `./data/logs` | `/app/data/logs` | 应用日志 |
| `./data/vision_debug` | `/app/data/vision_debug` | 视觉调试产物 |

### 6.2 目录初始化

应用在读取配置时会自动创建以下目录：

- `data/logs`
- `data/uploads`
- `data/parsed`
- `data/images`
- `data/mineru_debug`
- `data/vision_debug`
- `DOCUMENT_DB_PATH` 的父目录

Dockerfile 在构建时也提前创建了这些运行目录，用于降低首次启动失败概率。

## 7. 网络与访问设计

### 7.1 对外访问

- 宿主机访问地址：`http://localhost:8000`
- 容器监听地址：`0.0.0.0:8000`

### 7.2 外部依赖访问

当前代码和文档支持两种访问方式：

- 通过 `host.docker.internal` 访问宿主机服务
- 通过固定局域网地址访问远程服务，例如当前 `docker-compose.yml` 中使用的 `10.223.11.19`

部署时应统一选择一种方式，避免环境变量和 Compose 内联变量相互覆盖。

## 8. 配置设计

### 8.1 配置来源

当前容器配置来源有两层：

- `env_file: .env`
- `docker-compose.yml` 中的 `environment`

在 Docker Compose 中，`environment` 会覆盖 `env_file` 中的同名配置。因此当前 `docker-compose.yml` 中写死的 `MYSQL_*`、`REDIS_URL`、`MILVUS_URI`、模型路径等值，会优先于 `.env` 生效。

### 8.2 关键配置项

部署时至少应确认以下配置：

- `APP_HOST`
- `APP_PORT`
- `DEBUG`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `MINERU_API_BASE_URL`
- `MINERU_API_TOKEN`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`
- `REDIS_URL`
- `VECTOR_BACKEND`
- `MILVUS_URI`
- `EMBEDDING_MODEL_NAME`
- `RERANK_MODEL_NAME`
- `AUTH_SECRET_KEY`

### 8.3 当前已知配置约束

- 应用代码实际读取的是 `ENVIRONMENT`，不是 `APP_ENV`
- `VECTOR_BACKEND=milvus` 时，Milvus 必须可达
- Redis 在应用启动期会执行 `ping`
- MySQL 在应用启动期会尝试创建数据库和 `users` 表
- 启动预热阶段会加载 Embedding 模型并执行向量库预热

## 9. 启动流程设计

应用容器当前启动流程如下：

1. Docker 启动 `rag-app` 容器
2. `python run.py` 启动 `uvicorn`
3. `get_settings()` 读取 `.env` 并创建本地目录
4. `FastAPI lifespan` 中创建 `AppContainer`
5. `AuthService` 连接 MySQL，确保数据库与 `users` 表存在
6. `ConversationHistoryService` 连接 Redis 并执行 `PING`
7. 根据 `PDF_PARSER_BACKEND` 初始化 PDF 解析服务
8. 初始化 Embedding、Rerank、LLM、向量库等核心服务
9. 执行 `warmup()`，加载 Embedding 模型并对 Milvus 做预热
10. 应用开始对外提供 HTTP 服务
11. Docker 健康检查访问 `/api/health`

该流程说明：当前部署方案属于“强依赖启动”。只要 MySQL、Redis、Milvus、模型挂载、必要配置有一项不可用，容器就可能无法正常启动。

## 10. 部署流程设计

### 10.1 前置条件

部署前应准备：

- 已安装 Docker 与 Docker Compose
- 外部 `MySQL`、`Redis`、`Milvus` 可访问
- 外部 `LLM API` 可访问
- 外部 `MinerU API` 可访问
- 宿主机模型目录存在且路径正确
- 宿主机 `8000` 端口未被占用

### 10.2 标准部署步骤

1. 复制环境文件：`cp .env.docker .env`
2. 修改 `.env` 中的密钥、IP、端口、模型配置
3. 执行镜像构建：`docker compose build`
4. 启动容器：`docker compose up -d`
5. 查看状态：`docker compose ps`
6. 查看日志：`docker compose logs -f rag-app`
7. 访问页面：`http://localhost:8000`
8. 检查健康接口：`http://localhost:8000/api/health`

## 11. 安全设计

当前方案的安全基线要求如下：

- `AUTH_SECRET_KEY` 必须替换为随机强密钥
- `LLM_API_KEY`、`MINERU_API_TOKEN`、数据库口令不应写入公开仓库
- 模型目录使用只读挂载
- 生产环境应关闭 `DEBUG`
- 如果通过 HTTPS 反向代理对外提供服务，应将 `AUTH_COOKIE_SECURE` 设为 `true`

## 12. 可观测性设计

当前可观测性主要依赖以下手段：

- Docker `json-file` 日志驱动
- 应用文件日志目录 `data/logs`
- 容器健康检查接口 `/api/health`
- 手工执行 `docker compose logs -f rag-app`

该设计适合单机部署与问题排查，但尚未形成标准化指标、告警和集中日志方案。

## 13. 风险与限制

当前方案存在以下已知限制：

- `docker-compose.yml` 中存在固定 IP、固定密码与模型路径，环境迁移成本较高
- 当前仅容器化应用，外部依赖需要手工准备
- 模型路径使用 Windows 盘符，跨平台可移植性较弱
- 启动过程对 MySQL、Redis、Milvus 都是强依赖，任一不可用会影响启动
- 健康检查只验证应用接口存活，不验证外部依赖是否就绪
- 当前 GPU 相关配置只在 Compose 中以注释形式保留，未形成正式 GPU 部署方案

## 14. 验收标准

完成部署后，应满足以下验收条件：

- `docker compose ps` 中 `rag-app` 为 `Up`
- `GET /api/health` 返回成功
- 浏览器可打开登录页与聊天页
- 用户注册与登录功能正常
- PDF 上传、解析、入库流程可用
- 问答接口可以成功调用 Milvus 与 LLM 完成一次检索问答
- 日志目录中可看到应用运行日志
- 重启容器后，上传数据和元数据未丢失

## 15. 结论

当前 Docker 部署设计适合“单应用容器 + 外部基础设施”的交付模式，优点是改造成本低、模型不入镜像、能够快速接入现有 MySQL/Redis/Milvus 环境。其主要问题是配置耦合较强、环境可移植性一般、启动链路对外部依赖敏感。后续优化应优先围绕配置治理、镜像规范化、启动就绪检查和环境标准化展开。
