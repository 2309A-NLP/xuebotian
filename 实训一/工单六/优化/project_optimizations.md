# 项目已完成优化点

本文只描述当前代码里已经落地的优化，不写规划项。

## 1. 文档解析与入库链路

- 大 PDF 自动分片解析。`app/services/document/mineru_parser.py` 会按 `MINERU_MAX_PAGES_PER_FILE` 切分 PDF，降低单次解析失败率，也绕开第三方解析接口的页数限制。
- 解析失败时做清理回滚。`app/services/document/manager.py` 在异常分支会删除当前文档的向量数据、解析文件和调试目录，避免脏数据残留。
- 解析中间产物可追踪。MinerU 原始返回、展开后的 `content_list`、压缩包和 `manifest.json` 都会落到 `data/mineru_debug`，问题定位成本显著降低。
- 解析文本做统一清洗。`TextCleaner` 会处理页面正文、表格标题、表格单元格和上下文文本，减少水印、噪声和重复内容对后续召回的干扰。
- 跨页表格做合并。`merge_cross_page_tables` 会把分页断开的表格拼回一张逻辑表，避免问答时命中残缺行。
- 图片信息进入知识库。`PdfImageDescriber` 会对 MinerU 提取到的图片做描述，随后 `DocumentChunker` 把图片作为独立 chunk 入库，补齐图表和流程图问答能力。
- 分模态切块。`DocumentChunker` 把正文、表格、图片拆成不同类型的 chunk，并在元数据里记录结构信息，方便后续按类型排序和补召回。
- 重建索引前先删旧向量。`DocumentService` 重新处理同一文档时会先执行 `delete_by_doc_id`，避免重复 chunk 堆积。

## 2. 检索召回与排序

- 查询改写是历史感知的。`app/services/rag/pipeline_query.py` 会读取最近会话，把代词、省略信息和上下文补全到改写查询里。
- 查询改写有安全约束。改写逻辑会保留年份、数字、否定词、组织名和图表锚点，避免 LLM 把问题改“跑偏”。
- 多查询并行召回。`RagPipeline.answer` 和 `stream_answer` 会对多个 query variant 同时向量化，再统一合并结果，提升召回覆盖率。
- 稠密检索和关键词检索融合。`MilvusVectorStore.search` 在支持 BM25 的情况下会做 dense + keyword 检索，并用加权 RRF 融合结果，减少只靠向量召回导致的字段遗漏。
- 召回池做了放宽。`pipeline_retrieval.py` 先拉大 `candidate_top_k` 与 rerank 候选池，再进入精排，避免好证据在前置阶段被截断。
- 排序不是只看向量分。`pipeline_ranking.py` 会根据标题、章节、文档名、是否列表块、表格标题、表头、图片 caption 等结构信号做加权排序。
- 面向图表和表格问题做特判。对于 `table_lookup`、`visual_lookup` 等意图，会主动提高表格和图片证据的排序权重。
- 最终结果补充多模态证据。`_append_modal_hits` 会在主结果之外补一个表格或图片证据，降低答案只有正文片段、缺失关键图表的情况。

## 3. Prompt 与回答质量

- 上下文不是无脑拼接。`pipeline_prompting.py` 会按 chunk 类型压缩上下文，对表格和图片优先保全，对长文本按关键词附近裁剪，减少 token 浪费。
- 对特殊表格做文本修复。`_repair_known_table_text` 会把部分关系表按结构化字段重新展开，改善表格类问题的可读性和抽取命中率。
- 证据不足时自动二次尝试。主回答命中“证据不足”短语后，会先做一次强制抽取式重试，再必要时退回原始问题重新检索和生成。
- 流式与非流式共享同一检索链路。这样两种接口的答案来源一致，减少“流式能答、非流式答偏”这类行为分叉。

## 4. 运行时与可维护性

- 启动时 warmup。`AppContainer.warmup()` 会提前加载 embedding 模型并触发向量库初始化，减少首问冷启动延迟。
- 会话历史放 Redis，并带 TTL。`ConversationHistoryService` 会按用户和会话存储历史，支持上下文问答，同时避免历史无限增长。
- MySQL 表自动初始化。`AuthService` 启动时会创建数据库和用户表，减少首次部署的手工初始化步骤。
- 请求链路带请求 ID。`app/main.py` 的中间件会统一打点请求开始、结束和状态码，方便日志串联。
- 配置集中管理。`app/core/config.py` 使用 `pydantic-settings`，把 LLM、Milvus、MySQL、Redis、MinerU、Vision、Speech 等配置集中到一处，部署和排障更直接。

## 5. 当前优化结论

- 这个项目已经不只是“上传 PDF 然后向量检索”的基础版实现，核心链路已经覆盖了解析容错、混合召回、结构化排序、多模态补证、上下文压缩和回答回退。
- 如果后续还要继续优化，优先级通常会落在部署自动化、依赖清单补齐、测试覆盖和观测指标，而不是再从零重写 RAG 主流程。
