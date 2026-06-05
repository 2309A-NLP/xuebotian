# 项目已完成优化点

## 1. RAG 检索链路优化

项目在 `app/services/rag/pipeline.py` 中已经实现了多阶段检索增强，不再只依赖单次向量召回：

- 查询预处理：通过 `IntentAnalyzer` 对用户问题做归一化与意图识别。
- 查询改写：开启 `QUERY_REWRITE_ENABLED` 后，使用大模型生成多个检索表达，提高召回覆盖率。
- 多路召回：同时使用 BGE-m3 向量检索、Milvus BM25 混合检索、Parsed JSON 关键词检索。
- 候选扩展：使用 `RECALL_CANDIDATE_COUNT` 拉大候选集，再进入后续排序。
- RRF 融合：Milvus 支持稠密向量与 BM25 稀疏检索融合，提升关键词型问题命中率。
- BGE 重排序：通过 `BgeReranker` 对候选片段进行二次排序，减少相似但不相关的片段。
- 业务特征加权：对表格、公司名称、年份、金额、控制关系、募集资金等字段做额外加权。
- 原问题兜底重试：当回答出现“未检索到充分依据”时，会使用原始问题重新召回并生成答案。

## 2. 文档解析与切分优化

项目在 PDF 入库阶段已经做了针对招股书、公告类 PDF 的结构化处理：

- 表格区域剔重：正文抽取时排除表格区域，避免正文和表格重复入库。
- 表格标题识别：识别表格上方标题，作为表格 chunk 的上下文。
- 跨页表格合并：通过 `merge_cross_page_tables` 合并跨页连续表格。
- 表格结构序列化：将表头、行数据、页码范围序列化为可检索文本。
- 语义切分：正文按章节、标题、列表项和句子进行切分，而不是固定硬切。
- chunk 去重：根据内容签名去除重复片段，降低冗余召回。
- overlap 保留：使用 `CHUNK_OVERLAP` 保留上下文，缓解切分边界丢信息问题。

## 3. 数据清洗优化

`TextCleaner` 已对 PDF 常见噪声做清理：

- 支持配置化水印去除，水印词由 `WATERMARK_PATTERNS` 控制。
- 自动识别页眉、页脚、页码等重复 boilerplate 行。
- 合并 PDF 抽取造成的断行。
- 清洗表格单元格内部换行和多余空白。
- 统一空白格式，提升 embedding 和关键词匹配效果。

## 4. 向量库与存储优化

项目已封装 Milvus 与本地内存两套向量存储实现：

- `VECTOR_BACKEND=milvus` 支持生产部署。
- `VECTOR_BACKEND=memory` 支持轻量调试。
- Milvus collection 自动建表、建索引、load collection。
- 支持按文档 ID 删除向量，避免删除文档后残留旧 chunk。
- metadata 使用 JSON 存储，并对过长字段做压缩，避免超过 Milvus 字段长度。
- SQLite 保存文档元数据，Parsed JSON 保存解析结果，便于排查与重复使用。

## 5. 问答体验优化

前后端已经实现了较完整的问答交互能力：

- `/api/chat/stream` 使用 SSE 流式输出，降低用户等待感。
- 流式接口先返回 meta 信息，包括归一化问题、意图、引用片段。
- 前端使用 requestAnimationFrame 批量刷新 token，减少频繁 DOM 更新。
- 回答结果附带引用页码、文件名、片段类型和分数，便于核验来源。
- 支持按文档筛选问答范围。
- 支持语音输入，前端录音后调用 `/api/speech/transcribe` 转写。

## 6. 工程结构优化

项目结构已经按职责拆分，后续扩展成本较低：

- API 层、Service 层、Core 层、Schema 层分离。
- `AppContainer` 统一装配依赖，便于替换向量库、LLM、解析器等组件。
- 配置集中在 `.env` 与 `Settings`，支持不同环境部署。
- 统一异常处理与请求日志记录。
- 启动时 warmup embedding 模型和向量库，减少首次请求冷启动影响。

