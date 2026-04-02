<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import type { PromptsConfigData } from '@/types'

const appStore = useAppStore()
const router = useRouter()
const route = useRoute()

const navItems = [
  {
    key: 'prompts',
    label: 'Prompt 配置',
    path: '/admin/prompts',
    description: '编辑 prompts_config.yaml 并刷新缓存',
  },
  {
    key: 'users',
    label: '用户管理',
    path: '/admin/users',
    description: '管理对话用户、重置密码',
  },
  {
    key: 'releases',
    label: 'App Release',
    path: '/admin/releases',
    description: '上传 Linux / macOS / Windows 发布包',
  },
  {
    key: 'repo-settings',
    label: 'Git 仓库配置',
    path: '/admin/repo-settings',
    description: '配置 OAM/协议栈代码仓库地址与鉴权',
  },
]

const configState = reactive<PromptsConfigData>({
  path: 'app/prompts/prompts_config.yaml',
  content: '',
  updated_at: '',
  size: 0,
  checksum: '',
  summary: {
    log_type_keys: [],
    has_default_plan: false,
    has_default_summary: false,
  },
})

const lastChecksum = ref('')
const lastSavedContent = ref('')

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingConfig = ref(false)
const saving = ref(false)
const conflict = ref(false)
const conflictMessage = ref('')

const authForm = reactive({
  username: '',
  password: '',
})

const formatBytes = (size: number) => {
  if (Number.isNaN(size) || size === undefined || size === null) return '--'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

const formatTimestamp = (value?: string) => {
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

const formatRelative = (value?: string) => {
  if (!value) return ''
  const diff = Date.now() - new Date(value).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}

const hasUnsavedChanges = computed(() => configState.content !== lastSavedContent.value)

const statusLabel = computed(() => {
  if (!isAuthenticated.value) return '未登录'
  if (loadingConfig.value) return '同步中'
  if (saving.value) return '保存中'
  if (conflict.value) return '检测到冲突'
  return hasUnsavedChanges.value ? '草稿未保存' : '已与磁盘同步'
})

const statusTone = computed(() => {
  if (!isAuthenticated.value) return 'bg-slate-700 text-slate-100'
  if (conflict.value) return 'bg-amber-100 text-amber-800'
  if (hasUnsavedChanges.value) return 'bg-cyan-100 text-cyan-900'
  return 'bg-emerald-100 text-emerald-900'
})

const navVisible = computed(() => appStore.adminSidebarVisible)

const readableUpdatedAt = computed(() => {
  if (!configState.updated_at) return '尚未加载'
  return `${formatTimestamp(configState.updated_at)} (${formatRelative(configState.updated_at)})`
})

const activeNavKey = computed(() => {
  if (route.path.startsWith('/admin/users')) return 'users'
  if (route.path.startsWith('/admin/releases')) return 'releases'
  if (route.path.startsWith('/admin/repo-settings')) return 'repo-settings'
  if (route.path.startsWith('/admin')) return 'prompts'
  return ''
})

const parseErrorMessage = (err: any) => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
}

const persistToken = (token: string) => {
  adminToken.set(token)
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const fetchConfig = async (withToast = false) => {
  loadingConfig.value = true
  conflict.value = false
  conflictMessage.value = ''
  try {
    const resp = await adminApi.fetchPromptsConfig()
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '无法读取配置')
    }
    Object.assign(configState, resp.data)
    lastChecksum.value = resp.data.checksum
    lastSavedContent.value = resp.data.content
    if (withToast) {
      appStore.showNotification({
        title: '已从磁盘刷新',
        message: `最近修改：${readableUpdatedAt.value}`,
        type: 'info',
      })
    }
  } catch (err: any) {
    appStore.showNotification({
      title: '读取失败',
      message: parseErrorMessage(err),
      type: 'error',
    })
    if (err?.response?.status === 401) {
      clearAuth()
    }
  } finally {
    loadingConfig.value = false
  }
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({
      title: '请输入用户名和密码',
      type: 'warning',
    })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '登录失败')
    }
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({
      title: '登录成功',
      message: `欢迎，${resp.data.username}`,
      type: 'success',
    })
    await fetchConfig()
  } catch (err: any) {
    appStore.showNotification({
      title: '登录失败',
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    isLoggingIn.value = false
  }
}

const handleSave = async (force = false) => {
  if (!isAuthenticated.value) return
  saving.value = true
  conflict.value = false
  conflictMessage.value = ''
  try {
    const resp = await adminApi.savePromptsConfig({
      content: configState.content,
      expected_checksum: lastChecksum.value || undefined,
      force,
    })
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '保存失败')
    }
    Object.assign(configState, resp.data)
    lastChecksum.value = resp.data.checksum
    lastSavedContent.value = resp.data.content
    appStore.showNotification({
      title: '保存成功',
      message: '文件已更新',
      type: 'success',
    })
  } catch (err: any) {
    if (err?.response?.status === 409) {
      conflict.value = true
      conflictMessage.value = parseErrorMessage(err)
      appStore.showNotification({
        title: '检测到新版本',
        message: conflictMessage.value,
        type: 'warning',
      })
    } else {
      appStore.showNotification({
        title: '保存失败',
        message: parseErrorMessage(err),
        type: 'error',
      })
    }
  } finally {
    saving.value = false
  }
}

const handleReload = async () => {
  if (hasUnsavedChanges.value) {
    const confirmed = window.confirm('有未保存的修改，确定要丢弃并从磁盘重新加载吗？')
    if (!confirmed) return
  }
  await fetchConfig(true)
}

const handleLogout = async () => {
  try {
    await adminApi.logout()
  } catch {
    // ignore network errors on logout
  } finally {
    clearAuth()
    appStore.showNotification({
      title: '已退出登录',
      type: 'info',
    })
  }
}

const handleNavClick = (item: (typeof navItems)[number]) => {
  if (item.path && route.path !== item.path) {
    router.push(item.path)
  }
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await fetchConfig()
    } else {
      clearAuth()
    }
  } catch {
    clearAuth()
  }
}

const handleKeydown = (event: KeyboardEvent) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (isAuthenticated.value) {
      handleSave()
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  bootstrap()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="admin-console admin-prompts-page">
    <header class="admin-topbar">
      <div class="admin-topbar-inner">
        <div class="admin-topbar-left">
          <button
            class="admin-icon-btn"
            :disabled="!isAuthenticated"
            @click="toggleNavVisibility"
            :title="navVisible ? '隐藏侧边栏' : '显示侧边栏'"
            aria-label="切换侧边栏"
          >
            {{ navVisible ? '☰' : '▤' }}
          </button>
          <div>
            <h1 class="admin-title">后台管理</h1>
            <p class="admin-subtitle">Prompt 配置中心</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full" :class="statusTone">
            {{ statusLabel }}
          </span>
          <button
            v-if="isAuthenticated"
            class="admin-logout-btn"
            @click="handleLogout"
          >
            退出
          </button>
        </div>
      </div>
    </header>

    <button
      v-if="isAuthenticated && navVisible"
      class="admin-sidebar-backdrop"
      @click="toggleNavVisibility"
      aria-label="关闭侧边栏"
    ></button>

    <aside
      v-if="isAuthenticated"
      class="admin-sidebar"
      :class="{ 'is-hidden': !navVisible }"
    >
      <div class="space-y-2">
        <button
          v-for="item in navItems"
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
              <h2 class="text-lg font-semibold text-slate-900">登录后台</h2>
              <p class="text-sm text-slate-500">请输入管理员凭证继续</p>
            </div>
            <span class="text-xs text-slate-500">内部安全访问</span>
          </div>
          <div class="grid gap-4 md:grid-cols-2">
            <form class="space-y-4" @submit.prevent="handleLogin">
              <label class="block">
                <span class="text-sm text-slate-700">用户名</span>
                <input
                  v-model="authForm.username"
                  type="text"
                  class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  placeholder="admin"
                  autocomplete="username"
                />
              </label>
              <label class="block">
                <span class="text-sm text-slate-700">密码</span>
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
                  {{ isLoggingIn ? '登录中…' : '登录' }}
                </button>
                <p class="text-xs text-slate-500">
                  凭证在 admin_auth.yaml 配置，建议登录后立即更改
                </p>
              </div>
            </form>
            <div class="bg-slate-50 rounded-lg p-4 space-y-3 text-sm text-slate-700">
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-emerald-400"></span>
                <span>仅限内部管理访问，凭证按需分发</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-cyan-400"></span>
                <span>登录后可进行配置维护，未登录状态不会读取数据</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-amber-400"></span>
                <span>会话基于 Bearer Token，关闭标签后自动清除</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else class="space-y-4">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4">
          <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-3">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">prompts_config.yaml</h2>
              <p class="text-sm text-slate-500">
                输入框内即为磁盘内容，保存后立即刷新 Agent 缓存；Ctrl/Cmd + S 可快速保存
              </p>
            </div>
            <div class="editor-toolbar-actions flex items-center gap-2">
              <button
                class="px-3 py-2 text-sm rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50"
                :disabled="loadingConfig"
                @click="handleReload"
              >
                重新加载
              </button>
              <button
                class="px-3 py-2 text-sm rounded-lg bg-cyan-600 text-white hover:bg-cyan-700 transition disabled:opacity-60"
                :disabled="saving || !hasUnsavedChanges"
                @click="handleSave"
              >
                {{ saving ? '保存中…' : '保存更改' }}
              </button>
              <button
                v-if="conflict"
                class="px-3 py-2 text-sm rounded-lg border border-amber-300 text-amber-700 bg-amber-50 hover:bg-amber-100"
                :disabled="saving"
                @click="handleSave(true)"
              >
                强制保存
              </button>
            </div>
          </div>
          <div class="editor-file-summary mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <div class="grid gap-2 text-xs text-slate-600 md:grid-cols-2">
              <div class="flex items-center gap-2">
                <span class="text-slate-500">路径</span>
                <span class="font-mono text-[11px] text-slate-800 break-all">{{ configState.path }}</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-slate-500">大小</span>
                <span>{{ formatBytes(configState.size) }}</span>
              </div>
            </div>
          </div>
          <div class="rounded-lg border border-slate-200 bg-slate-50 overflow-hidden">
            <textarea
              v-model="configState.content"
              class="w-full h-[420px] md:h-[560px] resize-none bg-white font-mono text-xs text-slate-800 p-4 focus:outline-none"
              spellcheck="false"
              :disabled="loadingConfig"
            ></textarea>
          </div>
          <div class="editor-meta-row flex items-center justify-between text-xs text-slate-500 mt-2">
            <div class="editor-meta-left flex items-center gap-3">
              <span>长度：{{ configState.content.length }} 字符</span>
              <span
                :class="hasUnsavedChanges ? 'text-amber-600' : 'text-emerald-600'"
              >{{ hasUnsavedChanges ? '有未保存的修改' : '已与磁盘同步' }}</span>
              <span v-if="conflict" class="text-amber-700 font-semibold">
                {{ conflictMessage || '文件在其他位置被更新' }}
              </span>
            </div>
            <div class="editor-meta-right flex items-center gap-2">
              <span class="px-2 py-1 rounded bg-slate-100 border border-slate-200">
                {{ readableUpdatedAt }}
              </span>
              <span class="px-2 py-1 rounded bg-slate-100 border border-slate-200">
                校验和：{{ lastChecksum || configState.checksum }}
              </span>
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

  .editor-toolbar-actions {
    width: 100%;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
  }

  .editor-toolbar-actions button {
    width: 100%;
  }

  .editor-meta-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .editor-meta-right,
  .editor-meta-left {
    flex-wrap: wrap;
  }
}
</style>
