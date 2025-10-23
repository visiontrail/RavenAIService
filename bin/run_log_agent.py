#!/usr/bin/env python3
"""
Simple CLI to run the Log Analysis Agent.
Usage:
  python bin/run_log_agent.py --query "查找ERROR并读取片段" --hint-archive uploads/sample.tar.gz
"""
import argparse
from typing import Dict

from app.agents.log_agent import demo_agent_run


def main():
    parser = argparse.ArgumentParser(description="Run Log Analysis Agent")
    parser.add_argument("--query", required=True, help="User query, e.g. '提取元数据; grep ERROR' ")
    parser.add_argument("--hint-archive", dest="archive", default=None, help="Archive path for metadata tool")
    parser.add_argument("--hint-path", dest="path", default=None, help="File path for grep/head/tail")
    parser.add_argument("--hint-pattern", dest="pattern", default=None, help="Pattern for grep")
    args = parser.parse_args()

    hints: Dict[str, str] = {}
    if args.archive:
        hints["archive_path"] = args.archive
    if args.path:
        hints["path"] = args.path
    if args.pattern:
        hints["pattern"] = args.pattern

    xml = demo_agent_run(args.query, hints=hints)
    print(xml)


if __name__ == "__main__":
    main()