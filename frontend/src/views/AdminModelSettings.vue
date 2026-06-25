<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { LogOut, Menu, PanelLeftClose } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { resolveAdminNavKey, type AdminNavItem } from '@/utils/adminNav'
import { useAdminScope } from '@/composables/useAdminScope'

const { t } = useI18n()
const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const { visibleNavItems } = useAdminScope()

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)

const authForm = reactive({ username: '', password: '' })

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const parseErrorMessage = (err: any) => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return t('admin.parseError')
}

const persistToken = (token: string) => {
  adminToken.set(token)
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const handleNavClick = (item: AdminNavItem) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({ title: t('admin.loginWarning'), type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.loginFailFallback'))
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: t('admin.loginSuccessTitle'), message: t('admin.loginSuccessMsg', { username: resp.data.username }), type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.loginFailFallback'), message: parseErrorMessage(err), type: 'error' })
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
    appStore.showNotification({ title: t('admin.logoutSuccessTitle'), type: 'info' })
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
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
            <p class="admin-subtitle">{{ t('admin.modelSettings.subtitle') }}</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? t('admin.modelSettings.badge') : t('admin.badgeNotLoggedIn') }}
          </span>
          <button v-if="isAuthenticated" class="admin-logout-btn" @click="handleLogout">
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

    <aside v-if="isAuthenticated" class="admin-sidebar" :class="{ 'is-hidden': !navVisible }">
      <div class="space-y-2">
        <button
          v-for="item in visibleNavItems"
          :key="item.key"
          class="admin-side-nav-item"
          :class="{ 'is-active': activeNavKey === item.key }"
          @click="handleNavClick(item)"
        >
          <div class="text-sm font-semibold">{{ item.label }}</div>
          <p v-if="item.description" class="text-xs mt-1 text-slate-400">{{ item.description }}</p>
        </button>
      </div>
    </aside>

    <main class="admin-main" :class="{ 'is-sidebar-hidden': !isAuthenticated || !navVisible }">
      <section v-if="!isAuthenticated" class="admin-login-wrap">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.loginCardTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.loginCardDesc') }}</p>
            </div>
          </div>
          <form class="space-y-4 max-w-md" @submit.prevent="handleLogin">
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
            <button
              type="submit"
              class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
              :disabled="isLoggingIn"
            >
              {{ isLoggingIn ? t('admin.loginBtnLoading') : t('admin.loginBtn') }}
            </button>
          </form>
        </div>
      </section>

      <section v-else class="space-y-4">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.modelSettings.sectionTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.modelSettings.sectionDesc') }}</p>
            </div>
          </div>

          <div class="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">
            <div class="text-sm font-semibold text-slate-800 mb-2">{{ t('admin.modelSettings.requiredVarsTitle') }}</div>
            <ul class="space-y-1 text-sm text-slate-700">
              <li><code>ANTHROPIC_PROVIDER</code> — {{ t('admin.modelSettings.varProviderDesc') }}</li>
              <li><code>ANTHROPIC_API_KEY</code> — {{ t('admin.modelSettings.varApiKeyDesc') }}</li>
            </ul>
          </div>

          <div class="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 mt-3">
            <div class="text-sm font-semibold text-slate-800 mb-2">{{ t('admin.modelSettings.optionalVarsTitle') }}</div>
            <ul class="space-y-1 text-sm text-slate-700">
              <li><code>ANTHROPIC_BASE_URL</code> — {{ t('admin.modelSettings.varBaseUrlDesc') }}</li>
              <li><code>ANTHROPIC_MODEL</code> — {{ t('admin.modelSettings.varModelDesc') }}</li>
              <li><code>ANTHROPIC_SMALL_FAST_MODEL</code> — {{ t('admin.modelSettings.varSmallFastModelDesc') }}</li>
              <li><code>ANTHROPIC_MAX_HISTORY_TURNS</code> — {{ t('admin.modelSettings.varMaxHistoryDesc') }}</li>
              <li><code>ANTHROPIC_SMALL_FAST_MAX_TOKENS</code> — {{ t('admin.modelSettings.varSmallFastMaxTokensDesc') }}</li>
              <li><code>ANTHROPIC_SMALL_FAST_REQUEST_TIMEOUT_SECONDS</code> — {{ t('admin.modelSettings.varSmallFastTimeoutDesc') }}</li>
              <li><code>DEVICE_AGENT_PERMISSION_TIMEOUT_SECONDS</code> — {{ t('admin.modelSettings.varDevicePermTimeoutDesc') }}</li>
              <li><code>DEVICE_AGENT_RESULT_EXCERPT_BYTES</code> — {{ t('admin.modelSettings.varDeviceExcerptDesc') }}</li>
              <li><code>DEVICE_AGENT_RESULT_MAX_BYTES</code> — {{ t('admin.modelSettings.varDeviceMaxBytesDesc') }}</li>
              <li><code>DEVICE_AGENT_MAX_REMOTE_TOOLS</code> — {{ t('admin.modelSettings.varDeviceMaxToolsDesc') }}</li>
            </ul>
          </div>

          <div class="text-sm text-slate-500 mt-3 space-y-1">
            <p>{{ t('admin.modelSettings.restartNote') }}</p>
            <p>{{ t('admin.modelSettings.deepseekNote') }}</p>
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
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
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
  max-width: 720px;
  margin: 1.25rem auto 0;
}

.admin-sidebar-backdrop {
  display: none;
}

@media (max-width: 768px) {
  .admin-console {
    --admin-sidebar-width: min(84vw, 320px);
  }
  .admin-main.is-sidebar-hidden {
    padding-left: 1rem;
  }
  .admin-sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 55;
    background: rgba(15, 23, 42, 0.45);
    border: 0;
  }
}
</style>
