import api from './index'

/**
 * 文献上传与解析相关 API
 * 对应契约 §1
 */

/**
 * 上传并解析文献
 * @param {File} file PDF/图片文件
 * @param {Object} options { parse_formula, parse_figures, parse_references }
 * @param {Function} onProgress 上传进度回调 (percent)
 */
export function uploadDocument(file, options = {}, onProgress = null) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('parse_formula', options.parse_formula !== false)
  formData.append('parse_figures', options.parse_figures !== false)
  formData.append('parse_references', options.parse_references !== false)

  return api.post('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) {
        onProgress(Math.round((e.loaded * 100) / e.total))
      }
    }
  })
}

/** 获取文档列表 */
export function listDocuments() {
  return api.get('/documents')
}

/** 获取文档完整解析结果 */
export function getDocumentDetail(documentId) {
  return api.get(`/documents/${documentId}`)
}

/** 删除文档 */
export function deleteDocument(documentId) {
  return api.delete(`/documents/${documentId}`)
}

/**
 * 更新文档标签（P1-4）
 * @param {String} documentId 文档 ID
 * @param {String[]} tags 新的标签数组（整体覆盖）
 * @returns {Promise<Object>} { updated: true }
 */
export function updateDocumentTags(documentId, tags) {
  return api.put(`/documents/${documentId}/tags`, { tags })
}

/**
 * 按关键词 / 标签搜索文档（P1-4）
 * @param {Object} params { keyword, tag }
 * @returns {Promise<Object>} { documents: [...], total: n }
 */
export function searchDocuments(params = {}) {
  return api.get('/documents/search', { params })
}

/**
 * 批量删除文档（P1-4）
 * @param {String[]} documentIds 待删除文档 ID 列表
 * @returns {Promise<Object>} { deleted: n }
 */
export function batchDeleteDocuments(documentIds) {
  return api.delete('/documents/batch', { data: { document_ids: documentIds } })
}

/**
 * 批量构建知识图谱（P1-4）
 * @param {String[]} documentIds 参与构建的文档 ID 列表
 * @returns {Promise<Object>} { graph_id, status, stats }
 */
export function batchBuildGraph(documentIds) {
  return api.post('/documents/batch/build-graph', { document_ids: documentIds })
}

/**
 * 获取单个文本块（chunk）详情（P1-2 问答溯源）
 * @param {String} docId 文档 ID
 * @param {String} chunkId 文本块 ID
 * @returns {Promise<Object>} 块详情 { document_id, chunk_id, text, page, paragraph_index, char_offset, filename }
 */
export function getChunkDetail(docId, chunkId) {
  return api.get(`/document/${docId}/chunk/${chunkId}`)
}
