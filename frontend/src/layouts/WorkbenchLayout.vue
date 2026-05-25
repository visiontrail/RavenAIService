<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import { useChatSessionStore } from '@/stores/chatSession'
import { useConversationRunsStore } from '@/stores/conversationRuns'
import { userApi } from '@/api/user'
import type { ChatSessionSummary } from '@/types'
import brandIcon from '@/assets/icon.png'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const userStore = useUserStore()
const sessionStore = useChatSessionStore()
const runsStore = useConversationRunsStore()

/**
 * Union of backend-reported running sessions (``run_status === 'running'``)
 * and the local optimistic running overlay maintained by the run store. The
 * overlay covers the gap between sendMessage and the next sessions list
 * refresh.
 */
const runningSessionIds = computed(() => {
  const ids = new Set<string>()
  for (const s of sessionStore.sessions) {
    if (s.run_status === 'running') ids.add(s.id)
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
    sessionStore.load().catch(() => { /* swallow; overlay still works */ })
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
const lang = ref<'zh' | 'en'>('zh')

const showLoginModal = ref(false)
const loginForm = reactive({ username: '', password: '' })
const isLoggingIn = ref(false)

const userMenuRef = ref<HTMLElement | null>(null)
const userButtonRef = ref<HTMLElement | null>(null)
const rowMenuRef = ref<HTMLElement | null>(null)

const isLoggedIn = computed(() => userStore.isAuthenticated)
const currentUserName = computed(() =>
  userStore.profile?.display_name || userStore.profile?.username || '用户'
)
const currentUserEmail = computed(() => userStore.profile?.email || '')
const currentUserRole = computed(() => (userStore.profile?.role || 'user').toString().toLowerCase())
const isAdmin = computed(() => isLoggedIn.value && currentUserRole.value === 'admin')
const userInitial = computed(() => (currentUserName.value || 'U').slice(0, 2).toUpperCase())
const currentUserStatusText = computed(() =>
  currentUserEmail.value || (isLoggedIn.value ? '已登录' : '未登录')
)

const goToAdminConsole = () => {
  showUserMenu.value = false
  router.push('/admin')
}

const navItems = computed(() => ([
  { id: 'logs',    label: '日志列表',   to: '/logs',          icon: 'logs', activeNames: ['Logs', 'LogDetail'] },
  { id: 'devices', label: '设备机柜',   to: '/devices',       icon: 'device' },
  { id: 'pkgs',    label: '重构包仓库', to: '/raven-manager', icon: 'box' },
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

  const groups: { label: string; items: ChatSessionSummary[] }[] = [
    { label: '今天', items: [] },
    { label: '昨天', items: [] },
    { label: '本周', items: [] },
    { label: '更早', items: [] },
  ]

  for (const s of filteredSessions.value) {
    const t = s.last_message_at ? new Date(s.last_message_at).getTime() : 0
    if (t >= today) groups[0].items.push(s)
    else if (t >= yesterday) groups[1].items.push(s)
    else if (t >= weekStart) groups[2].items.push(s)
    else groups[3].items.push(s)
  }
  return groups.filter((g) => g.items.length > 0)
})

const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as Node

  if (showUserMenu.value && userMenuRef.value && userButtonRef.value &&
      !userMenuRef.value.contains(target) && !userButtonRef.value.contains(target)) {
    showUserMenu.value = false
  }

  if (openRowMenuId.value && rowMenuRef.value && !rowMenuRef.value.contains(target)) {
    openRowMenuId.value = null
  }
}

const handleKey = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    showUserMenu.value = false
    openRowMenuId.value = null
  }
}

const bootstrapUser = async () => {
  await userStore.bootstrap()
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
      appStore.showNotification({ title: '同步会话失败', type: 'error' })
    }
  } else {
    sessionStore.reset()
  }
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
    appStore.showNotification({ title: '同步会话失败', type: 'error' })
  }
}

const deleteSession = async (id: string) => {
  openRowMenuId.value = null
  const confirmed = window.confirm('确定要删除该对话吗？此操作不可恢复。')
  if (!confirmed) return
  try {
    await sessionStore.removeSession(id)
    runsStore.clearSession(id)
    appStore.showNotification({ title: '会话已删除', type: 'success' })
  } catch (error) {
    console.error('删除会话失败', error)
    appStore.showNotification({ title: '删除失败', type: 'error' })
  }
}

const handleUserLogin = async () => {
  if (!loginForm.username || !loginForm.password) {
    appStore.showNotification({ title: '请输入用户名和密码', type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await userApi.login(loginForm.username.trim(), loginForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '登录失败')
    userStore.setToken(resp.data.token)
    userStore.setProfile(resp.data.user)
    appStore.showNotification({ title: '登录成功', type: 'success' })
    showLoginModal.value = false
    loginForm.username = ''
    loginForm.password = ''
    await sessionStore.load()
  } catch (error: any) {
    appStore.showNotification({
      title: '登录失败',
      message: error?.message || '请检查账号密码',
      type: 'error',
    })
  } finally {
    isLoggingIn.value = false
  }
}

const handleUserLogout = () => {
  userStore.clear()
  sessionStore.reset()
  showUserMenu.value = false
}
</script>

<template>
  <div class="raven-workbench" :class="{ 'lang-en': lang === 'en' }">
    <!-- Sidebar -->
    <aside class="rw-sidebar">
      <!-- Brand -->
      <div class="rw-brand">
        <div class="rw-brand-left">
          <img :src="brandIcon" alt="" class="rw-brand-mark" aria-hidden="true" />
          <div>
            <div class="rw-brand-name">RavenAI</div>
            <div class="rw-brand-sub">BASEBAND · WORKBENCH</div>
          </div>
        </div>
        <button class="rw-icon-btn" title="搜索对话" @click="showSearchBox = !showSearchBox" aria-label="搜索对话">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        </button>
      </div>

      <!-- New chat -->
      <button class="rw-new-btn" @click="startNewChat">
        <span class="rw-new-btn-left">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          新建对话
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
          <span class="rw-group-label">最近对话</span>
          <span v-if="isLoggedIn" class="rw-group-count">{{ sessionStore.sessions.length }}</span>
          <button
            v-if="isLoggedIn"
            class="rw-refresh-btn"
            :disabled="sessionStore.loading"
            @click="reloadSessions"
            title="刷新"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: sessionStore.loading }"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>
          </button>
        </div>

        <template v-if="!isLoggedIn">
          <div class="rw-login-hint">
            <div class="rw-login-hint-title">登录可同步历史对话</div>
            <button class="rw-login-link" @click="showLoginModal = true">立即登录 →</button>
          </div>
        </template>
        <template v-else-if="sessionStore.loading">
          <div class="rw-empty">会话加载中…</div>
        </template>
        <template v-else-if="!sessionStore.sessions.length">
          <div class="rw-empty">暂无会话，开始新的对话吧</div>
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
              }"
              @click="handleSelectSession(session)"
              @mouseenter="hoverSessionId = session.id"
              @mouseleave="hoverSessionId = null"
            >
              <span class="rw-chat-row-text">{{ session.title || '未命名对话' }}</span>
              <span
                v-if="isSessionRunning(session.id)"
                class="rw-row-spinner"
                title="正在运行"
                aria-label="正在运行"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>
              </span>
              <button
                class="rw-row-more"
                :class="{ visible: hoverSessionId === session.id || openRowMenuId === session.id }"
                @click.stop="openRowMenuId = openRowMenuId === session.id ? null : session.id"
                aria-label="更多"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></svg>
              </button>
              <div
                v-if="openRowMenuId === session.id"
                ref="rowMenuRef"
                class="rw-row-menu"
                @click.stop
              >
                <button class="rw-menu-item" @click="openRowMenuId = null">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4l10-10-4-4L4 16zM14 6l4 4"/></svg>
                  重命名对话
                </button>
                <button class="rw-menu-item" @click="openRowMenuId = null">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v6M9 8h6l2 6H7zM12 14v8"/></svg>
                  置顶对话
                </button>
                <div class="rw-menu-divider"/>
                <button class="rw-menu-item is-danger" @click="deleteSession(session.id)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>
                  删除对话
                </button>
              </div>
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
                  <span v-if="isAdmin" class="rw-role-badge">管理员</span>
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
              后台管理
              <span class="rw-kbd-right">/admin</span>
            </button>
            <div v-if="isAdmin" class="rw-menu-divider"/>
            <div class="rw-menu-section">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>
              <span>语言</span>
              <span class="rw-lang-pill">
                <span class="rw-lang-opt" :class="{ active: lang === 'zh' }" @click="lang = 'zh'">中</span>
                <span class="rw-lang-opt" :class="{ active: lang === 'en' }" @click="lang = 'en'">EN</span>
              </span>
            </div>
            <button class="rw-user-menu-item" @click="showUserMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33 1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82 1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              设置
              <span class="rw-kbd-right">⌘ ,</span>
            </button>
            <button class="rw-user-menu-item" @click="showUserMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 1.5-2.5 2-2.5 3.5"/><circle cx="12" cy="17" r="0.4" fill="currentColor"/></svg>
              帮助与快捷键
              <span class="rw-kbd-right">?</span>
            </button>
            <div class="rw-menu-divider"/>
            <button
              class="rw-user-menu-item"
              @click="isLoggedIn ? handleUserLogout() : (showUserMenu = false, showLoginModal = true)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="rw-menu-leading"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>
              {{ isLoggedIn ? '退出登录' : '立即登录' }}
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
                <span v-if="isAdmin">管理员 · {{ currentUserStatusText }}</span>
                <span v-else-if="isLoggedIn">{{ currentUserStatusText }}</span>
                <span v-else>未登录 · 点击登录</span>
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

    <!-- Login modal -->
    <div v-if="showLoginModal" class="rw-modal-backdrop" @click.self="showLoginModal = false">
      <div class="rw-modal">
        <div class="rw-modal-head">
          <div>
            <h3 class="rw-modal-title">登录账户</h3>
            <p class="rw-modal-sub">登录可同步历史对话</p>
          </div>
          <button class="rw-modal-close" @click="showLoginModal = false" aria-label="关闭">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
          </button>
        </div>
        <form class="rw-modal-form" @submit.prevent="handleUserLogin">
          <label class="rw-form-field">
            <span class="rw-form-label">用户名</span>
            <input v-model="loginForm.username" type="text" class="rw-input" placeholder="输入用户名" autocomplete="username" />
          </label>
          <label class="rw-form-field">
            <span class="rw-form-label">密码</span>
            <input v-model="loginForm.password" type="password" class="rw-input" placeholder="输入密码" autocomplete="current-password" />
          </label>
          <div class="rw-modal-actions">
            <button type="submit" class="rw-btn-primary" :disabled="isLoggingIn">
              {{ isLoggingIn ? '登录中…' : '立即登录' }}
            </button>
            <button type="button" class="rw-btn-ghost" @click="showLoginModal = false">取消</button>
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
  text-transform: uppercase; margin-top: 3px;
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
.rw-login-link {
  margin-top: 4px; font-size: 12px; color: var(--rw-ink);
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

.rw-row-spinner {
  display: inline-grid; place-items: center;
  width: 16px; height: 16px;
  color: var(--rw-muted);
  flex-shrink: 0;
  animation: rw-row-spin 1s linear infinite;
}
.rw-row-spinner svg { display: block; }
@keyframes rw-row-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

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
.rw-modal-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.rw-modal-title { font-size: 16px; font-weight: 600; color: var(--rw-ink); margin: 0; }
.rw-modal-sub { font-size: 12px; color: var(--rw-muted); margin: 4px 0 0; }
.rw-modal-close { width: 28px; height: 28px; border-radius: 6px; display: grid; place-items: center; color: var(--rw-body); }
.rw-modal-close:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }
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
}
</style>
