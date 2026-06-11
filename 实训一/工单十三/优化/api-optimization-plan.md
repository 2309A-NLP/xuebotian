# API 优化方案

## 1. 优化原则

- 优先降低 P95，而不是只追求单次最佳耗时。
- 优先减少外部调用次数，再考虑局部代码微优化。
- 优先隔离重任务，避免索引拖慢在线问答。
- 先补观测，再做参数调优，否则无法判断收益。

## 2. 分阶段优化路线

## 阶段一：低风险快速收敛

目标：不大改架构，先把在线问答的平均耗时和尾延迟压下来。

建议动作：

- 将生产环境 `DEBUG=false`，避免开发模式热更新开销。
- 将 `LLM_QUERY_VARIANT_COUNT` 控制在 1 到 2。
- 将 `RECALL_CANDIDATE_COUNT` 从 60 下调到 24 到 40。
- 将 rerank 候选数量改为显式受 `RERANK_CANDIDATE_COUNT` 控制，建议先设为 20 到 40。
- 将 `TOP_K` 控制在 6 左右，避免上下文过长。
- 将 `PROMPT_MAX_CONTEXT_CHARS` 下调到 6000 到 8000。
- 将 `PROMPT_CHUNK_CHAR_LIMIT` 下调到 1000 到 1500。
- 生产环境默认关闭 `VISION_ENABLED`，只有确实需要图像理解时再打开。
- 对 query rewrite、fallback retry 增加开关，优先保证稳定而不是追求极限召回。

预期收益：

- 单次问答的 Milvus 查询次数下降。
- CrossEncoder rerank 负载下降。
- LLM token 消耗下降。
- P95 延迟与调用成本同步下降。

## 阶段二：任务隔离与资源治理

目标：解决“上传大文档拖慢所有聊天”的核心问题。

建议动作：

- 用 Celery、RQ 或自定义 Redis 队列替换当前 `BackgroundTasks`。
- API 只负责接收上传并入队，立即返回任务 ID。
- Worker 独立消费任务，执行 PDF 解析、图片描述、切块、embedding、Milvus 写入。
- 对 Worker 设置并发上限，避免 GPU/CPU 被一次性打满。
- 对图片描述增加最大图片数、单文档限流和超时熔断。

预期收益：

- 在线 API 与离线索引资源彻底解耦。
- 服务重启时任务可恢复或重试。
- 高峰期可以通过横向扩 worker 提升吞吐。

## 阶段三：I/O 与依赖访问优化

目标：减少阻塞等待，让每个 worker 能承载更多请求。

建议动作：

- Redis 改为 `redis.asyncio` 或统一放在线程池中调用。
- MySQL 改为带连接池的访问层，避免每次请求现连现关。
- LLM/MinerU 调用统一使用可配置超时、重试和并发信号量。
- 对 `get_document_content` 改成按页分页读取，避免每次整包加载大 JSON。
- 对语音接口设置文件大小限制，必要时改为流式上传或临时文件方式。

预期收益：

- 在线请求不会因为外部 I/O 长时间占住事件循环。
- Redis/MySQL/LLM 抖动时的影响范围可控。

## 阶段四：检索链路深度优化

目标：在保证效果的前提下降低召回与重排成本。

建议动作：

- 把 query rewrite 改成“按意图启用”，不是所有问题都重写。
- 对纯事实性短问题，仅保留原问题查询。
- 只在确实需要时开启 hybrid search。
- 将 dense/BM25 的 top_k 分别缩小，再在融合后统一截断。
- 给 embedding 和 query rewrite 增加短期缓存。
- 对热点问题增加回答级缓存，命中后直接返回。

预期收益：

- 每次请求的后端扇出大幅下降。
- Milvus 与 rerank 成本更稳定。

## 3. 建议的生产参数

下面是一组适合作为第一版生产基线的建议值：

```env
DEBUG=false
TOP_K=6
RECALL_CANDIDATE_COUNT=32
LLM_QUERY_VARIANT_COUNT=1
RERANK_ENABLED=true
RERANK_BATCH_SIZE=8
PROMPT_MAX_CONTEXT_CHARS=7000
PROMPT_CHUNK_CHAR_LIMIT=1200
VISION_ENABLED=false
LLM_TIMEOUT=45
STREAM_EMIT_CHAR_THRESHOLD=80
```

说明：

- 如果部署在 CPU 环境，优先压低 rerank 候选数。
- 如果部署在 GPU 环境，可以保留 rerank，但仍不建议盲目增大 query variants。
- 如果外部 LLM 响应不稳定，应优先关闭 fallback 重试逻辑，而不是继续加 worker。

## 4. 需要优先修复的工程问题

这些问题不一定是最大性能瓶颈，但会直接影响优化落地：

- `requirements.txt` 需要包含 `redis` 依赖，否则服务启动会失败。
- `RERANK_CANDIDATE_COUNT` 需要真正接入检索主流程，否则配置不可控。
- 启动阶段不应把所有外部依赖都作为强前置条件，至少要支持降级或延迟初始化。
- 文档元数据不建议长期继续使用 SQLite 承担并发读写。

## 5. 验证方式

每一轮优化都建议做固定压测，不要凭主观感觉判断：

- 场景 A：20 并发纯聊天，请求长度 50 到 150 字。
- 场景 B：聊天压测同时上传 2 个 100 页 PDF。
- 场景 C：外部 LLM 人为增加 2 秒延迟。
- 场景 D：Milvus 响应时间抖动到 500 ms。

观察指标：

- `/api/chat` P50、P95、错误率。
- `/api/chat/stream` 首包时间。
- worker 索引吞吐。
- CPU、内存、GPU 利用率。
- Redis/MySQL/Milvus 的平均 RTT。

## 6. 预期实施顺序

建议按下面顺序推进：

1. 先做指标和日志补齐。
2. 收紧 query rewrite、召回数量和 rerank 数量。
3. 把文档索引迁移到独立 worker。
4. 再做存储、缓存和异步化改造。

这个顺序的原因很直接：前两步最便宜、见效最快，第三步解决系统性资源争用，第四步才适合做更深层的工程优化。
