<template>
  <div class="page-container">
    <h2 class="page-title">深度问答</h2>

    <el-row :gutter="16">
      <!-- 左侧：文献选择 + 检索模式 -->
      <el-col :span="6">
        <el-card shadow="never">
          <template #header><span>检索范围</span></template>
          <DocumentSelector
            :documents="docStore.documents"
            :selected-ids="selectedDocIds"
            label="选择文献"
            @update:selected-ids="selectedDocIds = $event"
          />

          <el-divider />

          <div class="mode-block">
            <div class="block-label">检索模式</div>
            <el-radio-group v-model="mode" style="width: 100%">
              <el-radio value="summary">摘要检索</el-radio>
              <el-radio value="fulltext">全文细查</el-radio>
              <el-radio value="hybrid">分层混合</el-radio>
            </el-radio-group>
          </div>

          <el-divider />

          <!-- 对比模式 -->
          <div class="mode-block">
            <div class="block-label">对比模式</div>
            <el-select v-model="compareDim" placeholder="选择对比维度" clearable style="width: 100%">
              <el-option label="方法" value="method" />
              <el-option label="数据集" value="dataset" />
              <el-option label="指标" value="metric" />
              <el-option label="结论" value="conclusion" />
            </el-select>
            <el-button
              type="primary"
              plain
              style="width: 100%; margin-top: 8px"
              :disabled="selectedDocIds.length < 2"
              :loading="comparing"
              @click="doCompare"
            >
              按维度对比
            </el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 中间：问答区 -->
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>对话</span>
              <el-button size="small" @click="qaStore.clearHistory()">清空历史</el-button>
            </div>
          </template>

          <div class="chat-area">
            <el-empty v-if="qaStore.history.length === 0" description="输入问题开始提问" />
            <div v-for="item in qaStore.history" :key="item.id" class="qa-turn">
              <!-- 问题 -->
              <div class="q-bubble">
                <el-icon><QuestionFilled /></el-icon>
                <span>{{ item.question }}</span>
              </div>
              <!-- 回答 -->
              <div class="a-bubble">
                <el-icon><MagicStick /></el-icon>
                <div class="answer-text markdown-body" v-html="renderMarkdown(item.answer)"></div>
                <!-- 检索信息 -->
                <div v-if="item.retrieval_info" class="retrieval-info">
                  <el-tag size="small">模式: {{ item.retrieval_info.mode }}</el-tag>
                  <el-tag size="small">摘要命中: {{ item.retrieval_info.summary_hits }}</el-tag>
                  <el-tag size="small">全文命中: {{ item.retrieval_info.fulltext_hits }}</el-tag>
                  <el-tag size="small">耗时: {{ item.retrieval_info.latency_ms }}ms</el-tag>
                </div>
              </div>
              <!-- 引用来源 -->
              <div v-if="item.sources?.length" class="sources">
                <div class="sources-title">引用来源 ({{ item.sources.length }})</div>
                <div
                  v-for="(src, i) in item.sources"
                  :key="i"
                  class="source-card"
                >
                  <div class="source-head">
                    <el-tag size="small" :type="src.retrieval_layer === 'summary' ? 'success' : 'warning'">
                      {{ src.retrieval_layer }}
                    </el-tag>
                    <span class="source-file">{{ src.filename }}</span>
                    <!-- 页码：page 为空或 0 时不显示 -->
                    <span v-if="src.page" class="source-page">p.{{ src.page }}</span>
                    <!-- 段落序号（P1-2） -->
                    <span v-if="src.paragraph_index != null" class="source-page">
                      段落 {{ src.paragraph_index + 1 }}
                    </span>
                    <el-tag size="small" type="info">相似度 {{ (src.score * 100).toFixed(1) }}%</el-tag>
                    <!-- 查看原文（P1-2 引用跳转） -->
                    <el-button
                      v-if="canJumpToSource(src)"
                      size="small"
                      type="primary"
                      link
                      @click="viewSource(src)"
                    >查看原文</el-button>
                  </div>
                  <p class="source-text">{{ src.text }}</p>
                </div>
              </div>
            </div>
            <LoadingSpinner v-if="qaStore.asking" text="正在检索与生成回答..." />
          </div>

          <!-- 输入框 -->
          <div class="input-area">
            <el-input
              v-model="question"
              type="textarea"
              :rows="2"
              placeholder="请输入问题，例如：对比两篇文献的方法差异"
              @keydown.enter.exact.prevent="sendQuestion"
            />
            <el-button
              type="primary"
              :loading="qaStore.asking"
              :disabled="!question.trim() || selectedDocIds.length === 0"
              @click="sendQuestion"
            >
              发送
            </el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：对比结果 / 历史 -->
      <el-col :span="6">
        <el-card shadow="never">
          <template #header><span>对比结果</span></template>
          <el-empty v-if="!comparison" description="选择维度并点击对比" />
          <div v-else class="comparison">
            <h4>{{ comparison.dimension }} 对比</h4>
            <div v-for="(it, i) in comparison.items" :key="i" class="cmp-item">
              <div class="cmp-title">{{ it.title }}</div>
              <p>{{ it.content }}</p>
            </div>
            <el-divider />
            <div class="cmp-section">
              <b>相似点</b>
              <el-tag v-for="(s, i) in comparison.similarities" :key="i" size="small" style="margin: 2px">
                {{ s }}
              </el-tag>
            </div>
            <div class="cmp-section">
              <b>差异点</b>
              <el-tag
                v-for="(d, i) in comparison.differences"
                :key="i"
                size="small"
                type="danger"
                style="margin: 2px"
              >{{ d }}</el-tag>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header><span>问答历史</span></template>
          <div class="history-list">
            <div
              v-for="(item, i) in qaStore.history"
              :key="item.id"
              class="history-item"
              @click="scrollToItem(item.id)"
            >
              <div class="h-q">{{ item.question }}</div>
              <div class="h-time">{{ item.time }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { marked } from 'marked'
import { useRouter } from 'vue-router'
import { useDocumentStore } from '../stores/document'
import { useQaStore } from '../stores/qa'
import { askQuestion, compareDocuments } from '../api/qa'
import DocumentSelector from '../components/DocumentSelector.vue'
import LoadingSpinner from '../components/LoadingSpinner.vue'

const docStore = useDocumentStore()
const qaStore = useQaStore()
const router = useRouter()

const selectedDocIds = ref([])
const mode = ref('hybrid')
const question = ref('')
const compareDim = ref('')
const comparing = ref(false)
const comparison = ref(null)

/** Markdown 渲染 */
function renderMarkdown(text) {
  if (!text) return ''
  return marked.parse(text, { breaks: true })
}

/** 发送问题 */
async function sendQuestion() {
  if (!question.value.trim() || selectedDocIds.value.length === 0) return
  const q = question.value.trim()
  question.value = ''
  qaStore.setAsking(true)
  try {
    const res = await askQuestion({
      question: q,
      document_ids: selectedDocIds.value,
      mode: mode.value,
      top_k: 5,
      include_citations: true
    })
    qaStore.addQaRecord({
      question: q,
      answer: res.answer,
      sources: res.sources,
      retrieval_info: res.retrieval_info,
      mode: mode.value,
      document_ids: selectedDocIds.value
    })
  } catch (err) {
    // 拦截器已提示
  } finally {
    qaStore.setAsking(false)
  }
}

/** 按维度对比 */
async function doCompare() {
  if (selectedDocIds.value.length < 2 || !compareDim.value) return
  comparing.value = true
  try {
    const res = await compareDocuments({
      document_ids: selectedDocIds.value,
      dimension: compareDim.value
    })
    comparison.value = res.comparison
  } catch (err) {
    // 拦截器已提示
  } finally {
    comparing.value = false
  }
}

function scrollToItem(id) {
  document.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ behavior: 'smooth' })
}

// ==================== P1-2 引用跳转 ====================

/** 取来源条目的文档 ID / 块 ID（兼容字段名） */
function sourceDocId(src) {
  return src.document_id || src.doc_id
}
function sourceChunkId(src) {
  return src.chunk_id || src.id
}
/** 是否具备跳转条件（同时有文档 ID 与块 ID） */
function canJumpToSource(src) {
  return !!(sourceDocId(src) && sourceChunkId(src))
}
/** 跳转到文献上传页并高亮对应原文块 */
function viewSource(src) {
  router.push({
    path: '/upload',
    query: {
      highlight_doc: sourceDocId(src),
      highlight_chunk: sourceChunkId(src)
    }
  })
}

onMounted(() => docStore.fetchDocuments())
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mode-block {
  margin-bottom: 8px;
}
.block-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.chat-area {
  min-height: 400px;
  max-height: 60vh;
  overflow-y: auto;
}
.qa-turn {
  margin-bottom: 16px;
}
.q-bubble {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  justify-content: flex-end;
  margin-bottom: 8px;
}
.q-bubble span {
  background: #409eff;
  color: #fff;
  padding: 8px 12px;
  border-radius: 8px;
  max-width: 80%;
}
.a-bubble {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 6px;
}
.answer-text {
  background: #f5f7fa;
  padding: 10px 12px;
  border-radius: 8px;
  max-width: 85%;
}
.retrieval-info {
  margin-top: 6px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.sources {
  margin-left: 24px;
  margin-top: 6px;
}
.sources-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.source-card {
  border-left: 3px solid #409eff;
  background: #fafcff;
  padding: 6px 10px;
  margin-bottom: 6px;
  border-radius: 0 4px 4px 0;
}
.source-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 12px;
}
.source-file {
  color: #303133;
  font-weight: 500;
}
.source-page {
  color: #909399;
}
.source-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
}
.input-area {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  align-items: flex-end;
}
.input-area .el-textarea {
  flex: 1;
}
.comparison h4 {
  margin-bottom: 8px;
}
.cmp-item {
  margin-bottom: 8px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
}
.cmp-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 4px;
}
.cmp-item p {
  font-size: 12px;
  color: #606266;
}
.cmp-section {
  margin: 8px 0;
}
.history-list {
  max-height: 300px;
  overflow-y: auto;
}
.history-item {
  padding: 8px;
  border-bottom: 1px solid #f0f2f5;
  cursor: pointer;
}
.history-item:hover {
  background: #f5f7fa;
}
.h-q {
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.h-time {
  font-size: 11px;
  color: #909399;
}
</style>
