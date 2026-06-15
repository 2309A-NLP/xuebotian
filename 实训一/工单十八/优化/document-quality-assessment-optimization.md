# 文档质量评估 Skill 优化文档

## 1. 优化目标

当前 `document-quality-assessment` skill 已具备基础审计能力，但仍存在“设计能力大于真实实现”的情况。优化目标是让它从可运行脚本升级为可稳定用于知识库准入的质量评估组件。

总体目标：

- 提高真实文本抽取覆盖率。
- 降低敏感信息误报和漏报。
- 补齐配置项与实现之间的差距。
- 提升大批量文档处理的稳定性和可恢复性。
- 让输出结果更适合 RAG 入库路由和人工复核。

## 2. 当前问题清单

### 2.1 文档解析覆盖不足

现状：

- PDF 使用 `pdfplumber` 抽取文本。
- TXT、MD 直接读取文本。
- DOCX、DOC、XLSX、XLS、PPTX、PPT 只按文件大小估算字符数。

影响：

- 非 PDF Office 文档长度统计不准确。
- Office 文档中的敏感信息无法被检测。
- 分类标签无法反映解析质量。

优化建议：

- DOCX：引入 `python-docx` 抽取段落和表格文本。
- XLSX：引入 `openpyxl` 读取单元格文本。
- PPTX：引入 `python-pptx` 抽取文本框内容。
- DOC、XLS、PPT：优先提示转换为新格式，或通过 LibreOffice headless 转换后再抽取。

优先级：P0。

### 2.2 配置项未完全生效

现状：

- `enabled_sensitive_types` 只在汇总阶段过滤，扫描阶段仍匹配所有 `SENSITIVE_PATTERNS`。
- `file_timeout` 未实际控制单文件处理耗时。
- `include_page_details`、`max_findings_per_category` 未完整作用到报告输出。
- `duplicate_detection.use_simhash` 存在配置，但未实现相似文档检测。
- `length_analysis.buckets` 存在配置，但当前代码使用硬编码桶。

影响：

- 配置文件与行为不一致，用户难以预测结果。
- 大文件或异常 PDF 可能拖慢整体流程。
- 报告体积无法按配置控制。

优化建议：

- 在 `detect_sensitive_info()` 中传入启用类型，只匹配启用模式。
- 在多进程 future 上使用 timeout，串行模式可用 `signal` 或子进程隔离。
- 让报告生成读取 `report.include_page_details` 和 `report.max_findings_per_category`。
- 让长度桶完全来自配置。
- 未实现的配置项要么实现，要么从默认配置移除并写入路线图。

优先级：P0。

### 2.3 PDF 扫描件判断较粗糙

现状：

- 仅通过每页可抽取字符数判断是否扫描页。

影响：

- 图片 PDF、表格 PDF、低文本密度 PDF 容易误判。
- 带少量页眉页脚文本的扫描件可能被误判为 mixed 或 text。

优化建议：

- 增加页面图像对象数量、文本块数量、字体对象密度等辅助特征。
- 输出每页判定原因，便于人工复核。
- 对低字符但存在大量表格线或图片的页面增加置信度字段。
- 为 PDF 类型输出 `confidence`。

优先级：P1。

### 2.4 敏感信息检测准确性不足

现状：

- 使用正则直接匹配手机号、座机、邮箱、身份证、银行卡。
- 缺少校验位、上下文类型和误报抑制。

影响：

- 身份证和银行卡可能误报普通长数字。
- 手机号可能命中文档编号。
- 缺少风险等级，人工复核成本高。

优化建议：

- 身份证号加入日期合法性和校验位验证。
- 银行卡使用 Luhn 校验后再输出。
- 手机号增加中文上下文提示词加权，例如“电话”“手机”“联系方式”。
- 输出 `risk_level`：`high`、`medium`、`low`。
- 对命中值做掩码输出，例如 `138****1234`，完整值可作为可选开关。

优先级：P1。

### 2.5 重复检测只支持完全一致

现状：

- 使用 MD5 检测二进制完全相同文件。

影响：

- 内容相同但文件元数据不同的 PDF/DOCX 无法识别。
- 版本差异、格式转换后的重复无法发现。

优化建议：

- 增加文本归一化 hash：抽取文本后去空白、去页码、统一标点，再计算 hash。
- 实现 SimHash 或 MinHash，用于相似文档检测。
- 输出重复类型：`binary_exact`、`text_exact`、`near_duplicate`。
- 对相似重复组输出相似度和推荐保留文件。

优先级：P1。

### 2.6 报告缺少处置建议

现状：

- 报告主要提供统计和列表。
- 标签未包含 `Duplicate`、`Sensitive` 等关键处置类标签。

影响：

- 人工拿到报告后还需要二次判断下一步动作。
- 工作流难以直接基于标签路由。

优化建议：

- 在 `documents` 中加入 `issues` 和 `recommendations` 字段。
- 补齐标签：`Duplicate`、`Sensitive`、`Pending_OCR`、`Needs_Text_Extraction`。
- 输出全局建议：OCR 数量、去重节省空间、敏感信息复核优先级。

优先级：P1。

### 2.7 Skill 文档与实现存在偏差

现状：

- `SKILL.md` 描述了 `assess_documents()` 等示例入口，但当前 `assess.py` 没有该函数。
- `README.md` 描述了 SimHash、API workflow 等部分未完全实现能力。

影响：

- 使用者可能按文档调用不存在的 API。
- 维护者难以判断哪些能力已完成。

优化建议：

- 将 `SKILL.md` 保持为精简操作指引，把详细设计迁移到外部 docs。
- 明确区分“已实现”“计划中”“集成示例”。
- 如需 Python API，补一个真实 `assess_documents(directory, config=None)` 包装函数。

优先级：P0。

## 3. 优先级路线图

### P0：修正可用性与一致性

- 补真实 Python API：`assess_documents()`。
- 让敏感信息启用类型在扫描阶段生效。
- 让配置中的长度桶、报告限制、page details 生效。
- 修正文档中与真实实现不一致的示例。
- 增加依赖说明和最小安装命令。

验收标准：

- README、安装文档和 CLI 行为一致。
- `python scripts/validate.py` 通过。
- 对 TXT、MD、PDF 的报告字段稳定输出。

### P1：提升质量评估准确性

- 增加 DOCX、XLSX、PPTX 文本抽取。
- 身份证校验位和银行卡 Luhn 校验。
- PDF 判定加入置信度。
- 补齐 `Duplicate`、`Sensitive`、`Pending_OCR` 标签。
- 增加文本级重复检测。

验收标准：

- Office 文档可以输出真实字符数。
- 敏感信息误报率明显降低。
- 文档标签可以直接驱动 RAG 入库路由。

### P2：增强大规模处理能力

- 单文件超时控制。
- 增量扫描缓存。
- 断点续跑。
- 批处理进度状态文件。
- HTML 报告分页或按问题类型分段。

验收标准：

- 1000+ 文件处理可恢复。
- 单个坏文件不会拖垮整批任务。
- 报告体积可控。

### P3：产品化与集成

- RAGFlow 后端接口和本地脚本共享核心分析模块。
- 输出 routing recommendations 标准 schema。
- 增加 CSV/Excel 导出。
- 提供前端可视化筛选页面。

验收标准：

- 本地 CLI、API 和 Agent tool 输出 schema 一致。
- 可直接将报告结果导入后续清洗工作流。

## 4. 建议重构方案

当前 `assess.py` 集中了扫描、解析、统计、报告和 CLI。建议拆分为：

```text
scripts/
  assess.py              # CLI thin wrapper
  dqa/
    __init__.py
    config.py            # load_config, defaults, schema validation
    scanner.py           # scan_documents
    extractors.py        # pdf/txt/md/docx/xlsx/pptx text extraction
    detectors.py         # pdf type, sensitive info, duplicate
    analyzer.py          # process_document, analyze_documents
    report.py            # generate_report, generate_html_report
    schemas.py           # typed dict/dataclass/pydantic models
```

收益：

- CLI、API 客户端和测试可以复用同一核心模块。
- 单元测试更聚焦。
- 后续新增格式解析器时不影响主流程。
- 配置和 schema 更容易校验。

## 5. 质量保障建议

测试用例应覆盖：

- 空目录。
- 仅 TXT/MD。
- PDF text、scanned、mixed、error。
- DOCX/XLSX/PPTX 文本抽取。
- 重复文件和近重复文件。
- 身份证校验位正确和错误。
- 银行卡 Luhn 正确和错误。
- 配置禁用某类敏感信息。
- `max_findings_per_category` 截断。
- 单文件异常不中断批处理。

性能测试建议：

- 100 个小文件。
- 1000 个混合文件。
- 单个超大 PDF。
- 损坏 PDF。
- 多进程和单进程结果一致性。

## 6. 安全与合规优化

建议默认策略：

- 报告中敏感值默认掩码。
- 完整敏感值仅在显式配置 `include_raw_sensitive_values: true` 时输出。
- HTML 报告增加“敏感信息报告，请勿外传”提示。
- 输出目录默认不放在原始文档目录内，避免误上传到知识库。

建议报告字段：

```json
{
  "type": "id_card",
  "masked_value": "110101********123X",
  "risk_level": "high",
  "context": "...身份证号 110101********123X ...",
  "document": "...",
  "page": 3
}
```

## 7. 文档优化建议

skill 包本体应保持轻量，避免把大量面向人的设计和安装说明塞入 `SKILL.md`。建议：

- `SKILL.md`：只保留触发后执行任务所需的核心流程和资源导航。
- `README.md`：保留简短功能说明和快速开始。
- `docs/document-quality-assessment-design.md`：维护设计细节。
- `docs/document-quality-assessment-optimization.md`：维护路线图和技术债。
- `docs/document-quality-assessment-installation-usage.md`：维护安装、运行和排错。

这样既符合 skill 的渐进式披露原则，也方便项目成员阅读完整文档。

