# ============================================================
# 后端 Dockerfile - Python FastAPI + 模型依赖
# 多阶段构建: 减少最终镜像体积
# ============================================================

# ---- 阶段1: 依赖构建 ----
FROM python:3.11-slim AS builder

WORKDIR /build

# 安装系统依赖（编译部分 Python 包需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 国内 pip 镜像源（加速依赖安装）
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --prefix=/install \
    -r requirements.txt

# ---- 阶段2: 运行时 ----
FROM python:3.11-slim AS runtime

WORKDIR /app

# 安装运行时系统依赖
# 注意：Debian Trixie 已移除 libgl1-mesa-glx，改用 libgl1；运行时用 libxrender1 而非 dev 包
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的依赖
COPY --from=builder /install /usr/local

# 复制应用代码
COPY . /app/

# 创建数据目录
RUN mkdir -p /app/data/uploads /app/data/vector_store /app/data/parsed /app/data/figures /models

# 设置 Python 环境
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# 国内 HuggingFace 镜像（可被环境变量覆盖）
ENV HF_ENDPOINT=https://hf-mirror.com

# 健康检查
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=20s \
    CMD curl -f http://localhost:8000/health || exit 1

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
