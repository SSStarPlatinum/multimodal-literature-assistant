"""
自定义异常模块
==============
业务层抛出的专用异常，由 main.py 注册的全局异常处理器统一转成 HTTP 响应。
"""
from typing import Any, Optional


class AppException(Exception):
    """业务异常基类。"""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        details: Optional[Any] = None,
    ) -> None:
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code
        self.details = details
        super().__init__(message)


class DocumentNotFoundError(AppException):
    """文档不存在。"""

    status_code = 404
    error_code = "document_not_found"


class GraphNotFoundError(AppException):
    """知识图谱不存在。"""

    status_code = 404
    error_code = "graph_not_found"


class GraphNodeNotFoundError(AppException):
    """知识图谱节点不存在（按 elementId 定位失败）。"""

    status_code = 404
    error_code = "graph_node_not_found"


class ReviewNotFoundError(AppException):
    """综述不存在。"""

    status_code = 404
    error_code = "review_not_found"


class FileValidationError(AppException):
    """上传文件校验失败（类型/大小）。"""

    status_code = 400
    error_code = "file_validation_error"


class ParsingError(AppException):
    """文献解析失败。"""

    status_code = 500
    error_code = "parsing_error"


class ModelInferenceError(AppException):
    """模型推理失败。"""

    status_code = 502
    error_code = "model_inference_error"


class GraphServiceError(AppException):
    """图谱服务（Neo4j）故障。"""

    status_code = 503
    error_code = "graph_service_unavailable"


class VectorStoreError(AppException):
    """向量存储故障。"""

    status_code = 503
    error_code = "vector_store_unavailable"
