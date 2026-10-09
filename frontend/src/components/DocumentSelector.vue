<template>
  <div class="document-selector">
    <div class="selector-header">
      <span class="label">{{ label }}</span>
      <span v-if="selectedIds.length > 0" class="count-badge">已选 {{ selectedIds.length }} 篇</span>
    </div>
    <div class="doc-list">
      <label
        v-for="doc in documents"
        :key="doc.document_id"
        class="doc-item"
        :class="{ active: selectedIds.includes(doc.document_id) }"
      >
        <input
          type="checkbox"
          :value="doc.document_id"
          :checked="selectedIds.includes(doc.document_id)"
          @change="toggle(doc.document_id)"
        />
        <div class="doc-meta">
          <div class="doc-title">{{ doc.title || doc.filename }}</div>
          <div class="doc-filename">{{ doc.filename }}</div>
        </div>
        <el-tag size="small" :type="statusType(doc.status)">{{ doc.status }}</el-tag>
      </label>
      <div v-if="documents.length === 0" class="empty-tip">
        暂无已上传文献，请先到「文献上传」页上传
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  documents: { type: Array, default: () => [] },
  selectedIds: { type: Array, default: () => [] },
  label: { type: String, default: '选择文献' }
})
const emit = defineEmits(['update:selectedIds'])

/** 切换选中状态 */
function toggle(id) {
  const next = props.selectedIds.includes(id)
    ? props.selectedIds.filter(x => x !== id)
    : [...props.selectedIds, id]
  emit('update:selectedIds', next)
}

function statusType(status) {
  if (status === 'completed') return 'success'
  if (status === 'parsing') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}
</script>

<style scoped>
.document-selector {
  width: 100%;
}
.selector-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.label {
  font-weight: 600;
}
.count-badge {
  color: #409eff;
  font-size: 12px;
}
.doc-list {
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 4px;
}
.doc-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}
.doc-item:hover {
  background: #f5f7fa;
}
.doc-item.active {
  background: #ecf5ff;
}
.doc-item input[type='checkbox'] {
  cursor: pointer;
}
.doc-meta {
  flex: 1;
  min-width: 0;
}
.doc-title {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.doc-filename {
  font-size: 12px;
  color: #909399;
}
.empty-tip {
  padding: 20px;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
</style>
