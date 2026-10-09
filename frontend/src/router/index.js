import { createRouter, createWebHistory } from 'vue-router'
import UploadView from '../views/UploadView.vue'
import QAView from '../views/QAView.vue'
import GraphView from '../views/GraphView.vue'
import ReviewView from '../views/ReviewView.vue'

// 路由配置：4 个核心页面
const routes = [
  { path: '/', redirect: '/upload' },
  { path: '/upload', name: 'upload', component: UploadView, meta: { title: '文献上传' } },
  { path: '/qa', name: 'qa', component: QAView, meta: { title: '深度问答' } },
  { path: '/graph', name: 'graph', component: GraphView, meta: { title: '知识图谱' } },
  { path: '/review', name: 'review', component: ReviewView, meta: { title: '综述生成' } }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
