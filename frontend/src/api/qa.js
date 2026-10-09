import api from './index'

/**
 * 深度问答 (RAG) 相关 API
 * 对应契约 §2
 */

/**
 * 发起问答
 * @param {Object} payload { question, document_ids, mode, top_k, include_citations }
 */
export function askQuestion(payload) {
  return api.post('/qa/ask', payload)
}

/**
 * 按维度对比多篇文献
 * @param {Object} payload { document_ids, dimension }
 */
export function compareDocuments(payload) {
  return api.post('/qa/compare', payload)
}
