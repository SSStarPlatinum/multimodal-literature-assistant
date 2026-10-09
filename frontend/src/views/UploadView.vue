<template>
  <div class="page-container">
    <h2 class="page-title">文献上传与解析</h2>

    <el-row :gutter="16">
      <!-- 左侧：上传区 + 解析选项 -->
      <el-col :span="10">
        <el-card shadow="never">
          <template #header><span>上传文献</span></template>

          <!-- 任务进行中提示 -->
          <p v-if="isProcessing" class="processing-hint">正在解析中，请稍候...</p>

          <!-- 拖拽上传区域 -->
          <div
            class="drop-zone"
            :class="{ dragover: dragOver, disabled: uploading || docStore.taskPolling }"
            @dragover.prevent="!isProcessing && (dragOver = true)"
            @dragleave.prevent="dragOver = false"
            @drop.prevent="!isProcessing && onDrop($event)"
            @click="!isProcessing && triggerSelect()"
          >
            <el-icon :size="40" color="#c0c4cc"><UploadFilled /></el-icon>
            <p>拖拽文件到此处，或点击选择</p>
            <p class="hint">支持 PDF / PNG / JPG</p>
            <input
              ref="fileInput"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg"
              hidden
              @change="onFileChange"
            />
          </div>

          <!-- 解析选项 -->
          <div class="options">
            <el-checkbox v-model="options.parse_formula">解析公式 (LaTeX)</el-checkbox>
            <el-checkbox v-model="options.parse_figures">解析图表</el-checkbox>
            <el-checkbox v-model="options.parse_references">解析参考文献</el-checkbox>
          </div>

          <!-- 解析进度（异步任务） -->
          <div v-if="uploading || docStore.taskPolling" class="parse-progress">
            <el-progress
              :percentage="displayProgress"
              :stroke-width="14"
              :status="progressStatus"
              style="margin-top: 12px"
            />
            <div class="progress-step">
              <el-icon v-if="docStore.taskStatus?.status === 'PROCESSING'" class="is-loading"><Loading /></el-icon>
              <span>{{ currentStepText }}</span>
            </div>
            <!-- 失败错误信息 -->
            <el-alert
              v-if="docStore.taskStatus?.status === 'FAILURE'"
              :title="docStore.taskStatus.error || '解析失败'"
              type="error"
              :closable="false"
              show-icon
              style="margin-top: 8px"
            />
          </div>
        </el-card>

        <!-- 已上传文献列表（P1-4：搜索 / 标签筛选 / 批量操作） -->
        <el-card shadow="never" style="margin-top: 16px">
          <template #header>
            <div class="card-header">
              <span>已上传文献</span>
              <el-button size="small" @click="loadDocs">刷新</el-button>
            </div>
          </template>

          <!-- 搜索框 + 标签筛选 -->
          <div class="list-toolbar">
            <el-input
              v-model="searchKeyword"
              size="small"
              placeholder="按标题 / 文件名关键词搜索"
              clearable
              :prefix-icon="Search"
              style="flex: 1"
              @input="onSearchInput"
              @clear="onFilterChange"
            />
            <el-select
              v-model="filterTag"
              size="small"
              placeholder="标签筛选"
              clearable
              style="width: 140px"
              @change="onFilterChange"
            >
              <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
            </el-select>
          </div>

          <el-table
            ref="tableRef"
            :data="docStore.documents"
            size="small"
            @row-click="onSelectDoc"
            @selection-change="onSelectionChange"
            stripe
            style="margin-top: 8px"
          >
            <el-table-column type="selection" width="40" />
            <el-table-column prop="title" label="标题" show-overflow-tooltip />
            <el-table-column label="标签" min-width="120">
              <template #default="{ row }">
                <el-tag
                  v-for="t in row.tags || []"
                  :key="t"
                  size="small"
                  class="tag-cell"
                  @click.stop="openTagEditor(row)"
                >{{ t }}</el-tag>
                <el-button
                  v-if="!(row.tags || []).length"
                  size="small"
                  text
                  @click.stop="openTagEditor(row)"
                >+ 标签</el-button>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="70">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="danger"
                  link
                  @click.stop="onDelete(row.document_id)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 批量操作栏 -->
          <div class="batch-bar">
            <span class="batch-count">已选 {{ docStore.selectedIds.length }} 篇</span>
            <el-button
              size="small"
              type="danger"
              :disabled="docStore.selectedIds.length === 0"
              :loading="batchBusy"
              @click="onBatchDelete"
            >批量删除</el-button>
            <el-button
              size="small"
              type="primary"
              :disabled="docStore.selectedIds.length === 0"
              :loading="batchBuildLoading"
              @click="onBatchBuildGraph"
            >批量构建图谱</el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：解析结果展示 -->
      <el-col :span="14">
        <el-card shadow="never">
          <template #header><span>解析结果</span></template>
          <LoadingSpinner v-if="docStore.loading" text="正在加载解析结果..." />
          <div v-else-if="!docStore.currentDocument" class="empty-result">
            点击左侧文献查看解析结果
          </div>
          <div v-else class="result">
            <!-- 元信息 -->
            <div class="meta">
              <h3>{{ docStore.currentDocument.metadata?.title || docStore.currentDocument.filename }}</h3>
              <p class="authors">{{ (docStore.currentDocument.metadata?.authors || []).join(', ') }}</p>
              <p class="abstract">{{ docStore.currentDocument.metadata?.abstract }}</p>
              <!-- 解析时间（P1-4） -->
              <p v-if="docStore.currentDocument.metadata?.parsed_at" class="parsed-at">
                解析时间：{{ docStore.currentDocument.metadata.parsed_at }}
              </p>
              <div class="stats">
                <el-tag>文本块 {{ docStore.currentDocument.stats?.text_blocks || 0 }}</el-tag>
                <el-tag>公式 {{ docStore.currentDocument.stats?.formulas || 0 }}</el-tag>
                <el-tag>图表 {{ docStore.currentDocument.stats?.figures || 0 }}</el-tag>
                <el-tag>参考文献 {{ docStore.currentDocument.stats?.references || 0 }}</el-tag>
              </div>
            </div>

            <el-tabs v-model="activeTab">
              <!-- 文本块（P1-2：支持高亮定位） -->
              <el-tab-pane label="文本块" name="text">
                <div class="block-list">
                  <div
                    v-for="(block, i) in docStore.currentDocument.text_blocks || []"
                    :key="i"
                    class="text-block"
                    :class="{ 'chunk-highlight': highlightedChunk === chunkIdOf(block, i) }"
                    :data-chunk-id="chunkIdOf(block, i)"
                  >
                    <div class="block-header">[{{ i + 1 }}] p.{{ block.page }}</div>
                    <p>{{ block.content || block.text || block }}</p>
                  </div>
                </div>
              </el-tab-pane>

              <!-- 公式（P1-1：KaTeX 渲染 + 原文对照 + 识别来源） -->
              <el-tab-pane label="公式" name="formula">
                <el-empty v-if="!(docStore.currentDocument.formulas || []).length" description="无公式" />
                <div
                  v-for="(f, i) in docStore.currentDocument.formulas || []"
                  :key="i"
                  class="formula-item"
                >
                  <div class="formula-head">
                    <span class="formula-label">
                      公式 {{ f.formula_number || (i + 1) }}
                    </span>
                    <el-tag v-if="f.page != null" size="small" type="info">p.{{ f.page }}</el-tag>
                    <el-tag v-if="f.detect_reason" size="small" :type="f.detect_reason === 'vl' ? 'success' : 'primary'">
                      {{ f.detect_reason === 'vl' ? 'VL识别' : (f.detect_reason === 'text' ? '标号检测' : '正则检测') }}
                    </el-tag>
                  </div>
                  <!-- 默认显示公式原图 -->
                  <div class="formula-image-wrap">
                    <img v-if="f.image_url" :src="f.image_url" alt="公式原文" class="formula-main-img" />
                    <pre v-else class="formula-fallback-text">{{ f.original }}</pre>
                  </div>
                  <!-- 查看LaTeX格式（折叠/展开） -->
                  <div v-if="typeof f !== 'string' && f.latex" class="formula-latex-toggle">
                    <el-button size="small" text @click="toggleFormula(i)">
                      {{ expandedFormula === i ? '收起LaTeX' : '查看LaTeX格式' }}
                    </el-button>
                    <pre v-show="expandedFormula === i" class="latex-text">{{ f.latex }}</pre>
                  </div>
                </div>
              </el-tab-pane>

              <!-- 图表 -->
              <el-tab-pane label="图表" name="figures">
                <el-empty v-if="!(docStore.currentDocument.figures || []).length" description="无图表" />
                <div v-else class="figure-grid">
                  <div v-for="(fig, i) in docStore.currentDocument.figures" :key="i" class="figure-item">
                    <img
                      :src="fig.url || fig.image_url"
                      :alt="fig.caption || 'figure'"
                      @error="onImgError($event, fig)"
                    />
                    <p v-if="fig.caption" class="fig-caption">{{ fig.caption }}</p>
                    <p v-else class="fig-caption">Figure {{ i + 1 }} (page {{ fig.page }})</p>
                  </div>
                </div>
              </el-tab-pane>

              <!-- 参考文献 -->
              <el-tab-pane label="参考文献" name="refs">
                <ol class="ref-list">
                  <li v-for="(ref, i) in docStore.currentDocument.references || []" :key="i">
                    <span v-if="ref.number" class="ref-num">[{{ ref.number }}]</span>
                    {{ typeof ref === 'string' ? ref : (ref.raw || ref.text || ref.title) }}
                    <span v-if="ref.year" class="ref-year">({{ ref.year }})</span>
                  </li>
                </ol>
              </el-tab-pane>
            </el-tabs>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 标签编辑对话框（P1-4） -->
    <el-dialog v-model="tagDialogVisible" title="编辑标签" width="420px">
      <div class="tag-editor">
        <el-tag
          v-for="(t, i) in editTags"
          :key="i"
          closable
          size="default"
          style="margin: 0 6px 6px 0"
          @close="editTags.splice(i, 1)"
        >{{ t }}</el-tag>
        <el-input
          v-model="newTag"
          size="default"
          placeholder="输入后回车添加"
          style="width: 200px"
          @keyup.enter="addTag"
        />
      </div>
      <template #footer>
        <el-button @click="tagDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="tagSaving" @click="saveTags">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, Search } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { useDocumentStore } from '../stores/document'
import FormulaRenderer from '../components/FormulaRenderer.vue'
import LoadingSpinner from '../components/LoadingSpinner.vue'

const docStore = useDocumentStore()
const route = useRoute()

const dragOver = ref(false)
const fileInput = ref(null)
const uploading = ref(false)
const progress = ref(0)
const activeTab = ref('text')

// P1-4：列表搜索 / 标签筛选 / 批量选择
const searchKeyword = ref('')
const filterTag = ref('')
const tableRef = ref(null)
const batchBusy = ref(false)
const batchBuildLoading = ref(false)

// P1-2：问答溯源高亮定位
const highlightedChunk = ref('')

// P1-1：公式原文对照展开项
const expandedFormula = ref(-1)

// P1-4：标签编辑对话框
const tagDialogVisible = ref(false)
const tagSaving = ref(false)
const editingDoc = ref(null)
const editTags = ref([])
const newTag = ref('')

const options = reactive({
  parse_formula: true,
  parse_figures: true,
  parse_references: true
})

// 是否正在处理（上传中或轮询中）
const isProcessing = computed(() => uploading.value || docStore.taskPolling)

// 显示的进度百分比：优先使用异步任务进度，否则回退到上传进度
const displayProgress = computed(() => {
  if (docStore.taskStatus) {
    return docStore.taskStatus.progress || 0
  }
  return progress.value
})

// 进度条状态：失败/成功/进行中
const progressStatus = computed(() => {
  if (docStore.taskStatus?.status === 'FAILURE') return 'exception'
  if (docStore.taskStatus?.status === 'SUCCESS') return 'success'
  return ''
})

// 当前解析步骤中文映射
const stepLabels = {
  'upload_complete': '上传完成',
  'text_extraction': '文本提取',
  'formula_recognition': '公式识别',
  'figure_extraction': '图表提取',
  'references': '参考文献提取',
  'summary_generation': '摘要生成',
  'completed': '解析完成',
  'running': '处理中',
  'failed': '解析失败',
  '': '等待中'
}
// 当前步骤中文显示文本
const currentStepText = computed(() => {
  const step = docStore.taskStatus?.current_step || ''
  return stepLabels[step] || step || '处理中'
})

// 聚合所有文档标签（用于标签筛选下拉）
const allTags = computed(() => {
  const set = new Set()
  docStore.documents.forEach(d => (d.tags || []).forEach(t => set.add(t)))
  return [...set]
})

/** 取文本块的 chunk id（兼容多种字段名） */
function chunkIdOf(block, i) {
  if (block && typeof block === 'object') {
    return block.chunk_id || block.id || block.block_id || `block-${i}`
  }
  return `block-${i}`
}

/** 点击触发文件选择 */
function triggerSelect() {
  fileInput.value?.click()
}

function onFileChange(e) {
  const file = e.target.files?.[0]
  if (file) doUpload(file)
  e.target.value = ''
}

/** 拖拽放下 */
function onDrop(e) {
  dragOver.value = false
  const file = e.dataTransfer.files?.[0]
  if (file) doUpload(file)
}

/** 执行上传：提交后由 store 接管轮询解析进度 */
async function doUpload(file) {
  uploading.value = true
  progress.value = 0
  try {
    const res = await docStore.startUploadAndPoll(file, options)
    ElMessage.success(`文件 ${res.filename} 已提交解析`)
  } catch (err) {
    // 上传阶段失败（拦截器已提示），重置轮询状态
    docStore.cancelPolling()
  } finally {
    uploading.value = false
  }
}

/** 列表行点击查看详情 */
function onSelectDoc(row) {
  docStore.fetchDetail(row.document_id)
}

async function onDelete(id) {
  await ElMessageBox.confirm('确定删除该文献？', '提示', { type: 'warning' })
  await docStore.removeDocument(id)
  ElMessage.success('已删除')
}

function loadDocs() {
  docStore.fetchDocuments()
}

function statusType(s) {
  if (s === 'completed') return 'success'
  if (s === 'parsing') return 'warning'
  if (s === 'failed') return 'danger'
  return 'info'
}

/** 图片加载失败时显示占位 */
function onImgError(e, fig) {
  e.target.style.display = 'none'
  const parent = e.target.parentElement
  if (parent && !parent.querySelector('.img-placeholder')) {
    const ph = document.createElement('div')
    ph.className = 'img-placeholder'
    ph.textContent = `[图片加载失败] ${fig.caption || 'Figure'}`
    parent.insertBefore(ph, e.target.nextSibling)
  }
}

// ==================== P1-4 搜索 / 筛选 / 批量 ====================

let searchTimer = null
/** 搜索框输入（防抖） */
function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    docStore.search(searchKeyword.value, filterTag.value)
  }, 350)
}
/** 标签筛选变化 */
function onFilterChange() {
  docStore.search(searchKeyword.value, filterTag.value)
}

/** el-table 勾选变化，同步到 store */
function onSelectionChange(rows) {
  docStore.selectedIds = rows.map(r => r.document_id)
}

/** 批量删除 */
async function onBatchDelete() {
  if (docStore.selectedIds.length === 0) return
  await ElMessageBox.confirm(
    `确定删除选中的 ${docStore.selectedIds.length} 篇文献？该操作不可恢复`,
    '批量删除',
    { type: 'warning' }
  )
  batchBusy.value = true
  try {
    await docStore.batchDelete([...docStore.selectedIds])
    ElMessage.success('批量删除完成')
    tableRef.value?.clearSelection()
    docStore.clearSelection()
  } catch (err) {
    // 拦截器已提示
  } finally {
    batchBusy.value = false
  }
}

/** 批量构建图谱 */
async function onBatchBuildGraph() {
  if (docStore.selectedIds.length === 0) return
  await ElMessageBox.confirm(
    `将基于选中的 ${docStore.selectedIds.length} 篇文献构建知识图谱，是否继续？`,
    '批量构建图谱',
    { type: 'info' }
  )
  batchBuildLoading.value = true
  try {
    const res = await docStore.batchBuildGraph([...docStore.selectedIds])
    ElMessage.success(`图谱构建已提交，graph_id: ${res.graph_id || ''}`)
    tableRef.value?.clearSelection()
    docStore.clearSelection()
  } catch (err) {
    // 拦截器已提示
  } finally {
    batchBuildLoading.value = false
  }
}

/** 打开标签编辑对话框 */
function openTagEditor(row) {
  editingDoc.value = row
  editTags.value = [...(row.tags || [])]
  newTag.value = ''
  tagDialogVisible.value = true
}
/** 添加标签 */
function addTag() {
  const t = newTag.value.trim()
  if (t && !editTags.value.includes(t)) editTags.value.push(t)
  newTag.value = ''
}
/** 保存标签 */
async function saveTags() {
  if (!editingDoc.value) return
  tagSaving.value = true
  try {
    await docStore.updateTags(editingDoc.value.document_id, [...editTags.value])
    ElMessage.success('标签已更新')
    tagDialogVisible.value = false
  } catch (err) {
    // 拦截器已提示
  } finally {
    tagSaving.value = false
  }
}

// ==================== P1-1 公式原文展开 ====================

function toggleFormula(i) {
  expandedFormula.value = expandedFormula.value === i ? -1 : i
}

// ==================== P1-2 路由高亮定位 ====================

/** 根据路由 query 加载文档并滚动高亮目标文本块 */
async function applyHighlightFromRoute() {
  const docId = route.query.highlight_doc
  const chunkId = route.query.highlight_chunk
  if (!docId) return
  // 加载目标文档详情
  await docStore.fetchDetail(docId)
  // 切换到文本块标签
  activeTab.value = 'text'
  highlightedChunk.value = chunkId || ''
  await nextTick()
  // 等待列表渲染后滚动定位并高亮
  setTimeout(() => {
    const el = document.querySelector(`[data-chunk-id="${chunkId}"]`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, 300)
}

onMounted(async () => {
  // 页面加载时清理可能残留的轮询状态
  docStore.cancelPolling()
  await docStore.fetchDocuments()
  await applyHighlightFromRoute()
})

// 从问答页跳转过来时（组件可能已挂载），监听 query 变化重新定位
watch(() => route.query, () => {
  applyHighlightFromRoute()
})
</script>

<style scoped>
.drop-zone {
  border: 2px dashed #dcdfe6;
  border-radius: 8px;
  padding: 30px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}
.drop-zone:hover,
.drop-zone.dragover {
  border-color: #409eff;
  background: #ecf5ff;
}
/* 任务进行中禁用拖拽上传区域 */
.drop-zone.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}
.processing-hint {
  color: #e6a23c;
  font-size: 13px;
  margin-bottom: 8px;
}
.progress-step {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
}
.parse-progress {
  margin-top: 4px;
}
.drop-zone p {
  margin-top: 8px;
  color: #606266;
}
.drop-zone .hint {
  font-size: 12px;
  color: #909399;
}
.options {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.list-toolbar {
  display: flex;
  gap: 8px;
}
.batch-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #f0f2f5;
}
.batch-count {
  font-size: 13px;
  color: #606266;
  margin-right: auto;
}
.tag-cell {
  margin: 2px 4px 2px 0;
  cursor: pointer;
}
.empty-result {
  padding: 40px;
  text-align: center;
  color: #909399;
}
.meta h3 {
  margin-bottom: 6px;
}
.authors {
  color: #606266;
  font-size: 13px;
}
.abstract {
  margin: 8px 0;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}
.parsed-at {
  font-size: 12px;
  color: #909399;
}
.stats {
  display: flex;
  gap: 6px;
  margin: 10px 0;
}
.block-list {
  max-height: 400px;
  overflow-y: auto;
}
.text-block {
  display: flex;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed #ebeef5;
  border-radius: 4px;
}
/* P1-2：高亮块（黄色背景 + 闪烁动画） */
.chunk-highlight {
  background: #fff3cd;
  animation: chunk-blink 1s ease-in-out 3;
}
@keyframes chunk-blink {
  0%, 100% { background: #fff3cd; }
  50% { background: #ffe69c; }
}
.block-header {
  color: #909399;
  font-size: 12px;
  flex-shrink: 0;
}
.formula-item {
  padding: 10px;
  border-bottom: 1px solid #f0f2f5;
  overflow-x: auto;
}
.formula-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.formula-label {
  font-size: 12px;
  color: #909399;
}
.formula-image-wrap {
  margin: 8px 0;
  text-align: center;
}
.formula-main-img {
  max-width: 100%;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 12px;
  background: #fff;
}
.formula-fallback-text {
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
  font-size: 13px;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
  text-align: left;
}
.formula-latex-toggle {
  margin-top: 4px;
}
.latex-text {
  background: #fef0f0;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  color: #f56c6c;
  white-space: pre-wrap;
  word-break: break-all;
  margin-top: 4px;
}
.formula-original {
  margin-top: 6px;
}
.original-content {
  margin-top: 6px;
}
.formula-original-img {
  max-width: 100%;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 8px;
  background: #fff;
}
.original-text {
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-all;
}
.figure-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.figure-item img {
  max-width: 100%;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}
.fig-caption {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.ref-list li {
  margin: 6px 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}
.ref-num {
  color: #409eff;
  font-weight: 600;
  margin-right: 4px;
}
.ref-year {
  color: #909399;
  margin-left: 4px;
}
.img-placeholder {
  padding: 20px;
  text-align: center;
  color: #909399;
  background: #f5f7fa;
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  font-size: 12px;
}
.tag-editor {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}
</style>
