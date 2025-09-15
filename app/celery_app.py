"""Celery应用配置"""

from celery import Celery
from app.config import settings

# 创建Celery应用实例
celery_app = Celery(
    "log_staging_service",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.log_processing"]
)

# 配置Celery
celery_app.conf.update(
    task_serializer=settings.celery_task_serializer,
    result_serializer=settings.celery_result_serializer,
    accept_content=settings.celery_accept_content,
    timezone=settings.celery_timezone,
    enable_utc=settings.celery_enable_utc,
    task_track_started=True,
    task_time_limit=settings.task_timeout,
    task_soft_time_limit=settings.task_timeout - 60,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_disable_rate_limits=False,
    task_compression='gzip',
    result_compression='gzip',
    task_routes={
        'app.tasks.log_processing.process_protocol_stack_log': {'queue': 'log_processing'},
    },
    task_default_queue='default',
    task_default_exchange='default',
    task_default_exchange_type='direct',
    task_default_routing_key='default',
)

# 配置队列
celery_app.conf.task_routes = {
    'app.tasks.log_processing.*': {'queue': 'log_processing'},
}

if __name__ == '__main__':
    celery_app.start()