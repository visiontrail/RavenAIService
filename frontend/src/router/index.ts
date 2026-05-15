import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized, RouteRecordRaw } from 'vue-router'

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
    path: '/logs',
    name: 'Logs',
    component: () => import('../views/LogList.vue'),
    meta: {
      title: '日志列表',
    },
  },
  {
    path: '/devices',
    name: 'DeviceList',
    component: () => import('../views/DeviceList.vue'),
    meta: {
      title: '设备列表',
    },
  },
  {
    path: '/devices/:id',
    name: 'DeviceDetail',
    component: () => import('../views/DeviceDetail.vue'),
    meta: {
      title: '设备详情',
    },
    props: true,
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
    alias: ['/raven', '/raven/'],
    name: 'RavenManager',
    component: () => import('../views/RavenManager.vue'),
    meta: {
      title: '重构包列表',
    },
  },
  {
    path: '/raven/package/:id',
    alias: ['/package/:id'],
    name: 'RavenPackageDetail',
    component: () => import('../views/RavenPackageDetail.vue'),
    meta: {
      title: '包详情',
    },
    props: true,
  },
  {
    path: '/ai-chat',
    name: 'AIChat',
    component: () => import('../views/AIChat.vue'),
    meta: {
      title: 'Raven AI Chat',
    },
  },
  {
    path: '/download',
    name: 'Download',
    component: () => import('../views/Download.vue'),
    meta: {
      title: '下载客户端',
    },
  },
  {
    path: '/about',
    name: 'About',
    component: () => import('../views/NotFound.vue'),
    meta: {
      title: '关于 Raven',
    },
  },
  {
    path: '/changelog',
    name: 'Changelog',
    component: () => import('../views/NotFound.vue'),
    meta: {
      title: '更新日志',
    },
  },
  {
    path: '/privacy',
    name: 'Privacy',
    component: () => import('../views/NotFound.vue'),
    meta: {
      title: '隐私政策',
    },
  },
  {
    path: '/terms',
    name: 'Terms',
    component: () => import('../views/NotFound.vue'),
    meta: {
      title: '服务条款',
    },
  },
  {
    path: '/admin',
    name: 'AdminHome',
    component: () => import('../views/AdminPrompts.vue'),
    meta: {
      title: '后台管理',
    },
  },
  {
    path: '/admin/prompts',
    name: 'AdminPrompts',
    component: () => import('../views/AdminPrompts.vue'),
    meta: {
      title: '后台管理',
    },
  },
  {
    path: '/admin/users',
    name: 'AdminUsers',
    component: () => import('../views/AdminUsers.vue'),
    meta: {
      title: '用户管理',
    },
  },
  {
    path: '/admin/releases',
    name: 'AdminReleases',
    component: () => import('../views/AdminRelease.vue'),
    meta: {
      title: 'App Release 管理',
    },
  },
  {
    path: '/admin/repo-settings',
    name: 'AdminRepoSettings',
    component: () => import('../views/AdminRepoSettings.vue'),
    meta: {
      title: 'Git 仓库配置',
    },
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

const normalizePort = (value?: unknown) => {
  if (value === null || value === undefined) return ''
  return String(value)
}

const shouldRedirectToRaven = (to: RouteLocationNormalized, from: RouteLocationNormalized) => {
  // 仅在首次访问根路径（默认日志列表）时尝试重定向
  if (from?.name) return false
  // 如果访问 /logs 路径，不进行重定向
  if (to.path === '/logs' || to.name === 'Logs') return false
  if (to.name !== 'LogList' && to.path !== '/') return false
  if (typeof window === 'undefined') return false

  const configuredPort =
    normalizePort((window as any).__RAVEN_SERVER_PORT__) ||
    normalizePort(import.meta.env.VITE_RAVEN_PORT) ||
    '8083'
  const currentPort = normalizePort(window.location.port)

  return configuredPort !== '' && currentPort === configuredPort
}

// 路由守卫
router.beforeEach((to, from, next) => {
  if (shouldRedirectToRaven(to, from)) {
    next({ name: 'RavenManager', replace: true })
    return
  }

  // 设置页面标题
  if (to.meta?.title) {
    document.title = `${to.meta.title} - Raven智能测试平台`
  }
  next()
})

export default router
