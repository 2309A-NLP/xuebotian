# 文档质量评估 Skill 设计文档

## 1. 背景与目标

`document-quality-assessment` skill 面向知识库建设前的数据准入检查。它用于递归扫描文档集合，输出格式分布、PDF 类型、文档长度、重复文件、敏感信息和分类标签等结果，帮助后续 RAG 入库前完成数据清洗、人工复核和解析路由。

核心目标：

- 在入库前发现低质量、重复、扫描件和敏感信息文档。
- 为 OCR、解析器选择、脱敏、去重等后续流程提供结构化依据。
- 同时提供 JSON 机器可读报告和 HTML 人工审阅报告。

非目标：

- 不直接执行 OCR。
- 不直接修改、删除、脱敏原始文件。
- 不替代人工合规审核，只提供待确认证据列表。

## 2. 目录结构

当前 skill 位于：

```text
skill/document_quality_assessment/
  SKILL.md
  README.md
  assessment_config.yaml
  scripts/
    assess.py
    api_client.py
    validate.py
    test_assess.py
    test_folder.py
    test_skill.py
    __init__.py
  references/
```

关键文件职责：

- `SKILL.md`：Codex 触发 skill 后读取的主要操作说明，包含工作流、算法示例和集成说明。
- `assessment_config.yaml`：默认阈值、支持扩展名、敏感信息类型、性能参数和报告配置。
- `scripts/assess.py`：本地扫描、分析和报告生成主入口。
- `scripts/api_client.py`：调用 RAGFlow 文档质量检查 API 的客户端。
- `scripts/validate.py`、`scripts/test_*.py`：用于基础功能验证和测试。

## 3. 功能边界

已实现能力：

- 递归扫描 `.pdf`、`.docx`、`.doc`、`.md`、`.txt`、`.xlsx`、`.xls`、`.pptx`、`.ppt`。
- 统计文档格式数量和百分比。
- 使用 `pdfplumber` 判断 PDF 页面是否具备可抽取文本，并归类为 `text`、`mixed`、`scanned`、`error` 或 `unknown`。
- 统计字符长度分布，包括 P25、P50、P75、P90、P99 和长度区间。
- 使用 MD5 检测完全重复文件。
- 对 PDF、TXT、MD 的可抽取文本检测手机号、座机、邮箱、身份证号和银行卡号。
- 生成 JSON 报告和 HTML 报告。
- 通过 API 客户端调用远程质量检查、路由建议和 HTML 报告接口。

当前限制：

- DOCX、DOC、XLSX、XLS、PPTX、PPT 当前只按文件大小估算字符数，不抽取真实文本。
- 敏感信息配置只在汇总阶段过滤类型，底层正则仍会先扫描全部内置类型。
- `file_timeout` 配置存在但当前本地处理未实际强制超时。
- `include_page_details`、`max_findings_per_category`、SimHash 相似检测等配置尚未完整落地。
- `SKILL.md` 中部分 Python API 示例属于设计说明，不完全等同当前 `assess.py` 的真实导出接口。

## 4. 核心流程

整体流程：

```text
输入目录
  -> scan_documents()
  -> analyze_documents()
      -> process_document()
          -> PDF: detect_pdf_type() + extract_text sensitive scan + md5
          -> TXT/MD: read text + sensitive scan + md5
          -> Other: size-based char_count estimate + md5
  -> generate_report()
      -> format_distribution()
      -> pdf_type_summary()
      -> length_distribution()
      -> find_duplicates()
      -> sensitive_info_summary()
      -> classify_document()
  -> JSON / HTML output
```

### 4.1 扫描阶段

`scan_documents(directory, supported_extensions)` 使用 `os.walk` 递归扫描目录，根据扩展名过滤受支持文件，并记录：

- `path`
- `name`
- `extension`
- `size`
- `relative_path`

### 4.2 单文档分析阶段

`process_document(doc, config)` 是单文件处理单元：

- PDF：用 `pdfplumber` 按页抽取文本，统计字符数和扫描页比例。
- TXT/MD：以 UTF-8 读取文本，失败字符忽略。
- 其他格式：用 `size // 2` 粗略估算字符数。
- 所有格式：计算 MD5。

### 4.3 PDF 类型判断

判断参数来自 `pdf_detection`：

- `char_threshold`：单页字符数低于该值则视为扫描页。
- `scan_threshold`：扫描页占比达到该值则视为扫描 PDF。

分类规则：

- `scanned`：扫描页比例大于等于阈值。
- `mixed`：扫描页比例大于 0 且低于阈值。
- `text`：扫描页比例等于 0。
- `error`：解析异常。
- `unknown`：缺少 `pdfplumber`。

### 4.4 统计与报告阶段

`generate_report()` 汇总输出：

- `metadata`：生成时间、版本和核心阈值。
- `summary`：文档数量、总大小。
- `format_distribution`：格式分布。
- `pdf_analysis`：PDF 类型分布和待确认扫描件列表。
- `length_distribution`：长度统计。
- `duplicates`：MD5 重复组。
- `sensitive_info`：敏感信息按类型聚合。
- `documents`：单文档摘要和分类标签。

HTML 报告由 `generate_html_report()` 基于 JSON 报告渲染，主要用于人工查看。

## 5. 配置设计

配置入口为 `assessment_config.yaml`。

主要配置项：

```yaml
pdf_detection:
  char_threshold: 100
  scan_threshold: 0.7

sensitive_info:
  enabled_types:
    - phone_mobile
    - phone_landline
    - email
    - id_card
  context_chars: 50

supported_extensions:
  - .pdf
  - .docx
  - .doc
  - .md
  - .txt
  - .xlsx
  - .xls
  - .pptx
  - .ppt

performance:
  workers: 0
  file_timeout: 60
  progress_interval: 100
```

设计原则：

- 检测阈值外置，适应不同知识库文档质量差异。
- 敏感信息类型可开关，降低高误报类型对结果的干扰。
- 输出报告结构固定，便于被上游 API、工作流或人工审阅页面消费。

## 6. API 客户端设计

`scripts/api_client.py` 封装远程接口访问，默认服务地址为：

```text
http://localhost:9380
```

支持认证方式：

- `--api-key`
- `--token`
- 环境变量 `RAGFLOW_API_KEY`
- 环境变量 `RAGFLOW_TOKEN`

主要调用模式：

- 目录评估：`/api/v1/document/quality-inspection`
- 文件评估：同一客户端内封装为 specific files 模式。
- 路由建议：用于返回文档应进入 OCR、文本解析或人工确认等后续流程的建议。
- HTML 报告：用于生成可视化人工审阅结果。

## 7. 标签体系

当前 `classify_document()` 会输出以下标签：

- `Scan_PDF`
- `Mixed_PDF`
- `Text_PDF`
- `DOCX`
- `Markdown`
- `Excel`
- `PowerPoint`
- `Text`
- `Short_Doc`
- `Long_Doc`
- `Has_Error`

建议后续补齐：

- `Duplicate`
- `Sensitive`
- `Pending_OCR`
- `Parse_Estimated`

这些标签可以用于后续 RAG 入库策略，例如扫描件进入 OCR 队列，重复文件进入去重队列，敏感文件进入人工复核或脱敏流程。

## 8. 质量与安全设计

安全原则：

- 默认只读扫描，不修改原始文档。
- 敏感信息输出包含上下文，便于人工判断误报。
- 银行卡检测虽然有正则，但默认配置未启用，避免高误报。

容错原则：

- 单文件解析失败不终止整个目录分析。
- PDF 解析异常记录为 `error`。
- 文件不可访问时尽量跳过并保留错误信息。

性能原则：

- 文档数量大于 10 且 `workers > 1` 时启用多进程。
- MD5 采用分块读取，避免一次性加载大文件。
- PDF 按页处理，减少单次内存压力。

## 9. 集成建议

本地执行适合离线审计：

```bash
python skill/document_quality_assessment/scripts/assess.py ./docs -o report.json --html report.html
```

API 客户端适合接入已有 RAGFlow 服务：

```bash
python skill/document_quality_assessment/scripts/api_client.py --base-url http://localhost:9380 --directory ./docs
```

RAG 工作流中建议将报告结果映射为以下动作：

- `Scan_PDF` 或 `Mixed_PDF`：进入 OCR 或人工确认。
- `Has_Error`：进入异常文件队列。
- 重复组：保留主文件，其他文件待删除或归档。
- 敏感信息命中：进入脱敏或权限隔离流程。

