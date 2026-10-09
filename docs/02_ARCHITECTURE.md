# 系统架构

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ 文献上传  │ │ 深度问答  │ │ 知识图谱  │ │ 综述生成  │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       └────────────┴────────────┴────────────┘                  │
│                    │ Vue3 + ECharts + KaTeX                     │
└────────────────────┼────────────────────────────────────────────┘
                     │ HTTP
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│        Nginx (literature-frontend, 端口 5173->80)               │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐    │
│  │ /api/       │  │ /static/    │  │ / (SPA + 静态资源)    │    │
│  │ 代理到backend│  │ 代理到backend│  │ 前端 dist 目录        │    │
│  └─────────────┘  └─────────────┘  └──────────────────────┘    │
└─────────┬──────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│        FastAPI 后端 (literature-backend, 端口 8000)             │
│                                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ /upload  │ │   /qa    │ │  /graph  │ │ /review  │           │
│  │  路由    │ │  路由    │ │  路由    │ │  路由    │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │            │            │            │                  │
│  ┌────▼────────────▼────────────▼────────────▼─────┐            │
│  │              服务层 (Services)                   │            │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐  │            │
│  │  │ParserService│ │ RAGService │ │GraphService│  │            │
│  │  │ (文献解析)  │ │ (分层检索) │ │ (图谱构建) │  │            │
│  │  └────────────┘ └────────────┘ └────────────┘  │            │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐  │            │
│  │  │VectorService│ │ReviewService│ │ModelLoader │  │            │
│  │  │ (向量存储)  │ │ (综述生成) │ │ (模型管理) │  │            │
│  │  └────────────┘ └────────────┘ └────────────┘  │            │
│  └─────────────────────────────────────────────────┘            │
│   上传接口仅落盘并入队 Celery 任务，立即返回 task_id             │
└───────┬─────────────────────────────────────────────────────────┘
        │ Celery 任务 (.delay)
        ▼
┌───────────────────────┐   任务   ┌─────────────────────────────────┐
│  Redis (literature-    │◄────────►│ Celery Worker (literature-     │
│  redis, 不暴露宿主机)  │  结果回写 │ celery-worker, 复用backend镜像) │
│  broker: db0          │          │  消费解析任务，调用 ParserService │
│  result backend: db1  │          │  6 级进度上报写回 Redis         │
└───────────────────────┘          └───────────────┬─────────────────┘
                                                     │
        ┌────────────────────────────────────────────┼───────────────┐
        ▼                ▼                          ▼               ▼
  ┌───────────┐   ┌───────────┐              ┌───────────┐   ┌────────────┐
  │ PyMuPDF   │   │ ChromaDB  │              │  Neo4j    │   │  LLM API   │
  │ (fitz文本/│   │ (向量库)  │              │ 5.16-     │   │ DeepSeek    │
  │  图片)    │   │ summary + │              │ community │   │ flash(视觉) │
  │           │   │ fulltext  │              │ 7474/7687 │   │ chat(文本)  │
  └───────────┘   └───────────┘              └───────────┘   └────────────┘
```

## 2. 服务架构

### 2.1 五服务编排

| 服务 | 镜像 | 端口 | 职责 |
|------|------|------|------|
| frontend | nginx:alpine + 构建产物（build context `./frontend`，`nginx.conf` 在 `frontend/` 目录） | 5173->80 | 托管前端静态资源，反向代理 /api/ 和 /static/ 到后端 |
| backend | python:3.11-slim + FastAPI（镜像由 `docker/backend.Dockerfile` 构建，代码卷挂载 `./backend:/app`） | 8000 | 业务逻辑、LLM 调用、向量检索、图谱操作；上传接口落盘并入队 Celery 任务 |
| celery-worker | 复用 backend 同一镜像（`celery worker` 命令启动，`--concurrency=2`），同样挂载 `./backend:/app` | 无 | 异步解析任务消费者，执行文献解析并上报 6 级进度 |
| redis | redis:7-alpine（`--requirepass` 带密码，appendonly 持久化） | 不暴露宿主机 | Celery broker（db0）+ 结果后端（db1） |
| neo4j | neo4j:5.16-community（含 apoc 插件） | 7474(HTTP), 7687(Bolt) | 知识图谱存储；镜像内无 curl，健康检查用 wget，`start_period=90s` |

> 代码卷挂载 `./backend:/app` 使 backend 与 celery-worker 共享同一份本地代码，修改代码后 `docker-compose restart` 即生效，无需重新构建镜像。前端为静态产物，修改后需 `docker-compose build frontend && docker-compose up -d frontend` 重新构建。

### 2.2 数据卷

| 卷名 | 挂载路径 | 用途 |
|------|----------|------|
| neo4j_data | /data | Neo4j 数据持久化 |
| neo4j_logs | /logs | Neo4j 日志 |
| backend_uploads | /app/data/uploads | 用户上传的原始文件 |
| backend_vector | /app/data/vector_store | ChromaDB 向量索引 |
| backend_parsed | /app/data/parsed | 解析结果 JSON |
| backend_figures | /app/data/figures | 从 PDF 提取的图表图片与公式原图 |
| backend_models | /models | BGE-M3 / bge-reranker-v2-m3 模型缓存（backend 与 celery-worker 共享） |
| redis_data | /data | Redis AOF 持久化 |

### 2.3 网络

- 所有服务连接到 `literature-net` bridge 网络
- 服务间通过服务名通信：backend 访问 `bolt://neo4j:7687`，frontend 代理到 `http://backend:8000`，backend 与 celery-worker 通过 `redis:6379` 收发 Celery 任务
- redis 不映射宿主机端口，仅在内部网络供 backend / celery-worker 访问
- 启动脚本 `start.ps1`：英文注释，先启动 neo4j + redis 并等待 healthy（最多 180 秒），再启动其余服务

## 3. 请求流转

### 3.1 文献上传与解析（异步）

```
用户上传 PDF
  → frontend nginx /api/ 代理
  → backend POST /api/v1/upload
  → 校验并落盘到 uploads 卷，提交 Celery 任务
  → 立即返回 task_id（status=parsing），不阻塞等待解析
  → 前端轮询 GET /api/v1/task/{task_id} 查询进度与状态
  → Celery Worker 消费任务，调用 ParserService.parse_file()
    ├── PyMuPDF(fitz) page.get_text("blocks") 提取文本块
    │     （双栏排序：左栏按 y 排序后接右栏；过滤页眉/页码短行）
    ├── 公式识别：标号行检测 → 栏位判断 → 区域裁剪 → 文本过滤
    │     每个公式区域渲染 200dpi PNG 存入 figures 卷（条目含 image_url）
    ├── fitz doc.extract_image(xref) 提取嵌入图片（存入 figures 卷）
    ├── pdfplumber 提取表格（备选；IEEE 双栏易丢空格，主引擎仍为 fitz）
    ├── 参考文献三级降级匹配定位 References 区段
    ├── LLM 生成结构化摘要（purpose/methods/data/conclusion）
    └── 保存解析结果 JSON 到 parsed 卷
  → 6 级进度上报（经 update_state 写回 Redis result backend）
    upload_complete 10% → text_extraction 30% → formula_recognition 50%
    → figure_extraction 70% → references 85% → summary_generation 100%
  → VectorService.ingest()（在 Worker 内完成向量化）
    ├── 摘要块 -> summary 集合（每篇 1 条）
    └── 全文 block chunk -> fulltext 集合（每篇约 143 chunks）
  → 任务完成（status=completed），前端停止轮询并展示结果
```

### 3.2 RAG 问答

```
用户提问
  → backend POST /api/v1/qa/ask
  → RAGService.ask()
    ├── 第一层：摘要检索（top_k=3）
    │   └── 确定相关文献集合
    ├── 第二层：全文细查（仅在相关文献内，top_k=8）
    │   └── hybrid 模式取摘要命中交集
    ├── 第三层：bge-reranker 重排序（top_n=5）
    ├── LLM 生成回答（带引用标注 [n]）
    └── 返回回答 + 来源片段
```

### 3.3 知识图谱构建

```
用户选择文献 → 构建图谱
  → backend POST /api/v1/graph/build
  → GraphService.build_graph()
    ├── 创建 Graph 根节点
    └── 对每篇文献：
        ├── LLM 抽取实体/关系（JSON 格式，带重试）
        ├── JSON 鲁棒解析（多格式兼容）
        ├── 节点类型映射（英文+中文容错）
        ├── Cypher MERGE 写入节点
        ├── Cypher MERGE 写入关系
        └── 建立 PROPOSED_BY 关系到 Document 节点
  → 返回 graph_id + 统计
```

### 3.4 图表图片访问

```
前端展示图表
  → <img src="/static/figures/{doc_id}_{idx}.png">
  → frontend nginx /static/ 代理
  → backend FastAPI StaticFiles
  → 读取 backend_figures 卷中的图片文件
  → 返回图片二进制
```

## 4. 模型架构

### 4.1 模型双模式

| 模式 | 说明 | 硬件要求 | 适用场景 |
|------|------|----------|----------|
| api | 调用 OpenAI 兼容 API（DeepSeek / DashScope） | 无 GPU 要求 | 快速上手、生产部署 |
| local | 本地 transformers 加载 Qwen2.5-VL | GPU 14GB（无量化）/ 4GB（4-bit） | 数据隐私、离线环境 |

### 4.2 模型分工

| 任务 | 模型 | 说明 |
|------|------|------|
| 视觉理解（可选） | deepseek-flash / qwen2.5-vl-7b | 视觉模型，VISION_ENABLED=true 时启用；当前公式识别默认 `FORMULA_VL_ENABLED=false`，不依赖 VL |
| 文本生成（图谱抽取/摘要/综述/RAG 问答） | deepseek-chat / qwen-plus | 纯文本推理。**注意：deepseek-v4-pro 对结构化 JSON 输出会返回空 content，不可用于图谱抽取** |
| 向量嵌入 | BGE-M3 | 本地加载，1024 维；`/models/bge-m3` 缺失时经 hf-mirror.com 自动下载并缓存到 backend_models 卷 |
| 重排序 | bge-reranker-v2-m3 | 本地 CrossEncoder；同样经 hf-mirror 自动下载 |

### 4.3 4-bit 量化（local 模式）

```python
BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4",           # Normalized Float 4-bit
    bnb_4bit_use_double_quant=True,      # 嵌套量化（二次量化量化常数）
)
```

效果：7B 模型显存占用从 ~14GB 降至 ~4GB，推理精度损失可控。

## 5. 配置管理

所有配置通过 `pydantic-settings` 从环境变量 / `.env` 文件读取，统一在 `app/core/config.py` 管理。关键配置项：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| MODEL_MODE | api | api / local |
| VISION_ENABLED | true | 是否启用视觉模型 |
| QWEN_API_BASE | https://api.deepseek.com | API 端点（当前接 DeepSeek，OpenAI 兼容） |
| QWEN_API_MODEL | deepseek-flash | 视觉模型名 |
| QWEN_TEXT_API_MODEL | deepseek-chat | 文本模型名（deepseek-v4-pro 对结构化 JSON 返回空 content，不可用于图谱抽取） |
| FORMULA_VL_ENABLED | false | 公式识别是否走 VL（默认关闭：基于标号定位+文本提取更稳定、零成本） |
| ENABLE_4BIT_QUANTIZATION | true | local 模式下是否 4-bit 量化 |
| EMBEDDING_DEVICE | cpu | 嵌入模型设备（cpu/cuda） |
| NEO4J_URI | bolt://neo4j:7687 | Neo4j 连接 |
| CELERY_BROKER_URL | redis://...@redis:6379/0 | Celery broker（db0） |
| CELERY_RESULT_BACKEND | redis://...@redis:6379/1 | Celery 任务结果/进度后端（db1） |
| HF_ENDPOINT | https://hf-mirror.com | HuggingFace 镜像（BGE-M3 / reranker 自动下载） |
