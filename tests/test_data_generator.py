#!/usr/bin/env python3
"""
测试数据生成器

用于生成各种类型的测试日志文件，支持AI日志分析功能测试
"""

import os
import json
import random
import tarfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any


class LogDataGenerator:
    """日志数据生成器"""
    
    def __init__(self, output_dir: str = "test_data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 日志级别和组件
        self.log_levels = ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
        self.stack_components = ["STACK_CUCP", "STACK_CUUP", "STACK_DU"]
        self.oam_components = ["CUUP_OAM", "DU_OAM", "DVB_OAM", "MAIN_OAM"]
        self.app_components = ["APP", "HTTP", "DB", "CACHE", "AUTH", "TASK", "MEM"]
        
        # 错误消息模板
        self.error_messages = [
            "连接超时",
            "握手失败",
            "内存不足",
            "认证失败",
            "数据库连接失败",
            "网络异常",
            "配置错误",
            "系统崩溃",
            "资源耗尽",
            "协议错误"
        ]
        
        self.warning_messages = [
            "信号强度低",
            "内存使用率高",
            "缓存命中率低",
            "响应时间长",
            "磁盘空间不足",
            "温度过高",
            "负载过高",
            "连接数过多"
        ]
        
        self.info_messages = [
            "系统启动",
            "连接建立",
            "数据传输开始",
            "任务完成",
            "配置更新",
            "状态正常",
            "健康检查通过",
            "备份完成"
        ]
    
    def generate_timestamp(self, base_time: datetime, offset_seconds: int = 0) -> str:
        """生成时间戳"""
        timestamp = base_time + timedelta(seconds=offset_seconds)
        return timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    def generate_log_entry(self, component: str, level: str, message: str, 
                          timestamp: str, extra_data: Dict[str, Any] = None) -> str:
        """生成单条日志记录"""
        entry = f"{timestamp} [{level}] {component}: {message}"
        
        if extra_data:
            for key, value in extra_data.items():
                entry += f" - {key}: {value}"
        
        return entry
    
    def generate_protocol_stack_log(self, num_entries: int = 1000, 
                                   error_rate: float = 0.1) -> str:
        """生成协议栈日志"""
        entries = []
        base_time = datetime.now() - timedelta(hours=1)
        
        for i in range(num_entries):
            component = random.choice(self.stack_components)
            
            # 根据错误率决定日志级别
            if random.random() < error_rate * 0.3:  # 3%的FATAL/ERROR
                level = random.choice(["ERROR", "FATAL"])
                message = random.choice(self.error_messages)
                extra_data = {
                    "错误码": f"0x{random.randint(1000, 9999):04X}",
                    "UE_ID": random.randint(10000, 99999)
                }
            elif random.random() < error_rate:  # 7%的WARN
                level = "WARN"
                message = random.choice(self.warning_messages)
                extra_data = {
                    "阈值": f"{random.randint(70, 95)}%",
                    "当前值": f"{random.randint(80, 100)}%"
                }
            else:  # 90%的INFO/DEBUG
                level = random.choice(["INFO", "DEBUG"])
                message = random.choice(self.info_messages)
                extra_data = {
                    "会话ID": f"SES_{random.randint(100000, 999999)}",
                    "状态": "正常"
                }
            
            timestamp = self.generate_timestamp(base_time, i * 2)
            entry = self.generate_log_entry(component, level, message, timestamp, extra_data)
            entries.append(entry)
        
        return "\n".join(entries)
    
    def generate_oam_antenna_log(self, num_entries: int = 800, 
                                error_rate: float = 0.15) -> str:
        """生成OAM天线日志"""
        entries = []
        base_time = datetime.now() - timedelta(hours=1)
        
        antenna_ids = [f"ANT_{i:03d}" for i in range(1, 21)]
        
        for i in range(num_entries):
            component = random.choice(self.oam_components)
            
            if random.random() < error_rate * 0.2:  # ERROR
                level = "ERROR"
                message = "天线故障检测"
                extra_data = {
                    "天线ID": random.choice(antenna_ids),
                    "故障类型": random.choice(["连接断开", "VSWR异常", "功率异常"])
                }
            elif random.random() < error_rate:  # WARN
                level = "WARN"
                message = random.choice(["VSWR异常", "温度过高警告", "功率偏差"])
                extra_data = {
                    "天线ID": random.choice(antenna_ids),
                    "测量值": f"{random.uniform(1.5, 3.0):.2f}",
                    "阈值": "2.0"
                }
            else:  # INFO/DEBUG
                level = random.choice(["INFO", "DEBUG"])
                message = random.choice([
                    "天线配置更新", "功率调整", "信号质量监控", 
                    "性能统计更新", "自动故障恢复"
                ])
                extra_data = {
                    "天线ID": random.choice(antenna_ids),
                    "发射功率": f"{random.randint(15, 25)}W"
                }
            
            timestamp = self.generate_timestamp(base_time, i * 3)
            entry = self.generate_log_entry(component, level, message, timestamp, extra_data)
            entries.append(entry)
        
        return "\n".join(entries)
    
    def generate_application_log(self, num_entries: int = 1200, 
                                error_rate: float = 0.08) -> str:
        """生成应用日志"""
        entries = []
        base_time = datetime.now() - timedelta(hours=1)
        
        for i in range(num_entries):
            component = random.choice(self.app_components)
            
            if random.random() < error_rate * 0.4:  # ERROR
                level = "ERROR"
                if component == "DB":
                    message = "数据库查询超时"
                    extra_data = {"查询时间": f"{random.randint(25, 60)}s"}
                elif component == "AUTH":
                    message = "认证失败"
                    extra_data = {"用户": f"user_{random.randint(1, 100)}"}
                else:
                    message = random.choice(self.error_messages)
                    extra_data = {"错误码": random.randint(500, 599)}
            elif random.random() < error_rate:  # WARN
                level = "WARN"
                message = random.choice(self.warning_messages)
                extra_data = {"使用率": f"{random.randint(75, 95)}%"}
            else:  # INFO/DEBUG
                level = random.choice(["INFO", "DEBUG"])
                if component == "HTTP":
                    message = f"接收请求 - {random.choice(['GET', 'POST', 'PUT', 'DELETE'])}"
                    extra_data = {
                        "路径": f"/api/{random.choice(['status', 'logs', 'users', 'data'])}",
                        "状态码": random.choice([200, 201, 204])
                    }
                else:
                    message = random.choice(self.info_messages)
                    extra_data = {"状态": "正常"}
            
            timestamp = self.generate_timestamp(base_time, i * 1.5)
            entry = self.generate_log_entry(component, level, message, timestamp, extra_data)
            entries.append(entry)
        
        return "\n".join(entries)
    
    def generate_metadata_json(self, log_files: List[str]) -> Dict[str, Any]:
        """生成元数据JSON"""
        total_size = sum(os.path.getsize(f) for f in log_files if os.path.exists(f))
        
        components = []
        for log_file in log_files:
            filename = os.path.basename(log_file)
            if "protocol_stack" in filename:
                components.extend([
                    {"component_name": "STACK_CUCP", "log_level": "INFO", "file_path": filename},
                    {"component_name": "STACK_CUUP", "log_level": "DEBUG", "file_path": filename},
                    {"component_name": "STACK_DU", "log_level": "INFO", "file_path": filename}
                ])
            elif "oam_antenna" in filename:
                components.extend([
                    {"component_name": "CUUP_OAM", "log_level": "DEBUG", "file_path": filename},
                    {"component_name": "DU_OAM", "log_level": "INFO", "file_path": filename},
                    {"component_name": "DVB_OAM", "log_level": "WARN", "file_path": filename},
                    {"component_name": "MAIN_OAM", "log_level": "INFO", "file_path": filename}
                ])
            elif "application" in filename:
                components.extend([
                    {"component_name": "APP", "log_level": "INFO", "file_path": filename},
                    {"component_name": "HTTP", "log_level": "DEBUG", "file_path": filename},
                    {"component_name": "DB", "log_level": "WARN", "file_path": filename}
                ])
        
        return {
            "log_package_info": {
                "package_name": f"test_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "created_time": datetime.now().isoformat() + "Z",
                "total_size": total_size,
                "file_count": len(log_files),
                "description": "AI日志分析测试数据包"
            },
            "log_components": components,
            "system_info": {
                "hostname": "test-server-01",
                "os_version": "Linux 5.4.0-74-generic",
                "cpu_cores": 8,
                "memory_gb": 32,
                "disk_gb": 500,
                "network_interfaces": ["eth0", "eth1"]
            },
            "collection_info": {
                "start_time": (datetime.now() - timedelta(hours=1)).isoformat() + "Z",
                "end_time": datetime.now().isoformat() + "Z",
                "collection_method": "automated",
                "compression_ratio": 0.75
            }
        }
    
    def create_test_dataset(self, dataset_name: str = "ai_test_logs"):
        """创建完整的测试数据集"""
        dataset_dir = self.output_dir / dataset_name
        dataset_dir.mkdir(exist_ok=True)
        
        print(f"创建测试数据集: {dataset_dir}")
        
        # 生成各种日志文件
        log_files = []
        
        # 协议栈日志
        print("生成协议栈日志...")
        protocol_log = self.generate_protocol_stack_log(1000, 0.12)
        protocol_file = dataset_dir / "protocol_stack.log"
        with open(protocol_file, 'w', encoding='utf-8') as f:
            f.write(protocol_log)
        log_files.append(str(protocol_file))
        
        # OAM天线日志
        print("生成OAM天线日志...")
        oam_log = self.generate_oam_antenna_log(800, 0.15)
        oam_file = dataset_dir / "oam_antenna.log"
        with open(oam_file, 'w', encoding='utf-8') as f:
            f.write(oam_log)
        log_files.append(str(oam_file))
        
        # 应用日志
        print("生成应用日志...")
        app_log = self.generate_application_log(1200, 0.08)
        app_file = dataset_dir / "application.log"
        with open(app_file, 'w', encoding='utf-8') as f:
            f.write(app_log)
        log_files.append(str(app_file))
        
        # 生成元数据
        print("生成元数据文件...")
        metadata = self.generate_metadata_json(log_files)
        metadata_file = dataset_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # 创建压缩包
        print("创建压缩包...")
        
        # TAR.GZ格式
        tar_file = self.output_dir / f"{dataset_name}.tar.gz"
        with tarfile.open(tar_file, "w:gz") as tar:
            for log_file in log_files:
                tar.add(log_file, arcname=os.path.basename(log_file))
            tar.add(metadata_file, arcname="metadata.json")
        
        # ZIP格式
        zip_file = self.output_dir / f"{dataset_name}.zip"
        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zip_archive:
            for log_file in log_files:
                zip_archive.write(log_file, os.path.basename(log_file))
            zip_archive.write(metadata_file, "metadata.json")
        
        print(f"测试数据集创建完成:")
        print(f"  目录: {dataset_dir}")
        print(f"  TAR.GZ: {tar_file}")
        print(f"  ZIP: {zip_file}")
        print(f"  文件数量: {len(log_files) + 1}")
        
        # 统计信息
        total_size = sum(os.path.getsize(f) for f in log_files + [str(metadata_file)])
        print(f"  总大小: {total_size / 1024:.2f} KB")
        
        return {
            "dataset_dir": str(dataset_dir),
            "log_files": log_files,
            "metadata_file": str(metadata_file),
            "tar_file": str(tar_file),
            "zip_file": str(zip_file),
            "total_size": total_size
        }
    
    def create_performance_dataset(self, dataset_name: str = "performance_test_logs"):
        """创建性能测试数据集（大文件）"""
        dataset_dir = self.output_dir / dataset_name
        dataset_dir.mkdir(exist_ok=True)
        
        print(f"创建性能测试数据集: {dataset_dir}")
        
        # 生成大型日志文件
        log_files = []
        
        # 大型协议栈日志（10000条记录）
        print("生成大型协议栈日志...")
        large_protocol_log = self.generate_protocol_stack_log(10000, 0.15)
        large_protocol_file = dataset_dir / "large_protocol_stack.log"
        with open(large_protocol_file, 'w', encoding='utf-8') as f:
            f.write(large_protocol_log)
        log_files.append(str(large_protocol_file))
        
        # 大型OAM日志（8000条记录）
        print("生成大型OAM日志...")
        large_oam_log = self.generate_oam_antenna_log(8000, 0.18)
        large_oam_file = dataset_dir / "large_oam_antenna.log"
        with open(large_oam_file, 'w', encoding='utf-8') as f:
            f.write(large_oam_log)
        log_files.append(str(large_oam_file))
        
        # 大型应用日志（12000条记录）
        print("生成大型应用日志...")
        large_app_log = self.generate_application_log(12000, 0.10)
        large_app_file = dataset_dir / "large_application.log"
        with open(large_app_file, 'w', encoding='utf-8') as f:
            f.write(large_app_log)
        log_files.append(str(large_app_file))
        
        # 生成元数据
        metadata = self.generate_metadata_json(log_files)
        metadata_file = dataset_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        total_size = sum(os.path.getsize(f) for f in log_files + [str(metadata_file)])
        print(f"性能测试数据集创建完成:")
        print(f"  目录: {dataset_dir}")
        print(f"  文件数量: {len(log_files) + 1}")
        print(f"  总大小: {total_size / 1024 / 1024:.2f} MB")
        
        return {
            "dataset_dir": str(dataset_dir),
            "log_files": log_files,
            "metadata_file": str(metadata_file),
            "total_size": total_size
        }


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="生成AI日志分析测试数据")
    parser.add_argument("--output-dir", default="test_data", help="输出目录")
    parser.add_argument("--dataset-name", default="ai_test_logs", help="数据集名称")
    parser.add_argument("--performance", action="store_true", help="生成性能测试数据集")
    
    args = parser.parse_args()
    
    generator = LogDataGenerator(args.output_dir)
    
    if args.performance:
        result = generator.create_performance_dataset(f"performance_{args.dataset_name}")
    else:
        result = generator.create_test_dataset(args.dataset_name)
    
    print("\n数据生成完成！")
    print("可以使用以下命令运行测试:")
    print("  python test_ai_log_analysis.py")
    print("  python test_ai_log_analysis.py --test-type unit")
    print("  python test_ai_log_analysis.py --test-type performance")


if __name__ == "__main__":
    main()