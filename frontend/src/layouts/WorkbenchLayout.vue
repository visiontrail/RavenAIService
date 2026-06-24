<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Save, ShieldCheck } from 'lucide-vue-next'
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import { useChatSessionStore } from '@/stores/chatSession'
import { useConversationRunsStore } from '@/stores/conversationRuns'
import { userApi } from '@/api/user'
import type { ChatSessionSummary, UserProfileRole } from '@/types'
import brandIcon from '@/assets/icon.png'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const appStore = useAppStore()
const userStore = useUserStore()
const sessionStore = useChatSessionStore()
const runsStore = useConversationRunsStore()

const profileRoleValues = ['developer', 'tester', 'product', 'ops', 'other'] as const

/**
 * Embedded mode: when the workbench is rendered inside the Raven desktop client
 * (in an <iframe> on the Files tab), the client already provides its own
 * left-hand navigation. Rendering the workbench sidebar as well would produce a
 * duplicate sidebar inside the embedded page, so we hide it and let the routed
 * content fill the full width.
 *
 * The check is evaluated once on load — whether we are framed cannot change for
 * the lifetime of the page — so it stays stable across in-frame router
 * navigation (e.g. opening a log/package detail):
 *   - explicit `?embed=1` query flag (the client passes this; also handy for
 *     direct browser preview)
 *   - otherwise any iframe embedding (`window.self !== window.top`)
 */
const detectEmbedded = (): boolean => {
  if (typeof window === 'undefined') return false
  try {
    const flag = new URLSearchParams(window.location.search).get('embed')
    if (flag === '1' || flag === 'true') return true
  } catch {
    /* ignore malformed query strings */
  }
  try {
    return window.self !== window.top
  } catch {
    // Cross-origin frames throw on access — being unable to reach top means framed.
    return true
  }
}
const isEmbedded = detectEmbedded()

/**
 * Union of backend-reported running sessions (``run_status === 'running'``)
 * and the local optimistic running overlay maintained by the run store. The
 * overlay covers the gap between sendMessage and the next sessions list
 * refresh.
 */
const runningSessionIds = computed(() => {
  const ids = new Set<string>()
  for (const s of sessionStore.sessions) {
    const localState = runsStore.bySession[s.id]
    const locallyFinished =
      localState &&
      !localState.isSending &&
      ['succeeded', 'failed', 'cancelled', 'stale'].includes(localState.runStatus)
    if (s.run_status === 'running' && !locallyFinished) ids.add(s.id)
  }
  for (const id of runsStore.localRunningSessionIds) ids.add(id)
  return ids
})

const isSessionRunning = (id: string) => runningSessionIds.value.has(id)

let pollHandle: number | null = null
const schedulePoll = () => {
  if (typeof window === 'undefined') return
  if (pollHandle !== null) return
  pollHandle = window.setInterval(() => {
    // Only refresh when at least one session is in running state — avoids
    // unnecessary polling for idle users.
    if (runningSessionIds.value.size === 0) return
    // Skip when the tab is hidden or a request is still in flight (slow
    // networks) — prevents request pile-up.
    if (document.visibilityState === 'hidden') return
    if (sessionStore.loading || sessionStore.refreshing) return
    sessionStore.load({ background: true }).catch(() => { /* swallow; overlay still works */ })
  }, 5000)
}
const stopPoll = () => {
  if (pollHandle !== null && typeof window !== 'undefined') {
    window.clearInterval(pollHandle)
    pollHandle = null
  }
}

const showUserMenu = ref(false)
const showSearchBox = ref(false)
const hoverSessionId = ref<string | null>(null)
const openRowMenuId = ref<string | null>(null)

// 当前语言来自 app store（启动期由 localStorage/浏览器/profile 解析）。
const activeLocale = computed(() => appStore.locale)
const setLanguage = (next: 'zh' | 'en') => {
  if (appStore.locale === next) return
  // setLocale 负责更新 store + localStorage + vue-i18n/Element Plus，
  // 已登录时同步 PATCH profile。
  appStore.setLocale(next)
}

const editingSessionId = ref<string | null>(null)
const editingSessionTitle = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

const showLoginModal = ref(false)
const authMode = ref<'login' | 'register'>('login')
const loginForm = reactive({
  username: '',
  password: '',
  displayName: '',
  email: '',
  confirmPassword: '',
})
const isLoggingIn = ref(false)
const showSettingsModal = ref(false)
const isSavingProfile = ref(false)
const profileForm = reactive({
  displayName: '',
  email: '',
  profileRole: 'developer' as UserProfileRole,
  clarificationEnabled: true,
  clarificationMaxRounds: 5,
  clarificationOnTimeout: 'cancel' as 'cancel' | 'continue',
})

const userMenuRef = ref<HTMLElement | null>(null)
const userButtonRef = ref<HTMLElement | null>(null)

const isLoggedIn = computed(() => userStore.isAuthenticated)
const currentUserName = computed(() =>
  userStore.profile?.display_name || userStore.profile?.username || t('workbench.userFallback')
)
const currentUserEmail = computed(() => userStore.profile?.email || '')
const currentUserRole = computed(() => (userStore.profile?.role || 'user').toString().toLowerCase())
const currentProfileRole = computed(() => (userStore.profile?.profile_role || 'developer').toString())
const isAdmin = computed(() => isLoggedIn.value && currentUserRole.value === 'admin')
const userInitial = computed(() => (currentUserName.value || 'U').slice(0, 2).toUpperCase())
const currentUserStatusText = computed(() =>
  currentUserEmail.value || (isLoggedIn.value ? t('workbench.loggedIn') : t('workbench.notLoggedIn'))
)
const profileRoleOptions = computed(() => {
  const items: { value: UserProfileRole; label: string }[] = profileRoleValues.map((value) => ({
    value,
    label: t(`workbench.settingsPanel.roles.${value}`),
  }))
  const current = currentProfileRole.value
  if (current && !items.some((item) => item.value === current)) {
    items.push({ value: current, label: current })
  }
  return items
})
const currentProfileRoleLabel = computed(() => {
  const current = currentProfileRole.value
  return profileRoleOptions.value.find((item) => item.value === current)?.label || current
})

const openAuthModal = (mode: 'login' | 'register' = 'login') => {
  authMode.value = mode
  showLoginModal.value = true
}

const syncProfileForm = () => {
  profileForm.displayName = userStore.profile?.display_name || ''
  profileForm.email = userStore.profile?.email || ''
  profileForm.profileRole = (userStore.profile?.profile_role || 'developer') as UserProfileRole
  profileForm.clarificationEnabled = userStore.profile?.clarification_enabled ?? true
  profileForm.clarificationMaxRounds = userStore.profile?.clarification_max_rounds ?? 5
  profileForm.clarificationOnTimeout =
    (userStore.profile?.clarification_on_timeout === 'continue' ? 'continue' : 'cancel')
}

const openSettingsModal = () => {
  showUserMenu.value = false
  if (!isLoggedIn.value) {
    appStore.showNotification({ title: t('workbench.settingsPanel.loginRequired'), type: 'warning' })
    openAuthModal('login')
    return
  }
  syncProfileForm()
  showSettingsModal.value = true
}

const closeSettingsModal = () => {
  showSettingsModal.value = false
}

const handleSaveProfile = async () => {
  if (!isLoggedIn.value) {
    appStore.showNotification({ title: t('workbench.settingsPanel.loginRequired'), type: 'warning' })
    openAuthModal('login')
    return
  }
  isSavingProfile.value = true
  try {
    const resp = await userApi.updateProfile({
      display_name: profileForm.displayName.trim() || null,
      email: profileForm.email.trim() || null,
      profile_role: profileForm.profileRole || 'developer',
      clarification_enabled: profileForm.clarificationEnabled,
      clarification_max_rounds: Number(profileForm.clarificationMaxRounds) || 5,
      clarification_on_timeout: profileForm.clarificationOnTimeout,
    })
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('workbench.settingsPanel.saveFailed'))
    }
    userStore.setProfile(resp.data)
    syncProfileForm()
    appStore.showNotification({ title: t('workbench.settingsPanel.saved'), type: 'success' })
  } catch (error: any) {
    appStore.showNotification({
      title: t('workbench.settingsPanel.saveFailed'),
      message: parseAuthError(error, t('workbench.notifications.tryAgainLater')),
      type: 'error',
    })
  } finally {
    isSavingProfile.value = false
  }
}

const goToAdminConsole = () => {
  showUserMenu.value = false
  router.push('/admin')
}

const goToBugFixes = () => {
  showUserMenu.value = false
  router.push('/bug-fixes')
}

const navItems = computed(() => ([
  { id: 'logs',    label: t('navbar.logs'),    to: '/logs',          icon: 'logs', activeNames: ['Logs', 'LogDetail'] },
  { id: 'devices', label: t('navbar.devices'), to: '/devices',       icon: 'device', activeNames: ['DeviceList', 'DeviceDetail'] },
  { id: 'pkgs',    label: t('navbar.raven'),   to: '/raven-manager', icon: 'box' },
]))

const isNavItemActive = (item: { activeNames?: string[] }, isActive: boolean) => {
  const routeName = (route.name as string) || ''
  return isActive || Boolean(item.activeNames?.includes(routeName))
}

const isHomeRoute = computed(() =>
  route.name === 'Workbench' || route.path === '/workbench' || route.path === '/ai-chat'
)

const filteredSessions = computed(() => sessionStore.sessions)

const groupedSessions = computed(() => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const yesterday = today - 24 * 60 * 60 * 1000
  const weekStart = today - 7 * 24 * 60 * 60 * 1000

  const pinned: ChatSessionSummary[] = []
  const groups: { label: string; items: ChatSessionSummary[] }[] = [
    { label: t('workbench.sessionGroups.today'), items: [] },
    { label: t('workbench.sessionGroups.yesterday'), items: [] },
    { label: t('workbench.sessionGroups.thisWeek'), items: [] },
    { label: t('workbench.sessionGroups.earlier'), items: [] },
  ]

  for (const s of filteredSessions.value) {
    if (s.is_pinned) {
      pinned.push(s)
      continue
    }
    const t = s.last_message_at ? new Date(s.last_message_at).getTime() : 0
    if (t >= today) groups[0].items.push(s)
    else if (t >= yesterday) groups[1].items.push(s)
    else if (t >= weekStart) groups[2].items.push(s)
    else groups[3].items.push(s)
  }
  const ordered = pinned.length
    ? [{ label: t('workbench.sessionGroups.pinned'), items: pinned }, ...groups]
    : groups
  return ordered.filter((g) => g.items.length > 0)
})

const startRenameSession = (session: ChatSessionSummary) => {
  openRowMenuId.value = null
  editingSessionId.value = session.id
  editingSessionTitle.value = session.title || ''
  nextTick(() => renameInputRef.value?.select())
}

const commitRename = async (id: string) => {
  const title = editingSessionTitle.value.trim()
  editingSessionId.value = null
  if (!title) return
  try {
    const ok = await sessionStore.renameSession(id, title)
    if (ok) appStore.showNotification({ title: t('workbench.notifications.renamed'), type: 'success' })
  } catch {
    appStore.showNotification({ title: t('workbench.notifications.renameFailed'), type: 'error' })
  }
}

const cancelRename = () => {
  editingSessionId.value = null
}

const handleRenameKeydown = (e: KeyboardEvent, id: string) => {
  if (e.key === 'Enter') { e.preventDefault(); commitRename(id) }
  if (e.key === 'Escape') { e.preventDefault(); cancelRename() }
}

const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as Node

  if (showUserMenu.value && userMenuRef.value && userButtonRef.value &&
      !userMenuRef.value.contains(target) && !userButtonRef.value.contains(target)) {
    showUserMenu.value = false
  }

  // The row menu lives inside a v-for, so `rowMenuRef` resolves to an array and
  // `.contains()` can't be used reliably. Detect outside clicks via `closest()`
  // against the menu and its trigger button instead.
  if (openRowMenuId.value) {
    const el = target instanceof Element ? target : (target as Node).parentElement
    if (!el?.closest('.rw-row-menu') && !el?.closest('.rw-row-more')) {
      openRowMenuId.value = null
    }
  }

  // Commit rename when clicking outside the inline input.
  if (editingSessionId.value) {
    const el = target instanceof Element ? target : (target as Node).parentElement
    if (!el?.closest('.rw-rename-input-wrap')) {
      commitRename(editingSessionId.value)
    }
  }
}

const handleKey = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    showSettingsModal.value = false
    showUserMenu.value = false
    openRowMenuId.value = null
  }
}

const bootstrapUser = async () => {
  await userStore.bootstrap()
  // 启动期语言解析：已登录时优先采用 profile 偏好
  appStore.initLocale()
  if (isLoggedIn.value) {
    try { await sessionStore.load() } catch { /* notification handled below */ }
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKey)
  bootstrapUser()
  schedulePoll()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKey)
  stopPoll()
})

watch(isLoggedIn, async (loggedIn) => {
  if (loggedIn) {
    try { await sessionStore.load() } catch {
      appStore.showNotification({ title: t('workbench.notifications.syncSessionsFailed'), type: 'error' })
    }
  } else {
    sessionStore.reset()
  }
})

watch(() => appStore.loginModalRequest, (val) => {
  if (val.seq > 0) openAuthModal(val.mode)
})

watch(() => userStore.profile, () => {
  if (showSettingsModal.value) syncProfileForm()
})

const handleSelectSession = (session: ChatSessionSummary) => {
  openRowMenuId.value = null
  sessionStore.selectSession(session.id)
  if (!isHomeRoute.value) router.push('/workbench')
}

const startNewChat = () => {
  sessionStore.startNewChat()
  if (!isHomeRoute.value) router.push('/workbench')
}

const reloadSessions = async () => {
  try { await sessionStore.load() } catch {
    appStore.showNotification({ title: t('workbench.notifications.syncSessionsFailed'), type: 'error' })
  }
}

const togglePinSession = async (session: ChatSessionSummary) => {
  openRowMenuId.value = null
  const wasPinned = Boolean(session.is_pinned)
  try {
    const ok = await sessionStore.togglePin(session.id)
    if (ok) {
      appStore.showNotification({
        title: wasPinned ? t('workbench.notifications.unpinned') : t('workbench.notifications.pinned'),
        type: 'success',
      })
    }
  } catch (error) {
    console.error('Pin operation failed', error)
    appStore.showNotification({ title: t('workbench.notifications.operationFailed'), type: 'error' })
  }
}

const deleteSession = async (id: string) => {
  openRowMenuId.value = null
  const confirmed = window.confirm(t('workbench.confirm.deleteSession'))
  if (!confirmed) return
  try {
    await sessionStore.removeSession(id)
    runsStore.clearSession(id)
    appStore.showNotification({ title: t('workbench.notifications.sessionDeleted'), type: 'success' })
  } catch (error) {
    console.error('Delete session failed', error)
    appStore.showNotification({ title: t('workbench.notifications.deleteFailed'), type: 'error' })
  }
}

const resetAuthForm = () => {
  loginForm.username = ''
  loginForm.password = ''
  loginForm.displayName = ''
  loginForm.email = ''
  loginForm.confirmPassword = ''
}

const closeAuthModal = () => {
  showLoginModal.value = false
  resetAuthForm()
}

const switchAuthMode = (mode: 'login' | 'register') => {
  authMode.value = mode
  loginForm.password = ''
  loginForm.confirmPassword = ''
}

const parseAuthError = (error: any, fallback: string) => {
  const detail = error?.response?.data?.detail || error?.response?.data?.message
  if (typeof detail === 'string') return detail
  return error?.message || fallback
}

const handleUserLogin = async () => {
  if (!loginForm.username || !loginForm.password) {
    appStore.showNotification({ title: t('workbench.notifications.usernamePasswordRequired'), type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await userApi.login(loginForm.username.trim(), loginForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('workbench.notifications.loginFailed'))
    userStore.setToken(resp.data.token)
    userStore.setProfile(resp.data.user)
    // 登录后 profile 语言偏好优先于本地 localStorage
    appStore.initLocale()
    appStore.showNotification({ title: t('workbench.notifications.loginSuccess'), type: 'success' })
    closeAuthModal()
    await sessionStore.load()
  } catch (error: any) {
    appStore.showNotification({
      title: t('workbench.notifications.loginFailed'),
      message: parseAuthError(error, t('workbench.notifications.checkCredentials')),
      type: 'error',
    })
  } finally {
    isLoggingIn.value = false
  }
}

const handleUserRegister = async () => {
  if (!loginForm.username.trim() || !loginForm.password) {
    appStore.showNotification({ title: t('workbench.notifications.usernamePasswordRequired'), type: 'warning' })
    return
  }
  if (loginForm.password.length < 6) {
    appStore.showNotification({ title: t('workbench.notifications.passwordTooShort'), type: 'warning' })
    return
  }
  if (loginForm.password !== loginForm.confirmPassword) {
    appStore.showNotification({ title: t('workbench.notifications.passwordMismatch'), type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await userApi.register({
      username: loginForm.username.trim(),
      password: loginForm.password,
      display_name: loginForm.displayName.trim() || null,
      email: loginForm.email.trim() || null,
    })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('workbench.notifications.registerFailed'))
    userStore.setToken(resp.data.token)
    userStore.setProfile(resp.data.user)
    // 新用户：把当前匿名期选择的语言写入新 profile
    appStore.setLocale(appStore.locale)
    appStore.showNotification({ title: t('workbench.notifications.registerSuccess'), type: 'success' })
    closeAuthModal()
    await sessionStore.load()
  } catch (error: any) {
    appStore.showNotification({
      title: t('workbench.notifications.registerFailed'),
      message: parseAuthError(error, t('workbench.notifications.tryAgainLater')),
      type: 'error',
    })
  } finally {
    isLoggingIn.value = false
  }
}

const handleAuthSubmit = () => {
  if (authMode.value === 'register') return handleUserRegister()
  return handleUserLogin()
}

const handleUserLogout = () => {
  userStore.clear()
  sessionStore.reset()
  showUserMenu.value = false
}
</script>

<template>
  <div class="raven-workbench" :class="{ 'lang-en': activeLocale === 'en', 'is-embedded': isEmbedded }">
    <!-- Sidebar — hidden when embedded in the Raven desktop client (Files tab),
         which provides its own navigation. -->
    <aside v-if="!isEmbedded" class="rw-sidebar">
      <!-- Brand -->
      <div class="rw-brand">
        <div class="rw-brand-left">
          <img :src="brandIcon" alt="" class="rw-brand-mark" aria-hidden="true" />
          <div>
            <div class="rw-brand-name">RavenAI</div>
            <div class="rw-brand-sub">{{ t('workbench.brandSub') }}</div>
          </div>
        </div>
        <button class="rw-icon-btn" :title="t('workbench.searchConversations')" @click="showSearchBox = !showSearchBox" :aria-label="t('workbench.searchConversations')">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        </button>
      </div>

      <!-- New chat -->
      <button class="rw-new-btn" @click="startNewChat">
        <span class="rw-new-btn-left">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          {{ t('workbench.newChat') }}
        </span>
        <span class="rw-kbd">⌘ N</span>
      </button>

      <!-- Nav -->
      <nav class="rw-nav-list">
        <router-link
          v-for="item in navItems"
          :key="item.id"
          :to="item.to"
          class="rw-nav-item"
          custom
          v-slot="{ navigate, isActive }"
        >
          <div class="rw-nav-row" :class="{ 'is-active': isNavItemActive(item, isActive) }" @click="navigate">
            <span class="rw-nav-icon">
              <svg v-if="item.icon === 'logs'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h10M4 18h16"/><circle cx="18" cy="12" r="1.4"/></svg>
              <svg v-else-if="item.icon === 'device'" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="11" rx="1.5"/><path d="M8 21h8M12 17v4"/><circle cx="7" cy="11" r="0.4" fill="currentColor"/></svg>
              <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/></svg>
            </span>
            <span>{{ item.label }}</span>
          </div>
        </router-link>
      </nav>

      <div class="rw-divider"/>

      <!-- Chat list -->
      <div class="rw-chat-list">
        <div class="rw-group-header">
          <span class="rw-group-label">{{ t('workbench.recentConversations') }}</span>
          <span v-if="isLoggedIn" class="rw-group-count">{{ sessionStore.sessions.length }}</span>
          <button
            v-if="isLoggedIn"
            class="rw-refresh-btn"
            :disabled="sessionStore.loading || sessionStore.refreshing"
            @click="reloadSessions"
            :title="t('common.refresh')"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: sessionStore.loading || sessionStore.refreshing }"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>
          </button>
        </div>

        <template v-if="!isLoggedIn">
          <div class="rw-login-hint">
            <div class="rw-login-hint-title">{{ t('workbench.loginHintTitle') }}</div>
            <div class="rw-login-actions">
              <button class="rw-login-link" @click="openAuthModal('login')">{{ t('workbench.loginNow') }}</button>
              <button class="rw-login-link" @click="openAuthModal('register')">{{ t('workbench.registerAccount') }}</button>
            </div>
          </div>
        </template>
        <!-- Placeholder only when we truly have nothing to show; background
             refreshes keep the existing list rendered (stale-while-revalidate). -->
        <template v-else-if="sessionStore.loading && !sessionStore.sessions.length">
          <div class="rw-empty">{{ t('workbench.sessionsLoading') }}</div>
        </template>
        <template v-else-if="!sessionStore.sessions.length">
          <div class="rw-empty">{{ t('workbench.emptySessions') }}</div>
        </template>
        <template v-else>
          <div v-for="group in groupedSessions" :key="group.label">
            <div class="rw-chat-group">{{ group.label }}</div>
            <div
              v-for="session in group.items"
              :key="session.id"
              class="rw-chat-row"
              :class="{
                'is-active': sessionStore.selectedSessionId === session.id && isHomeRoute,
                'is-hover': hoverSessionId === session.id || openRowMenuId === session.id,
                'is-editing': editingSessionId === session.id,
              }"
              @click="editingSessionId !== session.id && handleSelectSession(session)"
              @mouseenter="hoverSessionId = session.id"
              @mouseleave="hoverSessionId = null"
            >
              <!-- Inline rename input -->
              <div
                v-if="editingSessionId === session.id"
                class="rw-rename-input-wrap"
                @click.stop
              >
                <input
                  ref="renameInputRef"
                  v-model="editingSessionTitle"
                  class="rw-rename-input"
                  type="text"
                  maxlength="80"
                  @keydown="handleRenameKeydown($event, session.id)"
                  @blur="commitRename(session.id)"
                />
              </div>
              <template v-else>
                <span class="rw-chat-row-text">{{ session.title || t('workbench.untitledSession') }}</span>
                <span
                  v-if="isSessionRunning(session.id)"
                  class="rw-row-thinking"
                  :title="t('workbench.thinking')"
                  :aria-label="t('workbench.thinking')"
                >
                  <span></span>
                  <span></span>
                  <span></span>
                </span>
                <button
                  class="rw-row-more"
                  :class="{ visible: hoverSessionId === session.id || openRowMenuId === session.id }"
                  @click.stop="openRowMenuId = openRowMenuId === session.id ? null : session.id"
                  :aria-label="t('common.more')"
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></svg>
                </button>
                <div
                  v-if="openRowMenuId === session.id"
                  class="rw-row-menu"
                  @click.stop
                >
                  <button class="rw-menu-item" @click="startRenameSession(session)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4l10-10-4-4L4 16zM14 6l4 4"/></svg>
                    {{ t('workbench.renameConversation') }}
                  </button>
                  <button class="rw-menu-item" @click="togglePinSession(session)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v6M9 8h6l2 6H7zM12 14v8"/></svg>
                    {{ session.is_pinned ? t('workbench.unpinConversation') : t('workbench.pinConversation') }}
                  </button>
                  <div class="rw-menu-divider"/>
                  <button class="rw-menu-item is-danger" @click="deleteSession(session.id)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>
                    {{ t('workbench.deleteConversation') }}
                  </button>
                </div>
              </template>
            </div>
          </div>
        </template>
      </div>

      <!-- Bottom user card -->
      <div class="rw-bottom">
        <div class="rw-menu-wrap">
          <div
            v-if="showUserMenu"
            ref="userMenuRef"
            class="rw-user-menu"
            role="menu"
          >
            <div class="rw-user-menu-head">
              <div class="rw-avatar lg">{{ userInitial }}</div>
              <div style="flex:1; min-width:0;">
                <div class="rw-user-menu-name">
                  {{ currentUserName }}
                  <span v-if="isAdmin" class="rw-role-badge">{{ t('workbench.adminRole') }}</span>
                </div>
                <div class="rw-user-menu-mail">{{ currentUserStatusText }}</div>
              </div>
            </div>
            <button
              v-if="isAdmin"
              class="rw-user-menu-item"
              @click="goToAdminConsole"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><path d="M12 3l8 4v6c0 4.5-3.5 7-8 8-4.5-1-8-3.5-8-8V7l8-4z"/><path d="m9 12 2 2 4-4"/></svg>
              {{ t('workbench.adminConsole') }}
              <span class="rw-kbd-right">/admin</span>
            </button>
            <button
              v-if="isLoggedIn"
              class="rw-user-menu-item"
              @click="goToBugFixes"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/></svg>
              {{ t('workbench.bugFixes') }}
              <span class="rw-kbd-right">/bug-fixes</span>
            </button>
            <div v-if="isLoggedIn || isAdmin" class="rw-menu-divider"/>
            <div class="rw-menu-section">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>
              <span>{{ t('language.label') }}</span>
              <span class="rw-lang-pill" role="group" :aria-label="t('language.switchTo')">
                <span class="rw-lang-opt" :class="{ active: activeLocale === 'zh' }" @click="setLanguage('zh')">{{ t('workbench.zhShort') }}</span>
                <span class="rw-lang-opt" :class="{ active: activeLocale === 'en' }" @click="setLanguage('en')">EN</span>
              </span>
            </div>
            <button class="rw-user-menu-item" @click="openSettingsModal">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33 1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              {{ t('workbench.settings') }}
              <span class="rw-kbd-right">⌘ ,</span>
            </button>
            <button class="rw-user-menu-item" @click="showUserMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5"/><circle cx="12" cy="17" r="0.4" fill="currentColor"/></svg>
              {{ t('workbench.helpShortcuts') }}
              <span class="rw-kbd-right">?</span>
            </button>
            <div class="rw-menu-divider"/>
            <button
              class="rw-user-menu-item"
              @click="isLoggedIn ? handleUserLogout() : (showUserMenu = false, openAuthModal('login'))"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>
              {{ isLoggedIn ? t('workbench.logout') : t('workbench.loginNow') }}
            </button>
          </div>
          <div
            ref="userButtonRef"
            class="rw-user-card"
            :class="{ open: showUserMenu }"
            @click="showUserMenu = !showUserMenu"
          >
            <div class="rw-avatar">{{ userInitial }}</div>
            <div class="rw-user-meta">
              <div class="rw-user-name">{{ currentUserName }}</div>
              <div class="rw-user-role">
                <span v-if="isAdmin">{{ t('workbench.adminRole') }} · {{ currentUserStatusText }}</span>
                <span v-else-if="isLoggedIn">{{ currentUserStatusText }}</span>
                <span v-else>{{ t('workbench.notLoggedInCta') }}</span>
              </div>
            </div>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-chevron" :class="{ flipped: showUserMenu }"><path d="m6 9 6 6 6-6"/></svg>
          </div>
        </div>
      </div>
    </aside>

    <!-- Main pane: routed content provides its own topbar + body -->
    <main class="rw-main">
      <router-view />
    </main>

    <!-- Settings modal — single-column popup, consistent with the login and
         share-conversation dialogs. -->
    <div v-if="showSettingsModal" class="rw-modal-backdrop" @click.self="closeSettingsModal">
      <div class="rw-modal rw-settings-modal" role="dialog" aria-modal="true" :aria-label="t('workbench.settingsPanel.title')">
        <div class="rw-modal-head">
          <div>
            <h3 class="rw-modal-title">{{ t('workbench.settingsPanel.title') }}</h3>
            <p class="rw-modal-sub">{{ t('workbench.settingsPanel.subtitle') }}</p>
          </div>
          <button class="rw-modal-close" @click="closeSettingsModal" :aria-label="t('workbench.settingsPanel.close')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
          </button>
        </div>

        <div class="rw-settings-account-strip">
          <div class="rw-avatar lg">{{ userInitial }}</div>
          <div class="rw-settings-account-meta">
            <strong>{{ currentUserName }}</strong>
            <span>{{ userStore.profile?.username }}</span>
          </div>
          <span class="rw-profile-role-chip">{{ currentProfileRoleLabel }}</span>
        </div>

        <form class="rw-modal-form" @submit.prevent="handleSaveProfile">
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.settingsPanel.username') }}</span>
            <input :value="userStore.profile?.username || ''" type="text" class="rw-input" disabled autocomplete="username" />
          </label>
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.settingsPanel.displayName') }}</span>
            <input
              v-model="profileForm.displayName"
              type="text"
              class="rw-input"
              maxlength="128"
              :placeholder="t('workbench.settingsPanel.displayNamePlaceholder')"
              autocomplete="name"
            />
          </label>
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.settingsPanel.email') }}</span>
            <input
              v-model="profileForm.email"
              type="email"
              class="rw-input"
              maxlength="255"
              :placeholder="t('workbench.settingsPanel.emailPlaceholder')"
              autocomplete="email"
            />
          </label>
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.settingsPanel.profileRole') }}</span>
            <select v-model="profileForm.profileRole" class="rw-select">
              <option v-for="item in profileRoleOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </label>

          <div class="rw-settings-section-title">{{ t('workbench.settingsPanel.clarification.section') }}</div>
          <label class="rw-form-field rw-form-field--inline">
            <span class="rw-form-label">{{ t('workbench.settingsPanel.clarification.enabledLabel') }}</span>
            <input v-model="profileForm.clarificationEnabled" type="checkbox" class="rw-checkbox" />
          </label>
          <p class="rw-form-hint">{{ t('workbench.settingsPanel.clarification.enabledHint') }}</p>
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.settingsPanel.clarification.maxRoundsLabel') }}</span>
            <input
              v-model.number="profileForm.clarificationMaxRounds"
              type="number"
              min="0"
              max="20"
              class="rw-input"
              :disabled="!profileForm.clarificationEnabled"
            />
          </label>
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.settingsPanel.clarification.onTimeoutLabel') }}</span>
            <select
              v-model="profileForm.clarificationOnTimeout"
              class="rw-select"
              :disabled="!profileForm.clarificationEnabled"
            >
              <option value="cancel">{{ t('workbench.settingsPanel.clarification.onTimeoutCancel') }}</option>
              <option value="continue">{{ t('workbench.settingsPanel.clarification.onTimeoutContinue') }}</option>
            </select>
          </label>
          <p class="rw-form-hint">{{ t('workbench.settingsPanel.clarification.onTimeoutHint') }}</p>

          <div class="rw-settings-permission">
            <ShieldCheck :size="16" stroke-width="1.8" />
            <span>{{ t('workbench.settingsPanel.permissionRole') }}</span>
            <strong>{{ isAdmin ? t('workbench.adminRole') : t('workbench.settingsPanel.permissionUser') }}</strong>
          </div>

          <div class="rw-modal-actions">
            <button type="submit" class="rw-btn-primary rw-save-profile-btn" :disabled="isSavingProfile">
              <Save v-if="!isSavingProfile" :size="14" stroke-width="1.8" />
              {{ isSavingProfile ? t('workbench.settingsPanel.saving') : t('workbench.settingsPanel.save') }}
            </button>
            <button type="button" class="rw-btn-ghost" @click="closeSettingsModal">{{ t('common.cancel') }}</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Login modal -->
    <div v-if="showLoginModal" class="rw-modal-backdrop" @click.self="closeAuthModal">
      <div class="rw-modal">
        <div class="rw-modal-head">
          <div>
            <h3 class="rw-modal-title">{{ authMode === 'register' ? t('workbench.auth.registerTitle') : t('workbench.auth.loginTitle') }}</h3>
            <p class="rw-modal-sub">{{ authMode === 'register' ? t('workbench.auth.registerSubtitle') : t('workbench.auth.loginSubtitle') }}</p>
          </div>
          <button class="rw-modal-close" @click="closeAuthModal" :aria-label="t('common.close')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
          </button>
        </div>
        <div class="rw-auth-tabs" role="tablist" :aria-label="t('workbench.auth.accountActions')">
          <button type="button" :class="{ active: authMode === 'login' }" @click="switchAuthMode('login')">{{ t('workbench.auth.loginTab') }}</button>
          <button type="button" :class="{ active: authMode === 'register' }" @click="switchAuthMode('register')">{{ t('workbench.auth.registerTab') }}</button>
        </div>
        <form class="rw-modal-form" @submit.prevent="handleAuthSubmit">
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.auth.username') }}</span>
            <input v-model="loginForm.username" type="text" class="rw-input" :placeholder="t('workbench.auth.usernamePlaceholder')" autocomplete="username" />
          </label>
          <label v-if="authMode === 'register'" class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.auth.displayName') }}</span>
            <input v-model="loginForm.displayName" type="text" class="rw-input" :placeholder="t('workbench.auth.optional')" autocomplete="name" />
          </label>
          <label v-if="authMode === 'register'" class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.auth.email') }}</span>
            <input v-model="loginForm.email" type="email" class="rw-input" :placeholder="t('workbench.auth.optional')" autocomplete="email" />
          </label>
          <label class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.auth.password') }}</span>
            <input
              v-model="loginForm.password"
              type="password"
              class="rw-input"
              :placeholder="t('workbench.auth.passwordPlaceholder')"
              :autocomplete="authMode === 'register' ? 'new-password' : 'current-password'"
            />
          </label>
          <label v-if="authMode === 'register'" class="rw-form-field">
            <span class="rw-form-label">{{ t('workbench.auth.confirmPassword') }}</span>
            <input v-model="loginForm.confirmPassword" type="password" class="rw-input" :placeholder="t('workbench.auth.confirmPasswordPlaceholder')" autocomplete="new-password" />
          </label>
          <div class="rw-modal-actions">
            <button type="submit" class="rw-btn-primary" :disabled="isLoggingIn">
              {{ isLoggingIn ? (authMode === 'register' ? t('workbench.auth.registerLoading') : t('workbench.auth.loginLoading')) : (authMode === 'register' ? t('workbench.auth.registerSubmit') : t('workbench.loginNow')) }}
            </button>
            <button type="button" class="rw-btn-ghost" @click="closeAuthModal">{{ t('common.cancel') }}</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.raven-workbench {
  /* Design tokens — Expo style */
  --rw-canvas: #ffffff;
  --rw-canvas-soft: #fafafa;
  --rw-surface-card: #ffffff;
  --rw-surface-strong: #f0f0f3;
  --rw-surface-dark: #171717;
  --rw-ink: #171717;
  --rw-body: #60646c;
  --rw-muted: #999999;
  --rw-muted-soft: #cccccc;
  --rw-hairline: #f0f0f3;
  --rw-hairline-soft: #f5f5f7;
  --rw-hairline-strong: #dcdee0;
  --rw-primary: #171717;
  --rw-primary-hover: #2e2e2e;
  --rw-primary-active: #404040;
  --rw-on-primary: #ffffff;
  --rw-success: #16a34a;
  --rw-danger: #c0382b;

  --rw-sans: 'Inter', -apple-system, system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  --rw-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;

  display: flex;
  height: 100%;
  min-height: 0;
  background: var(--rw-canvas);
  color: var(--rw-ink);
  font-family: var(--rw-sans);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

.raven-workbench *,
.raven-workbench *::before,
.raven-workbench *::after {
  box-sizing: border-box;
}

.raven-workbench button {
  font-family: inherit;
  cursor: pointer;
  border: none;
  background: none;
  padding: 0;
  color: inherit;
}

.raven-workbench input,
.raven-workbench textarea {
  font-family: inherit;
  color: inherit;
}

.spin { animation: rw-spin 1s linear infinite; }
@keyframes rw-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

/* ---------- Sidebar ---------- */
.rw-sidebar {
  width: 272px;
  flex-shrink: 0;
  background: var(--rw-canvas-soft);
  border-right: 1px solid var(--rw-hairline);
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.rw-brand { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 12px; }
.rw-brand-left { display: flex; align-items: center; gap: 9px; }
.rw-brand-mark {
  width: 26px; height: 26px; border-radius: 6px;
  object-fit: contain; flex-shrink: 0;
}
.rw-brand-name { font-size: 14px; font-weight: 600; letter-spacing: -0.1px; line-height: 1; }
.rw-brand-sub {
  font-size: 10.5px; color: var(--rw-muted);
  font-weight: 500; letter-spacing: 0.4px;
  margin-top: 3px;
}

.rw-icon-btn {
  width: 28px; height: 28px; border-radius: 6px;
  display: grid; place-items: center;
  color: var(--rw-body); transition: background .15s, color .15s;
}
.rw-icon-btn:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }

.raven-workbench button.rw-new-btn {
  margin: 4px 12px 10px; height: 36px;
  background: var(--rw-primary); color: var(--rw-on-primary);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 12px;
  font-size: 13.5px; font-weight: 500;
  transition: background .15s, color .15s;
}
.raven-workbench button.rw-new-btn:hover {
  background: var(--rw-primary-hover);
  color: var(--rw-on-primary);
}
.raven-workbench button.rw-new-btn:active {
  background: var(--rw-primary-active);
  color: var(--rw-on-primary);
}
.rw-new-btn-left { display: inline-flex; align-items: center; gap: 8px; }
.rw-kbd {
  font-family: var(--rw-mono); font-size: 11px;
  color: rgba(255,255,255,.55);
  border: 1px solid rgba(255,255,255,.18);
  border-radius: 4px; padding: 1px 5px; line-height: 1.2;
}


.rw-nav-list { padding: 0 8px; display: flex; flex-direction: column; gap: 1px; }
.rw-nav-item { display: block; text-decoration: none; color: inherit; }
.rw-nav-row {
  display: flex; align-items: center; gap: 10px;
  height: 32px; padding: 0 8px; border-radius: 6px;
  font-size: 13.5px; font-weight: 500; color: var(--rw-body);
  cursor: pointer; transition: background .12s, color .12s;
}
.rw-nav-row:hover { background: var(--rw-hairline-soft); color: var(--rw-ink); }
.rw-nav-row.is-active { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-nav-icon { display: inline-flex; color: inherit; }

.rw-divider { margin: 14px 16px 10px; height: 1px; background: var(--rw-hairline); }

.rw-chat-list {
  flex: 1; min-height: 0; overflow: auto;
  padding: 0 8px 8px;
}
.rw-group-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px 6px; gap: 8px;
}
.rw-group-label {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.8px;
  text-transform: uppercase; color: var(--rw-muted);
}
.rw-group-count { font-family: var(--rw-mono); font-size: 11px; color: var(--rw-muted); }
.rw-refresh-btn {
  width: 22px; height: 22px; border-radius: 4px;
  display: grid; place-items: center; color: var(--rw-muted);
  margin-left: auto;
}
.rw-refresh-btn:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-refresh-btn[disabled] { opacity: .6; cursor: default; }

.rw-login-hint {
  margin: 4px 8px 8px; padding: 10px 12px;
  background: var(--rw-canvas); border: 1px solid var(--rw-hairline-strong);
  border-radius: 8px;
}
.rw-login-hint-title { font-size: 12.5px; font-weight: 600; color: var(--rw-ink); }
.rw-login-actions { display: flex; align-items: center; gap: 12px; margin-top: 4px; }
.rw-login-link {
  font-size: 12px; color: var(--rw-ink);
  text-decoration: underline; text-underline-offset: 2px;
  text-decoration-color: var(--rw-hairline-strong);
}
.rw-login-link:hover { text-decoration-color: var(--rw-ink); }
.rw-empty { padding: 6px 16px 8px; font-size: 12px; color: var(--rw-muted); }

.rw-chat-group {
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.6px;
  color: var(--rw-muted); text-transform: uppercase;
  padding: 10px 8px 4px;
}
.rw-chat-row {
  display: flex; align-items: center; gap: 8px;
  height: 30px; padding: 0 8px; border-radius: 6px;
  font-size: 13px; color: var(--rw-body); font-weight: 400;
  cursor: pointer; transition: background .12s, color .12s;
  position: relative;
}
.rw-chat-row:hover, .rw-chat-row.is-hover { background: var(--rw-hairline-soft); }
.rw-chat-row.is-active { background: var(--rw-surface-strong); color: var(--rw-ink); font-weight: 500; }
.rw-chat-row-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-row-more {
  width: 22px; height: 22px; border-radius: 4px;
  display: grid; place-items: center;
  color: var(--rw-body); flex-shrink: 0;
  visibility: hidden; margin-left: auto;
}
.rw-row-more.visible { visibility: visible; }
.rw-row-more:hover { background: var(--rw-hairline-strong); }

.rw-chat-row.is-editing {
  padding: 0 4px;
  cursor: default;
}
.rw-rename-input-wrap {
  flex: 1; min-width: 0; display: flex; align-items: center;
}
.rw-rename-input {
  width: 100%; height: 26px;
  background: var(--rw-canvas);
  border: 1px solid var(--rw-ink);
  border-radius: 5px;
  padding: 0 7px;
  font-size: 13px; font-family: inherit;
  color: var(--rw-ink); outline: none;
}
.rw-rename-input:focus {
  box-shadow: 0 0 0 2px rgba(23,23,23,.12);
}

.rw-row-thinking {
  display: inline-flex; align-items: center; justify-content: center; gap: 2px;
  width: 16px; height: 16px;
  color: var(--rw-muted);
  flex-shrink: 0;
}
.rw-row-thinking span {
  width: 3px; height: 3px; border-radius: 999px;
  background: currentColor;
  animation: rw-row-thinking-dot 1.05s ease-in-out infinite;
}
.rw-row-thinking span:nth-child(2) { animation-delay: .14s; }
.rw-row-thinking span:nth-child(3) { animation-delay: .28s; }
@keyframes rw-row-thinking-dot {
  0%, 72%, 100% { opacity: .35; transform: translateY(0); }
  36% { opacity: 1; transform: translateY(-2px); }
}

.rw-row-menu {
  position: absolute; top: 100%; right: 4px; margin-top: 2px;
  width: 168px; background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong); border-radius: 8px;
  padding: 4px;
  box-shadow: 0 10px 24px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.04);
  z-index: 25;
}

.rw-menu-item {
  display: flex; align-items: center; gap: 9px;
  width: 100%; height: 30px; padding: 0 10px;
  border-radius: 5px; font-size: 12.5px; font-weight: 500;
  color: var(--rw-ink); cursor: pointer;
}
.rw-menu-item:hover { background: var(--rw-surface-strong); }
.rw-menu-item.is-danger { color: var(--rw-danger); }
.rw-menu-item.is-danger:hover { background: rgba(192,56,43,.06); }
.rw-menu-divider { height: 1px; background: var(--rw-hairline); margin: 4px 6px; }

/* Bottom user card */
.rw-bottom {
  border-top: 1px solid var(--rw-hairline);
  padding: 10px;
  display: flex; flex-direction: column; gap: 4px;
  background: var(--rw-canvas-soft);
}
.rw-menu-wrap { position: relative; }
.rw-user-menu {
  position: absolute; left: 0; right: 0;
  bottom: calc(100% + 6px);
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong); border-radius: 10px;
  padding: 4px;
  box-shadow: 0 12px 32px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.04);
  z-index: 20;
}
.rw-user-menu-head {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 10px 12px;
  border-bottom: 1px solid var(--rw-hairline);
  margin-bottom: 4px;
}
.rw-user-menu-name {
  font-size: 13.5px; font-weight: 600; color: var(--rw-ink); line-height: 1.2;
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.rw-role-badge {
  display: inline-flex; align-items: center;
  padding: 1px 6px; border-radius: 4px;
  background: #171717; color: #ffffff;
  font-size: 10px; font-weight: 600; letter-spacing: 0.4px;
  text-transform: uppercase; line-height: 1.4;
  font-family: var(--rw-mono);
}
.rw-user-menu-mail { font-size: 11.5px; color: var(--rw-muted); margin-top: 3px; line-height: 1.2; font-family: var(--rw-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-menu-section,
.raven-workbench button.rw-user-menu-item {
  display: flex; align-items: center; gap: 10px;
  padding: 6px 10px; height: 32px;
  border-radius: 6px; font-size: 13px; color: var(--rw-ink); font-weight: 500;
}
.rw-menu-section {
  cursor: default;
}
.raven-workbench button.rw-user-menu-item {
  cursor: pointer; width: 100%; text-align: left;
}
.raven-workbench button.rw-user-menu-item:hover { background: var(--rw-surface-strong); }
.rw-menu-leading { color: var(--rw-body); flex-shrink: 0; }
.rw-kbd-right { margin-left: auto; font-family: var(--rw-mono); font-size: 11px; color: var(--rw-muted); }
.rw-lang-pill {
  display: inline-flex; margin-left: auto;
  background: var(--rw-surface-strong); border-radius: 6px;
  padding: 2px; font-family: var(--rw-mono); font-size: 11px; font-weight: 600;
}
.rw-lang-opt { padding: 3px 8px; border-radius: 4px; color: var(--rw-muted); cursor: pointer; }
.rw-lang-opt.active { background: var(--rw-canvas); color: var(--rw-ink); box-shadow: 0 1px 2px rgba(0,0,0,.06); }

.rw-user-card {
  display: flex; align-items: center; gap: 10px;
  padding: 6px; border-radius: 8px; cursor: pointer;
  transition: background .12s;
}
.rw-user-card:hover, .rw-user-card.open { background: var(--rw-surface-strong); }
.rw-avatar {
  width: 30px; height: 30px; border-radius: 999px;
  background: linear-gradient(135deg, #cfe7ff 0%, #a8c8e8 100%);
  color: var(--rw-ink);
  display: grid; place-items: center;
  font-size: 11px; font-weight: 600;
  flex-shrink: 0;
  border: 1px solid rgba(0,0,0,.06);
  text-transform: uppercase;
}
.rw-avatar.lg { width: 34px; height: 34px; font-size: 13px; }
.rw-user-meta { flex: 1; min-width: 0; }
.rw-user-name { font-size: 13px; font-weight: 600; color: var(--rw-ink); line-height: 1.2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-user-role { font-size: 11px; color: var(--rw-muted); margin-top: 2px; line-height: 1.2; font-family: var(--rw-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-chevron { color: var(--rw-muted); transition: transform .15s; flex-shrink: 0; }
.rw-chevron.flipped { transform: rotate(180deg); }

/* ---------- Main pane ---------- */
.rw-main {
  flex: 1; min-width: 0; min-height: 0;
  display: flex; flex-direction: column;
  background: var(--rw-canvas); height: 100%;
}

/* ---------- Modal ---------- */
.rw-modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.4);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  padding: 16px; z-index: 100;
}
.rw-modal {
  width: 100%; max-width: 380px;
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 14px;
  padding: 22px;
  box-shadow: 0 24px 64px rgba(0,0,0,.18);
}
.rw-modal.rw-settings-modal {
  max-width: 420px;
}
.rw-settings-account-strip {
  margin-top: 16px;
  padding: 12px 0 16px;
  border-bottom: 1px solid var(--rw-hairline);
  display: flex;
  align-items: center;
  gap: 11px;
}
.rw-settings-account-meta {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.rw-settings-account-meta strong {
  font-size: 13.5px;
  font-weight: 650;
  color: var(--rw-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rw-settings-account-meta span {
  font-size: 11.5px;
  color: var(--rw-muted);
  font-family: var(--rw-mono);
}
.rw-profile-role-chip {
  margin-left: auto;
  flex-shrink: 0;
  border-radius: 999px;
  background: #e8f7ef;
  color: #116b3a;
  border: 1px solid #c8ead6;
  padding: 4px 9px;
  font-size: 11.5px;
  font-weight: 650;
}
.rw-select {
  width: 100%;
  height: 38px;
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 8px;
  padding: 0 34px 0 12px;
  font-size: 13.5px;
  outline: none;
  background-color: var(--rw-canvas);
  color: var(--rw-ink);
  font-family: inherit;
  appearance: none;
  background-image: linear-gradient(45deg, transparent 50%, var(--rw-muted) 50%), linear-gradient(135deg, var(--rw-muted) 50%, transparent 50%);
  background-position: calc(100% - 17px) 16px, calc(100% - 12px) 16px;
  background-size: 5px 5px, 5px 5px;
  background-repeat: no-repeat;
}
.rw-select:focus {
  border-color: var(--rw-ink);
}
.rw-input:disabled {
  background: var(--rw-canvas-soft);
  color: var(--rw-muted);
  cursor: not-allowed;
}
.rw-settings-permission {
  min-height: 40px;
  border: 1px solid var(--rw-hairline);
  border-radius: 8px;
  padding: 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--rw-body);
  font-size: 12.5px;
}
.rw-settings-permission strong {
  margin-left: auto;
  color: var(--rw-ink);
  font-size: 12.5px;
}
.raven-workbench button.rw-save-profile-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.rw-modal-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.rw-modal-title { font-size: 16px; font-weight: 600; color: var(--rw-ink); margin: 0; }
.rw-modal-sub { font-size: 12px; color: var(--rw-muted); margin: 4px 0 0; }
.rw-modal-close { width: 28px; height: 28px; border-radius: 6px; display: grid; place-items: center; color: var(--rw-body); }
.rw-modal-close:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-auth-tabs {
  margin-top: 18px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px;
  padding: 3px;
  background: var(--rw-surface-strong);
  border-radius: 8px;
}
.rw-auth-tabs button {
  height: 30px;
  border-radius: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--rw-body);
}
.rw-auth-tabs button.active {
  background: var(--rw-canvas);
  color: var(--rw-ink);
  box-shadow: 0 1px 2px rgba(0,0,0,.08);
}
.rw-modal-form { margin-top: 18px; display: flex; flex-direction: column; gap: 14px; }
.rw-form-field { display: flex; flex-direction: column; gap: 6px; }
.rw-form-label { font-size: 12px; color: var(--rw-body); font-weight: 500; }
.rw-input {
  width: 100%; height: 38px;
  border: 1px solid var(--rw-hairline-strong); border-radius: 8px;
  padding: 0 12px; font-size: 13.5px; outline: none;
  background: var(--rw-canvas);
}
.rw-input:focus { border-color: var(--rw-ink); }
.rw-modal-actions { display: flex; gap: 10px; padding-top: 4px; }
.raven-workbench button.rw-btn-primary {
  height: 36px; padding: 0 16px;
  background: var(--rw-primary); color: var(--rw-on-primary);
  border-radius: 8px; font-size: 13.5px; font-weight: 500;
  transition: background .15s, color .15s;
}
.raven-workbench button.rw-btn-primary:hover:not(:disabled) {
  background: var(--rw-primary-hover);
  color: var(--rw-on-primary);
}
.raven-workbench button.rw-btn-primary:active:not(:disabled) {
  background: var(--rw-primary-active);
  color: var(--rw-on-primary);
}
.rw-btn-primary:disabled { opacity: .6; cursor: default; }
.rw-btn-ghost {
  height: 36px; padding: 0 14px;
  background: var(--rw-canvas); color: var(--rw-ink);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 8px; font-size: 13.5px; font-weight: 500;
}
.rw-btn-ghost:hover { background: var(--rw-surface-strong); }

/* ---------- Scrollbar ---------- */
.rw-chat-list::-webkit-scrollbar { width: 10px; height: 10px; }
.rw-chat-list::-webkit-scrollbar-track { background: transparent; }
.rw-chat-list::-webkit-scrollbar-thumb {
  background: #e6e6ea; border-radius: 999px; border: 2px solid var(--rw-canvas);
}
.rw-chat-list::-webkit-scrollbar-thumb:hover { background: var(--rw-muted-soft); }

/* ---------- Responsive ---------- */
@media (max-width: 900px) {
  .rw-sidebar { width: 240px; }
}

@media (max-width: 720px) {
  .raven-workbench { position: relative; }
  .rw-sidebar {
    position: absolute; left: 0; top: 0; bottom: 0;
    width: min(82vw, 320px);
    z-index: 40;
    box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12);
    transform: translateX(-100%);
    transition: transform .25s ease;
  }
  .rw-modal.rw-settings-modal {
    max-height: calc(100vh - 24px);
    overflow: auto;
  }
}
</style>
