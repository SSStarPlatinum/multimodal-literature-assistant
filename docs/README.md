# 项目文档索引

本目录包含项目的完整文档，按主题分类。任何关于项目的问题都可以在这里找到答案。

## 文档列表

| 序号 | 文档 | 内容 | 适用场景 |
|------|------|------|----------|
| 01 | [项目概述](./01_PROJECT_OVERVIEW.md) | 项目定位、核心功能、技术栈、目录结构 | 快速了解项目 |
| 02 | [系统架构](./02_ARCHITECTURE.md) | 整体架构图、服务编排、请求流转、模型架构 | 理解系统设计 |
| 03 | [后端实现细节](./03_BACKEND_IMPLEMENTATION.md) | 6 个服务的完整实现、关键算法、代码设计决策 | 后端开发/调试 |
| 04 | [前端实现细节](./04_FRONTEND_IMPLEMENTATION.md) | 4 个页面、组件、状态管理、ECharts 配置 | 前端开发/调试 |
| 05 | [RAG 与知识图谱核心设计](./05_RAG_AND_KNOWLEDGE_GRAPH.md) | 三层检索策略、图谱 Schema、Prompt 工程、容错机制 | 核心算法理解 |
| 06 | [部署指南](./06_DEPLOYMENT.md) | 环境要求、快速启动、服务管理、数据备份、生产建议 | 部署运维 |
| 07 | [问题排查手册](./07_TROUBLESHOOTING.md) | 所有已知问题的根因分析和解决方案 | 故障排查 |
| 08 | [常见问题 FAQ](./08_FAQ.md) | 50+ 常见问题的简明回答 | 快速答疑 |
| - | [API 契约](./API_CONTRACT.md) | 前后端接口定义、请求/响应格式 | 接口联调 |

## 快速导航

### 我想了解项目
→ 读 [01 项目概述](./01_PROJECT_OVERVIEW.md) + [02 系统架构](./02_ARCHITECTURE.md)

### 我要部署项目
→ 读 [06 部署指南](./06_DEPLOYMENT.md)，遇到问题查 [07 问题排查](./07_TROUBLESHOOTING.md)

### 我要修改后端代码
→ 读 [03 后端实现](./03_BACKEND_IMPLEMENTATION.md) + [API 契约](./API_CONTRACT.md)

### 我要修改前端代码
→ 读 [04 前端实现](./04_FRONTEND_IMPLEMENTATION.md)

### 我想理解 RAG/图谱原理
→ 读 [05 RAG 与知识图谱](./05_RAG_AND_KNOWLEDGE_GRAPH.md)

### 我遇到了 Bug
→ 先查 [07 问题排查](./07_TROUBLESHOOTING.md)，再查 [08 FAQ](./08_FAQ.md)

### 别人问我项目问题
→ 按主题查阅对应文档，所有实现细节和设计决策都有记录

## 已解决的问题清单

以下问题在开发过程中遇到并已解决，详细方案见 [07 问题排查手册](./07_TROUBLESHOOTING.md)：

1. ✅ PDF 文本块单词粘连（pdfplumber → PyMuPDF）
2. ✅ 公式误判 100 条（正则含连字符 → 严格密度检测）
3. ✅ 图表破损不显示（只返回坐标 → fitz 提取图片 + StaticFiles）
4. ✅ 参考文献 0 条（正则过严 → 三级降级匹配）
5. ✅ 前端字段不匹配（block.text → block.content）
6. ✅ Neo4j 健康检查失败（wget 处理 + start_period）
7. ✅ 图谱 0 节点（API Key 401 → 正确配置 DeepSeek）
8. ✅ 图谱删除后残留（MATCH 为空 → OPTIONAL MATCH）
9. ✅ 图表图片 404（nginx 缺 /static 代理）
10. ✅ nginx 配置不生效（Docker build context 路径问题）
11. ✅ 双栏论文文本整页合并为 1 块（纯文本空行切分 → PyMuPDF block 结构切分 + 双栏排序，文本块 5 → 143）
12. ✅ 公式 VL 识别效果差（版面分析 + VL → 公式标号检测 + 区域裁剪 + 文本提取，IEEE 双栏 5 页论文 12 个公式全部命中，9/12 完全干净）
13. ✅ BGE-M3 / bge-reranker 本地模型路径缺失（启动时自动从 hf-mirror 下载，缓存到 /models）
14. ✅ 异步解析阻塞 HTTP（三服务 → 五服务编排，新增 redis + celery-worker，6 级进度上报）
15. ✅ deepseek-v4-pro 图谱抽取返回空 content（改用 deepseek-chat 作为文本模型）
