#!/usr/bin/env python3
"""
Document Quality Assessment Script
Assess document quality for knowledge base building.
"""

import os
import sys
import json
import hashlib
import re
import argparse
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import Counter
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import yaml

try:
    import pdfplumber
except ImportError:
    print("Warning: pdfplumber not installed. PDF analysis will be limited.")
    pdfplumber = None


# Configuration defaults
DEFAULT_CONFIG = {
    'pdf_detection': {
        'char_threshold': 100,
        'scan_threshold': 0.7
    },
    'sensitive_info': {
        'enabled_types': ['phone_mobile', 'phone_landline', 'email', 'id_card'],
        'context_chars': 50
    },
    'supported_extensions': ['.pdf', '.docx', '.doc', '.md', '.txt', '.xlsx', '.xls', '.pptx', '.ppt'],
    'performance': {
        'workers': 4,
        'file_timeout': 60,
        'progress_interval': 100
    }
}

# Sensitive info patterns
SENSITIVE_PATTERNS = {
    'phone_mobile': r'(?:1[3-9]\d{9})',
    'phone_landline': r'(?:0\d{2,3}-?\d{7,8}|\d{3,4}-?\d{7,8})',
    'email': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    'id_card': r'\b([1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx])\b',
    'bank_card': r'\b([2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})\b'
}


def load_config(config_path: str = None) -> Dict:
    """Load configuration from YAML file."""
    config = DEFAULT_CONFIG.copy()

    if config_path and os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f)
            if user_config:
                # Deep merge
                for section, values in user_config.items():
                    if section in config and isinstance(config[section], dict):
                        config[section].update(values)
                    else:
                        config[section] = values

    return config


def scan_documents(directory: str, supported_extensions: List[str]) -> List[Dict]:
    """Recursively scan directory for supported documents."""
    documents = []

    for root, _, files in os.walk(directory):
        for file in files:
            ext = Path(file).suffix.lower()
            if ext in supported_extensions:
                full_path = os.path.join(root, file)
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0

                documents.append({
                    'path': full_path,
                    'name': file,
                    'extension': ext,
                    'size': size,
                    'relative_path': os.path.relpath(full_path, directory)
                })

    return documents


def calculate_md5(file_path: str) -> str:
    """Calculate MD5 hash of a file."""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return ''


def detect_pdf_type(pdf_path: str, config: Dict) -> Tuple[str, float, List[Dict]]:
    """
    Detect PDF type and return classification.
    Returns: (type, scan_ratio, page_details)
    """
    if pdfplumber is None:
        return ('unknown', 0, [])

    char_threshold = config['pdf_detection']['char_threshold']
    scan_threshold = config['pdf_detection']['scan_threshold']

    page_details = []
    scanned_pages = 0
    total_chars = 0

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)

            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ''
                char_count = len(text.strip())
                total_chars += char_count
                is_scanned = char_count < char_threshold

                if is_scanned:
                    scanned_pages += 1

                page_details.append({
                    'page': i + 1,
                    'char_count': char_count,
                    'is_scanned': is_scanned
                })

            scan_ratio = scanned_pages / total_pages if total_pages > 0 else 0

            if scan_ratio >= scan_threshold:
                pdf_type = 'scanned'
            elif scan_ratio > 0:
                pdf_type = 'mixed'
            else:
                pdf_type = 'text'

    except Exception as e:
        return ('error', 0, [{'error': str(e)}])

    return pdf_type, scan_ratio, page_details, total_chars


def detect_sensitive_info(text: str, context_chars: int = 50) -> List[Dict]:
    """Detect sensitive information with surrounding context."""
    results = []

    for info_type, pattern in SENSITIVE_PATTERNS.items():
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


def process_document(doc: Dict, config: Dict) -> Dict:
    """Process a single document and extract quality metrics."""
    result = doc.copy()

    try:
        # PDF processing
        if doc['extension'] == '.pdf':
            pdf_type, scan_ratio, page_details, char_count = detect_pdf_type(doc['path'], config)
            result['pdf_type'] = pdf_type
            result['scan_ratio'] = scan_ratio
            result['page_details'] = page_details
            result['char_count'] = char_count

            # Detect sensitive info in PDFs
            if pdfplumber:
                sensitive_findings = []
                with pdfplumber.open(doc['path']) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text() or ''
                        findings = detect_sensitive_info(text, config['sensitive_info']['context_chars'])
                        for f in findings:
                            f['page'] = page.page_number
                            sensitive_findings.append(f)
                result['sensitive_findings'] = sensitive_findings

        # Text-based files
        elif doc['extension'] in ['.txt', '.md']:
            try:
                with open(doc['path'], 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                result['char_count'] = len(text)

                # Detect sensitive info
                findings = detect_sensitive_info(text, config['sensitive_info']['context_chars'])
                result['sensitive_findings'] = findings

            except Exception as e:
                result['error'] = str(e)
                result['char_count'] = 0

        # For other files, estimate based on size
        else:
            result['char_count'] = doc['size'] // 2

        # Calculate MD5
        result['md5'] = calculate_md5(doc['path'])

    except Exception as e:
        result['error'] = str(e)

    return result


def analyze_documents(documents: List[Dict], config: Dict, progress_callback=None) -> Dict:
    """Analyze all documents with parallel processing."""
    workers = config['performance'].get('workers', 4)
    progress_interval = config['performance'].get('progress_interval', 100)

    processed = []
    total = len(documents)

    if workers > 1 and total > 10:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_document, doc, config): doc for doc in documents}

            for i, future in enumerate(as_completed(futures)):
                try:
                    result = future.result()
                    processed.append(result)
                except Exception as e:
                    doc = futures[future]
                    processed.append({**doc, 'error': str(e)})

                if progress_callback and (i + 1) % progress_interval == 0:
                    progress_callback(i + 1, total)
    else:
        for i, doc in enumerate(documents):
            result = process_document(doc, config)
            processed.append(result)

            if progress_callback and (i + 1) % progress_interval == 0:
                progress_callback(i + 1, total)

    return processed


def format_distribution(documents: List[Dict]) -> Dict:
    """Calculate format distribution statistics."""
    ext_counts = Counter(doc['extension'] for doc in documents)
    total = len(documents)

    return {
        'total_documents': total,
        'distribution': {
            ext: {
                'count': count,
                'percentage': round(count / total * 100, 2) if total > 0 else 0
            }
            for ext, count in ext_counts.items()
        }
    }


def pdf_type_summary(documents: List[Dict]) -> Dict:
    """Summarize PDF types."""
    pdf_docs = [d for d in documents if d['extension'] == '.pdf']

    if not pdf_docs:
        return {'total_pdfs': 0}

    type_counts = Counter(d.get('pdf_type', 'unknown') for d in pdf_docs)

    return {
        'total_pdfs': len(pdf_docs),
        'by_type': {
            'text': {'count': type_counts.get('text', 0)},
            'scanned': {'count': type_counts.get('scanned', 0)},
            'mixed': {'count': type_counts.get('mixed', 0)},
            'error': {'count': type_counts.get('error', 0)}
        },
        'pending_confirmation': [
            {
                'path': d['path'],
                'type': d.get('pdf_type', 'unknown'),
                'scan_ratio': round(d.get('scan_ratio', 0) * 100, 2)
            }
            for d in pdf_docs
            if d.get('pdf_type') in ['scanned', 'mixed']
        ]
    }


def length_distribution(documents: List[Dict]) -> Dict:
    """Calculate document length statistics."""
    lengths = [d.get('char_count', 0) for d in documents if d.get('char_count', 0) > 0]

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
            'mean': round(sum(lengths) / n, 2),
            'median': percentile(0.50),
            'min': min(lengths),
            'max': max(lengths)
        },
        'buckets': buckets
    }


def find_duplicates(documents: List[Dict]) -> Dict:
    """Find duplicate files by MD5 hash."""
    hash_map = {}

    for doc in documents:
        if doc.get('md5'):
            if doc['md5'] not in hash_map:
                hash_map[doc['md5']] = []
            hash_map[doc['md5']].append(doc)

    duplicates = {h: files for h, files in hash_map.items() if len(files) > 1}

    return {
        'duplicate_groups': len(duplicates),
        'duplicate_files': sum(len(f) - 1 for f in duplicates.values()),
        'groups': [
            {
                'hash': hash_val,
                'count': len(files),
                'files': [
                    {'path': f['path'], 'name': f['name'], 'size': f['size']}
                    for f in files
                ]
            }
            for hash_val, files in duplicates.items()
        ]
    }


def sensitive_info_summary(documents: List[Dict], config: Dict) -> Dict:
    """Summarize sensitive information findings."""
    enabled_types = config['sensitive_info'].get('enabled_types', [])
    all_findings = []

    for doc in documents:
        findings = doc.get('sensitive_findings', [])
        for f in findings:
            if f['type'] in enabled_types:
                all_findings.append({**f, 'document': doc['path'], 'filename': doc['name']})

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


def classify_document(doc: Dict) -> List[str]:
    """Classify a document based on analysis results."""
    tags = []

    # PDF type
    if doc['extension'] == '.pdf':
        pdf_type = doc.get('pdf_type', 'unknown')
        if pdf_type == 'scanned':
            tags.append('Scan_PDF')
        elif pdf_type == 'mixed':
            tags.append('Mixed_PDF')
        elif pdf_type == 'text':
            tags.append('Text_PDF')

    # File type
    elif doc['extension'] in ['.docx', '.doc']:
        tags.append('DOCX')
    elif doc['extension'] == '.md':
        tags.append('Markdown')
    elif doc['extension'] in ['.xlsx', '.xls']:
        tags.append('Excel')
    elif doc['extension'] in ['.pptx', '.ppt']:
        tags.append('PowerPoint')
    elif doc['extension'] == '.txt':
        tags.append('Text')

    # Length
    char_count = doc.get('char_count', 0)
    if char_count > 0:
        if char_count < 1000:
            tags.append('Short_Doc')
        elif char_count > 100000:
            tags.append('Long_Doc')

    # Has errors
    if doc.get('error'):
        tags.append('Has_Error')

    return tags


def generate_report(analysis_results: Dict, documents: List[Dict], config: Dict) -> Dict:
    """Generate comprehensive assessment report."""
    report = {
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'version': '1.0',
            'config': {
                'char_threshold': config['pdf_detection']['char_threshold'],
                'scan_threshold': config['pdf_detection']['scan_threshold']
            }
        },
        'summary': {
            'total_documents': len(documents),
            'total_size_bytes': sum(d['size'] for d in documents),
            'total_size_mb': round(sum(d['size'] for d in documents) / 1024 / 1024, 2)
        },
        'format_distribution': format_distribution(documents),
        'pdf_analysis': pdf_type_summary(documents),
        'length_distribution': length_distribution(documents),
        'duplicates': find_duplicates(documents),
        'sensitive_info': sensitive_info_summary(documents, config),
        'documents': [
            {
                'path': doc['path'],
                'name': doc['name'],
                'extension': doc['extension'],
                'size': doc['size'],
                'char_count': doc.get('char_count', 0),
                'tags': classify_document(doc)
            }
            for doc in documents
        ]
    }

    return report


def generate_html_report(report: Dict) -> str:
    """Generate HTML report from JSON report."""
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Document Quality Assessment Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; border-left: 4px solid #4CAF50; padding-left: 10px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat-box {{ background: #f9f9f9; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #4CAF50; }}
        .stat-label {{ color: #666; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #4CAF50; color: white; }}
        tr:hover {{ background: #f5f5f5; }}
        .pending {{ background: #fff3cd; padding: 15px; border-radius: 5px; margin: 10px 0; }}
        .warning {{ color: #856404; }}
        .tag {{ display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 12px; margin: 2px; }}
        .tag-scan {{ background: #ff9800; color: white; }}
        .tag-text {{ background: #4CAF50; color: white; }}
        .tag-mixed {{ background: #2196F3; color: white; }}
        .tag-duplicate {{ background: #f44336; color: white; }}
        .tag-sensitive {{ background: #9c27b0; color: white; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Document Quality Assessment Report</h1>
        <p>Generated: {report['metadata']['generated_at']}</p>

        <h2>Summary</h2>
        <div class="summary">
            <div class="stat-box">
                <div class="stat-value">{report['summary']['total_documents']}</div>
                <div class="stat-label">Total Documents</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{report['summary']['total_size_mb']} MB</div>
                <div class="stat-label">Total Size</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{report['pdf_analysis']['total_pdfs']}</div>
                <div class="stat-label">PDF Files</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{report['duplicates']['duplicate_files']}</div>
                <div class="stat-label">Duplicate Files</div>
            </div>
        </div>

        <h2>Format Distribution</h2>
        <table>
            <tr><th>Format</th><th>Count</th><th>Percentage</th></tr>"""

    for ext, data in report['format_distribution']['distribution'].items():
        html += f"<tr><td>{ext}</td><td>{data['count']}</td><td>{data['percentage']}%</td></tr>"

    html += """
        </table>

        <h2>PDF Type Analysis</h2>
        <table>
            <tr><th>Type</th><th>Count</th></tr>"""

    for ptype, data in report['pdf_analysis']['by_type'].items():
        html += f"<tr><td>{ptype.upper()}</td><td>{data['count']}</td></tr>"

    html += """
        </table>"""

    if report['pdf_analysis'].get('pending_confirmation'):
        html += """
        <div class="pending">
            <h3 class="warning">PDFs Requiring Confirmation (Scanned/Mixed)</h3>
            <table>
                <tr><th>File</th><th>Type</th><th>Scan Ratio</th></tr>"""

        for item in report['pdf_analysis']['pending_confirmation']:
            html += f"<tr><td>{item['path']}</td><td>{item['type']}</td><td>{item['scan_ratio']}%</td></tr>"

        html += """
            </table>
        </div>"""

    html += f"""
        <h2>Document Length Distribution</h2>
        <div class="summary">
            <div class="stat-box">
                <div class="stat-value">{report['length_distribution'].get('distribution', {}).get('min', 'N/A')}</div>
                <div class="stat-label">Min Length</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{report['length_distribution'].get('percentiles', {}).get('P50', 'N/A')}</div>
                <div class="stat-label">Median (P50)</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{report['length_distribution'].get('distribution', {}).get('max', 'N/A')}</div>
                <div class="stat-label">Max Length</div>
            </div>
            <div class="stat-box">
                <div class="stat-value">{report['length_distribution'].get('distribution', {}).get('mean', 'N/A')}</div>
                <div class="stat-label">Mean Length</div>
            </div>
        </div>

        <h2>Percentiles</h2>
        <table>
            <tr><th>Percentile</th><th>Characters</th></tr>"""

    for p, v in report['length_distribution'].get('percentiles', {}).items():
        html += f"<tr><td>{p}</td><td>{v}</td></tr>"

    html += """
        </table>

        <h2>Length Buckets</h2>
        <table>
            <tr><th>Range</th><th>Count</th></tr>"""

    for bucket, count in report['length_distribution'].get('buckets', {}).items():
        html += f"<tr><td>{bucket}</td><td>{count}</td></tr>"

    if report['duplicates']['groups']:
        html += f"""
        <div class="pending">
            <h3 class="warning">Duplicate Files (Pending Confirmation)</h3>
            <p>{report['duplicates']['duplicate_groups']} groups, {report['duplicates']['duplicate_files']} duplicate files</p>
        """

        for i, group in enumerate(report['duplicates']['groups'][:10]):  # Show first 10
            html += f"<h4>Group {i+1} (Hash: {group['hash'][:16]}..., Count: {group['count']})</h4><ul>"
            for f in group['files']:
                html += f"<li>{f['path']}</li>"
            html += "</ul>"

        if len(report['duplicates']['groups']) > 10:
            html += f"<p>... and {len(report['duplicates']['groups']) - 10} more groups</p>"

        html += "</div>"

    if report['sensitive_info']['total_findings'] > 0:
        html += f"""
        <div class="pending">
            <h3 class="warning">Sensitive Information Found (Pending Review)</h3>
            <p>Total: {report['sensitive_info']['total_findings']} findings</p>
        """

        for ptype, data in report['sensitive_info']['by_type'].items():
            html += f"<h4>{ptype} ({data['count']} items)</h4><ul>"
            for item in data['items'][:5]:  # Show first 5 per type
                html += f"<li><strong>{item.get('document', 'Unknown')}</strong>: {item['value']}<br><small>{item['context']}</small></li>"
            if len(data['items']) > 5:
                html += f"<li>... and {len(data['items']) - 5} more</li>"
            html += "</ul>"

        html += "</div>"

    html += """
    </div>
</body>
</html>"""

    return html


def main():
    parser = argparse.ArgumentParser(description='Document Quality Assessment Tool')
    parser.add_argument('directory', help='Directory containing documents to assess')
    parser.add_argument('--config', '-c', help='Path to configuration file')
    parser.add_argument('--output', '-o', help='Output JSON file path')
    parser.add_argument('--html', help='Output HTML file path')
    parser.add_argument('--workers', '-w', type=int, help='Number of parallel workers')

    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: {args.directory} is not a valid directory")
        sys.exit(1)

    # Load configuration
    config = load_config(args.config)

    if args.workers:
        config['performance']['workers'] = args.workers

    print(f"Scanning directory: {args.directory}")
    documents = scan_documents(args.directory, config['supported_extensions'])
    print(f"Found {len(documents)} documents")

    if not documents:
        print("No documents found")
        sys.exit(0)

    print("Analyzing documents...")

    def progress(current, total):
        print(f"\rProgress: {current}/{total} ({current * 100 // total}%)", end='', flush=True)

    analyzed = analyze_documents(documents, config, progress_callback=progress)
    print()  # New line after progress

    print("Generating report...")
    report = generate_report({}, analyzed, config)

    # Save JSON report
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"JSON report saved to: {args.output}")

    # Generate and save HTML report
    if args.html:
        html_report = generate_html_report(report)
        with open(args.html, 'w', encoding='utf-8') as f:
            f.write(html_report)
        print(f"HTML report saved to: {args.html}")

    # Print summary
    print("\n" + "=" * 50)
    print("ASSESSMENT SUMMARY")
    print("=" * 50)
    print(f"Total Documents: {report['summary']['total_documents']}")
    print(f"Total Size: {report['summary']['total_size_mb']} MB")
    print(f"PDF Files: {report['pdf_analysis']['total_pdfs']}")
    print(f"Duplicate Files: {report['duplicates']['duplicate_files']}")
    print(f"Sensitive Info Findings: {report['sensitive_info']['total_findings']}")
    print("=" * 50)

    # Print pending confirmations
    pending = report['pdf_analysis'].get('pending_confirmation', [])
    if pending:
        print(f"\nPDFs Requiring Confirmation: {len(pending)}")

    if report['duplicates']['duplicate_groups'] > 0:
        print(f"Duplicate Groups: {report['duplicates']['duplicate_groups']}")

    print(f"\nFull report saved to: {args.output or 'stdout (JSON above)'}")


if __name__ == '__main__':
    main()
