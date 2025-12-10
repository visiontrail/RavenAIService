import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'LogList',
    component: () => import('../views/LogList.vue'),
    meta: {
      title: '日志列表',
    },
  },
  {
    path: '/upload',
    name: 'Upload',
    component: () => import('../views/Upload.vue'),
    meta: {
      title: '上传日志',
    },
  },
  {
    path: '/log/:id',
    name: 'LogDetail',
    component: () => import('../views/LogDetail.vue'),
    meta: {
      title: '日志详情',
    },
    props: true,
  },
  {
    path: '/raven-manager',
    name: 'RavenManager',
    component: () => import('../views/RavenManager.vue'),
    meta: {
      title: 'Raven包管理',
    },
  },
  {
    path: '/raven/package/:id',
    name: 'RavenPackageDetail',
    component: () => import('../views/RavenPackageDetail.vue'),
    meta: {
      title: '包详情',
    },
    props: true,
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('../views/NotFound.vue'),
    meta: {
      title: '页面未找到',
    },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫
router.beforeEach((to, from, next) => {
  // 设置页面标题
  if (to.meta?.title) {
    document.title = `${to.meta.title} - 日志管理系统`
  }
  next()
})

export default router
