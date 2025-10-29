"""
定期清理任务
用于清理临时文件和过期数据
"""

import logging
from app.celery_app import celery_app
from app.utils.temp_directory_cleaner import temp_directory_cleaner

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name='app.tasks.cleanup_tasks.cleanup_temp_directories')
def cleanup_temp_directories(self, processing_max_age: int = 24, extracted_max_age: int = 48):
    """
    清理临时目录的定时任务
    
    Args:
        processing_max_age: 临时处理目录最大保留时间（小时）
        extracted_max_age: 解压文件最大保留时间（小时）
    
    Returns:
        dict: 清理统计信息
    """
    try:
        logger.info(
            f"开始定时清理临时目录: "
            f"processing_max_age={processing_max_age}h, "
            f"extracted_max_age={extracted_max_age}h"
        )
        
        # 执行清理
        stats = temp_directory_cleaner.cleanup_all(
            processing_max_age=processing_max_age,
            extracted_max_age=extracted_max_age
        )
        
        logger.info(
            f"定时清理完成: "
            f"删除 {stats['total_deleted']} 个目录/文件, "
            f"释放空间 {temp_directory_cleaner._format_size(stats['total_freed_space_bytes'])}, "
            f"失败 {stats['total_failed']} 个"
        )
        
        return {
            "status": "success",
            "stats": stats
        }
        
    except Exception as e:
        error_msg = f"定时清理任务失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "failed",
            "error": error_msg
        }

