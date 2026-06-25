import { afterEach, describe, expect, it } from 'vitest'
import { setAdminIdentity, clearAdminIdentity, useAdminScope } from './useAdminScope'
import { adminNavItems } from '@/utils/adminNav'
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

describe('useAdminScope', () => {
  afterEach(() => clearAdminIdentity())

  it('shows all nav items before the scope resolves', () => {
    const { visibleNavItems } = useAdminScope()
    expect(visibleNavItems.value.length).toBe(adminNavItems.length)
  })

  it('shows all nav items for a global admin', () => {
    setAdminIdentity(globalAdmin)
    const { visibleNavItems, isGlobalAdmin } = useAdminScope()
    expect(isGlobalAdmin.value).toBe(true)
    expect(visibleNavItems.value.length).toBe(adminNavItems.length)
  })

  it('filters nav to project surfaces for a project-member admin', () => {
    setAdminIdentity(projectMember)
    const { visibleNavItems, isProjectMember } = useAdminScope()
    expect(isProjectMember.value).toBe(true)
    const keys = visibleNavItems.value.map((i) => i.key)
    expect(keys).toEqual(['project-repos'])
    expect(keys).not.toContain('users')
    expect(keys).not.toContain('prompts')
    expect(keys).not.toContain('metrics')
  })

  it('gates project codes for project-member admins (Project Skills guard)', () => {
    setAdminIdentity(projectMember)
    const { canAccessProjectCode } = useAdminScope()
    expect(canAccessProjectCode('alpha')).toBe(true)
    expect(canAccessProjectCode('ALPHA')).toBe(true) // case-insensitive
    expect(canAccessProjectCode('beta')).toBe(false)
  })

  it('lets global admins access any project code', () => {
    setAdminIdentity(globalAdmin)
    const { canAccessProjectCode } = useAdminScope()
    expect(canAccessProjectCode('anything')).toBe(true)
  })
})
