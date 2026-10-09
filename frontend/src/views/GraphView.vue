<template>
  <div class="page-container">
    <h2 class="page-title">知识图谱</h2>

    <el-row :gutter="16">
      <!-- 左侧控制区 -->
      <el-col :span="5">
        <el-card shadow="never">
          <template #header><span>构建图谱</span></template>
          <DocumentSelector
            :documents="docStore.documents"
            :selected-ids="selectedDocIds"
            label="选择文献"
            @update:selected-ids="selectedDocIds = $event"
          />
          <el-divider />
          <el-button
            type="primary"
            style="width: 100%"
            :loading="graphStore.building"
            :disabled="selectedDocIds.length === 0"
            @click="buildGraph"
          >
            构建知识图谱
          </el-button>

          <!-- P1-3：手动增删节点 / 关系（需先加载某个图谱） -->
          <el-divider />
          <el-button
            plain
            style="width: 100%; margin-bottom: 8px"
            :disabled="!graphStore.currentGraphId"
            @click="openNodeDialog"
          >添加节点</el-button>
          <el-button
            plain
            type="success"
            style="width: 100%"
            :disabled="!graphStore.currentGraphId"
            @click="openEdgeDialog"
          >添加关系</el-button>
          <p v-if="!graphStore.currentGraphId" class="hint-tip">请先构建或选择一个图谱后再编辑</p>
        </el-card>

        <!-- 类型筛选 -->
        <el-card shadow="never" style="margin-top: 16px">
          <template #header><span>节点类型筛选</span></template>
          <div v-for="(color, type) in typeColors" :key="type" class="filter-item">
            <el-checkbox
              :model-value="graphStore.visibleTypes[type]"
              @change="graphStore.toggleType(type); renderChart()"
            >
              <span class="dot" :style="{ background: color }"></span>
              {{ typeLabels[type] || type }}
            </el-checkbox>
          </div>
        </el-card>

        <!-- 图谱统计 -->
        <el-card shadow="never" style="margin-top: 16px">
          <template #header><span>统计</span></template>
          <div class="stat-row">
            <span>节点数</span>
            <b>{{ graphStore.stats.nodes }}</b>
          </div>
          <div class="stat-row">
            <span>关系数</span>
            <b>{{ graphStore.stats.relationships }}</b>
          </div>
        </el-card>
      </el-col>

      <!-- 中间：图谱画布 -->
      <el-col :span="13">
        <el-card shadow="never" body-style="padding: 0">
          <div ref="chartContainer" class="graph-chart"></div>
          <LoadingSpinner v-if="graphStore.loading" text="正在加载图谱..." overlay />
          <el-empty
            v-if="!graphStore.loading && graphStore.nodes.length === 0"
            description="选择文献并构建知识图谱"
            style="height: 500px"
          />
        </el-card>
      </el-col>

      <!-- 右侧：节点详情 + 已有图谱列表 -->
      <el-col :span="6">
        <el-card shadow="never">
          <template #header><span>节点详情</span></template>
          <el-empty v-if="!selectedNode" description="点击图谱节点查看 / 编辑详情" />
          <div v-else class="node-detail">
            <el-form label-position="top" size="small">
              <el-form-item label="名称">
                <el-input v-model="editName" placeholder="节点名称" />
              </el-form-item>
              <el-form-item label="类型">
                <el-select v-model="editType" style="width: 100%">
                  <el-option
                    v-for="(label, value) in typeLabels"
                    :key="value"
                    :label="label"
                    :value="value"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="描述">
                <el-input v-model="editDesc" type="textarea" :rows="3" placeholder="节点描述" />
              </el-form-item>
            </el-form>
            <div class="detail-actions">
              <el-button type="primary" size="small" :loading="nodeSaving" @click="saveNode">保存</el-button>
              <el-button type="danger" size="small" :loading="nodeDeleting" @click="removeNode">删除节点</el-button>
            </div>
            <div class="node-props">
              <div v-for="(v, k) in selectedNode.properties" :key="k" class="prop-row">
                <span class="prop-key">{{ k }}:</span>
                <span class="prop-val">{{ typeof v === 'string' ? v : JSON.stringify(v) }}</span>
              </div>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header>
            <div class="card-header">
              <span>已有图谱</span>
              <el-button size="small" @click="graphStore.fetchGraphList()">刷新</el-button>
            </div>
          </template>
          <div
            v-for="g in graphStore.graphList"
            :key="g.graph_id"
            class="graph-item"
            :class="{ active: g.graph_id === graphStore.currentGraphId }"
          >
            <div class="g-name" @click="graphStore.loadGraph(g.graph_id)">
              {{ g.name || g.graph_id.slice(0, 8) }}
            </div>
            <div class="g-meta">
              <span>{{ g.node_count }} 节点</span>
              <el-button size="small" type="danger" link @click="onDeleteGraph(g.graph_id)">删除</el-button>
            </div>
          </div>
          <el-empty v-if="graphStore.graphList.length === 0" description="暂无图谱" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 添加节点对话框（P1-3） -->
    <el-dialog v-model="nodeDialogVisible" title="添加节点" width="420px">
      <el-form label-position="top" size="default">
        <el-form-item label="名称">
          <el-input v-model="newNode.name" placeholder="节点名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="newNode.type" style="width: 100%">
            <el-option
              v-for="(label, value) in typeLabels"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="newNode.description" type="textarea" :rows="3" placeholder="节点描述" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nodeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="nodeCreating" @click="submitNewNode">创建</el-button>
      </template>
    </el-dialog>

    <!-- 添加关系对话框（P1-3） -->
    <el-dialog v-model="edgeDialogVisible" title="添加关系" width="420px">
      <el-form label-position="top" size="default">
        <el-form-item label="源节点">
          <el-select v-model="newEdge.source" placeholder="选择源节点" style="width: 100%">
            <el-option
              v-for="n in graphStore.nodes"
              :key="n.id"
              :label="n.label"
              :value="n.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="目标节点">
          <el-select v-model="newEdge.target" placeholder="选择目标节点" style="width: 100%">
            <el-option
              v-for="n in graphStore.nodes"
              :key="n.id"
              :label="n.label"
              :value="n.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="关系类型">
          <el-select v-model="newEdge.relation" style="width: 100%">
            <el-option
              v-for="(label, value) in relationLabels"
              :key="value"
              :label="label"
              :value="value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edgeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="edgeCreating" @click="submitNewEdge">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDocumentStore } from '../stores/document'
import { useGraphStore } from '../stores/graph'
import DocumentSelector from '../components/DocumentSelector.vue'
import LoadingSpinner from '../components/LoadingSpinner.vue'

const docStore = useDocumentStore()
const graphStore = useGraphStore()

const selectedDocIds = ref([])
const selectedNode = ref(null)
const chartContainer = ref(null)
let chartInstance = null

// 节点类型 -> 颜色映射
const typeColors = {
  concept: '#409eff',
  algorithm: '#67c23a',
  dataset: '#e6a23c',
  metric: '#f56c6c',
  conclusion: '#909399'
}
// 节点类型中文标签
const typeLabels = {
  concept: '概念',
  algorithm: '算法',
  dataset: '数据集',
  metric: '指标',
  conclusion: '结论'
}
// 关系类型中文标签（P1-3）
const relationLabels = {
  uses: '使用 (uses)',
  improves: '改进 (improves)',
  evaluates_on: '在…上评估 (evaluates_on)',
  achieves: '达到 (achieves)',
  compares_with: '与…对比 (compares_with)',
  proposed_by: '由…提出 (proposed_by)'
}

// ==================== P1-3 节点编辑状态 ====================
const editName = ref('')
const editDesc = ref('')
const editType = ref('')
const nodeSaving = ref(false)
const nodeDeleting = ref(false)

// 添加节点对话框
const nodeDialogVisible = ref(false)
const nodeCreating = ref(false)
const newNode = reactive({ name: '', description: '', type: 'concept' })

// 添加关系对话框
const edgeDialogVisible = ref(false)
const edgeCreating = ref(false)
const newEdge = reactive({ source: '', target: '', relation: 'uses' })

// 选中节点变化时同步到编辑表单
watch(selectedNode, (n) => {
  if (n) {
    editName.value = n.label || n.name || ''
    editDesc.value = n.properties?.description || n.properties?.desc || ''
    editType.value = n.type || ''
  }
}, { immediate: true })

/** 保存节点修改 */
async function saveNode() {
  if (!selectedNode.value) return
  nodeSaving.value = true
  try {
    await graphStore.updateNode(selectedNode.value.id, {
      name: editName.value,
      description: editDesc.value,
      type: editType.value
    })
    ElMessage.success('节点已保存')
    // 重新选中刷新后的节点，保持详情面板与最新数据一致
    const fresh = graphStore.nodes.find(n => n.id === selectedNode.value.id)
    if (fresh) selectedNode.value = fresh
  } catch (err) {
    // 拦截器已提示
  } finally {
    nodeSaving.value = false
  }
}

/** 删除当前节点 */
async function removeNode() {
  if (!selectedNode.value) return
  await ElMessageBox.confirm('确定删除该节点及其关联关系？', '提示', { type: 'warning' })
  nodeDeleting.value = true
  try {
    await graphStore.removeNode(selectedNode.value.id)
    ElMessage.success('节点已删除')
    selectedNode.value = null
  } catch (err) {
    // 拦截器已提示
  } finally {
    nodeDeleting.value = false
  }
}

/** 打开添加节点对话框 */
function openNodeDialog() {
  newNode.name = ''
  newNode.description = ''
  newNode.type = 'concept'
  nodeDialogVisible.value = true
}

/** 提交新节点 */
async function submitNewNode() {
  if (!newNode.name.trim()) {
    ElMessage.warning('请输入节点名称')
    return
  }
  nodeCreating.value = true
  try {
    await graphStore.addNode({
      name: newNode.name.trim(),
      description: newNode.description,
      type: newNode.type
    })
    ElMessage.success('节点已添加')
    nodeDialogVisible.value = false
  } catch (err) {
    // 拦截器已提示
  } finally {
    nodeCreating.value = false
  }
}

/** 打开添加关系对话框 */
function openEdgeDialog() {
  newEdge.source = ''
  newEdge.target = ''
  newEdge.relation = 'uses'
  edgeDialogVisible.value = true
}

/** 提交新关系 */
async function submitNewEdge() {
  if (!newEdge.source || !newEdge.target) {
    ElMessage.warning('请选择源节点与目标节点')
    return
  }
  if (newEdge.source === newEdge.target) {
    ElMessage.warning('源节点与目标节点不能相同')
    return
  }
  edgeCreating.value = true
  try {
    await graphStore.addEdge({
      source: newEdge.source,
      target: newEdge.target,
      relation: newEdge.relation
    })
    ElMessage.success('关系已添加')
    edgeDialogVisible.value = false
  } catch (err) {
    // 拦截器已提示
  } finally {
    edgeCreating.value = false
  }
}

/** 初始化 ECharts 实例 */
function initChart() {
  if (!chartContainer.value) return
  chartInstance = echarts.init(chartContainer.value)
  // 节点点击事件
  chartInstance.on('click', (params) => {
    if (params.dataType === 'node') {
      selectedNode.value = params.data
    }
  })
  window.addEventListener('resize', resizeChart)
}

function resizeChart() {
  chartInstance?.resize()
}

/** 基于 store 中的 nodes/links 与类型筛选渲染力导向图 */
function renderChart() {
  if (!chartInstance) return

  // 根据可见类型过滤节点
  const visibleNodes = graphStore.nodes.filter(n => graphStore.visibleTypes[n.type])
  const visibleNodeIds = new Set(visibleNodes.map(n => n.id))
  // 边两端节点都可见时才显示
  const visibleLinks = graphStore.links.filter(
    l => visibleNodeIds.has(l.source) && visibleNodeIds.has(l.target)
  )

  // 节点样式按类型着色
  const seriesData = visibleNodes.map(n => ({
    id: n.id,
    name: n.label,
    label: n.label,
    symbolSize: Math.max(18, 30 - (n.label?.length || 0)),
    itemStyle: { color: typeColors[n.type] || '#909399' },
    // 保留原始属性供点击详情使用
    value: n.type,
    properties: n.properties || {},
    type: n.type
  }))

  // 边按类型区分样式
  const edgeTypes = [...new Set(visibleLinks.map(l => l.type))]
  const edgeLineStyles = {
    uses: { color: '#c0c4cc', width: 1, curveness: 0.1 },
    compares: { color: '#e6a23c', width: 1.5, curveness: 0.1 },
    compares_with: { color: '#e6a23c', width: 1.5, curveness: 0.1 },
    improves: { color: '#67c23a', width: 1.5, curveness: 0.1 },
    evaluates_on: { color: '#409eff', width: 1, curveness: 0.1 },
    achieves: { color: '#f56c6c', width: 1.5, curveness: 0.1 },
    proposed_by: { color: '#909399', width: 1, curveness: 0.1 }
  }

  const seriesLinks = visibleLinks.map(l => {
    const style = edgeLineStyles[l.type] || { color: '#dcdfe6', width: 1, curveness: 0.1 }
    return {
      source: l.source,
      target: l.target,
      value: l.type,
      lineStyle: { ...style, curveness: 0.2 }
    }
  })

  const option = {
    tooltip: {
      formatter: (p) => {
        if (p.dataType === 'node') {
          return `<b>${p.data.name}</b><br/>类型: ${typeLabels[p.data.type] || p.data.type}`
        }
        return `关系: ${p.data.value}`
      }
    },
    legend: [{
      data: Object.keys(typeLabels).map(t => typeLabels[t]),
      bottom: 10
    }],
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true, // 支持缩放拖拽
      draggable: true,
      data: seriesData,
      links: seriesLinks,
      categories: Object.keys(typeLabels).map(t => ({ name: typeLabels[t] })),
      force: {
        repulsion: 300,       // 斥力
        edgeLength: [80, 150],// 边长范围
        gravity: 0.1          // 引力
      },
      label: {
        show: true,
        position: 'right',
        fontSize: 11
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3 }
      },
      lineStyle: { opacity: 0.7 }
    }]
  }

  chartInstance.setOption(option, true)
}

/** 构建图谱 */
async function buildGraph() {
  if (selectedDocIds.value.length === 0) return
  try {
    await graphStore.build({
      document_ids: selectedDocIds.value,
      entity_types: ['concept', 'algorithm', 'dataset', 'metric', 'conclusion'],
      relation_types: ['uses', 'compares', 'improves', 'evaluates_on', 'achieves']
    })
    ElMessage.success('图谱构建完成')
    await nextTick()
    renderChart()
  } catch (err) {
    // 拦截器已提示
  }
}

async function onDeleteGraph(id) {
  await ElMessageBox.confirm('确定删除该图谱？', '提示', { type: 'warning' })
  await graphStore.removeGraph(id)
  renderChart()
}

// 监听图谱数据变化自动重渲染
watch(
  () => [graphStore.nodes, graphStore.links],
  async () => {
    await nextTick()
    renderChart()
  },
  { deep: true }
)

onMounted(async () => {
  await Promise.all([docStore.fetchDocuments(), graphStore.fetchGraphList()])
  await nextTick()
  initChart()
  renderChart()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  chartInstance?.dispose()
})
</script>

<style scoped>
.graph-chart {
  width: 100%;
  height: 600px;
  position: relative;
}
.filter-item {
  margin: 6px 0;
}
.dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 4px;
}
.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.node-detail h3 {
  margin: 8px 0;
}
.detail-actions {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}
.hint-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
.node-desc {
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}
.node-props {
  margin-top: 10px;
}
.prop-row {
  font-size: 12px;
  margin: 4px 0;
}
.prop-key {
  color: #909399;
}
.prop-val {
  color: #303133;
}
.graph-item {
  padding: 8px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid transparent;
}
.graph-item:hover {
  background: #f5f7fa;
}
.graph-item.active {
  background: #ecf5ff;
  border-color: #409eff;
}
.g-name {
  font-size: 13px;
  font-weight: 500;
}
.g-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
