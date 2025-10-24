#!/usr/bin/env python3
"""
AI日志分析测试运行器

提供便捷的测试执行、结果报告和测试数据管理功能
"""

import os
import sys
import time
import json
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional


class TestRunner:
    """测试运行器"""
    
    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parent.parent
        self.test_data_dir = self.project_root / "test_data"
        self.test_results_dir = self.project_root / "test_results"
        self.test_results_dir.mkdir(exist_ok=True)
        
        # 测试配置
        self.test_configs = {
            "unit": {
                "description": "单元测试 - 测试各个工具函数和基础功能",
                "timeout": 300,  # 5分钟
                "required_data": ["ai_test_logs"]
            },
            "integration": {
                "description": "集成测试 - 测试Agent完整流程和DeepSeek集成",
                "timeout": 600,  # 10分钟
                "required_data": ["ai_test_logs"]
            },
            "performance": {
                "description": "性能测试 - 测试大文件处理和并发性能",
                "timeout": 1200,  # 20分钟
                "required_data": ["performance_ai_test_logs"]
            },
            "all": {
                "description": "完整测试套件 - 运行所有测试",
                "timeout": 1800,  # 30分钟
                "required_data": ["ai_test_logs", "performance_ai_test_logs"]
            }
        }
    
    def check_dependencies(self) -> Dict[str, bool]:
        """检查测试依赖"""
        dependencies = {
            "python_modules": True,
            "test_files": True,
            "test_data": True,
            "deepseek_config": True
        }
        
        # 检查Python模块
        required_modules = [
            "unittest", "asyncio", "pathlib", "json", "tarfile", 
            "zipfile", "tempfile", "shutil", "psutil", "time"
        ]
        
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                print(f"❌ 缺少Python模块: {module}")
                dependencies["python_modules"] = False
        
        # 检查测试文件
        test_files = [
            "tests/test_ai_log_analysis.py",
            "tests/test_data_generator.py"
        ]
        
        for test_file in test_files:
            if not (self.project_root / test_file).exists():
                print(f"❌ 缺少测试文件: {test_file}")
                dependencies["test_files"] = False
        
        # 检查核心代码文件
        core_files = [
            "app/agents/log_agent.py",
            "app/tools/grep_tool.py",
            "app/tools/metadata_tool.py", 
            "app/tools/fs_tools.py",
            "app/config.py"
        ]
        
        for core_file in core_files:
            if not (self.project_root / core_file).exists():
                print(f"⚠️  核心文件不存在: {core_file}")
        
        # 检查配置
        config_file = self.project_root / "app" / "config.py"
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_content = f.read()
                    if 'deepseek' in config_content.lower():
                        print("✅ DeepSeek配置已找到")
                    else:
                        print("⚠️  未找到DeepSeek配置")
                        dependencies["deepseek_config"] = False
            except Exception as e:
                print(f"❌ 配置文件读取失败: {e}")
                dependencies["deepseek_config"] = False
        
        return dependencies
    
    def setup_test_data(self, force_regenerate: bool = False) -> bool:
        """设置测试数据"""
        print("🔧 设置测试数据...")
        
        # 检查是否需要生成测试数据
        basic_data_exists = (self.test_data_dir / "ai_test_logs").exists()
        performance_data_exists = (self.test_data_dir / "performance_ai_test_logs").exists()
        
        if force_regenerate or not basic_data_exists:
            print("📊 生成基础测试数据...")
            try:
                result = subprocess.run([
                    sys.executable, "tests/test_data_generator.py",
                    "--output-dir", str(self.test_data_dir),
                    "--dataset-name", "ai_test_logs"
                ], cwd=self.project_root, capture_output=True, text=True, timeout=120)
                
                if result.returncode != 0:
                    print(f"❌ 基础测试数据生成失败: {result.stderr}")
                    return False
                print("✅ 基础测试数据生成完成")
            except subprocess.TimeoutExpired:
                print("❌ 基础测试数据生成超时")
                return False
            except Exception as e:
                print(f"❌ 基础测试数据生成异常: {e}")
                return False
        
        if force_regenerate or not performance_data_exists:
            print("📊 生成性能测试数据...")
            try:
                result = subprocess.run([
                    sys.executable, "tests/test_data_generator.py",
                    "--output-dir", str(self.test_data_dir),
                    "--dataset-name", "ai_test_logs",
                    "--performance"
                ], cwd=self.project_root, capture_output=True, text=True, timeout=300)
                
                if result.returncode != 0:
                    print(f"❌ 性能测试数据生成失败: {result.stderr}")
                    return False
                print("✅ 性能测试数据生成完成")
            except subprocess.TimeoutExpired:
                print("❌ 性能测试数据生成超时")
                return False
            except Exception as e:
                print(f"❌ 性能测试数据生成异常: {e}")
                return False
        
        return True
    
    def run_test_suite(self, test_type: str = "all", verbose: bool = False, 
                      save_results: bool = True) -> Dict[str, Any]:
        """运行测试套件"""
        if test_type not in self.test_configs:
            raise ValueError(f"未知的测试类型: {test_type}")
        
        config = self.test_configs[test_type]
        print(f"🚀 开始运行测试: {config['description']}")
        
        # 记录开始时间
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 构建测试命令
        cmd = [
            sys.executable, "tests/test_ai_log_analysis.py",
            "--test-type", test_type
        ]
        
        # 测试脚本内部处理详细输出，不传递 --verbose
        
        # 运行测试
        try:
            print(f"⏱️  超时设置: {config['timeout']}秒")
            result = subprocess.run(
                cmd, 
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=config['timeout']
            )
            
            end_time = time.time()
            duration = end_time - start_time
            
            # 处理输出为更易读的结构
            stdout_lines = result.stdout.splitlines() if result.stdout else []
            stderr_lines = result.stderr.splitlines() if result.stderr else []
            stdout_preview = "\n".join(stdout_lines[:20]) if stdout_lines else ""
            stderr_preview = "\n".join(stderr_lines[:20]) if stderr_lines else ""
            
            # 保存原始文本输出为独立文件，避免JSON中的\n转义
            stdout_path = self._save_text_output(result.stdout, "stdout", timestamp)
            stderr_path = self._save_text_output(result.stderr, "stderr", timestamp)
            
            # 解析测试结果
            test_results = {
                "test_type": test_type,
                "timestamp": timestamp,
                "duration": duration,
                "return_code": result.returncode,
                "success": result.returncode == 0,
                # 新增可读性字段
                "stdout_lines": stdout_lines,
                "stderr_lines": stderr_lines,
                "stdout_preview": stdout_preview,
                "stderr_preview": stderr_preview,
                "stdout_path": stdout_path,
                "stderr_path": stderr_path,
                "config": config
            }
            
            # 尝试解析JSON输出（从stdout末尾提取）
            try:
                if result.stdout and result.stdout.strip():
                    lines = result.stdout.strip().split('\n')
                    for line in reversed(lines):
                        if line.startswith('{') and line.endswith('}'):
                            test_results["detailed_results"] = json.loads(line)
                            break
            except json.JSONDecodeError:
                pass
            
            # 保存结果
            if save_results:
                self.save_test_results(test_results, timestamp)
            
            # 显示结果摘要
            self.display_test_summary(test_results)
            
            return test_results
            
        except subprocess.TimeoutExpired:
            end_time = time.time()
            duration = end_time - start_time
            
            test_results = {
                "test_type": test_type,
                "timestamp": timestamp,
                "duration": duration,
                "return_code": -1,
                "success": False,
                "error": "测试超时",
                "timeout": config['timeout'],
                "config": config
            }
            
            if save_results:
                self.save_test_results(test_results, timestamp)
            
            print(f"❌ 测试超时 ({config['timeout']}秒)")
            return test_results
            
        except Exception as e:
            test_results = {
                "test_type": test_type,
                "timestamp": timestamp,
                "duration": 0,
                "return_code": -2,
                "success": False,
                "error": str(e),
                "config": config
            }
            
            if save_results:
                self.save_test_results(test_results, timestamp)
            
            print(f"❌ 测试执行异常: {e}")
            return test_results

    def _save_text_output(self, content: Optional[str], kind: str, timestamp: str) -> Optional[str]:
        """将原始文本输出保存为独立文件，并返回路径"""
        if not content:
            return None
        try:
            file_path = self.test_results_dir / f"test_results_{timestamp}.{kind}.txt"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return str(file_path)
        except Exception as e:
            print(f"⚠️  保存{kind}输出失败: {e}")
            return None
    
    def save_test_results(self, results: Dict[str, Any], timestamp: str):
        """保存测试结果"""
        results_file = self.test_results_dir / f"test_results_{timestamp}.json"
        
        try:
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False, default=str)
            print(f"📄 测试结果已保存: {results_file}")
        except Exception as e:
            print(f"⚠️  保存测试结果失败: {e}")
    
    def display_test_summary(self, results: Dict[str, Any]):
        """显示测试摘要"""
        print("\n" + "="*60)
        print("📊 测试结果摘要")
        print("="*60)
        
        print(f"测试类型: {results['test_type']}")
        print(f"执行时间: {results['duration']:.2f}秒")
        print(f"测试状态: {'✅ 成功' if results['success'] else '❌ 失败'}")
        
        if 'detailed_results' in results:
            detailed = results['detailed_results']
            if 'summary' in detailed:
                summary = detailed['summary']
                print(f"总测试数: {summary.get('total_tests', 'N/A')}")
                print(f"成功数量: {summary.get('passed', 'N/A')}")
                print(f"失败数量: {summary.get('failed', 'N/A')}")
                print(f"跳过数量: {summary.get('skipped', 'N/A')}")
        
        if not results['success']:
            if 'error' in results:
                print(f"错误信息: {results['error']}")
            elif results.get('stderr_preview') or results.get('stderr_lines'):
                print("错误输出预览:")
                preview = results.get('stderr_preview') or "\n".join(results.get('stderr_lines', [])[:20])
                print(preview)
            if results.get('stderr_path'):
                print(f"完整错误输出: {results['stderr_path']}")
        
        # 提示查看完整stdout
        if results.get('stdout_path'):
            print(f"完整标准输出: {results['stdout_path']}")
        
        print("="*60)
    
    def list_test_results(self, limit: int = 10):
        """列出历史测试结果"""
        print("📋 历史测试结果:")
        
        result_files = sorted(
            self.test_results_dir.glob("test_results_*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        if not result_files:
            print("  暂无测试结果")
            return
        
        for i, result_file in enumerate(result_files[:limit]):
            try:
                with open(result_file, 'r', encoding='utf-8') as f:
                    result = json.load(f)
                
                status = "✅" if result.get('success') else "❌"
                test_type = result.get('test_type', 'unknown')
                duration = result.get('duration', 0)
                timestamp = result.get('timestamp', 'unknown')
                
                print(f"  {i+1}. {status} {test_type} - {duration:.1f}s - {timestamp}")
                
            except Exception as e:
                print(f"  {i+1}. ❓ {result_file.name} - 读取失败: {e}")
    
    def clean_test_data(self):
        """清理测试数据"""
        print("🧹 清理测试数据...")
        
        if self.test_data_dir.exists():
            import shutil
            shutil.rmtree(self.test_data_dir)
            print(f"✅ 已删除测试数据目录: {self.test_data_dir}")
        else:
            print("ℹ️  测试数据目录不存在")
    
    def clean_test_results(self, keep_latest: int = 5):
        """清理测试结果"""
        print(f"🧹 清理测试结果（保留最新{keep_latest}个）...")
        
        result_files = sorted(
            self.test_results_dir.glob("test_results_*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        deleted_count = 0
        for result_file in result_files[keep_latest:]:
            try:
                result_file.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"⚠️  删除失败 {result_file}: {e}")
        
        print(f"✅ 已删除 {deleted_count} 个旧的测试结果文件")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="AI日志分析测试运行器")
    parser.add_argument("--test-type", choices=["unit", "integration", "performance", "all"], 
                       default="all", help="测试类型")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--setup-data", action="store_true", help="重新生成测试数据")
    parser.add_argument("--check-deps", action="store_true", help="检查依赖")
    parser.add_argument("--list-results", action="store_true", help="列出历史测试结果")
    parser.add_argument("--clean-data", action="store_true", help="清理测试数据")
    parser.add_argument("--clean-results", action="store_true", help="清理测试结果")
    parser.add_argument("--project-root", help="项目根目录")
    
    args = parser.parse_args()
    
    # 创建测试运行器
    runner = TestRunner(args.project_root)
    
    print("🔬 AI日志分析测试运行器")
    print("="*50)
    
    # 执行操作
    if args.check_deps:
        print("🔍 检查依赖...")
        deps = runner.check_dependencies()
        all_good = all(deps.values())
        print(f"依赖检查结果: {'✅ 全部满足' if all_good else '❌ 存在问题'}")
        if not all_good:
            sys.exit(1)
    
    if args.clean_data:
        runner.clean_test_data()
        return
    
    if args.clean_results:
        runner.clean_test_results()
        return
    
    if args.list_results:
        runner.list_test_results()
        return
    
    if args.setup_data:
        if not runner.setup_test_data(force_regenerate=True):
            print("❌ 测试数据设置失败")
            sys.exit(1)
        return
    
    # 检查依赖
    deps = runner.check_dependencies()
    if not all(deps.values()):
        print("❌ 依赖检查失败，请先解决依赖问题")
        sys.exit(1)
    
    # 设置测试数据
    if not runner.setup_test_data():
        print("❌ 测试数据设置失败")
        sys.exit(1)
    
    # 运行测试
    results = runner.run_test_suite(
        test_type=args.test_type,
        verbose=args.verbose
    )
    
    # 退出码
    sys.exit(0 if results['success'] else 1)


if __name__ == "__main__":
    main()