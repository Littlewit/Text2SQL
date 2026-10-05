"""Celery 应用实例（DEP-01 worker 服务入口）。"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "t2s",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.timezone,
    task_acks_late=True,          # 任务执行完再确认，避免 worker 崩溃丢任务
    worker_prefetch_multiplier=1, # 长任务公平分发
)
