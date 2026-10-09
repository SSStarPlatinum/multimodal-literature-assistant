# 后端实现细节

## 1. 应用入口 (main.py)

### 1.1 启动流程

```python
# 1. 初始化 FastAPI 应用
app = FastAPI(title="...", version="1.0.0")

# 2. 配置 CORS（允许前端跨域）
app.add_middleware(CORSMiddleware, allow_origins=[...])

# 3. 注册全局异常处理器
# AppException -> 统一 JSON 错误响应
# Exception -> 500 兜底

# 4. 注册业务路由（前缀 /api/v1）
app.include_router(api_router, prefix="/api/v1")

# 5. 挂载静态文件（提取的图表图片）
app.mount("/static/figures", StaticFiles(directory=FIGURE_DIR), name="figures")

# 6. 健康检查端点
@app.get("/health")
```

### 1.2 静态文件挂载

图表图片通过 FastAPI `StaticFiles` 暴露：
- 挂载路径：`/static/figures`
- 物理路径：`/app/data/figures`（docker volume `backend_figures`）
- 前端通过 `fig.url` 字段访问，URL 格式：`/static/figures/{doc_id}_{index}.{ext}`

**关键设计决策**：StaticFiles 挂载必须在 `include_router` 之后，否则路由匹配优先级可能导致冲突。

## 2. 配置管理 (app/core/config.py)

使用 `pydantic-settings` 的 `BaseSettings`，从环境变量和 `.env` 文件读取配置。

### 2.1 关键特性

- **大小写不敏感**：环境变量名与字段名大小写不敏感映射
- **计算属性**：`cors_origins_list`、`allowed_ext_list`、`use_local_model`
- **HF 镜像预设置**：在 `get_settings()` 中提前设置 `HF_ENDPOINT` 环境变量，确保 transformers 加载模型时走镜像

### 2.2 配置分类

| 分类 | 配置项 |
|------|--------|
| 应用 | APP_HOST, APP_PORT, APP_ENV, LOG_LEVEL, API_PREFIX |
| 模型 | MODEL_MODE, QWEN_*, VISION_ENABLED, LLM_TEMPERATURE, LLM_MAX_TOKENS |
| 量化 | ENABLE_4BIT_QUANTIZATION, LOAD_IN_4BIT, BNB_4BIT_* |
| 嵌入 | EMBEDDING_MODEL_NAME, EMBEDDING_DEVICE, EMBEDDING_BATCH_SIZE |
| 向量库 | VECTOR_STORE_TYPE, VECTOR_STORE_PATH, CHUNK_SIZE, CHUNK_OVERLAP |
| RAG | RAG_TOP_K, RAG_SUMMARY_TOP_K, RAG_FULLTEXT_TOP_K, RAG_ENABLE_RERANK |
| Neo4j | NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE |
| 文件 | UPLOAD_DIR, FIGURE_DIR, STATIC_URL_PREFIX, MAX_UPLOAD_SIZE |

## 3. 文献解析服务 (ParserService)

### 3.1 文本提取引擎选型

**为什么用 PyMuPDF 而不是 pdfplumber？**

| 维度 | PyMuPDF (fitz) | pdfplumber |
|------|----------------|------------|
| 文本空格准确率 | 高（基于字符间距智能插入） | 低（IEEE 双栏论文常丢失空格） |
| 嵌入图片提取 | 原生支持 `doc.extract_image(xref)` | 仅返回坐标，不提取图片数据 |
| 页面渲染 | 支持 `page.get_pixmap()` | 不支持 |
| 表格提取 | 有限（需额外配置） | 强（`page.extract_tables()`） |
| 性能 | 快（C 扩展） | 较慢（纯 Python） |

**决策**：PyMuPDF 作为主引擎（文本+图片），pdfplumber 作为表格提取备选。

### 3.2 文本块切分算法

**旧方案（已废弃）**：对整页 `page_text` 按空行切分段落。IEEE 双栏论文两栏连续排版、栏间几乎没有空行，导致整页被合并为 1 个文本块——一篇 5 页论文只能切出 5 个文本块，语义粒度过粗，RAG 细查基本失效。

**新方案**：直接使用 PyMuPDF `page.get_text("blocks")` 返回的 block 结构（每个 block 自带 bbox 坐标），在坐标层面完成双栏排序与过滤，不再依赖空行：

```python
def _split_blocks(page, page_no):
    blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)
    # 1. 按 x0 划分栏位：x0 < 页面宽度 * 0.5 -> 左栏，否则右栏
    left  = [b for b in blocks if b[0] < page.rect.width * 0.5]
    right = [b for b in blocks if b[0] >= page.rect.width * 0.5]
    # 2. 每栏内按 y0 排序，再左栏接右栏，还原自然阅读顺序
    blocks = sorted(left, key=lambda b: b[1]) + sorted(right, key=lambda b: b[1])
    # 3. 过滤页眉/页码：剔除页面顶部/底部的短文本行
    ...
```

**设计要点**：
- 栏位阈值为页面宽度的 0.5（页面中点），与公式栏位判断使用同一阈值
- 双栏排序：左栏 block 按 y 排序后接右栏 block，避免左右栏内容交错
- 过滤页面顶部/底部短文本行，去掉页眉、页码
- 连字符换行仍按规则拼接（`cross-\ndomain` → `crossdomain`，否则加空格）

**测试结果**：同一篇 IEEE 双栏 5 页论文，文本块数量从旧方案的 5 个提升到 **143 个**，语义粒度满足 RAG 细查需求。

### 3.3 公式识别算法（标号定位 + 区域裁剪）

**旧方案（已废弃）**：VL 识别公式 + 正则严格检测（数学符号密度 / LaTeX 命令关键词三重判定）。问题：VL 识别公式容易出错且有成本；正则又因连字符 `-` 导致普通英文行（cross-domain、state-of-the-art）误命中，早期 100 条"公式"几乎全是正文。

**新方案核心逻辑**（基于 PyMuPDF block 坐标，纯文本 + 几何，零 VL 成本）：

```
1. 识别公式标号行：检测形如 (1)、(2)、(2.3) 的标号
2. 确定栏位：根据标号 x 坐标判断左栏/右栏（阈值 0.5，即页面中点）
3. 裁剪公式区域：从标号行到下一个标号行/正文行之间的区域
4. 从区域文本过滤正文行：去掉不含数学符号的普通文本行
5. 从第一个含等号(=)的行开始保留：去掉标号上方的正文
6. 去掉末尾正文片段：公式结束后可能混入的正文
```

**公式原图保存**：每个公式区域用 fitz 渲染为 200dpi PNG，保存到 `/app/data/figures/`（`backend_figures` 卷），公式条目含 `image_url` 字段，前端通过 `/static/figures/...` 访问。

**VL 默认关闭**：`FORMULA_VL_ENABLED=false`。VL 识别公式容易出错，基于标号定位 + 文本提取的方案更稳定且零成本；确需 VL 时可用 `FORMULA_VL_MAX_PER_PAGE` 限制每页处理数量。

**测试结果**：IEEE 双栏 5 页论文，12 个公式全部命中，其中 9/12 提取文本完全干净。

**已知限制**：公式 (10)-(12) 这类二维布局公式，左半部分可能丢失，开头缺少少量变量名。

### 3.4 图表提取

```python
def _extract_figures_fitz(doc, doc_id):
    seen_xrefs = set()  # 去重：同一图片可能被多页引用
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen_xrefs:
                continue
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            if len(image_bytes) < 2048:  # 过滤 <2KB 的装饰性元素
                continue
            url = save_figure_image(doc_id, idx, image_bytes, ext)
            caption = _find_figure_caption(page, img_info)  # 正则查找 Fig. X
```

**图注提取**：正则 `(?:Fig\.?|Figure|图)\s*\d+[:：.\s]+[^\n]{5,150}` 在页面文本中查找。

### 3.5 参考文献提取

**三级降级匹配定位 References 区段**：
1. 严格行首匹配：`^\s*(references|bibliography)\s*$`
2. 换行包围：`\n\s*(references|bibliography)\s*\n`
3. 宽松关键词：`\b(references|bibliography)\b`

**条目切分**：按 `[1]` 或 `1. ` 编号切分，提取编号、年份、标题。测试一篇论文可定位 35 条参考文献。

### 3.6 异步执行与进度上报

`ParserService.parse_file()` 本身为同步函数，由 Celery 任务 `app/tasks/parse_task.py::parse_document_task` 封装为异步任务：

- 上传接口 `POST /upload` 只负责校验、落盘并 `.delay()` 提交任务，立即返回 `task_id`，不阻塞 HTTP 响应。
- Worker 执行时通过回调 `on_progress(step, progress, message)` 调用 `self.update_state(state="PROCESSING", meta={...})`，进度写入 Redis result backend（db1）。
- 前端轮询 `GET /task/{task_id}` 读取进度与状态。

**6 级进度**：

| step | 进度 | 含义 |
|------|------|------|
| upload_complete | 10% | 文件上传完成，开始解析 |
| text_extraction | 30% | 文本块提取完成 |
| formula_recognition | 50% | 公式识别完成 |
| figure_extraction | 70% | 图表提取完成 |
| references | 85% | 参考文献提取完成 |
| summary_generation | 100% | 结构化摘要生成完成（任务结束） |

任务成功后更新文档索引为 `completed`，并在 Worker 内完成 `VectorService.index_document()` 向量化；解析异常会被 Celery 标记为 FAILURE，文档索引置为 `failed`。

## 4. 模型加载器 (ModelLoader)

### 4.1 单例与懒加载

- 全局单例 `model_loader`
- VL 模型、嵌入模型、reranker 均懒加载（首次调用时初始化）
- 线程安全（`threading.Lock` 双重检查锁定）

### 4.2 API 模式文本生成

```python
def _chat_text_api(self, system_prompt, user_prompt):
    client = OpenAI(base_url=settings.QWEN_API_BASE, api_key=settings.QWEN_API_KEY)
    resp = client.chat.completions.create(
        model=settings.QWEN_TEXT_API_MODEL,  # deepseek-chat / qwen-plus
        messages=[{"role": "system", "content": system_prompt},
                  {"role": "user", "content": user_prompt}],
        temperature=0.2, max_tokens=2048,
    )
    return resp.choices[0].message.content
```

**模型选择注意**：文本生成当前使用 `deepseek-chat`。`deepseek-v4-pro` 对结构化 JSON 输出会返回空 content（图谱抽取依赖严格 JSON），因此不可用于图谱抽取等需要结构化输出的场景。

### 4.3 API 模式视觉生成

```python
def _chat_image_api(self, prompt, image_bytes):
    data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
    resp = client.chat.completions.create(
        model=settings.QWEN_API_MODEL,  # deepseek-flash / qwen2.5-vl-7b
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]}],
    )
```

**DeepSeek 兼容性**：DeepSeek Flash 支持 OpenAI 兼容的 `image_url` 格式，无需特殊处理。

### 4.4 local 模式 4-bit 量化

```python
quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4",       # Normalized Float，比 fp4 精度更好
    bnb_4bit_use_double_quant=True,  # 嵌套量化：量化常数本身也被量化
)
model = VLModel.from_pretrained(
    model_path, quantization_config=quant_config,
    device_map="auto", trust_remote_code=True,
)
```

## 5. 向量服务 (VectorService)

### 5.1 双集合设计

| 集合名 | 内容 | 用途 |
|--------|------|------|
| literature_summary（summary collection） | 每篇文献的结构化摘要（purpose/methods/data/conclusion），每篇 1 条 | RAG 第一层粗检索 |
| literature_chunks（fulltext collection） | 全文按 block 切分后再按 512 token 切分的 chunk，每篇约 143 个 | RAG 第二层细查 |

### 5.2 向量化流程

```
文档解析完成（在 Celery Worker 内）
  → 结构化摘要 -> 拼接为文本 -> BGE-M3 嵌入 -> 写入 summary 集合
  → text_blocks（带页码/段落序号/字符偏移）-> 按 512 token 切分（重叠 50）
    -> BGE-M3 嵌入 -> 写入 fulltext 集合（chunk 主键 {doc_id}_{chunk_id}）
```

### 5.3 模型自动下载与共享卷

- **BGE-M3 嵌入模型**：本地路径 `/models/bge-m3` 不存在时，自动从 HuggingFace 镜像 `https://hf-mirror.com`（`HF_ENDPOINT`）下载，下载后缓存到卷内，后续直接加载。
- **bge-reranker-v2-m3 重排序模型**：同样在 `/models` 缺失时经 hf-mirror 自动下载。
- **共享卷**：Docker 卷 `backend_models` 挂载到 `/models`，由 backend 与 celery-worker 共享，避免两个容器重复下载同一模型。

## 6. RAG 服务 (RAGService)

### 6.1 三层检索策略

```
用户问题
  │
  ├─ 第一层：摘要检索（top_k=3）
  │   └── 在 summary 集合中检索，确定相关文献集合
  │
  ├─ 第二层：全文细查（top_k=8）
  │   └── 仅在第一层命中的文献内检索 fulltext chunks
  │   └── 避免全库扫描，提升效率和准确率
  │
  └─ 第三层：重排序（top_n=5）
      └── bge-reranker-v2-m3 CrossEncoder 对 (query, chunk) 对打分
      └── 取 top 5 作为最终上下文
```

**为什么分层？** 长文献全文检索容易引入噪声片段，先用摘要确定相关文献，再在小范围内细查，准确率更高。

### 6.2 回答生成

```python
prompt = QA_USER_TEMPLATE.format(
    question=question,
    context="\n---\n".join([f"[{i+1}] {chunk}" for i, chunk in enumerate(top_chunks)])
)
answer = model_loader.chat_text(QA_SYSTEM, prompt)
# 系统提示要求：答案必须基于片段，用 [n] 标注引用
```

## 7. 知识图谱服务 (GraphService)

### 7.1 节点与关系 Schema

**5 类节点**：
| 类型 | 标签 | 说明 |
|------|------|------|
| concept | Concept | 概念、术语、理论、问题定义 |
| algorithm | Algorithm | 算法、模型、方法、框架 |
| dataset | Dataset | 数据集、基准测试 |
| metric | Metric | 评估指标、性能指标 |
| conclusion | Conclusion | 实验结论、发现、贡献 |

**6 类关系**：
| 关系 | 方向 | 说明 |
|------|------|------|
| USES | Algorithm -> Concept | 算法使用了某概念 |
| IMPROVES | Algorithm -> Algorithm | 算法改进了另一算法 |
| EVALUATES_ON | Algorithm -> Dataset | 算法在某数据集上评估 |
| ACHIEVES | Algorithm -> Metric | 算法达到了某指标 |
| COMPARES_WITH | Algorithm -> Algorithm | 算法与另一算法对比 |
| PROPOSED_BY | Node -> Document | 实体由该文献提出 |

### 7.2 实体抽取 Prompt 设计

**系统提示词**包含：
- 5 类节点的明确定义（什么是 concept，什么是 algorithm）
- 6 类关系的定义和方向
- 6 条输出要求（必须 JSON、必须含字段、source/target 必须已定义、宁缺毋滥、3-15 个节点）

**用户提示词**包含：
- 论文标题和正文节选（8000 字符）
- 完整的 JSON 输出示例（5 节点 + 3 关系）
- 明确要求"只输出 JSON，不要其他内容"

### 7.3 JSON 鲁棒解析

LLM 输出的 JSON 可能有各种格式问题，`_safe_json` 四级降级：
1. 直接 `json.loads`
2. 截取第一个 `{` 到最后一个 `}`
3. 逐段扫描，取第一个含 `nodes` 字段的合法 JSON
4. 修复尾逗号（`,}` -> `}`，`,]` -> `]`）后重试

### 7.4 中文类型容错

LLM 可能返回中文类型名，映射表：
```python
CHINESE_TYPE_TO_EN = {
    "概念": "concept", "算法": "algorithm", "模型": "algorithm",
    "方法": "algorithm", "数据集": "dataset", "数据": "dataset",
    "指标": "metric", "评估指标": "metric",
    "结论": "conclusion", "实验结论": "conclusion",
}
```

未知类型降级为 `concept`（而非直接跳过），确保节点不丢失。

### 7.5 Cypher 写入

```cypher
-- 节点写入（MERGE 幂等）
MATCH (g:Graph {graph_id: $gid})
MERGE (n:Concept {name: $name, source_document: $did})
SET n.description = $desc, n.page_number = $page, n.type = $ntype
MERGE (g)-[:CONTAINS_NODE]->(n)
RETURN elementId(n) AS eid

-- 关系写入
MATCH (a), (b) WHERE elementId(a) = $src_id AND elementId(b) = $tgt_id
MERGE (a)-[r:USES]->(b)
SET r.source_document = $did
```

**为什么用 elementId 而不是 name？** 不同文献可能有同名节点，elementId 是全局唯一的。

### 7.6 删除图谱（关键 Bug 修复）

**初始 Bug**：`MATCH (g)-[:CONTAINS_NODE]->(n)` 在 0 节点图谱时匹配为空，`WITH g` 不执行，`DETACH DELETE g` 被跳过，Graph 根节点残留。

**修复后**：
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

用 `OPTIONAL MATCH` 确保无论有没有子节点都能执行到最终删除。

## 8. 综述服务 (ReviewService)

两阶段生成：
1. **大纲生成**：LLM 根据文献摘要生成综述章节大纲（JSON 数组）
2. **观点汇总**：LLM 汇总核心观点、研究缺口、发展时间线（JSON 对象）

## 9. 路由层

### 9.1 路由分组

所有路由统一挂载在 `/api/v1` 前缀下。

| 分组 | 端点 | 说明 |
|------|------|------|
| 文档/任务 | POST /upload | 上传文献并提交异步解析任务，返回 task_id |
| | GET /task/{task_id} | 查询异步解析任务状态与进度（6 级进度） |
| | GET /documents | 列出全部文档 |
| | GET /documents/search | 按关键词/标签搜索文档 |
| | GET /documents/{doc_id} | 获取文档完整解析结果 |
| | DELETE /documents/{doc_id} | 删除文档（文件+解析结果+向量索引） |
| | PUT /documents/{doc_id}/tags | 更新文档标签 |
| | POST /documents/batch/build-graph | 批量选择文档构建图谱 |
| | DELETE /documents/batch | 批量删除文档 |
| 问答 | POST /qa/ask | 分层 RAG 问答 |
| | POST /qa/compare | 按维度对比多篇文献 |
| | GET /document/{doc_id}/chunk/{chunk_id} | 查询单 chunk 详情（引用溯源定位原文） |
| 图谱 | POST /graph/build | 构建图谱 |
| | GET /graph/list | 图谱列表 |
| | GET /graph/{graph_id} | 查询图谱详情 |
| | DELETE /graph/{graph_id} | 删除图谱（OPTIONAL MATCH 分步删除） |
| | POST /graph/{graph_id}/node、PUT/DELETE /graph/{graph_id}/node/{node_id} | 节点增改删 |
| | POST /graph/{graph_id}/edge | 新增关系 |
| | GET /graph/{graph_id}/logs | 图谱操作日志 |
| 综述 | POST /review/generate | 生成综述 |
| | GET /review/{review_id} | 查询综述结果 |
| | GET /review/{review_id}/export | 导出综述 |

> 注：早期设计中的 `POST /review/outline`、`POST /review/views` 两阶段端点未实现，实际为 `POST /review/generate` 一次性生成。

### 9.2 统一响应格式

所有端点使用 Pydantic response_model 确保输出格式一致，异常通过 `AppException` 统一处理。
