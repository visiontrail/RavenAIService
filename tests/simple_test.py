#!/usr/bin/env python3
"""
AI日志分析简化测试套件

这是一个独立的测试文件，可以在没有完整项目依赖的情况下运行，
用于验证测试数据和基础功能。
"""

import os
import sys
import json
import time
import unittest
import tempfile
import shutil
import tarfile
import zipfile
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional


class SimpleTestDataValidator:
    """简单的测试数据验证器"""
    
    def __init__(self, test_data_dir: str):
        self.test_data_dir = Path(test_data_dir)
    
    def validate_test_data(self) -> Dict[str, bool]:
        """验证测试数据是否存在且有效"""
        results = {
            "basic_dataset_exists": False,
            "log_files_exist": False,
            "metadata_exists": False,
            "archives_exist": False,
            "file_sizes_valid": False
        }
        
        # 检查基础数据集目录
        basic_dataset = self.test_data_dir / "ai_test_logs"
        if basic_dataset.exists() and basic_dataset.is_dir():
            results["basic_dataset_exists"] = True
            
            # 检查日志文件
            expected_files = [
                "protocol_stack.log",
                "oam_antenna.log", 
                "application.log"
            ]
            
            existing_files = 0
            for file_name in expected_files:
                file_path = basic_dataset / file_name
                if file_path.exists() and file_path.is_file():
                    existing_files += 1
            
            if existing_files == len(expected_files):
                results["log_files_exist"] = True
            
            # 检查元数据文件
            metadata_file = basic_dataset / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        if "log_package_info" in metadata and "log_components" in metadata:
                            results["metadata_exists"] = True
                except Exception:
                    pass
        
        # 检查压缩包
        tar_file = self.test_data_dir / "ai_test_logs.tar.gz"
        zip_file = self.test_data_dir / "ai_test_logs.zip"
        
        if tar_file.exists() and zip_file.exists():
            results["archives_exist"] = True
        
        # 检查文件大小（基本合理性检查）
        if results["log_files_exist"]:
            total_size = 0
            for file_name in expected_files:
                file_path = basic_dataset / file_name
                if file_path.exists():
                    total_size += file_path.stat().st_size
            
            # 期望总大小在50KB到1MB之间
            if 50 * 1024 <= total_size <= 1024 * 1024:
                results["file_sizes_valid"] = True
        
        return results
    
    def analyze_log_content(self) -> Dict[str, Any]:
        """分析日志内容的基本统计"""
        analysis = {
            "total_lines": 0,
            "error_lines": 0,
            "warn_lines": 0,
            "info_lines": 0,
            "components_found": set(),
            "time_range": {"start": None, "end": None}
        }
        
        basic_dataset = self.test_data_dir / "ai_test_logs"
        if not basic_dataset.exists():
            return analysis
        
        log_files = [
            "protocol_stack.log",
            "oam_antenna.log",
            "application.log"
        ]
        
        for file_name in log_files:
            file_path = basic_dataset / file_name
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            
                            analysis["total_lines"] += 1
                            
                            # 统计日志级别
                            if "[ERROR]" in line or "[FATAL]" in line:
                                analysis["error_lines"] += 1
                            elif "[WARN]" in line:
                                analysis["warn_lines"] += 1
                            elif "[INFO]" in line or "[DEBUG]" in line:
                                analysis["info_lines"] += 1
                            
                            # 提取组件名称
                            if "STACK_" in line:
                                for component in ["STACK_CUCP", "STACK_CUUP", "STACK_DU"]:
                                    if component in line:
                                        analysis["components_found"].add(component)
                            
                            if "OAM" in line:
                                for component in ["CUUP_OAM", "DU_OAM", "DVB_OAM", "MAIN_OAM"]:
                                    if component in line:
                                        analysis["components_found"].add(component)
                            
                            if any(comp in line for comp in ["APP", "HTTP", "DB", "CACHE"]):
                                for component in ["APP", "HTTP", "DB", "CACHE"]:
                                    if component in line:
                                        analysis["components_found"].add(component)
                
                except Exception as e:
                    print(f"分析文件 {file_name} 时出错: {e}")
        
        analysis["components_found"] = list(analysis["components_found"])
        return analysis


class TestBasicFunctionality(unittest.TestCase):
    """基础功能测试"""
    
    def setUp(self):
        self.test_data_dir = Path(__file__).resolve().parent.parent / "test_data"
        self.validator = SimpleTestDataValidator(self.test_data_dir)
    
    def test_test_data_exists(self):
        """测试数据存在性检查"""
        results = self.validator.validate_test_data()
        
        self.assertTrue(results["basic_dataset_exists"], "基础数据集目录不存在")
        self.assertTrue(results["log_files_exist"], "日志文件不完整")
        self.assertTrue(results["metadata_exists"], "元数据文件无效")
        self.assertTrue(results["archives_exist"], "压缩包文件不存在")
        self.assertTrue(results["file_sizes_valid"], "文件大小不合理")
    
    def test_log_content_analysis(self):
        """日志内容分析测试"""
        analysis = self.validator.analyze_log_content()
        
        self.assertGreater(analysis["total_lines"], 100, "日志行数太少")
        self.assertGreater(analysis["error_lines"], 0, "没有错误日志")
        self.assertGreater(analysis["info_lines"], 0, "没有信息日志")
        self.assertGreater(len(analysis["components_found"]), 3, "组件类型太少")
    
    def test_metadata_content(self):
        """元数据内容测试"""
        metadata_file = self.test_data_dir / "ai_test_logs" / "metadata.json"
        
        self.assertTrue(metadata_file.exists(), "元数据文件不存在")
        
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # 检查必要字段
        self.assertIn("log_package_info", metadata)
        self.assertIn("log_components", metadata)
        self.assertIn("system_info", metadata)
        
        # 检查包信息
        package_info = metadata["log_package_info"]
        self.assertIn("package_name", package_info)
        self.assertIn("created_time", package_info)
        self.assertIn("total_size", package_info)
        self.assertIn("file_count", package_info)
        
        # 检查组件信息
        components = metadata["log_components"]
        self.assertIsInstance(components, list)
        self.assertGreater(len(components), 0)
        
        for component in components:
            self.assertIn("component_name", component)
            self.assertIn("log_level", component)
            self.assertIn("file_path", component)
    
    def test_archive_integrity(self):
        """压缩包完整性测试"""
        tar_file = self.test_data_dir / "ai_test_logs.tar.gz"
        zip_file = self.test_data_dir / "ai_test_logs.zip"
        
        # 测试TAR.GZ文件
        self.assertTrue(tar_file.exists(), "TAR.GZ文件不存在")
        
        try:
            with tarfile.open(tar_file, "r:gz") as tar:
                members = tar.getnames()
                self.assertIn("protocol_stack.log", members)
                self.assertIn("oam_antenna.log", members)
                self.assertIn("application.log", members)
                self.assertIn("metadata.json", members)
        except Exception as e:
            self.fail(f"TAR.GZ文件损坏: {e}")
        
        # 测试ZIP文件
        self.assertTrue(zip_file.exists(), "ZIP文件不存在")
        
        try:
            with zipfile.ZipFile(zip_file, "r") as zip_archive:
                members = zip_archive.namelist()
                self.assertIn("protocol_stack.log", members)
                self.assertIn("oam_antenna.log", members)
                self.assertIn("application.log", members)
                self.assertIn("metadata.json", members)
        except Exception as e:
            self.fail(f"ZIP文件损坏: {e}")


class TestSimpleGrep(unittest.TestCase):
    """简单的grep功能测试"""
    
    def setUp(self):
        self.test_data_dir = Path(__file__).resolve().parent.parent / "test_data"
        self.log_dir = self.test_data_dir / "ai_test_logs"
    
    def simple_grep(self, file_path: Path, pattern: str, max_lines: int = 100) -> List[str]:
        """简单的grep实现"""
        results = []
        if not file_path.exists():
            return results
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if pattern.lower() in line.lower():
                        results.append(f"{line_num}: {line.strip()}")
                        if len(results) >= max_lines:
                            break
        except Exception:
            pass
        
        return results
    
    def test_grep_error_logs(self):
        """测试搜索错误日志"""
        for log_file in ["protocol_stack.log", "oam_antenna.log", "application.log"]:
            file_path = self.log_dir / log_file
            if file_path.exists():
                results = self.simple_grep(file_path, "ERROR")
                # 应该能找到一些错误日志
                self.assertGreater(len(results), 0, f"在{log_file}中没有找到ERROR日志")
    
    def test_grep_components(self):
        """测试搜索组件名称"""
        component_patterns = ["STACK_", "OAM", "APP", "HTTP"]
        
        for pattern in component_patterns:
            found_in_any_file = False
            for log_file in ["protocol_stack.log", "oam_antenna.log", "application.log"]:
                file_path = self.log_dir / log_file
                if file_path.exists():
                    results = self.simple_grep(file_path, pattern)
                    if results:
                        found_in_any_file = True
                        break
            
            self.assertTrue(found_in_any_file, f"在任何日志文件中都没有找到组件模式: {pattern}")


class TestPerformanceBasic(unittest.TestCase):
    """基础性能测试"""
    
    def setUp(self):
        self.test_data_dir = Path(__file__).resolve().parent.parent / "test_data"
        self.log_dir = self.test_data_dir / "ai_test_logs"
    
    def test_file_reading_performance(self):
        """测试文件读取性能"""
        for log_file in ["protocol_stack.log", "oam_antenna.log", "application.log"]:
            file_path = self.log_dir / log_file
            if file_path.exists():
                start_time = time.time()
                
                line_count = 0
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line_count += 1
                except Exception:
                    pass
                
                end_time = time.time()
                duration = end_time - start_time
                
                # 基本性能检查：读取应该在合理时间内完成
                self.assertLess(duration, 5.0, f"读取{log_file}耗时过长: {duration:.2f}秒")
                self.assertGreater(line_count, 0, f"{log_file}为空文件")
    
    def test_memory_usage_basic(self):
        """基础内存使用测试"""
        try:
            import psutil
            process = psutil.Process()
            
            # 记录初始内存使用
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            # 读取所有日志文件
            total_lines = 0
            for log_file in ["protocol_stack.log", "oam_antenna.log", "application.log"]:
                file_path = self.log_dir / log_file
                if file_path.exists():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            total_lines += 1
            
            # 记录最终内存使用
            final_memory = process.memory_info().rss / 1024 / 1024  # MB
            memory_increase = final_memory - initial_memory
            
            # 内存增长应该在合理范围内
            self.assertLess(memory_increase, 100, f"内存使用增长过多: {memory_increase:.2f}MB")
            self.assertGreater(total_lines, 100, "读取的日志行数太少")
            
        except ImportError:
            self.skipTest("psutil模块不可用，跳过内存测试")


def run_simple_tests(test_type: str = "all", verbose: bool = False) -> bool:
    """运行简化测试"""
    
    # 配置测试套件
    test_classes = []
    
    if test_type in ["all", "unit"]:
        test_classes.extend([
            TestBasicFunctionality,
            TestSimpleGrep
        ])
    
    if test_type in ["all", "performance"]:
        test_classes.append(TestPerformanceBasic)
    
    # 创建测试套件
    suite = unittest.TestSuite()
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # 运行测试
    verbosity = 2 if verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stdout)
    
    print(f"🔬 运行简化AI日志分析测试 (类型: {test_type})")
    print("=" * 60)
    
    start_time = time.time()
    result = runner.run(suite)
    end_time = time.time()
    
    # 输出结果摘要
    print("\n" + "=" * 60)
    print("📊 测试结果摘要")
    print("=" * 60)
    print(f"执行时间: {end_time - start_time:.2f}秒")
    print(f"总测试数: {result.testsRun}")
    print(f"成功数量: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败数量: {len(result.failures)}")
    print(f"错误数量: {len(result.errors)}")
    print(f"跳过数量: {len(result.skipped) if hasattr(result, 'skipped') else 0}")
    
    if result.failures:
        print("\n❌ 失败的测试:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split('AssertionError: ')[-1].split('\\n')[0]}")
    
    if result.errors:
        print("\n💥 错误的测试:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split('\\n')[-2]}")
    
    success = len(result.failures) == 0 and len(result.errors) == 0
    print(f"\n🎯 整体结果: {'✅ 成功' if success else '❌ 失败'}")
    
    return success


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="AI日志分析简化测试套件")
    parser.add_argument(
        "--test-type",
        choices=["all", "unit", "performance"],
        default="all",
        help="测试类型 (默认: all)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细输出"
    )
    parser.add_argument(
        "--test-data-dir",
        default="test_data",
        help="测试数据目录 (默认: test_data)"
    )
    
    args = parser.parse_args()
    
    # 检查测试数据目录
    test_data_dir = Path(__file__).resolve().parent.parent / args.test_data_dir
    if not test_data_dir.exists():
        print(f"❌ 测试数据目录不存在: {test_data_dir}")
        print("请先运行以下命令生成测试数据:")
        print("  python3 tests/test_data_generator.py")
        sys.exit(1)
    
    # 运行测试
    success = run_simple_tests(args.test_type, args.verbose)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()