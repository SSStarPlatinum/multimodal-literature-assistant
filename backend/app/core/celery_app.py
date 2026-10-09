"""
Celery 应用实例
===============
统一配置 broker / result backend / 序列化方式。
所有异步任务通过 `from app.core.celery_app import celery_app` 引入此实例并注册。
Worker 启动命令: celery -A app.core.celery_app.celery_app worker
"""
from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "literature_parser",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务执行超时（防止卡死），10 分钟
    task_time_limit=600,
    task_soft_time_limit=570,
    # 结果过期时间（1 小时后自动清理）
    result_expires=3600,
    # worker 预取数：每个 worker 进程一次取 1 个任务，避免长任务阻塞
    worker_prefetch_multiplier=1,
    # 自动发现 app.tasks 包下的任务
    imports=["app.tasks.parse_task"],
)
