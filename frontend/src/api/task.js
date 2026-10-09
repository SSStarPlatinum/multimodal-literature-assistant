import api from './index'

/**
 * 异步任务状态查询 API
 * 对应后端 GET /task/{task_id}
 */

/**
 * 查询 Celery 异步任务状态
 * @param {string} taskId - Celery 任务 ID
 * @returns {Promise<Object>} 任务状态 { task_id, status, progress, current_step, result, error }
 */
export function getTaskStatus(taskId) {
  return api.get(`/task/${taskId}`)
}
