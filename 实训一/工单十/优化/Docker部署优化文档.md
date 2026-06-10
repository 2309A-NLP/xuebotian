# Docker 部署优化文档

## 1. 文档目标

本文档用于评估当前 Docker 部署方案的不足，并给出一套按优先级落地的优化建议，目标是在不破坏现有业务能力的前提下，提高部署一致性、可迁移性、安全性、稳定性和运维效率。

## 2. 当前方案评估

结合仓库中的 `Dockerfile`、`docker-compose.yml`、`.env.docker`、配置代码和启动流程，当前部署方案具备“能跑”的基础，但距离稳定生产化仍有几项明显短板。

### 2.1 主要问题清单

| 类别 | 当前状态 | 影响 |
| --- | --- | --- |
| 配置治理 | `env_file` 与 `environment` 同时存在，且 Compose 中写死关键配置 | `.env` 容易失效，环境切换不透明 |
| 配置命名 | Compose 使用 `APP_ENV`，代码实际读取 `ENVIRONMENT` | 配置语义不一致，容易误判环境 |
| 机密管理 | `docker-compose.yml` 与 `.env.docker` 中包含固定地址、账号或示例口令 | 容易泄露敏感信息，审计困难 |
| 可移植性 | 模型挂载路径直接写死为 `G:/...` | 仅适配当前 Windows 目录结构 |
| 启动韧性 | 启动时强依赖 MySQL、Redis、Milvus、模型加载 | 任一依赖异常会导致容器启动失败 |
| 健康检查 | 只有 `/api/health` 单一检查 | 不能区分“进程存活”和“依赖就绪” |
| 镜像规范 | 容器默认 root 运行 | 安全面偏弱 |
| 镜像构建 | 依赖安装重，未体现上下文裁剪策略 | 构建耗时长，镜像交付效率一般 |
| 运行模式 | CPU 镜像与 GPU 配置未正式拆分 | 部署路径不清晰 |
| 日志策略 | 同时写容器日志和应用文件日志 | 采集路径重复，运维复杂度上升 |
| 编排能力 | 未提供可选的一体化开发环境 | 新环境搭建依赖人工准备外部服务 |

## 3. 优化目标

建议将部署优化目标统一为以下五项：

- 同一套镜像和配置模板可在多环境复用
- 配置、密钥、模型路径可替换，避免写死在 Compose 中
- 容器启动失败时能够快速定位是应用故障还是依赖未就绪
- 支持 CPU 与 GPU 两种清晰部署路径
- 让开发、测试、生产三类环境都有对应的标准化使用方式

## 4. 优先级建议

### 4.1 P0：应优先落地

#### 4.1.1 清理 Compose 内联硬编码

建议：

- 将 `docker-compose.yml` 中的 `MYSQL_*`、`REDIS_URL`、`MILVUS_URI`、模型路径等硬编码改为变量引用
- 只保留 `env_file`，或者只保留变量插值，不要双重维护
- 把 `APP_ENV` 统一改为 `ENVIRONMENT`

收益：

- 避免 `.env` 被 Compose 覆盖
- 降低跨环境切换成本
- 让问题排查更直接

建议示例：

```yaml
environment:
  APP_HOST: 0.0.0.0
  APP_PORT: 8000
  DEBUG: ${DEBUG:-false}
  ENVIRONMENT: ${ENVIRONMENT:-production}
  VECTOR_BACKEND: ${VECTOR_BACKEND:-milvus}
  MILVUS_URI: ${MILVUS_URI}
  MYSQL_HOST: ${MYSQL_HOST}
  MYSQL_PORT: ${MYSQL_PORT:-3306}
  MYSQL_USER: ${MYSQL_USER}
  MYSQL_PASSWORD: ${MYSQL_PASSWORD}
  MYSQL_DATABASE: ${MYSQL_DATABASE}
  REDIS_URL: ${REDIS_URL}
```

#### 4.1.2 将密钥与口令从模板中剥离

建议：

- `.env.docker` 只保留占位符，不出现真实 IP、用户名、密码
- 生产环境通过部署系统注入密钥
- 至少区分 `.env.docker.example` 与本地私有 `.env`

收益：

- 降低泄露风险
- 便于统一审计与轮换

#### 4.1.3 增加启动就绪检查

建议：

- 区分 `liveness` 和 `readiness`
- `liveness` 仅验证进程可响应
- `readiness` 验证 MySQL、Redis、Milvus 和模型是否可用

收益：

- 避免“接口 200 但业务不可用”
- 反向代理或编排系统可依据 readiness 决定是否接流量

#### 4.1.4 将模型路径参数化

建议：

- 使用 `${EMBEDDING_MODEL_HOST_PATH}` 和 `${RERANK_MODEL_HOST_PATH}`
- 保留容器内固定路径 `/models/...`

收益：

- 解除 Windows 盘符耦合
- Linux、Windows、不同磁盘布局都可复用

#### 4.1.5 补齐 `.dockerignore`

建议排除：

- `.git`
- `.venv`
- `__pycache__`
- `data/logs`
- `data/uploads`
- `data/parsed`
- 大型临时文件和本地 IDE 目录

收益：

- 降低构建上下文大小
- 提升构建速度
- 避免无关数据进入构建过程

## 5. P1：建议在下一阶段完成

### 5.1 镜像安全加固

建议：

- 在 Dockerfile 中创建非 root 用户并切换运行
- 明确 `WORKDIR`、目录权限和只读模型目录
- 根据需要增加 `read_only`、`tmpfs`、`no-new-privileges`

收益：

- 降低容器逃逸和误写风险

### 5.2 CPU / GPU 镜像分离

当前 Compose 中只保留了注释形式的 GPU 配置，但 Dockerfile 仍是通用 CPU 方案。建议拆分为：

- `Dockerfile.cpu`
- `Dockerfile.gpu`
- `docker-compose.cpu.yml`
- `docker-compose.gpu.yml`

收益：

- 部署边界清晰
- 降低单一镜像对多场景妥协的复杂度

### 5.3 启动预热可配置

当前 `AppContainer.warmup()` 会在启动阶段执行 Embedding 模型加载和向量库预热。建议：

- 增加 `STARTUP_WARMUP_ENABLED`
- 增加 `STARTUP_FAIL_ON_DEPENDENCY_ERROR`
- 在某些环境允许“先启动、后预热”

收益：

- 降低首启耗时
- 对外部依赖抖动更宽容

### 5.4 标准化日志策略

建议从两种方案中选一种：

- 方案 A：应用只输出 stdout/stderr，由 Docker 统一采集
- 方案 B：应用保留文件日志，但通过 sidecar 或宿主机代理采集

如果保持当前模式，应明确哪一份日志为主，避免排障时口径不一致。

### 5.5 版本锁定与构建稳定性

当前 `requirements.txt` 使用的是下限版本。建议：

- 产出锁定文件
- 固定关键依赖版本
- 在 CI 中做可重复构建验证

收益：

- 减少“今天能构建、明天构建失败”的不确定性

## 6. P2：中期增强项

### 6.1 提供一体化开发编排

建议新增一套可选 Compose Profile，用于本地开发或演示环境：

- `rag-app`
- `redis`
- `mysql`
- `milvus`

说明：

- 这不是替换当前生产模式
- 而是补充一套“开箱即用”的开发环境

收益：

- 新同学上手更快
- 测试环境复现更容易

### 6.2 引入反向代理与 HTTPS

建议：

- 使用 `nginx` 或 `traefik` 作为入口
- 处理 HTTPS、静态缓存、请求头透传和访问控制

收益：

- 提升安全性
- 为生产流量治理预留空间

### 6.3 增加可观测性

建议逐步补齐：

- Prometheus 指标
- 请求耗时和依赖耗时指标
- 容器资源监控
- 告警规则

重点建议暴露：

- 文档解析耗时
- Embedding 耗时
- Milvus 检索耗时
- LLM 调用耗时
- 失败率与异常类型

## 7. 推荐目标架构

建议后续将部署模式明确为两套标准方案。

### 7.1 方案 A：生产标准模式

```text
反向代理
  |
  v
rag-app 容器
  +----> 外部 MySQL
  +----> 外部 Redis
  +----> 外部 Milvus
  +----> 外部 LLM / MinerU API
  +----> 宿主机模型目录
```

适用场景：

- 生产环境
- 已有中间件基础设施
- 需要复用现网数据库与向量库

### 7.2 方案 B：开发演示模式

```text
docker compose
  |- rag-app
  |- mysql
  |- redis
  |- milvus
```

适用场景：

- 本地开发
- 测试演示
- 新环境快速验证

## 8. 落地顺序建议

建议按以下顺序推进：

1. 先改配置治理：去掉 Compose 硬编码、统一环境变量命名
2. 再做镜像规范：`.dockerignore`、非 root、路径参数化
3. 然后补就绪检查与预热开关
4. 最后再扩展 CPU/GPU 双方案和开发环境 Profile

这样做的原因是：前两步几乎不影响业务逻辑，但能立即提升部署稳定性；后两步涉及启动行为和交付形态，适合在基础稳定后推进。

## 9. 最小优化清单

如果只做一轮低风险优化，建议至少完成以下事项：

- 去掉 `docker-compose.yml` 中的固定 IP、口令和模型宿主路径
- 把 `APP_ENV` 改为 `ENVIRONMENT`
- 新增 `.dockerignore`
- 增加 readiness 检查
- 将容器改为非 root 运行
- 将密钥模板改为占位符形式

完成这六项后，当前 Docker 方案就会从“可用”提升到“基本可维护”。

## 10. 结论

当前 Docker 部署方案的核心问题不是技术路线错误，而是“工程化完成度不够”。它已经具备应用容器化基础，但仍保留了明显的环境耦合和交付耦合。优化工作的重点应放在配置治理、镜像安全、启动韧性和环境标准化上，而不是一开始就追求更复杂的编排平台。
