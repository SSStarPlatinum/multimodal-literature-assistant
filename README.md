# 多模态文献精读与知识图谱助手

> 面向科研人员、研究生的 AI 文献研读工具 —— 公式精准识别、分层 RAG 问答、知识图谱自动构建

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/Vue-3.x-green)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-teal)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

## 一分钟启动

```powershell
# 1. 配置 API Key
copy .env.example .env
# 编辑 .env，填入 QWEN_API_KEY（DeepSeek API Key）

# 2. 启动全部服务
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

启动后访问：
- 前端页面：http://localhost:5173
- API 文档：http://localhost:8000/docs
- Neo4j 控制台：http://localhost:7474（neo4j / literature2024）

## 核心功能

| 功能 | 说明 |
|------|------|
| **公式精准识别** | 基于论文标号 `(1)(2)` 定位公式区域，文本提取 + 公式原图对照，LaTeX 一键查看 |
| **分层 RAG 问答** | 摘要粗检索 → 全文细检索 → bge-reranker 重排序，答案带引用溯源 |
| **知识图谱构建** | LLM 抽取概念/算法/结论及关联，Neo4j 存储，ECharts 力导向图可视化 |
| **多模态解析** | PyMuPDF 引擎，双栏排版识别，文本/公式/图表/参考文献结构化输出 |
| **综述辅助生成** | 自动梳理研究脉络，生成综述大纲、核心观点汇总与研究缺口分析 |
| **异步任务队列** | Celery + Redis，6 级进度上报，长文献解析不阻塞 |

## 实测效果

以 5 页 IEEE 双栏论文为例：
- 文本块：143 个（按段落切分，非整页合并）
- 公式：12/12 全部命中，9 个完全干净
- 参考文献：35 条
- 向量索引：143 chunks，问答响应 ~15s

---

## 目录

- [项目简介](#项目简介)
- [系统架构](#系统架构)
- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [环境要求](#环境要求)
- [快速启动](#快速启动)
- [本地开发](#本地开发)
- [API 文档](#api-文档)
- [配置说明](#配置说明)
- [常见问题排查](#常见问题排查)
- [完整文档索引](#完整文档索引)

---

## 项目简介

本项目是一个**完整可运行**的全栈 AI 应用，融合多模态理解与结构化知识抽取，不仅仅是文本总结工具。支持 PDF/图片文献上传、数学公式自动转 LaTeX、基于分层 RAG 的跨文献精准问答、知识图谱自动构建与可视化、以及文献综述辅助生成。

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (Vue3 + ECharts)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ 上传解析  │ │ 深度问答  │ │ 知识图谱  │ │ 综述生成  │       │
│  │ (轮询进度)│ │          │ │          │ │          │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP / REST API
┌────────────────────────▼────────────────────────────────────┐
│                    后端 (Python FastAPI)                      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────┐ │
│  │ 上传路由    │ │ RAG 服务    │ │ 图谱服务    │ │ 综述服务  │ │
│  │ (提交任务)  │ │ LlamaIndex │ │  Neo4j     │ │  LLM     │ │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └──────────┘ │
│        │              │              │                        │
│  ┌─────▼──────────────▼──────────────▼──────────────────┐   │
│  │              模型加载器 (Model Loader)                  │   │
│  │   local: transformers + bitsandbytes 4-bit 量化        │   │
│  │   api:   OpenAI 兼容客户端 (DeepSeek API)              │   │
│  └───────────────────────────────────────────────────────┘   │
└──────┬───────────────────┬───────────────────┬───────────────┘
       │ 提交任务           │                   │
       ▼                    ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌────────────────┐
│  Redis       │   │  Chroma      │   │    Neo4j       │
│  消息队列     │   │  向量存储    │   │  知识图谱存储   │
│  (broker+    │   │  (summary   │   │  节点/关系      │
│   result)    │   │   +fulltext)│   │                │
└──────┬───────┘   └──────────────┘   └────────────────┘
       │ 消费任务
       ▼
┌──────────────────────────────────────────────────────────────┐
│              Celery Worker (异步解析任务消费者)                 │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  解析服务 (parser_service)                               │  │
│  │  文本提取 → 公式识别 → 图表提取 → 参考文献 → 摘要生成    │  │
│  │  进度通过 self.update_state 上报，前端每 2s 轮询         │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 异步任务架构

文献解析采用 **Celery + Redis** 异步任务队列，避免长耗时解析阻塞 HTTP 请求：

```
用户上传 PDF
    │
    ▼
POST /upload  ──►  文件落盘 + 提交 Celery任务  ──►  立即返回 task_id
    │
    ▼ (前端每 2s 轮询)
GET /task/{task_id}  ──►  Redis 查询任务状态
    │
    ├── PENDING: 等待 worker 领取
    ├── PROCESSING: 解析中，返回 progress(0-100) + current_step
    │   ├── upload_complete (10%)
    │   ├── text_extraction (30%)
    │   ├── formula_recognition (50%)
    │   ├── figure_extraction (70%)
    │   ├── references (85%)
    │   └── summary_generation (100%)
    ├── SUCCESS: 解析完成，自动刷新文档列表 + 加载详情
    └── FAILURE: 解析失败，展示错误信息
```

- **Worker 与 Backend 共享同一镜像**（不同 command），保证依赖和运行时一致
- **代码卷挂载**：backend 与 celery-worker 均挂载 `./backend:/app`，修改代码后 `docker-compose restart` 即生效，无需重新构建镜像
- **Worker 挂载全部数据卷**（uploads/vector/parsed/figures），可直接读写上传文件和解析产物
- **模型卷共享**：`backend_models` 卷挂载到 `/models`，backend 与 celery-worker 共享 BGE-M3 / bge-reranker 缓存（本地路径不存在时自动从 hf-mirror 下载）
- **Redis 带密码保护**（`REDIS_PASSWORD`），broker 用 db0，result backend 用 db1，不暴露宿主机端口
- **前端轮询超时 5 分钟**，超时后提示用户在文档列表查看状态

### RAG 分层检索策略

```
用户问题
    │
    ▼
┌─────────────────┐
│  第一层: 摘要检索  │  每篇文献的结构化摘要(purpose/methods/data/conclusion)
│  (Summary Ret.) │  嵌入后粗检索，命中相关文献集合
└────────┬────────┘
         │ 命中的 document_id 集合
         ▼
┌─────────────────┐
│  第二层: 全文细查  │  仅在命中文献范围内进行 chunk 级细粒度检索
│  (Fulltext Ret.)│  避免全库扫描，提升精度和效率
└────────┬────────┘
         │ 合并去重
         ▼
┌─────────────────┐
│  第三层: 重排序    │  bge-reranker-v2-m3 对结果交叉编码重排序
│  (Rerank)       │  取 Top-N 作为最终上下文
└────────┬────────┘
         ▼
    LLM 生成回答（含引用溯源）
```

## 核心功能

### 1. 多模态文献解析
- **PDF 解析**：基于 PyMuPDF (fitz) block 结构切分文本，双栏排序（左栏按 y 排序后接右栏），过滤页码页眉；pdfplumber 备选表格提取
- **公式识别**：基于公式标号 (1)(2)... 检测 + 区域裁剪 + 文本提取，每个公式区域渲染为 200dpi PNG 保存到 `/app/data/figures/`，公式条目含 `image_url` 字段；旧的 VL 识别方案效果差已废弃为可选，默认关闭（`FORMULA_VL_ENABLED=false`）
- **公式标签页**：默认显示公式原图，点击"查看LaTeX格式"展开显示红色 LaTeX 代码，标注页码
- **图片解析**：PIL 预处理后送 VL 模型进行 OCR + 公式识别
- **图表提取**：fitz 提取嵌入图片并持久化，表格自动转 Markdown
- **参考文献解析**：正则提取 + 结构化解析（年份、作者、标题）
- **结构化摘要**：自动生成 purpose/methods/data/conclusion 四元摘要

### 2. 深度精准问答
- **跨文献问答**：支持同时选择多篇文献进行问答
- **分层检索**：摘要粗检索 → 全文细检索 → 重排序，三层策略
- **引用溯源增强（P1）**：向量库记录每个 chunk 的页码、段落序号、字符偏移；回答中每个引用附带页码和段落ID；点击引用跳转到文献上传页，自动滚动并高亮对应文本块
- **文献对比**：按 method/dataset/metric/conclusion 维度对比多篇文献
- **检索模式**：支持 summary / fulltext / hybrid 三种模式切换

### 3. 知识图谱自动构建与人工校对
- **实体抽取**：Concept（概念）、Algorithm（算法模型）、Dataset（数据集）、Metric（评估指标）、Conclusion（实验结论）
- **关系抽取**：USES、IMPROVES、EVALUATES_ON、ACHIEVES、COMPARES_WITH、PROPOSED_BY
- **Neo4j 存储**：Cypher 语句写入，支持持久化和查询
- **ECharts 可视化**：力导向图（force graph），节点按类型着色，支持缩放拖拽、点击详情、类型筛选
- **人工校对（P1）**：节点点击弹出编辑面板（修改名称/描述/类型）；支持删除节点（连带删除关系）；支持添加节点和关系；所有修改操作记录操作日志（持久化 JSONL）

### 4. 综述辅助生成与导出
- **综述大纲**：自动生成背景/方法/数据/挑战/展望章节大纲
- **核心观点汇总**：每个观点标注支撑文献和证据
- **研究缺口分析**：按高/中/低严重程度分级，给出建议方向
- **发展脉络时间线**：梳理研究领域里程碑事件
- **综述导出（P1）**：支持导出为 Markdown 文件（带引用格式）和 Word (.docx) 文件，内容包含大纲、核心观点、研究缺口、发展脉络、参考文献列表

### 5. 文献管理增强（P1）
- **标签系统**：每篇文献可加多个标签，按标签筛选
- **全文搜索**：标题/文件名关键词搜索
- **批量操作**：批量删除、批量构建图谱
- **文献详情**：显示元信息、统计、解析时间

## 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| 前端框架 | Vue 3 | ^3.4 |
| 构建工具 | Vite | ^5.0 |
| 状态管理 | Pinia | ^2.1 |
| 路由 | Vue Router | ^4.2 |
| UI 组件 | Element Plus | ^2.5 |
| 图谱可视化 | ECharts | ^5.5 |
| HTTP 客户端 | Axios | ^1.6 |
| 公式渲染 | KaTeX | ^0.16 |
| 后端框架 | FastAPI | ^0.109 |
| RAG 框架 | LlamaIndex | ^0.10 |
| 向量嵌入 | BGE-M3 (sentence-transformers) | ^2.2 |
| 向量存储 | ChromaDB | ^0.4 |
| 知识图谱 | Neo4j | 5.16 |
| 多模态模型 | DeepSeek Flash(视觉) / DeepSeek Chat(文本) | API 模式 |
| 重排序 | bge-reranker-v2-m3 | - |
| 4-bit 量化 | bitsandbytes | ^0.42（仅 local 模式） |
| 异步任务队列 | Celery + Redis | 5.3+ / 7.x |
| 文档导出 | python-docx | >=1.1.0 |
| 容器化 | Docker + Docker Compose | 五服务编排 |

## 目录结构

```
multimodal-literature-assistant/
├── frontend/                    # 前端 Vue3 应用
│   ├── src/
│   │   ├── api/                 # API 封装层（axios）
│   │   │   ├── index.js         #   axios 实例 + 拦截器
│   │   │   ├── document.js      #   文献上传/列表/详情
│   │   │   ├── task.js          #   异步任务状态查询
│   │   │   ├── qa.js            #   问答/对比
│   │   │   ├── graph.js         #   图谱构建/查询
│   │   │   └── review.js        #   综述生成
│   │   ├── components/          # 通用组件
│   │   │   ├── DocumentSelector.vue
│   │   │   ├── FormulaRenderer.vue
│   │   │   ├── LoadingSpinner.vue
│   │   │   └── Sidebar.vue
│   │   ├── stores/              # Pinia 状态管理
│   │   │   ├── document.js
│   │   │   ├── qa.js
│   │   │   └── graph.js
│   │   ├── views/               # 4 个核心页面
│   │   │   ├── UploadView.vue   #   文献上传与解析
│   │   │   ├── QAView.vue       #   深度问答
│   │   │   ├── GraphView.vue    #   知识图谱可视化
│   │   │   └── ReviewView.vue   #   综述生成
│   │   ├── router/index.js      # 路由配置
│   │   ├── App.vue              # 根组件（布局）
│   │   ├── main.js              # 应用入口
│   │   └── style.css            # 全局样式
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf               # Nginx 配置（build context 为 ./frontend，须与 docker/nginx.conf 保持同步）
│   └── index.html
├── backend/                     # 后端 FastAPI 服务
│   ├── app/
│   │   ├── api/routes/          # API 路由
│   │   │   ├── upload.py        #   POST /upload(异步), GET /task/{id}, GET /documents
│   │   │   ├── qa.py            #   POST /qa/ask, /qa/compare
│   │   │   ├── graph.py         #   POST /graph/build, GET /graph/{id}
│   │   │   └── review.py        #   POST /review/generate
│   │   ├── core/                # 核心配置
│   │   │   ├── config.py        #   pydantic-settings 环境变量管理
│   │   │   ├── celery_app.py    #   Celery 实例（broker/backend/序列化）
│   │   │   ├── logging.py       #   日志配置
│   │   │   └── exceptions.py    #   自定义异常
│   │   ├── schemas/             # Pydantic 请求/响应模型
│   │   │   ├── document.py      #   文档相关模型
│   │   │   └── task.py          #   异步任务状态模型
│   │   ├── tasks/               # Celery 异步任务
│   │   │   └── parse_task.py    #   文献解析任务（进度上报+索引更新）
│   │   ├── services/            # 业务服务层
│   │   │   ├── model_loader.py  #   模型加载器（local/api 双模式）
│   │   │   ├── parser_service.py#   多模态解析服务
│   │   │   ├── vector_service.py#   向量嵌入与索引
│   │   │   ├── rag_service.py   #   RAG 分层检索问答
│   │   │   ├── graph_service.py #   Neo4j 知识图谱
│   │   │   └── review_service.py#   综述生成
│   │   └── utils/               # 工具
│   │       ├── file_utils.py
│   │       ├── task_utils.py    #   任务状态查询工具
│   │       └── prompts.py       # 全部 LLM prompt 集中管理
│   ├── data/                    # 数据目录（uploads, vector_store）
│   ├── main.py                  # FastAPI 入口
│   ├── requirements.txt
│   └── .env.example
├── docker/                      # Docker 配置
│   ├── backend.Dockerfile
│   ├── frontend.Dockerfile
│   └── nginx.conf               # Nginx 配置（须与 frontend/nginx.conf 保持同步）
├── docs/
│   └── API_CONTRACT.md          # API 契约规范
├── docker-compose.yml           # Docker Compose 五服务编排（neo4j/redis/celery-worker/backend/frontend）
├── .env.example                 # Compose 环境变量模板
├── start.ps1                    # Windows 快速启动脚本（英文注释，先启 neo4j+redis 等待 healthy）
└── README.md
```

## 环境要求

### Docker 部署（推荐）
- Docker Engine >= 20.10
- Docker Compose >= 2.0
- 至少 4GB RAM（api 模式）/ 16GB RAM + GPU（local 模式）
- 磁盘空间 >= 10GB

### 本地开发
- Python >= 3.10（推荐 3.11）
- Node.js >= 18（推荐 20）
- npm >= 9
- Neo4j >= 5.0（可选，Docker 方式自动提供）

## 快速启动

### 方式一：Docker Compose 一键启动（推荐）

```powershell
# 1. 进入项目目录
cd D:\TEST\multimodal-literature-assistant

# 2. 复制环境变量配置
copy .env.example .env

# 3. 编辑 .env，填入你的 DeepSeek API Key（api 模式）
#    QWEN_API_KEY=your-deepseek-api-key

# 4. 启动所有服务（neo4j + redis + celery-worker + backend + frontend）
docker-compose up -d --build

# 5. 访问
#    前端页面:  http://localhost:5173
#    API 文档:  http://localhost:8000/docs
#    Neo4j 控制台: http://localhost:7474 (neo4j / literature2024)
#
# 服务说明：
#   - neo4j: 知识图谱存储
#   - redis: Celery 消息队列 + 结果后端（带密码，不暴露宿主机端口）
#   - celery-worker: 异步解析任务消费者（复用 backend 镜像）
#   - backend: FastAPI API 服务
#   - frontend: Vue3 前端
```

或使用快速启动脚本（先启动 neo4j + redis 等待 healthy，再启动其余服务）：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

### 方式二：本地开发启动

详见 [本地开发](#本地开发) 章节。

## 本地开发

### 后端开发

```powershell
cd backend

# 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装依赖（使用国内镜像加速）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 配置环境变量
copy .env.example .env
# 编辑 .env，设置 QWEN_API_KEY

# 启动开发服务器（需要先启动 Neo4j，或使用 Docker 仅启动 neo4j）
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

仅启动 Neo4j（供本地后端连接）：

```powershell
docker-compose up -d neo4j
```

### 前端开发

```powershell
cd frontend

# 安装依赖
npm install

# 启动开发服务器（自动代理 /api -> http://localhost:8000）
npm run dev
# 访问 http://localhost:5173
```

### 生产构建

```powershell
# 前端构建
cd frontend
npm run build
# 产物在 dist/ 目录
```

## API 文档

完整 API 契约见 [docs/API_CONTRACT.md](docs/API_CONTRACT.md)。

### 端点总览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/upload` | 上传文献并提交异步解析任务，立即返回 task_id |
| GET | `/api/v1/task/{task_id}` | 查询异步解析任务状态（6 级进度/当前步骤/结果/错误） |
| GET | `/api/v1/documents` | 获取文献列表 |
| GET | `/api/v1/documents/{id}` | 获取文献解析详情 |
| DELETE | `/api/v1/documents/{id}` | 删除文献 |
| POST | `/api/v1/qa/ask` | RAG 深度问答 |
| POST | `/api/v1/qa/compare` | 多文献对比 |
| POST | `/api/v1/graph/build` | 构建知识图谱 |
| GET | `/api/v1/graph/list` | 图谱列表 |
| GET | `/api/v1/graph/{id}` | 获取图谱详情 |
| DELETE | `/api/v1/graph/{id}` | 删除图谱 |
| POST | `/api/v1/review/generate` | 生成综述 |
| GET | `/static/figures/{filename}` | 访问公式/图表图片 |
| GET | `/api/v1/health` | 健康检查 |

启动后访问 `http://localhost:8000/docs` 查看交互式 Swagger 文档。

## 配置说明

### 模型模式（MODEL_MODE）

| 模式 | 说明 | 硬件要求 | 适用场景 |
|------|------|----------|----------|
| `api` | 调用 DeepSeek API（OpenAI 兼容） | 低（4GB RAM） | 快速体验、无 GPU |
| `local` | 本地加载 Qwen2.5-VL | 高（16GB RAM + GPU） | 数据隐私、离线部署 |

### 4-bit 量化（仅 local 模式）

通过环境变量控制：

```env
ENABLE_4BIT_QUANTIZATION=true   # 启用 4-bit 量化
LOAD_IN_4BIT=true               # 加载时量化
BNB_4BIT_QUANT_TYPE=nf4         # 量化类型 nf4/fp4
BNB_4BIT_USE_NESTED_QUANT=true  # 嵌套量化（进一步省显存）
BNB_4BIT_COMPUTE_DTYPE=float16  # 计算精度
```

启用 4-bit 量化后，7B 模型显存占用从 ~14GB 降至 ~4GB。

### 国内网络环境

项目已内置国内镜像源配置：

- **pip 镜像**：Dockerfile 中使用清华镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`
- **npm 镜像**：Dockerfile 中使用淘宝镜像 `https://registry.npmmirror.com`
- **HuggingFace 镜像**：默认 `HF_ENDPOINT=https://hf-mirror.com`，可通过环境变量覆盖

如需使用官方源，设置 `HF_ENDPOINT=https://huggingface.co` 即可。

### 关键环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_MODE` | `api` | 模型加载模式（api=调用 DeepSeek API，无需 GPU） |
| `QWEN_API_KEY` | - | DeepSeek API Key（api 模式必填） |
| `QWEN_API_BASE` | `https://api.deepseek.com` | API 端点 |
| `QWEN_API_MODEL` | `deepseek-flash` | 视觉模型（公式/图片理解，DeepSeek Flash 已支持视觉） |
| `QWEN_TEXT_API_MODEL` | `deepseek-chat` | 文本模型（图谱抽取/问答；deepseek-v4-pro 结构化 JSON 输出为空，不可用于图谱抽取） |
| `VISION_ENABLED` | `true` | 是否启用视觉能力 |
| `ENABLE_4BIT_QUANTIZATION` | `true` | 4-bit 量化开关（仅 local 模式） |
| `NEO4J_PASSWORD` | `literature2024` | Neo4j 密码 |
| `REDIS_PASSWORD` | `literature_redis_2024` | Redis 密码（Celery broker/backend） |
| `CELERY_BROKER_URL` | `redis://:...@redis:6379/0` | Celery 消息队列地址 |
| `CELERY_RESULT_BACKEND` | `redis://:...@redis:6379/1` | Celery 结果后端地址 |
| `EMBEDDING_DEVICE` | `cpu` | 嵌入模型设备（cpu/cuda） |
| `CHUNK_SIZE` | `512` | 文本分块大小 |
| `RAG_TOP_K` | `5` | 检索返回数量 |
| `FORMULA_VL_ENABLED` | `false` | 公式 VL 识别开关（默认关闭，改用标号检测 + 区域裁剪 + 文本提取） |
| `FORMULA_VL_MAX_PER_PAGE` | `5` | 每页最多识别公式数（FORMULA_VL_ENABLED=true 时生效） |
| `HF_ENDPOINT` | hf-mirror | HuggingFace 镜像（BGE-M3 / bge-reranker 首次启动自动下载） |

## 常见问题排查

### 1. Docker 镜像拉取失败

**现象**：`docker-compose build` 时报网络超时或拉取失败。

**解决**：
```powershell
# 配置 Docker 国内镜像加速器
# 在 Docker Desktop -> Settings -> Docker Engine 中添加：
# "registry-mirrors": ["https://docker.mirrors.ustc.edu.cn"]
```

### 2. 后端启动失败：Neo4j 连接超时

**现象**：日志显示 `ServiceUnavailable` 或连接超时。

**解决**：
```powershell
# 确认 Neo4j 已启动且健康
docker-compose ps
docker-compose logs neo4j

# Neo4j 首次启动需要 10-30 秒初始化，等待健康检查通过
# 后端 depends_on 已配置 condition: service_healthy
```

### 3. API 调用返回 401 / 认证失败

**现象**：问答或解析接口返回认证错误。

**解决**：
- 确认 `.env` 中 `QWEN_API_KEY` 已正确填写
- 确认 `MODEL_MODE=api`
- 检查 API Key 是否有余额和对应模型权限
- DeepSeek 开放平台: https://platform.deepseek.com/

### 4. 前端页面空白或 API 请求失败

**现象**：页面打开空白，或控制台显示网络错误。

**解决**：
```powershell
# 确认后端已启动
curl http://localhost:8000/api/v1/health

# 确认前端代理配置（vite.config.js）
# 开发模式: /api -> http://localhost:8000
# Docker 模式: Nginx 代理 /api -> backend:8000

# 清除浏览器缓存后重试
```

### 5. 本地模式模型加载失败（OOM）

**现象**：`CUDA out of memory` 或内存不足。

**解决**：
- 确保 `ENABLE_4BIT_QUANTIZATION=true`
- 7B 模型 4-bit 量化后约需 4-5GB 显存
- 如无 GPU，设置 `EMBEDDING_DEVICE=cpu` 并使用 `api` 模式
- 本地模型路径通过 `QWEN_MODEL_PATH` 指定，或挂载到 `/models`

### 6. 上传大文件失败

**现象**：上传超过 50MB 的 PDF 报错。

**解决**：
- 默认 `MAX_UPLOAD_SIZE=52428800`（50MB）
- 修改 `.env` 中 `MAX_UPLOAD_SIZE` 值
- Docker 部署时 Nginx 已配置 `client_max_body_size 100m`

### 7. 知识图谱节点不显示

**现象**：图谱构建成功但前端无节点显示。

**解决**：
- 确认 Neo4j 连接正常：访问 http://localhost:7474
- 在 Neo4j Browser 中执行 `MATCH (n) RETURN n LIMIT 100` 验证数据
- 检查图谱构建接口返回的 `stats.nodes` 是否大于 0
- 实体抽取依赖 LLM 输出，文本过短可能抽取结果为空

### 8. pip install 速度慢

**解决**：
```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 9. 上传后任务一直 PENDING（worker 未消费）

**现象**：前端显示"等待中"，`GET /task/{task_id}` 返回 status=PENDING 超过 30 秒。

**解决**：
```powershell
# 检查 celery-worker 容器状态和日志
docker-compose ps celery-worker
docker-compose logs celery-worker

# 常见原因：
# 1. worker 启动中（首次需加载模型依赖，约 30-60s），等待健康检查通过
# 2. Redis 连接失败：检查 REDIS_PASSWORD 是否一致，worker 环境变量中 CELERY_BROKER_URL 是否正确
# 3. 任务未注册：确认 celery_app.py 中 imports=["app.tasks.parse_task"] 存在
```

### 10. 解析任务失败（FAILURE）

**现象**：前端显示红色错误信息，文档列表中状态为 failed。

**解决**：
```powershell
# 查看 worker 日志中的完整异常堆栈
docker-compose logs celery-worker --tail=100

# 常见原因：
# 1. 模型 API Key 无效或欠费：检查 QWEN_API_KEY 和余额
# 2. PDF 文件损坏：尝试用其他 PDF 阅读器打开验证
# 3. 内存不足（local 模式）：增加 Docker 内存限制或使用 api 模式
# 4. 向量索引失败：不影响解析结果，仅警告，可在 backend 日志中查看
```

### 11. 本地开发时如何启动 Celery Worker

```powershell
# 1. 先启动 Redis（可用 Docker 仅启动 redis）
docker-compose up -d redis

# 2. 设置环境变量（指向本地 Redis）
$env:CELERY_BROKER_URL="redis://:literature_redis_2024@localhost:6379/0"
$env:CELERY_RESULT_BACKEND="redis://:literature_redis_2024@localhost:6379/1"

# 3. 启动 worker（在 backend 目录下）
cd backend
celery -A app.core.celery_app.celery_app worker --loglevel=info --concurrency=2

# 4. 另开终端启动 FastAPI
uvicorn main:app --reload
```

## 已知限制

- 公式 (10-12) 等二维布局公式开头可能缺少少量变量名（左半部分丢失），可通过"查看原文"对照公式原图
- 图表提取仅能提取嵌入位图，矢量图形可能无法识别
- 首次启动需自动下载 BGE-M3（约 2GB）和 bge-reranker 模型到 `/models`，耗时较长
- api 模式需有效的 DeepSeek API Key 及余额
- 前端修改后需重新构建镜像：`docker-compose build frontend && docker-compose up -d frontend`；后端代码改动 `docker-compose restart` 即生效

---

## 完整文档索引

项目包含完整的技术文档集，位于 `docs/` 目录，覆盖所有实现细节、设计决策和问题排查：

| 文档 | 内容 |
|------|------|
| [docs/01_PROJECT_OVERVIEW.md](docs/01_PROJECT_OVERVIEW.md) | 项目定位、核心功能、技术栈、目录结构 |
| [docs/02_ARCHITECTURE.md](docs/02_ARCHITECTURE.md) | 系统架构图、服务编排、请求流转、模型架构 |
| [docs/03_BACKEND_IMPLEMENTATION.md](docs/03_BACKEND_IMPLEMENTATION.md) | 6 个服务的完整实现、关键算法、代码设计决策 |
| [docs/04_FRONTEND_IMPLEMENTATION.md](docs/04_FRONTEND_IMPLEMENTATION.md) | 4 个页面、组件、状态管理、ECharts 配置 |
| [docs/05_RAG_AND_KNOWLEDGE_GRAPH.md](docs/05_RAG_AND_KNOWLEDGE_GRAPH.md) | 三层检索策略、图谱 Schema、Prompt 工程、容错机制 |
| [docs/06_DEPLOYMENT.md](docs/06_DEPLOYMENT.md) | 环境要求、快速启动、服务管理、数据备份、生产建议 |
| [docs/07_TROUBLESHOOTING.md](docs/07_TROUBLESHOOTING.md) | 所有已知问题的根因分析和解决方案（10+ 已解决问题） |
| [docs/08_FAQ.md](docs/08_FAQ.md) | 50+ 常见问题的简明回答 |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | 前后端接口定义、请求/响应格式 |

**快速查找**：遇到问题先查 [07 问题排查手册](docs/07_TROUBLESHOOTING.md)，再查 [08 FAQ](docs/08_FAQ.md)。

---

## 许可证

MIT License
