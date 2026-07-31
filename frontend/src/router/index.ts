import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/chat',
  },
  {
    path: '/chat',
    name: 'Chat',
    component: () => import('@/views/Chat.vue'),
    meta: { title: 'AI 助手', icon: 'ChatDotRound' },
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('@/views/Tasks.vue'),
    meta: { title: '定时任务', icon: 'AlarmClock' },
  },
  {
    path: '/lineage',
    name: 'Lineage',
    component: () => import('@/views/Lineage.vue'),
    meta: { title: '数据地图', icon: 'Connection' },
  },
  {
    path: '/audit',
    name: 'Audit',
    component: () => import('@/views/Audit.vue'),
    meta: { title: '操作记录', icon: 'Notebook' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
