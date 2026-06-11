# API 性能瓶颈设计方案

## 1. 目标

本方案面向当前仓库的 FastAPI RAG 服务，目标不是泛化地讨论“怎么优化 API”，而是围绕现有实现识别真实瓶颈、定义观测指标，并给出可执行的改造方向。

建议以以下目标作为本项目的生产基线：

- `/api/chat` 文本问答接口：P95 小于 5 秒，错误率小于 1%。
- `/api/chat/stream` 首包时间：P95 小于 2 秒。
- `/api/documents/upload` 上传确认接口：P95 小于 500 ms。
- 文档索引任务：100 页 PDF 在 8 分钟内完成，且不影响在线问答。
- 应用冷启动时间：小于 60 秒。
- 外部依赖异常时，接口应快速失败，不允许长时间阻塞工作进程。

## 2. 当前调用链路

### 2.1 聊天问答链路

当前 `/api/chat` 与 `/api/chat/stream` 的主路径如下：

1. 从 Redis 读取会话历史。
2. 进行 query rewrite，默认走一次 LLM 改写。
3. 对多个 query variant 执行 embedding。
4. 对每个 variant 执行 Milvus 检索；若启用混合检索，还会追加 BM25 检索。
5. 对召回结果执行 soft rank、CrossEncoder rerank、final rank。
6. 组装 prompt，再调用一次主 LLM 生成答案。
7. 当答案命中“证据不足”时，可能再次触发抽取式补偿和原问题回退检索。
8. 将问答结果写回 Redis。

这条链路的主要入口在：

- `app/api/routes/chat.py`
- `app/services/rag/pipeline.py`
- `app/services/rag/pipeline_query.py`
- `app/services/rag/pipeline_retrieval.py`
- `app/services/rag/reranker.py`
- `app/services/llm/client.py`

### 2.2 文档上传与索引链路

当前 `/api/documents/upload` 的主路径如下：

1. 请求线程保存上传文件。
2. 通过 FastAPI `BackgroundTasks` 在同一进程中启动后台处理。
3. 解析 PDF，当前默认走 MinerU。
4. 如启用视觉能力，批量调用视觉模型生成图片描述。
5. 清洗正文、表格、图片信息并切分 chunk。
6. 对 chunk 批量生成 embedding。
7. 先删除旧向量，再写入 Milvus，并在每次导入后 `flush`。
8. 将解析结果整体写入本地 JSON，并更新 SQLite 元数据。

主要入口在：

- `app/api/routes/documents.py`
- `app/services/document/manager.py`
- `app/services/document/mineru_parser.py`
- `app/services/document/image_processor.py`
- `app/services/vector/embedder.py`
- `app/services/vector/milvus_store.py`

### 2.3 语音转写链路

当前 `/api/speech/transcribe` 的主路径较短，但同样存在阻塞点：

1. 一次性把整个音频文件读入内存。
2. 调用外部语音模型转写。

主要入口在：

- `app/api/routes/speech.py`
- `app/services/speech/transcriber.py`

## 3. 核心瓶颈识别

| 编号 | 瓶颈点 | 现状 | 影响 | 优先级 |
| --- | --- | --- | --- | --- |
| B1 | `async` 路由内部执行同步阻塞逻辑 | Redis、MySQL、Milvus、SentenceTransformer、OpenAI SDK、requests 都在同步调用链上 | 单 worker 下并发能力很差，外部接口慢时会直接占住事件循环 | P0 |
| B2 | 文档处理使用进程内 `BackgroundTasks` | 上传确认后，实际索引仍在 API 进程内执行 | CPU/GPU 与在线问答争抢资源；进程重启会中断任务 | P0 |
| B3 | 聊天链路 LLM 调用次数偏多 | query rewrite + 主回答 + 抽取补偿 + 原问题回退，最坏可达 3 到 4 次 | 直接拉高 P95 和成本，对上游限流极其敏感 | P0 |
| B4 | 检索扇出过大 | 多个 query variant * dense 检索 * BM25 检索，再接 rerank | Milvus QPS、CrossEncoder 推理耗时都会放大 | P0 |
| B5 | rerank 候选池偏大 | `target_top_k * 20`，最多 200 条进入 rerank | CPU/GPU 占用高，问答延迟明显增加 | P1 |
| B6 | 启动阶段强依赖外部组件 | 启动时立即连接 MySQL、Redis、Milvus，并执行 embedding warmup | 任何一个依赖未就绪，整个服务无法启动 | P1 |
| B7 | 元数据存储使用 SQLite 且未做并发调优 | 每次操作新建连接，没有 WAL、busy timeout | 后台索引和前台查询并发时容易锁竞争 | P1 |
| B8 | 鉴权与会话存储没有连接池/异步化 | 每次请求都可能访问 MySQL/Redis | 登录、鉴权和会话读写会放大请求尾延迟 | P1 |
| B9 | 向量写入策略粗粒度 | 每次文档导入都 `delete + insert + flush` | Milvus 写入吞吐下降，重建索引窗口长 | P1 |
| B10 | 解析产物按整文件读取 | `/documents/{doc_id}/content` 每次整包读取大 JSON | 大文档下内存抖动明显，接口响应随文档大小线性变慢 | P2 |
| B11 | 语音接口整包读入内存 | `await file.read()` 一次性读音频 | 大文件场景容易造成单请求内存峰值偏高 | P2 |
| B12 | 观测粒度不够 | 目前只记录 `embed/search/llm/total` 粗粒度日志 | 很难定位是 query rewrite、Milvus、rerank 还是上游 LLM 导致变慢 | P0 |

## 4. 具体根因分析

### 4.1 在线接口本质上是“同步阻塞 API”

虽然路由定义为 `async def`，但核心依赖均为同步调用：

- Redis 使用 `redis.Redis`。
- MySQL 使用 `PyMySQL`。
- Milvus 客户端是同步接口。
- Embedding/Rerank 模型推理为同步本地调用。
- LLM 与语音转写为同步 SDK 调用。
- MinerU 解析使用 `requests.Session`。

这意味着当前服务更多像“在 FastAPI 外壳里的同步应用”。当外部 LLM 变慢、Milvus 查询增加或文档解析任务挤占 CPU 时，请求并发会急剧下降。

### 4.2 文档索引和在线查询没有资源隔离

`/api/documents/upload` 虽然很快返回，但后续索引任务仍在 API 进程中执行。对当前项目而言，最重的计算全部集中在这个后台流程：

- MinerU 解析长文档。
- 图片批量描述。
- chunk embedding。
- Milvus 删除与写入。
- 大 JSON 落盘。

这会导致“上传一个大 PDF，所有聊天都变慢”的典型资源争用问题。

### 4.3 聊天链路存在明显的扇出放大

当前问答不是“一次检索 + 一次生成”，而是：

- 先做 query rewrite。
- 再对多个 variant 执行 embedding。
- 每个 variant 可能执行 dense 与 BM25 两类检索。
- 召回后做结构加权，再做 CrossEncoder rerank。
- 最后还可能进入 fallback 逻辑，重新检索并再次调用 LLM。

如果 `llm_query_variant_count=4` 且 hybrid search 开启，那么一次问答的后端扇出会非常大。P50 也许还能接受，但 P95 很容易失控。

### 4.4 生产配置与代码实现存在轻微漂移

当前仓库存在几处会影响稳定性的配置/实现偏差：

- `requirements.txt` 缺少 `redis` 依赖，而运行时代码强依赖它。
- `RERANK_CANDIDATE_COUNT` 已定义在配置中，但当前检索主链路没有真正使用该参数，实际候选规模由代码中的倍数规则控制。
- 启动时 `warmup()` 会主动加载 embedding 模型并触发一次向量化，这对冷启动时间影响很明显。

这类漂移本身不是最大耗时项，但会增加部署失败率和调优成本。

## 5. 观测指标设计

在开始大改之前，建议先补齐指标。至少要覆盖下面这些维度：

- HTTP 指标：`request_count`、`request_latency_ms`、`status_code`、`path`。
- 聊天阶段指标：`history_read_ms`、`query_rewrite_ms`、`embed_ms`、`milvus_dense_ms`、`milvus_bm25_ms`、`rerank_ms`、`prompt_build_ms`、`llm_answer_ms`、`fallback_ms`。
- 聊天规模指标：`query_variant_count`、`retrieval_hit_count`、`rerank_candidate_count`、`prompt_chars`、`reference_count`。
- 索引指标：`pdf_parse_ms`、`image_describe_ms`、`chunk_count`、`embed_batch_ms`、`milvus_upsert_ms`、`parsed_json_write_ms`。
- 资源指标：CPU、内存、GPU 显存、Milvus QPS、Redis RTT、MySQL RTT。
- 外部依赖指标：LLM 成功率、MinerU 成功率、重试次数、超时次数。

## 6. 目标架构设计

建议将当前单体式 API 进程拆成“在线请求面”和“离线索引面”两部分：

- API 服务
  - 负责鉴权、会话、聊天问答、查询文档状态。
  - 保持轻量，避免执行重型 PDF 解析。
- Worker 服务
  - 专门执行文档解析、图片描述、切块、embedding、Milvus 写入。
  - 通过队列接收任务，支持重试、限流与恢复。
- 公共依赖
  - MySQL：账号体系。
  - Redis：会话与任务队列。
  - Milvus：向量检索。
  - 外部 LLM / MinerU：统一通过超时、熔断与并发限制访问。

## 7. 推荐改造顺序

### P0

- 给聊天链路和索引链路补齐阶段级指标。
- 将文档处理从 `BackgroundTasks` 迁移到独立 worker。
- 控制 query rewrite、hybrid search、fallback 的扇出规模。
- 对所有外部调用增加明确的超时、重试上限和并发限制。

### P1

- 把 Redis、MySQL 访问改为连接池或异步客户端。
- 把 SQLite 元数据改为 MySQL/PostgreSQL，或至少开启 WAL。
- 对 Milvus 写入改成批量、异步、减少 `flush` 次数。
- 大文档内容接口改成分页或按页读取。

### P2

- 引入 embedding cache、query cache、热点回答 cache。
- 对图片描述、语音转写增加大小限制与队列化。
- 在 GPU 部署场景下拆分 embedding/rerank 推理节点。

## 8. 结论

本项目当前的主要性能矛盾不是“FastAPI 本身够不够快”，而是：

- 在线接口同步阻塞。
- 检索链路扇出过大。
- 文档索引与在线查询没有资源隔离。
- 外部依赖没有被限流和治理。

只要先完成“观测补齐 + 任务隔离 + 扇出收缩”这三步，API 的稳定性和 P95 延迟会明显改善，这也是后续做更细粒度优化的前提。
