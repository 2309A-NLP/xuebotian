# 文档质量评估 Skill 安装使用文档

## 1. 环境要求

推荐环境：

- Python 3.9 或更高版本。
- Windows、Linux、macOS 均可运行。
- 可选：RAGFlow 服务，用于通过 API 客户端远程调用。

当前本地脚本依赖：

```bash
pip install pyyaml pdfplumber requests pytest
```

说明：

- `pyyaml`：读取 `assessment_config.yaml`。
- `pdfplumber`：解析 PDF 文本并判断扫描件。
- `requests`：运行 `api_client.py` 时需要。
- `pytest`：运行单元测试时需要。

如果只扫描 TXT/MD 且不调用 API，可以暂不安装 `pdfplumber` 和 `requests`，但 PDF 分析和 API 客户端能力会受限。

## 2. Skill 安装

### 2.1 项目内使用

当前仓库已包含 skill：

```text
skill/document_quality_assessment/
```

在仓库根目录执行本地脚本即可：

```bash
python skill/document_quality_assessment/scripts/assess.py ./测试目录 --output ./报告/dqa_report.json --html ./报告/dqa_report.html
```

### 2.2 安装到 Codex Skills 目录

如果希望 Codex 自动发现该 skill，可以将目录复制到 Codex skills 目录。

Windows PowerShell 示例：

```powershell
$target = "$env:USERPROFILE\.codex\skills\document_quality_assessment"
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.codex\skills" | Out-Null
Copy-Item -Recurse -Force "skill\document_quality_assessment" $target
```

安装后目录应类似：

```text
C:\Users\<you>\.codex\skills\document_quality_assessment\SKILL.md
```

注意：skill 的 frontmatter 名称是 `document-quality-assessment`，触发时可用“document quality assessment”“knowledge base audit”“document inspection”“data quality check”“file validation”等意图描述。

## 3. 本地命令行使用

主入口：

```bash
python skill/document_quality_assessment/scripts/assess.py <文档目录> [选项]
```

常用参数：

- `--config, -c`：指定配置文件路径。
- `--output, -o`：输出 JSON 报告路径。
- `--html`：输出 HTML 报告路径。
- `--workers, -w`：并行处理进程数。

基础示例：

```bash
python skill/document_quality_assessment/scripts/assess.py ./测试目录
```

同时输出 JSON 和 HTML：

```bash
python skill/document_quality_assessment/scripts/assess.py ./测试目录 --output ./报告/dqa_report.json --html ./报告/dqa_report.html
```

使用自定义配置：

```bash
python skill/document_quality_assessment/scripts/assess.py ./测试目录 --config skill/document_quality_assessment/assessment_config.yaml --output ./报告/dqa_report.json
```

指定并行进程数：

```bash
python skill/document_quality_assessment/scripts/assess.py ./测试目录 --workers 4 --output ./报告/dqa_report.json --html ./报告/dqa_report.html
```

## 4. 配置说明

默认配置文件：

```text
skill/document_quality_assessment/assessment_config.yaml
```

常用配置：

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

performance:
  workers: 0
  file_timeout: 60
  progress_interval: 100
```

参数含义：

- `char_threshold`：PDF 单页抽取字符数低于该值时，该页被视为扫描页。
- `scan_threshold`：扫描页比例达到该值时，PDF 被视为扫描 PDF。
- `enabled_types`：报告中启用的敏感信息类型。
- `context_chars`：敏感信息命中点前后保留的上下文字符数。
- `workers`：并行进程数。当前 CLI 通过 `--workers` 覆盖该值。
- `progress_interval`：每处理多少文件回调一次进度。

注意：当前 `file_timeout`、`include_page_details`、`max_findings_per_category` 等配置在实现中尚未完整生效，属于后续优化项。

## 5. 输出报告

### 5.1 JSON 报告

JSON 报告包含：

- `metadata`：生成时间、版本和阈值。
- `summary`：总文档数、总大小。
- `format_distribution`：文件格式分布。
- `pdf_analysis`：PDF 类型统计和待确认扫描件。
- `length_distribution`：字符长度统计。
- `duplicates`：MD5 完全重复文件。
- `sensitive_info`：敏感信息命中。
- `documents`：每个文档的基础信息、字符数和标签。

### 5.2 HTML 报告

HTML 报告适合人工查看，包含：

- 总览卡片。
- 格式分布表。
- PDF 类型统计。
- 重复文件列表。
- 敏感信息列表。
- 文档摘要表。

建议将报告输出到独立目录，例如：

```text
报告/dqa_report.json
报告/dqa_report.html
```

不要将报告误放入待入库文档目录，避免后续被 RAG 系统当作文档摄入。

## 6. API 客户端使用

API 客户端入口：

```bash
python skill/document_quality_assessment/scripts/api_client.py [选项]
```

默认服务地址：

```text
http://localhost:9380
```

目录评估：

```bash
python skill/document_quality_assessment/scripts/api_client.py --base-url http://localhost:9380 --directory ./测试目录
```

指定文件评估：

```bash
python skill/document_quality_assessment/scripts/api_client.py --file ./测试目录/a.pdf --file ./测试目录/b.md
```

获取路由建议：

```bash
python skill/document_quality_assessment/scripts/api_client.py --routing --directory ./测试目录
```

获取 HTML 报告：

```bash
python skill/document_quality_assessment/scripts/api_client.py --html --directory ./测试目录 --output ./报告/api_report.html
```

认证方式：

```bash
python skill/document_quality_assessment/scripts/api_client.py --api-key your-api-key --directory ./测试目录
```

或使用环境变量：

```bash
set RAGFLOW_API_KEY=your-api-key
python skill/document_quality_assessment/scripts/api_client.py --directory ./测试目录
```

PowerShell：

```powershell
$env:RAGFLOW_API_KEY = "your-api-key"
python skill/document_quality_assessment/scripts/api_client.py --directory ./测试目录
```

## 7. 测试与验证

运行基础验证脚本：

```bash
python skill/document_quality_assessment/scripts/validate.py
```

运行 pytest 单元测试：

```bash
pytest skill/document_quality_assessment/scripts/test_assess.py -v
```

运行完整脚本并检查输出：

```bash
python skill/document_quality_assessment/scripts/assess.py ./测试目录 --output ./报告/dqa_report.json --html ./报告/dqa_report.html
```

验证重点：

- 是否成功发现文档。
- PDF 总数和分类是否合理。
- 重复文件是否符合预期。
- 敏感信息命中是否需要人工复核。
- HTML 报告是否能正常打开。

## 8. 常见问题

### 8.1 提示 `pdfplumber not installed`

安装依赖：

```bash
pip install pdfplumber
```

未安装时，PDF 类型会受限，可能输出 `unknown`。

### 8.2 没有发现文档

检查：

- 输入路径是否存在。
- 文件扩展名是否在 `supported_extensions` 中。
- 当前用户是否有目录读取权限。

### 8.3 Office 文档字符数不准

这是当前实现限制。DOCX、XLSX、PPTX 等格式目前按文件大小估算字符数，没有抽取真实文本。需要更准确结果时，应优先增加对应格式解析器。

### 8.4 敏感信息误报较多

建议：

- 在配置中关闭高误报类型，例如 `bank_card`。
- 降低报告暴露范围，只保留上下文供人工复核。
- 后续实现身份证校验位和银行卡 Luhn 校验。

### 8.5 并行处理没有明显加速

可能原因：

- 文件数量少于 10 时当前实现不会启用多进程。
- PDF 解析受 I/O 或单文件复杂度影响。
- `workers` 设置过高可能导致磁盘争用。

建议从 `--workers 2` 或 `--workers 4` 开始测试。

## 9. 推荐使用流程

标准知识库准入流程：

1. 将待入库文档放入独立目录。
2. 运行本地评估脚本，输出 JSON 和 HTML。
3. 人工查看 HTML 中的扫描件、重复文件和敏感信息。
4. 对扫描件执行 OCR 或人工确认。
5. 对重复文件执行保留、归档或删除策略。
6. 对敏感文件执行脱敏或权限隔离。
7. 将处理后的文档再进入 RAG 入库流程。

推荐命令：

```bash
python skill/document_quality_assessment/scripts/assess.py ./待入库文档 --workers 4 --output ./报告/dqa_report.json --html ./报告/dqa_report.html
```

