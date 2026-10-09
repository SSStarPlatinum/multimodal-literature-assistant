"""RAG 问答与文献对比路由。"""
from fastapi import APIRouter, HTTPException

from app.schemas.qa import (
    ChunkDetailResponse,
    CompareRequest,
    CompareResponse,
    QARequest,
    QAResponse,
)
from app.services.parser_service import parser_service  # noqa: F401  (保留既有导入)
from app.services.rag_service import rag_service
from app.services.vector_service import vector_service
from app.utils.file_utils import get_document_index, load_parsed_result  # noqa: F401

router = APIRouter()


@router.post("/qa/ask", response_model=QAResponse)
async def ask(req: QARequest):
    """分层 RAG 问答。"""
    try:
        return rag_service.ask(
            question=req.question,
            document_ids=req.document_ids,
            mode=req.mode,
            top_k=req.top_k,
            include_citations=req.include_citations,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"问答失败: {exc}")


@router.post("/qa/compare", response_model=CompareResponse)
async def compare(req: CompareRequest):
    """按维度对比多篇文献。"""
    titles = {}
    for doc_id in req.document_ids:
        idx = get_document_index(doc_id)
        if not idx:
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
        titles[doc_id] = idx.get("title") or idx.get("filename", "")
    try:
        return rag_service.compare(
            document_ids=req.document_ids, dimension=req.dimension, titles=titles
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"对比失败: {exc}")


@router.get(
    "/document/{doc_id}/chunk/{chunk_id}",
    response_model=ChunkDetailResponse,
)
async def get_chunk_detail(doc_id: str, chunk_id: str):
    """查询单个 chunk 的详情（原文 + 页码 + 段落序号 + 字符偏移）。

    供前端「引用溯源」点击后定位原文使用。
    向量库中 chunk 的主键为 ``{doc_id}_{chunk_id}``，不存在时返回 404。
    """
    chunk = vector_service.get_chunk_by_id(doc_id, chunk_id)
    if not chunk:
        raise HTTPException(
            status_code=404,
            detail=f"chunk 不存在: doc_id={doc_id}, chunk_id={chunk_id}",
        )
    return chunk
