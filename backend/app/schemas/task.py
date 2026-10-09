"""异步任务状态响应模型。"""
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class TaskStatus(BaseModel):
    """Celery 异步任务状态查询响应。"""

    task_id: str
    status: str = Field(description="PENDING | PROCESSING | SUCCESS | FAILURE")
    progress: int = Field(default=0, ge=0, le=100, description="进度百分比 0-100")
    current_step: str = Field(default="", description="当前步骤名称，如 text_extraction")
    result: Optional[Dict[str, Any]] = Field(default=None, description="任务成功时的解析结果摘要")
    error: Optional[str] = Field(default=None, description="任务失败时的错误信息")


class UploadAcceptedResponse(BaseModel):
    """POST /upload 异步提交后的立即响应。"""

    task_id: str
    document_id: str
    filename: str
    status: str = "parsing"
