import { defineStore } from 'pinia'

/**
 * 问答历史状态管理
 * 维护对话式问答历史，包含每一轮的问题、回答与引用来源
 */
export const useQaStore = defineStore('qa', {
  state: () => ({
    history: [],   // [{id, question, answer, sources, retrieval_info, mode, document_ids, time}]
    asking: false
  }),

  actions: {
    /** 添加一轮问答记录 */
    addQaRecord(record) {
      this.history.push({
        id: Date.now().toString(),
        time: new Date().toLocaleString(),
        ...record
      })
    },

    /** 清空历史 */
    clearHistory() {
      this.history = []
    },

    setAsking(v) {
      this.asking = v
    }
  }
})
