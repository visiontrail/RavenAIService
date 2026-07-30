<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  CircleHelp,
  Bot,
  FolderTree,
  LogOut,
  Menu,
  Pencil,
  PanelLeftClose,
  PlugZap,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
  UserMinus,
  UserPlus,
  Users,
  X,
} from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAppStore } from '@/stores/app'
import { resolveAdminNavKey, type AdminNavItem } from '@/utils/adminNav'
import { localizeProjectAgent } from '@/utils/adminPromptMetadata'
import { useAdminScope } from '@/composables/useAdminScope'
import type { ProjectAgentInfo, ProjectMember, ProjectRepo, ProjectRepoPayload, TestConnectionResult, UserProfile } from '@/types'

const { t } = useI18n()
const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const { visibleNavItems, isGlobalAdmin } = useAdminScope()

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingRepos = ref(false)
const loadingProjectAgents = ref(false)
const savingRepo = ref(false)
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const deletingId = ref<number | null>(null)
const testingId = ref<number | null>(null)
const includeDisabled = ref(true)
const repos = ref<ProjectRepo[]>([])
const projectAgents = ref<ProjectAgentInfo[]>([])
const testResults = reactive<Record<number, TestConnectionResult | undefined>>({})
const memberDialogVisible = ref(false)
const selectedRepoForMembers = ref<ProjectRepo | null>(null)
const loadingMembers = ref(false)
const loadingUsers = ref(false)
const addingMemberId = ref<string | null>(null)
const removingMemberId = ref<string | null>(null)
const memberSearch = ref('')
const projectMembers = ref<ProjectMember[]>([])
const userCandidates = ref<UserProfile[]>([])
type RepoHelpKey = 'projectCode' | 'token' | 'connectivity'
const activeHelp = ref<RepoHelpKey | null>(null)

const toggleHelp = (key: RepoHelpKey) => {
  activeHelp.value = activeHelp.value === key ? null : key
}

const authForm = reactive({
  username: '',
  password: '',
})

const repoForm = reactive({
  project_code: '',
  project_name: '',
  // 是否关联代码仓库。为 false 时无需填写 Git URL / Token，
  // 该项目仅项目专家可见。
  associate_repo: true,
  repo_url: '',
  default_branch: 'main',
  git_token: '',
  project_card: '',
  enabled: true,
  enabled_agent_keys: [] as string[],
})

const editingRepoId = ref<number | null>(null)

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))
const enabledCount = computed(() => repos.value.filter((repo) => repo.enabled).length)
const disabledCount = computed(() => repos.value.length - enabledCount.value)
const memberUserIds = computed(() => new Set(projectMembers.value.map((member) => member.id)))
const normalizedMemberSearch = computed(() => memberSearch.value.trim().toLowerCase())
const filteredUserCandidates = computed(() => {
  const query = normalizedMemberSearch.value
  if (!query) return []
  return userCandidates.value
    .filter((user) => {
      if (memberUserIds.value.has(user.id)) return false
      const fields = [user.username, user.email || '', user.display_name || '']
      return fields.some((field) => field.toLowerCase().includes(query))
    })
    .slice(0, 12)
})
const projectAgentByKey = computed(() => {
  const map = new Map<string, ProjectAgentInfo>()
  projectAgents.value.forEach((agent) => map.set(agent.key, agent))
  return map
})

const compatibleProjectAgents = computed(() =>
  projectAgents.value.filter((agent) => repoForm.associate_repo || !agent.requires_repo)
)

const projectAgentLabel = (agent: ProjectAgentInfo): string =>
  localizeProjectAgent(
    agent.key,
    agent.display_name || agent.name || agent.key,
    agent.description,
  ).name

const projectAgentDescription = (agent: ProjectAgentInfo): string | null | undefined =>
  localizeProjectAgent(
    agent.key,
    agent.display_name || agent.name || agent.key,
    agent.description,
  ).description

const enabledAgentLabels = (repo: ProjectRepo): string[] =>
  (repo.enabled_agent_keys || [])
    .map((key) => {
      const agent = projectAgentByKey.value.get(key)
      return agent ? projectAgentLabel(agent) : key
    })
    .filter(Boolean)

const defaultAgentKeysForAssociateState = (): string[] =>
  projectAgents.value
    .filter((agent) => repoForm.associate_repo || !agent.requires_repo)
    .map((agent) => agent.key)

const normalizeRepoFormAgentKeys = () => {
  const allowed = new Set(compatibleProjectAgents.value.map((agent) => agent.key))
  repoForm.enabled_agent_keys = repoForm.enabled_agent_keys.filter((key) => allowed.has(key))
  if (!repoForm.enabled_agent_keys.length) {
    repoForm.enabled_agent_keys = defaultAgentKeysForAssociateState()
  }
}

const toggleProjectAgent = (key: string) => {
  const agent = projectAgentByKey.value.get(key)
  if (!agent) return
  if (agent.requires_repo && !repoForm.associate_repo) return
  if (repoForm.enabled_agent_keys.includes(key)) {
    repoForm.enabled_agent_keys = repoForm.enabled_agent_keys.filter((item) => item !== key)
  } else {
    repoForm.enabled_agent_keys = [...repoForm.enabled_agent_keys, key]
  }
}

const parseErrorMessage = (err: any): string => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return t('admin.parseError')
}

const formatTimestamp = (value?: string | null): string => {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return value
  }
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  repos.value = []
  projectAgents.value = []
  memberDialogVisible.value = false
  selectedRepoForMembers.value = null
  projectMembers.value = []
  userCandidates.value = []
  authForm.password = ''
}

const handleLogin = async () => {
  if (!authForm.username.trim() || !authForm.password) {
    appStore.showNotification({ title: t('admin.loginWarning'), type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data?.token) throw new Error(resp?.message || t('admin.loginFailFallback'))
    adminToken.set(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: t('admin.loginSuccessTitle'), message: t('admin.loginSuccessMsg', { username: resp.data.username }), type: 'success' })
    await Promise.all([fetchProjectAgents(), fetchRepos()])
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

const handleNavClick = (item: AdminNavItem) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => appStore.toggleAdminSidebar()

const fetchRepos = async () => {
  if (!isAuthenticated.value) return
  loadingRepos.value = true
  try {
    const resp = await adminApi.listProjectRepos({
      include_disabled: includeDisabled.value,
      limit: 200,
    })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.projectRepos.loadFailFallback'))
    repos.value = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.loadFail'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingRepos.value = false
  }
}

const fetchProjectAgents = async () => {
  if (!isAuthenticated.value || loadingProjectAgents.value || projectAgents.value.length) return
  loadingProjectAgents.value = true
  try {
    const resp = await adminApi.listProjectAgents()
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.projectRepos.loadAgentsFailFallback'))
    projectAgents.value = resp.data
  } catch (err: any) {
    projectAgents.value = []
    appStore.showNotification({ title: t('admin.loadFail'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingProjectAgents.value = false
  }
}

const updateRepoMemberCount = (repoId: number, memberCount: number) => {
  repos.value = repos.value.map((repo) =>
    repo.id === repoId ? { ...repo, member_count: memberCount } : repo
  )
  if (selectedRepoForMembers.value?.id === repoId) {
    selectedRepoForMembers.value = {
      ...selectedRepoForMembers.value,
      member_count: memberCount,
    }
  }
}

const fetchProjectMembers = async (repoId: number) => {
  loadingMembers.value = true
  try {
    const resp = await adminApi.listProjectRepoMembers(repoId)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.projectRepos.loadMembersFailFallback'))
    projectMembers.value = resp.data
    updateRepoMemberCount(repoId, resp.data.length)
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.projectRepos.memberLoadFail'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingMembers.value = false
  }
}

const fetchUserCandidates = async () => {
  loadingUsers.value = true
  try {
    const resp = await adminApi.listUsers()
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.projectRepos.loadUsersFailFallback'))
    userCandidates.value = resp.data
  } catch (err: any) {
    userCandidates.value = []
    appStore.showNotification({ title: t('admin.projectRepos.userLoadFail'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingUsers.value = false
  }
}

const openMemberDialog = async (repo: ProjectRepo) => {
  selectedRepoForMembers.value = repo
  projectMembers.value = []
  memberSearch.value = ''
  memberDialogVisible.value = true
  await Promise.all([fetchProjectMembers(repo.id), fetchUserCandidates()])
}

const closeMemberDialog = () => {
  if (addingMemberId.value || removingMemberId.value) return
  memberDialogVisible.value = false
  selectedRepoForMembers.value = null
  projectMembers.value = []
  memberSearch.value = ''
}

const addProjectMember = async (user: UserProfile) => {
  const repo = selectedRepoForMembers.value
  if (!repo) return
  addingMemberId.value = user.id
  try {
    const resp = await adminApi.addProjectRepoMember(repo.id, user.id)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.projectRepos.addMemberFail'))
    projectMembers.value = resp.data
    updateRepoMemberCount(repo.id, resp.data.length)
    memberSearch.value = ''
    appStore.showNotification({ title: t('admin.projectRepos.addMemberSuccess'), message: user.username, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.projectRepos.addMemberFail'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    addingMemberId.value = null
  }
}

const removeProjectMember = async (member: ProjectMember) => {
  const repo = selectedRepoForMembers.value
  if (!repo) return
  if (!window.confirm(t('admin.projectRepos.removeMemberConfirm', { project: repo.project_code, username: member.username }))) return
  removingMemberId.value = member.id
  try {
    await adminApi.removeProjectRepoMember(repo.id, member.id)
    projectMembers.value = projectMembers.value.filter((item) => item.id !== member.id)
    updateRepoMemberCount(repo.id, projectMembers.value.length)
    appStore.showNotification({ title: t('admin.projectRepos.removeMemberSuccess'), message: member.username, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.projectRepos.removeMemberFail'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    removingMemberId.value = null
  }
}

const resetRepoForm = () => {
  editingRepoId.value = null
  repoForm.project_code = ''
  repoForm.project_name = ''
  repoForm.associate_repo = true
  repoForm.repo_url = ''
  repoForm.default_branch = 'main'
  repoForm.git_token = ''
  repoForm.project_card = ''
  repoForm.enabled = true
  repoForm.enabled_agent_keys = defaultAgentKeysForAssociateState()
}

const openCreateDialog = async () => {
  await fetchProjectAgents()
  resetRepoForm()
  activeHelp.value = null
  dialogMode.value = 'create'
  dialogVisible.value = true
}

const openEditDialog = async (repo: ProjectRepo) => {
  await fetchProjectAgents()
  activeHelp.value = null
  editingRepoId.value = repo.id
  dialogMode.value = 'edit'
  repoForm.project_code = repo.project_code
  repoForm.project_name = repo.project_name
  repoForm.associate_repo = repo.has_repo ?? !!repo.repo_url
  repoForm.repo_url = repo.repo_url
  repoForm.default_branch = repo.default_branch || 'main'
  repoForm.git_token = ''
  repoForm.project_card = repo.project_card || ''
  repoForm.enabled = repo.enabled
  repoForm.enabled_agent_keys = [...(repo.enabled_agent_keys || [])]
  normalizeRepoFormAgentKeys()
  dialogVisible.value = true
}

const closeDialog = () => {
  if (savingRepo.value) return
  activeHelp.value = null
  dialogVisible.value = false
}

const buildPayload = (): ProjectRepoPayload => {
  const associate = repoForm.associate_repo
  const payload: ProjectRepoPayload = {
    project_name: repoForm.project_name.trim(),
    // 未关联代码仓库时清空 URL（后端据此判定项目不向其它 Agent 暴露）。
    repo_url: associate ? repoForm.repo_url.trim() : '',
    default_branch: repoForm.default_branch.trim() || 'main',
    project_card: repoForm.project_card.trim(),
  }
  // 项目成员管理员仅能修改安全的项目字段；enabled/git_token 为全局管理员专属，
  // 后端也会拒绝项目成员对这些字段的修改，因此前端不下发。
  if (!isGlobalAdmin.value) {
    return payload
  }
  payload.enabled = repoForm.enabled
  payload.enabled_agent_keys = [...repoForm.enabled_agent_keys]
  if (dialogMode.value === 'create') {
    payload.project_code = repoForm.project_code.trim().toLowerCase()
  }
  if (associate) {
    const token = repoForm.git_token.trim()
    if (token && token !== '••••••••') payload.git_token = token
  } else {
    // 编辑时若改为不关联仓库，显式清空 Token。
    payload.git_token = ''
  }
  return payload
}

const validateForm = () => {
  if (!repoForm.project_code.trim()) return t('admin.projectRepos.projectCodeRequired')
  if (!repoForm.project_name.trim()) return t('admin.projectRepos.projectNameRequired')
  if (!repoForm.project_card.trim()) return t('admin.projectRepos.projectCardRequired')
  if (repoForm.associate_repo && !repoForm.repo_url.trim()) return t('admin.projectRepos.repoUrlRequired')
  if (isGlobalAdmin.value && !repoForm.enabled_agent_keys.length) return t('admin.projectRepos.agentRequired')
  return ''
}

const submitRepo = async () => {
  const validationError = validateForm()
  if (validationError) {
    appStore.showNotification({ title: validationError, type: 'warning' })
    return
  }

  savingRepo.value = true
  try {
    const payload = buildPayload()
    const resp =
      dialogMode.value === 'create'
        ? await adminApi.createProjectRepo(payload)
        : await adminApi.updateProjectRepo(editingRepoId.value as number, payload)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.projectRepos.saveFailFallback'))
    appStore.showNotification({
      title: dialogMode.value === 'create' ? t('admin.projectRepos.createSuccess') : t('admin.projectRepos.updateSuccess'),
      message: resp.data.project_code,
      type: 'success',
    })
    dialogVisible.value = false
    await fetchRepos()
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.projectRepos.saveFailFallback'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    savingRepo.value = false
  }
}

const deleteRepo = async (repo: ProjectRepo) => {
  if (!window.confirm(t('admin.projectRepos.deleteConfirm', { code: repo.project_code }))) return
  deletingId.value = repo.id
  try {
    try {
      await adminApi.deleteProjectRepo(repo.id)
    } catch (err: any) {
      // 409：项目仍被日志引用，确认后强制删除（关联日志的 project_id 置空）
      const affected = err?.response?.status === 409 ? err?.response?.data?.affected_logs : undefined
      if (affected === undefined) throw err
      if (
        !window.confirm(
          t('admin.projectRepos.deleteForceConfirm', { code: repo.project_code, count: affected })
        )
      ) {
        return
      }
      await adminApi.deleteProjectRepo(repo.id, true)
    }
    repos.value = repos.value.filter((item) => item.id !== repo.id)
    delete testResults[repo.id]
    appStore.showNotification({ title: t('admin.projectRepos.deleteSuccess'), message: repo.project_code, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.projectRepos.deleteFailFallback'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    deletingId.value = null
  }
}

const testConnection = async (repo: ProjectRepo) => {
  testingId.value = repo.id
  delete testResults[repo.id]
  try {
    const resp = await adminApi.testProjectRepoConnection(repo.id)
    testResults[repo.id] = resp.data
  } catch (err: any) {
    testResults[repo.id] = {
      success: false,
      message: parseErrorMessage(err),
      auth_method: 'unknown',
    }
  } finally {
    testingId.value = null
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await Promise.all([fetchProjectAgents(), fetchRepos()])
    } else {
      clearAuth()
    }
  } catch {
    clearAuth()
  }
}

onMounted(() => bootstrap())

watch(
  () => repoForm.associate_repo,
  () => {
    normalizeRepoFormAgentKeys()
  }
)
</script>

<template>
  <div class="admin-console admin-project-repos-page">
    <header class="admin-topbar">
      <div class="admin-topbar-inner">
        <div class="admin-topbar-left">
          <button
            class="admin-back-btn"
            :title="t('admin.backToChatTitle')"
            :aria-label="t('admin.backToChatTitle')"
            @click="router.push('/workbench')"
          >
            <ArrowLeft :size="16" />
            <span class="admin-back-btn-label">{{ t('admin.backToChat') }}</span>
          </button>
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
            <p class="admin-subtitle">{{ t('admin.projectRepos.subtitle') }}</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <ThemeToggle class="admin-theme-toggle" />
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? t('admin.projectRepos.badge', { enabled: enabledCount, disabled: disabledCount }) : t('admin.badgeNotLoggedIn') }}
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
    />

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
            <span class="text-xs text-slate-500">{{ t('admin.secureAccess') }}</span>
          </div>
          <form class="space-y-4 max-w-sm" @submit.prevent="handleLogin">
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
          <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div class="min-w-0 flex-1">
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.projectRepos.listTitle') }}</h2>
              <p class="mt-0.5 text-sm text-slate-500 md:truncate" :title="t('admin.projectRepos.listDesc')">
                {{ t('admin.projectRepos.listDesc') }}
              </p>
            </div>
            <div class="flex shrink-0 flex-nowrap items-center gap-2">
              <label class="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600">
                <input
                  v-model="includeDisabled"
                  type="checkbox"
                  class="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                  @change="fetchRepos"
                />
                {{ t('admin.projectRepos.showDisabled') }}
              </label>
              <button
                class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loadingRepos"
                @click="fetchRepos"
              >
                <RefreshCw :size="15" />
                {{ loadingRepos ? t('admin.refreshing') : t('common.refresh') }}
              </button>
              <button
                v-if="isGlobalAdmin"
                class="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700"
                @click="openCreateDialog"
              >
                <Plus :size="16" />
                {{ t('admin.projectRepos.newRepoBtn') }}
              </button>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <div v-if="loadingRepos" class="px-5 py-12 text-center text-sm text-slate-400">
            {{ t('admin.projectRepos.loadingText') }}
          </div>

          <div v-else-if="!repos.length" class="px-5 py-12 text-center">
            <p class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.emptyTitle') }}</p>
            <p class="mt-1 text-xs text-slate-400">{{ t('admin.projectRepos.emptyHint') }}</p>
          </div>

          <div v-else class="project-table-wrap">
            <table class="project-table text-sm text-slate-700">
              <colgroup>
                <col class="project-table-col-project" />
                <col class="project-table-col-repository" />
                <col class="project-table-col-access" />
                <col class="project-table-col-updated" />
                <col class="project-table-col-actions" />
              </colgroup>
              <thead>
                <tr class="border-b border-slate-100 bg-slate-50">
                  <th class="py-2.5 pl-5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.projectRepos.colProject') }}</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.projectRepos.colRepository') }}</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.projectRepos.colAccessStatus') }}</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.projectRepos.colUpdatedAt') }}</th>
                  <th class="py-2.5 pr-5 text-right font-semibold text-slate-600">{{ t('admin.projectRepos.colActions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="repo in repos"
                  :key="repo.id"
                  class="project-table-row border-b border-slate-100 hover:bg-slate-50/70 transition-colors"
                >
                  <td class="project-cell py-3 pl-5 pr-4" :data-label="t('admin.projectRepos.colProject')">
                    <div class="project-name font-semibold text-slate-900">{{ repo.project_name }}</div>
                    <div class="mt-1 flex min-w-0 flex-wrap items-center gap-2">
                      <code class="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{{ repo.project_code }}</code>
                      <span class="project-card-summary min-w-0 truncate text-xs text-slate-400" :title="repo.project_card">
                        {{ repo.project_card }}
                      </span>
                    </div>
                    <div class="mt-2 flex flex-wrap gap-1">
                      <span
                        v-for="label in enabledAgentLabels(repo)"
                        :key="`${repo.id}-${label}`"
                        class="inline-flex items-center rounded-full bg-cyan-50 px-2 py-0.5 text-[11px] font-semibold text-cyan-700"
                      >
                        {{ label }}
                      </span>
                    </div>
                  </td>
                  <td class="project-repository-cell py-3 pr-4" :data-label="t('admin.projectRepos.colRepository')">
                    <span
                      v-if="(repo.has_repo ?? !!repo.repo_url)"
                      class="project-repo-url block truncate font-mono text-xs text-slate-600"
                      :title="repo.repo_url"
                    >
                      {{ repo.repo_url }}
                    </span>
                    <span
                      v-else
                      class="inline-flex rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700"
                    >
                      {{ t('admin.projectRepos.noRepoTag') }}
                    </span>
                    <div v-if="(repo.has_repo ?? !!repo.repo_url)" class="project-repo-meta mt-2">
                      <span class="project-repo-meta-item" :title="t('admin.projectRepos.colBranch')">
                        <span>{{ t('admin.projectRepos.colBranch') }}</span>
                        <code>{{ repo.default_branch }}</code>
                      </span>
                      <span
                        class="inline-flex rounded-full px-2 py-1 text-xs font-semibold"
                        :class="repo.git_token_set ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                      >
                        {{ repo.git_token_set ? t('admin.projectRepos.tokenSet') : t('admin.projectRepos.tokenNotSet') }}
                      </span>
                    </div>
                    <div
                      v-if="testResults[repo.id]"
                      class="project-test-result mt-2 flex items-start gap-1.5 rounded-lg border px-2 py-1.5 text-xs"
                      :class="testResults[repo.id]?.success
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'border-red-200 bg-red-50 text-red-700'"
                    >
                      <CheckCircle2 v-if="testResults[repo.id]?.success" :size="14" class="mt-0.5 shrink-0" />
                      <CircleAlert v-else :size="14" class="mt-0.5 shrink-0" />
                      <span>{{ testResults[repo.id]?.message }}（{{ testResults[repo.id]?.auth_method }}）</span>
                    </div>
                  </td>
                  <td class="project-access-cell py-3 pr-4" :data-label="t('admin.projectRepos.colAccessStatus')">
                    <div class="project-access-stack">
                    <span class="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-1 text-xs font-semibold text-indigo-700">
                      <Users :size="13" />
                      {{ t('admin.projectRepos.memberCount', { count: repo.member_count ?? 0 }) }}
                    </span>
                    <span
                      class="inline-flex rounded-full px-2 py-1 text-xs font-semibold"
                      :class="repo.enabled ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-100 text-slate-500'"
                    >
                      {{ repo.enabled ? t('admin.projectRepos.statusEnabled') : t('admin.projectRepos.statusDisabled') }}
                    </span>
                    </div>
                  </td>
                  <td class="project-updated-cell py-3 pr-4 text-xs text-slate-400" :data-label="t('admin.projectRepos.colUpdatedAt')">
                    {{ formatTimestamp(repo.updated_at) }}
                  </td>
                  <td class="project-actions-cell py-3 pr-5" :data-label="t('admin.projectRepos.colActions')">
                    <div class="project-table-actions">
                      <button
                        class="admin-action-btn project-action-btn"
                        :title="t('admin.projectRepos.tooltipSkills')"
                        @click="router.push(`/admin/project-repos/${repo.project_code}/skills`)"
                      >
                        <FolderTree :size="15" />
                      </button>
                      <button v-if="isGlobalAdmin" class="admin-action-btn project-action-btn" :title="t('admin.projectRepos.tooltipMembers')" @click="openMemberDialog(repo)">
                        <Users :size="15" />
                      </button>
                      <button
                        v-if="(repo.has_repo ?? !!repo.repo_url)"
                        class="admin-action-btn project-action-btn"
                        :disabled="testingId === repo.id"
                        :title="t('admin.projectRepos.tooltipTestConn')"
                        @click="testConnection(repo)"
                      >
                        <PlugZap :size="15" />
                      </button>
                      <button class="admin-action-btn project-action-btn" :title="t('common.edit')" @click="openEditDialog(repo)">
                        <Pencil :size="15" />
                      </button>
                      <button
                        v-if="isGlobalAdmin"
                        class="admin-action-btn project-action-btn danger"
                        :disabled="deletingId === repo.id"
                        :title="t('common.delete')"
                        @click="deleteRepo(repo)"
                      >
                        <Trash2 :size="15" />
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>

    <div v-if="dialogVisible" class="admin-modal-backdrop">
      <div
        class="admin-modal-card repo-modal"
        role="dialog"
        aria-modal="true"
        :aria-label="dialogMode === 'create' ? t('admin.projectRepos.dialogCreateTitle') : t('admin.projectRepos.dialogEditTitle')"
        @click.stop="activeHelp = null"
        @keydown.esc="activeHelp = null"
      >
        <header class="repo-modal-header">
          <div class="min-w-0">
            <div class="flex items-center gap-2.5">
              <span class="repo-modal-mark"><FolderTree :size="17" /></span>
              <h3 class="truncate text-base font-semibold text-slate-900">
                {{ dialogMode === 'create' ? t('admin.projectRepos.dialogCreateTitle') : t('admin.projectRepos.dialogEditTitle') }}
              </h3>
            </div>
          </div>
          <button class="admin-close-btn shrink-0" :disabled="savingRepo" :title="t('admin.projectRepos.tooltipClose')" @click="closeDialog">
            <X :size="17" />
          </button>
        </header>

        <div class="repo-modal-body">
          <div class="repo-modal-grid">
            <section class="repo-modal-section repo-project-section">
              <div class="repo-section-heading">
                <span class="repo-section-index">01</span>
                <div class="min-w-0 flex-1">
                  <div class="repo-section-title-line">
                    <h4>{{ t('admin.projectRepos.projectSectionTitle') }}</h4>
                  </div>
                  <p>{{ t('admin.projectRepos.projectSectionHint') }}</p>
                </div>
              </div>

              <div class="repo-field-grid">
                <div class="block">
                  <div class="repo-field-label">
                    <label for="repo-project-code">Project Code <span class="text-rose-500">*</span></label>
                    <div class="repo-help">
                      <button
                        type="button"
                        class="repo-help-trigger"
                        :class="{ 'is-active': activeHelp === 'projectCode' }"
                        :aria-label="t('admin.projectRepos.helpAriaLabel', { label: 'Project Code' })"
                        :aria-expanded="activeHelp === 'projectCode'"
                        aria-controls="repo-help-project-code"
                        @click.stop="toggleHelp('projectCode')"
                      >
                        <CircleHelp :size="14" />
                      </button>
                      <Transition name="repo-help-popover">
                        <div v-if="activeHelp === 'projectCode'" id="repo-help-project-code" class="repo-help-popover" role="dialog" @click.stop>
                          <strong>Project Code</strong>
                          <p>{{ t('admin.projectRepos.projectCodeHint') }}</p>
                        </div>
                      </Transition>
                    </div>
                  </div>
                  <input
                    id="repo-project-code"
                    v-model="repoForm.project_code"
                    type="text"
                    class="repo-input font-mono disabled:bg-slate-50 disabled:text-slate-400"
                    placeholder="oam_antenna"
                    :disabled="dialogMode === 'edit'"
                    spellcheck="false"
                  />
                </div>
                <label class="block">
                  <span class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.fieldProjectName') }} <span class="text-rose-500">*</span></span>
                  <input
                    v-model="repoForm.project_name"
                    type="text"
                    class="repo-input"
                    placeholder="OAM Antenna"
                  />
                </label>
              </div>

              <label class="block">
                <span class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.fieldProjectCard') }} <span class="text-rose-500">*</span></span>
                <textarea
                  v-model="repoForm.project_card"
                  rows="5"
                  maxlength="4000"
                  class="repo-input repo-card-textarea resize-none"
                  :placeholder="t('admin.projectRepos.projectCardPlaceholder')"
                />
                <span class="mt-1.5 block text-xs leading-5 text-slate-400">{{ t('admin.projectRepos.projectCardHint') }}</span>
              </label>

              <div v-if="isGlobalAdmin" class="repo-toggle-card repo-project-status">
                <div>
                  <p class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.enableRepoLabel') }}</p>
                  <p class="mt-0.5 text-xs leading-5 text-slate-400">{{ t('admin.projectRepos.enableRepoHint') }}</p>
                </div>
                <label class="relative inline-flex shrink-0 cursor-pointer items-center">
                  <input v-model="repoForm.enabled" type="checkbox" class="peer sr-only" />
                  <span class="h-6 w-11 rounded-full bg-slate-300 transition peer-checked:bg-cyan-500"></span>
                  <span class="absolute left-0.5 h-5 w-5 rounded-full bg-white shadow transition peer-checked:translate-x-5"></span>
                </label>
              </div>
            </section>

            <section class="repo-modal-section repo-integration-section">
              <div class="repo-section-heading">
                <span class="repo-section-index">02</span>
                <div class="min-w-0 flex-1">
                  <div class="repo-section-title-line">
                    <h4>{{ t('admin.projectRepos.integrationSectionTitle') }}</h4>
                    <div class="repo-help is-end">
                      <span class="repo-help-node"><PlugZap :size="12" />{{ t('admin.projectRepos.connectivityLabel') }}</span>
                      <button
                        type="button"
                        class="repo-help-trigger"
                        :class="{ 'is-active': activeHelp === 'connectivity' }"
                        :aria-label="t('admin.projectRepos.helpAriaLabel', { label: t('admin.projectRepos.connectivityLabel') })"
                        :aria-expanded="activeHelp === 'connectivity'"
                        aria-controls="repo-help-connectivity"
                        @click.stop="toggleHelp('connectivity')"
                      >
                        <CircleHelp :size="14" />
                      </button>
                      <Transition name="repo-help-popover">
                        <div v-if="activeHelp === 'connectivity'" id="repo-help-connectivity" class="repo-help-popover" role="dialog" @click.stop>
                          <strong>{{ t('admin.projectRepos.connectivityLabel') }}</strong>
                          <p>{{ t('admin.projectRepos.connectionHint') }}</p>
                        </div>
                      </Transition>
                    </div>
                  </div>
                  <p>{{ t('admin.projectRepos.integrationSectionHint') }}</p>
                </div>
              </div>

              <div class="repo-toggle-card">
                <div>
                  <p class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.associateRepoLabel') }}</p>
                  <p class="mt-0.5 text-xs leading-5 text-slate-400">{{ t('admin.projectRepos.associateRepoHint') }}</p>
                </div>
                <label class="relative inline-flex shrink-0 cursor-pointer items-center">
                  <input v-model="repoForm.associate_repo" type="checkbox" class="peer sr-only" />
                  <span class="h-6 w-11 rounded-full bg-slate-300 transition peer-checked:bg-cyan-500"></span>
                  <span class="absolute left-0.5 h-5 w-5 rounded-full bg-white shadow transition peer-checked:translate-x-5"></span>
                </label>
              </div>

              <template v-if="repoForm.associate_repo">
                <label class="block">
                  <span class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.fieldRepoUrl') }} <span class="text-rose-500">*</span></span>
                  <input
                    v-model="repoForm.repo_url"
                    type="url"
                    class="repo-input font-mono"
                    placeholder="https://gitlab.example.com/group/project.git"
                    spellcheck="false"
                  />
                </label>
                <div class="repo-field-grid">
                  <label class="block">
                    <span class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.fieldBranch') }}</span>
                    <input
                      v-model="repoForm.default_branch"
                      type="text"
                      class="repo-input font-mono"
                      placeholder="main"
                      spellcheck="false"
                    />
                  </label>
                  <div v-if="isGlobalAdmin" class="block">
                    <div class="repo-field-label">
                      <label for="repo-git-token">{{ t('admin.projectRepos.fieldToken') }}</label>
                      <div class="repo-help is-end">
                        <button
                          type="button"
                          class="repo-help-trigger"
                          :class="{ 'is-active': activeHelp === 'token' }"
                          :aria-label="t('admin.projectRepos.helpAriaLabel', { label: t('admin.projectRepos.fieldToken') })"
                          :aria-expanded="activeHelp === 'token'"
                          aria-controls="repo-help-token"
                          @click.stop="toggleHelp('token')"
                        >
                          <CircleHelp :size="14" />
                        </button>
                        <Transition name="repo-help-popover">
                          <div v-if="activeHelp === 'token'" id="repo-help-token" class="repo-help-popover" role="dialog" @click.stop>
                            <strong>{{ t('admin.projectRepos.fieldToken') }}</strong>
                            <p>{{ t('admin.projectRepos.tokenHint') }}</p>
                            <p class="repo-help-note">{{ t('admin.projectRepos.tokenHintEdit') }}</p>
                          </div>
                        </Transition>
                      </div>
                    </div>
                    <input
                      id="repo-git-token"
                      v-model="repoForm.git_token"
                      type="password"
                      autocomplete="new-password"
                      class="repo-input font-mono"
                      :placeholder="dialogMode === 'edit' ? t('admin.projectRepos.tokenPlaceholderEdit') : t('admin.projectRepos.tokenPlaceholderCreate')"
                    />
                  </div>
                </div>
              </template>
              <p v-else class="rounded-xl border border-dashed border-amber-200 bg-amber-50/70 px-3 py-2.5 text-xs leading-5 text-amber-800">
                {{ t('admin.projectRepos.noRepoNotice') }}
              </p>

              <div v-if="isGlobalAdmin" class="repo-agent-panel">
                <div class="repo-agent-heading">
                  <Bot :size="17" class="mt-0.5 shrink-0 text-cyan-600" />
                  <div>
                    <p class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.agentSelectLabel') }}</p>
                    <p class="mt-0.5 text-xs leading-5 text-slate-400">{{ t('admin.projectRepos.agentSelectHint') }}</p>
                  </div>
                </div>
                <div v-if="loadingProjectAgents" class="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-center text-xs text-slate-400">
                  {{ t('admin.projectRepos.loadingAgents') }}
                </div>
                <div v-else class="repo-agent-grid">
                  <label
                    v-for="agent in projectAgents"
                    :key="agent.key"
                    class="repo-agent-card"
                    :class="[
                      repoForm.enabled_agent_keys.includes(agent.key) ? 'is-selected' : '',
                      agent.requires_repo && !repoForm.associate_repo ? 'is-disabled' : ''
                    ]"
                  >
                    <input
                      type="checkbox"
                      class="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                      :checked="repoForm.enabled_agent_keys.includes(agent.key)"
                      :disabled="agent.requires_repo && !repoForm.associate_repo"
                      @change="toggleProjectAgent(agent.key)"
                    />
                    <span class="min-w-0">
                      <span class="block font-semibold leading-5">{{ projectAgentLabel(agent) }}</span>
                      <span class="mt-1 block text-[11px] leading-4 text-slate-500">{{ projectAgentDescription(agent) }}</span>
                      <span v-if="agent.requires_repo" class="mt-1.5 inline-flex rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-500">
                        {{ t('admin.projectRepos.agentRequiresRepo') }}
                      </span>
                    </span>
                  </label>
                </div>
              </div>
            </section>
          </div>
        </div>

        <footer class="repo-modal-footer">
          <button
            class="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            :disabled="savingRepo"
            @click="closeDialog"
          >
            {{ t('admin.projectRepos.cancelBtn') }}
          </button>
          <button
            class="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-5 py-2 text-sm font-semibold text-white shadow-sm shadow-cyan-600/20 hover:bg-cyan-700 disabled:opacity-60"
            :disabled="savingRepo"
            @click="submitRepo"
          >
            <Save :size="16" />
            {{ savingRepo ? t('admin.projectRepos.savingBtn') : t('admin.projectRepos.saveBtn') }}
          </button>
        </footer>
      </div>
    </div>

    <div
      v-if="memberDialogVisible && selectedRepoForMembers"
      class="admin-modal-backdrop"
      @click="closeMemberDialog"
    >
      <div class="admin-modal-card member-modal" @click.stop>
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 class="text-base font-semibold text-slate-900">{{ t('admin.projectRepos.memberMgmtTitle') }}</h3>
            <p class="mt-1 text-sm text-slate-500">
              {{ selectedRepoForMembers.project_name }}
              <code class="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                {{ selectedRepoForMembers.project_code }}
              </code>
            </p>
          </div>
          <button class="admin-close-btn" :title="t('admin.projectRepos.tooltipClose')" @click="closeMemberDialog">
            <X :size="17" />
          </button>
        </div>

        <div class="member-permission-note">
          <Users :size="17" class="member-permission-note-icon" />
          <div>
            <p class="member-permission-note-title">{{ t('admin.projectRepos.colMembers') }}</p>
            <p class="member-permission-note-copy">{{ t('admin.projectRepos.memberHint') }}</p>
          </div>
        </div>

        <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.95fr)]">
          <section class="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div class="mb-3 flex items-center justify-between gap-3">
              <div>
                <h4 class="text-sm font-semibold text-slate-900">{{ t('admin.projectRepos.currentMembersTitle') }}</h4>
                <p class="text-xs text-slate-500">{{ t('admin.projectRepos.memberCountDesc', { count: projectMembers.length }) }}</p>
              </div>
              <button
                class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50"
                :disabled="loadingMembers"
                @click="fetchProjectMembers(selectedRepoForMembers.id)"
              >
                <RefreshCw :size="13" />
                {{ loadingMembers ? t('admin.refreshing') : t('common.refresh') }}
              </button>
            </div>

            <div v-if="loadingMembers" class="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-400">
              {{ t('admin.projectRepos.loadingMembers') }}
            </div>
            <div v-else-if="!projectMembers.length" class="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-8 text-center">
              <p class="text-sm font-medium text-slate-700">{{ t('admin.projectRepos.noMembers') }}</p>
              <p class="mt-1 text-xs text-slate-400">{{ t('admin.projectRepos.noMembersHint') }}</p>
            </div>
            <div v-else class="member-list-scroll space-y-2">
              <div
                v-for="member in projectMembers"
                :key="member.id"
                class="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2"
              >
                <div class="min-w-0">
                  <div class="flex items-center gap-2">
                    <p class="truncate text-sm font-semibold text-slate-900">{{ member.display_name || member.username }}</p>
                    <code class="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                      {{ member.username }}
                    </code>
                  </div>
                  <p class="mt-0.5 truncate text-xs text-slate-500">{{ member.email || t('admin.projectRepos.noEmail') }}</p>
                </div>
                <button
                  class="admin-action-btn danger shrink-0"
                  :disabled="removingMemberId === member.id"
                  :title="t('admin.projectRepos.tooltipRemoveMember')"
                  @click="removeProjectMember(member)"
                >
                  <UserMinus :size="15" />
                </button>
              </div>
            </div>
          </section>

          <section class="rounded-xl border border-slate-200 bg-white p-4">
            <div class="mb-3">
              <h4 class="text-sm font-semibold text-slate-900">{{ t('admin.projectRepos.addMembersTitle') }}</h4>
              <p class="text-xs text-slate-500">{{ t('admin.projectRepos.addMembersDesc') }}</p>
            </div>

            <label class="block">
              <span class="sr-only">{{ t('admin.projectRepos.addMembersTitle') }}</span>
              <div class="relative">
                <Search class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" :size="16" />
                <input
                  v-model="memberSearch"
                  type="search"
                  class="w-full rounded-lg border border-slate-200 py-2 pl-9 pr-3 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :placeholder="t('admin.projectRepos.searchUserPlaceholder')"
                />
              </div>
            </label>

            <div class="mt-3">
              <div v-if="loadingUsers" class="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-400">
                {{ t('admin.projectRepos.loadingUsers') }}
              </div>
              <div v-else-if="!normalizedMemberSearch" class="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                {{ t('admin.projectRepos.enterKeyword') }}
              </div>
              <div v-else-if="!filteredUserCandidates.length" class="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
                {{ t('admin.projectRepos.noMatchingUsers') }}
              </div>
              <div v-else class="member-list-scroll space-y-2">
                <div
                  v-for="user in filteredUserCandidates"
                  :key="user.id"
                  class="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-3 py-2"
                >
                  <div class="min-w-0">
                    <div class="flex items-center gap-2">
                      <p class="truncate text-sm font-semibold text-slate-900">{{ user.display_name || user.username }}</p>
                      <span
                        v-if="!user.is_active"
                        class="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500"
                      >
                        {{ t('admin.projectRepos.userDisabled') }}
                      </span>
                    </div>
                    <p class="mt-0.5 truncate text-xs text-slate-500">
                      {{ user.username }} · {{ user.email || t('admin.projectRepos.noEmail') }}
                    </p>
                  </div>
                  <button
                    class="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-cyan-200 px-2.5 py-1.5 text-xs font-semibold text-cyan-700 hover:bg-cyan-50 disabled:opacity-50"
                    :disabled="addingMemberId === user.id"
                    @click="addProjectMember(user)"
                  >
                    <UserPlus :size="14" />
                    {{ addingMemberId === user.id ? t('admin.projectRepos.addingMember') : t('admin.projectRepos.addMemberBtn') }}
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
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

.admin-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  border: 1px solid #cbd5e1;
  color: #475569;
  background: #ffffff;
  transition: all 0.15s ease;
}

.admin-action-btn:hover:not(:disabled) {
  border-color: #22d3ee;
  color: #0891b2;
  background: #ecfeff;
}

.admin-action-btn.danger:hover:not(:disabled) {
  border-color: #fecdd3;
  color: #e11d48;
  background: #fff1f2;
}

.admin-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.project-table-wrap,
.project-table {
  width: 100%;
}

.project-table-wrap {
  overflow: hidden;
}

.project-table {
  table-layout: fixed;
  border-collapse: collapse;
}

.project-table-col-project {
  width: 28%;
}

.project-table-col-repository {
  width: 29%;
}

.project-table-col-access {
  width: 13%;
}

.project-table-col-updated {
  width: 12%;
}

.project-table-col-actions {
  width: 18%;
}

.project-table th,
.project-table td {
  min-width: 0;
  vertical-align: top;
}

.project-name,
.project-test-result span {
  overflow-wrap: anywhere;
}

.project-card-summary,
.project-repo-url {
  width: 100%;
}

.project-cell > div:last-child span {
  max-width: 100%;
  overflow-wrap: anywhere;
}

.project-repo-meta {
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}

.project-repo-meta-item {
  min-width: 0;
  max-width: 100%;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border-radius: 999px;
  background: #f1f5f9;
  padding: 0.25rem 0.5rem;
  color: #64748b;
  font-size: 0.68rem;
  line-height: 1rem;
}

.project-repo-meta-item span {
  flex: none;
}

.project-repo-meta-item code {
  min-width: 0;
  overflow: hidden;
  color: #334155;
  font-size: 0.7rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-access-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.45rem;
}

.project-updated-cell {
  line-height: 1.15rem;
  overflow-wrap: anywhere;
}

.project-table-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.375rem;
}

.project-action-btn {
  width: 1.9rem;
  height: 1.9rem;
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
  width: min(720px, 100%);
  border-radius: 1rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  box-shadow: 0 20px 45px rgba(15, 23, 42, 0.25);
  padding: 1.25rem;
}

.repo-modal {
  width: min(1180px, 100%);
  max-height: calc(100dvh - 2rem);
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.repo-modal-header,
.repo-modal-footer {
  flex: none;
  background: rgba(255, 255, 255, 0.97);
}

.repo-modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid #e2e8f0;
}

.repo-modal-mark {
  width: 1.85rem;
  height: 1.85rem;
  border-radius: 0.55rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #0e7490;
  background: #cffafe;
  border: 1px solid #a5f3fc;
}

.repo-modal-body {
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 1rem;
  background:
    radial-gradient(circle at 8% 0%, rgba(34, 211, 238, 0.08), transparent 30%),
    #f8fafc;
}

.repo-modal-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.88fr) minmax(0, 1.12fr);
  gap: 1rem;
  align-items: start;
}

.repo-modal-section {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.9rem;
  padding: 1rem;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.repo-section-heading {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  padding-bottom: 0.7rem;
  border-bottom: 1px solid #f1f5f9;
}

.repo-section-heading h4 {
  color: #0f172a;
  font-size: 0.875rem;
  font-weight: 700;
  line-height: 1.25rem;
}

.repo-section-heading p {
  margin-top: 0.1rem;
  color: #94a3b8;
  font-size: 0.7rem;
  line-height: 1rem;
}

.repo-section-title-line,
.repo-field-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.repo-section-title-line {
  justify-content: space-between;
}

.repo-field-label {
  min-height: 1.25rem;
  color: #334155;
  font-size: 0.875rem;
  font-weight: 500;
}

.repo-help {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  flex: none;
}

.repo-help-node {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  color: #64748b;
  font-size: 0.68rem;
  font-weight: 600;
  line-height: 1rem;
}

.repo-help-trigger {
  width: 1.15rem;
  height: 1.15rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #94a3b8;
  transition: color 0.15s ease, background 0.15s ease, transform 0.15s ease;
}

.repo-help-trigger:hover,
.repo-help-trigger:focus-visible,
.repo-help-trigger.is-active {
  color: #0891b2;
  background: #cffafe;
  outline: none;
}

.repo-help-trigger:active {
  transform: scale(0.92);
}

.repo-help-popover {
  position: absolute;
  top: calc(100% + 0.45rem);
  left: 0;
  z-index: 30;
  width: min(19rem, calc(100vw - 3rem));
  border: 1px solid #cbd5e1;
  border-radius: 0.75rem;
  background: #ffffff;
  padding: 0.7rem 0.8rem;
  color: #475569;
  font-size: 0.75rem;
  font-weight: 400;
  line-height: 1.25rem;
  text-align: left;
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.16);
}

.repo-help.is-end .repo-help-popover {
  right: 0;
  left: auto;
}

.repo-help-popover::before {
  position: absolute;
  top: -0.3rem;
  left: 0.45rem;
  width: 0.55rem;
  height: 0.55rem;
  content: '';
  border-top: 1px solid #cbd5e1;
  border-left: 1px solid #cbd5e1;
  background: #ffffff;
  transform: rotate(45deg);
}

.repo-help.is-end .repo-help-popover::before {
  right: 0.45rem;
  left: auto;
}

.repo-help-popover strong {
  display: block;
  margin-bottom: 0.2rem;
  color: #0f172a;
  font-size: 0.75rem;
  font-weight: 700;
}

.repo-help-note {
  margin-top: 0.4rem;
  padding-top: 0.4rem;
  border-top: 1px solid #f1f5f9;
  color: #64748b;
}

.repo-help-popover-enter-active,
.repo-help-popover-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
  transform-origin: top left;
}

.repo-help-popover-enter-from,
.repo-help-popover-leave-to {
  opacity: 0;
  transform: translateY(-0.2rem) scale(0.98);
}

.repo-section-index {
  flex: none;
  color: #0891b2;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.65rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  line-height: 1.25rem;
}

.repo-field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

.repo-input {
  width: 100%;
  margin-top: 0.25rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.625rem;
  background: #ffffff;
  padding: 0.55rem 0.75rem;
  color: #0f172a;
  font-size: 0.875rem;
  line-height: 1.25rem;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.repo-input:focus {
  border-color: #06b6d4;
  box-shadow: 0 0 0 3px rgba(207, 250, 254, 0.95);
}

.repo-card-textarea {
  min-height: 7.65rem;
}

.repo-toggle-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  background: #f8fafc;
  padding: 0.65rem 0.75rem;
}

.repo-project-status {
  margin-top: auto;
}

.repo-agent-panel {
  border-top: 1px solid #f1f5f9;
  padding-top: 0.8rem;
}

.repo-agent-heading {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  margin-bottom: 0.65rem;
}

.repo-agent-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.5rem;
}

.repo-agent-card {
  min-width: 0;
  min-height: 6.4rem;
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  cursor: pointer;
  border: 1px solid #e2e8f0;
  border-radius: 0.7rem;
  background: #f8fafc;
  padding: 0.6rem;
  color: #475569;
  font-size: 0.75rem;
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}

.repo-agent-card:hover {
  border-color: #a5f3fc;
  background: #ecfeff;
}

.repo-agent-card.is-selected {
  border-color: #67e8f9;
  background: #ecfeff;
  color: #164e63;
  box-shadow: inset 0 0 0 1px rgba(103, 232, 249, 0.35);
}

.repo-agent-card.is-disabled {
  cursor: not-allowed;
  opacity: 0.52;
}

.repo-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 0.8rem 1.25rem;
  border-top: 1px solid #e2e8f0;
  box-shadow: 0 -8px 22px rgba(15, 23, 42, 0.04);
}

.member-modal {
  width: min(980px, 100%);
  max-height: 90vh;
  overflow-y: auto;
}

.member-permission-note {
  display: flex;
  align-items: flex-start;
  gap: 0.65rem;
  margin-bottom: 1rem;
  border: 1px solid #bae6fd;
  border-radius: 0.75rem;
  background: #f0f9ff;
  padding: 0.75rem 0.85rem;
}

.member-permission-note-icon {
  flex: none;
  margin-top: 0.1rem;
  color: #0284c7;
}

.member-permission-note-title {
  color: #0f172a;
  font-size: 0.75rem;
  font-weight: 700;
  line-height: 1rem;
}

.member-permission-note-copy {
  margin-top: 0.15rem;
  color: #475569;
  font-size: 0.75rem;
  line-height: 1.2rem;
}

.member-list-scroll {
  max-height: 360px;
  overflow-y: auto;
  padding-right: 0.15rem;
}

.admin-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  border: 1px solid #e2e8f0;
  color: #64748b;
  background: #ffffff;
}

.admin-close-btn:hover:not(:disabled) {
  color: #0f172a;
  background: #f8fafc;
}

@media (max-width: 1180px) {
  .project-table colgroup {
    display: none;
  }

  .project-table,
  .project-table tbody {
    display: block;
    width: 100%;
  }

  .project-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
    border: 0;
  }

  .project-table-row {
    display: grid;
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr);
    grid-template-areas:
      'project repository'
      'access updated'
      'actions actions';
    gap: 1rem 1.25rem;
    padding: 1rem 1.1rem;
  }

  .project-table-row > td {
    padding: 0;
  }

  .project-table-row > td::before {
    display: block;
    margin-bottom: 0.4rem;
    color: #94a3b8;
    content: attr(data-label);
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    line-height: 1rem;
    text-transform: uppercase;
  }

  .project-cell {
    grid-area: project;
  }

  .project-repository-cell {
    grid-area: repository;
  }

  .project-access-cell {
    grid-area: access;
  }

  .project-updated-cell {
    grid-area: updated;
  }

  .project-actions-cell {
    grid-area: actions;
    padding-top: 0.75rem !important;
    border-top: 1px solid #f1f5f9;
  }

  .project-access-stack {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .project-table-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 1024px) {
  .admin-topbar-inner {
    padding: 0 0.75rem;
  }

  .admin-topbar-right span {
    display: none;
  }

  .repo-modal-grid {
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

  .admin-modal-backdrop {
    padding: 0.5rem;
  }

  .repo-modal {
    max-height: calc(100dvh - 1rem);
  }

  .repo-modal-header,
  .repo-modal-footer {
    padding-left: 1rem;
    padding-right: 1rem;
  }

  .repo-modal-body {
    padding: 0.75rem;
  }

  .repo-field-grid,
  .repo-agent-grid {
    grid-template-columns: 1fr;
  }

  .project-table-row {
    grid-template-columns: 1fr;
    grid-template-areas:
      'project'
      'repository'
      'access'
      'updated'
      'actions';
    gap: 0.9rem;
    padding: 0.9rem;
  }
}

@media (max-height: 800px) and (min-width: 1025px) {
  .repo-modal-header {
    padding-top: 0.75rem;
    padding-bottom: 0.75rem;
  }

  .repo-modal-body {
    padding: 0.75rem;
  }

  .repo-modal-grid,
  .repo-modal-section {
    gap: 0.75rem;
  }

  .repo-modal-section {
    padding: 0.85rem;
  }

  .repo-card-textarea {
    min-height: 6.25rem;
  }

  .repo-modal-footer {
    padding-top: 0.65rem;
    padding-bottom: 0.65rem;
  }
}
</style>
