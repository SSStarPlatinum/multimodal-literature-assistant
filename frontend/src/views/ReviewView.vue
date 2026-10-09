<template>
  <div class="page-container">
    <h2 class="page-title">综述生成</h2>

    <el-row :gutter="16">
      <!-- 左侧：配置 -->
      <el-col :span="6">
        <el-card shadow="never">
          <template #header><span>生成配置</span></template>
          <DocumentSelector
            :documents="docStore.documents"
            :selected-ids="selectedDocIds"
            label="选择文献"
            @update:selected-ids="selectedDocIds = $event"
          />
          <el-divider />
          <div class="form-item">
            <label>综述主题</label>
            <el-input v-model="topic" placeholder="例如：多模态大模型研究综述" />
          </div>
          <div class="form-item">
            <label>综述章节</label>
            <el-checkbox-group v-model="selectedSections">
              <el-checkbox value="background">研究背景</el-checkbox>
              <el-checkbox value="methods">方法分类</el-checkbox>
              <el-checkbox value="datasets">数据集</el-checkbox>
              <el-checkbox value="challenges">挑战</el-checkbox>
              <el-checkbox value="future">未来方向</el-checkbox>
            </el-checkbox-group>
          </div>
          <el-button
            type="primary"
            style="width: 100%"
            :loading="generating"
            :disabled="selectedDocIds.length === 0 || !topic.trim()"
            @click="generate"
          >
            生成综述
          </el-button>
        </el-card>
      </el-col>

      <!-- 右侧：结果展示 -->
      <el-col :span="18">
        <el-card shadow="never">
          <template #header>
            <div class="card-header">
              <span>{{ result?.title || '综述结果' }}</span>
              <!-- P1-5：导出按钮组 -->
              <el-button-group v-if="result && reviewId">
                <el-button
                  size="small"
                  :loading="exportingMd"
                  @click="doExport('md')"
                >导出 Markdown</el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="exportingDocx"
                  @click="doExport('docx')"
                >导出 Word</el-button>
              </el-button-group>
            </div>
          </template>
          <LoadingSpinner v-if="generating" text="正在生成综述，请稍候（可能需要较长时间）..." />
          <el-empty v-else-if="!result" description="选择文献与主题后点击生成" />

          <div v-else class="review-result">
            <!-- 大纲（可折叠章节） -->
            <h3 class="section-title">综述大纲</h3>
            <el-collapse v-model="activeSections">
              <el-collapse-item
                v-for="(item, i) in result.outline || []"
                :key="i"
                :name="String(i)"
                :title="item.section"
              >
                <ul>
                  <li v-for="(point, j) in item.key_points || []" :key="j">{{ point }}</li>
                </ul>
              </el-collapse-item>
            </el-collapse>

            <!-- 核心观点卡片 -->
            <h3 class="section-title">核心观点</h3>
            <el-row :gutter="12">
              <el-col v-for="(v, i) in result.core_views || []" :key="i" :span="12">
                <el-card shadow="hover" class="view-card">
                  <p class="view-text">{{ v.view }}</p>
                  <div class="view-evidence">依据：{{ v.evidence }}</div>
                  <div class="view-docs">
                    <el-tag
                      v-for="(id, k) in v.supporting_docs || []"
                      :key="k"
                      size="small"
                      type="primary"
                      style="margin: 2px"
                    >
                      {{ docTitle(id) }}
                    </el-tag>
                  </div>
                </el-card>
              </el-col>
            </el-row>

            <!-- 研究缺口 -->
            <h3 class="section-title">研究缺口</h3>
            <div
              v-for="(g, i) in result.research_gaps || []"
              :key="i"
              class="gap-item"
            >
              <el-tag :type="severityType(g.severity)" effect="dark" style="color:#fff">
                {{ severityLabel(g.severity) }}
              </el-tag>
              <div class="gap-content">
                <p class="gap-desc">{{ g.gap }}</p>
                <p class="gap-suggestion">建议方向：{{ g.suggested_direction }}</p>
              </div>
            </div>

            <!-- 发展脉络时间线 -->
            <h3 class="section-title">发展脉络</h3>
            <el-timeline>
              <el-timeline-item
                v-for="(t, i) in result.evolution_timeline || []"
                :key="i"
                :timestamp="t.year"
                placement="top"
              >
                <div class="timeline-event">
                  {{ t.event }}
                  <el-tag v-if="t.document_id" size="small" style="margin-left: 6px">
                    {{ docTitle(t.document_id) }}
                  </el-tag>
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useDocumentStore } from '../stores/document'
import { generateReview, exportReview } from '../api/review'
import DocumentSelector from '../components/DocumentSelector.vue'
import LoadingSpinner from '../components/LoadingSpinner.vue'

const docStore = useDocumentStore()

const selectedDocIds = ref([])
const topic = ref('')
const selectedSections = ref(['background', 'methods', 'datasets', 'challenges', 'future'])
const generating = ref(false)
const result = ref(null)
const activeSections = ref(['0'])

// P1-5：导出状态
const exportingMd = ref(false)
const exportingDocx = ref(false)

/** 当前综述 ID（兼容 review_id / id 字段） */
const reviewId = computed(() => result.value?.review_id || result.value?.id || null)

/** 生成综述 */
async function generate() {
  generating.value = true
  try {
    const res = await generateReview({
      document_ids: selectedDocIds.value,
      topic: topic.value.trim(),
      sections: selectedSections.value
    })
    result.value = res
    activeSections.value = (res.outline || []).map((_, i) => String(i))
    ElMessage.success('综述生成完成')
  } catch (err) {
    // 拦截器已提示
  } finally {
    generating.value = false
  }
}

/** 根据 document_id 找到文献标题 */
function docTitle(id) {
  const d = docStore.documents.find(x => x.document_id === id)
  return d ? (d.title || d.filename) : id?.slice(0, 8)
}

// ==================== P1-5 导出综述 ====================

/**
 * 导出综述为文件并触发浏览器下载
 * @param {'md'|'docx'} format 导出格式
 */
async function doExport(format) {
  if (!reviewId.value) {
    ElMessage.warning('暂无可导出的综述')
    return
  }
  const loadingRef = format === 'md' ? exportingMd : exportingDocx
  loadingRef.value = true
  try {
    // exportReview 返回 Blob（拦截器已解包 response.data）
    const blob = await exportReview(reviewId.value, format)
    // 构造下载文件名：{综述标题}.md / .docx
    const title = (result.value?.title || '综述').replace(/[\\/:*?"<>|]/g, '_')
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${title}.${format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (err) {
    // 拦截器已提示
  } finally {
    loadingRef.value = false
  }
}

function severityType(s) {
  if (s === 'high') return 'danger'
  if (s === 'medium') return 'warning'
  return 'info'
}
function severityLabel(s) {
  if (s === 'high') return '高'
  if (s === 'medium') return '中'
  return '低'
}

onMounted(() => docStore.fetchDocuments())
</script>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.form-item {
  margin-bottom: 12px;
}
.form-item label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.form-item .el-checkbox-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.section-title {
  margin: 18px 0 10px;
  font-size: 16px;
  border-left: 4px solid #409eff;
  padding-left: 8px;
}
.view-card {
  margin-bottom: 10px;
}
.view-text {
  font-size: 13px;
  line-height: 1.6;
}
.view-evidence {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
.view-docs {
  margin-top: 6px;
}
.gap-item {
  display: flex;
  gap: 10px;
  padding: 10px;
  background: #fdf6ec;
  border-radius: 6px;
  margin-bottom: 8px;
}
.gap-content {
  flex: 1;
}
.gap-desc {
  font-size: 13px;
}
.gap-suggestion {
  font-size: 12px;
  color: #67c23a;
  margin-top: 4px;
}
.timeline-event {
  font-size: 13px;
}
</style>
