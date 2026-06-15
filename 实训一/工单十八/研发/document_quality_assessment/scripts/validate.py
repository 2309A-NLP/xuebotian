#!/usr/bin/env python3
"""
Validation script for Document Quality Assessment Skill

This script tests the skill functionality with a sample dataset.
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

# Add scripts to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def create_test_files(test_dir):
    """Create test files for validation."""
    # Create some test files
    files = [
        ('test1.pdf', 'This is a text-based PDF with some content.'),
        ('test2.pdf', 'Another document.'),
        ('readme.md', '# Readme\n\nThis is a markdown file.'),
        ('notes.txt', 'Plain text file.\nWith multiple lines.'),
    ]

    created = []
    for name, content in files:
        path = os.path.join(test_dir, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        created.append(path)

    return created


def test_scan_documents():
    """Test document scanning."""
    print("Testing document scanning...")

    with tempfile.TemporaryDirectory() as test_dir:
        create_test_files(test_dir)

        docs = scan_documents(test_dir, DEFAULT_CONFIG['supported_extensions'])

        assert len(docs) == 4, f"Expected 4 documents, got {len(docs)}"
        print(f"  PASS: Scanned {len(docs)} documents")


def test_sensitive_info_detection():
    """Test sensitive information detection."""
    print("Testing sensitive information detection...")

    test_texts = [
        ("手机：13812345678", "phone_mobile", "13812345678"),
        ("邮箱: test@example.com", "email", "test@example.com"),
        ("身份证号：110101199001011234", "id_card", "110101199001011234"),
    ]

    for text, expected_type, expected_value in test_texts:
        findings = detect_sensitive_info(text)
        assert len(findings) > 0, f"No findings in: {text}"

        types = [f['type'] for f in findings]
        assert expected_type in types, f"Expected {expected_type} in {types}"

        values = [f['value'] for f in findings]
        assert expected_value in values, f"Expected {expected_value} in {values}"

    print("  PASS: Sensitive info detection working")


def test_format_distribution():
    """Test format distribution calculation."""
    print("Testing format distribution...")

    docs = [
        {'extension': '.pdf'},
        {'extension': '.pdf'},
        {'extension': '.docx'},
        {'extension': '.md'},
    ]

    result = format_distribution(docs)

    assert result['total_documents'] == 4
    assert result['distribution']['.pdf']['count'] == 2
    assert result['distribution']['.pdf']['percentage'] == 50.0

    print("  PASS: Format distribution correct")


def test_classification():
    """Test document classification."""
    print("Testing document classification...")

    doc = {
        'extension': '.pdf',
        'pdf_type': 'scanned',
        'char_count': 100
    }

    tags = classify_document(doc)
    assert 'Scan_PDF' in tags
    assert 'Short_Doc' in tags

    print("  PASS: Classification working")


def test_report_generation():
    """Test report generation."""
    print("Testing report generation...")

    docs = [
        {
            'path': '/test/doc1.pdf',
            'name': 'doc1.pdf',
            'extension': '.pdf',
            'size': 1024,
            'char_count': 5000,
            'pdf_type': 'text',
            'md5': 'abc123',
            'sensitive_findings': []
        },
        {
            'path': '/test/doc2.pdf',
            'name': 'doc2.pdf',
            'extension': '.pdf',
            'size': 1024,
            'char_count': 100,
            'pdf_type': 'scanned',
            'md5': 'abc123',
            'sensitive_findings': []
        }
    ]

    report = generate_report({}, docs, DEFAULT_CONFIG)

    # Check structure
    assert 'metadata' in report
    assert 'summary' in report
    assert 'format_distribution' in report
    assert 'pdf_analysis' in report
    assert 'duplicates' in report
    assert 'sensitive_info' in report

    # Check duplicates detected
    assert report['duplicates']['duplicate_groups'] == 1

    print("  PASS: Report generation working")


def test_html_generation():
    """Test HTML report generation."""
    print("Testing HTML report generation...")

    docs = [{
        'path': '/test.pdf',
        'name': 'test.pdf',
        'extension': '.pdf',
        'size': 100,
        'char_count': 50,
        'md5': 'abc',
        'sensitive_findings': []
    }]

    report = generate_report({}, docs, DEFAULT_CONFIG)
    html = generate_html_report(report)

    assert '<html>' in html
    assert 'Document Quality Assessment Report' in html
    assert len(html) > 1000

    print("  PASS: HTML report generation working")


def run_all_tests():
    """Run all validation tests."""
    print("=" * 60)
    print("Document Quality Assessment Skill - Validation Tests")
    print("=" * 60)

    tests = [
        test_scan_documents,
        test_sensitive_info_detection,
        test_format_distribution,
        test_classification,
        test_report_generation,
        test_html_generation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {str(e)}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
