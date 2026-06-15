#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Document Quality Assessment Skill - Folder Test Script

Usage:
    python test_folder.py <folder_path>

Example:
    python test_folder.py "C:\Users\TIANTIAN\Documents"
    python test_folder.py "g:\my_documents"
"""

import os
import sys
import json
import argparse
from pathlib import Path

# Add scripts directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from assess import (
    scan_documents,
    calculate_md5,
    detect_pdf_type,
    detect_sensitive_info,
    format_distribution,
    classify_document,
    generate_report,
    generate_html_report,
    DEFAULT_CONFIG
)


def analyze_document(doc, config):
    """Analyze a single document."""
    result = doc.copy()
    result['md5'] = calculate_md5(doc['path'])

    try:
        # Get file size
        result['size'] = os.path.getsize(doc['path'])
    except:
        pass

    # PDF specific analysis
    if doc['extension'] == '.pdf':
        try:
            pdf_type, scan_ratio, page_details, char_count = detect_pdf_type(doc['path'], config)
            result['pdf_type'] = pdf_type
            result['scan_ratio'] = scan_ratio
            result['char_count'] = char_count
        except Exception as e:
            result['error'] = str(e)
            result['pdf_type'] = 'error'
    else:
        # Text-based documents
        try:
            with open(doc['path'], 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            result['char_count'] = len(content)

            # Detect sensitive info
            if result['char_count'] > 0:
                result['sensitive_info'] = detect_sensitive_info(content)
            else:
                result['sensitive_info'] = []
        except Exception as e:
            result['error'] = str(e)
            result['char_count'] = 0
            result['sensitive_info'] = []

    # Classify document
    result['tags'] = classify_document(result)

    return result


def analyze_folder(folder_path):
    """Analyze all documents in a folder."""
    print(f"\n{'='*60}")
    print(f"Analyzing Folder: {folder_path}")
    print(f"{'='*60}\n")

    # Validate folder
    if not os.path.exists(folder_path):
        print(f"[ERROR] Folder does not exist: {folder_path}")
        return None

    if not os.path.isdir(folder_path):
        print(f"[ERROR] Not a directory: {folder_path}")
        return None

    # Scan documents
    print("[1/4] Scanning documents...")
    documents = scan_documents(folder_path, DEFAULT_CONFIG['supported_extensions'])

    if not documents:
        print("[INFO] No supported documents found in folder.")
        print("Supported formats:", ', '.join(DEFAULT_CONFIG['supported_extensions']))
        return None

    print(f"       Found {len(documents)} documents")

    # Analyze each document
    print("[2/4] Analyzing documents...")
    analyzed = []
    for i, doc in enumerate(documents):
        doc_name = doc['name'][:40] + '...' if len(doc['name']) > 40 else doc['name']
        print(f"       [{i+1}/{len(documents)}] {doc_name}")

        result = analyze_document(doc, DEFAULT_CONFIG)
        analyzed.append(result)

    # Generate report
    print("[3/4] Generating report...")
    report = generate_report({}, analyzed, DEFAULT_CONFIG)

    # Print summary
    print(f"\n{'='*60}")
    print("ASSESSMENT SUMMARY")
    print(f"{'='*60}")

    summary = report['summary']
    print(f"\nTotal Documents: {summary.get('total_documents', 0)}")
    print(f"Total Size: {summary.get('total_size_mb', 0):.2f} MB")

    # Format distribution
    print(f"\n--- Format Distribution ---")
    dist = report['format_distribution']['distribution']
    for ext, info in sorted(dist.items(), key=lambda x: x[1]['count'], reverse=True):
        print(f"  {ext}: {info['count']} files ({info['percentage']:.1f}%)")

    # PDF analysis
    pdf_analysis = report.get('pdf_analysis', {})
    if pdf_analysis.get('total_pdfs', 0) > 0:
        print(f"\n--- PDF Analysis ---")
        print(f"Total PDFs: {pdf_analysis.get('total_pdfs', 0)}")
        by_type = pdf_analysis.get('by_type', {})
        for pdf_type, info in by_type.items():
            print(f"  {pdf_type}: {info.get('count', 0)} files")

    # Sensitive info
    sensitive = report.get('sensitive_info', {})
    if sensitive.get('total_findings', 0) > 0:
        print(f"\n--- Sensitive Information ---")
        print(f"Total Findings: {sensitive.get('total_findings', 0)}")
        by_type = sensitive.get('by_type', {})
        for info_type, count in by_type.items():
            print(f"  {info_type}: {count}")

    # Duplicates
    duplicates = report.get('duplicates', {})
    if duplicates.get('duplicate_groups', 0) > 0:
        print(f"\n--- Duplicates ---")
        print(f"Duplicate Groups: {duplicates.get('duplicate_groups', 0)}")
        print(f"Duplicate Files: {duplicates.get('duplicate_files', 0)}")

    # Document routing recommendations
    print(f"\n--- Routing Recommendations ---")
    routing_map = {
        'Scan_PDF': 'OCR Parser (HIGH PRIORITY)',
        'Mixed_PDF': 'OCR Parser (mixed)',
        'Text_PDF': 'Text Parser',
        'DOCX': 'DOCX Parser',
        'Markdown': 'Markdown Parser',
        'Excel': 'Excel Parser',
        'PPT': 'PPT Parser'
    }

    for doc in analyzed:
        tags = doc.get('tags', [])
        path = doc.get('name', 'unknown')

        # Find primary route
        route = 'Default Parser'
        for tag, route_name in routing_map.items():
            if tag in tags:
                route = route_name
                break

        # Check for issues
        issues = []
        if 'Scan_PDF' in tags:
            issues.append('needs OCR')
        if 'Has_Error' in tags:
            issues.append('PARSE ERROR')
        if doc.get('sensitive_info') and len(doc.get('sensitive_info', [])) > 0:
            issues.append(f"{len(doc['sensitive_info'])} sensitive info")

        issue_str = f" [{', '.join(issues)}]" if issues else ""

        # Truncate path for display
        display_path = path[:50] + '...' if len(path) > 50 else path
        print(f"  {display_path}: {route}{issue_str}")

    # Save report
    print(f"\n[4/4] Saving report...")
    report_path = os.path.join(folder_path, 'quality_assessment_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"       Report saved: {report_path}")

    # Also generate HTML
    html_path = os.path.join(folder_path, 'quality_assessment_report.html')
    html_content = generate_html_report(report)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"       HTML report saved: {html_path}")

    print(f"\n{'='*60}")
    print("ASSESSMENT COMPLETED")
    print(f"{'='*60}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description='Document Quality Assessment - Test a folder',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_folder.py "C:\\Users\\Me\\Documents"
  python test_folder.py "g:\\my_folder"
  python test_folder.py .
        """
    )

    parser.add_argument(
        'folder',
        nargs='?',
        default='.',
        help='Path to folder to analyze (default: current directory)'
    )

    args = parser.parse_args()

    # Resolve folder path
    folder_path = os.path.abspath(args.folder)
    print(f"Target folder: {folder_path}")

    # Run analysis
    report = analyze_folder(folder_path)

    if report:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
