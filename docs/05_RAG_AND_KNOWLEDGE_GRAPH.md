# RAG 与知识图谱核心设计

## 1. RAG 分层检索架构

### 1.1 设计动机

传统 RAG 直接对全文 chunk 做向量检索，存在两个问题：
1. **噪声引入**：长文献中大量无关片段被检索到，稀释上下文
2. **效率低下**：全库扫描，文献越多越慢

本项目采用「摘要检索 + 全文细查」分层策略。

### 1.2 三层检索流程

```
┌─────────────────────────────────────────────────────┐
│  用户问题: "本文提出的方法在哪个数据集上达到了多少AUC?" │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  第一层：摘要检索（RAG_SUMMARY_TOP_K=3）              │
│  集合：literature_summary                            │
│  内容：每篇文献的结构化摘要（purpose/methods/...）    │
│  输出：相关文献 ID 集合 {doc_A, doc_B, doc_C}         │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  第二层：全文细查（RAG_FULLTEXT_TOP_K=8）             │
│  集合：literature_chunks                             │
│  过滤：仅在 {doc_A, doc_B, doc_C} 文献内检索          │
│  输出：8 个最相关的全文 chunk                         │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  第三层：重排序（RERANK_TOP_N=5）                     │
│  模型：bge-reranker-v2-m3 (CrossEncoder)             │
│  输入：(query, chunk) 对                             │
│  输出：top 5 最相关片段                               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  LLM 生成回答                                        │
│  系统提示：答案必须基于片段，用 [n] 标注引用           │
│  输出：回答 + 来源片段                                │
└─────────────────────────────────────────────────────┘
```

### 1.3 嵌入模型 BGE-M3

- **维度**：1024 维稠密向量
- **特点**：支持多语言（中英）、长文本（最大 8192 token）、稠密+稀疏+多向量统一
- **设备**：默认 CPU，可配置 CUDA 加速
- **批量**：EMBEDDING_BATCH_SIZE=32
- **自动下载**：本地 `/models/bge-m3` 不存在时，启动阶段自动从 hf-mirror（`https://hf-mirror.com`）下载并缓存到 `/models/bge-m3`，无需人工预置
- **卷挂载**：`backend_models` 卷挂载到容器 `/models`，`backend` 与 `celery-worker` 共享同一份模型缓存，避免重复下载

### 1.4 重排序模型 bge-reranker-v2-m3

- **类型**：CrossEncoder（对 query-doc 对联合编码，比双编码器更精准）
- **作用**：修正向量检索的语义偏差，提升 top-k 准确率
- **设备**：默认 CPU
- **自动下载**：与 BGE-M3 一致，本地 `/models/bge-reranker-v2-m3` 缺失时自动从 hf-mirror 下载，缓存到 `/models`，由 `backend_models` 卷在 backend 与 celery-worker 间共享

### 1.5 Chunk 策略

| 参数 | 值 | 说明 |
|------|-----|------|
| CHUNK_SIZE | 512 | 每个 chunk 的 token 数 |
| CHUNK_OVERLAP | 50 | 相邻 chunk 重叠 token 数，避免语义断裂 |

向量库为 ChromaDB，分两个 collection：
- `summary` collection：每篇文献一条结构化摘要向量（粗筛相关文献）
- `fulltext` collection：正文切块向量（细查引用片段）。文本块基于 fitz block 结构切分后，每篇约产出 143 个 chunk（以 5 页 IEEE 双栏论文实测为准），即 fulltext collection 平均每篇约 143 条

## 2. 知识图谱构建

### 2.1 图谱数据模型

```
Graph (图谱根节点)
  │
  ├── CONTAINS_DOC ──> Document (文献节点)
  │                     │
  └── CONTAINS_NODE ──> Concept / Algorithm / Dataset / Metric / Conclusion
                        │
                        └── PROPOSED_BY ──> Document
                        └── USES / IMPROVES / EVALUATES_ON / ACHIEVES / COMPARES_WITH
```

### 2.2 实体抽取 Prompt 工程

#### 系统提示词设计要点

1. **角色定义**："你是一名知识图谱构建专家"
2. **类型约束**：明确列出 5 类节点和 6 类关系的定义和方向
3. **输出格式**：必须只输出 JSON，不要解释、不要 Markdown 代码块
4. **质量要求**：只抽取明确出现的实体，宁缺毋滥；3-15 个节点

#### 用户提示词设计要点

1. **上下文**：论文标题 + 正文节选（8000 字符）
2. **示例引导**：提供完整的 JSON 输出示例（5 节点 + 3 关系），降低 LLM 格式偏差
3. **明确指令**："现在请根据上方论文正文，输出你抽取的 JSON。只输出 JSON，不要其他内容。"

#### 示例的作用

LLM 对 JSON 格式的遵循度高度依赖示例。提供具体示例（而非仅描述 schema）能显著提升输出格式准确率。示例中包含：
- 每种节点类型至少一个
- 每种关系类型至少一个
- 真实感的描述文本

### 2.3 抽取容错机制

| 问题 | 解决方案 |
|------|----------|
| LLM 返回 Markdown 代码块 | 正则去除 ```json 包裹 |
| JSON 前后有解释文字 | 截取第一个 `{` 到最后一个 `}` |
| 多个 JSON 对象 | 逐段扫描，取第一个含 nodes 字段的 |
| 尾逗号语法错误 | 正则修复 `,}` -> `}`，`,]` -> `]` |
| 中文类型名 | 映射表转换（概念->concept 等） |
| 未知类型名 | 降级为 concept（不丢弃节点） |
| 抽取结果为空 | 自动重试 1 次 |
| API 调用失败 | 记录错误日志，返回 0 节点 |

### 2.4 幂等写入

使用 `MERGE` 而非 `CREATE`，确保重复构建不会产生重复节点：

```cypher
MERGE (n:Concept {name: $name, source_document: $did})
SET n.description = $desc
```

节点唯一性由 `(name, source_document)` 联合确定，不同文献的同名实体视为不同节点。

### 2.5 图谱查询

```cypher
-- 获取图谱所有节点
MATCH (g:Graph {graph_id: $gid})-[:CONTAINS_NODE]->(n)
RETURN elementId(n) AS eid, n.name AS name, n.type AS type, ...

-- 获取节点间关系（两端都在已取节点集合内）
MATCH (a)-[r]->(b)
WHERE elementId(a) IN $eids AND elementId(b) IN $eids
RETURN elementId(a) AS src, elementId(b) AS tgt, type(r) AS rel
```

返回格式直接兼容 ECharts graph series 的 `data` 和 `links`。

## 3. 多模态解析

### 3.1 文本提取

基于 PyMuPDF `page.get_text("dict")` 返回的 block 结构逐块切分，而非整页 `get_text("text")` 后按段落粗切：

1. 遍历每页 `blocks`，只取文本块（`type==0`），汇总其行（lines）与跨度（spans）
2. **双栏排序**：依据每行 x 坐标判断所属栏（标号/正文 x 超过页面宽度 50% 归右栏），
   先排左栏、再排右栏，保证双栏论文的阅读顺序正确
3. 每个 block 作为一个文本块输出，前端展示字段为 `block.content`

实测效果：5 页 IEEE 双栏论文由「整页 5 个文本块」细化为「143 个文本块」，粒度显著提升，
后续 fulltext 切块与 RAG 溯源都基于这些 block。

### 3.2 公式检测

新方案**以公式标号为锚点**，结合栏位判断、区域裁剪与文本过滤，**默认不调用 VL 模型**
（`FORMULA_VL_ENABLED=false`，避免逐页 API 调用成本）。流程：

1. **标号检测**：用正则 `\((\d+(?:\.\d+)?)\)\s*$` 匹配行尾公式标号（如 `(1)`、`(2.3)`、`(10)`），
   命中行的数字即公式标号 `formula_number`
2. **栏位判断**：依据标号行 x 坐标判断所在栏——标号行 x 超过页面宽度 50% 判定为右栏
   （裁剪左边界取页面 52% 处），否则为左栏（左边界取 40pt），防止双栏论文把相邻栏正文裁进来
3. **区域裁剪**：以标号行为基准向上扩展 2.5 倍行高、向下扩展 1.5 倍行高确定 y 范围，
   x 范围从所在栏左边界到标号行右边界 +10pt，覆盖分数、求和符号等二维布局
4. **文本提取与过滤**：`page.get_text("text", clip=bbox)` 提取区域文本，只保留含等号/数学运算符的行，
   用常见英文停用词表过滤正文行，合并为公式文本；并校验数学符号密度，过滤误判
5. **公式原图保存**：将裁剪区域用 `page.get_pixmap(clip=..., dpi=200)` 渲染为 200dpi PNG，
   保存到 `/app/data/figures/`，条目写入 `image_url`（形如 `/static/figures/{doc_id}_{idx}.png`），
   供前端默认展示
6. **VL 增强（可选，默认关）**：仅当 `FORMULA_VL_ENABLED=true` 时，才对裁剪区域额外调用 VL 模型
   尝试识别为 LaTeX（`detect_reason="vl"`）；默认关闭时 `detect_reason="text"`，LaTeX 来自步骤 4 的文本提取

最终公式条目字段：`page`（页码）、`latex`（文本提取的公式文本）、`image_url`（公式原图 PNG）、
`formula_number`（标号）、`detect_reason`（text/vl）、`original`、`vl_success`。

### 3.3 图片提取

PyMuPDF `page.get_images(full=True)` 获取页面引用的图片 xref，`doc.extract_image(xref)` 提取图片二进制。

去重：同一 xref 只提取一次（PDF 中图片可能被多页引用）。

过滤：< 2KB 的图片跳过（通常是装饰元素、logo）。

### 3.4 参考文献提取

三级降级定位 References 区段，按编号切分条目，提取编号/年份/标题。

## 4. 模型调用策略

### 4.1 模型与视觉开关

用户实际接入 **DeepSeek API**（`MODEL_MODE=api`）：

- `QWEN_API_BASE=https://api.deepseek.com`
- `QWEN_API_MODEL=deepseek-flash`（视觉模型，处理图片/图表）
- `QWEN_TEXT_API_MODEL=deepseek-chat`（文本模型，处理所有纯文本生成任务）

两个独立开关：

- `VISION_ENABLED=true`：DeepSeek Flash 支持视觉，全局开启视觉能力（图片/图表可走 VL）
- `FORMULA_VL_ENABLED=false`：公式识别的 VL 增强**默认关闭**。公式主流程走 3.2 的「标号检测+裁剪+文本提取」，
  不依赖 VL；仅在需要更准 LaTeX 时才手动打开该开关

> ⚠️ **不要用 deepseek-v4-pro 做结构化 JSON 输出**：该模型对要求严格 JSON 返回的场景（尤其图谱实体抽取）
> 会返回空 `content`，导致解析失败。图谱抽取、摘要等结构化任务统一走 `deepseek-chat`。

### 4.2 模型分工

| 任务 | 调用方法 | 模型配置项 | 实际模型 |
|------|----------|-----------|----------|
| 结构化摘要 | chat_text | QWEN_TEXT_API_MODEL | deepseek-chat |
| 图谱实体抽取 | chat_text | QWEN_TEXT_API_MODEL | deepseek-chat |
| RAG 问答生成 | chat_text | QWEN_TEXT_API_MODEL | deepseek-chat |
| 综述生成 | chat_text | QWEN_TEXT_API_MODEL | deepseek-chat |
| 图片公式识别（VL 增强） | chat_with_image | QWEN_API_MODEL | deepseek-flash |
| 图片表格识别 | chat_with_image | QWEN_API_MODEL | deepseek-flash |

文本任务统一走 `deepseek-chat`，视觉任务走 `deepseek-flash`，可独立优化成本和效果。
注意：公式识别主链路默认不开 VL（见 3.2），上表「图片公式识别」仅在 `FORMULA_VL_ENABLED=true` 时触发。
