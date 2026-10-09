"""
任务状态查询工具
==============
封装 Celery AsyncResult 的状态读取，统一转换为 TaskStatus 响应模型。
处理 Celery 原生状态（PENDING/STARTED/SUCCESS/FAILURE）与自定义 PROCESSING 状态的映射。
"""
from typing import Optional

from celery.result import AsyncResult

from app.core.celery_app import celery_app
from app.schemas.task import TaskStatus


def get_task_status(task_id: str) -> TaskStatus:
    """
    查询 Celery 任务状态，返回统一的 TaskStatus。

    状态映射：
    - PENDING: 任务已提交，尚未被 worker 领取
    - STARTED / RETRY: 映射为 PROCESSING
    - SUCCESS: 任务完成，result 中包含解析结果
    - FAILURE: 任务失败，error 中包含异常信息
    - 任务通过 self.update_state(state="PROCESSING", meta={...}) 上报的自定义状态
      直接读取 meta 中的 progress / current_step
    """
    async_result = AsyncResult(task_id, app=celery_app)
    celery_state = async_result.state

    # 读取任务 meta（自定义进度信息存放在 meta 中）
    meta = async_result.info if isinstance(async_result.info, dict) else {}

    # 状态映射
    if celery_state == "PENDING":
        status = "PENDING"
        progress = 0
        current_step = ""
    elif celery_state in ("STARTED", "RETRY"):
        status = "PROCESSING"
        progress = meta.get("progress", 0)
        current_step = meta.get("current_step", "running")
    elif celery_state == "PROCESSING":
        # 自定义状态：任务执行中，通过 update_state 上报
        status = "PROCESSING"
        progress = meta.get("progress", 0)
        current_step = meta.get("current_step", "running")
    elif celery_state == "SUCCESS":
        status = "SUCCESS"
        progress = 100
        current_step = "completed"
    elif celery_state == "FAILURE":
        status = "FAILURE"
        progress = 0
        current_step = "failed"
    else:
        status = celery_state
        progress = meta.get("progress", 0)
        current_step = meta.get("current_step", "")

    # 提取结果（成功时）
    result = None
    if status == "SUCCESS" and async_result.result is not None:
        if isinstance(async_result.result, dict):
            result = async_result.result
        else:
            result = {"value": str(async_result.result)}

    # 提取错误信息（失败时）
    error = None
    if status == "FAILURE":
        if async_result.info is not None:
            error = str(async_result.info)
        elif meta.get("error"):
            error = meta["error"]
        else:
            error = "任务执行失败"

    return TaskStatus(
        task_id=task_id,
        status=status,
        progress=progress,
        current_step=current_step,
        result=result,
        error=error,
    )
