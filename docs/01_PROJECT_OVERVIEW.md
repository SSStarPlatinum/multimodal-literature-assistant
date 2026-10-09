# 项目概述

## 1. 项目定位

**多模态文献精读与知识图谱助手**是一个面向科研人员、研究生的 AI 文献研读工具，解决以下痛点：

- 文献量大，阅读效率低
- 数学公式、图表难以解析和检索
- 知识点零散，难以形成结构化认知
- 跨文献对比、综述写作耗时

## 2. 核心功能

### 2.1 多模态文献解析
- 支持 PDF / PNG / JPG 格式文献上传
- 自动识别文字、数学公式（转 LaTeX）、图表数据、参考文献
- 文本块按段落智能切分，保留阅读顺序
- 公式严格检测（数学符号密度 + LaTeX 关键词 + 常见词排除）
- 嵌入图片提取并持久化，前端可直接预览

### 2.2 深度精准问答（RAG）
- 基于 LlamaIndex + ChromaDB 的向量检索架构
- 「摘要检索 + 全文细查」分层策略，避免全库扫描
- bge-reranker-v2-m3 重排序，提升长文献问答准确率
- 支持跨文献对比、溯源引用来源、定位关键实验数据

### 2.3 知识图谱自动构建
- LLM 从文献中抽取核心概念、算法模型、实验结论和关联关系
- 5 类节点：Concept（概念）、Algorithm（算法）、Dataset（数据集）、Metric（指标）、Conclusion（结论）
- 6 类关系：USES、IMPROVES、EVALUATES_ON、ACHIEVES、COMPARES_WITH、PROPOSED_BY
- Neo4j 图数据库存储，ECharts 力导向图可视化
- 支持按节点类型筛选、节点点击查看详情、缩放拖拽

### 2.4 综述辅助生成
- 自动梳理研究领域发展脉络
- 生成文献综述大纲、核心观点汇总
- 研究缺口分析与未来方向建议

## 3. 技术栈

| 层级 | 技术 | 版本/说明 |
|------|------|-----------|
| 前端框架 | Vue 3 | Composition API + `<script setup>` |
| 构建工具 | Vite | 5.x |
| UI 组件库 | Element Plus | 2.x |
| 状态管理 | Pinia | 2.x |
| HTTP 客户端 | Axios | 1.x |
| 图谱可视化 | ECharts | 5.x（力导向图） |
| 公式渲染 | KaTeX | 0.16.x |
| 后端框架 | FastAPI | 0.110+ |
| 文本提取 | PyMuPDF (fitz) | 1.24+（主引擎） |
| 表格提取 | pdfplumber | 0.11+（备选） |
| 多模态模型 | DeepSeek Flash(视觉) / DeepSeek Chat(文本) | API 模式 |
| 向量嵌入 | BGE-M3 | 1024 维稠密向量 |
| 重排序 | bge-reranker-v2-m3 | CrossEncoder |
| RAG 框架 | LlamaIndex | 0.10+ |
| 向量数据库 | ChromaDB | 0.5+ |
| 图数据库 | Neo4j | 5.16 Community |
| 容器化 | Docker Compose | 五服务编排 |
| 模型量化 | bitsandbytes | 4-bit nf4 + 嵌套量化（local 模式） |

## 4. 项目亮点

1. **多模态融合**：不只是文本总结，融合多模态理解与结构化知识抽取
2. **RAG 优化**：「摘要检索 + 全文细查」分层策略 + 重排序模型，提升长文献问答准确率
3. **工程化完整**：Docker Compose 一键部署，健康检查、数据卷、环境变量模板齐全
4. **模型双模式**：API 模式调用 DeepSeek（零硬件门槛，4GB RAM 即可）/ local 模式（4-bit 量化，7B 模型显存从 14GB 降至 ~4GB）
5. **国内网络适配**：pip 清华镜像、npm 淘宝镜像、HF_ENDPOINT 镜像，均可环境变量覆盖
6. **可扩展**：预留论文投稿格式检查、实验数据可信度评估等进阶功能接口

## 5. 目录结构

```
multimodal-literature-assistant/
├── backend/                    # 后端 FastAPI 服务（backend 与 celery-worker 均挂载 ./backend:/app）
│   ├── main.py                 # 应用入口（CORS/异常/路由/静态文件/健康检查）
│   ├── requirements.txt        # Python 依赖
│   ├── Dockerfile              # （通过 docker/backend.Dockerfile 构建）
│   └── app/
│       ├── api/routes/         # upload / qa / graph / review 四组路由
│       ├── core/               # 配置管理、日志、异常定义
│       ├── schemas/            # Pydantic 请求/响应模型
│       ├── services/           # 6 个服务：模型加载器/解析/向量/RAG/图谱/综述
│       └── utils/              # prompts（LLM提示词集中管理）、文件工具
├── frontend/                   # 前端 Vue3 应用
│   ├── src/
│   │   ├── views/              # UploadView / QAView / GraphView / ReviewView
│   │   ├── components/         # DocumentSelector / FormulaRenderer / Sidebar / LoadingSpinner
│   │   ├── api/                # axios 封装，严格对齐 API 契约
│   │   ├── stores/             # Pinia 状态管理（document/qa/graph）
│   │   ├── router/             # Vue Router
│   │   └── dist/               # 构建产物
│   └── nginx.conf              # Nginx 配置（build context 为 ./frontend，须与 docker/nginx.conf 同步）
├── docker/                     # Dockerfile 和 nginx 配置
│   ├── backend.Dockerfile      # 多阶段构建（依赖构建 + 运行时）
│   ├── frontend.Dockerfile     # 多阶段构建（Node构建 + Nginx运行）
│   └── nginx.conf              # nginx 配置（须与 frontend/nginx.conf 保持同步）
├── docs/                       # 项目文档
│   ├── API_CONTRACT.md         # 前后端 API 契约
│   ├── 01_PROJECT_OVERVIEW.md  # 本文档
│   ├── 02_ARCHITECTURE.md      # 系统架构
│   ├── 03_BACKEND_IMPLEMENTATION.md
│   ├── 04_FRONTEND_IMPLEMENTATION.md
│   ├── 05_RAG_AND_KNOWLEDGE_GRAPH.md
│   ├── 06_DEPLOYMENT.md
│   ├── 07_TROUBLESHOOTING.md
│   └── 08_FAQ.md
├── docker-compose.yml          # 五服务编排（neo4j / redis / celery-worker / backend / frontend）
├── .env.example                # 环境变量模板
├── start.ps1                   # Windows 一键启动脚本（先启 neo4j+redis 等待 healthy）
└── README.md                   # 项目主文档
```

> 五服务说明：literature-neo4j（7474/7687，neo4j:5.16-community）、literature-redis（redis:7-alpine，Celery broker，不暴露宿主机端口）、literature-celery-worker（异步解析任务消费者，6 级进度上报）、literature-backend（8000，FastAPI，代码卷挂载 ./backend:/app）、literature-frontend（5173→80，Vue3+Nginx）。`backend_models` 卷挂载到 `/models`，由 backend 与 celery-worker 共享 BGE-M3 / bge-reranker 缓存。
