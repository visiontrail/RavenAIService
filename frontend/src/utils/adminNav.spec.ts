import { describe, expect, it } from 'vitest'
import { PROJECT_MEMBER_HOME, resolveAdminRedirect } from './adminNav'
import { adminNavItems } from './adminNav'
import type { AdminIdentity } from '@/types'

const globalAdmin: AdminIdentity = {
  username: 'admin',
  access_level: 'global_admin',
  allowed_nav_keys: adminNavItems.map((i) => i.key),
  allowed_project_ids: [],
  allowed_project_codes: [],
}

const projectMember: AdminIdentity = {
  username: 'mallory',
  access_level: 'project_member',
  allowed_nav_keys: ['project-repos'],
  allowed_project_ids: [1],
  allowed_project_codes: ['alpha'],
}

describe('resolveAdminRedirect', () => {
  it('does not redirect when there is no admin identity', () => {
    expect(resolveAdminRedirect(null, '/admin/users')).toBeNull()
  })

  it('does not redirect global admins anywhere', () => {
    expect(resolveAdminRedirect(globalAdmin, '/admin/users')).toBeNull()
    expect(resolveAdminRedirect(globalAdmin, '/admin')).toBeNull()
  })

  it('sends project-member admins from /admin home to project repos', () => {
    expect(resolveAdminRedirect(projectMember, '/admin')).toBe(PROJECT_MEMBER_HOME)
  })

  it('blocks project-member admins from global-only admin routes', () => {
    expect(resolveAdminRedirect(projectMember, '/admin/users')).toBe(PROJECT_MEMBER_HOME)
    expect(resolveAdminRedirect(projectMember, '/admin/announcements')).toBe(PROJECT_MEMBER_HOME)
    expect(resolveAdminRedirect(projectMember, '/admin/metrics')).toBe(PROJECT_MEMBER_HOME)
    expect(resolveAdminRedirect(projectMember, '/admin/agent-skills')).toBe(
      PROJECT_MEMBER_HOME
    )
  })

  it('registers announcements as an independent global admin tab', () => {
    const item = adminNavItems.find((entry) => entry.key === 'announcements')
    expect(item?.path).toBe('/admin/announcements')
  })

  it('allows project-member admins on the project repos area', () => {
    expect(resolveAdminRedirect(projectMember, '/admin/project-repos')).toBeNull()
  })

  it('allows project-member admins on the Project Skills route', () => {
    // Project-code scope is enforced inside the view + backend, not by the redirect.
    expect(
      resolveAdminRedirect(projectMember, '/admin/project-repos/alpha/skills')
    ).toBeNull()
  })
})
