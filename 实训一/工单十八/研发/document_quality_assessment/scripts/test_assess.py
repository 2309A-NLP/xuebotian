#!/usr/bin/env python3
"""
Unit Tests for Document Quality Assessment Skill
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

import pytest

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assess import (
    scan_documents,
    calculate_md5,
    detect_pdf_type,
    detect_sensitive_info,
    format_distribution,
    pdf_type_summary,
    length_distribution,
    find_duplicates,
    classify_document,
    generate_report,
    generate_html_report,
    DEFAULT_CONFIG
)


class TestScanDocuments:
    """Test document scanning functionality."""

    def setup_method(self):
        """Create temporary test directory."""
        self.test_dir = tempfile.mkdtemp()
        self.test_files = []

    def teardown_method(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_file(self, name: str, content: str = "test content"):
        """Helper to create a test file."""
        path = os.path.join(self.test_dir, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return path

    def test_scan_empty_directory(self):
        """Test scanning empty directory."""
        docs = scan_documents(self.test_dir, DEFAULT_CONFIG['supported_extensions'])
        assert len(docs) == 0

    def test_scan_pdf_files(self):
        """Test scanning PDF files."""
        self._create_file("test.pdf")
        self._create_file("document.PDF")

        docs = scan_documents(self.test_dir, DEFAULT_CONFIG['supported_extensions'])
        assert len(docs) == 2
        assert all(d['extension'] == '.pdf' for d in docs)

    def test_scan_multiple_formats(self):
        """Test scanning multiple file formats."""
        self._create_file("doc1.pdf")
        self._create_file("doc2.docx")
        self._create_file("readme.md")
        self._create_file("notes.txt")

        docs = scan_documents(self.test_dir, DEFAULT_CONFIG['supported_extensions'])
        assert len(docs) == 4

        exts = {d['extension'] for d in docs}
        assert exts == {'.pdf', '.docx', '.md', '.txt'}

    def test_scan_nested_directories(self):
        """Test scanning nested directories."""
        nested = os.path.join(self.test_dir, "subdir")
        os.makedirs(nested)

        self._create_file("root.pdf")
        self._create_file(os.path.join("subdir", "nested.pdf"))

        docs = scan_documents(self.test_dir, DEFAULT_CONFIG['supported_extensions'])
        assert len(docs) == 2

    def test_scan_excludes_unsupported(self):
        """Test that unsupported files are excluded."""
        self._create_file("image.jpg")
        self._create_file("video.mp4")
        self._create_file("document.pdf")

        docs = scan_documents(self.test_dir, DEFAULT_CONFIG['supported_extensions'])
        assert len(docs) == 1
        assert docs[0]['extension'] == '.pdf'


class TestCalculateMD5:
    """Test MD5 calculation."""

    def setup_method(self):
        """Create temporary test file."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, mode='w')
        self.temp_file.write("test content")
        self.temp_file.close()

    def teardown_method(self):
        """Clean up test file."""
        try:
            os.unlink(self.temp_file.name)
        except OSError:
            pass

    def test_md5_consistency(self):
        """Test that MD5 is consistent for same content."""
        md5_1 = calculate_md5(self.temp_file.name)
        md5_2 = calculate_md5(self.temp_file.name)
        assert md5_1 == md5_2
        assert len(md5_1) == 32  # MD5 hash length

    def test_md5_different_content(self):
        """Test that different content produces different MD5."""
        temp_file2 = tempfile.NamedTemporaryFile(delete=False, mode='w')
        temp_file2.write("different content")
        temp_file2.close()

        try:
            md5_1 = calculate_md5(self.temp_file.name)
            md5_2 = calculate_md5(temp_file2.name)
            assert md5_1 != md5_2
        finally:
            os.unlink(temp_file2.name)


class TestDetectSensitiveInfo:
    """Test sensitive information detection."""

    def test_detect_mobile_phone(self):
        """Test Chinese mobile phone detection."""
        text = "联系电话：13812345678"
        results = detect_sensitive_info(text)

        assert len(results) == 1
        assert results[0]['type'] == 'phone_mobile'
        assert results[0]['value'] == '13812345678'

    def test_detect_email(self):
        """Test email detection."""
        text = "邮箱：test@example.com"
        results = detect_sensitive_info(text)

        assert len(results) == 1
        assert results[0]['type'] == 'email'
        assert results[0]['value'] == 'test@example.com'

    def test_detect_id_card(self):
        """Test Chinese ID card detection."""
        text = "身份证号：110101199001011234"
        results = detect_sensitive_info(text)

        assert len(results) == 1
        assert results[0]['type'] == 'id_card'
        assert results[0]['value'] == '110101199001011234'

    def test_detect_multiple_types(self):
        """Test detecting multiple types in same text."""
        text = "手机：13912345678，邮箱：test@163.com，身份证：110101199001011234"
        results = detect_sensitive_info(text)

        types = {r['type'] for r in results}
        assert 'phone_mobile' in types
        assert 'email' in types
        assert 'id_card' in types

    def test_detect_with_context(self):
        """Test that context is included."""
        text = "这是前后文，联系电话：13812345678，请尽快联系"
        results = detect_sensitive_info(text, context_chars=10)

        assert len(results) == 1
        assert '...' in results[0]['context']
        assert '13812345678' in results[0]['context']

    def test_detect_no_match(self):
        """Test text with no sensitive info."""
        text = "这是一段普通的中文文本，不包含任何敏感信息"
        results = detect_sensitive_info(text)

        assert len(results) == 0


class TestFormatDistribution:
    """Test format distribution statistics."""

    def test_empty_input(self):
        """Test empty document list."""
        result = format_distribution([])
        assert result['total_documents'] == 0
        assert result['distribution'] == {}

    def test_single_format(self):
        """Test single format."""
        docs = [
            {'extension': '.pdf'},
            {'extension': '.pdf'},
            {'extension': '.pdf'},
        ]
        result = format_distribution(docs)

        assert result['total_documents'] == 3
        assert result['distribution']['.pdf']['count'] == 3
        assert result['distribution']['.pdf']['percentage'] == 100.0

    def test_multiple_formats(self):
        """Test multiple formats."""
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
        assert result['distribution']['.docx']['count'] == 1
        assert result['distribution']['.md']['count'] == 1


class TestClassifyDocument:
    """Test document classification."""

    def test_text_pdf(self):
        """Test text PDF classification."""
        doc = {
            'extension': '.pdf',
            'pdf_type': 'text',
            'char_count': 5000
        }
        tags = classify_document(doc)

        assert 'Text_PDF' in tags
        assert 'Short_Doc' not in tags

    def test_scanned_pdf(self):
        """Test scanned PDF classification."""
        doc = {
            'extension': '.pdf',
            'pdf_type': 'scanned',
            'char_count': 100
        }
        tags = classify_document(doc)

        assert 'Scan_PDF' in tags
        assert 'Short_Doc' in tags

    def test_mixed_pdf(self):
        """Test mixed PDF classification."""
        doc = {
            'extension': '.pdf',
            'pdf_type': 'mixed',
            'char_count': 5000
        }
        tags = classify_document(doc)

        assert 'Mixed_PDF' in tags

    def test_docx(self):
        """Test DOCX classification."""
        doc = {
            'extension': '.docx',
            'char_count': 5000
        }
        tags = classify_document(doc)

        assert 'DOCX' in tags

    def test_markdown(self):
        """Test Markdown classification."""
        doc = {
            'extension': '.md',
            'char_count': 5000
        }
        tags = classify_document(doc)

        assert 'Markdown' in tags

    def test_short_document(self):
        """Test short document classification."""
        doc = {
            'extension': '.txt',
            'char_count': 500
        }
        tags = classify_document(doc)

        assert 'Short_Doc' in tags
        assert 'Text' in tags

    def test_long_document(self):
        """Test long document classification."""
        doc = {
            'extension': '.pdf',
            'pdf_type': 'text',
            'char_count': 200000
        }
        tags = classify_document(doc)

        assert 'Long_Doc' in tags

    def test_has_error(self):
        """Test error flag."""
        doc = {
            'extension': '.pdf',
            'error': 'Some error occurred'
        }
        tags = classify_document(doc)

        assert 'Has_Error' in tags


class TestGenerateReport:
    """Test report generation."""

    def test_report_structure(self):
        """Test report has required fields."""
        docs = [
            {
                'path': '/test/doc.pdf',
                'name': 'doc.pdf',
                'extension': '.pdf',
                'size': 1024,
                'char_count': 5000,
                'pdf_type': 'text',
                'md5': 'abc123'
            }
        ]

        report = generate_report({}, docs, DEFAULT_CONFIG)

        assert 'metadata' in report
        assert 'summary' in report
        assert 'format_distribution' in report
        assert 'pdf_analysis' in report
        assert 'length_distribution' in report
        assert 'duplicates' in report
        assert 'sensitive_info' in report
        assert 'documents' in report

    def test_report_metadata(self):
        """Test report metadata."""
        docs = [{'path': '/test.pdf', 'name': 'test.pdf', 'extension': '.pdf', 'size': 100, 'char_count': 50, 'md5': 'abc'}]

        report = generate_report({}, docs, DEFAULT_CONFIG)

        assert 'generated_at' in report['metadata']
        assert 'version' in report['metadata']
        assert report['metadata']['version'] == '1.0'

    def test_html_report_generation(self):
        """Test HTML report can be generated."""
        docs = [{'path': '/test.pdf', 'name': 'test.pdf', 'extension': '.pdf', 'size': 100, 'char_count': 50, 'md5': 'abc'}]

        report = generate_report({}, docs, DEFAULT_CONFIG)
        html = generate_html_report(report)

        assert '<html>' in html
        assert '<body>' in html
        assert 'Document Quality Assessment Report' in html
        assert len(html) > 1000


class TestFindDuplicates:
    """Test duplicate detection."""

    def test_no_duplicates(self):
        """Test with no duplicates."""
        docs = [
            {'path': '/doc1.pdf', 'name': 'doc1.pdf', 'extension': '.pdf', 'size': 100, 'md5': 'hash1'},
            {'path': '/doc2.pdf', 'name': 'doc2.pdf', 'extension': '.pdf', 'size': 100, 'md5': 'hash2'},
        ]

        result = find_duplicates(docs)

        assert result['duplicate_groups'] == 0
        assert result['duplicate_files'] == 0
        assert len(result['groups']) == 0

    def test_with_duplicates(self):
        """Test with duplicates."""
        docs = [
            {'path': '/doc1.pdf', 'name': 'doc1.pdf', 'extension': '.pdf', 'size': 100, 'md5': 'hash1'},
            {'path': '/doc2.pdf', 'name': 'doc2.pdf', 'extension': '.pdf', 'size': 100, 'md5': 'hash1'},
            {'path': '/doc3.pdf', 'name': 'doc3.pdf', 'extension': '.pdf', 'size': 100, 'md5': 'hash2'},
        ]

        result = find_duplicates(docs)

        assert result['duplicate_groups'] == 1
        assert result['duplicate_files'] == 1  # 3 files - 1 unique = 2 duplicates? No: (2-1) + (1-1) = 1
        # Actually: hash1 has 2 files = 1 duplicate, hash2 has 1 file = 0 duplicates
        # So total duplicates = 1


class TestLengthDistribution:
    """Test length distribution calculation."""

    def test_empty_input(self):
        """Test with empty input."""
        result = length_distribution([])

        assert 'error' in result

    def test_single_document(self):
        """Test with single document."""
        docs = [{'char_count': 1000}]

        result = length_distribution(docs)

        assert result['count'] == 1
        assert result['percentiles']['P50'] == 1000

    def test_percentiles(self):
        """Test percentile calculation."""
        docs = [{'char_count': i * 1000} for i in range(1, 101)]

        result = length_distribution(docs)

        assert result['percentiles']['P25'] == 25000
        assert result['percentiles']['P50'] == 50000
        assert result['percentiles']['P75'] == 75000
        assert result['percentiles']['P90'] == 90000

    def test_buckets(self):
        """Test length buckets."""
        docs = [
            {'char_count': 500},    # 0-1K
            {'char_count': 5000},   # 1K-10K
            {'char_count': 50000},  # 10K-100K
            {'char_count': 500000}, # 100K-1M
            {'char_count': 2000000}, # 1M+
        ]

        result = length_distribution(docs)

        assert result['buckets']['0-1K'] == 1
        assert result['buckets']['1K-10K'] == 1
        assert result['buckets']['10K-100K'] == 1
        assert result['buckets']['100K-1M'] == 1
        assert result['buckets']['1M+'] == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
