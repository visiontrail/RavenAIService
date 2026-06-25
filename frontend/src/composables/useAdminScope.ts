import { computed, ref } from 'vue'
import type { AdminIdentity } from '@/types'
import { adminNavItems, type AdminNavItem } from '@/utils/adminNav'

// Module-level singleton holding the admin identity reported by
// `GET /admin/auth/me`. Every admin view shares the same scope so navigation,
// route guards, and project-scoped controls stay consistent. Backend
// authorization remains the source of truth; this only shapes the UI.
const identity = ref<AdminIdentity | null>(null)

const setAdminIdentity = (value: AdminIdentity | null) => {
  identity.value = value
}

const clearAdminIdentity = () => {
  identity.value = null
}

export const useAdminScope = () => {
  const isGlobalAdmin = computed(() => identity.value?.access_level === 'global_admin')
  const isProjectMember = computed(
    () => identity.value?.access_level === 'project_member'
  )

  const allowedNavKeys = computed<string[]>(() => identity.value?.allowed_nav_keys ?? [])
  const allowedProjectIds = computed<number[]>(
    () => identity.value?.allowed_project_ids ?? []
  )
  const allowedProjectCodes = computed<string[]>(
    () => identity.value?.allowed_project_codes ?? []
  )

  // Global admins (or callers before `me()` resolves the scope) see every nav
  // item. Project-member admins only see the keys reported by the backend.
  const visibleNavItems = computed<readonly AdminNavItem[]>(() => {
    if (!identity.value || isGlobalAdmin.value) return adminNavItems
    const allowed = new Set(allowedNavKeys.value)
    return adminNavItems.filter((item) => allowed.has(item.key))
  })

  const normalizeCode = (code: string) => (code || '').trim().toLowerCase()

  const canAccessProjectCode = (code: string): boolean => {
    if (!identity.value || isGlobalAdmin.value) return true
    return allowedProjectCodes.value.includes(normalizeCode(code))
  }

  const canAccessNavKey = (key: string): boolean => {
    if (!identity.value || isGlobalAdmin.value) return true
    return allowedNavKeys.value.includes(key)
  }

  return {
    identity,
    setAdminIdentity,
    clearAdminIdentity,
    setIdentity: setAdminIdentity,
    clearIdentity: clearAdminIdentity,
    isGlobalAdmin,
    isProjectMember,
    allowedNavKeys,
    allowedProjectIds,
    allowedProjectCodes,
    visibleNavItems,
    canAccessProjectCode,
    canAccessNavKey,
  }
}

export { setAdminIdentity, clearAdminIdentity }
