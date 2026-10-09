import api from './index'

/**
 * 综述生成相关 API
 * 对应契约 §4
 */

/**
 * 生成综述
 * @param {Object} payload { document_ids, topic, sections }
 */
export function generateReview(payload) {
  return api.post('/review/generate', payload)
}

/** 获取综述完整内容 */
export function getReview(reviewId) {
  return api.get(`/review/${reviewId}`)
}

/**
 * 导出综述为文件（P1-5）
 * 注意：导出接口返回文件流，使用 responseType: 'blob'，
 * 返回的是 Blob 对象，调用方需自行用 URL.createObjectURL 触发下载。
 * @param {String} reviewId 综述 ID
 * @param {String} format 导出格式 'md' | 'docx'
 * @returns {Promise<Blob>} 文件二进制流
 */
export function exportReview(reviewId, format) {
  return api.get(`/review/${reviewId}/export`, {
    params: { format },
    responseType: 'blob'
  })
}
