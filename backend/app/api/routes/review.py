"""综述生成路由。"""
from fastapi import APIRouter, HTTPException, Query, Response

from app.core.exceptions import ReviewNotFoundError
from app.schemas.review import ReviewGenerateRequest, ReviewResponse
from app.services.parser_service import parser_service
from app.services.review_service import review_service
from app.utils.file_utils import get_document_index, load_parsed_result

router = APIRouter()


@router.post("/review/generate", response_model=ReviewResponse)
async def generate_review(req: ReviewGenerateRequest):
    """生成综述。"""
    parsed_docs = {}
    for doc_id in req.document_ids:
        if not get_document_index(doc_id):
            raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
        doc = load_parsed_result(doc_id)
        if doc:
            parsed_docs[doc_id] = doc
    try:
        return review_service.generate_review(
            document_ids=req.document_ids,
            topic=req.topic,
            sections=req.sections,
            parsed_docs=parsed_docs,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"综述生成失败: {exc}")


@router.get("/review/{review_id}", response_model=ReviewResponse)
async def get_review(review_id: str):
    """获取已生成的综述。"""
    try:
        return review_service.get_review(review_id)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)


@router.get("/review/{review_id}/export")
async def export_review(
    review_id: str,
    format: str = Query(default="md", pattern="^(md|docx)$"),
):
    """导出综述为 Markdown 或 Word(docx) 文件下载。"""
    try:
        content, filename = review_service.export_review(review_id, format)
    except ReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        # 例如未安装 python-docx
        raise HTTPException(status_code=500, detail=str(exc))

    media_type = (
        "text/markdown"
        if format == "md"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    # filename 已经过 safe_filename 处理（ASCII），可安全放入 Content-Disposition
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=content, media_type=media_type, headers=headers)
