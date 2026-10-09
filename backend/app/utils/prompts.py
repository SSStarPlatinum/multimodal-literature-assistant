"""
LLM Prompt 模板集中管理
=======================
所有发给大模型的 system/user 提示词统一在此定义，便于版本管理与调优。
JSON 输出类任务都要求模型只输出合法 JSON，不附加解释。
"""

# ============ 1. 结构化摘要（RAG 第一层） ============
SUMMARY_SYSTEM = """你是一名严谨的科研文献阅读助手。请阅读给定的学术论文文本，输出结构化摘要。
你必须严格只输出一个 JSON 对象，不要输出任何额外解释、Markdown 代码块或注释。"""

SUMMARY_USER_TEMPLATE = """请为下面这篇论文生成结构化摘要，包含四个字段：
- purpose: 研究目的/要解决的问题（1-2句）
- methods: 采用的方法/技术路线（2-3句）
- data: 使用的数据集/实验设置（1-2句，没有则填"未明确"）
- conclusion: 主要结论与贡献（1-2句）

论文标题: {title}
论文正文（节选）:
{text}

请输出形如 {{"purpose": "...", "methods": "...", "data": "...", "conclusion": "..."}} 的 JSON。"""


# ============ 2. 公式识别（图文） ============
# 直接要求输出 LaTeX，不强制 JSON，降低视觉模型输出难度，提升识别成功率
FORMULA_VL_USER_TEMPLATE = """这是从学术论文中截取的一张图片，其中包含数学公式。
请将图中的数学公式完整、准确地转换为 LaTeX 表示。

要求：
1. 只输出 LaTeX 公式本身，用 $$ 包裹，例如：$$E = mc^2$$
2. 如果图片中有多个公式，用 \\n\\n 分隔每个 $$...$$
3. 不要输出任何解释、说明或 JSON 格式
4. 确保公式完整，包括上下标、分数、根号、求和符号等所有元素
5. 如果图片中没有数学公式，输出：$$NONE$$"""


# ============ 3. 图表/表格识别（图文） ============
TABLE_VL_USER_TEMPLATE = """这是从学术论文中截取的一张图片，可能是一个数据表格。
请把表格内容提取出来，并转换为 Markdown 表格格式。
如果图片不是表格，请只输出 JSON: {{"is_table": false, "markdown": ""}}。
如果是表格，请只输出如下 JSON：
{{"is_table": true, "caption": "表格标题(若有)", "markdown": "用 | 分隔的 Markdown 表格"}}"""


# ============ 4. RAG 问答生成 ============
QA_SYSTEM = """你是一名学术文献精读助手。请基于下方提供的文献片段回答用户问题。
要求：
1. 答案必须严格基于给定片段，不要编造片段中没有的事实。
2. 当信息不足以回答时，明确说明"根据提供的文献片段无法确定"。
3. 在答案中用 [n] 标注引用来源序号，n 对应片段编号。
4. 语言简洁、专业。"""

QA_USER_TEMPLATE = """问题: {question}

以下是按相关性排序的文献片段:
{context}

请给出详细回答。"""


# ============ 5. 文献对比 ============
COMPARE_SYSTEM = """你是一名学术对比分析助手。请按指定维度对比多篇论文，输出结构化结果。
必须只输出 JSON，不要额外解释。"""

COMPARE_USER_TEMPLATE = """对比维度: {dimension}
维度说明: {dimension_desc}

各文献在该维度下的信息:
{per_doc_info}

请只输出如下 JSON：
{{
  "items": [{{"document_id": "xxx", "title": "yyy", "content": "该文献在本维度下的描述"}}],
  "similarities": ["相似点1", "相似点2"],
  "differences": ["差异点1", "差异点2"]
}}"""

COMPARE_DIMENSION_DESC = {
    "method": "方法/技术路线：模型结构、算法、训练流程",
    "dataset": "数据集：使用的数据规模、领域、来源",
    "metric": "评估指标：采用的评价指标与数值结果",
    "conclusion": "结论：主要发现、贡献与局限",
}


# ============ 6. 知识图谱实体/关系抽取 ============
GRAPH_EXTRACT_SYSTEM = """你是一名知识图谱构建专家。请从学术论文文本中抽取实体与关系，输出严格 JSON。

【节点类型】只能是以下5种（type字段必须用英文小写）：
- concept: 概念、术语、理论、问题定义
- algorithm: 算法、模型、方法、框架、架构
- dataset: 数据集、基准测试、实验数据
- metric: 评估指标、性能指标、评价标准
- conclusion: 实验结论、发现、贡献、局限性

【关系类型】只能是以下6种（relation字段必须用英文大写）：
- USES: 算法使用了某概念/技术
- IMPROVES: 算法改进了另一算法
- EVALUATES_ON: 算法在某数据集上评估
- ACHIEVES: 算法达到了某指标/结果
- COMPARES_WITH: 算法与另一算法对比
- PROPOSED_BY: 实体由该文献提出

【输出要求】
1. 必须只输出一个合法 JSON 对象，不要输出任何解释、Markdown代码块或注释
2. nodes 数组中每个对象必须包含 name, type, description, page_number 四个字段
3. edges 数组中每个对象必须包含 source, target, relation 三个字段
4. source 和 target 必须是 nodes 中已定义的实体 name
5. 只抽取正文中明确出现的实体，宁缺毋滥
6. 至少抽取3个节点，最多15个节点"""

GRAPH_EXTRACT_USER_TEMPLATE = """文献标题: {title}
文献正文（节选）:
{text}

请抽取其中的关键实体与关系，输出如下 JSON 格式（这是示例，不是答案）：
{{
  "nodes": [
    {{"name": "Deepfake Detection", "type": "concept", "description": "检测伪造人脸图像的技术", "page_number": {page}}},
    {{"name": "Knowledge Distillation", "type": "algorithm", "description": "通过教师模型指导学生模型训练的方法", "page_number": {page}}},
    {{"name": "FF++ Dataset", "type": "dataset", "description": "FaceForensics++ 伪造人脸检测数据集", "page_number": {page}}},
    {{"name": "AUC", "type": "metric", "description": "ROC曲线下面积，分类模型评估指标", "page_number": {page}}},
    {{"name": "跨域检测准确率提升", "type": "conclusion", "description": "所提方法在目标域上取得SOTA性能", "page_number": {page}}}
  ],
  "edges": [
    {{"source": "Knowledge Distillation", "target": "Deepfake Detection", "relation": "USES"}},
    {{"source": "Knowledge Distillation", "target": "FF++ Dataset", "relation": "EVALUATES_ON"}},
    {{"source": "Knowledge Distillation", "target": "AUC", "relation": "ACHIEVES"}}
  ]
}}

现在请根据上方论文正文，输出你抽取的 JSON。只输出 JSON，不要其他内容。"""


# ============ 7. 综述生成 ============
REVIEW_OUTLINE_SYSTEM = """你是一名学术综述撰写专家。请基于给定文献集合，规划综述大纲。只输出 JSON。"""

REVIEW_OUTLINE_USER_TEMPLATE = """综述主题: {topic}
目标章节: {sections}

各文献要点:
{doc_summaries}

请只输出 JSON:
[
  {{"section": "1. 章节标题", "key_points": ["要点1", "要点2"]}},
  ...
]"""


REVIEW_VIEWS_SYSTEM = """你是一名学术综述撰写专家。请汇总核心观点、研究缺口与发展脉络。只输出 JSON。"""

REVIEW_VIEWS_USER_TEMPLATE = """综述主题: {topic}
文献信息:
{doc_summaries}

请只输出如下 JSON：
{{
  "core_views": [
    {{"view": "核心观点", "supporting_docs": ["doc_id1"], "evidence": "支撑证据摘录"}}
  ],
  "research_gaps": [
    {{"gap": "缺口描述", "severity": "high|medium|low", "suggested_direction": "建议方向"}}
  ],
  "evolution_timeline": [
    {{"year": "2021", "event": "里程碑事件", "document_id": "doc_id1"}}
  ]
}}"""
