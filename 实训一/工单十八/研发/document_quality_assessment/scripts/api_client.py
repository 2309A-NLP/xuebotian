#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Document Quality Assessment API Client

Usage:
    python api_client.py                          # Interactive mode
    python api_client.py --directory "path"       # Assess a directory
    python api_client.py --file "file1.pdf" --file "file2.pdf"  # Assess specific files
    python api_client.py --routing "path"         # Get routing recommendations

Examples:
    # Test local endpoint
    python api_client.py --base-url "http://localhost:9380" --directory "C:\docs"

    # With API key authentication
    python api_client.py --api-key "your-api-key" --directory "C:\docs"

    # With JWT token
    python api_client.py --token "your-jwt-token" --directory "C:\docs"

    # Get routing recommendations
    python api_client.py --routing --directory "C:\docs"

    # Get HTML report
    python api_client.py --html --directory "C:\docs" --output report.html
"""

import argparse
import json
import sys
import os
from pathlib import Path
from typing import List, Optional
import requests


class DocumentQualityAPIClient:
    """Client for RAGFlow Document Quality Assessment API."""

    def __init__(
        self,
        base_url: str = "http://localhost:9380",
        api_key: Optional[str] = None,
        token: Optional[str] = None
    ):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.token = token

    def _get_headers(self) -> dict:
        """Get request headers with authentication."""
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers

    def assess_directory(
        self,
        directory: str,
        return_html: bool = False,
        config: Optional[dict] = None
    ) -> dict:
        """
        Assess documents in a directory.

        Args:
            directory: Path to directory containing documents
            return_html: Whether to include HTML report
            config: Optional configuration overrides

        Returns:
            Assessment report dictionary
        """
        url = f"{self.base_url}/api/v1/document/quality-inspection"
        payload = {
            "directory": directory,
            "return_html": return_html
        }

        if config:
            payload["config"] = config

        print(f"Calling API: {url}")
        print(f"Directory: {directory}")

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=300  # 5 minutes for large directories
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "response": getattr(e.response, 'text', None)
            }

    def assess_files(
        self,
        file_paths: List[str],
        return_html: bool = False,
        config: Optional[dict] = None
    ) -> dict:
        """
        Assess specific files by their paths.

        Args:
            file_paths: List of file paths to assess
            return_html: Whether to include HTML report
            config: Optional configuration overrides

        Returns:
            Assessment report dictionary
        """
        url = f"{self.base_url}/api/v1/document/quality-inspection"
        payload = {
            "file_paths": file_paths,
            "return_html": return_html
        }

        if config:
            payload["config"] = config

        print(f"Calling API: {url}")
        print(f"Files: {len(file_paths)} files")

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=300
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "response": getattr(e.response, 'text', None)
            }

    def get_routing_recommendations(
        self,
        directory: Optional[str] = None,
        file_paths: Optional[List[str]] = None
    ) -> dict:
        """
        Get document routing recommendations.

        Args:
            directory: Path to directory containing documents
            file_paths: List of specific file paths

        Returns:
            List of routing recommendations
        """
        url = f"{self.base_url}/api/v1/document/quality-inspection/routing"
        payload = {}

        if directory:
            payload["directory"] = directory
        elif file_paths:
            payload["file_paths"] = file_paths
        else:
            return {"success": False, "error": "Must provide directory or file_paths"}

        print(f"Calling API: {url}")

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=300
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "response": getattr(e.response, 'text', None)
            }

    def get_html_report(
        self,
        directory: Optional[str] = None,
        file_paths: Optional[List[str]] = None
    ) -> str:
        """
        Get HTML report for document quality assessment.

        Args:
            directory: Path to directory containing documents
            file_paths: List of specific file paths

        Returns:
            HTML report string
        """
        url = f"{self.base_url}/api/v1/document/quality-inspection/report"
        payload = {}

        if directory:
            payload["directory"] = directory
        elif file_paths:
            payload["file_paths"] = file_paths
        else:
            return "<html><body>Must provide directory or file_paths</body></html>"

        print(f"Calling API: {url}")

        try:
            response = requests.post(
                url,
                headers=self._get_headers(),
                json=payload,
                timeout=300
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            return f"<html><body>Error: {str(e)}</body></html>"


def print_report(report: dict):
    """Print assessment report in a readable format."""
    if not report.get('success'):
        print(f"\n[ERROR] {report.get('error', 'Unknown error')}")
        if 'response' in report:
            print(f"Response: {report.get('response')}")
        return

    data = report.get('data', {})
    if 'message' in data and data.get('total_documents', 0) == 0:
        print(f"\n[INFO] {data.get('message')}")
        return

    print("\n" + "=" * 60)
    print("DOCUMENT QUALITY ASSESSMENT REPORT")
    print("=" * 60)

    # Summary
    summary = data.get('summary', {})
    print(f"\n📊 Summary")
    print(f"   Total Documents: {summary.get('total_documents', 0)}")
    print(f"   Total Size: {summary.get('total_size_mb', 0):.2f} MB")

    # Format distribution
    fmt_dist = data.get('format_distribution', {})
    dist = fmt_dist.get('distribution', {})
    if dist:
        print(f"\n📁 Format Distribution")
        for ext, info in sorted(dist.items(), key=lambda x: x[1]['count'], reverse=True):
            print(f"   {ext}: {info['count']} files ({info['percentage']:.1f}%)")

    # PDF Analysis
    pdf_analysis = data.get('pdf_analysis', {})
    if pdf_analysis.get('total_pdfs', 0) > 0:
        print(f"\n📄 PDF Analysis")
        print(f"   Total PDFs: {pdf_analysis.get('total_pdfs', 0)}")
        by_type = pdf_analysis.get('by_type', {})
        for pdf_type, info in by_type.items():
            print(f"   {pdf_type}: {info.get('count', 0)} files")

    # Sensitive Info
    sensitive = data.get('sensitive_info', {})
    if sensitive.get('total_findings', 0) > 0:
        print(f"\n🔒 Sensitive Information Detected")
        print(f"   Total Findings: {sensitive.get('total_findings', 0)}")
        by_type = sensitive.get('by_type', {})
        for info_type, count in by_type.items():
            emoji = {
                'phone_mobile': '📱',
                'email': '✉️',
                'id_card': '🪪',
                'phone_landline': '📞'
            }.get(info_type, '🔍')
            print(f"   {emoji} {info_type}: {count}")

    # Duplicates
    duplicates = data.get('duplicates', {})
    if duplicates.get('duplicate_groups', 0) > 0:
        print(f"\n🔄 Duplicates Found")
        print(f"   Duplicate Groups: {duplicates.get('duplicate_groups', 0)}")
        print(f"   Duplicate Files: {duplicates.get('duplicate_files', 0)}")

    print("\n" + "=" * 60)


def print_routing(report: dict):
    """Print routing recommendations."""
    if not report.get('success'):
        print(f"\n[ERROR] {report.get('error', 'Unknown error')}")
        return

    data = report.get('data', [])
    if not data:
        print("\n[INFO] No routing recommendations")
        return

    print("\n" + "=" * 60)
    print("DOCUMENT ROUTING RECOMMENDATIONS")
    print("=" * 60)

    # Group by route
    routes = {}
    for item in data:
        route = item.get('recommended_route', 'unknown')
        if route not in routes:
            routes[route] = []
        routes[route].append(item)

    for route, docs in routes.items():
        route_emoji = {
            'ocr': '🔍',
            'text_parser': '📄',
            'docx_parser': '📝',
            'markdown_parser': '📋',
            'excel_parser': '📊',
            'default_parser': '📦'
        }.get(route, '📄')

        print(f"\n{route_emoji} {route.upper().replace('_', ' ')} ({len(docs)} files)")
        for doc in docs[:5]:  # Show first 5
            path = os.path.basename(doc.get('path', 'unknown'))
            tags = doc.get('tags', [])
            priority = doc.get('priority', 'normal')
            flag = ' ⭐' if priority == 'high' else ''
            print(f"   - {path}{flag}")
        if len(docs) > 5:
            print(f"   ... and {len(docs) - 5} more")

    print("\n" + "=" * 60)


def interactive_mode(client: DocumentQualityAPIClient):
    """Run in interactive mode."""
    print("\n" + "=" * 60)
    print("Document Quality Assessment API - Interactive Mode")
    print("=" * 60)

    while True:
        print("\nOptions:")
        print("  1. Assess a directory")
        print("  2. Assess specific files")
        print("  3. Get routing recommendations")
        print("  4. Get HTML report")
        print("  5. Exit")

        choice = input("\nSelect option (1-5): ").strip()

        if choice == '5':
            print("Goodbye!")
            break

        if choice == '1':
            directory = input("Enter directory path: ").strip().strip('"')
            if not directory:
                print("[ERROR] Directory path required")
                continue
            if not os.path.exists(directory):
                print(f"[ERROR] Directory not found: {directory}")
                continue

            html = input("Include HTML report? (y/n): ").strip().lower() == 'y'

            report = client.assess_directory(directory, return_html=html)
            print_report(report)

        elif choice == '2':
            files_input = input("Enter file paths (comma-separated): ").strip()
            if not files_input:
                print("[ERROR] File paths required")
                continue

            file_paths = [f.strip().strip('"') for f in files_input.split(',')]
            file_paths = [f for f in file_paths if os.path.exists(f)]

            if not file_paths:
                print("[ERROR] No valid files found")
                continue

            html = input("Include HTML report? (y/n): ").strip().lower() == 'y'

            report = client.assess_files(file_paths, return_html=html)
            print_report(report)

        elif choice == '3':
            directory = input("Enter directory path (or press Enter for specific files): ").strip().strip('"')

            if directory:
                report = client.get_routing_recommendations(directory=directory)
            else:
                files_input = input("Enter file paths (comma-separated): ").strip()
                if files_input:
                    file_paths = [f.strip().strip('"') for f in files_input.split(',')]
                    report = client.get_routing_recommendations(file_paths=file_paths)
                else:
                    print("[ERROR] Must provide directory or files")
                    continue

            print_routing(report)

        elif choice == '4':
            directory = input("Enter directory path (or press Enter for specific files): ").strip().strip('"')
            output_file = input("Output HTML file (or press Enter for console): ").strip()

            if directory:
                html = client.get_html_report(directory=directory)
            else:
                files_input = input("Enter file paths (comma-separated): ").strip()
                if files_input:
                    file_paths = [f.strip().strip('"') for f in files_input.split(',')]
                    html = client.get_html_report(file_paths=file_paths)
                else:
                    print("[ERROR] Must provide directory or files")
                    continue

            if output_file:
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(html)
                print(f"HTML report saved to: {output_file}")
            else:
                print("\n" + "=" * 60)
                print("HTML REPORT")
                print("=" * 60)
                print(html[:5000])  # Truncate for display


def main():
    parser = argparse.ArgumentParser(
        description='RAGFlow Document Quality Assessment API Client',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Connection options
    parser.add_argument(
        '--base-url', '-u',
        default='http://localhost:9380',
        help='RAGFlow API base URL (default: http://localhost:9380)'
    )
    parser.add_argument(
        '--api-key', '-k',
        help='API key for authentication'
    )
    parser.add_argument(
        '--token', '-t',
        help='JWT token for authentication'
    )

    # Assessment options
    parser.add_argument(
        '--directory', '-d',
        help='Directory to assess'
    )
    parser.add_argument(
        '--file', '-f',
        action='append',
        dest='files',
        help='Specific file to assess (can be used multiple times)'
    )
    parser.add_argument(
        '--routing', '-r',
        action='store_true',
        help='Get routing recommendations instead of full report'
    )
    parser.add_argument(
        '--html',
        action='store_true',
        help='Include HTML report in response'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output file for HTML report'
    )

    # Interactive mode
    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='Run in interactive mode'
    )

    args = parser.parse_args()

    # Create client
    client = DocumentQualityAPIClient(
        base_url=args.base_url,
        api_key=args.api_key,
        token=args.token
    )

    # Interactive mode
    if args.interactive or (not args.directory and not args.files and not args.routing):
        interactive_mode(client)
        return

    # Get API key or token from environment if not provided
    if not args.api_key and not args.token:
        env_api_key = os.environ.get('RAGFLOW_API_KEY')
        env_token = os.environ.get('RAGFLOW_TOKEN')
        if env_api_key:
            client.api_key = env_api_key
        elif env_token:
            client.token = env_token

    # Routing mode
    if args.routing:
        if args.directory:
            report = client.get_routing_recommendations(directory=args.directory)
        elif args.files:
            report = client.get_routing_recommendations(file_paths=args.files)
        else:
            print("[ERROR] Must specify --directory or --file for routing recommendations")
            sys.exit(1)
        print_routing(report)
        return

    # Assessment mode
    if args.html and args.output:
        if args.directory:
            html = client.get_html_report(directory=args.directory)
        else:
            html = client.get_html_report(file_paths=args.files)
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"HTML report saved to: {args.output}")
        return

    # Full assessment
    if args.directory:
        report = client.assess_directory(args.directory, return_html=args.html)
    elif args.files:
        report = client.assess_files(args.files, return_html=args.html)
    else:
        print("[ERROR] Must specify --directory or --file")
        sys.exit(1)

    print_report(report)

    # Save full response if requested
    if args.html:
        output = {
            'report': report,
            'html_report': report.get('data', {}).get('html_report', '')
        }
        output_file = args.output or 'quality_assessment_response.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\nFull response saved to: {output_file}")


if __name__ == '__main__':
    main()
