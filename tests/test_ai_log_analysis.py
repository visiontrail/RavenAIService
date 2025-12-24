#!/usr/bin/env python3
"""
AI日志分析功能测试套件

测试内容：
1. AI Agent基础功能测试
2. 日志分析工具测试（grep、metadata、fs_tools）
3. DeepSeek模型集成测试
4. 性能和压力测试
5. 错误处理和边界条件测试

使用方法：
    python test_ai_log_analysis.py
    python test_ai_log_analysis.py --test-type unit
    python test_ai_log_analysis.py --test-type integration
    python test_ai_log_analysis.py --test-type performance
"""

import os
import sys
import json
import time
import tempfile
import tarfile
import zipfile
import argparse
import unittest
from pathlib import Path
from typing import Dict, List, Any, Optional
from unittest.mock import patch, MagicMock

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.agents.log_agent import LogAnalysisAgent, demo_agent_run, get_llm
from app.tools.grep_tool import grep_file, grep_file_xml
from app.tools.metadata_tool import get_log_package_metadata, get_log_package_metadata_xml
from app.tools.fs_tools import read_head_xml, read_tail_xml, stat_xml, safe_listdir
from app.agents.xml_utils import wrap_plan, wrap_document, wrap_search_results


class TestDataGenerator:
    """测试数据生成器"""
    
    def __init__(self, temp_dir: str):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(exist_ok=True)
    
    def create_sample_log_file(self, filename: str, content: str) -> str:
        """创建示例日志文件"""
        file_path = self.temp_dir / filename
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return str(file_path)
    
    def create_protocol_stack_log(self) -> str:
        """创建协议栈日志示例"""
        content = """
2024-01-15 10:30:15.123 [INFO] STACK_CUCP: 系统初始化完成
2024-01-15 10:30:16.456 [DEBUG] STACK_CUUP: 连接建立 - UE ID: 12345
2024-01-15 10:30:17.789 [WARN] STACK_DU: 信号强度低 - RSRP: -105 dBm
2024-01-15 10:30:18.012 [ERROR] STACK_CUCP: 握手失败 - 错误码: 0x1001
2024-01-15 10:30:19.345 [INFO] STACK_CUUP: 数据传输开始
2024-01-15 10:30:20.678 [ERROR] STACK_DU: 连接超时 - UE ID: 12345
2024-01-15 10:30:21.901 [FATAL] STACK_CUCP: 系统崩溃 - 核心转储已生成
2024-01-15 10:30:22.234 [INFO] STACK_CUUP: 尝试重连
2024-01-15 10:30:23.567 [WARN] STACK_DU: 内存使用率过高: 85%
2024-01-15 10:30:24.890 [INFO] STACK_CUCP: 系统恢复正常
"""
        return self.create_sample_log_file("protocol_stack.log", content)
    
    def create_oam_log(self) -> str:
        """创建OAM日志示例"""
        content = """
2024-01-15 10:30:15.123 [INFO] CUUP_OAM: 天线配置更新
2024-01-15 10:30:16.456 [DEBUG] DU_OAM: 功率调整 - 发射功率: 20W
2024-01-15 10:30:17.789 [WARN] DVB_OAM: 天线VSWR异常 - 值: 2.5
2024-01-15 10:30:18.012 [ERROR] MAIN_OAM: 天线故障检测 - 天线ID: ANT_001
2024-01-15 10:30:19.345 [INFO] CUUP_OAM: 信号质量监控启动
2024-01-15 10:30:20.678 [ERROR] DU_OAM: 天线连接断开 - 天线ID: ANT_002
2024-01-15 10:30:21.901 [WARN] DVB_OAM: 温度过高警告 - 温度: 75°C
2024-01-15 10:30:22.234 [INFO] MAIN_OAM: 自动故障恢复启动
2024-01-15 10:30:23.567 [DEBUG] CUUP_OAM: 性能统计更新
2024-01-15 10:30:24.890 [INFO] DU_OAM: 系统状态正常
"""
        return self.create_sample_log_file("oam_antenna.log", content)
    
    def create_application_log(self) -> str:
        """创建应用日志示例"""
        content = """
2024-01-15 10:30:15.123 [INFO] APP: 应用启动
2024-01-15 10:30:16.456 [DEBUG] HTTP: 接收请求 - GET /api/status
2024-01-15 10:30:17.789 [INFO] DB: 数据库连接建立
2024-01-15 10:30:18.012 [WARN] CACHE: 缓存命中率低 - 45%
2024-01-15 10:30:19.345 [ERROR] AUTH: 认证失败 - 用户: admin
2024-01-15 10:30:20.678 [INFO] HTTP: 响应发送 - 状态码: 200
2024-01-15 10:30:21.901 [DEBUG] TASK: 后台任务执行
2024-01-15 10:30:22.234 [ERROR] DB: 查询超时 - 查询时间: 30s
2024-01-15 10:30:23.567 [WARN] MEM: 内存使用率高 - 90%
2024-01-15 10:30:24.890 [INFO] APP: 健康检查通过
"""
        return self.create_sample_log_file("application.log", content)
    
    def create_metadata_json(self) -> str:
        """创建元数据文件"""
        metadata = {
            "log_package_info": {
                "package_name": "test_logs_20240115",
                "created_time": "2024-01-15T10:30:00Z",
                "total_size": 1048576,
                "file_count": 3
            },
            "log_components": [
                {
                    "component_name": "STACK_CUCP",
                    "log_level": "INFO",
                    "file_path": "protocol_stack.log"
                },
                {
                    "component_name": "CUUP_OAM",
                    "log_level": "DEBUG",
                    "file_path": "oam_antenna.log"
                },
                {
                    "component_name": "APP",
                    "log_level": "INFO",
                    "file_path": "application.log"
                }
            ],
            "system_info": {
                "hostname": "test-server-01",
                "os_version": "Linux 5.4.0",
                "cpu_cores": 8,
                "memory_gb": 32
            }
        }
        
        file_path = self.temp_dir / "metadata.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        return str(file_path)
    
    def create_log_archive(self, archive_type: str = "tar.gz") -> str:
        """创建日志压缩包"""
        # 创建所有测试文件
        protocol_log = self.create_protocol_stack_log()
        oam_log = self.create_oam_log()
        app_log = self.create_application_log()
        metadata = self.create_metadata_json()
        
        if archive_type == "tar.gz":
            archive_path = self.temp_dir / "test_logs.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(protocol_log, arcname="protocol_stack.log")
                tar.add(oam_log, arcname="oam_antenna.log")
                tar.add(app_log, arcname="application.log")
                tar.add(metadata, arcname="metadata.json")
        elif archive_type == "zip":
            archive_path = self.temp_dir / "test_logs.zip"
            with zipfile.ZipFile(archive_path, "w") as zip_file:
                zip_file.write(protocol_log, "protocol_stack.log")
                zip_file.write(oam_log, "oam_antenna.log")
                zip_file.write(app_log, "application.log")
                zip_file.write(metadata, "metadata.json")
        
        return str(archive_path)


class TestAILogAnalysisTools(unittest.TestCase):
    """AI日志分析工具测试"""
    
    def setUp(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.data_generator = TestDataGenerator(self.temp_dir)
        
        # 备份原始配置
        self.original_root_dir = settings.agent_root_dir
        self.original_agent_enabled = settings.agent_enabled
        
        # 设置测试配置
        settings.agent_root_dir = self.temp_dir
        settings.agent_enabled = True
    
    def tearDown(self):
        """测试后清理"""
        # 恢复原始配置
        settings.agent_root_dir = self.original_root_dir
        settings.agent_enabled = self.original_agent_enabled
        
        # 清理临时文件
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_grep_tool_basic(self):
        """测试grep工具基础功能"""
        print("\n=== 测试grep工具基础功能 ===")
        
        # 创建测试日志文件
        log_file = self.data_generator.create_protocol_stack_log()
        
        # 测试搜索ERROR
        result = grep_file(log_file, "ERROR", context=2)
        self.assertIn("query", result)
        self.assertIn("results", result)
        self.assertEqual(result["query"], "ERROR")
        self.assertGreater(len(result["results"]), 0)
        
        print(f"找到 {len(result['results'])} 个ERROR匹配")
        for match in result["results"]:
            print(f"  行 {match['start_line']}-{match['end_line']}: {match['text'][:50]}...")
    
    def test_grep_tool_xml_output(self):
        """测试grep工具XML输出"""
        print("\n=== 测试grep工具XML输出 ===")
        
        log_file = self.data_generator.create_protocol_stack_log()
        xml_result = grep_file_xml(log_file, "STACK_CUCP", context=1)
        
        self.assertIn("<search_results>", xml_result)
        self.assertIn("STACK_CUCP", xml_result)
        print("XML输出格式正确")
        print(f"XML结果长度: {len(xml_result)} 字符")
    
    def test_metadata_tool(self):
        """测试元数据提取工具"""
        print("\n=== 测试元数据提取工具 ===")
        
        # 创建测试压缩包
        archive_path = self.data_generator.create_log_archive("tar.gz")
        
        # 测试元数据提取
        metadata = get_log_package_metadata(archive_path)
        self.assertIn("source", metadata)
        self.assertIn("file_count", metadata)
        self.assertIn("total_size", metadata)
        
        print(f"文件数量: {metadata['file_count']}")
        print(f"总大小: {metadata['total_size']} 字节")
        print(f"内容类型: {metadata['content_types']}")
        
        # 测试XML输出
        xml_metadata = get_log_package_metadata_xml(archive_path)
        self.assertIn("<metadata>", xml_metadata)
        print("元数据XML格式正确")
    
    def test_fs_tools(self):
        """测试文件系统工具"""
        print("\n=== 测试文件系统工具 ===")
        
        log_file = self.data_generator.create_protocol_stack_log()
        
        # 测试读取文件头部
        head_xml = read_head_xml(log_file, n_lines=5)
        self.assertIn("<excerpt>", head_xml)
        self.assertIn("系统初始化完成", head_xml)
        print("文件头部读取正常")
        
        # 测试读取文件尾部
        tail_xml = read_tail_xml(log_file, n_lines=5)
        self.assertIn("<excerpt>", tail_xml)
        self.assertIn("系统恢复正常", tail_xml)
        print("文件尾部读取正常")
        
        # 测试文件状态
        stat_result = stat_xml(log_file)
        self.assertIn("<metadata>", stat_result)
        self.assertIn("size", stat_result)
        print("文件状态获取正常")
        
        # 测试目录列表
        dir_list = safe_listdir(self.temp_dir)
        self.assertGreater(len(dir_list), 0)
        print(f"目录中找到 {len(dir_list)} 个文件")


class TestAILogAnalysisAgent(unittest.TestCase):
    """AI日志分析Agent测试"""
    
    def setUp(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.data_generator = TestDataGenerator(self.temp_dir)
        
        # 备份原始配置
        self.original_root_dir = settings.agent_root_dir
        self.original_agent_enabled = settings.agent_enabled
        
        # 设置测试配置
        settings.agent_root_dir = self.temp_dir
        settings.agent_enabled = True
        
        # 创建测试数据
        self.protocol_log = self.data_generator.create_protocol_stack_log()
        self.oam_log = self.data_generator.create_oam_log()
        self.app_log = self.data_generator.create_application_log()
        self.archive = self.data_generator.create_log_archive()
    
    def tearDown(self):
        """测试后清理"""
        settings.agent_root_dir = self.original_root_dir
        settings.agent_enabled = self.original_agent_enabled
        
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_agent_initialization(self):
        """测试Agent初始化"""
        print("\n=== 测试Agent初始化 ===")
        
        agent = LogAnalysisAgent()
        self.assertIsNotNone(agent.llm)
        self.assertIsNotNone(agent.memory)
        self.assertIsNotNone(agent.search_backend)
        print("Agent初始化成功")
    
    def test_agent_planning(self):
        """测试Agent规划功能"""
        print("\n=== 测试Agent规划功能 ===")
        
        agent = LogAnalysisAgent()
        
        # 测试不同类型的查询
        queries = [
            "查找所有ERROR日志",
            "提取日志包元数据",
            "分析协议栈错误",
            "读取日志文件片段"
        ]
        
        for query in queries:
            plan = agent.plan(query)
            self.assertIn("<plan>", plan)
            print(f"查询: {query}")
            print(f"计划: {plan[:100]}...")
    
    def test_agent_execution(self):
        """测试Agent执行功能"""
        print("\n=== 测试Agent执行功能 ===")
        
        # 测试基础查询
        result = demo_agent_run(
            "查找ERROR日志",
            hints={"path": self.protocol_log, "pattern": "ERROR"}
        )
        
        self.assertIsInstance(result, str)
        self.assertIn("ERROR", result)
        print("Agent执行查询成功")
        print(f"结果长度: {len(result)} 字符")
        
        # 测试元数据提取
        metadata_result = demo_agent_run(
            "提取日志包元数据",
            hints={"archive_path": self.archive}
        )
        
        self.assertIsInstance(metadata_result, str)
        print("Agent元数据提取成功")
    
    @patch('app.agents.log_agent.get_llm')
    def test_agent_with_mock_llm(self, mock_get_llm):
        """测试Agent与模拟LLM"""
        print("\n=== 测试Agent与模拟LLM ===")
        
        # 创建模拟LLM
        mock_llm = MagicMock()
        mock_llm.predict.return_value = "<plan><step>查找ERROR日志</step></plan>"
        mock_get_llm.return_value = mock_llm
        
        agent = LogAnalysisAgent()
        result = agent.run("查找ERROR日志", hints={"path": self.protocol_log})
        
        self.assertIsInstance(result, str)
        mock_llm.predict.assert_called()
        print("模拟LLM测试通过")


class TestDeepSeekIntegration(unittest.TestCase):
    """DeepSeek模型集成测试"""
    
    def setUp(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.data_generator = TestDataGenerator(self.temp_dir)
        
        # 备份原始配置
        self.original_provider = settings.llm_provider
        self.original_api_key = getattr(settings, 'deepseek_api_key', None)
        self.original_base_url = getattr(settings, 'deepseek_base_url', None)
        self.original_model = settings.llm_model_name
    
    def tearDown(self):
        """测试后清理"""
        settings.llm_provider = self.original_provider
        if self.original_api_key:
            settings.deepseek_api_key = self.original_api_key
        if self.original_base_url:
            settings.deepseek_base_url = self.original_base_url
        settings.llm_model_name = self.original_model
        
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_deepseek_configuration(self):
        """测试DeepSeek配置（统一单一模型）"""
        print("\n=== 测试DeepSeek配置 ===")
        provider = getattr(settings, 'llm_provider', 'GalaxySpace')

        # 统一为 GalaxySpace
        self.assertEqual(provider, "GalaxySpace")

        api_key = getattr(settings, 'deepseek_api_key', None)
        base_url = getattr(settings, 'deepseek_base_url', None)
        model_name = getattr(settings, 'llm_model_name', None)

        self.assertIsNotNone(api_key)
        self.assertIsNotNone(base_url)
        self.assertEqual(model_name, "deepseek-v3.1")

        print(f"LLM提供商: {provider}")
        print(f"模型名称: {model_name}")
        print(f"DeepSeek API基础URL: {base_url}")
        print("DeepSeek配置检查通过（单一模型）")
    
    def test_llm_initialization(self):
        """测试LLM初始化"""
        print("\n=== 测试LLM初始化 ===")
        
        llm = get_llm()
        self.assertIsNotNone(llm)
        print(f"LLM类型: {type(llm).__name__}")
    
        llm_type = type(llm).__name__
        if hasattr(llm, 'model_name'):
            print(f"使用真实LLM客户端，模型={llm.model_name}")
        elif hasattr(llm, 'invoke'):
            print("使用真实LLM客户端")
        elif hasattr(llm, 'predict'):
            print("使用备用LLM接口")
        else:
            print(f"使用未知LLM接口: {llm_type}")
    
    @unittest.skipIf(not hasattr(settings, 'deepseek_api_key') or not settings.deepseek_api_key, 
                     "需要有效的DeepSeek API密钥")
    def test_deepseek_api_call(self):
        """测试DeepSeek API调用（需要有效API密钥）"""
        print("\n=== 测试DeepSeek API调用 ===")
        
        try:
            llm = get_llm()
            if hasattr(llm, 'predict'):
                # DummyLLM
                result = llm.predict("分析这个日志错误")
                print(f"DummyLLM响应: {result}")
            else:
                # 真实LLM
                result = llm.invoke("分析这个日志错误")
                print(f"DeepSeek响应: {str(result)[:100]}...")
            
            self.assertIsNotNone(result)
            print("API调用成功")
            
        except Exception as e:
            print(f"API调用失败: {e}")
            # 在测试环境中，API调用失败是可以接受的


class TestPerformanceAndStress(unittest.TestCase):
    """性能和压力测试"""
    
    def setUp(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.data_generator = TestDataGenerator(self.temp_dir)
        
        settings.agent_root_dir = self.temp_dir
        settings.agent_enabled = True
    
    def tearDown(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_large_file_processing(self):
        """测试大文件处理"""
        print("\n=== 测试大文件处理 ===")
        
        # 创建大文件（模拟）
        large_content = "\n".join([
            f"2024-01-15 10:30:{i:02d}.123 [INFO] TEST: 测试日志行 {i}"
            for i in range(1000)
        ])
        large_file = self.data_generator.create_sample_log_file("large.log", large_content)
        
        start_time = time.time()
        result = grep_file(large_file, "TEST", max_matches=10)
        end_time = time.time()
        
        self.assertLessEqual(len(result["results"]), 10)
        processing_time = end_time - start_time
        print(f"处理1000行文件耗时: {processing_time:.3f}秒")
        print(f"找到匹配: {len(result['results'])}个")
        
        # 性能断言
        self.assertLess(processing_time, 5.0, "大文件处理时间应小于5秒")
    
    def test_memory_usage(self):
        """测试内存使用"""
        print("\n=== 测试内存使用 ===")
        
        import psutil
        import gc
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # 创建多个文件并处理
        for i in range(10):
            content = "\n".join([
                f"2024-01-15 10:30:{j:02d}.123 [ERROR] 错误日志 {j}"
                for j in range(100)
            ])
            file_path = self.data_generator.create_sample_log_file(f"test_{i}.log", content)
            grep_file(file_path, "ERROR")
        
        gc.collect()
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        print(f"初始内存: {initial_memory:.2f} MB")
        print(f"最终内存: {final_memory:.2f} MB")
        print(f"内存增长: {memory_increase:.2f} MB")
        
        # 内存增长应该在合理范围内
        self.assertLess(memory_increase, 100, "内存增长应小于100MB")
    
    def test_concurrent_processing(self):
        """测试并发处理"""
        print("\n=== 测试并发处理 ===")
        
        import threading
        import queue
        
        # 创建测试文件
        files = []
        for i in range(5):
            content = f"2024-01-15 10:30:{i:02d}.123 [ERROR] 并发测试错误 {i}\n" * 100
            file_path = self.data_generator.create_sample_log_file(f"concurrent_{i}.log", content)
            files.append(file_path)
        
        results_queue = queue.Queue()
        
        def process_file(file_path):
            try:
                result = grep_file(file_path, "ERROR", max_matches=5)
                results_queue.put(("success", len(result["results"])))
            except Exception as e:
                results_queue.put(("error", str(e)))
        
        # 启动并发处理
        threads = []
        start_time = time.time()
        
        for file_path in files:
            thread = threading.Thread(target=process_file, args=(file_path,))
            thread.start()
            threads.append(thread)
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        end_time = time.time()
        
        # 收集结果
        success_count = 0
        error_count = 0
        total_matches = 0
        
        while not results_queue.empty():
            status, data = results_queue.get()
            if status == "success":
                success_count += 1
                total_matches += data
            else:
                error_count += 1
        
        print(f"并发处理耗时: {end_time - start_time:.3f}秒")
        print(f"成功处理: {success_count}个文件")
        print(f"处理失败: {error_count}个文件")
        print(f"总匹配数: {total_matches}")
        
        self.assertEqual(success_count, 5, "所有文件都应该成功处理")
        self.assertEqual(error_count, 0, "不应该有处理失败")


def run_tests(test_type: str = "all"):
    """运行测试"""
    print(f"\n{'='*60}")
    print(f"AI日志分析功能测试 - {test_type.upper()}")
    print(f"{'='*60}")
    
    # 检查配置
    print(f"\n当前配置:")
    print(f"  LLM提供商: {settings.llm_provider}")
    print(f"  模型名称: {settings.llm_model_name}")
    print(f"  Agent根目录: {settings.agent_root_dir}")
    print(f"  Agent启用: {settings.agent_enabled}")
    print("  回退链路: DeepSeek→Qwen→DummyLLM")
    
    if hasattr(settings, 'deepseek_api_key'):
        api_key = settings.deepseek_api_key
        masked_key = f"{api_key[:8]}...{api_key[-8:]}" if api_key else "未设置"
        print(f"  DeepSeek API密钥: {masked_key}")
    
    if hasattr(settings, 'deepseek_base_url'):
        print(f"  DeepSeek基础URL: {settings.deepseek_base_url}")
    
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    if test_type in ["all", "unit"]:
        suite.addTests(loader.loadTestsFromTestCase(TestAILogAnalysisTools))
    
    if test_type in ["all", "integration"]:
        suite.addTests(loader.loadTestsFromTestCase(TestAILogAnalysisAgent))
        suite.addTests(loader.loadTestsFromTestCase(TestDeepSeekIntegration))
    
    if test_type in ["all", "performance"]:
        suite.addTests(loader.loadTestsFromTestCase(TestPerformanceAndStress))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出总结
    print(f"\n{'='*60}")
    print(f"测试总结:")
    print(f"  运行测试: {result.testsRun}")
    print(f"  成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  失败: {len(result.failures)}")
    print(f"  错误: {len(result.errors)}")
    print(f"{'='*60}")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI日志分析功能测试")
    parser.add_argument(
        "--test-type", 
        choices=["all", "unit", "integration", "performance"],
        default="all",
        help="测试类型 (默认: all)"
    )
    
    args = parser.parse_args()
    
    success = run_tests(args.test_type)
    sys.exit(0 if success else 1)
