# 前端实现细节

## 1. 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | 3.4+ | 框架（Composition API + `<script setup>`） |
| Vite | 5.x | 构建工具 |
| Vue Router | 4.x | 路由管理（history 模式） |
| Pinia | 2.x | 状态管理 |
| Element Plus | 2.x | UI 组件库 |
| ECharts | 5.x | 知识图谱力导向图可视化 |
| KaTeX | 0.16.x | 数学公式渲染 |
| Axios | 1.x | HTTP 客户端 |

## 2. 页面结构

### 2.1 四个主页面

| 页面 | 路由 | 组件 | 功能 |
|------|------|------|------|
| 文献上传 | /upload | UploadView.vue | 文件上传、解析结果展示 |
| 深度问答 | /qa | QAView.vue | RAG 问答、文献对比 |
| 知识图谱 | /graph | GraphView.vue | 图谱构建、ECharts 可视化 |
| 综述生成 | /review | ReviewView.vue | 综述大纲、观点汇总 |

### 2.2 布局

- 左侧固定侧边栏（Sidebar 组件）：导航菜单
- 右侧内容区：动态路由组件
- 顶部无单独 header，侧边栏包含项目标题

## 3. 状态管理 (Pinia)

### 3.1 document store

```javascript
state: {
  documents: [],      // 已上传文献列表
  currentDocument: null,  // 当前查看的解析结果
  loading: false,
}
actions: {
  fetchDocuments(),     // 获取文献列表
  fetchDetail(doc_id),  // 获取解析详情
  removeDocument(id),   // 删除文献
}
```

### 3.2 qa store

```javascript
state: {
  history: [],      // 问答历史
  loading: false,
  currentAnswer: null,
  sources: [],      // 引用来源片段
}
```

### 3.3 graph store

```javascript
state: {
  graphs: [],           // 已有图谱列表
  currentGraph: null,   // 当前图谱数据（nodes/links）
  selectedNode: null,   // 选中的节点详情
  loading: false,
  nodeTypeFilter: [...], // 节点类型筛选
}
```

## 4. API 封装

### 4.1 Axios 实例配置

```javascript
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 120000,  // 解析/问答/图谱构建可能耗时较长
})

// 响应拦截器：统一解包 data、错误提示
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const msg = error.response?.data?.detail || error.message
    ElMessage.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    return Promise.reject(error)
  }
)
```

### 4.2 模块化 API

| 文件 | 功能 |
|------|------|
| api/document.js | 上传、列表、详情、删除 |
| api/task.js | 异步解析任务状态轮询（`GET /task/{task_id}`） |
| api/qa.js | 提问、对比 |
| api/graph.js | 构建、列表、详情、删除 |
| api/review.js | 大纲生成、观点汇总 |

## 5. 文献上传页 (UploadView)

### 5.1 上传流程

解析为异步任务（Celery），上传接口立即返回 `task_id`，前端轮询进度：

```
拖拽/点击选择文件
  → 校验扩展名（pdf/png/jpg/jpeg/tiff）
  → FormData 上传（含 parse_formula/parse_figures/parse_references 选项）
  → 上传进度条展示（axios onUploadProgress，仅反映文件上传字节进度）
  → 后端立即返回 { task_id, document_id, filename, status:"parsing" }
  → 前端每 2s 轮询 GET /task/{task_id}（docStore.startUploadAndPoll 接管）
  → 按 progress(0-100) + current_step 展示 6 级解析进度
  → 任务 SUCCESS 后自动 fetchDocuments 刷新列表，并 fetchDetail 展示解析结果
  → 任务 FAILURE 时 el-alert 展示 error 信息，停止轮询
```

6 级进度与 `current_step` 映射：

| current_step | progress | 说明 |
|--------------|----------|------|
| upload_complete | 10% | 文件落盘完成 |
| text_extraction | 30% | 文本块提取 |
| formula_recognition | 50% | 公式检测与裁剪 |
| figure_extraction | 70% | 图表提取 |
| references | 85% | 参考文献提取 |
| summary_generation | 100% | 结构化摘要生成 |

轮询期间禁用拖拽上传区（`taskPolling` 置灰），避免重复提交。

### 5.2 解析结果展示

四个 Tab 页：

**文本块**：
- 按段落展示，标注序号和页码（`[i] p.{block.page}`）
- 字段：`block.content`（注意：不是 block.text；兜底链 `block.content || block.text || block`）
- 切分方式：后端基于 PyMuPDF(fitz) 的 block 结构逐块切分，并对双栏论文做栏位排序
  （测试：5 页 IEEE 双栏论文由整页 5 个文本块细化为 143 个文本块）

**公式**：
- **默认显示公式原图**：直接渲染 `f.image_url` 指向的 200dpi 公式区域 PNG（来自 `/static/figures/`）
- 点击「查看LaTeX格式」按钮，展开显示**红色 LaTeX 代码**（`<pre class="latex-text">`，`#f56c6c`）；再次点击「收起LaTeX」折叠
- 即「默认原图、点击查看 LaTeX」，而非旧版「默认渲染 LaTeX、点击查看原文」
- 若 `f.image_url` 缺失，降级显示 `f.original` 原文文本
- 字段：`f.image_url`（公式原图）、`f.latex`（文本提取出的 LaTeX）、`f.page`（页码）、
  `f.formula_number`（公式标号，如从 `(1)` 提取的 "1"）、`f.detect_reason`（`text`=标号检测 / `vl`=VL识别）

**图表**：
- 网格布局（2列）
- 图片 URL：`fig.url || fig.image_url`
- 图注：`fig.caption`，无则显示 "Figure {i+1} (page {fig.page})"
- 加载失败兜底：`@error` 隐藏 img，显示占位文字

**参考文献**：
- 有序列表展示
- 字段：`ref.raw || ref.text || ref.title`
- 显示编号 `[ref.number]` 和年份 `(ref.year)`

### 5.3 关键 Bug 修复

**初始问题**：文本块显示 `[object Object]`，参考文献空白。
**根因**：前端读 `block.text` 但后端返回 `block.content`；前端读 `ref.text` 但后端返回 `ref.raw`。
**修复**：字段对齐，增加兜底链 `block.content || block.text || block`。

## 6. 知识图谱页 (GraphView)

### 6.1 ECharts 力导向图配置

```javascript
option = {
  tooltip: { formatter: ... },  // 悬停显示节点详情
  legend: [{ data: nodeTypes }], // 类型筛选图例
  series: [{
    type: 'graph',
    layout: 'force',
    force: {
      repulsion: 300,      // 节点间斥力
      edgeLength: [80, 150], // 边长度范围
      gravity: 0.1,        // 向心力
    },
    roam: true,            // 允许缩放拖拽
    draggable: true,       // 节点可拖拽
    label: { show: true, position: 'right' },
    lineStyle: { color: 'source', curveness: 0.1 },
    emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
    data: nodes.map(n => ({
      id: n.id,
      name: n.label,
      category: typeToIndex[n.type],
      symbolSize: 40 + Math.random() * 20,
      itemStyle: { color: typeColors[n.type] },
    })),
    links: links.map(l => ({
      source: l.source,
      target: l.target,
      label: { show: true, formatter: l.type.toUpperCase() },
    })),
  }]
}
```

### 6.2 节点类型颜色

| 类型 | 颜色 |
|------|------|
| concept | #409eff（蓝） |
| algorithm | #67c23a（绿） |
| dataset | #e6a23c（橙） |
| metric | #f56c6c（红） |
| conclusion | #909399（灰） |

### 6.3 交互功能

- **节点点击**：右侧面板显示节点详情（名称、类型、描述、来源文献、页码）
- **类型筛选**：左侧复选框控制显示哪些类型节点
- **缩放拖拽**：鼠标滚轮缩放，拖拽移动画布
- **已有图谱列表**：右侧展示历史图谱，可切换/删除

## 7. 公式渲染组件 (FormulaRenderer)

```vue
<template>
  <div ref="containerRef"></div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  latex: { type: String, required: true },
  displayMode: { type: Boolean, default: false },
})

function render() {
  try {
    katex.render(props.latex, containerRef.value, {
      displayMode: props.displayMode,
      throwOnError: false,  // 渲染失败不抛异常，显示原文
      output: 'html',
    })
  } catch (e) {
    containerRef.value.textContent = props.latex
  }
}
</script>
```

**关键**：`throwOnError: false` 确保公式语法错误时不崩溃，降级显示原文。

## 8. 构建与部署

### 8.1 多阶段 Docker 构建

```dockerfile
# 阶段1：Node 构建
FROM node:20-alpine AS builder
WORKDIR /app
RUN npm config set registry https://registry.npmmirror.com  # 国内镜像
COPY package*.json ./
RUN npm install
COPY . .
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# 阶段2：Nginx 运行时
FROM nginx:1.25-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf  # 注意：从 build context 复制
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 8.2 Nginx 配置要点

```nginx
# API 反向代理
location /api/ {
    proxy_pass http://backend:8000;
    client_max_body_size 100m;  # 大文件上传
    proxy_read_timeout 300s;    # 长耗时请求
}

# 静态资源（图表图片）代理
location /static/ {
    proxy_pass http://backend:8000;
    expires 7d;
    add_header Cache-Control "public, immutable";
}

# SPA 路由回退
location / {
    try_files $uri $uri/ /index.html;
}
```

### 8.3 关键 Bug：nginx.conf 路径问题

**问题**：docker-compose build context 是 `./frontend`，Dockerfile 中 `COPY nginx.conf` 实际复制的是 **`frontend/nginx.conf`**，而非 `docker/nginx.conf`。修改 `docker/nginx.conf` 后容器内配置不更新。

**结论**：`frontend/nginx.conf` 才是容器实际使用的配置；`docker/nginx.conf` 仅为仓库留档，二者必须保持同步——任何改动都要先改 `frontend/nginx.conf`，再同步到 `docker/nginx.conf`，并重新 build 前端镜像生效。

### 8.4 代码更新后的生效方式

- **后端 / celery-worker**：后端代码通过卷挂载（volume mount）进容器，改动后 `docker-compose restart backend celery-worker` 即生效，无需重新 build。
- **前端**：前端产物在 build 阶段打包进 Nginx 镜像，改动源码后**必须重新 build** 前端镜像（`docker-compose build frontend && docker-compose up -d frontend`）才会生效；仅 restart 不生效。
- **nginx.conf**：同前端，改动需重新 build 前端镜像。

## 9. 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| VITE_API_BASE_URL | /api/v1 | 构建时注入的 API 前缀 |

通过 docker-compose build args 传递：
```yaml
args:
  - VITE_API_BASE_URL=${VITE_API_BASE_URL:-/api/v1}
```
