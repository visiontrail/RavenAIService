<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Menu, PanelLeftClose, RefreshCw, Save } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import type { PromptEntry, PromptsConfigData } from '@/types'

type PromptSnapshot = Record<string, string>

interface PromptAgentGroup {
  key: string
  name: string
  description?: string | null
  prompts: PromptEntry[]
}

interface PromptFunctionGroup {
  key: string
  name: string
  description?: string | null
  agents: PromptAgentGroup[]
}

const appStore = useAppStore()
const router = useRouter()
const route = useRoute()

const navItems = adminNavItems

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
    function_keys: [],
    editable_prompt_count: 0,
  },
  prompts: [],
})

const lastChecksum = ref('')
const lastSavedPrompts = ref<PromptSnapshot>({})
const selectedPromptId = ref('')

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

const snapshotPrompts = (prompts: PromptEntry[]): PromptSnapshot =>
  prompts.reduce<PromptSnapshot>((acc, prompt) => {
    acc[prompt.id] = prompt.content
    return acc
  }, {})

const currentPromptSnapshot = computed(() => snapshotPrompts(configState.prompts))

const hasUnsavedChanges = computed(() => {
  const current = currentPromptSnapshot.value
  const saved = lastSavedPrompts.value
  const currentKeys = Object.keys(current).sort()
  const savedKeys = Object.keys(saved).sort()
  if (currentKeys.length !== savedKeys.length) return true
  return currentKeys.some((key, index) => key !== savedKeys[index] || current[key] !== saved[key])
})

const selectedPrompt = computed(() =>
  configState.prompts.find((prompt) => prompt.id === selectedPromptId.value) || null
)

const selectedPromptContent = computed({
  get: () => selectedPrompt.value?.content || '',
  set: (value: string) => {
    const prompt = selectedPrompt.value
    if (prompt) prompt.content = value
  },
})

const promptGroups = computed<PromptFunctionGroup[]>(() => {
  const functionMap = new Map<string, PromptFunctionGroup>()

  configState.prompts.forEach((prompt) => {
    if (!functionMap.has(prompt.function_key)) {
      functionMap.set(prompt.function_key, {
        key: prompt.function_key,
        name: prompt.function_name,
        description: prompt.function_description,
        agents: [],
      })
    }

    const functionGroup = functionMap.get(prompt.function_key) as PromptFunctionGroup
    let agentGroup = functionGroup.agents.find((agent) => agent.key === prompt.agent_key)
    if (!agentGroup) {
      agentGroup = {
        key: prompt.agent_key,
        name: prompt.agent_name,
        description: prompt.agent_description,
        prompts: [],
      }
      functionGroup.agents.push(agentGroup)
    }
    agentGroup.prompts.push(prompt)
  })

  return Array.from(functionMap.values())
})

const statusLabel = computed(() => {
  if (!isAuthenticated.value) return '未登录'
  if (loadingConfig.value) return '同步中'
  if (saving.value) return '保存中'
  if (conflict.value) return '检测到冲突'
  return hasUnsavedChanges.value ? '草稿未保存' : '已同步'
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

const activeNavKey = computed(() => resolveAdminNavKey(route.path))

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

const ensureSelectedPrompt = () => {
  if (configState.prompts.some((prompt) => prompt.id === selectedPromptId.value)) return
  selectedPromptId.value = configState.prompts[0]?.id || ''
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
    lastSavedPrompts.value = snapshotPrompts(resp.data.prompts || [])
    ensureSelectedPrompt()
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
  if (!isAuthenticated.value || !configState.prompts.length) return
  saving.value = true
  conflict.value = false
  conflictMessage.value = ''
  try {
    const resp = await adminApi.savePromptsConfig({
      prompts: configState.prompts.map((prompt) => ({
        id: prompt.id,
        content: prompt.content,
      })),
      expected_checksum: lastChecksum.value || undefined,
      force,
    })
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '保存失败')
    }
    Object.assign(configState, resp.data)
    lastChecksum.value = resp.data.checksum
    lastSavedPrompts.value = snapshotPrompts(resp.data.prompts || [])
    ensureSelectedPrompt()
    appStore.showNotification({
      title: '保存成功',
      message: '系统提示词已更新并刷新 Agent 缓存',
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
    const confirmed = window.confirm('有未保存的系统提示词修改，确定要丢弃并从磁盘重新加载吗？')
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
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">后台管理</h1>
            <p class="admin-subtitle">系统提示词配置</p>
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
            <LogOut :size="14" />
            <span>退出</span>
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
                <span>登录后按功能和 Agent 维护系统提示词</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-cyan-400"></span>
                <span>保存后立即刷新后台 Agent 提示词缓存</span>
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
        <div class="prompt-header-panel bg-white rounded-2xl shadow-sm border border-slate-200 p-4">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">Agent 系统提示词</h2>
              <p class="text-sm text-slate-500">
                按功能与 Agent 选择对应的系统提示词，保存后立即刷新运行时缓存
              </p>
            </div>
            <div class="editor-toolbar-actions flex items-center gap-2">
              <button
                class="admin-command-btn"
                :disabled="loadingConfig"
                @click="handleReload"
              >
                <RefreshCw :size="15" />
                <span>重新加载</span>
              </button>
              <button
                class="admin-command-btn primary"
                :disabled="saving || !hasUnsavedChanges"
                @click="() => handleSave()"
              >
                <Save :size="15" />
                <span>{{ saving ? '保存中' : '保存' }}</span>
              </button>
              <button
                v-if="conflict"
                class="admin-command-btn warning"
                :disabled="saving"
                @click="handleSave(true)"
              >
                <Save :size="15" />
                <span>强制保存</span>
              </button>
            </div>
          </div>
          <div class="prompt-meta-strip">
            <span>可编辑提示词：{{ configState.summary.editable_prompt_count || configState.prompts.length }}</span>
            <span>配置大小：{{ formatBytes(configState.size) }}</span>
            <span>最近修改：{{ readableUpdatedAt }}</span>
            <span class="prompt-path">{{ configState.path }}</span>
          </div>
        </div>

        <div class="prompt-workbench">
          <aside class="prompt-list-panel">
            <div class="prompt-list-title">
              <span>功能与 Agent</span>
              <span>{{ configState.prompts.length }}</span>
            </div>
            <div v-if="!promptGroups.length" class="prompt-empty">
              未发现可编辑的系统提示词
            </div>
            <div v-for="group in promptGroups" :key="group.key" class="prompt-function-group">
              <div class="prompt-function-name">
                <span>{{ group.name }}</span>
                <small>{{ group.agents.length }} 个 Agent</small>
              </div>
              <p v-if="group.description" class="prompt-function-desc">{{ group.description }}</p>
              <button
                v-for="agent in group.agents"
                :key="agent.key"
                class="prompt-agent-item"
                :class="{ 'is-active': agent.prompts.some((prompt) => prompt.id === selectedPromptId) }"
                @click="selectedPromptId = agent.prompts[0]?.id || ''"
              >
                <span class="prompt-agent-name">{{ agent.name }}</span>
                <span class="prompt-agent-desc">{{ agent.description }}</span>
                <span class="prompt-agent-foot">
                  {{ agent.prompts.map((prompt) => prompt.prompt_label).join('、') }}
                </span>
              </button>
            </div>
          </aside>

          <section class="prompt-editor-panel">
            <template v-if="selectedPrompt">
              <div class="prompt-editor-head">
                <div>
                  <div class="prompt-breadcrumb">
                    {{ selectedPrompt.function_name }} / {{ selectedPrompt.agent_name }}
                  </div>
                  <h3>{{ selectedPrompt.prompt_label }}</h3>
                  <p v-if="selectedPrompt.agent_description">{{ selectedPrompt.agent_description }}</p>
                </div>
                <span
                  class="prompt-dirty-badge"
                  :class="currentPromptSnapshot[selectedPrompt.id] !== lastSavedPrompts[selectedPrompt.id] ? 'is-dirty' : 'is-clean'"
                >
                  {{ currentPromptSnapshot[selectedPrompt.id] !== lastSavedPrompts[selectedPrompt.id] ? '未保存' : '已同步' }}
                </span>
              </div>
              <textarea
                v-model="selectedPromptContent"
                class="prompt-textarea"
                spellcheck="false"
                :disabled="loadingConfig || saving"
              ></textarea>
              <div class="prompt-editor-footer">
                <div class="flex items-center gap-3 flex-wrap">
                  <span>长度：{{ selectedPromptContent.length }} 字符</span>
                  <span v-if="conflict" class="text-amber-700 font-semibold">
                    {{ conflictMessage || '文件在其他位置被更新' }}
                  </span>
                </div>
                <span>校验和：{{ lastChecksum || configState.checksum }}</span>
              </div>
            </template>
            <div v-else class="prompt-empty editor-empty">
              请选择一个 Agent 的系统提示词
            </div>
          </section>
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
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

.admin-command-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.55rem;
  color: #334155;
  background: #ffffff;
  font-size: 0.85rem;
  font-weight: 700;
  padding: 0.55rem 0.8rem;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.admin-command-btn:hover:not(:disabled) {
  background: #f8fafc;
}

.admin-command-btn.primary {
  color: #ffffff;
  background: #0891b2;
  border-color: #0891b2;
}

.admin-command-btn.primary:hover:not(:disabled) {
  background: #0e7490;
}

.admin-command-btn.warning {
  color: #92400e;
  background: #fffbeb;
  border-color: #fbbf24;
}

.admin-command-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.prompt-meta-strip {
  margin-top: 0.9rem;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  color: #475569;
  font-size: 0.75rem;
}

.prompt-meta-strip span {
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  background: #f8fafc;
  padding: 0.35rem 0.55rem;
}

.prompt-meta-strip .prompt-path {
  max-width: 100%;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  word-break: break-all;
}

.prompt-workbench {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  gap: 1rem;
}

.prompt-list-panel,
.prompt-editor-panel {
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

.prompt-list-panel {
  padding: 0.85rem;
  align-self: start;
}

.prompt-list-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #0f172a;
  font-size: 0.85rem;
  font-weight: 800;
  margin-bottom: 0.75rem;
}

.prompt-list-title span:last-child {
  min-width: 1.5rem;
  text-align: center;
  color: #0e7490;
  background: #ecfeff;
  border: 1px solid #a5f3fc;
  border-radius: 999px;
  padding: 0.1rem 0.45rem;
}

.prompt-function-group + .prompt-function-group {
  margin-top: 1rem;
}

.prompt-function-name {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #0f172a;
  font-size: 0.82rem;
  font-weight: 800;
  margin-bottom: 0.25rem;
}

.prompt-function-name small {
  color: #64748b;
  font-weight: 600;
}

.prompt-function-desc {
  color: #64748b;
  font-size: 0.75rem;
  line-height: 1.45;
  margin-bottom: 0.55rem;
}

.prompt-agent-item {
  width: 100%;
  text-align: left;
  display: grid;
  gap: 0.25rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #f8fafc;
  padding: 0.75rem;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.prompt-agent-item + .prompt-agent-item {
  margin-top: 0.5rem;
}

.prompt-agent-item:hover,
.prompt-agent-item.is-active {
  border-color: #06b6d4;
  background: #ecfeff;
}

.prompt-agent-name {
  color: #0f172a;
  font-size: 0.85rem;
  font-weight: 800;
}

.prompt-agent-desc {
  min-height: 2.45rem;
  color: #64748b;
  font-size: 0.75rem;
  line-height: 1.35;
}

.prompt-agent-foot {
  color: #0e7490;
  font-size: 0.72rem;
  font-weight: 700;
}

.prompt-editor-panel {
  min-height: 640px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.prompt-editor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.prompt-editor-head h3 {
  color: #0f172a;
  font-size: 1rem;
  font-weight: 800;
}

.prompt-editor-head p {
  color: #64748b;
  font-size: 0.8rem;
  margin-top: 0.25rem;
}

.prompt-breadcrumb {
  color: #0e7490;
  font-size: 0.72rem;
  font-weight: 800;
  margin-bottom: 0.2rem;
}

.prompt-dirty-badge {
  white-space: nowrap;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 800;
  padding: 0.25rem 0.55rem;
}

.prompt-dirty-badge.is-dirty {
  color: #92400e;
  background: #fef3c7;
}

.prompt-dirty-badge.is-clean {
  color: #047857;
  background: #d1fae5;
}

.prompt-textarea {
  flex: 1;
  min-height: 500px;
  width: 100%;
  resize: vertical;
  border: 0;
  border-radius: 0;
  outline: none;
  color: #1e293b;
  background: #ffffff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8rem;
  line-height: 1.65;
  padding: 1rem;
}

.prompt-textarea:disabled {
  background: #f8fafc;
}

.prompt-editor-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border-top: 1px solid #e2e8f0;
  color: #64748b;
  background: #f8fafc;
  font-size: 0.75rem;
  padding: 0.65rem 1rem;
}

.prompt-empty {
  color: #64748b;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 0.75rem;
  font-size: 0.85rem;
  padding: 1rem;
}

.editor-empty {
  margin: auto;
}

@media (max-width: 1024px) {
  .admin-topbar-inner {
    padding: 0 0.75rem;
  }

  .admin-topbar-right span {
    display: none;
  }

  .prompt-workbench {
    grid-template-columns: 1fr;
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

  .prompt-header-panel {
    border-radius: 0.85rem;
  }

  .prompt-editor-panel {
    min-height: 560px;
  }

  .prompt-editor-head,
  .prompt-editor-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
