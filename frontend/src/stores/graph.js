import { defineStore } from 'pinia'
import {
  buildGraph,
  getGraph,
  listGraphs,
  deleteGraph,
  updateGraphNode,
  deleteGraphNode,
  createGraphNode,
  createGraphEdge
} from '../api/graph'

/**
 * 知识图谱状态管理
 * 维护图谱列表、当前图谱数据（节点/边）、构建状态与类型筛选
 */
export const useGraphStore = defineStore('graph', {
  state: () => ({
    graphList: [],           // 已有图谱列表
    currentGraphId: null,
    nodes: [],               // ECharts 节点数据
    links: [],               // ECharts 边数据
    stats: { nodes: 0, relationships: 0 },
    building: false,
    loading: false,
    // 类型筛选：默认全部显示
    visibleTypes: {
      concept: true,
      algorithm: true,
      dataset: true,
      metric: true,
      conclusion: true
    }
  }),

  actions: {
    /** 拉取已有图谱列表 */
    async fetchGraphList() {
      try {
        const res = await listGraphs()
        this.graphList = res.graphs || []
      } catch (err) {
        console.error('获取图谱列表失败:', err)
        this.graphList = []
      }
    },

    /** 构建新图谱 */
    async build(payload) {
      this.building = true
      try {
        const res = await buildGraph(payload)
        // 构建完成后自动加载图谱数据
        await this.loadGraph(res.graph_id)
        await this.fetchGraphList()
        return res
      } finally {
        this.building = false
      }
    },

    /** 加载指定图谱的节点与边 */
    async loadGraph(graphId) {
      this.loading = true
      try {
        const res = await getGraph(graphId)
        this.currentGraphId = res.graph_id
        this.nodes = res.nodes || []
        this.links = res.links || []
        this.stats = res.stats || { nodes: 0, relationships: 0 }
      } catch (err) {
        console.error('加载图谱失败:', err)
        this.nodes = []
        this.links = []
      } finally {
        this.loading = false
      }
    },

    /** 删除图谱 */
    async removeGraph(graphId) {
      try {
        await deleteGraph(graphId)
        this.graphList = this.graphList.filter(g => g.graph_id !== graphId)
        if (this.currentGraphId === graphId) {
          this.currentGraphId = null
          this.nodes = []
          this.links = []
        }
      } catch (err) {
        console.error('删除图谱失败:', err)
        throw err
      }
    },

    /** 切换节点类型可见性 */
    toggleType(type) {
      this.visibleTypes[type] = !this.visibleTypes[type]
    },

    // ==================== P1-3 图谱节点 / 关系编辑 ====================
    // 约定：所有写操作完成后重新拉取当前图谱，刷新本地 nodes/links 并触发热渲染

    /**
     * 更新节点属性
     * @param {String} nodeId 节点 ID
     * @param {Object} data { name?, description?, type? }
     * @returns {Promise<Object>} 更新后的节点
     */
    async updateNode(nodeId, data) {
      const res = await updateGraphNode(this.currentGraphId, nodeId, data)
      await this.loadGraph(this.currentGraphId)
      return res
    },

    /**
     * 删除节点
     * @param {String} nodeId 节点 ID
     * @returns {Promise<Object>} { deleted: true }
     */
    async removeNode(nodeId) {
      const res = await deleteGraphNode(this.currentGraphId, nodeId)
      await this.loadGraph(this.currentGraphId)
      return res
    },

    /**
     * 新建节点
     * @param {Object} data { name, description, type }
     * @returns {Promise<Object>} 新节点 { id, label, type, properties }
     */
    async addNode(data) {
      const res = await createGraphNode(this.currentGraphId, data)
      await this.loadGraph(this.currentGraphId)
      return res
    },

    /**
     * 新建关系（边）
     * @param {Object} data { source, target, relation }
     * @returns {Promise<Object>} { created: true }
     */
    async addEdge(data) {
      const res = await createGraphEdge(this.currentGraphId, data)
      await this.loadGraph(this.currentGraphId)
      return res
    }
  }
})
