"""
全局配置管理模块
================
使用 pydantic-settings 从环境变量 / .env 文件读取所有配置项。
所有服务、路由统一通过 get_settings() 读取配置，避免散落的常量。
"""
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用全局配置。字段名与 .env 中的环境变量大小写不敏感映射。"""

    # ---- 模型元信息（供健康检查与日志展示）----
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ===== 应用配置 =====
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    API_PREFIX: str = "/api/v1"

    # ===== 模型配置 =====
    # local: 本地加载权重；api: 走 OpenAI 兼容接口（DashScope）
    MODEL_MODE: str = "api"
    QWEN_MODEL_NAME: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    QWEN_MODEL_PATH: str = "/models/Qwen2.5-VL-7B-Instruct"
    QWEN_API_BASE: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_API_KEY: str = ""
    QWEN_API_MODEL: str = "qwen2.5-vl-7b-instruct"
    # 文本生成模型（用于摘要/实体抽取/综述等纯文本任务，默认与 VL 同源）
    QWEN_TEXT_API_MODEL: str = "qwen-plus"
    # 生成温度
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 2048

    # ===== 视觉能力开关 =====
    # 使用纯文本模型（DeepSeek/LLaMA 等）时设为 false，
    # 跳过图片公式 OCR / 图表识别，仅用 pdfplumber 文本提取 + 正则公式识别。
    VISION_ENABLED: bool = True

    # ===== 公式识别 =====
    # 公式检测基于标号定位（如 (1), (2.3)），默认用文本提取，稳定可靠。
    # FORMULA_VL_ENABLED: 是否额外调用 VL 模型增强识别为 LaTeX。
    #   默认 false（VL 识别公式容易出错，文本提取更稳定）。
    #   设为 true 时，对每个检测到的公式区域尝试 VL 识别，成功则用 VL 结果，失败回退文本提取。
    FORMULA_VL_ENABLED: bool = False
    # 每页最多送 VL 识别的候选公式区域数（成本控制，仅 VL 启用时生效）。
    FORMULA_VL_MAX_PER_PAGE: int = 5

    # ===== 4-bit 量化（仅 local 模式生效）=====
    ENABLE_4BIT_QUANTIZATION: bool = True
    LOAD_IN_4BIT: bool = True
    BNB_4BIT_COMPUTE_DTYPE: str = "float16"
    BNB_4BIT_QUANT_TYPE: str = "nf4"
    BNB_4BIT_USE_NESTED_QUANT: bool = True

    # ===== Embedding (BGE-M3) =====
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    EMBEDDING_MODEL_PATH: str = "/models/bge-m3"
    EMBEDDING_DEVICE: str = "cpu"
    EMBEDDING_BATCH_SIZE: int = 32
    EMBEDDING_DIM: int = 1024  # bge-m3 稠密向量维度

    # ===== 向量存储 =====
    VECTOR_STORE_TYPE: str = "chroma"
    VECTOR_STORE_PATH: str = "/app/data/vector_store"
    VECTOR_COLLECTION_NAME: str = "literature_chunks"
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    # ===== RAG 配置 =====
    RAG_TOP_K: int = 5
    RAG_SUMMARY_TOP_K: int = 3
    RAG_FULLTEXT_TOP_K: int = 8
    RAG_ENABLE_RERANK: bool = True
    RERANK_MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"
    RERANK_TOP_N: int = 5
    RERANK_DEVICE: str = "cpu"

    # ===== Neo4j 配置 =====
    NEO4J_URI: str = "bolt://neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "literature2024"
    NEO4J_DATABASE: str = "neo4j"

    # ===== 文件存储 =====
    UPLOAD_DIR: str = "/app/data/uploads"
    # 从 PDF 中提取的图表图片存放目录，通过 /static 暴露给前端
    FIGURE_DIR: str = "/app/data/figures"
    # 静态文件 URL 前缀（main.py 中挂载 StaticFiles）
    STATIC_URL_PREFIX: str = "/static"
    MAX_UPLOAD_SIZE: int = 52428800  # 50MB
    ALLOWED_EXTENSIONS: str = "pdf,png,jpg,jpeg,tiff"

    # ===== Celery / Redis 异步任务 =====
    REDIS_PASSWORD: str = "literature_redis_2024"
    CELERY_BROKER_URL: str = "redis://:literature_redis_2024@redis:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://:literature_redis_2024@redis:6379/1"

    # ===== CORS =====
    CORS_ORIGINS: str = "http://localhost:5173,http://frontend:80"

    # ===== HuggingFace 镜像 =====
    HF_ENDPOINT: str = "https://hf-mirror.com"
    TRANSFORMERS_OFFLINE: int = 0

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _strip_cors(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins_list(self) -> List[str]:
        """把逗号分隔的 CORS_ORIGINS 拆成列表。"""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_ext_list(self) -> List[str]:
        """允许上传的扩展名列表（小写，不含点）。"""
        return [e.strip().lower().lstrip(".") for e in self.ALLOWED_EXTENSIONS.split(",") if e.strip()]

    @property
    def use_local_model(self) -> bool:
        """是否走本地模型加载。"""
        return self.MODEL_MODE.lower() == "local"


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例。进程内只解析一次环境变量。"""
    # 在导入 transformers/sentence-transformers 之前设置 HF 镜像，
    # 保证国内网络环境下能从 hf-mirror.com 拉模型。
    import os

    settings = Settings()
    if settings.HF_ENDPOINT:
        os.environ.setdefault("HF_ENDPOINT", settings.HF_ENDPOINT)
    os.environ.setdefault("TRANSFORMERS_OFFLINE", str(settings.TRANSFORMERS_OFFLINE))
    return settings
