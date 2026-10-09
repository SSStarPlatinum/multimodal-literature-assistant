# 常见问题 FAQ

## 1. 项目概览

### Q: 这个项目是做什么的？
A: 多模态文献精读与知识图谱助手，面向科研人员和研究生，解决文献量大、公式图表难读、知识点零散的痛点。支持 PDF/图片文献解析、RAG 深度问答、知识图谱自动构建、综述辅助生成四大核心功能。

### Q: 技术栈是什么？
A: 前端 Vue3 + ECharts + Element Plus，后端 Python FastAPI，多模态模型 DeepSeek Flash / Qwen2.5-VL，向量嵌入 BGE-M3，向量库 ChromaDB，图数据库 Neo4j，RAG 框架 LlamaIndex，Docker Compose 容器化部署。

### Q: 需要 GPU 吗？
A: API 模式不需要 GPU，零硬件门槛。local 模式需要 GPU（7B 模型 4-bit 量化后约 4GB 显存）。

---

## 2. 模型配置

### Q: 支持哪些 LLM？
A: 任何 OpenAI 兼容 API 的模型都支持。项目实际使用配置：
- **DeepSeek Flash（视觉）+ DeepSeek Chat（文本）**：推荐方案
- 阿里云 Qwen2.5-VL（视觉）+ Qwen-Plus（文本）：备选
- 本地 Qwen2.5-VL（transformers 加载）

> 注意：`deepseek-v4-pro` 对结构化 JSON 输出会返回空 content，导致知识图谱抽取 0 节点，**不可用于图谱抽取**，文本模型请用 `deepseek-chat`。

### Q: DeepSeek 和 DashScope 怎么选？
A: 
- **DeepSeek（推荐）**：成本低，deepseek-flash 支持视觉，deepseek-chat 做文本抽取/问答稳定
- **DashScope**：国内访问稳定，Qwen 系列模型丰富，VL 模型成熟，作为备选

### Q: 为什么有两个模型配置（QWEN_API_MODEL 和 QWEN_TEXT_API_MODEL）？
A: 视觉任务（图片公式/表格识别）用 `QWEN_API_MODEL`，文本任务（图谱抽取/问答/综述）用 `QWEN_TEXT_API_MODEL`。当前推荐配置：视觉用便宜的 `deepseek-flash`，文本用 `deepseek-chat`。

### Q: VISION_ENABLED 设为 true 还是 false？
A: 
- 使用支持视觉的模型（deepseek-flash, qwen2.5-vl）→ `true`
- 使用纯文本模型（qwen-plus 纯文本）→ `false`
- 设为 false 时，PDF 文本解析、公式检测、图表提取（fitz）仍正常工作，仅跳过图片 OCR

### Q: FORMULA_VL_ENABLED 是什么？
A: 公式识别的 VL 增强开关，**默认 false**。关闭时公式采用「标号检测 + 区域裁剪 + 文本提取」方案，稳定且零额外 API 成本；开启后会对裁剪出的公式区域调用 VL 模型做增强识别（调用量增加）。一般保持默认 false 即可。

### Q: API Key 在哪里获取？
A: 
- DeepSeek: https://platform.deepseek.com/api_keys
- DashScope: https://dashscope.console.aliyun.com/apiKey

---

## 3. 文献解析

### Q: 支持哪些文件格式？
A: PDF、PNG、JPG、JPEG、TIFF。单张图片会送 VL 模型做公式和表格识别。

### Q: PDF 文本提取为什么用 PyMuPDF 而不是 pdfplumber？
A: pdfplumber 在 IEEE 双栏论文中常丢失空格（单词粘连），PyMuPDF 基于字符位置智能插入空格，准确率高得多。pdfplumber 保留为表格提取备选。

### Q: 公式识别准确吗？
A: 采用「公式标号检测 + 区域裁剪 + 文本提取」方案（`FORMULA_VL_ENABLED=false`，默认关闭 VL）：先匹配行内公式标号（如 `(1)`、`(2.3)`）定位公式位置，裁剪对应区域后提取文字，公式原图保存为 200dpi PNG，前端默认显示原图供人工对照。

实测：一篇 IEEE 双栏 5 页论文 12 个公式全部命中，其中 9/12 完全干净；已知限制是个别公式（编号靠后的 10-12）开头可能缺少少量变量名。如需更强识别，可在 `.env` 中开启 `FORMULA_VL_ENABLED=true`。

### Q: 文本块怎么切分的？
A: 基于 PyMuPDF (`fitz`) 的 block 结构切分，并按双栏排序：直接读取页面物理 block，左栏排完再排右栏。旧的空行切分不适用于双栏论文（整页合并成 5 块），新方案实测同一篇论文切出 143 个文本块，段落边界正确。

### Q: 图表图片存在哪里？
A: 从 PDF 提取的嵌入图片保存在 Docker 卷 `backend_figures`，对应容器路径 `/app/data/figures/`，通过 `/static/figures/` URL 访问。

### Q: 参考文献识别支持哪些格式？
A: 支持 IEEE `[1] Author, "Title," Journal, pp. X, Year.` 和 ACM `1. Author. Title. Journal, Year.` 两种主流格式。

---

## 4. 知识图谱

### Q: 图谱有哪些节点类型？
A: 5 类：Concept（概念）、Algorithm（算法/模型）、Dataset（数据集）、Metric（指标）、Conclusion（结论）。

### Q: 图谱有哪些关系类型？
A: 6 类：USES、IMPROVES、EVALUATES_ON、ACHIEVES、COMPARES_WITH、PROPOSED_BY。

### Q: 构建图谱后 0 节点怎么办？
A: 99% 是 API Key 配置问题。检查：
1. `docker logs literature-backend --tail 30` 看是否有 401 错误
2. `.env` 中 `QWEN_API_BASE`、`QWEN_API_KEY`、`QWEN_TEXT_API_MODEL` 三者是否匹配
3. 确认模型服务已开通（DeepSeek/DashScope 控制台）

详见 `07_TROUBLESHOOTING.md` 第 2.1 节。

### Q: 图谱节点可以自定义类型吗？
A: 当前固定 5 类。如需扩展，修改 `app/services/graph_service.py` 中的 `NODE_TYPE_TO_LABEL` 和 `prompts.py` 中的系统提示词。

### Q: 图谱数据存在哪里？
A: Neo4j 图数据库，数据卷 `neo4j_data`。可通过 http://localhost:7474 浏览器查看（neo4j / literature2024）。

---

## 5. RAG 问答

### Q: RAG 检索策略是什么？
A: 三层策略：
1. 摘要检索（top 3）：确定相关文献集合
2. 全文细查（top 8）：仅在相关文献内检索 chunk
3. 重排序（top 5）：bge-reranker 精排

### Q: 为什么不用全文直接检索？
A: 长文献全文检索容易引入噪声片段，先用摘要确定相关文献再细查，准确率更高。

### Q: 回答会标注引用来源吗？
A: 会。系统提示词要求答案中用 `[n]` 标注引用来源，n 对应片段编号。

---

## 6. 部署与运维

### Q: 启动后访问哪个地址？
A: 
- 前端：http://localhost:5173
- API 文档：http://localhost:8000/docs
- Neo4j 控制台：http://localhost:7474（neo4j / literature2024）

### Q: 启动命令是什么？
A: 推荐使用一键脚本：
```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```
脚本会先启动 Neo4j + Redis 并等待 Neo4j healthy（最多 180 秒），再启动其余服务，避免后端因依赖未就绪而反复重启。

### Q: 一共有几个服务？
A: 五个：frontend（Vue3+Nginx）、backend（FastAPI）、celery-worker（异步解析任务）、redis（Celery broker）、neo4j（图数据库）。

### Q: 首次启动为什么慢？
A: 后端首次启动会自动从 HuggingFace 镜像（hf-mirror.com）下载 BGE-M3 和 bge-reranker-v2-m3 两个模型，共约 2GB，缓存到 `backend_models` 卷（容器内 `/models`）。之后启动不再重复下载。

### Q: 如何完全重置项目？
A: `docker-compose down -v && docker-compose up -d --build`。这会删除所有数据卷（上传的文献、解析结果、向量索引、知识图谱）。

### Q: 如何备份数据？
A: 备份 8 个数据卷：neo4j_data、neo4j_logs、backend_uploads、backend_vector、backend_parsed、backend_figures、backend_models、redis_data。其中 backend_models 丢失后会自动重新下载，redis_data 为 Celery 任务状态。详见 `06_DEPLOYMENT.md` 第 4 节。

### Q: 修改代码后如何生效？
A: 
- 后端代码（Python）：backend 和 celery-worker 都挂载了代码卷 `./backend:/app`，**无需重新构建镜像**，重启即可：
  ```powershell
  docker-compose restart backend celery-worker
  ```
- 前端代码（Vue）：需要重新构建：
  ```powershell
  docker-compose build frontend
  docker-compose up -d frontend
  ```
- nginx 配置：frontend 的 build context 是 `./frontend`，必须修改 `frontend/nginx.conf`（并与 `docker/nginx.conf` 保持同步），再 build frontend。

### Q: 国内网络慢怎么办？
A: 项目已内置国内镜像：pip 清华源、npm 淘宝源、HuggingFace hf-mirror.com。可通过环境变量覆盖。

---

## 7. 开发扩展

### Q: 如何添加新的 API 端点？
A: 
1. 在 `app/schemas/` 定义 Pydantic 模型
2. 在 `app/services/` 实现业务逻辑
3. 在 `app/api/routes/` 添加路由
4. 在 `app/api/routes/__init__.py` 注册路由
5. 前端在 `src/api/` 添加对应封装

### Q: 如何添加新的节点/关系类型？
A: 
1. `graph_service.py`：修改 `NODE_TYPE_TO_LABEL` / `REL_TYPE_TO_REL`
2. `prompts.py`：更新系统提示词中的类型定义
3. 前端 `GraphView.vue`：添加类型颜色和筛选选项

### Q: 如何支持更多文献格式（如 .docx, .epub）？
A: 在 `parser_service.py` 的 `parse_file` 方法中添加格式分发，实现对应的 `_parse_xxx` 方法。

### Q: 如何增加论文投稿格式检查功能？
A: 预留扩展点。可在 `app/services/` 新增 `format_checker.py`，调用 LLM 检查文献格式合规性，添加对应路由。

---

## 8. 常见错误

### Q: 401 Incorrect API key
A: API Key 错误或与 base_url 不匹配。检查 `.env` 配置。

### Q: 404 model_not_found
A: 模型名错误。DeepSeek 用 `deepseek-flash`（视觉）/ `deepseek-chat`（文本），DashScope 用 `qwen-plus` / `qwen2.5-vl-7b-instruct`。注意 `deepseek-v4-pro` 不能用于结构化 JSON 任务。

### Q: Neo4j unhealthy
A: 健康检查用 `wget -q -O /dev/null`（neo4j 镜像无 curl），`start_period` 已设为 90s（首次初始化较慢）。如仍失败执行 `docker-compose down -v && docker-compose up -d`。

### Q: 图谱构建后 0 节点？
A: 除了检查 API Key / base_url / 模型名三者匹配外，特别注意：如果文本模型配置的是 `deepseek-v4-pro`，它对结构化 JSON 会返回空 content，导致 0 节点。改用 `deepseek-chat` 即可。详见 `07_TROUBLESHOOTING.md` 第 2.1 节。

### Q: 502 Bad Gateway
A: nginx 代理后端失败，通常是 backend 未启动或健康检查未通过。执行 `docker-compose ps backend` 看状态，`docker logs literature-backend --tail 50` 看日志，等 backend healthy 后刷新。详见 `07_TROUBLESHOOTING.md` 第 3.4 节。

### Q: Celery 任务一直 PENDING（解析不动）
A: 异步解析任务由 celery-worker 消费。先看 `docker logs literature-celery-worker --tail 50`，常见原因是 `.env` 中 `REDIS_PASSWORD` 与 redis 服务实际密码不一致，或 worker 首次启动还在下载向量模型。详见 `07_TROUBLESHOOTING.md` 第 3.7 节。

### Q: 图表图片 404
A: nginx 缺少 `/static/` 代理。确认 `frontend/nginx.conf` 包含 `location /static/` 配置并重新 build。

### Q: 前端页面空白
A: 检查浏览器控制台。常见原因：API 地址配置错误、后端未启动、CORS 问题。
