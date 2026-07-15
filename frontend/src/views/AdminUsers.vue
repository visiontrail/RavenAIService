<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { LogOut, Menu, PanelLeftClose } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAppStore } from '@/stores/app'
import { resolveAdminNavKey, type AdminNavItem } from '@/utils/adminNav'
import { useAdminScope } from '@/composables/useAdminScope'
import type { UserProfile } from '@/types'

const { t } = useI18n()
const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const { visibleNavItems } = useAdminScope()

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingUsers = ref(false)
const users = ref<UserProfile[]>([])
const userDialogVisible = ref(false)
const userDialogMode = ref<'create' | 'edit'>('create')
const savingUser = ref(false)
const editingUserId = ref<string | null>(null)
const deletingUserId = ref('')
const loadingRegistrationSettings = ref(false)
const savingRegistrationSettings = ref(false)

const authForm = reactive({
  username: '',
  password: '',
})

const userDialogForm = reactive({
  username: '',
  display_name: '',
  email: '',
  password: '',
  role: 'user' as 'user' | 'admin',
})

const registrationSettingsForm = reactive({
  email_regex: '',
  email_validation_message: '',
})

const navVisible = computed(() => appStore.adminSidebarVisible)

const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const parseErrorMessage = (err: any) => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return t('admin.parseError')
}

const formatTimestamp = (value?: string | null) => {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return value
  }
}

const getLastLoginTimestamp = (user: UserProfile) => user.last_login_at || user.created_at

const persistToken = (token: string) => {
  adminToken.set(token)
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const handleNavClick = (item: AdminNavItem) => {
  if (item.path && route.path !== item.path) {
    router.push(item.path)
  }
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
}

const fetchUsers = async () => {
  if (!isAuthenticated.value) return
  loadingUsers.value = true
  try {
    const resp = await adminApi.listUsers()
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.users.loadFailFallback'))
    }
    users.value = resp.data
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.loadFail'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    loadingUsers.value = false
  }
}

const fetchRegistrationSettings = async () => {
  if (!isAuthenticated.value) return
  loadingRegistrationSettings.value = true
  try {
    const resp = await adminApi.getRegistrationEmailSettings()
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.users.registrationSettingsLoadFail'))
    }
    registrationSettingsForm.email_regex = resp.data.email_regex || ''
    registrationSettingsForm.email_validation_message = resp.data.email_validation_message || ''
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.users.registrationSettingsLoadFail'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    loadingRegistrationSettings.value = false
  }
}

const saveRegistrationSettings = async () => {
  if (!registrationSettingsForm.email_validation_message.trim()) {
    appStore.showNotification({
      title: t('admin.users.validationMessageRequired'),
      type: 'warning',
    })
    return
  }
  savingRegistrationSettings.value = true
  try {
    const resp = await adminApi.updateRegistrationEmailSettings({
      email_regex: registrationSettingsForm.email_regex,
      email_validation_message: registrationSettingsForm.email_validation_message.trim(),
    })
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.users.registrationSettingsSaveFail'))
    }
    registrationSettingsForm.email_regex = resp.data.email_regex
    registrationSettingsForm.email_validation_message = resp.data.email_validation_message
    appStore.showNotification({
      title: t('admin.users.registrationSettingsSaved'),
      type: 'success',
    })
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.users.registrationSettingsSaveFail'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    savingRegistrationSettings.value = false
  }
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({
      title: t('admin.loginWarning'),
      type: 'warning',
    })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.loginFailFallback'))
    }
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({
      title: t('admin.loginSuccessTitle'),
      message: t('admin.loginSuccessMsg', { username: resp.data.username }),
      type: 'success',
    })
    await Promise.all([fetchUsers(), fetchRegistrationSettings()])
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.loginFailFallback'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    isLoggingIn.value = false
  }
}

const handleLogout = async () => {
  try {
    await adminApi.logout()
  } catch {
    // ignore
  } finally {
    clearAuth()
    users.value = []
    appStore.showNotification({
      title: t('admin.logoutSuccessTitle'),
      type: 'info',
    })
  }
}

const resetUserDialogForm = () => {
  userDialogForm.username = ''
  userDialogForm.display_name = ''
  userDialogForm.email = ''
  userDialogForm.password = ''
  userDialogForm.role = 'user'
}

const normalizeRole = (role?: string | null): 'user' | 'admin' =>
  (role || '').toString().toLowerCase() === 'admin' ? 'admin' : 'user'

const roleLabel = (role?: string | null) => (normalizeRole(role) === 'admin' ? t('admin.users.roleAdmin') : t('admin.users.roleUser'))

const openCreateUserDialog = () => {
  userDialogMode.value = 'create'
  editingUserId.value = null
  resetUserDialogForm()
  userDialogVisible.value = true
}

const openEditUserDialog = (user: UserProfile) => {
  userDialogMode.value = 'edit'
  editingUserId.value = user.id
  userDialogForm.username = user.username
  userDialogForm.display_name = user.display_name || ''
  userDialogForm.email = user.email || ''
  userDialogForm.password = ''
  userDialogForm.role = normalizeRole(user.role)
  userDialogVisible.value = true
}

const closeUserDialog = () => {
  if (savingUser.value) return
  userDialogVisible.value = false
}

const submitUserDialog = async () => {
  if (userDialogMode.value === 'create' && (!userDialogForm.username || !userDialogForm.password)) {
    appStore.showNotification({
      title: t('admin.loginWarning'),
      type: 'warning',
    })
    return
  }
  if (userDialogMode.value === 'edit' && !editingUserId.value) return

  savingUser.value = true
  try {
    if (userDialogMode.value === 'create') {
      const resp = await adminApi.createUser({
        username: userDialogForm.username.trim(),
        password: userDialogForm.password,
        display_name: userDialogForm.display_name || undefined,
        email: userDialogForm.email || undefined,
        role: userDialogForm.role,
      })
      if (!resp?.success || !resp.data) {
        throw new Error(resp?.message || t('admin.users.createFailFallback'))
      }
      appStore.showNotification({
        title: t('admin.users.createSuccess'),
        message: t('admin.users.createdMsg', { username: resp.data.username }),
        type: 'success',
      })
    } else {
      const payload: {
        display_name?: string
        email?: string
        password?: string
        role?: 'user' | 'admin'
      } = {
        display_name: userDialogForm.display_name || undefined,
        email: userDialogForm.email || undefined,
        role: userDialogForm.role,
      }
      if (userDialogForm.password) {
        payload.password = userDialogForm.password
      }
      const resp = await adminApi.updateUser(editingUserId.value as string, payload)
      if (!resp?.success || !resp.data) {
        throw new Error(resp?.message || t('admin.users.updateFailFallback'))
      }
      appStore.showNotification({
        title: t('admin.users.updateSuccess'),
        message: t('admin.users.updatedMsg', { username: resp.data.username }),
        type: 'success',
      })
    }
    userDialogVisible.value = false
    resetUserDialogForm()
    await fetchUsers()
  } catch (err: any) {
    appStore.showNotification({
      title: userDialogMode.value === 'create' ? t('admin.users.createFailFallback') : t('admin.users.updateFailFallback'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    savingUser.value = false
  }
}

const toggleActive = async (user: UserProfile) => {
  const nextStatus = !user.is_active
  try {
    const resp = await adminApi.updateUser(user.id, { is_active: nextStatus })
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.users.updateFailFallback'))
    }
    users.value = users.value.map((u) => (u.id === user.id ? resp.data as UserProfile : u))
    appStore.showNotification({
      title: nextStatus ? t('admin.users.enabledTitle') : t('admin.users.disabledTitle'),
      message: resp.data.username,
      type: 'success',
    })
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.users.statusUpdateFail'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  }
}

const resetPassword = async (user: UserProfile) => {
  const password = window.prompt(t('admin.users.resetPasswordPrompt', { username: user.username }))
  if (!password) return
  try {
    const resp = await adminApi.updateUser(user.id, { password })
    if (!resp?.success) {
      throw new Error(resp?.message || t('admin.users.resetFailFallback'))
    }
    appStore.showNotification({
      title: t('admin.users.passwordResetSuccess'),
      message: user.username,
      type: 'success',
    })
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.users.resetFailFallback'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  }
}

const deleteUser = async (user: UserProfile) => {
  const confirmed = window.confirm(t('admin.users.deleteConfirm', { username: user.username }))
  if (!confirmed) return
  deletingUserId.value = user.id
  try {
    const resp = await adminApi.disableUser(user.id)
    if (!resp?.success) {
      throw new Error(resp?.message || t('admin.users.deleteFailFallback'))
    }
    users.value = users.value.filter((u) => u.id !== user.id)
    appStore.showNotification({
      title: t('admin.users.deleteSuccess'),
      message: user.username,
      type: 'success',
    })
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.users.deleteFailFallback'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    deletingUserId.value = ''
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await Promise.all([fetchUsers(), fetchRegistrationSettings()])
    } else {
      clearAuth()
    }
  } catch {
    clearAuth()
  }
}

onMounted(() => {
  bootstrap()
})
</script>

<template>
  <div class="admin-console admin-users-page">
    <header class="admin-topbar">
      <div class="admin-topbar-inner">
        <div class="admin-topbar-left">
          <button
            class="admin-icon-btn"
            :disabled="!isAuthenticated"
            @click="toggleNavVisibility"
            :title="navVisible ? t('admin.toggleSidebarHide') : t('admin.toggleSidebarShow')"
            :aria-label="t('admin.toggleSidebarAriaLabel')"
          >
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">{{ t('admin.title') }}</h1>
            <p class="admin-subtitle">{{ t('admin.users.subtitle') }}</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <ThemeToggle class="admin-theme-toggle" />
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? t('admin.users.badge', { count: users.length }) : t('admin.badgeNotLoggedIn') }}
          </span>
          <button
            v-if="isAuthenticated"
            class="admin-logout-btn"
            @click="handleLogout"
          >
            <LogOut :size="14" />
            <span>{{ t('admin.logoutBtn') }}</span>
          </button>
        </div>
      </div>
    </header>

    <button
      v-if="isAuthenticated && navVisible"
      class="admin-sidebar-backdrop"
      @click="toggleNavVisibility"
      :aria-label="t('admin.closeSidebarAriaLabel')"
    ></button>

    <aside
      v-if="isAuthenticated"
      class="admin-sidebar"
      :class="{ 'is-hidden': !navVisible }"
    >
      <div class="space-y-2">
        <button
          v-for="item in visibleNavItems"
          :key="item.key"
          class="admin-side-nav-item"
          :class="{ 'is-active': activeNavKey === item.key }"
          @click="handleNavClick(item)"
        >
          <div class="text-sm font-semibold">{{ item.label }}</div>
          <p v-if="item.description" class="text-xs mt-1 text-slate-400">
            {{ item.description }}
          </p>
        </button>
      </div>
    </aside>

    <main
      class="admin-main"
      :class="{ 'is-sidebar-hidden': !isAuthenticated || !navVisible }"
    >
      <section v-if="!isAuthenticated" class="admin-login-wrap">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.loginCardTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.loginCardDesc') }}</p>
            </div>
            <span class="text-xs text-slate-500">{{ t('admin.secureAccess') }}</span>
          </div>
          <div class="grid gap-4 md:grid-cols-2">
            <form class="space-y-4" @submit.prevent="handleLogin">
              <label class="block">
                <span class="text-sm text-slate-700">{{ t('admin.usernameLabel') }}</span>
                <input
                  v-model="authForm.username"
                  type="text"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  placeholder="admin"
                  autocomplete="username"
                />
              </label>
              <label class="block">
                <span class="text-sm text-slate-700">{{ t('admin.passwordLabel') }}</span>
                <input
                  v-model="authForm.password"
                  type="password"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  placeholder="••••••••"
                  autocomplete="current-password"
                />
              </label>
              <div class="login-actions flex items-center gap-3">
                <button
                  type="submit"
                  class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
                  :disabled="isLoggingIn"
                >
                  {{ isLoggingIn ? t('admin.loginBtnLoading') : t('admin.loginBtn') }}
                </button>
                <p class="text-xs text-slate-500">
                  {{ t('admin.credentialsHint') }}
                </p>
              </div>
            </form>
            <div class="bg-slate-50 rounded-lg p-4 space-y-3 text-sm text-slate-700">
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-emerald-400"></span>
                <span>{{ t('admin.users.loginHint1') }}</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-cyan-400"></span>
                <span>{{ t('admin.users.loginHint2') }}</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-amber-400"></span>
                <span>{{ t('admin.users.loginHint3') }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else class="space-y-4">
        <form
          class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4"
          @submit.prevent="saveRegistrationSettings"
        >
          <div class="flex flex-col gap-1 mb-4">
            <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.users.registrationSettingsTitle') }}</h2>
            <p class="text-sm text-slate-500">{{ t('admin.users.registrationSettingsDesc') }}</p>
          </div>
          <div v-if="loadingRegistrationSettings" class="text-sm text-slate-500">
            {{ t('admin.users.registrationSettingsLoading') }}
          </div>
          <div v-else class="grid gap-4 lg:grid-cols-2">
            <label class="text-sm text-slate-700">
              {{ t('admin.users.emailRegexLabel') }}
              <textarea
                v-model="registrationSettingsForm.email_regex"
                rows="4"
                maxlength="512"
                spellcheck="false"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                :placeholder="t('admin.users.emailRegexPlaceholder')"
              ></textarea>
              <p class="text-xs text-slate-500 mt-1">{{ t('admin.users.emailRegexHint') }}</p>
            </label>
            <div class="space-y-3">
              <label class="block text-sm text-slate-700">
                {{ t('admin.users.emailValidationMessageLabel') }}
                <input
                  v-model="registrationSettingsForm.email_validation_message"
                  type="text"
                  required
                  maxlength="255"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="t('admin.users.emailValidationMessagePlaceholder')"
                />
              </label>
              <p class="text-xs text-slate-500">{{ t('admin.users.emailValidationMessageHint') }}</p>
              <button
                type="submit"
                class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-60"
                :disabled="savingRegistrationSettings"
              >
                {{ savingRegistrationSettings ? t('admin.users.registrationSettingsSaving') : t('admin.users.registrationSettingsSave') }}
              </button>
            </div>
          </div>
        </form>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4">
          <div class="user-list-header flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.users.listTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.users.listDesc') }}</p>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="px-3 py-1.5 text-sm rounded-lg border border-cyan-200 text-cyan-700 hover:bg-cyan-50"
                @click="openCreateUserDialog"
              >
                {{ t('admin.users.createBtn') }}
              </button>
              <button
                class="text-sm text-slate-600 hover:text-slate-900"
                @click="fetchUsers"
                :disabled="loadingUsers"
              >
                {{ loadingUsers ? t('admin.users.syncingBtn') : t('common.refresh') }}
              </button>
            </div>
          </div>

          <div v-if="loadingUsers" class="text-sm text-slate-500">{{ t('admin.users.loadingText') }}</div>
          <div v-else-if="!users.length" class="text-sm text-slate-500">{{ t('admin.users.emptyText') }}</div>
          <div v-else class="users-table-wrapper overflow-x-auto touch-scroll">
            <table class="min-w-full text-left text-sm text-slate-700 users-table">
              <thead>
                <tr class="border-b border-slate-200">
                  <th class="py-2 pr-4 font-semibold">{{ t('admin.users.colUsername') }}</th>
                  <th class="py-2 pr-4 font-semibold">{{ t('admin.users.colDisplayName') }}</th>
                  <th class="py-2 pr-4 font-semibold">{{ t('admin.users.colEmail') }}</th>
                  <th class="py-2 pr-4 font-semibold">{{ t('admin.users.colRole') }}</th>
                  <th class="py-2 pr-4 font-semibold">{{ t('admin.users.colStatus') }}</th>
                  <th class="py-2 pr-4 font-semibold">{{ t('admin.users.colLastLogin') }}</th>
                  <th class="py-2 pr-4 font-semibold">{{ t('admin.users.colActions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in users" :key="user.id" class="border-b border-slate-100">
                  <td class="py-2 pr-4 font-medium text-slate-900">{{ user.username }}</td>
                  <td class="py-2 pr-4">{{ user.display_name || '-' }}</td>
                  <td class="py-2 pr-4">{{ user.email || '-' }}</td>
                  <td class="py-2 pr-4">
                    <span
                      class="px-2 py-1 rounded-full text-xs font-semibold"
                      :class="normalizeRole(user.role) === 'admin' ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'"
                    >
                      {{ roleLabel(user.role) }}
                    </span>
                  </td>
                  <td class="py-2 pr-4">
                    <span
                      class="px-2 py-1 rounded-full text-xs font-semibold"
                      :class="user.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                    >
                      {{ user.is_active ? t('admin.users.statusEnabled') : t('admin.users.statusDisabled') }}
                    </span>
                  </td>
                  <td class="py-2 pr-4 text-slate-500">{{ formatTimestamp(getLastLoginTimestamp(user)) }}</td>
                  <td class="py-2 pr-4 space-x-2">
                    <button
                      class="text-xs px-3 py-1 rounded-lg border border-slate-200 hover:bg-slate-50"
                      @click="toggleActive(user)"
                    >
                      {{ user.is_active ? t('admin.users.toggleDisableBtn') : t('admin.users.toggleEnableBtn') }}
                    </button>
                    <button
                      class="text-xs px-3 py-1 rounded-lg border border-cyan-200 text-cyan-700 hover:bg-cyan-50"
                      @click="openEditUserDialog(user)"
                    >
                      {{ t('admin.users.editBtn') }}
                    </button>
                    <button
                      class="text-xs px-3 py-1 rounded-lg border border-amber-200 text-amber-700 hover:bg-amber-50"
                      @click="resetPassword(user)"
                    >
                      {{ t('admin.users.resetPasswordBtn') }}
                    </button>
                    <button
                      class="text-xs px-3 py-1 rounded-lg border border-rose-200 text-rose-700 hover:bg-rose-50 disabled:opacity-60"
                      :disabled="deletingUserId === user.id"
                      @click="deleteUser(user)"
                    >
                      {{ deletingUserId === user.id ? t('admin.users.deletingBtn') : t('admin.users.deleteBtn') }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div
          v-if="userDialogVisible"
          class="admin-modal-backdrop"
          @click="closeUserDialog"
        >
          <div class="admin-modal-card" @click.stop>
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-base font-semibold text-slate-900">
                {{ userDialogMode === 'create' ? t('admin.users.dialogTitleCreate') : t('admin.users.dialogTitleEdit') }}
              </h3>
              <button
                class="text-sm text-slate-500 hover:text-slate-800"
                :disabled="savingUser"
                @click="closeUserDialog"
              >
                {{ t('admin.users.closeBtn') }}
              </button>
            </div>

            <div class="grid md:grid-cols-2 gap-4">
              <label class="text-sm text-slate-700">
                {{ t('admin.users.formUsername') }}
                <input
                  v-model="userDialogForm.username"
                  type="text"
                  :disabled="userDialogMode === 'edit'"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none disabled:bg-slate-100 disabled:text-slate-500"
                  placeholder="username"
                />
              </label>
              <label class="text-sm text-slate-700">
                {{ t('admin.users.formDisplayName') }}
                <input
                  v-model="userDialogForm.display_name"
                  type="text"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="t('admin.users.formDisplayNamePlaceholder')"
                />
              </label>
              <label class="text-sm text-slate-700">
                {{ t('admin.users.formEmail') }}
                <input
                  v-model="userDialogForm.email"
                  type="email"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  placeholder="email@example.com"
                />
              </label>
              <label class="text-sm text-slate-700">
                {{ userDialogMode === 'create' ? t('admin.users.formInitialPassword') : t('admin.users.formNewPassword') }}
                <input
                  v-model="userDialogForm.password"
                  type="password"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="userDialogMode === 'create' ? t('admin.users.formInitialPasswordPlaceholder') : t('admin.users.formNewPasswordPlaceholder')"
                />
              </label>
              <label class="text-sm text-slate-700">
                {{ t('admin.users.formRole') }}
                <select
                  v-model="userDialogForm.role"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none bg-white"
                >
                  <option value="user">{{ t('admin.users.roleUser') }}</option>
                  <option value="admin">{{ t('admin.users.roleAdmin') }}</option>
                </select>
                <p class="text-xs text-slate-500 mt-1">{{ t('admin.users.roleHint') }}</p>
              </label>
            </div>

            <div class="mt-4 flex justify-end gap-2">
              <button
                class="px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                :disabled="savingUser"
                @click="closeUserDialog"
              >
                {{ t('admin.users.cancelBtn') }}
              </button>
              <button
                class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-60"
                :disabled="savingUser"
                @click="submitUserDialog"
              >
                {{ savingUser ? t('admin.users.submittingBtn') : (userDialogMode === 'create' ? t('admin.users.createUserBtn') : t('admin.users.saveChangesBtn')) }}
              </button>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.admin-console {
  --admin-topbar-height: 72px;
  --admin-sidebar-width: 280px;
  min-height: 100vh;
  background: linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%);
}

.admin-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  width: 100%;
  height: var(--admin-topbar-height);
  z-index: 70;
  background: rgba(15, 23, 42, 0.96);
  border-bottom: 1px solid rgba(148, 163, 184, 0.3);
  backdrop-filter: blur(10px);
}

.admin-topbar-inner {
  height: 100%;
  padding: 0 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.admin-topbar-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.admin-icon-btn {
  width: 2.25rem;
  height: 2.25rem;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 0.625rem;
  color: #f8fafc;
  background: rgba(51, 65, 85, 0.6);
}

.admin-icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.admin-title {
  color: #f8fafc;
  font-size: 0.95rem;
  font-weight: 700;
  line-height: 1.1;
}

.admin-subtitle {
  color: #94a3b8;
  font-size: 0.75rem;
}

.admin-topbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.admin-logout-btn {
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 0.55rem;
  color: #e2e8f0;
  background: rgba(51, 65, 85, 0.45);
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.45rem 0.7rem;
}

.admin-sidebar {
  position: fixed;
  left: 0;
  top: 0;
  width: var(--admin-sidebar-width);
  height: 100vh;
  z-index: 60;
  background: #0f172a;
  border-right: 1px solid rgba(148, 163, 184, 0.25);
  padding: calc(var(--admin-topbar-height) + 1rem) 1rem 1rem;
  transition: transform 0.25s ease;
  overflow-y: auto;
}

.admin-sidebar.is-hidden {
  transform: translateX(calc(-1 * var(--admin-sidebar-width)));
}

.admin-side-nav-item {
  width: 100%;
  text-align: left;
  padding: 0.8rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(100, 116, 139, 0.45);
  color: #cbd5e1;
  background: rgba(30, 41, 59, 0.45);
}

.admin-side-nav-item.is-active {
  color: #0f172a;
  background: #22d3ee;
  border-color: #22d3ee;
}

.admin-main {
  min-height: 100vh;
  padding: calc(var(--admin-topbar-height) + 1rem) 1rem 1rem calc(var(--admin-sidebar-width) + 1rem);
  transition: padding-left 0.25s ease;
}

.admin-main.is-sidebar-hidden {
  padding-left: 1rem;
}

.admin-login-wrap {
  max-width: 960px;
  margin: 1.25rem auto 0;
}

.admin-sidebar-backdrop {
  display: none;
}

.admin-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(2, 6, 23, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.admin-modal-card {
  width: min(760px, 100%);
  border-radius: 1rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  box-shadow: 0 20px 45px rgba(15, 23, 42, 0.25);
  padding: 1rem;
}

@media (max-width: 1024px) {
  .admin-topbar-inner {
    padding: 0 0.75rem;
  }

  .admin-topbar-right span {
    display: none;
  }
}

@media (max-width: 768px) {
  .admin-console {
    --admin-sidebar-width: min(84vw, 320px);
  }

  .admin-main {
    padding: calc(var(--admin-topbar-height) + 0.85rem) 0.75rem 0.75rem;
  }

  .admin-main.is-sidebar-hidden {
    padding-left: 0.75rem;
  }

  .admin-sidebar {
    box-shadow: 20px 0 45px rgba(15, 23, 42, 0.35);
  }

  .admin-sidebar-backdrop {
    display: block;
    position: fixed;
    inset: var(--admin-topbar-height) 0 0 0;
    z-index: 55;
    background: rgba(2, 6, 23, 0.4);
  }

  .admin-topbar-right {
    display: none;
  }

  .admin-subtitle {
    display: none;
  }

  .login-actions {
    flex-direction: column;
    align-items: flex-start;
  }

  .user-list-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .admin-modal-card {
    padding: 0.85rem;
  }

  .users-table {
    min-width: 720px;
  }
}
</style>
