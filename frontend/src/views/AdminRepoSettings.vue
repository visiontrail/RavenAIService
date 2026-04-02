<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import type { RepoSettingsData, TestConnectionResult } from '@/types'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

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

// ─── State ───────────────────────────────────────────────────────

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loading = ref(false)
const saving = ref(false)

const authForm = reactive({ username: '', password: '' })

// 表单数据
const form = reactive({
  oam_url: '',
  stack_url: '',
  git_token: '',           // 空 = 不修改；'__CLEAR__' = 清除
  clone_depth: 1,
})

// 原始已保存状态
const saved = reactive<RepoSettingsData>({
  oam_url: '',
  stack_url: '',
  git_token_set: false,
  clone_depth: 1,
  updated_at: '',
})

// 连通性测试结果
const testResults = reactive<Record<'oam' | 'stack', TestConnectionResult | null>>({
  oam: null,
  stack: null,
})
const testingOam   = ref(false)
const testingStack = ref(false)

const toast = reactive({ visible: false, type: 'success' as 'success' | 'error', text: '' })

// ─── Computed ─────────────────────────────────────────────────────

const navVisible = computed(() => appStore.adminSidebarVisible)

const activeNavKey = computed(() => {
  if (route.path.startsWith('/admin/repo-settings')) return 'repo-settings'
  if (route.path.startsWith('/admin/releases')) return 'releases'
  if (route.path.startsWith('/admin/users')) return 'users'
  if (route.path.startsWith('/admin')) return 'prompts'
  return ''
})

const hasUnsavedChanges = computed(() =>
  form.oam_url     !== saved.oam_url   ||
  form.stack_url   !== saved.stack_url ||
  form.clone_depth !== saved.clone_depth ||
  form.git_token   !== ''
)

const tokenPlaceholder = computed(() =>
  saved.git_token_set ? '••••••••（已设置，输入新值可覆盖）' : '粘贴 Personal Access Token…'
)

// ─── Helpers ──────────────────────────────────────────────────────

const showToast = (type: 'success' | 'error', text: string) => {
  toast.visible = true
  toast.type = type
  toast.text = text
  setTimeout(() => { toast.visible = false }, 3500)
}

const parseError = (err: any): string => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
}

const applyServerData = (data: RepoSettingsData) => {
  saved.oam_url      = data.oam_url
  saved.stack_url    = data.stack_url
  saved.git_token_set = data.git_token_set
  saved.clone_depth  = data.clone_depth
  saved.updated_at   = data.updated_at

  // 表单同步（token 字段清空，不回填）
  form.oam_url     = data.oam_url
  form.stack_url   = data.stack_url
  form.clone_depth = data.clone_depth
  form.git_token   = ''
}

// ─── Auth ─────────────────────────────────────────────────────────

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) return
  isLoggingIn.value = true
  try {
    const res = await adminApi.login(authForm.username, authForm.password)
    if (!res?.data?.token) {
      throw new Error(res?.message || '登录失败')
    }
    adminToken.set(res.data.token)
    isAuthenticated.value = true
    await loadSettings()
  } catch (err) {
    showToast('error', parseError(err))
  } finally {
    isLoggingIn.value = false
  }
}

const handleLogout = () => {
  adminToken.clear()
  isAuthenticated.value = false
}

// ─── Data Loading ─────────────────────────────────────────────────

const loadSettings = async () => {
  loading.value = true
  try {
    const res = await adminApi.fetchRepoSettings()
    if (!res?.data) {
      throw new Error(res?.message || '读取仓库配置失败')
    }
    applyServerData(res.data)
  } catch (err) {
    showToast('error', parseError(err))
  } finally {
    loading.value = false
  }
}

// ─── Save ─────────────────────────────────────────────────────────

const handleSave = async () => {
  saving.value = true
  try {
    const payload: any = {
      oam_url:     form.oam_url.trim(),
      stack_url:   form.stack_url.trim(),
      clone_depth: form.clone_depth,
    }

    if (form.git_token === '__CLEAR__') {
      payload.clear_token = true
      payload.git_token = ''
    } else if (form.git_token.trim()) {
      payload.git_token = form.git_token.trim()
    }
    // 否则 git_token 字段不传，后端不修改

    const res = await adminApi.saveRepoSettings(payload)
    if (!res?.data) {
      throw new Error(res?.message || '保存仓库配置失败')
    }
    applyServerData(res.data)
    // 清除测试结果（URL 可能已变）
    testResults.oam   = null
    testResults.stack = null
    showToast('success', '保存成功，配置已立即生效')
  } catch (err) {
    showToast('error', parseError(err))
  } finally {
    saving.value = false
  }
}

const handleClearToken = () => {
  form.git_token = '__CLEAR__'
  showToast('success', '点击保存后 Token 将被清除')
}

// ─── Test Connection ──────────────────────────────────────────────

const testConnection = async (type: 'oam' | 'stack') => {
  const url = type === 'oam' ? form.oam_url.trim() : form.stack_url.trim()
  if (!url) {
    showToast('error', '请先填写仓库 URL')
    return
  }

  const testingRef = type === 'oam' ? testingOam : testingStack
  testingRef.value = true
  testResults[type] = null

  try {
    // 如果表单里有新 Token，用新 Token 测试；否则后端会用已保存的 Token
    const token = form.git_token && form.git_token !== '__CLEAR__'
      ? form.git_token.trim()
      : null

    const res = await adminApi.testRepoConnection({ url, token })
    testResults[type] = res.data as TestConnectionResult
  } catch (err) {
    testResults[type] = {
      success: false,
      message: parseError(err),
      auth_method: 'unknown',
    }
  } finally {
    testingRef.value = false
  }
}

// ─── Nav ──────────────────────────────────────────────────────────

const handleNavClick = (item: (typeof navItems)[number]) => {
  router.push(item.path)
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
}

// ─── Lifecycle ────────────────────────────────────────────────────

onMounted(async () => {
  const token = adminToken.get()
  if (token) {
    try {
      await adminApi.me()
      isAuthenticated.value = true
      await loadSettings()
    } catch {
      adminToken.clear()
    }
  }
})
</script>

<template>
  <div class="admin-console admin-repo-settings-page">
    <!-- Toast -->
    <Transition name="toast-slide">
      <div
        v-if="toast.visible"
        class="fixed top-4 right-4 z-50 px-4 py-3 rounded-xl shadow-lg text-sm font-medium flex items-center gap-2"
        :class="toast.type === 'success'
          ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
          : 'bg-red-50 text-red-800 border border-red-200'"
      >
        <span>{{ toast.type === 'success' ? '✓' : '✕' }}</span>
        <span>{{ toast.text }}</span>
      </div>
    </Transition>

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
            <p class="admin-subtitle">Git 仓库配置</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full" :class="hasUnsavedChanges ? 'bg-amber-100 text-amber-800' : 'bg-slate-700 text-slate-100'">
            {{ isAuthenticated ? (hasUnsavedChanges ? '有未保存的更改' : '已同步') : '未登录' }}
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

    <!-- Sidebar -->
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

    <!-- Main -->
    <main class="admin-main" :class="{ 'is-sidebar-hidden': !isAuthenticated || !navVisible }">
      <!-- Login -->
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

      <!-- Settings -->
      <section v-else class="space-y-4">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4">
          <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">Git 代码仓库配置</h2>
              <p class="text-sm text-slate-500 mt-0.5">
                配置用于日志代码联合分析的源码仓库。保存后立即生效，无需重启服务。
              </p>
            </div>
            <div class="flex items-center gap-2">
              <span
                class="text-xs px-2 py-1 rounded-full"
                :class="hasUnsavedChanges ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'"
              >
                {{ hasUnsavedChanges ? '有未保存的更改' : '已同步' }}
              </span>
              <button
                class="text-sm text-slate-600 hover:text-slate-900"
                @click="loadSettings"
                :disabled="loading"
              >
                {{ loading ? '同步中…' : '刷新' }}
              </button>
            </div>
          </div>
        </div>

        <!-- Auth Method Info -->
        <div class="bg-slate-50 border border-slate-200 rounded-2xl p-4 text-sm text-slate-600 space-y-2">
          <p class="font-semibold text-slate-700">关于 Git 鉴权方式</p>
          <div class="grid gap-2 md:grid-cols-3">
            <div class="flex items-start gap-2">
              <span class="mt-0.5 h-2 w-2 rounded-full bg-emerald-400 shrink-0"></span>
              <div>
                <p class="font-medium">Personal Access Token（推荐）</p>
                <p class="text-xs text-slate-500 mt-0.5">适用于 GitHub/GitLab/Gitee HTTPS URL。Token 将以 <code class="bg-slate-200 px-1 rounded">oauth2:TOKEN@host</code> 形式注入 URL。</p>
              </div>
            </div>
            <div class="flex items-start gap-2">
              <span class="mt-0.5 h-2 w-2 rounded-full bg-cyan-400 shrink-0"></span>
              <div>
                <p class="font-medium">匿名访问</p>
                <p class="text-xs text-slate-500 mt-0.5">公开仓库无需 Token，直接使用 HTTPS URL 即可。</p>
              </div>
            </div>
            <div class="flex items-start gap-2">
              <span class="mt-0.5 h-2 w-2 rounded-full bg-slate-400 shrink-0"></span>
              <div>
                <p class="font-medium">SSH Key（暂不支持）</p>
                <p class="text-xs text-slate-500 mt-0.5">SSH URL（<code class="bg-slate-200 px-1 rounded">git@…</code>）需在服务器预先配置 SSH Key，Token 字段对 SSH 无效。</p>
              </div>
            </div>
          </div>
        </div>

        <!-- OAM Repo -->
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 space-y-4">
          <div>
            <div class="flex items-center gap-3">
              <span class="h-8 w-8 rounded-lg bg-blue-100 text-blue-600 flex items-center justify-center text-sm font-bold">OAM</span>
              <div>
                <h3 class="font-semibold text-slate-900 text-sm">OAM 天线模块代码仓库</h3>
                <p class="text-xs text-slate-400">对应日志类型：<code class="bg-slate-100 px-1 rounded">oam_antenna</code></p>
              </div>
            </div>
          </div>
          <div class="space-y-3">
            <label class="block">
              <span class="text-sm text-slate-700 font-medium">仓库 URL</span>
              <div class="mt-1 flex gap-2">
                <input
                  v-model="form.oam_url"
                  type="url"
                  class="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  placeholder="https://gitlab.example.com/project/oam-module.git"
                  spellcheck="false"
                />
                <button
                  class="px-3 py-2 text-sm rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap"
                  :disabled="testingOam || !form.oam_url.trim()"
                  @click="testConnection('oam')"
                >
                  {{ testingOam ? '检测中…' : '测试连接' }}
                </button>
              </div>
            </label>
            <div
              v-if="testResults.oam"
              class="flex items-start gap-2 text-sm rounded-lg px-3 py-2 border"
              :class="testResults.oam.success
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : 'bg-red-50 border-red-200 text-red-700'"
            >
              <span class="font-bold shrink-0">{{ testResults.oam.success ? '✓' : '✕' }}</span>
              <div>
                <p>{{ testResults.oam.message }}</p>
                <p class="text-xs mt-0.5 opacity-70">鉴权方式：{{ testResults.oam.auth_method }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Stack Repo -->
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 space-y-4">
          <div class="flex items-center gap-3">
            <span class="h-8 w-8 rounded-lg bg-violet-100 text-violet-600 flex items-center justify-center text-sm font-bold">STK</span>
            <div>
              <h3 class="font-semibold text-slate-900 text-sm">协议栈模块代码仓库</h3>
              <p class="text-xs text-slate-400">对应日志类型：<code class="bg-slate-100 px-1 rounded">stack</code> / <code class="bg-slate-100 px-1 rounded">full</code></p>
            </div>
          </div>
          <div class="space-y-3">
            <label class="block">
              <span class="text-sm text-slate-700 font-medium">仓库 URL</span>
              <div class="mt-1 flex gap-2">
                <input
                  v-model="form.stack_url"
                  type="url"
                  class="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  placeholder="https://gitlab.example.com/project/stack-module.git"
                  spellcheck="false"
                />
                <button
                  class="px-3 py-2 text-sm rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50 whitespace-nowrap"
                  :disabled="testingStack || !form.stack_url.trim()"
                  @click="testConnection('stack')"
                >
                  {{ testingStack ? '检测中…' : '测试连接' }}
                </button>
              </div>
            </label>
            <div
              v-if="testResults.stack"
              class="flex items-start gap-2 text-sm rounded-lg px-3 py-2 border"
              :class="testResults.stack.success
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : 'bg-red-50 border-red-200 text-red-700'"
            >
              <span class="font-bold shrink-0">{{ testResults.stack.success ? '✓' : '✕' }}</span>
              <div>
                <p>{{ testResults.stack.message }}</p>
                <p class="text-xs mt-0.5 opacity-70">鉴权方式：{{ testResults.stack.auth_method }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Auth & Clone Options -->
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5 space-y-4">
          <h3 class="font-semibold text-slate-900 text-sm">鉴权 & 克隆选项</h3>
          <p class="text-xs text-slate-500 -mt-2">Token 对两个仓库共享使用（同一 Git 服务的 Personal Access Token）。</p>

          <div class="grid gap-4 md:grid-cols-2">
            <!-- Token -->
            <div class="md:col-span-2">
              <label class="block">
                <span class="text-sm text-slate-700 font-medium">Personal Access Token</span>
                <div class="mt-1 flex gap-2 items-center">
                  <div class="relative flex-1">
                    <input
                      v-model="form.git_token"
                      type="password"
                      autocomplete="new-password"
                      class="w-full rounded-lg border px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                      :class="form.git_token === '__CLEAR__'
                        ? 'border-red-300 bg-red-50 text-red-600'
                        : 'border-slate-200'"
                      :placeholder="form.git_token === '__CLEAR__' ? '保存后将清除 Token' : tokenPlaceholder"
                      :disabled="form.git_token === '__CLEAR__'"
                    />
                    <span
                      v-if="saved.git_token_set && form.git_token === ''"
                      class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-emerald-600 font-medium pointer-events-none"
                    >已设置</span>
                  </div>
                  <button
                    v-if="saved.git_token_set && form.git_token !== '__CLEAR__'"
                    class="px-3 py-2 text-xs rounded-lg border border-red-200 text-red-600 hover:bg-red-50 whitespace-nowrap"
                    @click="handleClearToken"
                  >清除 Token</button>
                  <button
                    v-if="form.git_token === '__CLEAR__'"
                    class="px-3 py-2 text-xs rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 whitespace-nowrap"
                    @click="form.git_token = ''"
                  >撤销清除</button>
                </div>
                <p class="mt-1 text-xs text-slate-400">
                  GitLab：Settings → Access Tokens，勾选 <code class="bg-slate-100 px-1 rounded">read_repository</code>；
                  GitHub：Settings → Developer settings → Personal access tokens，勾选 <code class="bg-slate-100 px-1 rounded">repo</code>。
                </p>
              </label>
            </div>

            <!-- Clone Depth -->
            <label class="block">
              <span class="text-sm text-slate-700 font-medium">浅克隆深度（Clone Depth）</span>
              <div class="mt-1 flex items-center gap-3">
                <input
                  v-model.number="form.clone_depth"
                  type="number"
                  min="1"
                  max="100"
                  class="w-24 rounded-lg border border-slate-200 px-3 py-2 text-sm text-center focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                />
                <p class="text-xs text-slate-400">
                  <code class="bg-slate-100 px-1 rounded">1</code> = 仅克隆最新快照（最快，推荐）。数值越大历史越多，克隆越慢。
                </p>
              </div>
            </label>
          </div>
        </div>

        <!-- Save Bar -->
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 flex items-center justify-between gap-4">
          <div class="text-xs text-slate-400">
            <span v-if="saved.updated_at">上次保存：{{ new Date(saved.updated_at).toLocaleString('zh-CN', { hour12: false }) }}</span>
            <span v-else>尚未保存</span>
          </div>
          <div class="flex items-center gap-3">
            <button
              class="px-3 py-2 text-sm rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-50"
              :disabled="loading"
              @click="loadSettings"
            >重新加载</button>
            <button
              class="px-4 py-2 text-sm rounded-lg bg-cyan-600 text-white font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
              :disabled="saving || !hasUnsavedChanges"
              @click="handleSave"
            >
              {{ saving ? '保存中…' : '保存配置' }}
            </button>
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

.toast-slide-enter-active,
.toast-slide-leave-active {
  transition: all 0.25s ease;
}
.toast-slide-enter-from,
.toast-slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
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
}
</style>
