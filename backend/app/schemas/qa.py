"""问答相关请求/响应模型。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class QARequest(BaseModel):
    """POST /qa/ask 请求体。"""

    question: str = Field(..., min_length=1, description="用户问题")
    document_ids: List[str] = Field(
        default_factory=list, description="限定检索的文献范围；为空则全库检索"
    )
    mode: str = Field(default="hybrid", pattern="^(summary|fulltext|hybrid)$")
    top_k: int = Field(default=5, ge=1, le=50)
    include_citations: bool = True


class SourceItem(BaseModel):
    """单条引用溯源。"""

    document_id: str
    filename: str
    chunk_id: str
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = Field(
        default=None, description="chunk 来源段落序号（全文块切分）"
    )
    char_offset: Optional[int] = Field(
        default=None, description="chunk 在全文中的起始字符偏移"
    )
    score: float = 0.0
    retrieval_layer: str = Field(default="fulltext", description="summary|fulltext")


class ChunkDetailResponse(BaseModel):
    """GET /document/{doc_id}/chunk/{chunk_id} 响应：单个 chunk 详情。"""

    document_id: str
    chunk_id: str
    text: str
    page: Optional[int] = None
    paragraph_index: Optional[int] = None
    char_offset: Optional[int] = None
    filename: str = ""


class RetrievalInfo(BaseModel):
    """检索过程信息。"""

    mode: str
    summary_hits: int = 0
    fulltext_hits: int = 0
    reranked: bool = False
    latency_ms: int = 0


class QAResponse(BaseModel):
    """POST /qa/ask 响应。"""

    answer: str
    sources: List[SourceItem] = Field(default_factory=list)
    retrieval_info: RetrievalInfo


class CompareRequest(BaseModel):
    """POST /qa/compare 请求体。"""

    document_ids: List[str] = Field(..., min_length=2)
    dimension: str = Field(
        default="method", pattern="^(method|dataset|metric|conclusion)$"
    )


class CompareItem(BaseModel):
    """单篇文献在某维度下的对比内容。"""

    document_id: str
    title: Optional[str] = None
    content: str


class ComparisonResult(BaseModel):
    """对比结果主体。"""

    dimension: str
    items: List[CompareItem] = Field(default_factory=list)
    differences: List[str] = Field(default_factory=list)
    similarities: List[str] = Field(default_factory=list)


class CompareResponse(BaseModel):
    """POST /qa/compare 响应。"""

    comparison: ComparisonResult
