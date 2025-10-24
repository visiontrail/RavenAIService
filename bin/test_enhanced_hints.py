#!/usr/bin/env python3
"""
Test script to verify the enhanced hints mechanism in LogAnalysisAgent.

This script tests the new intelligent file selection and enhanced hints features.
"""
import argparse
import os
import sys
import tempfile
import shutil
from typing import Dict, Any

# Ensure project root is on path when running directly
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, PROJECT_ROOT)

from app.main import setup_logging
from app.config import settings
from app.agents.log_agent import LogAnalysisAgent


def create_test_log_files(temp_dir: str) -> Dict[str, str]:
    """创建测试用的日志文件"""
    files = {}
    
    # 创建错误日志文件
    error_log = os.path.join(temp_dir, "error.log")
    with open(error_log, "w", encoding="utf-8") as f:
        f.write("""2024-01-15 10:30:15 [ERROR] Database connection failed
2024-01-15 10:30:16 [ERROR] Failed to authenticate user
2024-01-15 10:30:17 [INFO] Retrying connection...
2024-01-15 10:30:18 [ERROR] Connection timeout after 30 seconds
2024-01-15 10:30:19 [WARN] Falling back to backup database
""")
    files["error"] = error_log
    
    # 创建天线操作日志文件
    antenna_log = os.path.join(temp_dir, "antenna_operation.log")
    with open(antenna_log, "w", encoding="utf-8") as f:
        f.write("""2024-01-15 10:25:00 [INFO] Antenna initialization started
2024-01-15 10:25:01 [INFO] Antenna calibration in progress
2024-01-15 10:25:02 [ERROR] Antenna positioning error detected
2024-01-15 10:25:03 [WARN] Signal strength below threshold
2024-01-15 10:25:04 [INFO] Antenna operation completed
""")
    files["antenna"] = antenna_log
    
    # 创建系统日志文件
    system_log = os.path.join(temp_dir, "system.log")
    with open(system_log, "w", encoding="utf-8") as f:
        f.write("""2024-01-15 10:20:00 [INFO] System startup initiated
2024-01-15 10:20:01 [INFO] Loading configuration files
2024-01-15 10:20:02 [INFO] Services started successfully
2024-01-15 10:20:03 [DEBUG] Memory usage: 45%
2024-01-15 10:20:04 [INFO] System ready
""")
    files["system"] = system_log
    
    # 创建普通文本文件
    readme_file = os.path.join(temp_dir, "README.txt")
    with open(readme_file, "w", encoding="utf-8") as f:
        f.write("""This is a test log package.
Contains various log files for testing purposes.
""")
    files["readme"] = readme_file
    
    return files


def test_intelligent_file_selection():
    """测试智能文件选择功能"""
    print("=== 测试智能文件选择功能 ===")
    
    # 创建临时目录和测试文件
    temp_dir = tempfile.mkdtemp()
    try:
        files = create_test_log_files(temp_dir)
        agent = LogAnalysisAgent()
        
        # 测试1: 查询错误相关内容
        print("\n1. 测试错误相关查询:")
        query = "查找系统中的错误信息"
        relevant_files = agent._select_relevant_files(temp_dir, query, max_files=3)
        print(f"查询: {query}")
        print(f"选择的文件: {[os.path.basename(f) for f in relevant_files]}")
        
        # 测试2: 查询天线相关内容
        print("\n2. 测试天线相关查询:")
        query = "分析天线操作日志"
        relevant_files = agent._select_relevant_files(temp_dir, query, max_files=3)
        print(f"查询: {query}")
        print(f"选择的文件: {[os.path.basename(f) for f in relevant_files]}")
        
        # 测试3: 通用查询
        print("\n3. 测试通用查询:")
        query = "查看系统状态"
        relevant_files = agent._select_relevant_files(temp_dir, query, max_files=3)
        print(f"查询: {query}")
        print(f"选择的文件: {[os.path.basename(f) for f in relevant_files]}")
        
    finally:
        shutil.rmtree(temp_dir)


def test_enhanced_hints_generation():
    """测试增强hints生成功能"""
    print("\n=== 测试增强hints生成功能 ===")
    
    # 创建临时目录和测试文件
    temp_dir = tempfile.mkdtemp()
    try:
        files = create_test_log_files(temp_dir)
        agent = LogAnalysisAgent()
        
        # 测试增强hints生成
        query = "查找天线错误信息"
        archive_path = "/fake/archive.tar.gz"
        enhanced_hints = agent._generate_enhanced_hints(temp_dir, query, archive_path)
        
        print(f"查询: {query}")
        print(f"生成的增强hints:")
        print(f"  - 主要文件: {os.path.basename(enhanced_hints.get('primary_file', '')) if enhanced_hints.get('primary_file') else 'None'}")
        print(f"  - 相关文件数量: {len(enhanced_hints.get('relevant_files', []))}")
        print(f"  - 相关文件: {[os.path.basename(f) for f in enhanced_hints.get('relevant_files', [])]}")
        print(f"  - 建议搜索模式: {enhanced_hints.get('suggested_patterns', [])}")
        print(f"  - 文件结构: {enhanced_hints.get('file_structure', {})}")
        print(f"  - 检测到的关键词: {enhanced_hints.get('query_context', {}).get('detected_keywords', [])}")
        
    finally:
        shutil.rmtree(temp_dir)


def test_keyword_extraction():
    """测试关键词提取功能"""
    print("\n=== 测试关键词提取功能 ===")
    
    agent = LogAnalysisAgent()
    
    test_queries = [
        "查找系统错误信息",
        "分析天线操作日志",
        "检查网络连接问题",
        "查看性能告警",
        "系统启动失败分析"
    ]
    
    for query in test_queries:
        keywords = agent._extract_keywords_from_query(query)
        print(f"查询: '{query}' -> 关键词: {keywords}")


def test_dynamic_hints_update():
    """测试动态hints更新功能"""
    print("\n=== 测试动态hints更新功能 ===")
    
    agent = LogAnalysisAgent()
    
    # 模拟初始hints
    initial_hints = {
        "relevant_files": ["/tmp/error.log", "/tmp/system.log"],
        "primary_file": "/tmp/error.log",
        "suggested_patterns": ["ERROR", "FAIL"],
        "path": "/tmp/error.log"
    }
    
    # 测试1: grep_search没有找到结果的情况
    print("\n1. 测试grep_search无结果时的hints更新:")
    tool_result = "<document>No matches found for pattern 'CRITICAL' in file /tmp/error.log</document>"
    updated_hints = agent._update_hints_after_tool_execution(
        initial_hints, "grep_search", tool_result, "查找严重错误"
    )
    print(f"原始hints键数: {len(initial_hints)}")
    print(f"更新后hints键数: {len(updated_hints)}")
    if "suggestion" in updated_hints:
        print(f"建议: {updated_hints['suggestion']}")
    if "pattern_suggestion" in updated_hints:
        print(f"模式建议: {updated_hints['pattern_suggestion']}")
    
    # 测试2: read_snippet成功的情况
    print("\n2. 测试read_snippet成功时的hints更新:")
    tool_result = """<document>
2024-01-15 10:30:15 [ERROR] Database connection failed
2024-01-15 10:30:16 [WARN] Network timeout detected
2024-01-15 10:30:17 [INFO] Service restart initiated
2024-01-15 10:30:18 [DEBUG] Configuration loaded
</document>"""
    updated_hints = agent._update_hints_after_tool_execution(
        initial_hints, "read_snippet", tool_result, "查看日志内容"
    )
    print(f"原始hints键数: {len(initial_hints)}")
    print(f"更新后hints键数: {len(updated_hints)}")
    if "content_based_patterns" in updated_hints:
        print(f"基于内容的搜索模式: {updated_hints['content_based_patterns']}")
    if "content_suggestion" in updated_hints:
        print(f"内容建议: {updated_hints['content_suggestion']}")
    
    # 测试3: 内容关键词提取
    print("\n3. 测试内容关键词提取:")
    test_content = """
    2024-01-15 ERROR: Database connection failed
    2024-01-15 WARN: Network antenna initialization error
    2024-01-15 INFO: System service start completed
    2024-01-15 DEBUG: Authentication config loaded
    """
    keywords = agent._extract_content_keywords(test_content)
    print(f"提取的关键词: {keywords}")


def main():
    parser = argparse.ArgumentParser(description="Test enhanced hints mechanism")
    parser.add_argument("--test", choices=["file_selection", "hints_generation", "keyword_extraction", "dynamic", "all"], 
                       default="all", help="Which test to run")
    
    args = parser.parse_args()
    
    setup_logging()
    
    print("开始测试增强hints机制...")
    
    if args.test in ["file_selection", "all"]:
        test_intelligent_file_selection()
    
    if args.test in ["hints_generation", "all"]:
        test_enhanced_hints_generation()
    
    if args.test in ["keyword_extraction", "all"]:
        test_keyword_extraction()
    
    if args.test in ["dynamic", "all"]:
        test_dynamic_hints_update()
    
    print("\n测试完成!")


if __name__ == "__main__":
    main()