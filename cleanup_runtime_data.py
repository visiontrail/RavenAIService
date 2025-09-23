#!/usr/bin/env python3
"""
LogStagingService 运行时数据清理工具 (Python版本)

功能：清理项目运行过程中产生的所有临时数据和缓存
作者：自动生成
版本：1.0
"""

import os
import sys
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import List, Optional
import sqlite3


class Colors:
    """终端颜色定义"""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color


class Logger:
    """日志输出类"""
    
    @staticmethod
    def info(message: str):
        print(f"{Colors.BLUE}[INFO]{Colors.NC} {message}")
    
    @staticmethod
    def success(message: str):
        print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {message}")
    
    @staticmethod
    def warning(message: str):
        print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {message}")
    
    @staticmethod
    def error(message: str):
        print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")


class RuntimeDataCleaner:
    """运行时数据清理器"""
    
    def __init__(self, project_root: Path, keep_uploads: bool = True, 
                 docker_cleanup: bool = False, dry_run: bool = False, 
                 verbose: bool = False):
        self.project_root = project_root
        self.keep_uploads = keep_uploads
        self.docker_cleanup = docker_cleanup
        self.dry_run = dry_run
        self.verbose = verbose
        self.logger = Logger()
        
        # 定义要清理的路径
        self.cleanup_paths = {
            'database': self.project_root / 'logs.db',
            'temp_dir': self.project_root / 'temp',
            'logs_dir': self.project_root / 'logs',
            'data_dir': self.project_root / 'data',
            'uploads_dir': self.project_root / 'uploads',
        }
    
    def get_size(self, path: Path) -> str:
        """获取文件或目录大小"""
        if not path.exists():
            return "不存在"
        
        try:
            if path.is_file():
                size = path.stat().st_size
            else:
                size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
            
            # 转换为人类可读格式
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    return f"{size:.1f}{unit}"
                size /= 1024.0
            return f"{size:.1f}TB"
        except (OSError, PermissionError):
            return "未知"
    
    def show_cleanup_plan(self):
        """显示清理计划"""
        self.logger.info("清理计划：")
        print(f"  📁 项目根目录: {self.project_root}")
        
        for name, path in self.cleanup_paths.items():
            size = self.get_size(path)
            icon = "🗃️" if name == "database" else "📂"
            
            if name == "uploads_dir" and self.keep_uploads:
                print(f"  {icon} {path.name}: 保留 ({size})")
            else:
                print(f"  {icon} {path.name}: {size}")
        
        if self.docker_cleanup:
            print("  🐳 Docker volumes 和 containers")
        
        print("  🐍 Python 缓存文件 (__pycache__)")
        print()
    
    def stop_services(self):
        """停止相关服务"""
        if self.dry_run:
            self.logger.info("[DRY RUN] 将停止相关服务")
            return
        
        self.logger.info("停止相关服务...")
        
        # 停止可能运行的进程
        try:
            subprocess.run(['pkill', '-f', 'celery.*app.celery_app'], 
                         capture_output=True, check=False)
            subprocess.run(['pkill', '-f', 'uvicorn.*app.main'], 
                         capture_output=True, check=False)
        except FileNotFoundError:
            pass  # pkill 命令不存在
        
        # 如果有stop.sh脚本，使用它
        stop_script = self.project_root / 'stop.sh'
        if stop_script.exists():
            try:
                subprocess.run(['bash', str(stop_script)], 
                             capture_output=True, check=False)
            except Exception:
                pass
        
        self.logger.success("服务已停止")
    
    def cleanup_database(self):
        """清理数据库"""
        db_path = self.cleanup_paths['database']
        
        if not db_path.exists():
            if self.verbose:
                self.logger.info("数据库文件不存在，跳过")
            return
        
        if self.dry_run:
            self.logger.info(f"[DRY RUN] 将清理数据库: {db_path}")
            return
        
        # 尝试获取数据库统计信息
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM log_records")
            record_count = cursor.fetchone()[0]
            conn.close()
            
            if self.verbose:
                self.logger.info(f"数据库包含 {record_count} 条日志记录")
        except Exception:
            pass
        
        try:
            db_path.unlink()
            self.logger.success("已清理数据库文件")
        except Exception as e:
            self.logger.error(f"清理数据库失败: {e}")
    
    def cleanup_directory(self, path: Path, description: str):
        """清理目录内容"""
        if not path.exists():
            if self.verbose:
                self.logger.info(f"{description}: 不存在，跳过")
            return
        
        size = self.get_size(path)
        
        if self.dry_run:
            self.logger.info(f"[DRY RUN] 将清理 {description} ({size})")
            return
        
        if self.verbose:
            self.logger.info(f"清理 {description} ({size})...")
        
        try:
            # 清理目录内容但保留目录本身
            for item in path.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            
            self.logger.success(f"已清理 {description}")
        except Exception as e:
            self.logger.error(f"清理 {description} 失败: {e}")
    
    def cleanup_python_cache(self):
        """清理Python缓存"""
        if self.dry_run:
            self.logger.info("[DRY RUN] 将清理Python缓存")
            return
        
        self.logger.info("清理Python缓存...")
        
        cache_count = 0
        try:
            # 清理 __pycache__ 目录
            for pycache_dir in self.project_root.rglob('__pycache__'):
                if pycache_dir.is_dir():
                    shutil.rmtree(pycache_dir, ignore_errors=True)
                    cache_count += 1
            
            # 清理 .pyc 和 .pyo 文件
            for pyc_file in self.project_root.rglob('*.pyc'):
                pyc_file.unlink(missing_ok=True)
                cache_count += 1
            
            for pyo_file in self.project_root.rglob('*.pyo'):
                pyo_file.unlink(missing_ok=True)
                cache_count += 1
            
            self.logger.success(f"已清理Python缓存 ({cache_count} 个文件/目录)")
        except Exception as e:
            self.logger.error(f"清理Python缓存失败: {e}")
    
    def cleanup_docker(self):
        """清理Docker相关数据"""
        if not self.docker_cleanup:
            return
        
        self.logger.info("清理Docker相关数据...")
        
        if not shutil.which('docker'):
            self.logger.warning("Docker未安装，跳过Docker清理")
            return
        
        if self.dry_run:
            self.logger.info("[DRY RUN] 将清理Docker volumes和containers")
            return
        
        try:
            # 使用docker-compose清理
            compose_file = self.project_root / 'docker-compose.yml'
            if compose_file.exists():
                subprocess.run(['docker-compose', 'down', '-v'], 
                             cwd=self.project_root, capture_output=True, check=False)
                self.logger.success("已执行docker-compose清理")
            
            # 清理相关容器
            result = subprocess.run(['docker', 'ps', '-a', '--filter', 
                                   'name=logstagingservice', '--format', '{{.Names}}'],
                                  capture_output=True, text=True, check=False)
            
            if result.stdout.strip():
                containers = result.stdout.strip().split('\n')
                for container in containers:
                    subprocess.run(['docker', 'stop', container], 
                                 capture_output=True, check=False)
                    subprocess.run(['docker', 'rm', container], 
                                 capture_output=True, check=False)
                self.logger.success(f"已清理Docker容器: {', '.join(containers)}")
            
            # 清理相关volumes
            result = subprocess.run(['docker', 'volume', 'ls', '--filter', 
                                   'name=logstagingservice', '--format', '{{.Name}}'],
                                  capture_output=True, text=True, check=False)
            
            if result.stdout.strip():
                volumes = result.stdout.strip().split('\n')
                for volume in volumes:
                    subprocess.run(['docker', 'volume', 'rm', volume], 
                                 capture_output=True, check=False)
                self.logger.success(f"已清理Docker volumes: {', '.join(volumes)}")
                
        except Exception as e:
            self.logger.error(f"Docker清理失败: {e}")
    
    def recreate_directories(self):
        """重新创建必要的目录"""
        if self.dry_run:
            return
        
        directories = ['temp', 'logs', 'data', 'uploads']
        
        for dir_name in directories:
            dir_path = self.project_root / dir_name
            dir_path.mkdir(exist_ok=True)
        
        # 创建.gitkeep文件
        (self.project_root / 'temp' / '.gitkeep').touch()
        (self.project_root / 'logs' / '.gitkeep').touch()
        
        self.logger.success("已重新创建必要目录")
    
    def run_cleanup(self):
        """执行清理"""
        self.logger.info("开始清理运行时数据...")
        
        # 停止服务
        self.stop_services()
        
        # 清理数据库
        self.cleanup_database()
        
        # 清理目录
        self.cleanup_directory(self.cleanup_paths['temp_dir'], "临时文件目录")
        self.cleanup_directory(self.cleanup_paths['logs_dir'], "日志文件目录")
        self.cleanup_directory(self.cleanup_paths['data_dir'], "数据目录")
        
        # 清理uploads目录（可选）
        if not self.keep_uploads:
            self.cleanup_directory(self.cleanup_paths['uploads_dir'], "上传文件目录")
        else:
            self.logger.info("保留uploads目录")
        
        # 清理Python缓存
        self.cleanup_python_cache()
        
        # 清理Docker数据（可选）
        self.cleanup_docker()
        
        # 重新创建目录
        self.recreate_directories()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='LogStagingService 运行时数据清理工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                    # 交互式清理
  %(prog)s -f                 # 强制清理所有数据
  %(prog)s -f --keep-uploads  # 强制清理但保留uploads
  %(prog)s -d                 # 清理包括Docker数据
  %(prog)s --dry-run          # 预览清理内容
        """
    )
    
    parser.add_argument('-f', '--force', action='store_true',
                       help='强制清理，不询问确认')
    parser.add_argument('--keep-uploads', action='store_true', default=True,
                       help='保留uploads目录（默认）')
    parser.add_argument('--remove-uploads', action='store_true',
                       help='同时清理uploads目录')
    parser.add_argument('-d', '--docker', action='store_true',
                       help='同时清理Docker相关数据')
    parser.add_argument('--dry-run', action='store_true',
                       help='仅显示将要清理的内容，不实际执行')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='详细输出')
    
    args = parser.parse_args()
    
    # 获取项目根目录
    script_dir = Path(__file__).parent.absolute()
    
    # 检查是否在项目根目录
    if not (script_dir / 'app' / 'main.py').exists():
        Logger.error("请在LogStagingService项目根目录下运行此脚本")
        sys.exit(1)
    
    # 处理uploads参数
    keep_uploads = args.keep_uploads and not args.remove_uploads
    
    # 创建清理器
    cleaner = RuntimeDataCleaner(
        project_root=script_dir,
        keep_uploads=keep_uploads,
        docker_cleanup=args.docker,
        dry_run=args.dry_run,
        verbose=args.verbose
    )
    
    print("🧹 LogStagingService 运行时数据清理工具")
    print("=" * 48)
    print()
    
    # 显示清理计划
    cleaner.show_cleanup_plan()
    
    # 确认清理
    if not args.force and not args.dry_run:
        print()
        Logger.warning("⚠️  此操作将清理所有运行时数据，包括：")
        print("   • 数据库中的所有日志记录")
        print("   • 所有临时文件和缓存")
        print("   • 应用程序日志")
        if not keep_uploads:
            print("   • 用户上传的文件")
        if args.docker:
            print("   • Docker容器和数据卷")
        print()
        
        try:
            response = input("确定要继续吗？(y/N): ").strip().lower()
            if response not in ['y', 'yes']:
                Logger.info("操作已取消")
                sys.exit(0)
        except KeyboardInterrupt:
            print()
            Logger.info("操作已取消")
            sys.exit(0)
    
    print()
    
    # 执行清理
    try:
        cleaner.run_cleanup()
        
        print()
        if args.dry_run:
            Logger.success("✅ 预览完成！使用 -f 参数执行实际清理")
        else:
            Logger.success("✅ 清理完成！所有运行时数据已清理")
            print()
            Logger.info("💡 提示：")
            print("   • 可以使用 ./start.sh 重新启动服务")
            print("   • 数据库将在下次启动时自动初始化")
            print("   • 如需恢复数据，请从备份中还原")
            
    except KeyboardInterrupt:
        print()
        Logger.info("清理已中断")
        sys.exit(1)
    except Exception as e:
        Logger.error(f"清理过程中发生错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()