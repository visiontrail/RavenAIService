import { createRouter, createWebHistory } from 'vue-router'
import { i18n } from '@/i18n'
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
        meta: { title: i18n.global.t('router.workbench') },
      },
      {
        path: 'logs',
        name: 'Logs',
        alias: ['/log-list'],
        component: () => import('../views/LogList.vue'),
        meta: { title: i18n.global.t('router.logList') },
      },
      {
        path: 'log/:id',
        name: 'LogDetail',
        component: () => import('../views/LogDetail.vue'),
        meta: { title: i18n.global.t('router.logDetail') },
        props: true,
      },
      {
        path: 'devices',
        name: 'DeviceList',
        component: () => import('../views/DeviceList.vue'),
        meta: { title: i18n.global.t('router.devices') },
      },
      {
        path: 'devices/:id',
        name: 'DeviceDetail',
        component: () => import('../views/DeviceDetail.vue'),
        meta: { title: i18n.global.t('router.deviceDetail') },
        props: true,
      },
      {
        path: 'raven-manager',
        alias: ['/raven', '/raven/'],
        name: 'RavenManager',
        component: () => import('../views/RavenManager.vue'),
        meta: { title: i18n.global.t('router.raven') },
      },
      {
        path: 'raven/package/:id',
        alias: ['/package/:id'],
        name: 'RavenPackageDetail',
        component: () => import('../views/RavenPackageDetail.vue'),
        meta: { title: i18n.global.t('router.ravenDetail') },
        props: true,
      },
      {
        path: 'bug-fixes',
        name: 'BugFixList',
        component: () => import('../views/BugFixList.vue'),
        meta: { title: i18n.global.t('router.bugFix') },
      },
      {
        path: 'bug-fixes/:id',
        name: 'BugFixDetail',
        component: () => import('../views/BugFixDetail.vue'),
        meta: { title: i18n.global.t('router.bugFixDetail') },
        props: true,
      },
      {
        path: 'upload',
        name: 'Upload',
        component: () => import('../views/Upload.vue'),
        meta: { title: i18n.global.t('router.upload') },
      },
      {
        path: 'download',
        name: 'Download',
        component: () => import('../views/Download.vue'),
        meta: { title: i18n.global.t('router.download') },
      },
      {
        path: 'about',
        name: 'About',
        component: () => import('../views/NotFound.vue'),
        meta: { title: i18n.global.t('router.about') },
      },
      {
        path: 'changelog',
        name: 'Changelog',
        component: () => import('../views/NotFound.vue'),
        meta: { title: i18n.global.t('router.changelog') },
      },
      {
        path: 'privacy',
        name: 'Privacy',
        component: () => import('../views/NotFound.vue'),
        meta: { title: i18n.global.t('router.privacy') },
      },
      {
        path: 'terms',
        name: 'Terms',
        component: () => import('../views/NotFound.vue'),
        meta: { title: i18n.global.t('router.terms') },
      },
    ],
  },
  {
    // Public, read-only shared conversation page. Top-level (outside
    // WorkbenchLayout): no sidebar, no nav, no input, no login guard.
    path: '/share/:token',
    name: 'SharedConversation',
    component: () => import('../views/SharedConversation.vue'),
    meta: {
      title: i18n.global.t('router.sharedConversation'),
      public: true,
    },
    props: true,
  },
  {
    path: '/admin',
    name: 'AdminHome',
    component: () => import('../views/AdminPrompts.vue'),
    meta: {
      title: i18n.global.t('router.admin'),
    },
  },
  {
    path: '/admin/prompts',
    name: 'AdminPrompts',
    component: () => import('../views/AdminPrompts.vue'),
    meta: {
      title: i18n.global.t('router.admin'),
    },
  },
  {
    path: '/admin/users',
    name: 'AdminUsers',
    component: () => import('../views/AdminUsers.vue'),
    meta: {
      title: i18n.global.t('router.adminUsers'),
    },
  },
  {
    path: '/admin/releases',
    name: 'AdminReleases',
    component: () => import('../views/AdminRelease.vue'),
    meta: {
      title: i18n.global.t('router.adminRelease'),
    },
  },
  {
    path: '/admin/project-repos',
    name: 'AdminProjectRepos',
    component: () => import('../views/AdminProjectRepos.vue'),
    meta: {
      title: i18n.global.t('router.adminRepos'),
    },
  },
  {
    path: '/admin/agent-skills',
    name: 'AdminAgentSkills',
    component: () => import('../views/AdminAgentSkills.vue'),
    meta: {
      title: i18n.global.t('router.adminAgentSkills'),
    },
  },
  {
    path: '/admin/project-repos/:projectCode/skills',
    name: 'AdminProjectSkills',
    component: () => import('../views/AdminProjectSkills.vue'),
    meta: {
      title: i18n.global.t('router.adminProjectSkills'),
    },
    props: true,
  },
  {
    path: '/admin/model-settings',
    name: 'AdminModelSettings',
    component: () => import('../views/AdminModelSettings.vue'),
    meta: {
      title: i18n.global.t('router.adminModelSettings'),
    },
  },
  {
    path: '/admin/metrics',
    name: 'AdminMetrics',
    component: () => import('../views/AdminMetrics.vue'),
    meta: {
      title: i18n.global.t('router.adminMetrics'),
    },
  },
  {
    path: '/:pathMatch(.*)*',
    component: () => import('../layouts/WorkbenchLayout.vue'),
    children: [
      {
        path: '',
        name: 'NotFound',
        component: () => import('../views/NotFound.vue'),
        meta: { title: i18n.global.t('router.notFound') },
      },
    ],
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
    document.title = `${to.meta.title}${i18n.global.t('router.docTitleSuffix')}`
  }
  next()
})

export default router
