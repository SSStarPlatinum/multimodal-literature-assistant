"""知识图谱路由。"""
from fastapi import APIRouter, HTTPException, Query

from app.core.exceptions import (
    GraphNodeNotFoundError,
    GraphNotFoundError,
    GraphServiceError,
)
from app.schemas.graph import (
    GraphBuildRequest,
    GraphBuildResponse,
    GraphEdgeCreateRequest,
    GraphEdgeOpResponse,
    GraphListResponse,
    GraphListItem,
    GraphNodeCreateRequest,
    GraphNodeOpResponse,
    GraphNodeUpdateRequest,
    GraphResponse,
    GraphStats,
)
from app.services.graph_service import graph_service
from app.utils.file_utils import get_document_index, load_parsed_result

router = APIRouter()


@router.post("/graph/build", response_model=GraphBuildResponse)
async def build_graph(req: GraphBuildRequest):
    """对给定文献集合构建知识图谱。"""
    parsed_docs = {}
    for doc_id in req.document_ids:
        if not get_document_index(doc_id):
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
        doc = load_parsed_result(doc_id)
        if doc:
            parsed_docs[doc_id] = doc
    try:
        result = graph_service.build_graph(
            document_ids=req.document_ids,
            parsed_docs=parsed_docs,
            entity_types=req.entity_types,
        )
        return GraphBuildResponse(
            graph_id=result["graph_id"],
            status=result["status"],
            stats=GraphStats(**result["stats"]),
        )
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"图谱构建失败: {exc}")


@router.get("/graph/list", response_model=GraphListResponse)
async def list_graphs():
    """列出所有图谱。"""
    try:
        items = graph_service.list_graphs()
        return GraphListResponse(
            graphs=[GraphListItem(**it) for it in items]
        )
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/graph/{graph_id}", response_model=GraphResponse)
async def get_graph(
    graph_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    node_type: str = Query(default=None),
):
    """获取图谱 ECharts 数据。"""
    try:
        return graph_service.get_graph(graph_id, limit=limit, node_type=node_type)
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.delete("/graph/{graph_id}")
async def delete_graph(graph_id: str):
    """删除图谱。"""
    try:
        graph_service.delete_graph(graph_id)
        return {"deleted": True}
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


# ---------- P1-3: 图谱人工校对 ----------

@router.put("/graph/{graph_id}/node/{node_id}", response_model=GraphNodeOpResponse)
async def update_graph_node(graph_id: str, node_id: str, req: GraphNodeUpdateRequest):
    """修改节点属性（名称/描述/类型），类型变更会同步切换 Label。"""
    try:
        return graph_service.update_node(
            graph_id,
            node_id,
            name=req.name,
            description=req.description,
            type=req.type,
        )
    except (GraphNotFoundError, GraphNodeNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"更新节点失败: {exc}")


@router.delete("/graph/{graph_id}/node/{node_id}")
async def delete_graph_node(graph_id: str, node_id: str):
    """删除节点（DETACH DELETE，连带删除其全部关系）。"""
    try:
        graph_service.delete_node(graph_id, node_id)
        return {"deleted": True, "id": node_id}
    except (GraphNotFoundError, GraphNodeNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"删除节点失败: {exc}")


@router.post("/graph/{graph_id}/node", response_model=GraphNodeOpResponse)
async def create_graph_node(graph_id: str, req: GraphNodeCreateRequest):
    """在图谱下手工新增一个实体节点。"""
    try:
        return graph_service.create_node(
            graph_id,
            name=req.name,
            description=req.description,
            type=req.type,
        )
    except GraphNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"新增节点失败: {exc}")


@router.post("/graph/{graph_id}/edge", response_model=GraphEdgeOpResponse)
async def create_graph_edge(graph_id: str, req: GraphEdgeCreateRequest):
    """在两个已存在节点间手工新增关系（用 elementId 定位两端）。"""
    try:
        return graph_service.create_edge(
            graph_id,
            source_eid=req.source,
            target_eid=req.target,
            relation=req.relation,
        )
    except (GraphNotFoundError, GraphNodeNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"新增关系失败: {exc}")


@router.get("/graph/{graph_id}/logs")
async def get_graph_logs(
    graph_id: str,
    limit: int = Query(default=50, ge=1, le=500),
):
    """查看图谱人工校对操作日志（默认最近 50 条，新的在前）。"""
    try:
        logs = graph_service.get_operation_logs(graph_id, limit=limit)
        return {"graph_id": graph_id, "total": len(logs), "logs": logs}
    except GraphServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
