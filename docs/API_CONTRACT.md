# 多模态文献精读与知识图谱助手 - API 契约规范
# 前后端必须严格遵循此文件定义的端点、请求/响应格式

Base URL: http://localhost:8000/api/v1

## 1. 文献上传与解析
### POST /upload
- 异步接口：上传后立即返回 task_id，解析由 Celery 在后台执行，不阻塞返回
- 请求: multipart/form-data
  - file: 文件 (PDF/PNG/JPG, 必填)
  - parse_formula: bool (默认 true)
  - parse_figures: bool (默认 true)
  - parse_references: bool (默认 true)
- 响应 200（受理成功，不等于解析完成）:
```json
{
  "task_id": "celery-task-uuid",
  "document_id": "uuid-string",
  "filename": "paper.pdf",
  "status": "parsing"
}
```

### GET /task/{task_id}
- 查询异步解析任务状态，前端每 2s 轮询一次直到 SUCCESS/FAILURE
- 响应 200:
```json
{
  "task_id": "celery-task-uuid",
  "status": "PENDING|PROCESSING|SUCCESS|FAILURE",
  "progress": 50,
  "current_step": "formula_recognition",
  "result": { "document_id": "uuid-string" },
  "error": null
}
```
- status：PENDING（排队）/ PROCESSING（解析中）/ SUCCESS（成功）/ FAILURE（失败）
- progress：0-100 整数
- current_step 当前 6 级步骤及对应进度：
  - upload_complete (10%) → text_extraction (30%) → formula_recognition (50%)
    → figure_extraction (70%) → references (85%) → summary_generation (100%)
- result：仅 SUCCESS 时返回，内含 document_id；error：仅 FAILURE 时返回错误信息

### GET /documents
- 响应 200:
```json
{
  "documents": [
    {"document_id": "uuid", "filename": "paper.pdf", "title": "...", "uploaded_at": "...", "status": "completed"}
  ],
  "total": 1
}
```

### GET /documents/{document_id}
- 响应 200: 文档完整解析结果，含 text_blocks, formulas, figures, tables, references, structured_summary
- text_blocks：基于 fitz block 结构切分（双栏排序），展示字段 `block.content`
- formulas 每条含：
  ```json
  {
    "page": 3,
    "latex": "提取出的公式文本",
    "image_url": "/static/figures/{doc_id}_0.png",
    "formula_number": "1",
    "detect_reason": "text",
    "original": "..."
  }
  ```
  （前端默认展示 image_url 原图，点击展开红色 LaTeX）

### DELETE /documents/{document_id}
- 响应 200: {"deleted": true}

## 2. 深度问答 (RAG)
### POST /qa/ask
- 请求:
```json
{
  "question": "对比两篇文献的方法差异",
  "document_ids": ["uuid1", "uuid2"],
  "mode": "hybrid",
  "top_k": 5,
  "include_citations": true
}
```
- mode: "summary" (摘要检索) | "fulltext" (全文细查) | "hybrid" (分层策略)
- 响应 200:
```json
{
  "answer": "详细回答文本...",
  "sources": [
    {
      "document_id": "uuid",
      "filename": "paper.pdf",
      "chunk_id": "chunk-12",
      "text": "引用片段",
      "page": 3,
      "score": 0.92,
      "retrieval_layer": "summary|fulltext"
    }
  ],
  "retrieval_info": {
    "mode": "hybrid",
    "summary_hits": 3,
    "fulltext_hits": 5,
    "reranked": true,
    "latency_ms": 1250
  }
}
```

### POST /qa/compare
- 请求:
```json
{
  "document_ids": ["uuid1", "uuid2"],
  "dimension": "method|dataset|metric|conclusion"
}
```
- 响应 200:
```json
{
  "comparison": {
    "dimension": "method",
    "items": [
      {"document_id": "uuid1", "title": "论文A", "content": "方法描述"},
      {"document_id": "uuid2", "title": "论文B", "content": "方法描述"}
    ],
    "differences": ["差异点1", "差异点2"],
    "similarities": ["相似点1"]
  }
}
```

## 3. 知识图谱
### POST /graph/build
- 请求:
```json
{
  "document_ids": ["uuid1", "uuid2"],
  "entity_types": ["concept", "algorithm", "dataset", "metric", "conclusion"],
  "relation_types": ["uses", "compares", "improves", "evaluates_on", "achieves"]
}
```
- 响应 200:
```json
{
  "graph_id": "graph-uuid",
  "status": "building|completed",
  "stats": {"nodes": 45, "relationships": 78}
}
```

### GET /graph/list
- 响应 200: {"graphs": [{"graph_id": "...", "name": "...", "created_at": "...", "node_count": 45}]}

### GET /graph/{graph_id}
- 查询参数: limit=200, node_type=optional
- 响应 200:
```json
{
  "graph_id": "graph-uuid",
  "nodes": [
    {"id": "n1", "label": "BERT", "type": "algorithm", "properties": {"description": "..."}}
  ],
  "links": [
    {"source": "n1", "target": "n2", "type": "improves", "properties": {}}
  ],
  "stats": {"nodes": 45, "relationships": 78}
}
```

### DELETE /graph/{graph_id}
- 响应 200: {"deleted": true}

## 4. 综述生成
### POST /review/generate
- 请求:
```json
{
  "document_ids": ["uuid1", "uuid2", "uuid3"],
  "topic": "多模态大模型研究综述",
  "sections": ["background", "methods", "datasets", "challenges", "future"]
}
```
- 响应 200:
```json
{
  "review_id": "review-uuid",
  "title": "多模态大模型研究综述",
  "outline": [
    {"section": "1. 研究背景", "key_points": ["..."]},
    {"section": "2. 方法分类", "key_points": ["..."]}
  ],
  "core_views": [
    {"view": "核心观点", "supporting_docs": ["uuid1"], "evidence": "引用"}
  ],
  "research_gaps": [
    {"gap": "研究缺口描述", "severity": "high|medium|low", "suggested_direction": "建议方向"}
  ],
  "evolution_timeline": [
    {"year": "2020", "event": "里程碑事件", "document_id": "uuid1"}
  ]
}
```

### GET /review/{review_id}
- 响应 200: 完整综述内容

## 5. 系统状态
### GET /health
- 注意：该端点挂载在根路径，不在 `/api/v1` 前缀下，即 `http://localhost:8000/health`
- 响应 200:
```json
{
  "status": "healthy",
  "components": {
    "neo4j": "connected",
    "vector_store": "ready",
    "model": "deepseek-chat/api",
    "embedding": "bge-m3"
  }
}
```

## 6. 静态资源
### GET /static/figures/{filename}
- 访问后端保存的公式原图与图表 PNG（挂载在根路径，经 Nginx `/static/` 代理到 backend）
- 公式原图：解析时按 200dpi 渲染公式裁剪区域保存到 `/app/data/figures/`，文件名形如 `{doc_id}_{index}.png`
- 文档详情中 `formulas[].image_url` 与 `figures[].image_url` 直接指向该路径
