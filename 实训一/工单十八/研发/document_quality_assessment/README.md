# Document Quality Assessment Skill

## Overview

This skill provides comprehensive document quality assessment for knowledge base building in RAGFlow. It analyzes documents and produces actionable reports including format statistics, PDF type detection, length distribution, duplicate detection, and sensitive information scanning.

## Features

### 1. Format Distribution Statistics
- Counts and percentages for PDF, DOCX, MD, TXT, XLSX, PPTX and other supported formats
- Visual summary of document type composition

### 2. PDF Type Detection
- **Text-based PDFs**: Standard PDFs with extractable text
- **Scanned PDFs**: Image-based PDFs requiring OCR
- **Mixed PDFs**: Combination of text and scanned pages

Detection logic: If a page has fewer than `char_threshold` characters (default: 100), it's considered scanned. If scanned pages exceed `scan_threshold` (default: 70%), the file is marked as scanned.

### 3. Document Length Distribution
- Character count statistics (mean, median, min, max)
- Percentile analysis (P25, P50, P75, P90, P99)
- Length bucket distribution (0-1K, 1K-10K, 10K-100K, 100K-1M, 1M+)

### 4. Duplicate Detection
- **MD5 exact matching**: Identifies identical files
- **SimHash similarity** (optional): Identifies similar documents

### 5. Sensitive Information Detection
Detects:
- Mobile phone numbers (Chinese format: 1XX-XXXX-XXXX)
- Landline phone numbers
- Email addresses
- Chinese ID card numbers
- Bank card numbers (disabled by default due to high false positive rate)

All findings include surrounding context for human review.

### 6. Document Classification Tags

| Tag | Description |
|-----|-------------|
| Scan_PDF | Scanned PDF (scan_ratio >= 70%) |
| Text_PDF | Text-based PDF |
| Mixed_PDF | Mixed PDF |
| DOCX | Word document |
| Markdown | Markdown file |
| Excel | Spreadsheet file |
| Short_Doc | Document with < 1000 characters |
| Long_Doc | Document with > 100000 characters |
| Duplicate | Exact duplicate detected |
| Sensitive | Contains sensitive information |

## Directory Structure

```
document_quality_assessment/
├── SKILL.md                    # Main skill definition
├── assessment_config.yaml       # Configuration file
├── scripts/
│   ├── __init__.py
│   ├── assess.py              # Main assessment script
│   ├── test_assess.py         # Unit tests
│   └── validate.py             # Validation script
└── references/                # Reference documentation
```

## Usage

### Command Line

```bash
# Basic usage
python assess.py /path/to/documents

# With custom output
python assess.py /path/to/documents --output report.json --html report.html

# With custom configuration
python assess.py /path/to/documents --config custom_config.yaml

# With parallel workers
python assess.py /path/to/documents --workers 8
```

### Python API

```python
from assess import assess_documents

# Basic usage
report = assess_documents('/path/to/documents')
print(json.dumps(report, indent=2))

# With custom config
config = {
    'pdf_detection': {
        'char_threshold': 50,
        'scan_threshold': 0.5
    }
}
report = assess_documents('/path/to/documents', config=config)
```

### API Endpoint

```
POST /api/v1/document/quality-inspection
```

Request body:
```json
{
    "directory": "/path/to/documents",
    "return_html": true,
    "config": {
        "scan_threshold": 0.7,
        "char_threshold": 100
    }
}
```

Response:
```json
{
    "success": true,
    "data": {
        "metadata": {...},
        "summary": {...},
        "format_distribution": {...},
        "pdf_analysis": {...},
        "length_distribution": {...},
        "duplicates": {...},
        "sensitive_info": {...},
        "documents": [...]
    }
}
```

## Configuration

Edit `assessment_config.yaml` to customize behavior:

```yaml
# PDF Type Detection
pdf_detection:
  char_threshold: 100      # Characters per page for text detection
  scan_threshold: 0.7      # Scanned page ratio threshold

# Sensitive Information
sensitive_info:
  enabled_types:
    - phone_mobile
    - phone_landline
    - email
    - id_card
  context_chars: 50        # Context characters around findings

# Performance
performance:
  workers: 4                # Parallel workers (0 = auto)
  file_timeout: 60         # Seconds per file
  progress_interval: 100    # Progress report frequency
```

## Output

### JSON Report

```json
{
    "metadata": {
        "generated_at": "2026-01-23T10:00:00",
        "version": "1.0"
    },
    "summary": {
        "total_documents": 100,
        "total_size_mb": 250.5
    },
    "format_distribution": {
        "total_documents": 100,
        "distribution": {
            ".pdf": {"count": 80, "percentage": 80.0},
            ".docx": {"count": 15, "percentage": 15.0},
            ".md": {"count": 5, "percentage": 5.0}
        }
    },
    "pdf_analysis": {
        "total_pdfs": 80,
        "by_type": {
            "text": {"count": 50},
            "scanned": {"count": 20},
            "mixed": {"count": 10}
        },
        "pending_confirmation": [
            {"path": "...", "type": "scanned", "scan_ratio": 85.0}
        ]
    },
    "duplicates": {
        "duplicate_groups": 3,
        "duplicate_files": 5,
        "groups": [...]
    },
    "sensitive_info": {
        "total_findings": 15,
        "by_type": {...}
    }
}
```

### HTML Report

Generates a human-readable HTML report with:
- Summary statistics with visual indicators
- Format distribution table
- PDF type breakdown
- Pending confirmation lists
- Actionable recommendations

## Integration with RAGFlow

### Agent Tool

The skill is registered as `DocumentQualityAssessmentTool` for use in RAGFlow agents:

```python
from agent.tools.document_quality_assessment import DocumentQualityAssessmentTool

tool = DocumentQualityAssessmentTool()
result = tool.invoke(directory="/path/to/documents")
```

### Workflow

A pre-built workflow `document_quality_inspection_workflow.json` is included that:
1. Triggers quality assessment
2. Calls DocumentQualityAssessmentSkill
3. Routes documents to appropriate parsers based on classification

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/document/quality-inspection` | POST | Perform assessment |
| `/api/v1/document/quality-inspection/routing` | POST | Get routing recommendations |
| `/api/v1/document/quality-inspection/report` | POST | Get HTML report |

## Testing

```bash
# Run unit tests
pytest scripts/test_assess.py -v

# Run validation script
python scripts/validate.py
```

## Performance

- **Small datasets** (< 100 files): Single-threaded processing
- **Large datasets** (100+ files): Parallel processing with configurable workers
- **Progress feedback**: Reports progress every 100 files
- **Error handling**: Continues on individual file errors

## Limitations

1. **SimHash similarity detection**: Currently not implemented (can be added as extension)
2. **Bank card detection**: Disabled by default due to high false positive rate
3. **Password-protected PDFs**: Cannot be analyzed without decryption
4. **Corrupted files**: Logged and skipped

## License

Part of RAGFlow project. See project license.

## References

- [RAGFlow Project](https://github.com/infiniflow/ragflow)
- [Anthropic Skills Documentation](https://docs.anthropic.com/en/docs/claude-code/skills)
