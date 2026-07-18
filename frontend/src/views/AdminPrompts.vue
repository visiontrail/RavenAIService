<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Eye, FileText, Layers, LogOut, Menu, PanelLeftClose, RefreshCw, Save } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAppStore } from '@/stores/app'
import { resolveAdminNavKey, type AdminNavItem } from '@/utils/adminNav'
import {
  localizeProjectAgent,
  localizePromptAgent,
  localizePromptFunction,
  localizePromptPreviewLayer,
} from '@/utils/adminPromptMetadata'
import { useAdminScope } from '@/composables/useAdminScope'
import { processMermaidBlocks, renderMarkdown } from '@/utils/markdownRenderer'
import type {
  PromptEntry,
  PromptsConfigData,
  ProjectAgentInfo,
  ProjectRepo,
  ProjectSystemPromptPreview,
} from '@/types'

type PromptSnapshot = Record<string, string>
type PromptWorkspace = 'config' | 'preview'

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

const { t, locale } = useI18n()
const appStore = useAppStore()
const router = useRouter()
const route = useRoute()

const { visibleNavItems } = useAdminScope()

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
const projectRepos = ref<ProjectRepo[]>([])
const projectAgents = ref<ProjectAgentInfo[]>([])
const selectedPreviewProjectCode = ref('')
const selectedPreviewAgentKey = ref('')
const activeWorkspace = ref<PromptWorkspace>('config')
const activePromptLocale = computed<'zh' | 'en'>(() =>
  locale.value.toLowerCase().startsWith('en') ? 'en' : 'zh'
)
const previewLocale = ref<'zh' | 'en'>(activePromptLocale.value)
const previewMode = ref<'rendered' | 'raw'>('rendered')
const previewData = ref<ProjectSystemPromptPreview | null>(null)
const previewError = ref('')
const previewPanelRef = ref<HTMLElement | null>(null)
let previewFetchSeq = 0

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingConfig = ref(false)
const loadingPreviewResources = ref(false)
const loadingPreview = ref(false)
const saving = ref(false)
const conflict = ref(false)
const conflictMessage = ref('')

const authForm = reactive({
  username: '',
  password: '',
})

const formatTimestamp = (value?: string) => {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString(activePromptLocale.value === 'en' ? 'en-US' : 'zh-CN', {
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
  if (minutes < 1) return t('admin.prompts.timeJustNow')
  if (minutes < 60) return t('admin.prompts.timeMinutesAgo', { minutes })
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t('admin.prompts.timeHoursAgo', { hours })
  const days = Math.floor(hours / 24)
  return t('admin.prompts.timeDaysAgo', { days })
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

const selectedPromptMeta = computed(() => {
  const prompt = selectedPrompt.value
  if (!prompt) return null
  return {
    function: localizePromptFunction(
      prompt.function_key,
      prompt.function_name,
      prompt.function_description,
    ),
    agent: localizePromptAgent(
      prompt.function_key,
      prompt.agent_key,
      prompt.agent_name,
      prompt.agent_description,
    ),
  }
})

const selectedPromptContent = computed({
  get: () => selectedPrompt.value?.content || '',
  set: (value: string) => {
    const prompt = selectedPrompt.value
    if (prompt) prompt.content = value
  },
})

const localeVariants = computed(() => {
  const current = selectedPrompt.value
  if (!current) return []
  return configState.prompts.filter(
    (p) =>
      p.function_key === current.function_key &&
      p.agent_key === current.agent_key &&
      p.prompt_key === current.prompt_key &&
      p.locale != null
  )
})

const switchLocale = (promptLocale: string) => {
  const variant = localeVariants.value.find((p) => p.locale === promptLocale)
  if (variant) selectedPromptId.value = variant.id
}

const promptGroups = computed<PromptFunctionGroup[]>(() => {
  const functionMap = new Map<string, PromptFunctionGroup>()

  configState.prompts.forEach((prompt) => {
    if (!functionMap.has(prompt.function_key)) {
      const functionMeta = localizePromptFunction(
        prompt.function_key,
        prompt.function_name,
        prompt.function_description,
      )
      functionMap.set(prompt.function_key, {
        key: prompt.function_key,
        name: functionMeta.name,
        description: functionMeta.description,
        agents: [],
      })
    }

    const functionGroup = functionMap.get(prompt.function_key) as PromptFunctionGroup
    let agentGroup = functionGroup.agents.find((agent) => agent.key === prompt.agent_key)
    if (!agentGroup) {
      const agentMeta = localizePromptAgent(
        prompt.function_key,
        prompt.agent_key,
        prompt.agent_name,
        prompt.agent_description,
      )
      agentGroup = {
        key: prompt.agent_key,
        name: agentMeta.name,
        description: agentMeta.description,
        prompts: [],
      }
      functionGroup.agents.push(agentGroup)
    }
    agentGroup.prompts.push(prompt)
  })

  return Array.from(functionMap.values())
})

const agentMetaByKey = computed(() => {
  const map = new Map<string, ProjectAgentInfo>()
  projectAgents.value.forEach((agent) => map.set(agent.key, agent))
  return map
})

const selectedPreviewProject = computed(() =>
  projectRepos.value.find((repo) => repo.project_code === selectedPreviewProjectCode.value) || null
)

const previewProjectAgents = computed(() => {
  const project = selectedPreviewProject.value
  if (!project) return []
  const enabled = new Set(project.enabled_agent_keys || [])
  return projectAgents.value.filter((agent) => {
    if (agent.requires_repo && !project.has_repo) return false
    return !enabled.size || enabled.has(agent.key)
  })
})

const selectedPreviewAgent = computed(() =>
  agentMetaByKey.value.get(selectedPreviewAgentKey.value) || null
)

const renderedPreviewHtml = computed(() =>
  renderMarkdown(previewData.value?.content || '', {
    cleanXml: false,
    wrapperClass: 'prompt-preview-markdown',
  })
)

const previewStats = computed(() => {
  const data = previewData.value
  if (!data) return []
  return [
    { key: 'base', label: t('admin.prompts.previewBaseChars'), value: data.base_chars },
    { key: 'project', label: t('admin.prompts.previewAddendumChars'), value: data.addendum_chars },
    { key: 'total', label: t('admin.prompts.previewTotalChars'), value: data.total_chars },
  ]
})

const statusLabel = computed(() => {
  if (!isAuthenticated.value) return t('admin.prompts.statusNotLoggedIn')
  if (loadingConfig.value) return t('admin.prompts.statusSyncing')
  if (saving.value) return t('admin.prompts.statusSaving')
  if (conflict.value) return t('admin.prompts.statusConflict')
  return hasUnsavedChanges.value ? t('admin.prompts.statusUnsaved') : t('admin.prompts.statusSynced')
})

const statusTone = computed(() => {
  if (!isAuthenticated.value) return 'bg-slate-700 text-slate-100'
  if (conflict.value) return 'bg-amber-100 text-amber-800'
  if (hasUnsavedChanges.value) return 'bg-cyan-100 text-cyan-900'
  return 'bg-emerald-100 text-emerald-900'
})

const navVisible = computed(() => appStore.adminSidebarVisible)

const readableUpdatedAt = computed(() => {
  if (!configState.updated_at) return t('admin.prompts.statusNotLoaded')
  return `${formatTimestamp(configState.updated_at)} (${formatRelative(configState.updated_at)})`
})

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

const ensureSelectedPrompt = () => {
  if (configState.prompts.some((prompt) => prompt.id === selectedPromptId.value)) return
  selectedPromptId.value =
    configState.prompts.find((prompt) => prompt.locale === activePromptLocale.value)?.id ||
    configState.prompts[0]?.id ||
    ''
}

const projectAgentKeyForPrompt = (prompt: PromptEntry): string | null => {
  const map: Record<string, string> = {
    claude_agent_project_expert: 'project_expert',
    claude_agent_log_analysis: 'log_analysis',
    claude_agent_package_search: 'package_search',
  }
  return map[prompt.function_key] || null
}

const selectPrompt = (prompt: PromptEntry) => {
  selectedPromptId.value = prompt.id
  const projectAgentKey = projectAgentKeyForPrompt(prompt)
  if (projectAgentKey && previewProjectAgents.value.some((agent) => agent.key === projectAgentKey)) {
    selectedPreviewAgentKey.value = projectAgentKey
  }
}

const selectAgentPrompt = (agent: PromptAgentGroup) => {
  const prompt = agent.prompts.find((p) => p.locale === activePromptLocale.value) ?? agent.prompts[0]
  if (prompt) selectPrompt(prompt)
}

const agentLabel = (agentKey: string) => {
  const meta = agentMetaByKey.value.get(agentKey)
  const fallback = meta?.display_name || meta?.name || agentKey
  return localizeProjectAgent(agentKey, fallback, meta?.description).name
}

const agentDescription = (agent: ProjectAgentInfo) =>
  localizeProjectAgent(
    agent.key,
    agent.display_name || agent.name || agent.key,
    agent.description,
  ).description

const promptKeysLabel = (agent: PromptAgentGroup) =>
  [...new Set(agent.prompts.map((prompt) => prompt.prompt_key))]
    .join(t('admin.prompts.promptKeySeparator'))

const ensurePreviewSelection = () => {
  if (!projectRepos.value.some((repo) => repo.project_code === selectedPreviewProjectCode.value)) {
    selectedPreviewProjectCode.value = projectRepos.value[0]?.project_code || ''
  }
  const agents = previewProjectAgents.value
  if (!agents.some((agent) => agent.key === selectedPreviewAgentKey.value)) {
    selectedPreviewAgentKey.value = agents[0]?.key || ''
  }
}

const fetchConfig = async (withToast = false) => {
  loadingConfig.value = true
  conflict.value = false
  conflictMessage.value = ''
  try {
    const resp = await adminApi.fetchPromptsConfig()
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.prompts.cantReadConfigFallback'))
    }
    Object.assign(configState, resp.data)
    lastChecksum.value = resp.data.checksum
    lastSavedPrompts.value = snapshotPrompts(resp.data.prompts || [])
    ensureSelectedPrompt()
    if (withToast) {
      appStore.showNotification({
        title: t('admin.prompts.refreshedFromDisk'),
        message: t('admin.prompts.lastModifiedMsg', { time: readableUpdatedAt.value }),
        type: 'info',
      })
    }
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.prompts.readFail'),
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

const fetchPromptPreview = async () => {
  if (!isAuthenticated.value || !selectedPreviewProjectCode.value || !selectedPreviewAgentKey.value) {
    previewData.value = null
    return
  }
  const seq = ++previewFetchSeq
  loadingPreview.value = true
  previewError.value = ''
  try {
    const resp = await adminApi.getProjectSystemPromptPreview(
      selectedPreviewProjectCode.value,
      selectedPreviewAgentKey.value,
      previewLocale.value
    )
    if (seq !== previewFetchSeq) return
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || t('admin.prompts.previewLoadFail'))
    }
    previewData.value = resp.data
  } catch (err: any) {
    if (seq !== previewFetchSeq) return
    previewData.value = null
    previewError.value = parseErrorMessage(err)
    if (err?.response?.status === 401) {
      clearAuth()
    }
  } finally {
    if (seq === previewFetchSeq) loadingPreview.value = false
  }
}

const fetchPreviewResources = async () => {
  loadingPreviewResources.value = true
  try {
    const [reposResp, agentsResp] = await Promise.all([
      adminApi.listProjectRepos({ include_disabled: false, limit: 200 }),
      adminApi.listProjectAgents(),
    ])
    if (!reposResp?.success || !Array.isArray(reposResp.data)) {
      throw new Error(reposResp?.message || t('admin.prompts.previewLoadFail'))
    }
    if (!agentsResp?.success || !Array.isArray(agentsResp.data)) {
      throw new Error(agentsResp?.message || t('admin.prompts.previewLoadFail'))
    }
    projectRepos.value = reposResp.data
    projectAgents.value = agentsResp.data
    ensurePreviewSelection()
    await fetchPromptPreview()
  } catch (err: any) {
    previewError.value = parseErrorMessage(err)
    if (err?.response?.status === 401) {
      clearAuth()
    }
  } finally {
    loadingPreviewResources.value = false
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
    await fetchConfig()
    await fetchPreviewResources()
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
      throw new Error(resp?.message || t('admin.prompts.saveFailFallback'))
    }
    Object.assign(configState, resp.data)
    lastChecksum.value = resp.data.checksum
    lastSavedPrompts.value = snapshotPrompts(resp.data.prompts || [])
    ensureSelectedPrompt()
    await fetchPromptPreview()
    appStore.showNotification({
      title: t('admin.prompts.saveSuccess'),
      message: t('admin.prompts.saveSuccessMsg'),
      type: 'success',
    })
  } catch (err: any) {
    if (err?.response?.status === 409) {
      conflict.value = true
      conflictMessage.value = parseErrorMessage(err)
      appStore.showNotification({
        title: t('admin.prompts.newVersionDetected'),
        message: conflictMessage.value,
        type: 'warning',
      })
    } else {
      appStore.showNotification({
        title: t('admin.prompts.saveFailTitle'),
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
    const confirmed = window.confirm(t('admin.prompts.discardConfirm'))
    if (!confirmed) return
  }
  await fetchConfig(true)
  await fetchPreviewResources()
}

const handleLogout = async () => {
  try {
    await adminApi.logout()
  } catch {
    // ignore network errors on logout
  } finally {
    clearAuth()
    appStore.showNotification({
      title: t('admin.logoutSuccessTitle'),
      type: 'info',
    })
  }
}

const handleNavClick = (item: AdminNavItem) => {
  if (item.path && route.path !== item.path) {
    router.push(item.path)
  }
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
}

const activateWorkspace = (workspace: PromptWorkspace, focus = false) => {
  activeWorkspace.value = workspace
  if (focus) {
    nextTick(() => document.getElementById(`prompt-${workspace}-tab`)?.focus())
  }
}

const handleWorkspaceTabKeydown = (event: KeyboardEvent, current: PromptWorkspace) => {
  const workspaces: PromptWorkspace[] = ['config', 'preview']
  const currentIndex = workspaces.indexOf(current)
  let nextWorkspace: PromptWorkspace | undefined

  if (event.key === 'ArrowRight') {
    nextWorkspace = workspaces[(currentIndex + 1) % workspaces.length]
  } else if (event.key === 'ArrowLeft') {
    nextWorkspace = workspaces[(currentIndex - 1 + workspaces.length) % workspaces.length]
  } else if (event.key === 'Home') {
    nextWorkspace = workspaces[0]
  } else if (event.key === 'End') {
    nextWorkspace = workspaces[workspaces.length - 1]
  }

  if (!nextWorkspace) return
  event.preventDefault()
  activateWorkspace(nextWorkspace, true)
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await fetchConfig()
      await fetchPreviewResources()
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
    if (isAuthenticated.value && activeWorkspace.value === 'config') {
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

watch(selectedPreviewProjectCode, () => {
  const beforeAgent = selectedPreviewAgentKey.value
  ensurePreviewSelection()
  if (beforeAgent === selectedPreviewAgentKey.value) {
    fetchPromptPreview()
  }
})

watch([selectedPreviewAgentKey, previewLocale], () => {
  fetchPromptPreview()
})

watch(activePromptLocale, (nextLocale) => {
  previewLocale.value = nextLocale
  if (selectedPrompt.value) {
    switchLocale(nextLocale)
  } else {
    ensureSelectedPrompt()
  }
})

watch([renderedPreviewHtml, previewMode], async () => {
  if (previewMode.value !== 'rendered') return
  await nextTick()
  processMermaidBlocks(previewPanelRef.value)
}, { flush: 'post' })

watch(activeWorkspace, async (workspace) => {
  if (workspace !== 'preview' || previewMode.value !== 'rendered') return
  await nextTick()
  processMermaidBlocks(previewPanelRef.value)
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
            :title="navVisible ? t('admin.toggleSidebarHide') : t('admin.toggleSidebarShow')"
            :aria-label="t('admin.toggleSidebarAriaLabel')"
          >
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">{{ t('admin.title') }}</h1>
            <p class="admin-subtitle">{{ t('admin.prompts.subtitle') }}</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <ThemeToggle class="admin-theme-toggle" />
          <span class="px-3 py-1 text-xs font-semibold rounded-full" :class="statusTone">
            {{ statusLabel }}
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
                <span>{{ t('admin.prompts.loginHint1') }}</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-cyan-400"></span>
                <span>{{ t('admin.prompts.loginHint2') }}</span>
              </div>
              <div class="flex items-center gap-2">
                <span class="h-2 w-2 rounded-full bg-amber-400"></span>
                <span>{{ t('admin.prompts.loginHint3') }}</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else class="prompt-workspace">
        <div
          class="prompt-workspace-tabs"
          role="tablist"
          :aria-label="t('admin.prompts.workspaceTabsLabel')"
        >
          <button
            id="prompt-config-tab"
            type="button"
            class="prompt-workspace-tab"
            :class="{ 'is-active': activeWorkspace === 'config' }"
            role="tab"
            :aria-selected="activeWorkspace === 'config'"
            aria-controls="prompt-config-panel"
            :tabindex="activeWorkspace === 'config' ? 0 : -1"
            @click="activateWorkspace('config')"
            @keydown="handleWorkspaceTabKeydown($event, 'config')"
          >
            <span class="prompt-workspace-tab-icon"><Layers :size="19" /></span>
            <span class="prompt-workspace-tab-copy">
              <strong>{{ t('admin.prompts.configTab') }}</strong>
              <small>{{ t('admin.prompts.configTabDesc') }}</small>
            </span>
            <span class="prompt-workspace-tab-count">
              {{ t('admin.prompts.configTabCount', { count: configState.summary.editable_prompt_count || configState.prompts.length }) }}
            </span>
          </button>
          <button
            id="prompt-preview-tab"
            type="button"
            class="prompt-workspace-tab"
            :class="{ 'is-active': activeWorkspace === 'preview' }"
            role="tab"
            :aria-selected="activeWorkspace === 'preview'"
            aria-controls="prompt-preview-panel"
            :tabindex="activeWorkspace === 'preview' ? 0 : -1"
            @click="activateWorkspace('preview')"
            @keydown="handleWorkspaceTabKeydown($event, 'preview')"
          >
            <span class="prompt-workspace-tab-icon"><Eye :size="19" /></span>
            <span class="prompt-workspace-tab-copy">
              <strong>{{ t('admin.prompts.previewTab') }}</strong>
              <small>{{ t('admin.prompts.previewTabDesc') }}</small>
            </span>
            <span class="prompt-workspace-tab-count">
              {{ t('admin.prompts.previewTabCount', { count: projectRepos.length }) }}
            </span>
          </button>
        </div>

        <section
          v-show="activeWorkspace === 'config'"
          id="prompt-config-panel"
          class="prompt-workspace-panel"
          role="tabpanel"
          tabindex="0"
          aria-labelledby="prompt-config-tab"
        >
          <div class="prompt-region-heading">
            <div class="prompt-region-icon">
              <Layers :size="18" />
            </div>
            <div>
              <h2>{{ t('admin.prompts.baseRegionTitle') }}</h2>
              <p>{{ t('admin.prompts.baseRegionDesc') }}</p>
            </div>
            <div class="editor-toolbar-actions prompt-config-actions flex items-center gap-2">
              <button
                class="admin-command-btn"
                :disabled="loadingConfig"
                @click="handleReload"
              >
                <RefreshCw :size="15" />
                <span>{{ t('admin.prompts.reloadBtn') }}</span>
              </button>
              <button
                class="admin-command-btn primary"
                :disabled="saving || !hasUnsavedChanges"
                @click="() => handleSave()"
              >
                <Save :size="15" />
                <span>{{ saving ? t('admin.prompts.savingBtn') : t('admin.prompts.saveBtn') }}</span>
              </button>
              <button
                v-if="conflict"
                class="admin-command-btn warning"
                :disabled="saving"
                @click="handleSave(true)"
              >
                <Save :size="15" />
                <span>{{ t('admin.prompts.forceSaveBtn') }}</span>
              </button>
            </div>
          </div>

          <div class="prompt-workbench">
            <aside class="prompt-list-panel">
              <div class="prompt-list-title">
                <span>{{ t('admin.prompts.agentGroup') }}</span>
                <span>{{ configState.prompts.length }}</span>
              </div>
              <div v-if="!promptGroups.length" class="prompt-empty">
                {{ t('admin.prompts.noPrompts') }}
              </div>
              <div v-for="group in promptGroups" :key="group.key" class="prompt-function-group">
                <div class="prompt-function-name">
                  <span>{{ group.name }}</span>
                  <small>{{ t('admin.prompts.agentCount', { count: group.agents.length }) }}</small>
                </div>
                <p v-if="group.description" class="prompt-function-desc">{{ group.description }}</p>
                <button
                  v-for="agent in group.agents"
                  :key="agent.key"
                  class="prompt-agent-item"
                  :class="{ 'is-active': agent.prompts.some((prompt) => prompt.id === selectedPromptId) }"
                  @click="selectAgentPrompt(agent)"
                >
                  <span class="prompt-agent-name">{{ agent.name }}</span>
                  <span class="prompt-agent-desc">{{ agent.description }}</span>
                  <span class="prompt-agent-foot">
                    {{ promptKeysLabel(agent) }}
                  </span>
                </button>
              </div>
            </aside>

            <section class="prompt-editor-panel">
              <template v-if="selectedPrompt">
                <div class="prompt-editor-head">
                  <div>
                    <div class="prompt-breadcrumb">
                      {{ selectedPromptMeta?.function.name }} / {{ selectedPromptMeta?.agent.name }}
                    </div>
                    <h3>{{ selectedPrompt.prompt_key }}</h3>
                    <p v-if="selectedPromptMeta?.agent.description">{{ selectedPromptMeta.agent.description }}</p>
                  </div>
                  <div class="prompt-editor-head-right">
                    <div v-if="localeVariants.length > 1" class="locale-tabs">
                      <button
                        v-for="variant in localeVariants"
                        :key="variant.id"
                        class="locale-tab"
                        :class="{ 'is-active': variant.id === selectedPromptId }"
                        @click="switchLocale(variant.locale!)"
                      >
                        {{ variant.locale }}
                      </button>
                    </div>
                    <span
                      class="prompt-dirty-badge"
                      :class="currentPromptSnapshot[selectedPrompt.id] !== lastSavedPrompts[selectedPrompt.id] ? 'is-dirty' : 'is-clean'"
                    >
                      {{ currentPromptSnapshot[selectedPrompt.id] !== lastSavedPrompts[selectedPrompt.id] ? t('admin.prompts.unsavedLabel') : t('admin.prompts.syncedLabel') }}
                    </span>
                  </div>
                </div>
                <textarea
                  v-model="selectedPromptContent"
                  class="prompt-textarea"
                  spellcheck="false"
                  :disabled="loadingConfig || saving"
                ></textarea>
                <div class="prompt-editor-footer">
                  <div class="flex items-center gap-3 flex-wrap">
                    <span>{{ t('admin.prompts.promptLength', { count: selectedPromptContent.length }) }}</span>
                    <span v-if="conflict" class="text-amber-700 font-semibold">
                      {{ conflictMessage || t('admin.prompts.conflictNote') }}
                    </span>
                  </div>
                  <span>{{ t('admin.prompts.checksumLabel', { checksum: lastChecksum || configState.checksum }) }}</span>
                </div>
              </template>
              <div v-else class="prompt-empty editor-empty">
                {{ t('admin.prompts.selectPromptHint') }}
              </div>
            </section>
          </div>
        </section>

        <section
          v-show="activeWorkspace === 'preview'"
          id="prompt-preview-panel"
          class="prompt-workspace-panel"
          role="tabpanel"
          tabindex="0"
          aria-labelledby="prompt-preview-tab"
        >
          <div class="prompt-region-heading preview-heading">
            <div class="prompt-region-icon preview">
              <Eye :size="18" />
            </div>
            <div>
              <h2>{{ t('admin.prompts.previewRegionTitle') }}</h2>
              <p>{{ t('admin.prompts.previewRegionDesc') }}</p>
            </div>
            <div class="preview-heading-actions">
              <div class="locale-tabs preview-tabs">
                <button
                  class="locale-tab"
                  :class="{ 'is-active': previewLocale === 'zh' }"
                  @click="previewLocale = 'zh'"
                >
                  zh
                </button>
                <button
                  class="locale-tab"
                  :class="{ 'is-active': previewLocale === 'en' }"
                  @click="previewLocale = 'en'"
                >
                  en
                </button>
              </div>
              <div class="preview-mode-tabs">
                <button
                  class="preview-mode-tab"
                  :class="{ 'is-active': previewMode === 'rendered' }"
                  @click="previewMode = 'rendered'"
                >
                  <Eye :size="14" />
                  <span>{{ t('admin.prompts.previewRendered') }}</span>
                </button>
                <button
                  class="preview-mode-tab"
                  :class="{ 'is-active': previewMode === 'raw' }"
                  @click="previewMode = 'raw'"
                >
                  <FileText :size="14" />
                  <span>{{ t('admin.prompts.previewRaw') }}</span>
                </button>
              </div>
              <button
                class="admin-command-btn"
                :disabled="loadingPreview || loadingPreviewResources"
                @click="fetchPromptPreview"
              >
                <RefreshCw :size="15" />
                <span>{{ t('admin.prompts.previewRefresh') }}</span>
              </button>
            </div>
          </div>

          <div class="project-preview-workbench">
            <aside class="project-preview-selector">
              <div class="prompt-list-title">
                <span>{{ t('admin.prompts.previewProjects') }}</span>
                <span>{{ projectRepos.length }}</span>
              </div>
              <div v-if="!projectRepos.length" class="prompt-empty">
                {{ loadingPreviewResources ? t('admin.prompts.previewLoading') : t('admin.prompts.previewNoProjects') }}
              </div>
              <div v-else class="project-preview-list">
                <button
                  v-for="repo in projectRepos"
                  :key="repo.id"
                  class="project-preview-item"
                  :class="{ 'is-active': repo.project_code === selectedPreviewProjectCode }"
                  @click="selectedPreviewProjectCode = repo.project_code"
                >
                  <span class="project-preview-name">{{ repo.project_name }}</span>
                  <span class="project-preview-code">{{ repo.project_code }}</span>
                  <span class="project-preview-foot">
                    {{ repo.has_repo ? t('admin.prompts.previewRepoLinked') : t('admin.prompts.previewRepoLess') }}
                    · {{ t('admin.prompts.previewAgentCount', { count: repo.enabled_agent_keys?.length || 0 }) }}
                  </span>
                </button>
              </div>

              <div class="project-agent-picker">
                <div class="prompt-list-title compact">
                  <span>{{ t('admin.prompts.previewAgents') }}</span>
                  <span>{{ previewProjectAgents.length }}</span>
                </div>
                <div v-if="!previewProjectAgents.length" class="prompt-empty">
                  {{ t('admin.prompts.previewNoAgents') }}
                </div>
                <template v-else>
                  <button
                    v-for="agent in previewProjectAgents"
                    :key="agent.key"
                    class="project-agent-chip"
                    :class="{ 'is-active': agent.key === selectedPreviewAgentKey }"
                    @click="selectedPreviewAgentKey = agent.key"
                  >
                    {{ agentLabel(agent.key) }}
                  </button>
                </template>
              </div>
            </aside>

            <section class="project-preview-panel">
              <div class="project-preview-head">
                <div>
                  <div class="prompt-breadcrumb">
                    {{ selectedPreviewProject?.project_code || '--' }} / {{ agentLabel(selectedPreviewAgentKey) }}
                  </div>
                  <h3>{{ selectedPreviewProject?.project_name || t('admin.prompts.previewEmptyTitle') }}</h3>
                  <p v-if="selectedPreviewAgent">{{ agentDescription(selectedPreviewAgent) }}</p>
                </div>
                <div class="preview-stat-row">
                  <span v-for="item in previewStats" :key="item.key">
                    {{ item.label }} {{ item.value }}
                  </span>
                </div>
              </div>

              <div v-if="previewData?.layers?.length" class="preview-layer-strip">
                <span
                  v-for="layer in previewData.layers"
                  :key="layer.key"
                  :class="{ 'is-empty': !layer.exists }"
                >
                  {{ localizePromptPreviewLayer(layer.key, layer.label) }} · {{ layer.exists ? t('admin.prompts.previewLayerOn') : t('admin.prompts.previewLayerOff') }}
                </span>
              </div>

              <div v-if="loadingPreview || loadingPreviewResources" class="prompt-empty preview-state">
                {{ t('admin.prompts.previewLoading') }}
              </div>
              <div v-else-if="previewError" class="prompt-empty preview-state is-error">
                {{ previewError }}
              </div>
              <div v-else-if="!previewData" class="prompt-empty preview-state">
                {{ t('admin.prompts.previewEmpty') }}
              </div>
              <div v-else-if="previewMode === 'rendered'" ref="previewPanelRef" class="project-preview-rendered" v-html="renderedPreviewHtml"></div>
              <pre v-else class="project-preview-raw">{{ previewData.content }}</pre>
            </section>
          </div>
        </section>
      </section>
    </main>
  </div>
</template>

<style scoped>
.admin-console {
  --admin-topbar-height: 72px;
  --admin-sidebar-width: 280px;
  min-height: 100vh;
  background: var(--admin-page-bg);
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

/* Fixed app-shell so the workspace tabs and left selectors stay pinned while
   only the editor / preview content scrolls. Higher specificity than the
   global `.admin-console.admin-console .admin-main` rule so it wins reliably. */
.admin-console.admin-prompts-page .admin-main {
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.prompt-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.admin-login-wrap {
  max-width: 960px;
  margin: 1.25rem auto 0;
  max-height: 100%;
  overflow-y: auto;
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

.prompt-workspace-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.4rem;
  border: 1px solid var(--admin-hairline);
  border-radius: 0.85rem;
  background: var(--admin-surface);
  padding: 0.4rem;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
}

.prompt-workspace-tab {
  position: relative;
  min-width: 0;
  min-height: 4.5rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 0.65rem;
  color: var(--admin-body);
  background: transparent;
  padding: 0.72rem 0.85rem;
  text-align: left;
  transition: color 0.18s ease, background 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}

.prompt-workspace-tab:hover:not(.is-active) {
  border-color: var(--admin-hairline);
  background: var(--admin-canvas-soft);
}

.prompt-workspace-tab.is-active {
  color: var(--admin-on-dark-soft);
  border-color: var(--admin-dark);
  background: var(--admin-dark);
}

.prompt-workspace-tab:focus-visible {
  outline: 3px solid var(--admin-focus-ring);
  outline-offset: 2px;
}

.prompt-workspace-tab-icon {
  width: 2.35rem;
  height: 2.35rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border: 1px solid var(--admin-hairline);
  border-radius: 0.6rem;
  color: var(--admin-link);
  background: var(--admin-surface);
}

.prompt-workspace-tab.is-active .prompt-workspace-tab-icon {
  color: #67e8f9;
  border-color: rgba(103, 232, 249, 0.24);
  background: rgba(103, 232, 249, 0.09);
}

.prompt-workspace-tab-copy {
  min-width: 0;
  display: grid;
  gap: 0.12rem;
}

.prompt-workspace-tab-copy strong {
  color: var(--admin-ink);
  font-size: 0.9rem;
  font-weight: 800;
}

.prompt-workspace-tab-copy small {
  overflow: hidden;
  color: var(--admin-muted);
  font-size: 0.74rem;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt-workspace-tab.is-active .prompt-workspace-tab-copy strong {
  color: var(--admin-on-dark);
}

.prompt-workspace-tab.is-active .prompt-workspace-tab-copy small {
  color: var(--admin-on-dark-soft);
}

.prompt-workspace-tab-count {
  flex: 0 0 auto;
  margin-left: auto;
  border: 1px solid var(--admin-hairline);
  border-radius: 999px;
  color: var(--admin-body);
  background: var(--admin-surface);
  font-size: 0.7rem;
  font-weight: 750;
  padding: 0.25rem 0.55rem;
  white-space: nowrap;
}

.prompt-workspace-tab.is-active .prompt-workspace-tab-count {
  color: var(--admin-on-dark-soft);
  border-color: var(--admin-dark-hairline);
  background: var(--admin-dark-elevated);
}

.prompt-workspace-panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  animation: prompt-workspace-enter 0.2s ease-out;
}

.prompt-workspace-panel:focus {
  outline: none;
}

.prompt-workspace-panel:focus-visible {
  outline: 3px solid var(--admin-focus-ring);
  outline-offset: 4px;
  border-radius: 0.85rem;
}

@keyframes prompt-workspace-enter {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.prompt-region-heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  flex: 0 0 auto;
  margin: 1.1rem 0 0.75rem;
  color: var(--admin-ink);
}

.prompt-config-actions {
  margin-left: auto;
}

.prompt-region-heading h2 {
  font-size: 0.98rem;
  font-weight: 850;
  letter-spacing: 0;
}

.prompt-region-heading p {
  margin-top: 0.12rem;
  color: var(--admin-body);
  font-size: 0.78rem;
}

.prompt-region-icon {
  width: 2.25rem;
  height: 2.25rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--admin-accent-soft-border);
  border-radius: 0.65rem;
  color: var(--admin-accent-soft-ink);
  background: var(--admin-accent-soft-bg);
}

.prompt-region-icon.preview {
  color: var(--admin-accent-soft-ink);
  border-color: var(--admin-accent-soft-border);
  background: var(--admin-accent-soft-bg);
}

.preview-heading {
  align-items: flex-start;
}

.preview-heading-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.preview-tabs {
  height: 2.25rem;
}

.preview-mode-tabs {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  border: 1px solid var(--admin-hairline-strong);
  border-radius: 0.55rem;
  padding: 0.2rem;
  background: var(--admin-surface);
}

.preview-mode-tab {
  min-height: 1.8rem;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border-radius: 0.4rem;
  color: var(--admin-body);
  font-size: 0.75rem;
  font-weight: 800;
  padding: 0.25rem 0.55rem;
  transition: background 0.15s ease, color 0.15s ease;
}

.preview-mode-tab.is-active {
  color: var(--admin-on-dark);
  background: var(--admin-primary);
}

.prompt-workbench {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  gap: 1rem;
  flex: 1;
  min-height: 0;
}

.prompt-list-panel,
.prompt-editor-panel {
  border: 1px solid var(--admin-hairline);
  border-radius: 1rem;
  background: var(--admin-surface);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

.prompt-list-panel {
  padding: 0.85rem;
  align-self: stretch;
  min-height: 0;
  overflow-y: auto;
}

.prompt-list-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--admin-ink);
  font-size: 0.85rem;
  font-weight: 800;
  margin-bottom: 0.75rem;
}

.prompt-list-title span:last-child {
  min-width: 1.5rem;
  text-align: center;
  color: var(--admin-accent-soft-ink);
  background: var(--admin-accent-soft-bg);
  border: 1px solid var(--admin-accent-soft-border);
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
  color: var(--admin-ink);
  font-size: 0.82rem;
  font-weight: 800;
  margin-bottom: 0.25rem;
}

.prompt-function-name small {
  color: var(--admin-body);
  font-weight: 600;
}

.prompt-function-desc {
  color: var(--admin-body);
  font-size: 0.75rem;
  line-height: 1.45;
  margin-bottom: 0.55rem;
}

.prompt-agent-item {
  width: 100%;
  text-align: left;
  display: grid;
  gap: 0.25rem;
  border: 1px solid var(--admin-hairline);
  border-radius: 0.75rem;
  background: var(--admin-canvas-soft);
  padding: 0.75rem;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.prompt-agent-item + .prompt-agent-item {
  margin-top: 0.5rem;
}

.prompt-agent-item:hover,
.prompt-agent-item.is-active {
  border-color: var(--admin-accent-soft-border);
  background: var(--admin-accent-soft-bg);
}

.prompt-agent-name {
  color: var(--admin-ink);
  font-size: 0.85rem;
  font-weight: 800;
}

.prompt-agent-desc {
  min-height: 2.45rem;
  color: var(--admin-body);
  font-size: 0.75rem;
  line-height: 1.35;
}

.prompt-agent-foot {
  color: var(--admin-link);
  font-size: 0.72rem;
  font-weight: 700;
}

.prompt-editor-panel {
  min-height: 0;
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

.prompt-editor-head-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.locale-tabs {
  display: flex;
  gap: 0.25rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  padding: 0.2rem;
  background: #ffffff;
}

.locale-tab {
  padding: 0.2rem 0.6rem;
  font-size: 0.72rem;
  font-weight: 700;
  border-radius: 0.35rem;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  transition: background 0.15s, color 0.15s;
}

.locale-tab.is-active {
  background: #0891b2;
  color: #ffffff;
}

.locale-tab:not(.is-active):hover {
  background: #f1f5f9;
  color: #0f172a;
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
  min-height: 0;
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

.project-preview-workbench {
  display: grid;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
  gap: 1rem;
  flex: 1;
  min-height: 0;
}

.project-preview-selector,
.project-preview-panel {
  border: 1px solid var(--admin-hairline);
  border-radius: 0.85rem;
  background: var(--admin-surface);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
}

.project-preview-selector {
  align-self: stretch;
  min-height: 0;
  overflow-y: auto;
  padding: 0.85rem;
}

.project-preview-list {
  display: grid;
  gap: 0.5rem;
  max-height: 22rem;
  overflow-y: auto;
  padding-right: 0.15rem;
}

.project-preview-item {
  width: 100%;
  text-align: left;
  display: grid;
  gap: 0.22rem;
  border: 1px solid var(--admin-hairline);
  border-radius: 0.7rem;
  background: var(--admin-canvas-soft);
  padding: 0.72rem;
  transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.project-preview-item:hover,
.project-preview-item.is-active {
  border-color: var(--admin-accent-soft-border);
  background: var(--admin-accent-soft-bg);
  box-shadow: inset 3px 0 0 var(--admin-accent-soft-ink);
}

.project-preview-name {
  color: var(--admin-ink);
  font-size: 0.86rem;
  font-weight: 850;
}

.project-preview-code {
  color: var(--admin-body);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.72rem;
  word-break: break-all;
}

.project-preview-foot {
  color: var(--admin-link);
  font-size: 0.72rem;
  font-weight: 750;
}

.project-agent-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 1rem;
}

.prompt-list-title.compact {
  width: 100%;
  margin-bottom: 0.15rem;
}

.project-agent-chip {
  min-height: 2rem;
  border: 1px solid var(--admin-hairline-strong);
  border-radius: 999px;
  color: var(--admin-body);
  background: var(--admin-surface);
  font-size: 0.78rem;
  font-weight: 800;
  padding: 0.35rem 0.7rem;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.project-agent-chip:hover,
.project-agent-chip.is-active {
  color: var(--admin-accent-soft-ink);
  border-color: var(--admin-accent-soft-border);
  background: var(--admin-accent-soft-bg);
}

.project-preview-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.project-preview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  border-bottom: 1px solid var(--admin-hairline);
  background: linear-gradient(180deg, var(--admin-canvas-soft) 0%, var(--admin-surface) 100%);
}

.project-preview-head h3 {
  color: var(--admin-ink);
  font-size: 1rem;
  font-weight: 850;
}

.project-preview-head p {
  color: var(--admin-body);
  font-size: 0.78rem;
  margin-top: 0.25rem;
}

.preview-stat-row {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.4rem;
  flex-shrink: 0;
}

.preview-stat-row span,
.preview-layer-strip span {
  border: 1px solid var(--admin-hairline-strong);
  border-radius: 999px;
  color: var(--admin-body);
  background: var(--admin-surface);
  font-size: 0.72rem;
  font-weight: 800;
  padding: 0.25rem 0.55rem;
}

.preview-layer-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  padding: 0.65rem 1rem;
  border-bottom: 1px solid var(--admin-hairline);
  background: var(--admin-canvas-soft);
}

.preview-layer-strip span:not(.is-empty) {
  color: var(--admin-accent-soft-ink);
  border-color: var(--admin-accent-soft-border);
  background: var(--admin-accent-soft-bg);
}

.preview-layer-strip span.is-empty {
  color: var(--admin-muted);
  background: var(--admin-canvas-soft);
}

.preview-state {
  margin: auto;
  max-width: 28rem;
}

.preview-state.is-error {
  color: #991b1b;
  border-color: #fecaca;
  background: #fef2f2;
}

.project-preview-rendered {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 1rem;
  color: var(--admin-body);
  background: var(--admin-surface);
}

.project-preview-raw {
  flex: 1;
  min-height: 0;
  overflow: auto;
  margin: 0;
  color: var(--admin-ink);
  background: var(--admin-surface);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.78rem;
  line-height: 1.65;
  padding: 1rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.project-preview-rendered :deep(.prompt-preview-markdown) {
  max-width: 78ch;
  font-size: 0.86rem;
  line-height: 1.72;
}

.project-preview-rendered :deep(.prompt-preview-markdown h1),
.project-preview-rendered :deep(.prompt-preview-markdown h2),
.project-preview-rendered :deep(.prompt-preview-markdown h3),
.project-preview-rendered :deep(.prompt-preview-markdown h4),
.project-preview-rendered :deep(.prompt-preview-markdown h5),
.project-preview-rendered :deep(.prompt-preview-markdown h6) {
  color: var(--admin-ink);
  font-weight: 850;
  margin: 1rem 0 0.45rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown h1) {
  font-size: 1.28rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown h2) {
  font-size: 1.08rem;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid var(--admin-hairline);
}

.project-preview-rendered :deep(.prompt-preview-markdown h3) {
  font-size: 0.95rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown h4),
.project-preview-rendered :deep(.prompt-preview-markdown h5),
.project-preview-rendered :deep(.prompt-preview-markdown h6) {
  font-size: 0.88rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown p),
.project-preview-rendered :deep(.prompt-preview-markdown ul),
.project-preview-rendered :deep(.prompt-preview-markdown ol) {
  margin: 0.45rem 0;
}

.project-preview-rendered :deep(.prompt-preview-markdown ul),
.project-preview-rendered :deep(.prompt-preview-markdown ol) {
  padding-left: 1.25rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown ul) { list-style-type: disc; }
.project-preview-rendered :deep(.prompt-preview-markdown ol) { list-style-type: decimal; }
.project-preview-rendered :deep(.prompt-preview-markdown ul ul) { list-style-type: circle; }
.project-preview-rendered :deep(.prompt-preview-markdown ul ul ul) { list-style-type: square; }

.project-preview-rendered :deep(.prompt-preview-markdown li + li) {
  margin-top: 0.2rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown code) {
  border: 1px solid var(--admin-hairline);
  border-radius: 0.35rem;
  color: var(--admin-link);
  background: var(--admin-canvas-soft);
  font-size: 0.82em;
  padding: 0.05rem 0.25rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown pre) {
  overflow: auto;
  border: 1px solid var(--admin-dark-hairline);
  border-radius: 0.6rem;
  background: #0f172a;
  padding: 0.9rem;
}

.project-preview-rendered :deep(.prompt-preview-markdown pre code) {
  border: 0;
  color: inherit;
  background: transparent;
  padding: 0;
}

.project-preview-rendered :deep(.prompt-preview-markdown blockquote) {
  margin: 0.75rem 0;
  border-left: 3px solid var(--admin-accent-soft-ink);
  color: var(--admin-body);
  background: var(--admin-canvas-soft);
  padding: 0.45rem 0.75rem;
}

.project-preview-rendered :deep(.table-wrapper) {
  overflow-x: auto;
  margin: 0.75rem 0;
}

.project-preview-rendered :deep(.markdown-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.project-preview-rendered :deep(.markdown-table th),
.project-preview-rendered :deep(.markdown-table td) {
  border: 1px solid var(--admin-hairline-strong);
  padding: 0.4rem 0.55rem;
  text-align: left;
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

  .project-preview-workbench {
    grid-template-columns: 1fr;
  }

  .preview-heading-actions {
    width: 100%;
    margin-left: 0;
    justify-content: flex-start;
  }

  /* Columns stack here, so drop the fixed app-shell and let the page scroll. */
  .admin-console.admin-prompts-page .admin-main {
    height: auto;
    overflow: visible;
    display: block;
  }

  .prompt-workspace,
  .prompt-workspace-panel {
    display: block;
    min-height: 0;
  }

  .prompt-workbench,
  .project-preview-workbench {
    min-height: 0;
  }

  .prompt-list-panel,
  .project-preview-selector {
    align-self: start;
    overflow: visible;
  }

  .prompt-editor-panel,
  .project-preview-panel {
    min-height: 560px;
  }

  .prompt-textarea {
    min-height: 420px;
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

  .prompt-workspace-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .prompt-workspace-tab {
    min-height: 4rem;
    gap: 0.55rem;
    padding: 0.6rem;
  }

  .prompt-workspace-tab-copy small {
    display: none;
  }

  .prompt-workspace-tab-count {
    display: none;
  }

  .prompt-editor-panel {
    min-height: 560px;
  }

  .prompt-editor-head,
  .prompt-editor-footer,
  .project-preview-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .prompt-region-heading {
    align-items: flex-start;
  }

  .preview-mode-tabs,
  .preview-tabs,
  .preview-heading-actions .admin-command-btn {
    width: 100%;
  }

  .preview-mode-tab,
  .preview-heading-actions .admin-command-btn {
    flex: 1;
  }

  .project-preview-panel {
    min-height: 560px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .prompt-workspace-tab,
  .prompt-workspace-panel {
    animation: none;
    transition: none;
  }
}
</style>
