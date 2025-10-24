#!/usr/bin/env python3
"""
Test script to run LogAnalysisAgent on a specified log file.

Usage examples:
  python bin/test_log_agent_file.py --file uploads/example.log --pattern ERROR
  python bin/test_log_agent_file.py --file uploads/example.log --query "读取日志片段; grep 错误"

This script configures logging and invokes the agent with hints so you can quickly
verify behavior against a single log file.
"""
import argparse
import os
import sys
from typing import Dict

# Ensure project root is on path when running directly
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from app.main import setup_logging  # re-use app logging configuration
from app.config import settings
from app.agents.log_agent import demo_agent_run


def main():
    parser = argparse.ArgumentParser(description="Run LogAnalysisAgent on a specified log file")
    parser.add_argument("--file", dest="file", required=True, help="Path to the log file to analyze")
    parser.add_argument("--pattern", dest="pattern", default="ERROR", help="Pattern to grep (default: ERROR)")
    parser.add_argument(
        "--query",
        dest="query",
        default=None,
        help="Agent query (defaults to '读取日志片段; grep <pattern>')",
    )
    parser.add_argument("--lines", dest="lines", type=int, default=50, help="Lines for head/tail reading")
    parser.add_argument("--log-file", dest="log_file", default=None, help="Write logs to specified file (optional)")

    args = parser.parse_args()

    if args.log_file:
        # Override default log file path before initializing logging
        settings.log_file_path = args.log_file
    setup_logging()

    if not os.path.isfile(args.file):
        print(f"[ERROR] Specified file does not exist: {args.file}")
        sys.exit(1)

    query = args.query or f"读取日志片段; grep {args.pattern}"

    hints: Dict[str, str] = {
        "path": args.file,
        "pattern": args.pattern,
    }

    print("[INFO] Running LogAnalysisAgent...")
    print(f"[INFO] Query: {query}")
    print(f"[INFO] File: {args.file}")
    print(f"[INFO] Pattern: {args.pattern}")

    result_xml = demo_agent_run(query, hints=hints)

    print("\n===== Agent Output (XML) =====")
    print(result_xml)
    print("===== End =====")


if __name__ == "__main__":
    main()