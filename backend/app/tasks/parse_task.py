"""
文献解析异步任务
================
将同步的 parser_service.parse_file 封装为 Celery 任务。
任务执行过程中通过 self.update_state 上报细粒度进度。
任务完成后自动更新文档索引和向量库。
"""
from pathlib import Path
from typing import Any, Dict

from app.core.celery_app import celery_app
from app.core.logging import logger
from app.services.parser_service import parser_service
from app.services.vector_service import vector_service
from app.utils.file_utils import (
    get_upload_path,
    upsert_document_index,
)


@celery_app.task(bind=True, name="parse_document", max_retries=0)
def parse_document_task(
    self,
    doc_id: str,
    filename: str,
    parse_formula: bool = True,
    parse_figures: bool = True,
    parse_references: bool = True,
) -> Dict[str, Any]:
    """
    异步解析文献。

    Args:
        doc_id: 文档 ID（文件已由 upload 路由保存到 UPLOAD_DIR）
        filename: 原始文件名
        parse_formula: 是否解析公式
        parse_figures: 是否解析图表
        parse_references: 是否解析参考文献

    Returns:
        解析结果摘要（document_id, filename, status, metadata, stats）

    Raises:
        各种解析异常会被 Celery 标记为 FAILURE，错误信息存入 result
    """
    # 构造进度回调：通过 Celery 的 update_state 上报
    def on_progress(step: str, progress: int, message: str = "") -> None:
        self.update_state(state="PROCESSING", meta={
            "progress": progress,
            "current_step": step,
            "message": message,
        })
        logger.info("任务 %s 进度: %s - %d%% - %s", self.request.id, step, progress, message)

    # 初始状态
    on_progress("upload_complete", 10, "文件上传完成，开始解析")

    # 查找上传文件
    src_path = get_upload_path(doc_id)
    if src_path is None:
        error_msg = f"找不到上传文件: doc_id={doc_id}"
        logger.error(error_msg)
        upsert_document_index(doc_id, filename, title=None, status="failed")
        raise FileNotFoundError(error_msg)

    try:
        # 执行解析（内部会通过 on_progress 上报各阶段进度）
        result = parser_service.parse_file(
            doc_id=doc_id,
            file_path=src_path,
            filename=filename,
            parse_formula=parse_formula,
            parse_figures=parse_figures,
            parse_references=parse_references,
            on_progress=on_progress,
        )
    except Exception as exc:
        # 解析失败：更新索引状态，记录错误，重新抛出让 Celery 标记 FAILURE
        logger.exception("文档 %s 解析失败", doc_id)
        upsert_document_index(doc_id, filename, title=None, status="failed")
        raise

    # 解析成功：更新文档索引
    title = result.get("metadata", {}).get("title")
    upsert_document_index(doc_id, filename, title=title, status="completed")
    logger.info("文档 %s 索引已更新为 completed", doc_id)

    # 写入向量库（失败不影响任务结果，仅警告）
    try:
        vector_service.index_document(
            doc_id=doc_id,
            filename=filename,
            full_text=result.get("full_text", ""),
            structured_summary=result.get("structured_summary"),
            # 传入结构化文本块，使 chunk 携带真实页码/段落序号/字符偏移（溯源增强）
            text_blocks=result.get("text_blocks"),
        )
        logger.info("文档 %s 向量索引完成", doc_id)
    except Exception as exc:
        logger.warning("文档 %s 向量索引失败（不影响解析结果）: %s", doc_id, exc)

    # 返回摘要（完整结果已落盘到 parsed/{doc_id}.json）
    return {
        "document_id": result.get("document_id", doc_id),
        "filename": result.get("filename", filename),
        "status": "completed",
        "title": title,
        "stats": result.get("stats", {}),
    }
