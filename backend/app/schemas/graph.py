"""知识图谱相关请求/响应模型。"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

class GraphBuildRequest(BaseModel):
    """POST /graph/build 请求体。"""

    document_ids: List[str] = Field(..., min_length=1)
    entity_types: List[str] = Field(
        default_factory=lambda: ["concept", "algorithm", "dataset", "metric", "conclusion"]
    )
    relation_types: List[str] = Field(
        default_factory=lambda: ["uses", "compares", "improves", "evaluates_on", "achieves"]
    )


class GraphStats(BaseModel):
    """图谱统计。"""

    nodes: int = 0
    relationships: int = 0


class GraphBuildResponse(BaseModel):
    """POST /graph/build 响应。"""

    graph_id: str
    status: str = Field(default="building", description="building|completed")
    stats: GraphStats = Field(default_factory=GraphStats)


class GraphNode(BaseModel):
    """ECharts 兼容节点。"""

    id: str
    label: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphLink(BaseModel):
    """ECharts 兼容边。"""

    source: str
    target: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    """GET /graph/{graph_id} 响应。"""

    graph_id: str
    nodes: List[GraphNode] = Field(default_factory=list)
    links: List[GraphLink] = Field(default_factory=list)
    stats: GraphStats = Field(default_factory=GraphStats)


class GraphListItem(BaseModel):
    """图谱列表项。"""

    graph_id: str
    name: Optional[str] = None
    created_at: Optional[str] = None
    node_count: int = 0


class GraphListResponse(BaseModel):
    """GET /graph/list 响应。"""

    graphs: List[GraphListItem] = Field(default_factory=list)


class GraphSummaryResponse(BaseModel):
    """构建后/删除等轻量响应。"""

    graph_id: str
    name: Optional[str] = None
    created_at: Optional[str] = None
    node_count: int = 0


# ---------- P1-3: 图谱人工校对 ----------

# 节点类型白名单（与 service 层 NODE_TYPE_TO_LABEL 保持一致）
_NODE_TYPE_PATTERN = "^(concept|algorithm|dataset|metric|conclusion)$"
# 关系类型白名单（小写，与 service 层 REL_TYPE_TO_REL 键保持一致）
_REL_TYPE_PATTERN = "^(uses|improves|evaluates_on|achieves|compares_with|proposed_by)$"


class GraphNodeUpdateRequest(BaseModel):
    """PUT /graph/{graph_id}/node/{node_id} 请求体。

    所有字段均可选：只传需要修改的字段。传 type 时会同步切换节点 Label。
    """

    name: Optional[str] = Field(None, description="节点名称")
    description: Optional[str] = Field(None, description="节点描述")
    type: Optional[str] = Field(None, pattern=_NODE_TYPE_PATTERN)


class GraphNodeCreateRequest(BaseModel):
    """POST /graph/{graph_id}/node 请求体。"""

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    type: str = Field(..., pattern=_NODE_TYPE_PATTERN)


class GraphEdgeCreateRequest(BaseModel):
    """POST /graph/{graph_id}/edge 请求体。"""

    source: str = Field(..., description="源节点 elementId")
    target: str = Field(..., description="目标节点 elementId")
    relation: str = Field(..., pattern=_REL_TYPE_PATTERN)


class GraphOperationLog(BaseModel):
    """操作日志条目（持久化到 data/graph_logs/{graph_id}.jsonl）。"""

    operation: str  # update_node|delete_node|create_node|create_edge
    target_id: str
    timestamp: str
    details: Dict[str, Any] = Field(default_factory=dict)


class GraphNodeOpResponse(BaseModel):
    """节点新增/修改后的返回体。"""

    id: str = Field(..., description="节点 elementId")
    name: str
    type: str
    description: str = ""


class GraphEdgeOpResponse(BaseModel):
    """关系新增后的返回体。"""

    source: str
    target: str
    relation: str
