import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/workbench',
  },
  {
    path: '/',
    component: () => import('../layouts/WorkbenchLayout.vue'),
    children: [
      {
        path: 'workbench',
        alias: ['/ai-chat'],
        name: 'Workbench',
        component: () => import('../views/AIChat.vue'),
        meta: { title: 'RavenAI 工作台' },
      },
      {
        path: 'logs',
        name: 'Logs',
        alias: ['/log-list'],
        component: () => import('../views/LogList.vue'),
        meta: { title: '日志列表' },
      },
      {
        path: 'log/:id',
        name: 'LogDetail',
        component: () => import('../views/LogDetail.vue'),
        meta: { title: '日志详情' },
        props: true,
      },
      {
        path: 'devices',
        name: 'DeviceList',
        component: () => import('../views/DeviceList.vue'),
        meta: { title: '设备机柜' },
      },
      {
        path: 'raven-manager',
        alias: ['/raven', '/raven/'],
        name: 'RavenManager',
        component: () => import('../views/RavenManager.vue'),
        meta: { title: '重构包仓库' },
      },
      {
        path: 'raven/package/:id',
        alias: ['/package/:id'],
        name: 'RavenPackageDetail',
        component: () => import('../views/RavenPackageDetail.vue'),
        meta: { title: '包详情' },
        props: true,
      },
    ],
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
    path: '/admin/project-repos',
    name: 'AdminProjectRepos',
    component: () => import('../views/AdminProjectRepos.vue'),
    meta: {
      title: '项目仓库管理',
    },
  },
  {
    path: '/admin/agent-skills',
    name: 'AdminAgentSkills',
    component: () => import('../views/AdminAgentSkills.vue'),
    meta: {
      title: 'Agent Skill 管理',
    },
  },
  {
    path: '/admin/model-settings',
    name: 'AdminModelSettings',
    component: () => import('../views/AdminModelSettings.vue'),
    meta: {
      title: '模型设置',
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

// 路由守卫
router.beforeEach((to, _from, next) => {
  // 设置页面标题
  if (to.meta?.title) {
    document.title = `${to.meta.title} - Raven智能测试平台`
  }
  next()
})

export default router
