"""路由聚合：把 upload/qa/graph/review 四个子路由挂到主 router 上。"""
from fastapi import APIRouter

from app.api.routes import graph, qa, review, upload

api_router = APIRouter()
api_router.include_router(upload.router, tags=["upload"])
api_router.include_router(qa.router, tags=["qa"])
api_router.include_router(graph.router, tags=["graph"])
api_router.include_router(review.router, tags=["review"])
