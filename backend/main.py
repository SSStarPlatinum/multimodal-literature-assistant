"""
FastAPI 应用入口
================
- 注册全部业务路由
- 配置 CORS
- 注册全局异常处理器（AppException -> JSON）
- 提供 /health 健康检查
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.logging import logger
from app.services.graph_service import graph_service
from app.services.model_loader import model_loader
from app.services.vector_service import vector_service
from app.utils.file_utils import ensure_dirs

settings = get_settings()

app = FastAPI(
    title="多模态文献精读与知识图谱助手",
    description="多模态文献解析 / RAG 分层问答 / 知识图谱 / 综述生成",
    version="1.0.0",
)

# ---- CORS ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- 全局异常处理 ----
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """把业务异常转成统一 JSON 错误响应。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底：未捕获异常。"""
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "服务器内部错误"},
    )


# ---- 启动 / 关闭 ----
@app.on_event("startup")
async def on_startup() -> None:
    ensure_dirs()
    logger.info("应用启动完成, env=%s, mode=%s", settings.APP_ENV, settings.MODEL_MODE)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        graph_service.close()
    except Exception:  # noqa: BLE001
        pass


# ---- 路由注册 ----
app.include_router(api_router, prefix=settings.API_PREFIX)

# ---- 静态文件（提取的图表图片）----
# 挂载 /static/figures -> FIGURE_DIR，前端通过 fig.url 访问
_figure_dir = Path(settings.FIGURE_DIR)
_figure_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    f"{settings.STATIC_URL_PREFIX}/figures",
    StaticFiles(directory=str(_figure_dir)),
    name="figures",
)


# ---- 健康检查 ----
@app.get("/health")
async def health():
    """系统健康检查。"""
    try:
        vector_stats = vector_service.stats()
        vector_status = "ready"
    except Exception:  # noqa: BLE001
        vector_status = "unavailable"
    try:
        neo4j_status = graph_service.health()
    except Exception:  # noqa: BLE001
        neo4j_status = "disconnected"
    return {
        "status": "healthy",
        "components": {
            "neo4j": neo4j_status,
            "vector_store": vector_status,
            "model": model_loader.model_label(),
            "embedding": settings.EMBEDDING_MODEL_NAME,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_ENV == "development",
    )
