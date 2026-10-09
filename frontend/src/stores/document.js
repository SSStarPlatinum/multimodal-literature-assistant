import { defineStore } from 'pinia'
import {
  listDocuments,
  getDocumentDetail,
  deleteDocument,
  uploadDocument,
  updateDocumentTags,
  searchDocuments,
  batchDeleteDocuments,
  batchBuildGraph
} from '../api/document'
import { getTaskStatus } from '../api/task'

/**
 * 文档列表状态管理
 * 管理已上传文献的列表、当前选中详情、加载状态
 * 以及异步解析任务的轮询状态
 */
export const useDocumentStore = defineStore('document', {
  state: () => ({
    documents: [],          // 文档列表 [{document_id, filename, title, uploaded_at, status}]
    currentDocument: null,  // 当前查看详情的文档完整解析结果
    loading: false,
    total: 0,
    currentTaskId: null,      // 当前进行中的解析任务 ID
    taskStatus: null,         // 当前任务状态对象 { status, progress, current_step, error }
    taskPolling: false,       // 是否正在轮询
    // P1-4 文献管理增强
    searchKeyword: '',        // 列表搜索关键词
    filterTag: '',            // 标签筛选
    selectedIds: []           // 批量操作选中的文档 ID
  }),

  actions: {
    /** 拉取文档列表 */
    async fetchDocuments() {
      this.loading = true
      try {
        const res = await listDocuments()
        this.documents = res.documents || []
        this.total = res.total || this.documents.length
      } catch (err) {
        console.error('获取文档列表失败:', err)
        this.documents = []
      } finally {
        this.loading = false
      }
    },

    /** 拉取单个文档完整解析结果 */
    async fetchDetail(documentId) {
      this.loading = true
      try {
        this.currentDocument = await getDocumentDetail(documentId)
      } catch (err) {
        console.error('获取文档详情失败:', err)
        this.currentDocument = null
      } finally {
        this.loading = false
      }
    },

    /** 删除文档后从列表移除 */
    async removeDocument(documentId) {
      try {
        await deleteDocument(documentId)
        this.documents = this.documents.filter(d => d.document_id !== documentId)
        if (this.currentDocument?.document_id === documentId) {
          this.currentDocument = null
        }
      } catch (err) {
        console.error('删除文档失败:', err)
        throw err
      }
    },

    /**
     * 提交上传并开始轮询异步解析任务状态
     * 替换原来在 UploadView 中直接调用 uploadDocument 的逻辑
     * @param {File} file 上传的文件
     * @param {Object} options 解析选项 { parse_formula, parse_figures, parse_references }
     * @returns {Promise<Object>} 上传接口的立即响应 { task_id, document_id, filename, status }
     */
    async startUploadAndPoll(file, options = {}) {
      // 1. 提交上传，获取 task_id
      const res = await uploadDocument(file, options)
      this.currentTaskId = res.task_id
      this.taskStatus = { status: 'PENDING', progress: 0, current_step: '', error: null }
      this.taskPolling = true

      // 2. 轮询任务状态
      const POLL_INTERVAL = 2000    // 每 2 秒轮询一次
      const MAX_POLL_TIME = 300000  // 最多轮询 5 分钟
      const startTime = Date.now()
      let pollCount = 0

      const poll = async () => {
        if (!this.taskPolling || !this.currentTaskId) return

        try {
          const status = await getTaskStatus(this.currentTaskId)
          this.taskStatus = status
          pollCount++

          if (status.status === 'SUCCESS') {
            // 任务成功：刷新文档列表 + 加载解析结果
            this.taskPolling = false
            await this.fetchDocuments()
            if (status.result?.document_id) {
              await this.fetchDetail(status.result.document_id)
            }
            return
          }

          if (status.status === 'FAILURE') {
            // 任务失败：停止轮询，错误信息已在 taskStatus.error 中
            this.taskPolling = false
            return
          }

          // 超时检查
          if (Date.now() - startTime > MAX_POLL_TIME) {
            this.taskPolling = false
            this.taskStatus = {
              ...this.taskStatus,
              status: 'FAILURE',
              error: '任务超时（超过 5 分钟），请稍后在文档列表中查看状态或重新上传'
            }
            return
          }

          // 继续轮询
          setTimeout(poll, POLL_INTERVAL)
        } catch (err) {
          // 轮询请求失败：重试，但不超过超时时间
          if (Date.now() - startTime > MAX_POLL_TIME) {
            this.taskPolling = false
            this.taskStatus = {
              ...this.taskStatus,
              status: 'FAILURE',
              error: '任务状态查询超时'
            }
            return
          }
          setTimeout(poll, POLL_INTERVAL)
        }
      }

      // 启动轮询（延迟首次查询，给 worker 一点时间领取任务）
      setTimeout(poll, 1000)
      return res
    },

    /** 取消轮询并清空任务状态（页面卸载/上传失败时调用） */
    cancelPolling() {
      this.taskPolling = false
      this.currentTaskId = null
      this.taskStatus = null
    },

    // ==================== P1-4 文献管理增强 ====================

    /**
     * 更新文档标签（整体覆盖），并同步本地列表与详情
     * @param {String} docId 文档 ID
     * @param {String[]} tags 新标签数组
     */
    async updateTags(docId, tags) {
      await updateDocumentTags(docId, tags)
      // 同步本地列表中的标签
      const target = this.documents.find(d => d.document_id === docId)
      if (target) target.tags = tags
      // 同步当前详情（若打开的是该文档）
      if (this.currentDocument?.document_id === docId) {
        this.currentDocument = { ...this.currentDocument, tags }
      }
    },

    /**
     * 按关键词 + 标签搜索文档；两个条件都为空时回退为全量列表
     * @param {String} keyword 搜索关键词
     * @param {String} tag 标签筛选
     */
    async search(keyword = '', tag = '') {
      this.searchKeyword = keyword || ''
      this.filterTag = tag || ''
      // 无筛选条件时直接拉全量列表
      if (!this.searchKeyword && !this.filterTag) {
        await this.fetchDocuments()
        return
      }
      this.loading = true
      try {
        const res = await searchDocuments({ keyword: this.searchKeyword, tag: this.filterTag })
        this.documents = res.documents || []
        this.total = res.total ?? this.documents.length
      } catch (err) {
        console.error('搜索文档失败:', err)
        this.documents = []
      } finally {
        this.loading = false
      }
    },

    /**
     * 批量删除文档，并清理选中状态
     * @param {String[]} ids 待删除文档 ID 列表
     * @returns {Promise<Object>} 接口返回 { deleted: n }
     */
    async batchDelete(ids) {
      const res = await batchDeleteDocuments(ids)
      const idSet = new Set(ids)
      this.documents = this.documents.filter(d => !idSet.has(d.document_id))
      this.selectedIds = this.selectedIds.filter(id => !idSet.has(id))
      if (this.currentDocument && idSet.has(this.currentDocument.document_id)) {
        this.currentDocument = null
      }
      return res
    },

    /**
     * 批量构建知识图谱
     * @param {String[]} ids 参与构建的文档 ID 列表
     * @returns {Promise<Object>} { graph_id, status, stats }
     */
    async batchBuildGraph(ids) {
      return await batchBuildGraph(ids)
    },

    /** 切换单个文档的批量选中状态 */
    toggleSelect(docId) {
      if (this.selectedIds.includes(docId)) {
        this.selectedIds = this.selectedIds.filter(id => id !== docId)
      } else {
        this.selectedIds.push(docId)
      }
    },

    /** 清空批量选中 */
    clearSelection() {
      this.selectedIds = []
    }
  }
})
