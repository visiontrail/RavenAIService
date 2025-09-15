"""协议栈日志处理异步任务"""

import os
import time
import tarfile
import shutil
import subprocess
import hashlib
from datetime import datetime
from typing import Optional
from pathlib import Path

from celery import current_task
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.models.database import db_manager
from app.models.log import LogRecord, LogStatus
from app.utils.file_utils import get_file_size
from app.utils.validation import file_validator


@celery_app.task(bind=True, max_retries=settings.max_retry_attempts)
def process_protocol_stack_log(self, log_id: str) -> dict:
    """
    处理协议栈日志的异步任务
    
    Args:
        log_id: 日志记录ID
        
    Returns:
        dict: 处理结果
    """
    task_id = self.request.id
    start_time = time.time()
    
    # 获取数据库会话（同步方式）
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    from app.config import settings
    
    # 创建同步数据库引擎和会话
    sync_engine = create_engine(settings.get_database_url().replace('aiosqlite', 'sqlite'))
    SessionLocal = sessionmaker(bind=sync_engine)
    db_session = SessionLocal()
    
    try:
        # 获取日志记录
        log_record = db_session.query(LogRecord).filter(LogRecord.id == log_id).first()
        if not log_record:
            raise ValueError(f"Log record with id {log_id} not found")
        
        # 更新任务状态
        log_record.task_id = task_id
        log_record.status = LogStatus.PROCESSING
        log_record.processing_started_at = datetime.utcnow()
        log_record.progress = 0.0
        db_session.commit()
        
        # 检查文件是否存在
        if not os.path.exists(log_record.file_path):
            raise FileNotFoundError(f"Log file not found: {log_record.file_path}")
        
        # 创建临时工作目录
        temp_work_dir = os.path.join(settings.temp_dir, f"processing_{task_id}")
        os.makedirs(temp_work_dir, exist_ok=True)
        
        try:
            # 步骤1: 解压文件 (进度 0-20%)
            extracted_dir = _extract_log_file(log_record.file_path, temp_work_dir)
            _update_progress(db_session, log_record, 20.0)
            
            # 步骤2: 调用外部工具处理 (进度 20-80%)
            processed_dir = _process_with_external_tool(
                extracted_dir, 
                temp_work_dir, 
                log_record.file_size,
                db_session,
                log_record
            )
            
            # 步骤3: 重新打包 (进度 80-95%)
            processed_file_path = _repackage_processed_files(
                processed_dir, 
                log_record.original_filename,
                temp_work_dir
            )
            _update_progress(db_session, log_record, 95.0)
            
            # 步骤4: 替换原文件并更新记录 (进度 95-100%)
            final_file_path = _replace_original_file(processed_file_path, log_record.file_path)
            
            # 更新数据库记录
            log_record.file_size = get_file_size(final_file_path)
            # 计算文件校验和
            with open(final_file_path, 'rb') as f:
                log_record.checksum = hashlib.sha256(f.read()).hexdigest()
            log_record.status = LogStatus.COMPLETED
            log_record.progress = 100.0
            log_record.processed_at = datetime.utcnow()
            log_record.error_message = None
            db_session.commit()
            
            processing_time = time.time() - start_time
            
            return {
                "status": "completed",
                "log_id": log_id,
                "task_id": task_id,
                "processing_time": processing_time,
                "file_size": log_record.file_size,
                "checksum": log_record.checksum
            }
            
        finally:
            # 清理临时文件
            if os.path.exists(temp_work_dir):
                shutil.rmtree(temp_work_dir, ignore_errors=True)
                
    except Exception as exc:
        # 错误处理
        error_message = str(exc)
        
        # 更新数据库记录
        if 'log_record' in locals():
            log_record.status = LogStatus.FAILED
            log_record.error_message = error_message
            log_record.retry_count += 1
            db_session.commit()
        
        # 重试逻辑
        if self.request.retries < self.max_retries:
            # 指数退避重试
            countdown = 2 ** self.request.retries * 60  # 1分钟, 2分钟, 4分钟
            raise self.retry(exc=exc, countdown=countdown)
        
        # 最终失败
        return {
            "status": "failed",
            "log_id": log_id,
            "task_id": task_id,
            "error": error_message,
            "retry_count": getattr(log_record, 'retry_count', 0) if 'log_record' in locals() else 0
        }
        
    finally:
        db_session.close()


def _extract_log_file(file_path: str, temp_dir: str) -> str:
    """
    解压日志文件
    
    Args:
        file_path: 原始文件路径
        temp_dir: 临时目录
        
    Returns:
        str: 解压后的目录路径
    """
    extracted_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extracted_dir, exist_ok=True)
    
    try:
        with tarfile.open(file_path, 'r:gz') as tar:
            tar.extractall(path=extracted_dir)
    except Exception as e:
        raise RuntimeError(f"Failed to extract file {file_path}: {str(e)}")
    
    return extracted_dir


def _process_with_external_tool(
    input_dir: str, 
    temp_dir: str, 
    total_file_size: int,
    db_session: Session,
    log_record: LogRecord
) -> str:
    """
    使用外部工具处理日志
    
    Args:
        input_dir: 输入目录
        temp_dir: 临时目录
        total_file_size: 总文件大小
        db_session: 数据库会话
        log_record: 日志记录
        
    Returns:
        str: 处理后的目录路径
    """
    processed_dir = os.path.join(temp_dir, "processed")
    os.makedirs(processed_dir, exist_ok=True)
    
    # 构建外部工具命令
    cmd = [
        "tool_log_decompress",
        input_dir,
        str(settings.thread_num_for_decompress)
    ]
    
    try:
        # 启动外部进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=processed_dir,
            text=True
        )
        
        # 监控进度
        start_time = time.time()
        while process.poll() is None:
            elapsed_time = time.time() - start_time
            
            # 基于时间和文件大小估算进度
            estimated_progress = min(
                20.0 + (elapsed_time * settings.log_processing_speed_mb_per_sec * 1024 * 1024) / total_file_size * 60.0,
                80.0
            )
            
            _update_progress(db_session, log_record, estimated_progress)
            time.sleep(5)  # 每5秒更新一次进度
        
        # 检查进程结果
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"External tool failed with return code {process.returncode}: {stderr}")
        
        # 最终进度设为80%
        _update_progress(db_session, log_record, 80.0)
        
    except FileNotFoundError:
        raise RuntimeError("External tool 'tool_log_decompress' not found. Please ensure it's installed and in PATH.")
    except Exception as e:
        raise RuntimeError(f"Failed to process with external tool: {str(e)}")
    
    return processed_dir


def _repackage_processed_files(processed_dir: str, original_filename: str, temp_dir: str) -> str:
    """
    重新打包处理后的文件
    
    Args:
        processed_dir: 处理后的目录
        original_filename: 原始文件名
        temp_dir: 临时目录
        
    Returns:
        str: 打包后的文件路径
    """
    # 生成新的文件名
    base_name = os.path.splitext(os.path.splitext(original_filename)[0])[0]  # 移除 .tar.gz
    new_filename = f"{base_name}_processed.tar.gz"
    output_file = os.path.join(temp_dir, new_filename)
    
    try:
        with tarfile.open(output_file, 'w:gz') as tar:
            for root, dirs, files in os.walk(processed_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, processed_dir)
                    tar.add(file_path, arcname=arcname)
    except Exception as e:
        raise RuntimeError(f"Failed to repackage files: {str(e)}")
    
    return output_file


def _replace_original_file(processed_file_path: str, original_file_path: str) -> str:
    """
    替换原始文件
    
    Args:
        processed_file_path: 处理后的文件路径
        original_file_path: 原始文件路径
        
    Returns:
        str: 最终文件路径
    """
    try:
        # 备份原文件（可选）
        backup_path = f"{original_file_path}.backup"
        if os.path.exists(original_file_path):
            shutil.copy2(original_file_path, backup_path)
        
        # 替换文件
        shutil.move(processed_file_path, original_file_path)
        
        # 删除备份（如果替换成功）
        if os.path.exists(backup_path):
            os.remove(backup_path)
            
    except Exception as e:
        # 如果替换失败，尝试恢复备份
        backup_path = f"{original_file_path}.backup"
        if os.path.exists(backup_path):
            shutil.move(backup_path, original_file_path)
        raise RuntimeError(f"Failed to replace original file: {str(e)}")
    
    return original_file_path


def _update_progress(db_session: Session, log_record: LogRecord, progress: float):
    """
    更新处理进度
    
    Args:
        db_session: 数据库会话
        log_record: 日志记录
        progress: 进度百分比
    """
    try:
        log_record.progress = min(progress, 95.0)  # 最大进度限制95%
        log_record.updated_at = datetime.utcnow()
        db_session.commit()
    except Exception:
        # 进度更新失败不应该影响主流程
        db_session.rollback()