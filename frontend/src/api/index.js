import axios from 'axios'
import { ElMessage } from 'element-plus'

/**
 * Axios 实例统一配置
 * baseURL 从环境变量读取，默认 /api/v1
 */
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 120000, // 文档解析、问答、图谱构建可能耗时较长，设置 120s 超时
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器：统一注入鉴权头（如有）
api.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
)

// 响应拦截器：统一解包 data、错误提示
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const msg = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    return Promise.reject(error)
  }
)

export default api
