<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  CheckCircle2,
  CircleAlert,
  FolderTree,
  LogOut,
  Menu,
  Pencil,
  PanelLeftClose,
  PlugZap,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  X,
} from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import type { ProjectRepo, ProjectRepoPayload, TestConnectionResult } from '@/types'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = adminNavItems

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingRepos = ref(false)
const savingRepo = ref(false)
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const deletingId = ref<number | null>(null)
const testingId = ref<number | null>(null)
const includeDisabled = ref(true)
const repos = ref<ProjectRepo[]>([])
const testResults = reactive<Record<number, TestConnectionResult | undefined>>({})

const authForm = reactive({
  username: '',
  password: '',
})

const repoForm = reactive({
  project_code: '',
  project_name: '',
  repo_url: '',
  default_branch: 'main',
  git_token: '',
  description: '',
  enabled: true,
})

const editingRepoId = ref<number | null>(null)

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))
const enabledCount = computed(() => repos.value.filter((repo) => repo.enabled).length)
const disabledCount = computed(() => repos.value.length - enabledCount.value)

const parseErrorMessage = (err: any): string => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
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
  authForm.password = ''
}

const handleLogin = async () => {
  if (!authForm.username.trim() || !authForm.password) {
    appStore.showNotification({ title: '请输入用户名和密码', type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data?.token) throw new Error(resp?.message || '登录失败')
    adminToken.set(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: '登录成功', message: `欢迎，${resp.data.username}`, type: 'success' })
    await fetchRepos()
  } catch (err: any) {
    appStore.showNotification({ title: '登录失败', message: parseErrorMessage(err), type: 'error' })
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
    appStore.showNotification({ title: '已退出登录', type: 'info' })
  }
}

const handleNavClick = (item: (typeof navItems)[number]) => {
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
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '获取项目仓库失败')
    repos.value = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingRepos.value = false
  }
}

const resetRepoForm = () => {
  editingRepoId.value = null
  repoForm.project_code = ''
  repoForm.project_name = ''
  repoForm.repo_url = ''
  repoForm.default_branch = 'main'
  repoForm.git_token = ''
  repoForm.description = ''
  repoForm.enabled = true
}

const openCreateDialog = () => {
  resetRepoForm()
  dialogMode.value = 'create'
  dialogVisible.value = true
}

const openEditDialog = (repo: ProjectRepo) => {
  editingRepoId.value = repo.id
  dialogMode.value = 'edit'
  repoForm.project_code = repo.project_code
  repoForm.project_name = repo.project_name
  repoForm.repo_url = repo.repo_url
  repoForm.default_branch = repo.default_branch || 'main'
  repoForm.git_token = ''
  repoForm.description = repo.description || ''
  repoForm.enabled = repo.enabled
  dialogVisible.value = true
}

const closeDialog = () => {
  if (savingRepo.value) return
  dialogVisible.value = false
}

const buildPayload = (): ProjectRepoPayload => {
  const payload: ProjectRepoPayload = {
    project_name: repoForm.project_name.trim(),
    repo_url: repoForm.repo_url.trim(),
    default_branch: repoForm.default_branch.trim() || 'main',
    description: repoForm.description.trim() || null,
    enabled: repoForm.enabled,
  }
  if (dialogMode.value === 'create') {
    payload.project_code = repoForm.project_code.trim().toLowerCase()
  }
  const token = repoForm.git_token.trim()
  if (token && token !== '••••••••') payload.git_token = token
  return payload
}

const validateForm = () => {
  if (!repoForm.project_code.trim()) return '请填写 project_code'
  if (!repoForm.project_name.trim()) return '请填写项目名称'
  if (!repoForm.repo_url.trim()) return '请填写 Git 仓库 URL'
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
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '保存失败')
    appStore.showNotification({
      title: dialogMode.value === 'create' ? '已创建项目仓库' : '已更新项目仓库',
      message: resp.data.project_code,
      type: 'success',
    })
    dialogVisible.value = false
    await fetchRepos()
  } catch (err: any) {
    appStore.showNotification({ title: '保存失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    savingRepo.value = false
  }
}

const deleteRepo = async (repo: ProjectRepo) => {
  if (!window.confirm(`确认删除项目仓库 ${repo.project_code}？`)) return
  deletingId.value = repo.id
  try {
    await adminApi.deleteProjectRepo(repo.id)
    repos.value = repos.value.filter((item) => item.id !== repo.id)
    delete testResults[repo.id]
    appStore.showNotification({ title: '已删除项目仓库', message: repo.project_code, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: '删除失败', message: parseErrorMessage(err), type: 'error' })
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
      await fetchRepos()
    } else {
      clearAuth()
    }
  } catch {
    clearAuth()
  }
}

onMounted(() => bootstrap())
</script>

<template>
  <div class="admin-console admin-project-repos-page">
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
            <p class="admin-subtitle">项目仓库管理</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? `${enabledCount} 个启用 / ${disabledCount} 个停用` : '未登录' }}
          </span>
          <button v-if="isAuthenticated" class="admin-logout-btn" @click="handleLogout">
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
    />

    <aside v-if="isAuthenticated" class="admin-sidebar" :class="{ 'is-hidden': !navVisible }">
      <div class="space-y-2">
        <button
          v-for="item in navItems"
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
              <h2 class="text-lg font-semibold text-slate-900">登录后台</h2>
              <p class="text-sm text-slate-500">请输入管理员凭证继续</p>
            </div>
            <span class="text-xs text-slate-500">内部安全访问</span>
          </div>
          <form class="space-y-4 max-w-sm" @submit.prevent="handleLogin">
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
            <button
              type="submit"
              class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
              :disabled="isLoggingIn"
            >
              {{ isLoggingIn ? '登录中…' : '登录' }}
            </button>
          </form>
        </div>
      </section>

      <section v-else class="space-y-4">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">项目仓库注册表</h2>
              <p class="text-sm text-slate-500 mt-0.5">
                维护 metadata.json 中 project_code 到 Git 仓库的映射，Claude Agent 会通过 lookup_project_repo 工具读取这里的配置。
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <label class="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600">
                <input
                  v-model="includeDisabled"
                  type="checkbox"
                  class="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500"
                  @change="fetchRepos"
                />
                显示停用项
              </label>
              <button
                class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loadingRepos"
                @click="fetchRepos"
              >
                <RefreshCw :size="15" />
                {{ loadingRepos ? '刷新中' : '刷新' }}
              </button>
              <button
                class="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-700"
                @click="openCreateDialog"
              >
                <Plus :size="16" />
                新建项目仓库
              </button>
            </div>
          </div>
        </div>

        <div class="bg-slate-50 border border-slate-200 rounded-2xl p-4">
          <div class="grid gap-3 md:grid-cols-3">
            <div>
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Project Code</p>
              <p class="mt-1 text-sm text-slate-600">保存时自动 trim + lower-case，用于 metadata.json 匹配。</p>
            </div>
            <div>
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Token</p>
              <p class="mt-1 text-sm text-slate-600">每个仓库可覆盖全局 Token；响应只显示是否已设置。</p>
            </div>
            <div>
              <p class="text-xs font-semibold uppercase tracking-wide text-slate-400">Connectivity</p>
              <p class="mt-1 text-sm text-slate-600">测试连接会复用服务端 git ls-remote 检查。</p>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <div v-if="loadingRepos" class="px-5 py-12 text-center text-sm text-slate-400">
            正在加载项目仓库…
          </div>

          <div v-else-if="!repos.length" class="px-5 py-12 text-center">
            <p class="text-sm font-medium text-slate-700">还没有项目仓库条目</p>
            <p class="mt-1 text-xs text-slate-400">点击右上角新建，先注册真实项目再运行日志 AI 分析。</p>
          </div>

          <div v-else class="overflow-x-auto">
            <table class="min-w-full text-sm text-slate-700">
              <thead>
                <tr class="border-b border-slate-100 bg-slate-50">
                  <th class="py-2.5 pl-5 pr-4 text-left font-semibold text-slate-600">项目</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">仓库 URL</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">默认分支</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">Token</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">状态</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">更新时间</th>
                  <th class="py-2.5 pr-5 text-right font-semibold text-slate-600">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="repo in repos"
                  :key="repo.id"
                  class="border-b border-slate-50 hover:bg-slate-50/70 transition-colors"
                >
                  <td class="py-3 pl-5 pr-4">
                    <div class="font-semibold text-slate-900">{{ repo.project_name }}</div>
                    <div class="mt-1 flex items-center gap-2">
                      <code class="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{{ repo.project_code }}</code>
                      <span v-if="repo.description" class="max-w-[220px] truncate text-xs text-slate-400" :title="repo.description">
                        {{ repo.description }}
                      </span>
                    </div>
                  </td>
                  <td class="py-3 pr-4">
                    <span class="block max-w-[360px] truncate font-mono text-xs text-slate-600" :title="repo.repo_url">
                      {{ repo.repo_url }}
                    </span>
                    <div
                      v-if="testResults[repo.id]"
                      class="mt-2 flex items-start gap-1.5 rounded-lg border px-2 py-1.5 text-xs"
                      :class="testResults[repo.id]?.success
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'border-red-200 bg-red-50 text-red-700'"
                    >
                      <CheckCircle2 v-if="testResults[repo.id]?.success" :size="14" class="mt-0.5 shrink-0" />
                      <CircleAlert v-else :size="14" class="mt-0.5 shrink-0" />
                      <span>{{ testResults[repo.id]?.message }}（{{ testResults[repo.id]?.auth_method }}）</span>
                    </div>
                  </td>
                  <td class="py-3 pr-4 font-mono text-xs text-slate-500">{{ repo.default_branch }}</td>
                  <td class="py-3 pr-4">
                    <span
                      class="inline-flex rounded-full px-2 py-1 text-xs font-semibold"
                      :class="repo.git_token_set ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                    >
                      {{ repo.git_token_set ? '已设置' : '使用全局/匿名' }}
                    </span>
                  </td>
                  <td class="py-3 pr-4">
                    <span
                      class="inline-flex rounded-full px-2 py-1 text-xs font-semibold"
                      :class="repo.enabled ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-100 text-slate-500'"
                    >
                      {{ repo.enabled ? '启用' : '停用' }}
                    </span>
                  </td>
                  <td class="py-3 pr-4 whitespace-nowrap text-xs text-slate-400">{{ formatTimestamp(repo.updated_at) }}</td>
                  <td class="py-3 pr-5">
                    <div class="flex justify-end gap-2">
                      <button
                        class="admin-action-btn"
                        title="项目 Skill"
                        @click="router.push(`/admin/project-repos/${repo.project_code}/skills`)"
                      >
                        <FolderTree :size="15" />
                      </button>
                      <button
                        class="admin-action-btn"
                        :disabled="testingId === repo.id"
                        title="测试连接"
                        @click="testConnection(repo)"
                      >
                        <PlugZap :size="15" />
                      </button>
                      <button class="admin-action-btn" title="编辑" @click="openEditDialog(repo)">
                        <Pencil :size="15" />
                      </button>
                      <button
                        class="admin-action-btn danger"
                        :disabled="deletingId === repo.id"
                        title="删除"
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

    <div v-if="dialogVisible" class="admin-modal-backdrop" @click="closeDialog">
      <div class="admin-modal-card repo-modal" @click.stop>
        <div class="mb-5 flex items-start justify-between gap-4">
          <div>
            <h3 class="text-base font-semibold text-slate-900">
              {{ dialogMode === 'create' ? '新建项目仓库' : '编辑项目仓库' }}
            </h3>
            <p class="mt-0.5 text-sm text-slate-500">Token 保存后不会回显；编辑时留空表示不修改。</p>
          </div>
          <button class="admin-close-btn" :disabled="savingRepo" title="关闭" @click="closeDialog">
            <X :size="17" />
          </button>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <label class="block">
            <span class="text-sm font-medium text-slate-700">Project Code <span class="text-rose-500">*</span></span>
            <input
              v-model="repoForm.project_code"
              type="text"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none disabled:bg-slate-50 disabled:text-slate-400"
              placeholder="oam_antenna"
              :disabled="dialogMode === 'edit'"
              spellcheck="false"
            />
          </label>
          <label class="block">
            <span class="text-sm font-medium text-slate-700">项目名称 <span class="text-rose-500">*</span></span>
            <input
              v-model="repoForm.project_name"
              type="text"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              placeholder="OAM Antenna"
            />
          </label>
          <label class="block md:col-span-2">
            <span class="text-sm font-medium text-slate-700">Git 仓库 URL <span class="text-rose-500">*</span></span>
            <input
              v-model="repoForm.repo_url"
              type="url"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              placeholder="https://gitlab.example.com/group/project.git"
              spellcheck="false"
            />
          </label>
          <label class="block">
            <span class="text-sm font-medium text-slate-700">默认分支</span>
            <input
              v-model="repoForm.default_branch"
              type="text"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              placeholder="main"
              spellcheck="false"
            />
          </label>
          <label class="block">
            <span class="text-sm font-medium text-slate-700">仓库 Token</span>
            <input
              v-model="repoForm.git_token"
              type="password"
              autocomplete="new-password"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              :placeholder="dialogMode === 'edit' ? '留空表示不修改' : '可选，覆盖全局 Token'"
            />
          </label>
          <label class="block md:col-span-2">
            <span class="text-sm font-medium text-slate-700">描述</span>
            <textarea
              v-model="repoForm.description"
              rows="3"
              class="mt-1 w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              placeholder="可选：适用日志、项目边界或维护负责人"
            />
          </label>
        </div>

        <div class="mt-4 flex items-center justify-between gap-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
          <div>
            <p class="text-sm font-medium text-slate-700">启用此项目仓库</p>
            <p class="text-xs text-slate-400">停用后 lookup_project_repo 不会返回该条目。</p>
          </div>
          <label class="relative inline-flex cursor-pointer items-center">
            <input v-model="repoForm.enabled" type="checkbox" class="peer sr-only" />
            <span class="h-6 w-11 rounded-full bg-slate-300 transition peer-checked:bg-cyan-500"></span>
            <span class="absolute left-0.5 h-5 w-5 rounded-full bg-white shadow transition peer-checked:translate-x-5"></span>
          </label>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <button
            class="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            :disabled="savingRepo"
            @click="closeDialog"
          >
            取消
          </button>
          <button
            class="inline-flex items-center gap-1.5 rounded-lg bg-cyan-600 px-5 py-2 text-sm font-semibold text-white hover:bg-cyan-700 disabled:opacity-60"
            :disabled="savingRepo"
            @click="submitRepo"
          >
            <Save :size="16" />
            {{ savingRepo ? '保存中…' : '保存' }}
          </button>
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

  .repo-modal {
    max-height: 90vh;
    overflow-y: auto;
  }
}
</style>
