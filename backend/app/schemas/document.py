"""文档相关请求/响应模型。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """文档元数据。"""

    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    abstract: Optional[str] = None
    page_count: int = 0
    parsed_at: Optional[str] = None


class ParsedStats(BaseModel):
    """解析统计信息。"""

    text_blocks: int = 0
    formulas: int = 0
    figures: int = 0
    tables: int = 0
    references: int = 0


class DocumentResponse(BaseModel):
    """POST /upload 与 GET /documents/{id} 的统一响应体。"""

    document_id: str
    filename: str
    status: str = Field(default="completed", description="parsing|completed|failed")
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    stats: ParsedStats = Field(default_factory=ParsedStats)
    # 完整解析结果（GET 详情时填充）
    text_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    formulas: List[Dict[str, Any]] = Field(default_factory=list)
    figures: List[Dict[str, Any]] = Field(default_factory=list)
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    references: List[Dict[str, Any]] = Field(default_factory=list)
    structured_summary: Optional[Dict[str, str]] = Field(
        default=None, description="结构化摘要: purpose/methods/data/conclusion"
    )


class DocumentListItem(BaseModel):
    """文档列表项。"""

    document_id: str
    filename: str
    title: Optional[str] = None
    uploaded_at: Optional[str] = None
    status: str = "completed"
    tags: List[str] = Field(default_factory=list)


class DocumentListResponse(BaseModel):
    """GET /documents 响应。"""

    documents: List[DocumentListItem] = Field(default_factory=list)
    total: int = 0


# ---------- P1-4: 文献管理增强 ----------

class DocumentTagsUpdateRequest(BaseModel):
    """PUT /documents/{document_id}/tags 请求体。"""

    tags: List[str] = Field(default_factory=list, max_length=20)


class DocumentSearchRequest(BaseModel):
    """POST 搜索请求体（本项目搜索走 GET query params，此处保留以便前端复用）。"""

    keyword: Optional[str] = Field(None, max_length=100)
    tag: Optional[str] = Field(None, max_length=50)


class BatchDocumentRequest(BaseModel):
    """批量操作（批量删除 / 批量建图）请求体。"""

    document_ids: List[str] = Field(..., min_length=1)
