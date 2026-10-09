"""综述相关请求/响应模型。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class ReviewGenerateRequest(BaseModel):
    """POST /review/generate 请求体。"""

    document_ids: List[str] = Field(..., min_length=1)
    topic: str = Field(..., description="综述主题")
    sections: List[str] = Field(
        default_factory=lambda: ["background", "methods", "datasets", "challenges", "future"]
    )


class OutlineSection(BaseModel):
    """大纲章节。"""

    section: str
    key_points: List[str] = Field(default_factory=list)


class CoreView(BaseModel):
    """核心观点。"""

    view: str
    supporting_docs: List[str] = Field(default_factory=list)
    evidence: Optional[str] = None


class ResearchGap(BaseModel):
    """研究缺口。"""

    gap: str
    severity: str = Field(default="medium", pattern="^(high|medium|low)$")
    suggested_direction: Optional[str] = None


class EvolutionEvent(BaseModel):
    """发展脉络事件。"""

    year: str
    event: str
    document_id: Optional[str] = None


class ReviewResponse(BaseModel):
    """POST /review/generate 与 GET /review/{id} 响应。"""

    review_id: str
    title: str
    outline: List[OutlineSection] = Field(default_factory=list)
    core_views: List[CoreView] = Field(default_factory=list)
    research_gaps: List[ResearchGap] = Field(default_factory=list)
    evolution_timeline: List[EvolutionEvent] = Field(default_factory=list)
    created_at: Optional[str] = None
