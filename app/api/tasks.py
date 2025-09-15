"""任务查询API接口"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from celery.result import AsyncResult

from app.models.database import get_db
from app.models.log import LogRecord, LogStatus
from app.models.base import BaseResponse
from app.celery_app import celery_app
from pydantic import BaseModel, Field


router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskStatusResponse(BaseModel):
    """任务状态响应模型"""
    task_id: str = Field(..., description="任务ID")
    log_id: str = Field(..., description="日志ID")
    status: LogStatus = Field(..., description="任务状态")
    progress: float = Field(..., ge=0.0, le=100.0, description="处理进度")
    retry_count: int = Field(..., description="重试次数")
    error_message: Optional[str] = Field(None, description="错误信息")
    processing_started_at: Optional[str] = Field(None, description="处理开始时间")
    processed_at: Optional[str] = Field(None, description="处理完成时间")
    celery_task_state: Optional[str] = Field(None, description="Celery任务状态")
    celery_task_info: Optional[dict] = Field(None, description="Celery任务详细信息")


class TaskListResponse(BaseModel):
    """任务列表响应模型"""
    tasks: list[TaskStatusResponse] = Field(..., description="任务列表")
    total: int = Field(..., description="总数量")


@router.get("/status/{task_id}", response_model=BaseResponse)
async def get_task_status(
    task_id: str,
    db: Session = Depends(get_db)
):
    """
    获取任务状态
    
    Args:
        task_id: Celery任务ID
        db: 数据库会话
        
    Returns:
        任务状态信息
    """
    # 从数据库获取任务信息
    log_record = db.query(LogRecord).filter(LogRecord.task_id == task_id).first()
    
    if not log_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found"
        )
    
    # 从Celery获取任务状态
    celery_result = AsyncResult(task_id, app=celery_app)
    celery_state = celery_result.state
    celery_info = celery_result.info if celery_result.info else {}
    
    task_status = TaskStatusResponse(
        task_id=task_id,
        log_id=log_record.id,
        status=log_record.status,
        progress=log_record.progress,
        retry_count=log_record.retry_count,
        error_message=log_record.error_message,
        processing_started_at=log_record.processing_started_at.isoformat() if log_record.processing_started_at else None,
        processed_at=log_record.processed_at.isoformat() if log_record.processed_at else None,
        celery_task_state=celery_state,
        celery_task_info=celery_info
    )
    
    return BaseResponse(
        success=True,
        message="Task status retrieved successfully",
        data=task_status
    )


@router.get("/log/{log_id}/status", response_model=BaseResponse)
async def get_log_task_status(
    log_id: str,
    db: Session = Depends(get_db)
):
    """
    根据日志ID获取任务状态
    
    Args:
        log_id: 日志记录ID
        db: 数据库会话
        
    Returns:
        任务状态信息
    """
    log_record = db.query(LogRecord).filter(LogRecord.id == log_id).first()
    
    if not log_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log with id {log_id} not found"
        )
    
    # 如果没有任务ID，说明还未开始处理
    if not log_record.task_id:
        task_status = TaskStatusResponse(
            task_id="",
            log_id=log_id,
            status=log_record.status,
            progress=log_record.progress,
            retry_count=log_record.retry_count,
            error_message=log_record.error_message,
            processing_started_at=None,
            processed_at=log_record.processed_at.isoformat() if log_record.processed_at else None,
            celery_task_state=None,
            celery_task_info=None
        )
    else:
        # 从Celery获取任务状态
        celery_result = AsyncResult(log_record.task_id, app=celery_app)
        celery_state = celery_result.state
        celery_info = celery_result.info if celery_result.info else {}
        
        task_status = TaskStatusResponse(
            task_id=log_record.task_id,
            log_id=log_id,
            status=log_record.status,
            progress=log_record.progress,
            retry_count=log_record.retry_count,
            error_message=log_record.error_message,
            processing_started_at=log_record.processing_started_at.isoformat() if log_record.processing_started_at else None,
            processed_at=log_record.processed_at.isoformat() if log_record.processed_at else None,
            celery_task_state=celery_state,
            celery_task_info=celery_info
        )
    
    return BaseResponse(
        success=True,
        message="Log task status retrieved successfully",
        data=task_status
    )


@router.get("/list", response_model=BaseResponse)
async def list_tasks(
    status_filter: Optional[LogStatus] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    获取任务列表
    
    Args:
        status_filter: 状态过滤
        limit: 限制数量
        offset: 偏移量
        db: 数据库会话
        
    Returns:
        任务列表
    """
    query = db.query(LogRecord).filter(LogRecord.task_id.isnot(None))
    
    if status_filter:
        query = query.filter(LogRecord.status == status_filter)
    
    # 获取总数
    total = query.count()
    
    # 分页查询
    log_records = query.order_by(LogRecord.created_at.desc()).offset(offset).limit(limit).all()
    
    tasks = []
    for log_record in log_records:
        # 从Celery获取任务状态
        celery_result = AsyncResult(log_record.task_id, app=celery_app)
        celery_state = celery_result.state
        celery_info = celery_result.info if celery_result.info else {}
        
        task_status = TaskStatusResponse(
            task_id=log_record.task_id,
            log_id=log_record.id,
            status=log_record.status,
            progress=log_record.progress,
            retry_count=log_record.retry_count,
            error_message=log_record.error_message,
            processing_started_at=log_record.processing_started_at.isoformat() if log_record.processing_started_at else None,
            processed_at=log_record.processed_at.isoformat() if log_record.processed_at else None,
            celery_task_state=celery_state,
            celery_task_info=celery_info
        )
        tasks.append(task_status)
    
    task_list = TaskListResponse(
        tasks=tasks,
        total=total
    )
    
    return BaseResponse(
        success=True,
        message="Task list retrieved successfully",
        data=task_list
    )


@router.post("/cancel/{task_id}", response_model=BaseResponse)
async def cancel_task(
    task_id: str,
    db: Session = Depends(get_db)
):
    """
    取消任务
    
    Args:
        task_id: Celery任务ID
        db: 数据库会话
        
    Returns:
        取消结果
    """
    # 从数据库获取任务信息
    log_record = db.query(LogRecord).filter(LogRecord.task_id == task_id).first()
    
    if not log_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task with id {task_id} not found"
        )
    
    # 检查任务状态
    if log_record.status in [LogStatus.COMPLETED, LogStatus.FAILED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task in {log_record.status.value} status"
        )
    
    try:
        # 取消Celery任务
        celery_app.control.revoke(task_id, terminate=True)
        
        # 更新数据库状态
        log_record.status = LogStatus.FAILED
        log_record.error_message = "Task cancelled by user"
        db.commit()
        
        return BaseResponse(
            success=True,
            message="Task cancelled successfully",
            data={"task_id": task_id, "status": "cancelled"}
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel task: {str(e)}"
        )


@router.post("/retry/{log_id}", response_model=BaseResponse)
async def retry_task(
    log_id: str,
    db: Session = Depends(get_db)
):
    """
    重试任务
    
    Args:
        log_id: 日志记录ID
        db: 数据库会话
        
    Returns:
        重试结果
    """
    from app.tasks.log_processing import process_protocol_stack_log
    
    log_record = db.query(LogRecord).filter(LogRecord.id == log_id).first()
    
    if not log_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log with id {log_id} not found"
        )
    
    # 检查是否可以重试
    if log_record.status == LogStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task is currently processing"
        )
    
    if log_record.status == LogStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task already completed"
        )
    
    try:
        # 重置状态
        log_record.status = LogStatus.PENDING
        log_record.progress = 0.0
        log_record.error_message = None
        log_record.task_id = None
        log_record.processing_started_at = None
        db.commit()
        
        # 启动新任务
        task_result = process_protocol_stack_log.delay(log_id)
        
        # 更新任务ID
        log_record.task_id = task_result.id
        db.commit()
        
        return BaseResponse(
            success=True,
            message="Task retry started successfully",
            data={"log_id": log_id, "task_id": task_result.id}
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retry task: {str(e)}"
        )