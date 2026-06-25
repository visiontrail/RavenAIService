import { i18n } from '@/i18n'
import type { AdminIdentity } from '@/types'

export const adminNavItems = [
  {
    key: 'prompts',
    label: i18n.global.t('adminNav.promptConfig'),
    path: '/admin/prompts',
    description: i18n.global.t('adminNav.promptConfigDesc'),
  },
  {
    key: 'users',
    label: i18n.global.t('adminNav.users'),
    path: '/admin/users',
    description: i18n.global.t('adminNav.usersDesc'),
  },
  {
    key: 'releases',
    label: 'App Release',
    path: '/admin/releases',
    description: i18n.global.t('adminNav.releaseDesc'),
  },
  {
    key: 'project-repos',
    label: i18n.global.t('adminNav.repos'),
    path: '/admin/project-repos',
    description: i18n.global.t('adminNav.reposDesc'),
  },
  {
    key: 'agent-skills',
    label: i18n.global.t('adminNav.agentSkills'),
    path: '/admin/agent-skills',
    description: i18n.global.t('adminNav.agentSkillsDesc'),
  },
  {
    key: 'model-settings',
    label: i18n.global.t('adminNav.modelSettings'),
    path: '/admin/model-settings',
    description: i18n.global.t('adminNav.modelSettingsDesc'),
  },
  {
    key: 'metrics',
    label: i18n.global.t('adminNav.metrics'),
    path: '/admin/metrics',
    description: i18n.global.t('adminNav.metricsDesc'),
  },
] as const

export type AdminNavItem = (typeof adminNavItems)[number]

export const resolveAdminNavKey = (path: string) => {
  if (path.startsWith('/admin/users')) return 'users'
  if (path.startsWith('/admin/releases')) return 'releases'
  if (path.startsWith('/admin/project-repos')) return 'project-repos'
  if (path.startsWith('/admin/project-skills')) return 'project-repos'
  if (path.startsWith('/admin/agent-skills')) return 'agent-skills'
  if (path.startsWith('/admin/model-settings')) return 'model-settings'
  if (path.startsWith('/admin/metrics')) return 'metrics'
  if (path.startsWith('/admin')) return 'prompts'
  return ''
}

export const PROJECT_MEMBER_HOME = '/admin/project-repos'

// Decide where a project-member admin should be redirected when entering an
// admin route. Global admins (and unauthenticated callers, where identity is
// null) are never redirected — their views render login/content directly.
// Returns the redirect target path, or null to allow the navigation.
export const resolveAdminRedirect = (
  identity: AdminIdentity | null,
  toPath: string
): string | null => {
  if (!identity || identity.access_level !== 'project_member') return null
  const navKey = resolveAdminNavKey(toPath)
  const allowed = new Set(identity.allowed_nav_keys)
  if (!navKey || !allowed.has(navKey)) {
    return toPath === PROJECT_MEMBER_HOME ? null : PROJECT_MEMBER_HOME
  }
  return null
}
