"""
AI日志分析测试配置

定义测试环境参数、DeepSeek模型配置和测试用例设置
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional


class TestConfig:
    """测试配置类"""
    
    def __init__(self):
        # 项目路径
        self.project_root = Path(__file__).resolve().parent.parent
        self.test_data_dir = self.project_root / "test_data"
        self.test_results_dir = self.project_root / "test_results"
        
        # DeepSeek配置（用于测试）
        self.deepseek_config = {
            "api_key": "sk-test-deepseek-key-for-testing",  # 测试用密钥
            "base_url": "http://oneapi.yhroot.com",
            "model_name": "deepseek-v3.1-chat",
            "reasoning_model": "deepseek-v3.1",
            "timeout": 30,
            "max_retries": 3,
            "temperature": 0.1,
            "max_tokens": 2048
        }
        
        # Qwen配置（用于测试，OpenAI兼容模式）
        self.qwen_config = {
            "api_key": "sk-test-qwen-key-for-testing",  # 测试用密钥
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_name": "qwen-plus-2025-09-11",
            "timeout": 30,
            "max_retries": 3,
            "temperature": 0.1,
            "max_tokens": 2048
        }
        
        # 测试数据配置
        self.test_data_config = {
            "basic_dataset": {
                "name": "ai_test_logs",
                "log_files": [
                    "protocol_stack.log",
                    "oam_antenna.log", 
                    "application.log"
                ],
                "metadata_file": "metadata.json",
                "expected_size_kb": 100,  # 预期大小（KB）
                "expected_entries": 3000   # 预期日志条数
            },
            "performance_dataset": {
                "name": "performance_ai_test_logs",
                "log_files": [
                    "large_protocol_stack.log",
                    "large_oam_antenna.log",
                    "large_application.log"
                ],
                "metadata_file": "metadata.json",
                "expected_size_mb": 10,    # 预期大小（MB）
                "expected_entries": 30000  # 预期日志条数
            }
        }
        
        # 工具测试配置
        self.tool_test_config = {
            "grep_tool": {
                "test_patterns": [
                    "ERROR",
                    "FATAL", 
                    "连接超时",
                    "认证失败",
                    r"\d{4}-\d{2}-\d{2}",  # 日期模式
                    r"STACK_\w+"           # 协议栈组件模式
                ],
                "context_lines": 3,
                "max_matches": 100
            },
            "metadata_tool": {
                "test_archives": [
                    "ai_test_logs.tar.gz",
                    "ai_test_logs.zip"
                ],
                "expected_components": [
                    "STACK_CUCP", "STACK_CUUP", "STACK_DU",
                    "CUUP_OAM", "DU_OAM", "DVB_OAM", "MAIN_OAM",
                    "APP", "HTTP", "DB"
                ]
            },
            "fs_tools": {
                "test_operations": [
                    "list_directory",
                    "read_head",
                    "read_tail", 
                    "read_chunk",
                    "get_stats",
                    "calculate_hash"
                ],
                "max_file_size_mb": 50,
                "max_read_lines": 1000
            }
        }
        
        # Agent测试配置
        self.agent_test_config = {
            "test_queries": [
                "分析协议栈日志中的错误情况",
                "查找OAM天线相关的故障信息",
                "统计应用日志中的HTTP请求状态",
                "检查系统中是否有内存不足的问题",
                "分析最近1小时内的所有ERROR级别日志",
                "查找VSWR异常相关的告警信息"
            ],
            "test_hints": [
                "重点关注ERROR和FATAL级别的日志",
                "分析天线ID和故障类型的关联",
                "统计不同HTTP状态码的分布",
                "检查内存使用率相关的警告",
                "按时间顺序分析错误趋势",
                "关注VSWR测量值超过阈值的情况"
            ],
            "max_planning_steps": 10,
            "max_execution_time": 300,  # 5分钟
            "memory_limit_mb": 512
        }
        
        # 性能测试配置
        self.performance_test_config = {
            "large_file_tests": {
                "file_sizes_mb": [1, 5, 10, 20],
                "concurrent_processes": [1, 2, 4, 8],
                "timeout_per_test": 600  # 10分钟
            },
            "memory_tests": {
                "max_memory_mb": 1024,
                "memory_check_interval": 5,  # 秒
                "memory_threshold": 0.8      # 80%
            },
            "stress_tests": {
                "concurrent_queries": [1, 5, 10],
                "query_duration": 60,        # 秒
                "max_response_time": 30      # 秒
            }
        }
        
        # 测试环境配置
        self.environment_config = {
            "python_version": "3.8+",
            "required_modules": [
                "unittest", "asyncio", "pathlib", "json", 
                "tarfile", "zipfile", "tempfile", "shutil",
                "psutil", "time", "re", "os", "sys"
            ],
            "optional_modules": [
                "pytest", "coverage", "memory_profiler"
            ],
            "test_isolation": True,
            "cleanup_after_test": True,
            "save_test_artifacts": True
        }
        
        # 报告配置
        self.report_config = {
            "output_formats": ["json", "text", "html"],
            "include_logs": True,
            "include_performance_metrics": True,
            "include_error_details": True,
            "max_log_lines": 1000,
            "timestamp_format": "%Y-%m-%d %H:%M:%S"
        }
    
    def get_test_data_path(self, dataset_name: str) -> Path:
        """获取测试数据路径"""
        return self.test_data_dir / dataset_name
    
    def get_test_file_path(self, dataset_name: str, filename: str) -> Path:
        """获取测试文件路径"""
        return self.test_data_dir / dataset_name / filename
    
    def get_archive_path(self, archive_name: str) -> Path:
        """获取压缩包路径"""
        return self.test_data_dir / archive_name
    
    def validate_test_environment(self) -> Dict[str, bool]:
        """验证测试环境"""
        validation_results = {
            "python_version": True,
            "required_modules": True,
            "test_directories": True,
            "test_data": True,
            "deepseek_config": True,
            "qwen_config": True
        }
        
        # 检查Python版本
        import sys
        python_version = sys.version_info
        if python_version < (3, 8):
            validation_results["python_version"] = False
        
        # 检查必需模块
        for module in self.environment_config["required_modules"]:
            try:
                __import__(module)
            except ImportError:
                validation_results["required_modules"] = False
                break
        
        # 检查测试目录
        required_dirs = [self.test_data_dir, self.test_results_dir]
        for directory in required_dirs:
            if not directory.exists():
                try:
                    directory.mkdir(parents=True, exist_ok=True)
                except Exception:
                    validation_results["test_directories"] = False
                    break
        
        # 检查基础测试数据
        basic_dataset_path = self.get_test_data_path(
            self.test_data_config["basic_dataset"]["name"]
        )
        if not basic_dataset_path.exists():
            validation_results["test_data"] = False
        
        # 检查DeepSeek配置
        if not self.deepseek_config.get("api_key") or not self.deepseek_config.get("base_url"):
            validation_results["deepseek_config"] = False
        
        # 检查Qwen配置
        if not self.qwen_config.get("api_key") or not self.qwen_config.get("base_url"):
            validation_results["qwen_config"] = False
        
        return validation_results
    
    def get_test_query_by_type(self, query_type: str) -> Optional[str]:
        """根据类型获取测试查询"""
        query_map = {
            "error_analysis": "分析协议栈日志中的错误情况",
            "antenna_fault": "查找OAM天线相关的故障信息", 
            "http_stats": "统计应用日志中的HTTP请求状态",
            "memory_check": "检查系统中是否有内存不足的问题",
            "recent_errors": "分析最近1小时内的所有ERROR级别日志",
            "vswr_analysis": "查找VSWR异常相关的告警信息"
        }
        return query_map.get(query_type)
    
    def get_performance_test_params(self, test_name: str) -> Dict[str, Any]:
        """获取性能测试参数"""
        if test_name == "large_file":
            return self.performance_test_config["large_file_tests"]
        elif test_name == "memory":
            return self.performance_test_config["memory_tests"]
        elif test_name == "stress":
            return self.performance_test_config["stress_tests"]
        else:
            return {}
    
    def create_test_environment_info(self) -> Dict[str, Any]:
        """创建测试环境信息"""
        import sys
        import platform
        
        return {
            "python_version": sys.version,
            "platform": platform.platform(),
            "architecture": platform.architecture(),
            "processor": platform.processor(),
            "project_root": str(self.project_root),
            "test_data_dir": str(self.test_data_dir),
            "test_results_dir": str(self.test_results_dir),
            "deepseek_config": {
                "base_url": self.deepseek_config["base_url"],
                "model_name": self.deepseek_config["model_name"],
                "reasoning_model": self.deepseek_config["reasoning_model"]
            },
            "qwen_config": {
                "base_url": self.qwen_config["base_url"],
                "model_name": self.qwen_config["model_name"],
            },
            "validation_results": self.validate_test_environment()
        }


# 全局测试配置实例
TEST_CONFIG = TestConfig()


def get_test_config() -> TestConfig:
    """获取测试配置实例"""
    return TEST_CONFIG


def validate_environment() -> bool:
    """验证测试环境是否就绪"""
    config = get_test_config()
    validation_results = config.validate_test_environment()
    return all(validation_results.values())


if __name__ == "__main__":
    # 测试配置验证
    config = get_test_config()
    
    print("🔧 AI日志分析测试配置")
    print("="*50)
    
    # 显示环境信息
    env_info = config.create_test_environment_info()
    print(f"Python版本: {env_info['python_version']}")
    print(f"平台: {env_info['platform']}")
    print(f"项目根目录: {env_info['project_root']}")
    
    # 验证环境
    print("\n🔍 环境验证:")
    validation_results = env_info["validation_results"]
    for check, result in validation_results.items():
        status = "✅" if result else "❌"
        print(f"  {check}: {status}")
    
    # 显示配置摘要
    print(f"\n📊 配置摘要:")
    print(f"  DeepSeek模型: {config.deepseek_config['model_name']}")
    print(f"  Qwen模型: {config.qwen_config['model_name']}")
    print(f"  测试数据集: {len(config.test_data_config)}个")
    print(f"  测试查询: {len(config.agent_test_config['test_queries'])}个")
    print(f"  工具测试: {len(config.tool_test_config)}个")
    
    # 整体状态
    all_valid = all(validation_results.values())
    print(f"\n🎯 环境状态: {'✅ 就绪' if all_valid else '❌ 需要修复'}")
    
    if not all_valid:
        print("\n⚠️  请解决上述问题后再运行测试")
        exit(1)
    else:
        print("\n🚀 环境验证通过，可以开始测试！")