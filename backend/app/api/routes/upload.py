"""文献上传与文档管理路由。"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.core.exceptions import DocumentNotFoundError, FileValidationError
from app.core.logging import logger
from app.schemas.document import (
    BatchDocumentRequest,
    DocumentListResponse,
    DocumentResponse,
    DocumentListItem,
    DocumentTagsUpdateRequest,
)
from app.schemas.graph import GraphBuildResponse, GraphStats
from app.schemas.task import TaskStatus, UploadAcceptedResponse
from app.services.graph_service import graph_service
from app.services.vector_service import vector_service
from app.tasks.parse_task import parse_document_task
from app.utils.file_utils import (
    get_document_index,
    list_documents_index,
    load_parsed_result,
    remove_document_index,
    save_upload_file,
    search_documents as search_documents_index,
    update_document_tags,
    upsert_document_index,
    validate_upload_file,
)
from app.utils.task_utils import get_task_status

router = APIRouter()


@router.post("/upload", response_model=UploadAcceptedResponse)
async def upload_document(
    file: UploadFile = File(...),
    parse_formula: bool = Form(default=True),
    parse_figures: bool = Form(default=True),
    parse_references: bool = Form(default=True),
):
    """上传文献并提交异步解析任务，立即返回 task_id。"""
    content = await file.read()
    filename = file.filename or "unknown"

    # 校验
    try:
        validate_upload_file(filename, len(content))
    except FileValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    # 落盘
    doc_id = save_upload_file(content, filename)
    upsert_document_index(doc_id, filename, title=None, status="parsing")

    # 提交异步解析任务
    task = parse_document_task.delay(
        doc_id=doc_id,
        filename=filename,
        parse_formula=parse_formula,
        parse_figures=parse_figures,
        parse_references=parse_references,
    )
    logger.info("文档 %s 已提交异步解析任务: task_id=%s", doc_id, task.id)

    return UploadAcceptedResponse(
        task_id=task.id,
        document_id=doc_id,
        filename=filename,
        status="parsing",
    )


@router.get("/task/{task_id}", response_model=TaskStatus)
async def get_task_status_endpoint(task_id: str):
    """查询异步解析任务状态。"""
    return get_task_status(task_id)


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents():
    """列出所有已上传文档。"""
    items = list_documents_index()
    return DocumentListResponse(
        documents=[DocumentListItem(**it) for it in items],
        total=len(items),
    )


# ---------- P1-4: 文献管理增强 ----------
# 注意：/documents/search、/documents/batch 这类字面量路由必须注册在
# /documents/{document_id} 之前，否则会被路径参数 {document_id} 抢先匹配。


@router.get("/documents/search", response_model=DocumentListResponse)
async def search_documents_endpoint(
    keyword: Optional[str] = Query(default=None, max_length=100),
    tag: Optional[str] = Query(default=None, max_length=50),
):
    """按关键词（标题/文件名/作者）和标签搜索文档。"""
    items = search_documents_index(keyword=keyword or "", tag=tag)
    return DocumentListResponse(
        documents=[DocumentListItem(**it) for it in items],
        total=len(items),
    )


@router.put("/documents/{document_id}/tags")
async def update_document_tags_endpoint(
    document_id: str, req: DocumentTagsUpdateRequest
):
    """更新文档标签。"""
    if not get_document_index(document_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    update_document_tags(document_id, req.tags)
    logger.info("文档 %s 标签更新为 %s", document_id, req.tags)
    return {"document_id": document_id, "tags": req.tags}


@router.post("/documents/batch/build-graph", response_model=GraphBuildResponse)
async def batch_build_graph(req: BatchDocumentRequest):
    """批量选择文档构建知识图谱。"""
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
        )
        return GraphBuildResponse(
            graph_id=result["graph_id"],
            status=result["status"],
            stats=GraphStats(**result["stats"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"批量建图失败: {exc}")


@router.delete("/documents/batch")
async def batch_delete_documents(req: BatchDocumentRequest):
    """批量删除文档（原始文件 + 解析结果 + 向量索引 + 索引条目）。"""
    deleted: list = []
    failed: list = []
    for doc_id in req.document_ids:
        if not get_document_index(doc_id):
            failed.append({"document_id": doc_id, "reason": "文档不存在"})
            continue
        try:
            vector_service.delete_document(doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("批量删除时清理向量索引失败 %s: %s", doc_id, exc)
        remove_document_index(doc_id)
        deleted.append(doc_id)
    logger.info("批量删除完成: 成功 %d, 失败 %d", len(deleted), len(failed))
    return {"deleted": deleted, "failed": failed, "total": len(deleted)}


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str):
    """获取文档完整解析结果。"""
    result = load_parsed_result(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="文档不存在")
    return DocumentResponse(**result)


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    """删除文档（原始文件 + 解析结果 + 向量索引）。"""
    if not get_document_index(document_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    try:
        vector_service.delete_document(document_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("清理向量索引失败: %s", exc)
    remove_document_index(document_id)
    return {"deleted": True}
