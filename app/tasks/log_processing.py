"""协议栈日志处理异步任务"""

import os
import time
import tarfile
import shutil
import subprocess
import hashlib
import logging
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

# 设置日志记录器
logger = logging.getLogger(__name__)


def _log_performance_stats(operation: str, start_time: float, file_size: int = None, additional_info: dict = None):
    """
    记录性能统计信息
    
    Args:
        operation: 操作名称
        start_time: 开始时间
        file_size: 文件大小（字节）
        additional_info: 额外信息字典
    """
    elapsed_time = time.time() - start_time
    throughput = None
    
    if file_size and file_size > 0:
        throughput = file_size / elapsed_time / (1024 * 1024)  # MB/s
    
    log_msg = f"PerformanceStats - {operation}: 耗时={elapsed_time:.2f}秒"
    
    if throughput:
        log_msg += f", 吞吐量={throughput:.2f}MB/s"
    
    if additional_info:
        for key, value in additional_info.items():
            log_msg += f", {key}={value}"
    
    logger.info(log_msg)


def _check_and_log_directory_status(directory_path: str, operation_name: str, required: bool = True) -> bool:
    """
    检查并记录目录状态
    
    Args:
        directory_path: 目录路径
        operation_name: 操作名称（用于日志）
        required: 是否要求目录必须存在
        
    Returns:
        bool: 目录是否存在
        
    Raises:
        FileNotFoundError: 当required=True且目录不存在时
    """
    abs_path = os.path.abspath(directory_path)
    exists = os.path.exists(abs_path)
    is_dir = os.path.isdir(abs_path) if exists else False
    
    if exists and is_dir:
        # 获取目录内容信息
        try:
            files = os.listdir(abs_path)
            file_count = len(files)
            total_size = 0
            
            for file_name in files:
                file_path = os.path.join(abs_path, file_name)
                if os.path.isfile(file_path):
                    total_size += os.path.getsize(file_path)
            
            logger.info(f"DirectoryStatus - {operation_name}: 目录存在且可访问, 路径={abs_path}, 文件数量={file_count}, 总大小={total_size}字节")
            if file_count > 0:
                # 显示前几个文件名作为示例
                sample_files = files[:5]
                logger.debug(f"DirectoryStatus - {operation_name}: 目录内容示例={sample_files}")
        except PermissionError as e:
            logger.warning(f"DirectoryStatus - {operation_name}: 目录存在但无法访问内容, 路径={abs_path}, 错误={str(e)}")
        except Exception as e:
            logger.warning(f"DirectoryStatus - {operation_name}: 目录存在但检查内容时出错, 路径={abs_path}, 错误={str(e)}")
            
    elif exists and not is_dir:
        logger.error(f"DirectoryStatus - {operation_name}: 路径存在但不是目录, 路径={abs_path}")
        if required:
            raise FileNotFoundError(f"Path exists but is not a directory: {abs_path}")
    else:
        logger.warning(f"DirectoryStatus - {operation_name}: 目录不存在, 路径={abs_path}")
        if required:
            raise FileNotFoundError(f"Required directory does not exist: {abs_path}")
    
    return exists and is_dir


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
    
    logger.info(f"LogProcessingTask - 开始处理协议栈日志: 任务ID={task_id}, 日志ID={log_id}, 重试次数={self.request.retries}")
    
    # 获取数据库会话（同步方式）
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    from app.config import settings
    
    # 创建同步数据库引擎和会话
    # 正确构建同步SQLite连接URL
    database_url = settings.get_database_url()
    if 'sqlite+aiosqlite' in database_url:
        sync_database_url = database_url.replace('sqlite+aiosqlite', 'sqlite')
    elif 'postgresql+asyncpg' in database_url:
        sync_database_url = database_url.replace('postgresql+asyncpg', 'postgresql+psycopg2')
    else:
        # 如果是其他数据库类型，保持原样但移除异步驱动器
        sync_database_url = database_url.replace('+asyncpg', '').replace('+aiosqlite', '')
    
    logger.debug(f"LogProcessingTask - 创建数据库连接: 数据库URL={sync_database_url}")
    # 为Celery任务创建独立的数据库引擎，避免连接池冲突
    sync_engine = create_engine(
        sync_database_url,
        pool_size=1,  # 减少连接池大小
        max_overflow=0,  # 不允许溢出连接
        pool_timeout=30,
        pool_recycle=3600,
        echo=False  # 减少日志输出
    )
    SessionLocal = sessionmaker(bind=sync_engine)
    db_session = SessionLocal()
    
    try:
        # 获取日志记录 - 优化重试机制
        logger.debug(f"LogProcessingTask - 查询日志记录: 日志ID={log_id}")
        log_record = None
        max_retries = 3  # 减少重试次数，因为数据库事务已经立即提交
        retry_delay = 0.5  # 减少初始延迟时间
        
        for attempt in range(max_retries):
            # 刷新数据库会话以确保获取最新数据
            db_session.expire_all()
            log_record = db_session.query(LogRecord).filter(LogRecord.id == log_id).first()
            if log_record:
                logger.info(f"LogProcessingTask - 成功找到日志记录: 日志ID={log_id}, 尝试次数={attempt + 1}")
                break
            
            if attempt < max_retries - 1:
                logger.warning(f"LogProcessingTask - 日志记录暂时不存在，等待重试: 日志ID={log_id}, 尝试次数={attempt + 1}/{max_retries}, 等待时间={retry_delay}秒")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2.0, 2.0)  # 指数退避，最大2秒
            else:
                logger.error(f"LogProcessingTask - 经过{max_retries}次重试后仍未找到日志记录: 日志ID={log_id}")
                raise ValueError(f"Log record with id {log_id} not found after {max_retries} retries")
        
        logger.info(f"LogProcessingTask - 找到日志记录: 文件名={log_record.original_filename}, 文件大小={log_record.file_size}字节, 当前状态={log_record.status}")
        
        # 更新任务状态和相关信息
        log_record.task_id = task_id
        log_record.status = LogStatus.PROCESSING
        log_record.processing_started_at = datetime.utcnow()
        log_record.progress = 0.0
        
        # 确保设置为协议栈类型
        from app.models.log import LogType
        log_record.log_type = LogType.STACK
        
        db_session.commit()
        logger.info(f"LogProcessingTask - 任务状态已更新为处理中: 任务ID={task_id}, 日志类型={log_record.log_type}")
        
        # 检查文件是否存在
        if not os.path.exists(log_record.file_path):
            logger.error(f"LogProcessingTask - 日志文件不存在: 文件路径={log_record.file_path}")
            raise FileNotFoundError(f"Log file not found: {log_record.file_path}")
        
        logger.info(f"LogProcessingTask - 日志文件验证通过: 文件路径={log_record.file_path}")
        
        # 创建临时工作目录 - 使用绝对路径确保路径解析正确
        temp_work_dir = os.path.abspath(os.path.join(settings.temp_dir, f"processing_{task_id}"))
        logger.info(f"LogProcessingTask - 准备创建临时工作目录: {temp_work_dir}")
        
        try:
            os.makedirs(temp_work_dir, exist_ok=True)
            logger.info(f"LogProcessingTask - 临时工作目录创建成功: {temp_work_dir}")
        except Exception as e:
            logger.error(f"LogProcessingTask - 创建临时工作目录失败: {str(e)}")
            raise RuntimeError(f"Failed to create temporary work directory: {str(e)}")
        
        # 验证临时工作目录创建成功
        _check_and_log_directory_status(temp_work_dir, "临时工作目录创建后验证", required=True)
        
        try:
            # 步骤1: 解压文件 (进度 0-20%)
            logger.info(f"LogProcessingTask - 开始步骤1: 解压日志文件")
            # 步骤1开始前的目录状态检查
            _check_and_log_directory_status(temp_work_dir, "步骤1开始前-临时工作目录状态", required=True)
            
            extracted_dir = _extract_log_file(log_record.file_path, temp_work_dir)
            _update_progress(db_session, log_record, 20.0)
            logger.info(f"LogProcessingTask - 步骤1完成: 解压文件到目录={os.path.abspath(extracted_dir)}")
            
            # 步骤1完成后验证解压目录
            _check_and_log_directory_status(extracted_dir, "步骤1完成后-解压目录验证", required=True)
            
            # 步骤2: 调用外部工具处理 (进度 20-80%)
            logger.info(f"LogProcessingTask - 开始步骤2: 调用外部工具处理日志")
            # 步骤2开始前的目录状态检查
            _check_and_log_directory_status(extracted_dir, "步骤2开始前-解压目录状态", required=True)
            _check_and_log_directory_status(temp_work_dir, "步骤2开始前-临时工作目录状态", required=True)
            
            processed_dir = _process_with_external_tool(
                extracted_dir, 
                temp_work_dir, 
                log_record.file_size,
                db_session,
                log_record
            )
            logger.info(f"LogProcessingTask - 步骤2完成: 外部工具处理完成，输出目录={os.path.abspath(processed_dir)}")
            
            # 步骤2完成后验证处理目录
            _check_and_log_directory_status(processed_dir, "步骤2完成后-处理目录验证", required=True)
            
            # 步骤3: 重新打包 (进度 80-95%)
            logger.info(f"LogProcessingTask - 开始步骤3: 重新打包处理后的文件")
            # 步骤3开始前的目录状态检查
            _check_and_log_directory_status(processed_dir, "步骤3开始前-处理目录状态", required=True)
            _check_and_log_directory_status(temp_work_dir, "步骤3开始前-临时工作目录状态", required=True)
            
            processed_file_path = _repackage_processed_files(
                processed_dir, 
                log_record.original_filename,
                temp_work_dir
            )
            _update_progress(db_session, log_record, 95.0)
            logger.info(f"LogProcessingTask - 步骤3完成: 重新打包完成，文件路径={os.path.abspath(processed_file_path)}")
            
            # 步骤3完成后验证打包文件
            if not os.path.exists(processed_file_path):
                raise FileNotFoundError(f"Repackaged file not found: {processed_file_path}")
            logger.info(f"LogProcessingTask - 步骤3验证: 打包文件存在，大小={os.path.getsize(processed_file_path)}字节")
            
            # 步骤4: 替换原文件并更新记录 (进度 95-100%)
            logger.info(f"LogProcessingTask - 开始步骤4: 替换原始文件")
            # 步骤4开始前验证打包文件和原始文件
            if not os.path.exists(processed_file_path):
                raise FileNotFoundError(f"Processed file not found before replacement: {processed_file_path}")
            if not os.path.exists(log_record.file_path):
                raise FileNotFoundError(f"Original file not found before replacement: {log_record.file_path}")
            logger.info(f"LogProcessingTask - 步骤4验证: 文件替换前检查通过")
            
            final_file_path = _replace_original_file(processed_file_path, log_record.file_path)
            logger.info(f"LogProcessingTask - 步骤4完成: 文件替换成功")
            
            # 更新数据库记录
            logger.info(f"LogProcessingTask - 开始更新数据库记录")
            original_file_size = log_record.file_size
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
            logger.info(f"LogProcessingTask - 处理完成: 日志ID={log_id}, 处理时间={processing_time:.2f}秒, 原文件大小={original_file_size}字节, 处理后大小={log_record.file_size}字节, 校验和={log_record.checksum}")
            
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
                logger.info(f"LogProcessingTask - 清理临时工作目录: {temp_work_dir}")
                shutil.rmtree(temp_work_dir, ignore_errors=True)
                logger.debug(f"LogProcessingTask - 临时工作目录清理完成")
                
    except Exception as exc:
        # 错误处理
        error_message = str(exc)
        processing_time = time.time() - start_time
        
        logger.error(f"LogProcessingTask - 处理过程中发生异常: 日志ID={log_id}, 任务ID={task_id}, 错误信息={error_message}, 处理时间={processing_time:.2f}秒, 异常类型={type(exc).__name__}", exc_info=True)
        
        # 更新数据库记录 - 安全检查log_record是否存在且不为None
        if 'log_record' in locals() and log_record is not None:
            try:
                log_record.status = LogStatus.FAILED
                log_record.error_message = error_message
                log_record.retry_count += 1
                db_session.commit()
                logger.info(f"LogProcessingTask - 数据库记录已更新为失败状态: 重试次数={log_record.retry_count}")
            except Exception as db_error:
                logger.error(f"LogProcessingTask - 更新数据库记录失败: {str(db_error)}")
                try:
                    db_session.rollback()
                except Exception as rollback_error:
                    logger.error(f"LogProcessingTask - 数据库回滚失败: {str(rollback_error)}")
        else:
            logger.warning(f"LogProcessingTask - 无法更新数据库记录，log_record不存在或为None: 日志ID={log_id}")
        
        # 重试逻辑
        if self.request.retries < self.max_retries:
            # 指数退避重试
            countdown = 2 ** self.request.retries * 60  # 1分钟, 2分钟, 4分钟
            logger.warning(f"LogProcessingTask - 准备重试任务: 当前重试次数={self.request.retries}, 最大重试次数={self.max_retries}, 等待时间={countdown}秒")
            raise self.retry(exc=exc, countdown=countdown)
        
        # 最终失败
        logger.error(f"LogProcessingTask - 任务最终失败: 日志ID={log_id}, 任务ID={task_id}, 总重试次数={self.request.retries}, 错误信息={error_message}")
        return {
            "status": "failed",
            "log_id": log_id,
            "task_id": task_id,
            "error": error_message,
            "retry_count": getattr(log_record, 'retry_count', 0) if 'log_record' in locals() else 0
        }
        
    finally:
        logger.debug(f"LogProcessingTask - 关闭数据库连接: 任务ID={task_id}")
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
    # 检查临时工作目录状态
    _check_and_log_directory_status(temp_dir, "解压前-临时工作目录检查", required=True)
    
    extracted_dir = os.path.join(temp_dir, "extracted")
    
    # 记录目标解压目录信息
    logger.info(f"ExtractTask - 准备创建解压目录: 目标路径={os.path.abspath(extracted_dir)}")
    
    # 检查解压目录是否已存在
    if os.path.exists(extracted_dir):
        logger.warning(f"ExtractTask - 解压目录已存在，将清理后重新创建: {os.path.abspath(extracted_dir)}")
        try:
            shutil.rmtree(extracted_dir)
            logger.info(f"ExtractTask - 已清理现有解压目录")
        except Exception as e:
            logger.error(f"ExtractTask - 清理现有解压目录失败: {str(e)}")
            raise RuntimeError(f"Failed to clean existing extraction directory: {str(e)}")
    
    # 创建解压目录
    try:
        os.makedirs(extracted_dir, exist_ok=True)
        logger.info(f"ExtractTask - 解压目录创建成功: {os.path.abspath(extracted_dir)}")
    except Exception as e:
        logger.error(f"ExtractTask - 创建解压目录失败: {str(e)}")
        raise RuntimeError(f"Failed to create extraction directory: {str(e)}")
    
    # 验证解压目录创建成功
    _check_and_log_directory_status(extracted_dir, "解压目录创建后验证", required=True)
    
    logger.info(f"ExtractTask - 开始解压文件: 源文件={file_path}, 目标目录={extracted_dir}")
    
    try:
        start_time = time.time()
        file_size = os.path.getsize(file_path)
        
        # 验证源文件存在性
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Source file does not exist: {file_path}")
        
        logger.info(f"ExtractTask - 源文件验证通过: 文件大小={file_size}字节")
        
        with tarfile.open(file_path, 'r:gz') as tar:
            # 获取压缩包中的文件列表
            file_list = tar.getnames()
            logger.info(f"ExtractTask - 压缩包分析完成: 包含文件数={len(file_list)}")
            logger.debug(f"ExtractTask - 压缩包文件列表前10项: {file_list[:10]}")
            
            # 解压文件
            logger.info(f"ExtractTask - 开始解压文件到目录: {os.path.abspath(extracted_dir)}")
            tar.extractall(path=extracted_dir)
            logger.info(f"ExtractTask - 文件解压完成")
            
        # 验证解压结果
        _check_and_log_directory_status(extracted_dir, "解压完成后验证", required=True)
        
        # 记录性能统计
        _log_performance_stats(
            "文件解压", 
            start_time, 
            file_size, 
            {"文件数": len(file_list), "源文件": os.path.basename(file_path)}
        )
        
        logger.info(f"ExtractTask - 解压任务完成: 解压目录={os.path.abspath(extracted_dir)}")
        
    except Exception as e:
        logger.error(f"ExtractTask - 文件解压失败: 源文件={file_path}, 错误信息={str(e)}", exc_info=True)
        # 清理失败的解压目录
        if os.path.exists(extracted_dir):
            try:
                shutil.rmtree(extracted_dir, ignore_errors=True)
                logger.info(f"ExtractTask - 已清理失败的解压目录")
            except Exception as cleanup_error:
                logger.warning(f"ExtractTask - 清理失败的解压目录时出错: {str(cleanup_error)}")
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
        input_dir: 输入目录 (extracted目录)
        temp_dir: 临时目录
        total_file_size: 总文件大小
        db_session: 数据库会话
        log_record: 日志记录
        
    Returns:
        str: 处理后的目录路径 (tool_log_decompress会直接在input_dir中生成结果)
    """
    logger.info(f"ExternalToolTask - 开始外部工具处理: 输入目录={input_dir}, 临时目录={temp_dir}, 文件大小={total_file_size}字节")
    
    # 验证临时工作目录状态
    if not _check_and_log_directory_status(temp_dir, "ExternalToolTask - 临时工作目录", required=True):
        raise RuntimeError(f"Temporary directory is not accessible: {temp_dir}")
    
    # 验证输入目录状态（必须存在且可访问）
    if not _check_and_log_directory_status(input_dir, "ExternalToolTask - 输入目录", required=True):
        raise RuntimeError(f"Input directory is not accessible: {input_dir}")
    
    # 检查输入目录是否为目录
    if not os.path.isdir(input_dir):
        error_msg = f"输入路径不是目录: {input_dir}"
        logger.error(f"ExternalToolTask - {error_msg}")
        raise RuntimeError(f"Input path is not a directory: {input_dir}")
    
    # 构建外部工具命令 - 使用绝对路径确保外部工具能正确找到输入目录
    abs_input_dir = os.path.abspath(input_dir)
    cmd = [
        "tool_log_decompress",
        abs_input_dir,
        str(settings.thread_num_for_decompress)
    ]
    
    logger.info(f"ExternalToolTask - 外部工具命令配置: 命令={cmd}, 线程数={settings.thread_num_for_decompress}")
    logger.info(f"ExternalToolTask - 路径信息: 输入目录(相对)={input_dir}, 输入目录(绝对)={abs_input_dir}")
    logger.info(f"ExternalToolTask - 注意: tool_log_decompress工具会直接在输入目录中生成处理结果")
    
    # 检查输入目录中的文件详情
    try:
        input_files = os.listdir(input_dir)
        logger.info(f"ExternalToolTask - 输入目录内容分析: 文件数量={len(input_files)}, 文件列表={input_files[:10]}{'...' if len(input_files) > 10 else ''}")
        
        if len(input_files) == 0:
            logger.warning(f"ExternalToolTask - 警告: 输入目录为空")
        
    except Exception as e:
        error_msg = f"无法读取输入目录内容: {str(e)}"
        logger.error(f"ExternalToolTask - {error_msg}")
        raise RuntimeError(f"Cannot read input directory contents: {str(e)}")
    
    # 检查外部工具是否存在
    import shutil as sh_util
    tool_path = sh_util.which("tool_log_decompress")
    if tool_path:
        logger.info(f"ExternalToolTask - 找到外部工具: 路径={tool_path}")
        # 检查工具是否可执行
        if not os.access(tool_path, os.X_OK):
            error_msg = f"外部工具不可执行: {tool_path}"
            logger.error(f"ExternalToolTask - {error_msg}")
            raise RuntimeError(f"External tool is not executable: {tool_path}")
    else:
        logger.warning(f"ExternalToolTask - 外部工具不在PATH中，尝试使用相对路径")
    
    try:
        # 启动外部进程 - 使用临时目录作为工作目录
        logger.info(f"ExternalToolTask - 启动外部进程: 工作目录={temp_dir}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=temp_dir,
            text=True,
            env=os.environ.copy()  # 传递环境变量
        )
        
        logger.info(f"ExternalToolTask - 外部进程已启动: PID={process.pid}")
        
        # 监控进度
        start_time = time.time()
        progress_update_count = 0
        last_log_time = start_time
        
        while process.poll() is None:
            elapsed_time = time.time() - start_time
            
            # 基于时间和文件大小估算进度
            estimated_progress = min(
                20.0 + (elapsed_time * settings.log_processing_speed_mb_per_sec * 1024 * 1024) / total_file_size * 60.0,
                80.0
            )
            
            _update_progress(db_session, log_record, estimated_progress)
            progress_update_count += 1
            
            # 每30秒记录一次详细日志，每10次进度更新记录一次简要日志
            current_time = time.time()
            if current_time - last_log_time >= 30:
                logger.info(f"ExternalToolTask - 详细进度监控: 已运行时间={elapsed_time:.1f}秒, 估算进度={estimated_progress:.1f}%, 进程状态=运行中, PID={process.pid}")
                last_log_time = current_time
            elif progress_update_count % 10 == 0:
                logger.debug(f"ExternalToolTask - 进度监控: 已运行时间={elapsed_time:.1f}秒, 估算进度={estimated_progress:.1f}%, 进程状态=运行中")
            
            time.sleep(5)  # 每5秒更新一次进度
        
        # 检查进程结果
        stdout, stderr = process.communicate()
        total_time = time.time() - start_time
        
        logger.info(f"ExternalToolTask - 外部进程执行完成: 返回码={process.returncode}, 执行时间={total_time:.2f}秒")
        
        # 记录完整的输出信息
        if stdout:
            stdout_preview = stdout[:1000] + "..." if len(stdout) > 1000 else stdout
            logger.info(f"ExternalToolTask - 标准输出 (长度={len(stdout)}): {stdout_preview}")
        else:
            logger.info(f"ExternalToolTask - 标准输出: 无输出")
        
        if stderr:
            stderr_preview = stderr[:1000] + "..." if len(stderr) > 1000 else stderr
            logger.warning(f"ExternalToolTask - 标准错误 (长度={len(stderr)}): {stderr_preview}")
        else:
            logger.info(f"ExternalToolTask - 标准错误: 无错误输出")
        
        # 验证输出目录状态 - 检查输入目录，因为tool_log_decompress会在输入目录中生成结果
        logger.info(f"ExternalToolTask - 开始验证输出目录状态")
        if not _check_and_log_directory_status(input_dir, "ExternalToolTask - 输出目录", required=True):
            logger.error(f"ExternalToolTask - 输出目录验证失败")
            # 即使目录验证失败，也继续检查进程返回码，以提供完整的错误信息
        
        # 检查输出目录内容详情 - 检查输入目录中的处理结果
        try:
            output_files = os.listdir(input_dir)
            logger.info(f"ExternalToolTask - 输出目录内容分析: 文件数量={len(output_files)}, 文件列表={output_files[:10]}{'...' if len(output_files) > 10 else ''}")
            
            if len(output_files) == 0:
                logger.warning(f"ExternalToolTask - 警告: 输出目录为空，外部工具可能未生成任何文件")
            else:
                logger.info(f"ExternalToolTask - 输出目录验证成功，包含 {len(output_files)} 个文件")
                
        except Exception as e:
            logger.error(f"ExternalToolTask - 无法读取输出目录内容: {str(e)}")
        
        if process.returncode != 0:
            # 提供更详细的错误信息
            error_details = []
            error_details.append(f"返回码: {process.returncode}")
            
            if stderr:
                error_details.append(f"错误输出: {stderr}")
            else:
                error_details.append("错误输出: 无")
            
            if stdout:
                error_details.append(f"标准输出: {stdout}")
            else:
                error_details.append("标准输出: 无")
            
            error_details.append(f"执行时间: {total_time:.2f}秒")
            error_details.append(f"工作目录: {temp_dir}")
            error_details.append(f"命令: {' '.join(cmd)}")
            
            # 常见错误码的解释
            error_code_meanings = {
                1: "一般错误",
                2: "误用shell命令",
                126: "命令不可执行",
                127: "命令未找到",
                128: "无效的退出参数",
                130: "脚本被Ctrl+C终止",
                255: "退出状态超出范围或其他严重错误"
            }
            
            if process.returncode in error_code_meanings:
                error_details.append(f"错误码含义: {error_code_meanings[process.returncode]}")
            
            full_error_msg = "; ".join(error_details)
            logger.error(f"ExternalToolTask - 外部工具执行失败: {full_error_msg}")
            raise RuntimeError(f"External tool failed with return code {process.returncode}: {full_error_msg}")
        
        # 最终进度设为80%
        _update_progress(db_session, log_record, 80.0)
        logger.info(f"ExternalToolTask - 外部工具处理成功完成")
        
    except FileNotFoundError as e:
        error_msg = f"外部工具未找到: tool_log_decompress, 详细错误: {str(e)}"
        logger.error(f"ExternalToolTask - {error_msg}")
        raise RuntimeError(f"External tool 'tool_log_decompress' not found. Please ensure it's installed and in PATH. Details: {str(e)}")
    except subprocess.TimeoutExpired as e:
        error_msg = f"外部工具执行超时: {str(e)}"
        logger.error(f"ExternalToolTask - {error_msg}")
        raise RuntimeError(f"External tool execution timed out: {str(e)}")
    except PermissionError as e:
        error_msg = f"权限错误: {str(e)}"
        logger.error(f"ExternalToolTask - {error_msg}")
        raise RuntimeError(f"Permission error when executing external tool: {str(e)}")
    except Exception as e:
        error_msg = f"外部工具处理失败: 错误类型={type(e).__name__}, 错误信息={str(e)}"
        logger.error(f"ExternalToolTask - {error_msg}", exc_info=True)
        raise RuntimeError(f"Failed to process with external tool: {type(e).__name__}: {str(e)}")
    
    # 返回输入目录，因为tool_log_decompress会直接在输入目录中生成处理结果
    return input_dir


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
    logger.info(f"RepackageTask - 开始重新打包: 输入目录={processed_dir}, 输出文件={output_file}")
    
    try:
        start_time = time.time()
        
        with tarfile.open(output_file, 'w:gz') as tar:
            file_count = 0
            total_size = 0
            for root, dirs, files in os.walk(processed_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, processed_dir)
                    tar.add(file_path, arcname=arcname)
                    file_count += 1
                    total_size += os.path.getsize(file_path)
        
        # 记录性能统计
        _log_performance_stats(
            "文件重新打包", 
            start_time, 
            total_size, 
            {"文件数": file_count, "输出文件": os.path.basename(output_file)}
        )
        
    except Exception as e:
        logger.error(f"RepackageTask - 重新打包失败: 错误={str(e)}")
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
    logger.info(f"ReplaceTask - 开始替换原始文件: {processed_file_path} -> {original_file_path}")
    try:
        start_time = time.time()
        file_size = os.path.getsize(processed_file_path)
        
        # 备份原文件（可选）
        backup_path = f"{original_file_path}.backup"
        if os.path.exists(original_file_path):
            shutil.copy2(original_file_path, backup_path)
            logger.info(f"ReplaceTask - 原文件备份完成: {backup_path}")
        
        # 替换文件
        shutil.move(processed_file_path, original_file_path)
        logger.info(f"ReplaceTask - 文件替换成功")
        
        # 删除备份（如果替换成功）
        if os.path.exists(backup_path):
            os.remove(backup_path)
            logger.info(f"ReplaceTask - 备份文件已删除")
        
        # 记录性能统计
        _log_performance_stats(
            "文件替换", 
            start_time, 
            file_size, 
            {"目标文件": os.path.basename(original_file_path)}
        )
            
    except Exception as e:
        # 如果替换失败，尝试恢复备份
        backup_path = f"{original_file_path}.backup"
        if os.path.exists(backup_path):
            shutil.move(backup_path, original_file_path)
            logger.info(f"ReplaceTask - 已恢复备份文件")
        logger.error(f"ReplaceTask - 文件替换失败: 错误={str(e)}")
        raise RuntimeError(f"Failed to replace original file: {str(e)}")
    
    logger.info(f"ReplaceTask - 文件替换操作完成: {original_file_path}")
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
        old_progress = log_record.progress
        new_progress = min(progress, 95.0)  # 最大进度限制95%
        
        # 只有当进度有显著变化时才记录日志（避免过多日志）
        if abs(new_progress - old_progress) >= 5.0 or new_progress >= 95.0:
            logger.info(f"ProgressUpdate - 进度更新: 日志ID={log_record.id}, 任务ID={log_record.task_id}, {old_progress:.1f}% -> {new_progress:.1f}%")
        else:
            logger.debug(f"ProgressUpdate - 进度更新: 日志ID={log_record.id}, {old_progress:.1f}% -> {new_progress:.1f}%")
        
        log_record.progress = new_progress
        log_record.updated_at = datetime.utcnow()
        db_session.commit()
        
    except Exception as e:
        # 进度更新失败不应该影响主流程
        logger.warning(f"ProgressUpdate - 进度更新失败: 日志ID={log_record.id}, 任务ID={getattr(log_record, 'task_id', 'N/A')}, 错误={str(e)}", exc_info=True)
        try:
            db_session.rollback()
        except Exception as rollback_error:
            logger.error(f"ProgressUpdate - 数据库回滚失败: 错误={str(rollback_error)}")