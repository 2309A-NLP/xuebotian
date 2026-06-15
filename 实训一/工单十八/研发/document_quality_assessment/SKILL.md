---
name: document-quality-assessment
description: "Use this skill when the user wants to assess document quality for a knowledge base. This includes: analyzing file format distribution (PDF, DOCX, MD, etc.); detecting PDF type (text-based vs scanned); measuring document length distribution; finding duplicate files via MD5; detecting sensitive information (phone numbers, emails, IDs); and classifying documents into categories (Scan_PDF, Text_PDF, DOCX, Markdown, etc.). Trigger when the user mentions 'document quality assessment', 'knowledge base audit', 'document inspection', 'data quality check', or 'file validation' for document collections."
---

# Document Quality Assessment Skill

Assess document quality for knowledge base building. This skill provides comprehensive analysis including format statistics, PDF type detection, length distribution, duplicate detection, and sensitive information scanning.

## Overview

Before building a domain-specific knowledge base, documents need quality assessment. This skill evaluates documents and produces actionable reports with "pending confirmation" lists for human review.

## Core Workflow

1. **Scan Input Directory**: Recursively find all supported document files
2. **Format Distribution**: Count and percentage by file type
3. **PDF Type Detection**: Classify each PDF as text-based, scanned, or mixed
4. **Length Analysis**: Calculate character count statistics and percentiles
5. **Duplicate Detection**: Find exact duplicates via MD5, flag similar documents
6. **Sensitive Info Scan**: Detect PII with context (phone, email, ID numbers)
7. **Document Classification**: Assign tags based on analysis results
8. **Generate Report**: Output structured JSON and HTML report

## File Types Supported

- PDF (.pdf)
- Word (.docx)
- Markdown (.md)
- Text (.txt)
- Excel (.xlsx, .xls)
- PowerPoint (.pptx, .ppt)

## Step-by-Step Implementation

### Step 1: Scan Directory for Documents

```python
import os
from pathlib import Path
from typing import List, Dict

SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.md', '.txt', '.xlsx', '.xls', '.pptx', '.ppt'}

def scan_documents(directory: str) -> List[Dict]:
    """Recursively scan directory for supported documents."""
    documents = []
    for root, _, files in os.walk(directory):
        for file in files:
            ext = Path(file).suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                full_path = os.path.join(root, file)
                documents.append({
                    'path': full_path,
                    'name': file,
                    'extension': ext,
                    'size': os.path.getsize(full_path)
                })
    return documents
```

### Step 2: Format Distribution Statistics

```python
from collections import Counter

def format_distribution(documents: List[Dict]) -> Dict:
    """Calculate format distribution statistics."""
    ext_counts = Counter(doc['extension'] for doc in documents)
    total = len(documents)
    
    return {
        'total_documents': total,
        'distribution': {
            ext: {
                'count': count,
                'percentage': round(count / total * 100, 2)
            }
            for ext, count in ext_counts.items()
        }
    }
```

### Step 3: PDF Type Detection

PDFs are classified into three types:
- **Text-based**: Extractable text on most pages
- **Scanned**: Images requiring OCR
- **Mixed**: Combination of both

Detection logic: Count characters per page. If a page has fewer than `CHAR_THRESHOLD` characters, it's considered a scanned page. If scanned pages exceed `SCAN_THRESHOLD` (default 70%), the file is marked as scanned.

```python
import pdfplumber
from typing import Tuple

CHAR_THRESHOLD = 100  # Characters per page to be considered text-based
SCAN_THRESHOLD = 0.7  # Percentage of scanned pages to mark as scanned

def detect_pdf_type(pdf_path: str) -> Tuple[str, float, List[Dict]]:
    """
    Detect PDF type and return classification.
    Returns: (type, scan_ratio, page_details)
    """
    page_details = []
    scanned_pages = 0
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ''
                char_count = len(text.strip())
                is_scanned = char_count < CHAR_THRESHOLD
                
                if is_scanned:
                    scanned_pages += 1
                
                page_details.append({
                    'page': i + 1,
                    'char_count': char_count,
                    'is_scanned': is_scanned
                })
            
            scan_ratio = scanned_pages / total_pages if total_pages > 0 else 0
            
            if scan_ratio >= SCAN_THRESHOLD:
                pdf_type = 'scanned'
            elif scan_ratio > 0:
                pdf_type = 'mixed'
            else:
                pdf_type = 'text'
                
    except Exception as e:
        pdf_type = 'error'
        scan_ratio = 0
        page_details = [{'error': str(e)}]
    
    return pdf_type, scan_ratio, page_details
```

### Step 4: Document Length Distribution

```python
import statistics

def calculate_length_distribution(documents: List[Dict]) -> Dict:
    """Calculate document length statistics."""
    lengths = [doc.get('char_count', 0) for doc in documents if doc.get('char_count')]
    
    if not lengths:
        return {'error': 'No length data available'}
    
    sorted_lengths = sorted(lengths)
    n = len(sorted_lengths)
    
    def percentile(p):
        idx = int(n * p)
        return sorted_lengths[min(idx, n - 1)]
    
    # Length buckets
    buckets = {
        '0-1K': sum(1 for l in lengths if l < 1000),
        '1K-10K': sum(1 for l in lengths if 1000 <= l < 10000),
        '10K-100K': sum(1 for l in lengths if 10000 <= l < 100000),
        '100K-1M': sum(1 for l in lengths if 100000 <= l < 1000000),
        '1M+': sum(1 for l in lengths if l >= 1000000)
    }
    
    return {
        'count': n,
        'percentiles': {
            'P25': percentile(0.25),
            'P50': percentile(0.50),
            'P75': percentile(0.75),
            'P90': percentile(0.90),
            'P99': percentile(0.99)
        },
        'distribution': {
            'mean': statistics.mean(lengths),
            'median': statistics.median(lengths),
            'min': min(lengths),
            'max': max(lengths),
            'stdev': statistics.stdev(lengths) if len(lengths) > 1 else 0
        },
        'buckets': buckets
    }
```

### Step 5: MD5 Duplicate Detection

```python
import hashlib

def calculate_md5(file_path: str) -> str:
    """Calculate MD5 hash of a file."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return ''

def find_duplicates(documents: List[Dict]) -> Dict:
    """Find duplicate files by MD5 hash."""
    hash_map = {}
    
    for doc in documents:
        file_hash = calculate_md5(doc['path'])
        if file_hash:
            if file_hash not in hash_map:
                hash_map[file_hash] = []
            hash_map[file_hash].append(doc)
    
    duplicates = {
        hash_val: files 
        for hash_val, files in hash_map.items() 
        if len(files) > 1
    }
    
    return {
        'duplicate_groups': len(duplicates),
        'duplicate_files': sum(len(f) - 1 for f in duplicates.values()),
        'groups': [
            {
                'hash': hash_val,
                'count': len(files),
                'files': [{'path': f['path'], 'name': f['name']} for f in files]
            }
            for hash_val, files in duplicates.items()
        ]
    }
```

### Step 6: Sensitive Information Detection

Detects:
- Phone numbers (mobile and landline, Chinese format)
- Email addresses
- ID numbers (Chinese ID cards)
- Bank card numbers (optional, disabled by default)

```python
import re
from typing import List, Dict, Tuple

def detect_sensitive_info(text: str, context_chars: int = 50) -> List[Dict]:
    """
    Detect sensitive information with surrounding context.
    Returns list of matches with context.
    """
    patterns = {
        'phone_mobile': r'(?:1[3-9]\d{9})',
        'phone_landline': r'(?:0\d{2,3}-?\d{7,8}|\d{3,4}-?\d{7,8})',
        'email': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        'id_card': r'\b([1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])\b',
        'bank_card': r'\b([2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})\b'
    }
    
    results = []
    
    for info_type, pattern in patterns.items():
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - context_chars)
            end = min(len(text), match.end() + context_chars)
            context = text[start:end].replace('\n', ' ').strip()
            
            results.append({
                'type': info_type,
                'value': match.group(),
                'context': f'...{context}...',
                'position': match.start()
            })
    
    return results

def scan_documents_for_sensitive_info(documents: List[Dict], 
                                       enabled_types: List[str] = None) -> Dict:
    """Scan all documents for sensitive information."""
    if enabled_types is None:
        enabled_types = ['phone_mobile', 'phone_landline', 'email', 'id_card']
    
    all_findings = []
    
    for doc in documents:
        if doc['extension'] == '.pdf':
            try:
                with pdfplumber.open(doc['path']) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text() or ''
                        findings = detect_sensitive_info(text)
                        for f in findings:
                            f['document'] = doc['path']
                            f['page'] = page.page_number
                            all_findings.append(f)
            except Exception:
                continue
        elif doc['extension'] in ['.txt', '.md']:
            try:
                with open(doc['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                    findings = detect_sensitive_info(text)
                    for f in findings:
                        f['document'] = doc['path']
                        f['page'] = None
                        all_findings.append(f)
            except Exception:
                continue
    
    # Group by type
    by_type = {}
    for finding in all_findings:
        t = finding['type']
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(finding)
    
    return {
        'total_findings': len(all_findings),
        'by_type': {
            t: {
                'count': len(items),
                'items': items
            }
            for t, items in by_type.items()
        }
    }
```

### Step 7: Document Classification

Assigns one or more tags based on analysis:

| Tag | Description | Criteria |
|-----|-------------|----------|
| Scan_PDF | Scanned PDF | scan_ratio >= 70% |
| Text_PDF | Text-based PDF | scan_ratio < 70% |
| Mixed_PDF | Mixed PDF | 0 < scan_ratio < 70% |
| DOCX | Word document | extension == .docx |
| Markdown | Markdown file | extension == .md |
| Short_Doc | Short document | char_count < 1000 |
| Long_Doc | Long document | char_count > 100000 |
| Duplicate | Exact duplicate | MD5 match found |
| Sensitive | Contains PII | Sensitive info detected |
| Pending_OCR | Needs OCR | Scan_PDF + no existing OCR |

```python
def classify_document(doc: Dict, analysis_results: Dict) -> List[str]:
    """Classify a document based on analysis results."""
    tags = []
    
    # PDF type
    if doc['extension'] == '.pdf':
        if doc.get('pdf_type') == 'scanned':
            tags.append('Scan_PDF')
        elif doc.get('pdf_type') == 'mixed':
            tags.append('Mixed_PDF')
        else:
            tags.append('Text_PDF')
    
    # File type
    elif doc['extension'] == '.docx':
        tags.append('DOCX')
    elif doc['extension'] == '.md':
        tags.append('Markdown')
    elif doc['extension'] in ['.xlsx', '.xls']:
        tags.append('Excel')
    elif doc['extension'] in ['.pptx', '.ppt']:
        tags.append('PowerPoint')
    
    # Length
    char_count = doc.get('char_count', 0)
    if char_count < 1000:
        tags.append('Short_Doc')
    elif char_count > 100000:
        tags.append('Long_Doc')
    
    # Duplicate
    if doc.get('is_duplicate'):
        tags.append('Duplicate')
    
    # Sensitive
    if doc.get('has_sensitive'):
        tags.append('Sensitive')
    
    return tags
```

### Step 8: Generate Report

```python
import json
from datetime import datetime

def generate_report(analysis_results: Dict) -> Dict:
    """Generate comprehensive assessment report."""
    report = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'version': '1.0'
        },
        'summary': {
            'total_documents': analysis_results['format_stats']['total_documents'],
            'total_size_mb': round(sum(d['size'] for d in analysis_results['documents']) / 1024 / 1024, 2)
        },
        'format_distribution': analysis_results['format_stats'],
        'pdf_analysis': analysis_results['pdf_types'],
        'length_distribution': analysis_results['length_stats'],
        'duplicates': analysis_results['duplicates'],
        'sensitive_info': analysis_results['sensitive_info'],
        'documents': [
            {
                'path': doc['path'],
                'tags': classify_document(doc, analysis_results)
            }
            for doc in analysis_results['documents']
        ],
        'pending_confirmations': {
            'scan_pdf_list': [
                {'path': d['path'], 'scan_ratio': d.get('scan_ratio', 0)}
                for d in analysis_results['documents']
                if d.get('pdf_type') in ['scanned', 'mixed']
            ],
            'duplicate_groups': analysis_results['duplicates']['groups'],
            'sensitive_findings': analysis_results['sensitive_info']['by_type']
        }
    }
    
    return report
```

## Main Entry Point

```python
def assess_documents(directory: str, config: Dict = None) -> Dict:
    """
    Main function to assess document quality.
    
    Args:
        directory: Path to documents directory
        config: Optional configuration overrides
        
    Returns:
        Comprehensive assessment report
    """
    config = config or {}
    
    # Scan documents
    documents = scan_documents(directory)
    
    # Analyze each document
    for doc in documents:
        if doc['extension'] == '.pdf':
            pdf_type, scan_ratio, page_details = detect_pdf_type(doc['path'])
            doc['pdf_type'] = pdf_type
            doc['scan_ratio'] = scan_ratio
            doc['page_details'] = page_details
            
            # Estimate character count
            char_count = sum(p.get('char_count', 0) for p in page_details)
            doc['char_count'] = char_count
        else:
            # For non-PDF, estimate based on file size
            doc['char_count'] = doc['size'] // 2  # Rough estimate
    
    # Run analyses
    analysis_results = {
        'documents': documents,
        'format_stats': format_distribution(documents),
        'pdf_types': analyze_pdf_types(documents),
        'length_stats': calculate_length_distribution(documents),
        'duplicates': find_duplicates(documents),
        'sensitive_info': scan_documents_for_sensitive_info(documents)
    }
    
    # Generate report
    report = generate_report(analysis_results)
    
    return report
```

## Configuration

The following parameters are configurable via `assessment_config.yaml`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| scan_threshold | 0.7 | PDF scanned page ratio threshold |
| char_threshold | 100 | Characters per page to be text-based |
| context_chars | 50 | Context characters around sensitive info |
| enabled_sensitive_types | phone_mobile, phone_landline, email, id_card | Types to detect |
| supported_extensions | .pdf, .docx, .md, .txt, .xlsx, .xls, .pptx, .ppt | File types to scan |

## Output Format

The assessment produces:

1. **JSON Report**: Complete structured data
2. **HTML Summary**: Human-readable report with:
   - Summary statistics
   - Format pie chart
   - PDF type breakdown
   - Pending confirmation lists
   - Actionable recommendations

## Performance Considerations

For large document sets (1000+ files):

1. **Progress Feedback**: Report progress every 100 files
2. **Interrupt Support**: Save state periodically, allow resume
3. **Parallel Processing**: Use multiprocessing for CPU-bound tasks
4. **Streaming**: Process large PDFs in chunks

```python
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

def assess_documents_parallel(directory: str, workers: int = 4) -> Dict:
    """Parallel document assessment for better performance."""
    documents = scan_documents(directory)
    
    results = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_document, doc): doc for doc in documents}
        
        for future in tqdm(as_completed(futures), total=len(futures)):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"Error processing document: {e}")
    
    return results
```

## Error Handling

- **Corrupted PDFs**: Log error, mark as 'error', continue processing
- **Inaccessible files**: Log permission error, skip file
- **Memory issues**: Process large PDFs in chunks
- **Timeout**: Set per-file timeout, skip if exceeded

## Integration with RAGFlow

This skill can be called from:
1. **API Endpoint**: `POST /v1/document/quality-inspection`
2. **Agent Workflow**: Via `DocumentQualityAssessmentSkill` tool
3. **Standalone**: Direct Python import

## Examples

### Basic Usage

```python
from document_quality_assessment import assess_documents

report = assess_documents('/path/to/documents')
print(json.dumps(report, indent=2, ensure_ascii=False))
```

### With Custom Config

```python
config = {
    'scan_threshold': 0.5,
    'char_threshold': 50,
    'enabled_sensitive_types': ['phone_mobile', 'email']
}

report = assess_documents('/path/to/documents', config=config)
```

### CLI Usage

```bash
python assess.py /path/to/documents --output report.json --format html
```
