# 问题排查手册

本文档记录项目开发和部署过程中遇到的所有问题、根因分析和解决方案。

---

## 1. 文献解析问题

### 1.1 文本块单词粘连

**现象**：上传 PDF 后，文本块中所有单词连在一起，如 `Therapiddevelopmentofdeepfaketechnology`。

**根因**：`pdfplumber.extract_text()` 默认的字符间距容差在 IEEE 双栏论文中无法正确插入空格。pdfplumber 是纯 Python 实现，对某些字体编码的 PDF 处理不佳。

**解决方案**：
- 改用 **PyMuPDF (fitz)** 作为主文本提取引擎
- `page.get_text("text")` 基于字符位置智能插入空格，准确率远高于 pdfplumber
- pdfplumber 保留为表格提取备选

**验证**：
```powershell
docker exec literature-backend python -c "import fitz; doc=fitz.open('/app/data/uploads/xxx.pdf'); print(doc[0].get_text()[:200])"
```

---

### 1.2 公式误判（100条全是普通文本）

> 历史问题：本节记录的正则检测方案已废弃，公式检测已升级为「公式标号检测 + 区域裁剪 + 文本提取」方案，详见 1.6 节。

**现象**：公式标签显示 100 条，但内容全是普通文本片段（如论文标题、正文句子），被 `$...$` 包裹。

**根因**：公式检测正则 `[=+\-*/∑∫√≤≥≠]` 包含普通连字符 `-`。学术论文中几乎每行都有 `cross-domain`、`state-of-the-art` 等连字符词，导致全部匹配。

**解决方案**：
- 完全重写 `_extract_formulas_strict()`
- 数学符号集合**不含连字符**，只包含真正的数学符号（100+ 字符）
- 三重判定：LaTeX 命令命中 / 数学符号密度 ≥ 8% / 常见英文单词 ≤ 2 个
- 排除参考文献行、纯数字行、过短过长行

**关键代码**：
```python
_MATH_SYMBOLS = set("=+*/∑∫√≤≥≠×÷±∂∇∏∈∀∃∞...")  # 不含 -
_COMMON_WORDS = {"the", "and", "for", "method", "results", ...}
```

---

### 1.3 图表破损无法显示

**现象**：图表标签页显示破损图片图标，图注正常。

**根因（多层）**：
1. 后端 `_detect_figures` 只返回坐标 `{x0, top}`，没有提取图片数据
2. 前端读 `fig.url` 为 undefined
3. 即使提取了图片，nginx 没有代理 `/static/` 路径
4. nginx.conf 修改不生效（Docker build context 问题）

**解决方案**：
1. 用 PyMuPDF `doc.extract_image(xref)` 真正提取嵌入图片
2. 保存到 `/app/data/figures/` 卷，返回 `/static/figures/{doc_id}_{idx}.png`
3. FastAPI 挂载 `StaticFiles("/static/figures", directory=FIGURE_DIR)`
4. Nginx 添加 `/static/` 反向代理到 backend:8000
5. 同步 `frontend/nginx.conf`（Docker build context 是 ./frontend，COPY 的是这个文件）

**验证**：
```powershell
# 后端直接访问
docker exec literature-backend curl -I http://localhost:8000/static/figures/{filename}
# 通过 nginx 访问
docker exec literature-frontend curl -I http://localhost/static/figures/{filename}
```
两者都应返回 `HTTP/1.1 200 OK` 且 `Content-Type: image/*`。

---

### 1.4 参考文献 0 条

**现象**：参考文献标签显示 0 条。

**根因**：正则 `r"\n\s*(references|bibliography)\s*\n"` 要求严格的换行包围。文本提取后换行格式可能异常，导致匹配失败。

**解决方案**：三级降级匹配：
1. 严格行首：`^\s*(references|bibliography)\s*$`
2. 换行包围：`\n\s*(references|bibliography)\s*\n`
3. 宽松关键词：`\b(references|bibliography)\b`

条目切分支持 `[1]` 和 `1. ` 两种编号格式。

---

### 1.5 前端字段不匹配

**现象**：文本块显示 `[object Object]`，参考文献空白。

**根因**：前端读 `block.text` 但后端返回 `block.content`；前端读 `ref.text` 但后端返回 `ref.raw`。

**解决方案**：字段对齐，增加兜底链：
```javascript
{{ block.content || block.text || block }}
{{ ref.raw || ref.text || ref.title }}
```

---

### 1.6 文本块整页合并（只有 5 块而非 143 块）

**现象**：解析完成后文本块数量极少（一篇双栏论文只有 5 个块），整页内容被合并成一个大块，无法按段落浏览。

**根因**：旧方案按空行切分文本。IEEE 双栏论文中同栏段落之间通常没有空行，跨栏阅读顺序也错乱，导致几乎每页只切出 1-2 个块。

**解决方案**：重写切分逻辑，改用 PyMuPDF (`fitz`) 的 block 结构：
- 直接读取 `page.get_text("dict")` 返回的物理 block（每段/每行是一个 block）
- 按双栏排序：先判断页面栏数，左栏 block 排完再排右栏
- 实测：同一篇论文从 5 个文本块提升到 143 个文本块，段落边界正确

---

### 1.7 公式识别效果差 / 误判

**现象**：公式条目把普通正文当公式，或真正的公式识别不出来；逐页调 VL 模型成本高、速度慢。

**根因**：旧的「正则符号密度检测」误报率高，旧的「逐页 VL 识别」方案调用量大、不稳定，均已废弃。

**解决方案**：新方案为**公式标号检测 + 区域裁剪 + 文本提取**，`FORMULA_VL_ENABLED=false`（默认关闭）：
1. 用正则匹配行内公式标号（如 `(1)`、`(2.3)`）定位公式位置
2. 裁剪标号上方/旁边的公式区域
3. 用文本提取（而非 VL）取回公式文字
4. 公式原图保存为 200dpi PNG 到 `/app/data/figures/`，前端默认显示原图供人工对照

**实测效果**：一篇 IEEE 双栏 5 页论文共 12 个公式全部命中，其中 9/12 完全干净。已知限制：公式 (10-12) 开头可能缺少少量变量名（区域裁剪边界问题）。如确需更强识别，可将 `FORMULA_VL_ENABLED=true` 开启 VL 增强（会增加 API 调用量）。

---

## 2. 知识图谱问题

### 2.1 图谱构建成功但 0 节点

**现象**：点击构建知识图谱，返回成功，但节点数 0，关系数 0。

**根因（按概率排序）**：
1. **API Key 错误（401）**：`.env` 中 `QWEN_API_KEY` 是占位符 `your-dashscope-api-key`，或用 DeepSeek 的 Key 调用 DashScope 接口
2. **模型名错误**：`QWEN_TEXT_API_MODEL` 配置了不存在的模型
3. **base_url 错误**：用 DeepSeek 的 Key 但 base_url 指向 DashScope
4. **deepseek-v4-pro 返回空 content**：`deepseek-v4-pro` 对结构化 JSON 输出会返回空 content（非格式错误、非报错），解析后自然 0 节点。**这是实际踩过的坑，图谱抽取必须用 `deepseek-chat`**
5. **LLM 返回 JSON 格式错误**：解析失败返回空

**诊断命令**：
```powershell
docker logs literature-backend --tail 60 | Select-String "图谱抽取|实体抽取|ERROR|401|404"
```

**解决方案**：
- 确认 `.env` 中 `QWEN_API_BASE`、`QWEN_API_KEY`、`QWEN_TEXT_API_MODEL` 三者匹配
- DeepSeek 配置示例（文本模型必须是 `deepseek-chat`，不要用 `deepseek-v4-pro`）：
  ```env
  QWEN_API_BASE=https://api.deepseek.com
  QWEN_API_KEY=sk-真实key
  QWEN_TEXT_API_MODEL=deepseek-chat
  ```
- 代码已增强：抽取失败自动重试 1 次，日志打印 LLM 原始返回前 300 字符。如果日志里 LLM 返回 content 为空，基本就是 `deepseek-v4-pro` 问题，换 `deepseek-chat` 即可

---

### 2.2 删除图谱后刷新又出现

**现象**：点击删除图谱，列表消失，但刷新页面后又出现。

**根因**：删除 Cypher 查询的 Bug：
```cypher
-- 错误写法
MATCH (g:Graph {graph_id: $gid})-[:CONTAINS_NODE]->(n)
OPTIONAL MATCH (n)-[r]-()
DELETE r, n
WITH g
DETACH DELETE g
```
当图谱有 0 个节点时，第一个 `MATCH` 匹配为空，`WITH g` 不执行，`DETACH DELETE g` 被跳过，Graph 根节点残留。

**解决方案**：改用 `OPTIONAL MATCH`：
```cypher
MATCH (g:Graph {graph_id: $gid})
OPTIONAL MATCH (g)-[:CONTAINS_NODE]->(n)
DETACH DELETE n
WITH g
OPTIONAL MATCH (g)-[:CONTAINS_DOC]->(d)
DETACH DELETE d
WITH g
DETACH DELETE g
```

**清理已有残留**：
```powershell
docker exec literature-neo4j cypher-shell -u neo4j -p literature2024 "MATCH (g:Graph) WHERE NOT (g)-[:CONTAINS_NODE]->() DETACH DELETE g"
```

---

### 2.3 Neo4j 健康检查失败

**现象**：`docker-compose up` 时报 `dependency failed to start: container literature-neo4j is unhealthy`。

**根因**：
1. neo4j:5.16-community 镜像中**没有 curl，只有 wget**，健康检查命令写错（用了 curl 或 `wget -qO-` 读返回体）会一直失败
2. `start_period: 30s` 对首次初始化（建库 + 加载 apoc 插件）不够
3. 旧数据卷密码冲突

**解决方案**：使用 `wget -q -O /dev/null`（比 `--spider` 更可靠，HTTP 200 即成功），并放宽启动等待：
```yaml
healthcheck:
  test: ["CMD-SHELL", "wget -q -O /dev/null http://localhost:7474 || exit 1"]
  interval: 15s
  timeout: 10s
  retries: 15
  start_period: 90s
```

如果仍失败，清理数据卷重启：
```powershell
docker-compose down -v
docker-compose up -d
```

---

## 3. 部署与配置问题

### 3.1 nginx 配置修改不生效

**现象**：修改 `docker/nginx.conf` 后重新 build frontend，容器内配置仍是旧的。

**根因**：docker-compose.yml 中 frontend 的 build context 是 `./frontend`，Dockerfile 中 `COPY nginx.conf /etc/nginx/conf.d/default.conf` 实际复制的是 `frontend/nginx.conf`，而非 `docker/nginx.conf`。

**解决方案**：
- 保持 `frontend/nginx.conf` 和 `docker/nginx.conf` 同步
- 修改后必须同步到 frontend 目录
- 构建时加 `--no-cache` 确保不用旧缓存

```powershell
Copy-Item docker\nginx.conf frontend\nginx.conf -Force
docker-compose build --no-cache frontend
docker-compose up -d frontend
```

---

### 3.2 API 401 Unauthorized

**现象**：后端日志显示 `openai.AuthenticationError: Error code: 401 - Incorrect API key provided`。

**根因**：
1. API Key 是占位符或错误
2. API Key 与 base_url 不匹配（用 DeepSeek 的 Key 调用 DashScope）
3. API Key 对应的模型服务未开通

**解决方案**：
- 检查 `.env` 中 `QWEN_API_KEY` 是否为真实 Key
- 确认 `QWEN_API_BASE` 与 Key 来源一致
- DeepSeek Key → `https://api.deepseek.com`
- DashScope Key → `https://dashscope.aliyuncs.com/compatible-mode/v1`

---

### 3.3 容器启动后立即退出

**现象**：`docker-compose ps` 显示容器状态为 `Exited`。

**诊断**：
```powershell
docker logs literature-backend --tail 30
docker logs literature-neo4j --tail 30
```

**常见原因**：
1. **后端**：依赖缺失（requirements.txt 未安装全）、端口被占用、配置错误
2. **Neo4j**：内存不足（heap 2G + pagecache 1G = 3G）、数据卷权限问题
3. **前端**：nginx 配置语法错误

**解决方案**：
- 后端：`docker exec literature-backend pip list` 检查依赖
- Neo4j：降低内存配置 `NEO4J_dbms_memory_heap_max__size=1G`
- 前端：`docker exec literature-frontend nginx -t` 检查配置语法

---

### 3.4 502 Bad Gateway

**现象**：访问前端页面正常，但页面内的 API 请求返回 `502 Bad Gateway`。

**根因**：nginx（frontend 容器）反向代理到 `backend:8000` 失败，通常是 backend 未启动、健康检查未通过或还在启动中。

**排查步骤**：
```powershell
# 1. 看 backend 容器状态
docker-compose ps backend
# 2. 看 backend 日志（是否启动完成 / 报错退出）
docker logs literature-backend --tail 50
# 3. backend 刚启动时模型下载/初始化较慢，健康检查 start_period=20s，稍等片刻
# 4. 确认 nginx.conf 中代理目标是 backend:8000（不是 localhost）
```

**解决方案**：等 backend healthy 后刷新；若 backend 反复退出，按 3.3 节排查后端日志。

---

### 3.5 向量模型下载慢 / 失败

**现象**：首次启动 backend 或 celery-worker 时卡在模型加载，日志反复出现 HuggingFace 下载相关报错。

**根因**：默认从 huggingface.co 下载 BGE-M3 / bge-reranker-v2-m3，国内网络不通或极慢。

**解决方案**：
- 确认 `.env` 中配置了 `HF_ENDPOINT=https://hf-mirror.com`（docker-compose 已内置默认值）
- 确认 `backend_models` 卷已挂载到 `/models`，下载产物会缓存其中
- 首次下载约 2GB，耗时较长属正常现象，耐心等待；下载失败重跑 `docker-compose restart backend celery-worker` 会续传/重下

---

### 3.6 WSL / Docker Desktop 相关错误

**现象**：`docker-compose up` 报 WSL2 后端相关错误，或容器状态异常、无法启动。

**解决方案**：
1. 重启 Docker Desktop
2. 如仍异常，在 PowerShell 执行 `wsl --shutdown` 后重新启动 Docker Desktop
3. 确认 WSL2 后端已启用、磁盘空间充足

---

### 3.7 Celery worker 不消费任务（任务一直 PENDING）

**现象**：上传文献后解析任务一直排队，进度不动，celery-worker 日志没有任务输出。

**根因（按概率排序）**：
1. **Redis 密码不一致**：backend 投递任务用的 `REDIS_PASSWORD` 与 worker / redis 服务实际密码不一致，消息进了队列但 worker 连不上
2. **worker 还在启动中**：worker 首次启动要下载向量模型，`inspect ping` 未 healthy 前不消费
3. **任务未注册**：worker 启动命令未加载到任务模块

**排查命令**：
```powershell
# worker 状态与日志
docker-compose ps celery-worker
docker logs literature-celery-worker --tail 50

# Redis 状态（密码见 .env，默认 literature_redis_2024）
docker exec -it literature-redis redis-cli -a literature_redis_2024 ping
docker exec -it literature-redis redis-cli -a literature_redis_2024 LLEN celery

# 检查 worker 注册的任务
docker exec literature-celery-worker celery -A app.core.celery_app.celery_app inspect registered
```

**解决方案**：统一 `.env` 中 `REDIS_PASSWORD` 后 `docker-compose restart backend celery-worker redis`；等待 worker healthy。

---

## 4. 性能问题

### 4.1 文献解析慢

**可能原因**：
1. LLM 结构化摘要调用耗时（deepseek-chat 视网络而定）
2. PDF 页数多，文本提取耗时
3. 网络延迟（API 调用）

**优化**：
- 结构化摘要可配置跳过（解析选项中关闭）
- 文本提取是本地操作，通常 < 2 秒/10 页
- LLM 调用通常 5-15 秒，取决于模型和网络

### 4.2 图谱构建慢

**可能原因**：
- LLM 抽取 8000 字符文本，deepseek-chat 逐段推理
- 每篇文献一次 LLM 调用

**优化**：
- 减少 `excerpt` 长度（当前 8000 字符）
- 注意：抽取模型必须用 `deepseek-chat`（`deepseek-v4-pro` 返回空 content）

### 4.3 首次启动慢

**现象**：第一次 `docker-compose up` 后 backend / celery-worker 长时间不 healthy。

**原因**：BGE-M3（embedding）和 bge-reranker-v2-m3（rerank）两个模型共约 2GB，首次启动自动从 hf-mirror.com 下载并缓存到 `backend_models` 卷。

**说明**：这是正常现象，下载完成后后续启动不再重复下载。如长时间无进展，按 3.5 节检查 `HF_ENDPOINT` 配置。

---

## 5. 诊断命令速查

```powershell
# 查看所有服务状态
docker-compose ps

# 查看后端日志（最后60行，过滤关键词）
docker logs literature-backend --tail 60 | Select-String "ERROR|WARNING|图谱抽取|实体抽取"

# 查看 celery-worker 日志（异步解析任务）
docker logs literature-celery-worker --tail 60

# 查看 Neo4j 日志
docker logs literature-neo4j --tail 30

# Redis 状态检查（密码见 .env，默认 literature_redis_2024）
docker exec -it literature-redis redis-cli -a literature_redis_2024 ping
docker exec -it literature-redis redis-cli -a literature_redis_2024 LLEN celery

# 测试后端 API
curl http://localhost:8000/health
curl http://localhost:8000/docs

# 测试静态文件
docker exec literature-backend curl -I http://localhost:8000/static/figures/

# 进入 Neo4j 查询
docker exec -it literature-neo4j cypher-shell -u neo4j -p literature2024

# 查看图谱节点数
docker exec literature-neo4j cypher-shell -u neo4j -p literature2024 "MATCH (n) RETURN labels(n)[0] as type, count(n) as cnt"

# 重新构建服务
docker-compose build --no-cache backend
docker-compose up -d backend
```
