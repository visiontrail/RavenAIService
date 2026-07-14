import { i18n } from '@/i18n'
import type { AdminIdentity } from '@/types'

const adminNavDefinitions = [
  {
    key: 'prompts',
    labelKey: 'adminNav.promptConfig',
    path: '/admin/prompts',
    descriptionKey: 'adminNav.promptConfigDesc',
  },
  {
    key: 'users',
    labelKey: 'adminNav.users',
    path: '/admin/users',
    descriptionKey: 'adminNav.usersDesc',
  },
  {
    key: 'announcements',
    labelKey: 'adminNav.announcements',
    path: '/admin/announcements',
    descriptionKey: 'adminNav.announcementsDesc',
  },
  {
    key: 'releases',
    labelKey: 'adminNav.release',
    path: '/admin/releases',
    descriptionKey: 'adminNav.releaseDesc',
  },
  {
    key: 'project-repos',
    labelKey: 'adminNav.repos',
    path: '/admin/project-repos',
    descriptionKey: 'adminNav.reposDesc',
  },
  {
    key: 'agent-skills',
    labelKey: 'adminNav.agentSkills',
    path: '/admin/agent-skills',
    descriptionKey: 'adminNav.agentSkillsDesc',
  },
  {
    key: 'model-settings',
    labelKey: 'adminNav.modelSettings',
    path: '/admin/model-settings',
    descriptionKey: 'adminNav.modelSettingsDesc',
  },
  {
    key: 'metrics',
    labelKey: 'adminNav.metrics',
    path: '/admin/metrics',
    descriptionKey: 'adminNav.metricsDesc',
  },
] as const

export interface AdminNavItem {
  key: (typeof adminNavDefinitions)[number]['key']
  label: string
  path: string
  description: string
}

/**
 * Resolve labels on demand so the admin sidebar follows vue-i18n locale
 * changes instead of retaining the language active when this module loaded.
 */
export const getAdminNavItems = (): readonly AdminNavItem[] =>
  adminNavDefinitions.map((item) => ({
    key: item.key,
    label: i18n.global.t(item.labelKey),
    path: item.path,
    description: i18n.global.t(item.descriptionKey),
  }))

// Stable structural export retained for route/scope callers and tests. UI
// rendering should use getAdminNavItems() so translated labels stay reactive.
export const adminNavItems = getAdminNavItems()

export const resolveAdminNavKey = (path: string) => {
  if (path.startsWith('/admin/users')) return 'users'
  if (path.startsWith('/admin/announcements')) return 'announcements'
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
