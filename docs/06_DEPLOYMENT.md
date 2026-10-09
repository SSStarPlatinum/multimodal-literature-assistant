# 部署指南

## 1. 环境要求

| 组件 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10+ / Linux / macOS | Windows 11 / Ubuntu 22.04 |
| Docker | 20.10+ | 24.0+ |
| Docker Compose | v2.0+ | v2.20+ |
| 内存 | 4GB（api 模式） | 8GB+ |
| 磁盘 | 10GB | 20GB+ |
| GPU | 不需要（api 模式） | NVIDIA（local 模式） |

> 说明：api 模式 4GB 内存即可运行。**首次启动需要额外时间**：后端会自动从 HuggingFace 镜像（hf-mirror.com）下载 BGE-M3 与 bge-reranker-v2-m3 向量模型，共约 2GB，缓存到 `backend_models` 卷（容器内 `/models`），之后启动不再重复下载。

## 2. 快速启动

### 2.1 克隆/进入项目目录

```powershell
cd D:\TEST\multimodal-literature-assistant
```

### 2.2 配置环境变量

```powershell
# 复制模板
copy .env.example .env

# 编辑配置
notepad .env
```

### 2.3 选择模型方案

#### 方案 A：DeepSeek（推荐方案，支持视觉）

```env
MODEL_MODE=api
VISION_ENABLED=true
QWEN_API_BASE=https://api.deepseek.com
QWEN_API_KEY=sk-你的DeepSeek_API_Key
QWEN_API_MODEL=deepseek-flash
QWEN_TEXT_API_MODEL=deepseek-chat
```

获取 API Key：https://platform.deepseek.com/api_keys

说明：
- `QWEN_API_MODEL=deepseek-flash`：视觉模型，用于图片/公式区域识别
- `QWEN_TEXT_API_MODEL=deepseek-chat`：文本模型，用于图谱抽取、问答、综述
- **注意**：`deepseek-v4-pro` 对结构化 JSON 输出会返回空 content，导致图谱抽取 0 节点，**不可用于图谱抽取**，请勿配置为 `QWEN_TEXT_API_MODEL`

#### 方案 B：阿里云 DashScope（备选）

```env
MODEL_MODE=api
VISION_ENABLED=true
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=sk-你的DashScope_API_Key
QWEN_API_MODEL=qwen2.5-vl-7b-instruct
QWEN_TEXT_API_MODEL=qwen-plus
```

#### 方案 C：本地模型（需要 GPU）

```env
MODEL_MODE=local
VISION_ENABLED=true
QWEN_MODEL_PATH=/models/Qwen2.5-VL-7B-Instruct
ENABLE_4BIT_QUANTIZATION=true
LOAD_IN_4BIT=true
```

需要在 docker-compose.yml 中取消本地模型挂载注释：
```yaml
volumes:
  - ./models:/models:ro
```

### 2.4 启动服务

项目采用 **五服务 Docker 架构**：

| 容器名 | 镜像 / 说明 | 端口 |
|--------|-------------|------|
| literature-neo4j | neo4j:5.16-community，知识图谱数据库 | 7474 / 7687 |
| literature-redis | redis:7-alpine，Celery broker（带密码，不暴露宿主机端口） | 无（仅内部网络） |
| literature-celery-worker | 复用 backend 同一镜像，异步解析任务消费者（6 级进度上报） | 无 |
| literature-backend | FastAPI 后端，代码卷挂载 `./backend:/app` | 8000 |
| literature-frontend | Vue3 + Nginx | 5173 → 80 |

**推荐使用一键脚本 `start.ps1` 启动**（详见第 6 节）。它会先启动 Neo4j 和 Redis 并等待 healthy，再启动其余服务，避免后端因依赖未就绪而反复重启：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

也可以手动启动：

```powershell
# 构建并启动（首次需要 5-10 分钟下载依赖，另需下载约 2GB 向量模型）
docker-compose up -d --build

# 查看服务状态
docker-compose ps
```

### 2.5 访问

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端 | http://localhost:5173 | 主界面 |
| API 文档 | http://localhost:8000/docs | Swagger UI |
| Neo4j 控制台 | http://localhost:7474 | 图数据库浏览器 |

Neo4j 登录：`neo4j` / `literature2024`

## 3. 服务管理

### 3.1 常用命令

```powershell
# 启动
docker-compose up -d

# 停止
docker-compose down

# 重启单个服务
docker-compose restart backend

# 重新构建单个服务
docker-compose build backend
docker-compose up -d backend

# 查看日志
docker-compose logs -f backend
docker logs literature-backend --tail 50

# 进入容器
docker exec -it literature-backend bash
docker exec -it literature-neo4j cypher-shell -u neo4j -p literature2024
```

### 3.2 代码修改后如何生效

**后端代码（Python，`./backend` 目录）**：backend 和 celery-worker 都挂载了代码卷 `./backend:/app`，修改代码后**无需重新构建镜像**，重启即可生效：

```powershell
docker-compose restart backend celery-worker
```

**前端代码（Vue，`./frontend/src`）**：前端构建产物在镜像内，修改后需要重新构建：

```powershell
docker-compose build frontend
docker-compose up -d frontend
```

**Nginx 配置**：frontend 的 build context 是 `./frontend`，容器内实际使用的是 `frontend/nginx.conf`。修改配置时必须：
1. 保持 `frontend/nginx.conf` 与 `docker/nginx.conf` 同步
2. 重新构建前端镜像

```powershell
Copy-Item docker\nginx.conf frontend\nginx.conf -Force
docker-compose build frontend
docker-compose up -d frontend
```

### 3.3 健康检查

```powershell
# 后端健康检查
curl http://localhost:8000/health

# 容器健康状态
docker inspect --format='{{.State.Health.Status}}' literature-backend
docker inspect --format='{{.State.Health.Status}}' literature-neo4j
```

Neo4j 健康检查配置（neo4j:5.16-community 镜像中**没有 curl，只有 wget**）：

```yaml
healthcheck:
  test: ["CMD-SHELL", "wget -q -O /dev/null http://localhost:7474 || exit 1"]
  interval: 15s
  timeout: 10s
  retries: 15
  start_period: 90s   # 首次启动需初始化数据库、加载 apoc 插件
```

## 4. 数据管理

### 4.1 数据卷

| 卷名 | 内容 | 备份方式 |
|------|------|----------|
| neo4j_data | 知识图谱数据 | `docker run --rm -v neo4j_data:/data -v ${PWD}:/backup alpine tar czf /backup/neo4j.tar.gz /data` |
| neo4j_logs | Neo4j 日志 | 同上 |
| backend_uploads | 上传的原始文件 | 同上 |
| backend_vector | ChromaDB 向量索引 | 同上 |
| backend_parsed | 解析结果 JSON | 同上 |
| backend_figures | 提取的图表图片（公式原图保存为 200dpi PNG） | 同上 |
| backend_models | BGE-M3 / bge-reranker-v2-m3 模型缓存（容器内 `/models`，约 2GB，丢失后自动重新下载） | 同上 |
| redis_data | Redis 持久化数据（Celery 任务状态） | 同上 |

### 4.2 完全重置（清除所有数据）

```powershell
docker-compose down -v
docker-compose up -d --build
```

**警告**：这会删除所有上传的文献、解析结果、向量索引和知识图谱。

### 4.3 仅清除知识图谱

```powershell
docker exec literature-neo4j cypher-shell -u neo4j -p literature2024 "MATCH (n) DETACH DELETE n"
```

## 5. 国内网络优化

项目已内置国内镜像源配置：

| 组件 | 镜像源 | 配置位置 |
|------|--------|----------|
| pip | 清华镜像 | backend.Dockerfile |
| npm | 淘宝镜像 | frontend.Dockerfile |
| HuggingFace | hf-mirror.com | .env HF_ENDPOINT |

**向量模型自动下载**：后端启动时如果本地 `/models`（即 `backend_models` 卷）不存在 BGE-M3 或 bge-reranker-v2-m3，会自动从 `https://hf-mirror.com` 下载。首次启动约需下载 2GB，请耐心等待；下载完成后缓存到卷中，后续启动不再重复下载。如遇下载失败，检查 `HF_ENDPOINT=https://hf-mirror.com` 是否配置、`backend_models` 卷是否正常挂载。

如需自定义，覆盖对应环境变量即可。

## 6. Windows 一键启动脚本

项目根目录提供 `start.ps1`（英文注释），推荐作为日常启动方式：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

> 如果直接 `.\start.ps1` 提示执行策略限制，使用上面的 `powershell -ExecutionPolicy Bypass -File` 命令绕过即可。

脚本流程：
1. **检查 `.env`**：不存在则从 `.env.example` 复制，并提示填写 API Key 后退出
2. **检查 Docker**：确认 Docker Desktop 正在运行
3. **构建镜像**：`docker-compose build`（首次约 5-15 分钟）
4. **先启动基础服务**：`docker-compose up -d neo4j redis`
5. **等待 Neo4j healthy**：轮询健康状态，最多等待 180 秒（首次初始化较慢）
6. **启动全部服务**：`docker-compose up -d` 启动 backend、celery-worker、frontend

这种"先启依赖、等待 healthy 再启应用"的顺序，可以避免后端因 Neo4j / Redis 未就绪而反复重启。

## 7. 生产部署建议

1. **反向代理**：在 Nginx 前加一层负载均衡，配置 HTTPS
2. **日志收集**：将 Docker 日志接入 ELK / Loki
3. **监控告警**：Prometheus + Grafana 监控容器资源和 API 延迟
4. **数据备份**：定时备份 neo4j_data 和 backend_uploads 卷
5. **API 限流**：Nginx 层配置 rate limiting，防止 LLM API 滥用
6. **环境隔离**：开发/测试/生产使用不同的 .env 和数据卷
