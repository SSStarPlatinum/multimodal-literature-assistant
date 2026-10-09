import api from './index'

/**
 * 知识图谱相关 API
 * 对应契约 §3
 */

/**
 * 构建知识图谱
 * @param {Object} payload { document_ids, entity_types, relation_types }
 */
export function buildGraph(payload) {
  return api.post('/graph/build', payload)
}

/**
 * 查询图谱数据
 * @param {String} graphId
 * @param {Object} params { limit, node_type }
 */
export function getGraph(graphId, params = {}) {
  return api.get(`/graph/${graphId}`, { params })
}

/** 获取图谱列表 */
export function listGraphs() {
  return api.get('/graph/list')
}

/** 删除图谱 */
export function deleteGraph(graphId) {
  return api.delete(`/graph/${graphId}`)
}

/**
 * 更新节点属性（P1-3）
 * @param {String} graphId 图谱 ID
 * @param {String} nodeId 节点 ID
 * @param {Object} data 待更新字段 { name?, description?, type? }
 * @returns {Promise<Object>} 更新后的节点
 */
export function updateGraphNode(graphId, nodeId, data) {
  return api.put(`/graph/${graphId}/node/${nodeId}`, data)
}

/**
 * 删除节点（P1-3）
 * @param {String} graphId 图谱 ID
 * @param {String} nodeId 节点 ID
 * @returns {Promise<Object>} { deleted: true }
 */
export function deleteGraphNode(graphId, nodeId) {
  return api.delete(`/graph/${graphId}/node/${nodeId}`)
}

/**
 * 新建节点（P1-3）
 * @param {String} graphId 图谱 ID
 * @param {Object} data { name, description, type }
 * @returns {Promise<Object>} 新节点 { id, label, type, properties }
 */
export function createGraphNode(graphId, data) {
  return api.post(`/graph/${graphId}/node`, data)
}

/**
 * 新建关系（边）（P1-3）
 * @param {String} graphId 图谱 ID
 * @param {Object} data { source, target, relation }
 * @returns {Promise<Object>} { created: true }
 */
export function createGraphEdge(graphId, data) {
  return api.post(`/graph/${graphId}/edge`, data)
}
