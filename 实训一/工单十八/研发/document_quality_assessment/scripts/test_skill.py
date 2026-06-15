#!/usr/bin/env python3
"""
Test script for Document Quality Assessment Skill
"""

import os
import sys
import json
import tempfile
import shutil
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


def create_test_files(test_dir: str):
    """Create test files for quality assessment."""
    
    # Create a simple text file
    text_file = os.path.join(test_dir, "test_document.txt")
    with open(text_file, 'w', encoding='utf-8') as f:
        f.write("""这是一份测试文档。
        
文档质量评估测试文件。

包含一些中文文本内容。

作者: 张三
邮箱: test@example.com
电话: 13812345678
""")

    # Create a markdown file
    md_file = os.path.join(test_dir, "readme.md")
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write("""# 测试文档

这是一个 Markdown 测试文件。

## 包含内容
- 列表项1
- 列表项2

## 联系方式
- 邮箱: admin@test.com
""")

    # Create a simple PDF (binary placeholder)
    pdf_file = os.path.join(test_dir, "sample.pdf")
    with open(pdf_file, 'wb') as f:
        # Minimal valid PDF structure
        f.write(b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000317 00000 n 
trailer
<< /Size 5 /Root 1 0 R >>
startxref
410
%%EOF
""")

    print(f"Created test files in: {test_dir}")
    return test_dir


def test_scan_documents(test_dir: str):
    """Test document scanning."""
    print("\n" + "="*60)
    print("TEST: Scan Documents")
    print("="*60)
    
    docs = scan_documents(test_dir, DEFAULT_CONFIG['supported_extensions'])
    
    print(f"Found {len(docs)} documents:")
    for doc in docs:
        print(f"  - {doc['name']} ({doc['extension']}, {doc['size']} bytes)")
    
    assert len(docs) >= 3, "Should find at least 3 test files"
    print("[PASSED]")


def test_md5_calculation():
    """Test MD5 calculation."""
    print("\n" + "="*60)
    print("TEST: MD5 Calculation")
    print("="*60)
    
    with tempfile.NamedTemporaryFile(delete=False, mode='w') as f:
        f.write("test content")
        temp_path = f.name
    
    try:
        md5_1 = calculate_md5(temp_path)
        md5_2 = calculate_md5(temp_path)
        
        print(f"MD5 hash: {md5_1}")
        assert md5_1 == md5_2, "MD5 should be consistent"
        assert len(md5_1) == 32, "MD5 should be 32 characters"
        print("  [PASSED]")
    finally:
        os.unlink(temp_path)


def test_sensitive_info_detection():
    """Test sensitive information detection."""
    print("\n" + "="*60)
    print("TEST: Sensitive Info Detection")
    print("="*60)
    
    test_texts = [
        "联系电话：13812345678",
        "邮箱：test@example.com",
        "身份证号：110101199001011234",
        "座机：010-12345678",
        "银行卡：6222 1234 5678 9012 34"
    ]
    
    total_findings = 0
    for text in test_texts:
        results = detect_sensitive_info(text)
        print(f"  Text: {text[:30]}...")
        print(f"  Findings: {len(results)}")
        for r in results:
            print(f"    - Type: {r['type']}, Value: {r['value']}")
        total_findings += len(results)
    
    assert total_findings >= 4, "Should detect at least 4 types of sensitive info"
    print(f"Total findings: {total_findings}")
    print("[PASSED]")


def test_format_distribution(test_dir: str):
    """Test format distribution calculation."""
    print("\n" + "="*60)
    print("TEST: Format Distribution")
    print("="*60)
    
    docs = scan_documents(test_dir, DEFAULT_CONFIG['supported_extensions'])
    result = format_distribution(docs)
    
    print(f"Total documents: {result['total_documents']}")
    print("Distribution:")
    for ext, info in result['distribution'].items():
        print(f"  {ext}: {info['count']} files ({info['percentage']:.1f}%)")
    
    print("[PASSED]")


def test_document_classification(test_dir: str):
    """Test document classification."""
    print("\n" + "="*60)
    print("TEST: Document Classification")
    print("="*60)
    
    docs = scan_documents(test_dir, DEFAULT_CONFIG['supported_extensions'])
    
    for doc in docs:
        # Add mock analysis data
        if doc['extension'] == '.txt':
            doc['char_count'] = 500
            doc['pdf_type'] = 'unknown'
        elif doc['extension'] == '.md':
            doc['char_count'] = 200
            doc['pdf_type'] = 'unknown'
        elif doc['extension'] == '.pdf':
            doc['char_count'] = 100  # Low char count = scanned
            doc['pdf_type'] = 'scanned'
        
        tags = classify_document(doc)
        print(f"  {doc['name']}: {tags}")
    
    print("[PASSED]")


def test_generate_report(test_dir: str):
    """Test report generation."""
    print("\n" + "="*60)
    print("TEST: Generate Report")
    print("="*60)
    
    docs = scan_documents(test_dir, DEFAULT_CONFIG['supported_extensions'])
    
    # Add mock analysis data to docs
    for doc in docs:
        doc['char_count'] = 500
        doc['md5'] = calculate_md5(doc['path']) if os.path.exists(doc['path']) else 'mock_md5'
        doc['pdf_type'] = 'scanned' if doc['extension'] == '.pdf' else 'unknown'
        doc['sensitive_info'] = detect_sensitive_info(open(doc['path'], 'r', encoding='utf-8', errors='ignore').read())
        doc['tags'] = classify_document(doc)
    
    report = generate_report({}, docs, DEFAULT_CONFIG)
    
    print(f"Report generated successfully!")
    print(f"  - Total documents: {report['summary']['total_documents']}")
    print(f"  - Format distribution: {len(report['format_distribution']['distribution'])} types")
    print(f"  - Sensitive info findings: {report['sensitive_info']['total_findings']}")
    print(f"  - Generated at: {report['metadata']['generated_at']}")
    
    # Also test HTML report
    html = generate_html_report(report)
    print(f"  - HTML report length: {len(html)} chars")
    
    print("[PASSED]")
    return report


def test_full_assessment_workflow(test_dir: str):
    """Test the full assessment workflow."""
    print("\n" + "="*60)
    print("TEST: Full Assessment Workflow")
    print("="*60)
    
    # Scan
    print("Step 1: Scanning documents...")
    docs = scan_documents(test_dir, DEFAULT_CONFIG['supported_extensions'])
    print(f"  Found {len(docs)} documents")
    
    # Analyze each document
    print("Step 2: Analyzing documents...")
    for doc in docs:
        if doc['extension'] == '.pdf':
            pdf_type, scan_ratio, _, _ = detect_pdf_type(doc['path'], DEFAULT_CONFIG)
            doc['pdf_type'] = pdf_type
            print(f"  {doc['name']}: PDF type = {pdf_type}, scan_ratio = {scan_ratio:.2f}")
        else:
            doc['pdf_type'] = 'unknown'
        
        # Read text content for sensitive info
        try:
            with open(doc['path'], 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            doc['char_count'] = len(content)
            doc['sensitive_info'] = detect_sensitive_info(content)
        except:
            doc['char_count'] = 0
            doc['sensitive_info'] = []
        
        doc['md5'] = calculate_md5(doc['path']) if os.path.exists(doc['path']) else 'mock'
        doc['tags'] = classify_document(doc)
        print(f"  {doc['name']}: tags = {doc['tags']}")
    
    # Generate report
    print("Step 3: Generating report...")
    report = generate_report({}, docs, DEFAULT_CONFIG)
    
    print("Full workflow completed!")
    print("[PASSED]")
    print(f"  Summary: {report['summary']['total_documents']} documents assessed")
    
    # Print routing recommendations
    print("\n  Routing recommendations:")
    for doc in report.get('documents', []):
        tags = doc.get('tags', [])
        if 'Scan_PDF' in tags:
            route = "OCR Parser (high priority)"
        elif 'Text_PDF' in tags:
            route = "Text Parser"
        elif 'DOCX' in tags:
            route = "DOCX Parser"
        elif 'Markdown' in tags:
            route = "Markdown Parser"
        else:
            route = "Default Parser"
        print(f"    {doc['name']}: {route}")
    
    print("[PASSED]")
    return report


def main():
    """Run all tests."""
    print("="*60)
    print("Document Quality Assessment Skill - Test Suite")
    print("="*60)
    
    # Create temporary test directory
    test_dir = tempfile.mkdtemp(prefix="ragflow_test_")
    print(f"\nTest directory: {test_dir}")
    
    try:
        # Create test files
        create_test_files(test_dir)
        
        # Run tests
        test_scan_documents(test_dir)
        test_md5_calculation()
        test_sensitive_info_detection()
        test_format_distribution(test_dir)
        test_document_classification(test_dir)
        test_generate_report(test_dir)
        test_full_assessment_workflow(test_dir)
        
        print("\n" + "="*60)
        print("ALL TESTS PASSED!")
        print("="*60)
        
    except Exception as e:
        print(f"\n[ERROR] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    finally:
        # Clean up
        print(f"\nCleaning up test directory: {test_dir}")
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
