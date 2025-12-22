<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import type { PromptsConfigData, PromptsSummary } from '@/types'

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
]

const emptySummary: PromptsSummary = {
  log_type_keys: [],
  has_default_plan: false,
  has_default_summary: false,
}

const configState = reactive<PromptsConfigData>({
  path: 'app/prompts/prompts_config.yaml',
  content: '',
  updated_at: '',
  size: 0,
  checksum: '',
  summary: { ...emptySummary },
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
  if (!isAuthenticated.value) return 'bg-slate-600/70 text-slate-100 ring-1 ring-white/10'
  if (conflict.value) return 'bg-amber-100 text-amber-800 ring-1 ring-amber-200'
  if (hasUnsavedChanges.value) return 'bg-cyan-100 text-cyan-900 ring-1 ring-cyan-200'
  return 'bg-emerald-100 text-emerald-900 ring-1 ring-emerald-200'
})

const readableUpdatedAt = computed(() => {
  if (!configState.updated_at) return '尚未加载'
  return `${formatTimestamp(configState.updated_at)} (${formatRelative(configState.updated_at)})`
})

const summaryBadges = computed(() => configState.summary?.log_type_keys || [])

const activeNavKey = computed(() => (route.path.startsWith('/admin') ? 'prompts' : ''))

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
      message: `文件已更新，包含 ${resp.data.summary?.log_type_keys?.length || 0} 个日志类型模板`,
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
  <div class="space-y-6">
    <section
      class="rounded-2xl bg-gradient-to-r from-slate-900 via-slate-800 to-cyan-800 text-white shadow-xl"
    >
      <div class="p-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div class="space-y-2">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-300">Raven Admin</p>
          <h1 class="text-2xl font-semibold">管理后台</h1>
          <p class="text-sm text-slate-200">受保护的后台入口，请先登录以管理配置</p>
        </div>
        <div class="flex items-center gap-3">
          <span
            class="px-3 py-1 text-xs font-semibold rounded-full inline-flex items-center gap-2 ring-1"
            :class="statusTone"
          >
            <span class="h-2 w-2 rounded-full bg-current/60"></span>
            {{ statusLabel }}
          </span>
          <button
            class="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 text-white text-sm font-semibold border border-white/20 transition"
            :disabled="!isAuthenticated || saving"
            @click="handleSave"
          >
            {{ saving ? '保存中…' : '立即保存' }}
          </button>
        </div>
      </div>
      <div
        v-if="isAuthenticated"
        class="px-6 pb-6 grid gap-3 md:grid-cols-3 text-sm text-slate-200"
      >
        <div class="flex items-center gap-2">
          <span class="text-slate-400">当前文件</span>
          <span class="font-mono text-xs bg-white/10 px-2 py-1 rounded">
            {{ configState.path }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-slate-400">最近更新</span>
          <span>{{ readableUpdatedAt }}</span>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-slate-400">日志类型</span>
          <div class="flex gap-1 flex-wrap">
            <span
              v-for="key in summaryBadges"
              :key="key"
              class="text-xs px-2 py-1 rounded-full bg-white/10 border border-white/10"
            >
              {{ key }}
            </span>
            <span v-if="!summaryBadges.length" class="text-xs text-slate-300">尚未加载</span>
          </div>
        </div>
      </div>
    </section>

    <section v-if="!isAuthenticated" class="max-w-3xl">
      <div class="bg-white rounded-xl shadow-sm border border-slate-100 p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">登录后台</h2>
            <p class="text-sm text-slate-500">请输入管理员凭证继续</p>
          </div>
          <span class="text-xs text-slate-500">内部安全访问</span>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="space-y-4">
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
            <div class="flex items-center gap-3">
              <button
                class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
                :disabled="isLoggingIn"
                @click="handleLogin"
              >
                {{ isLoggingIn ? '登录中…' : '登录' }}
              </button>
              <p class="text-xs text-slate-500">
                凭证在 admin_auth.yaml 配置，建议登录后立即更改
              </p>
            </div>
          </div>
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
            <div
              class="rounded-lg border border-dashed border-slate-200 p-3 text-xs text-slate-500 leading-5"
            >
              提示：token 默认保存在 sessionStorage，退出或关闭标签页后会被清理。可在
              admin_auth.yaml 中禁用或调整账号。
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-else class="grid gap-6 lg:grid-cols-[240px,1fr]">
      <aside class="bg-white rounded-xl shadow-sm border border-slate-100 p-4 space-y-4">
        <div>
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">管理导航</p>
          <h2 class="text-lg font-semibold text-slate-900">后台</h2>
        </div>
        <nav class="space-y-2">
          <button
            v-for="item in navItems"
            :key="item.key"
            class="w-full text-left px-3 py-2 rounded-lg border transition"
            :class="
              activeNavKey === item.key
                ? 'border-cyan-200 bg-cyan-50 text-cyan-800 shadow-[0_6px_30px_-16px_rgba(14,165,233,0.5)]'
                : 'border-slate-200 hover:bg-slate-50 text-slate-700'
            "
            @click="handleNavClick(item)"
          >
            <div class="flex items-center justify-between">
              <span class="text-sm font-semibold">{{ item.label }}</span>
              <span
                v-if="activeNavKey === item.key"
                class="text-[11px] font-medium text-cyan-700"
              >
                当前
              </span>
            </div>
            <p v-if="item.description" class="text-xs text-slate-500 mt-1">
              {{ item.description }}
            </p>
          </button>
        </nav>
        <div class="pt-3 border-t border-slate-100">
          <div class="flex items-center justify-between">
            <span class="text-xs text-slate-500">{{ statusLabel }}</span>
            <button class="text-xs text-slate-600 hover:text-slate-900" @click="handleLogout">
              退出
            </button>
          </div>
        </div>
      </aside>

      <div class="space-y-6">
        <div class="grid gap-6 lg:grid-cols-3">
          <div class="lg:col-span-2 space-y-4">
            <div class="bg-white rounded-xl shadow-sm border border-slate-100 p-4">
              <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-3">
                <div>
                  <h2 class="text-lg font-semibold text-slate-900">prompts_config.yaml</h2>
                  <p class="text-sm text-slate-500">
                    输入框内即为磁盘内容，保存后立即刷新 Agent 缓存；Ctrl/Cmd + S 可快速保存
                  </p>
                </div>
                <div class="flex items-center gap-2">
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
              <div class="rounded-lg border border-slate-200 bg-slate-50 overflow-hidden">
                <textarea
                  v-model="configState.content"
                  class="w-full h-[520px] resize-none bg-white font-mono text-xs text-slate-800 p-4 focus:outline-none"
                  spellcheck="false"
                  :disabled="loadingConfig"
                ></textarea>
              </div>
              <div class="flex items-center justify-between text-xs text-slate-500 mt-2">
                <div class="flex items-center gap-3">
                  <span>长度：{{ configState.content.length }} 字符</span>
                  <span
                    :class="hasUnsavedChanges ? 'text-amber-600' : 'text-emerald-600'"
                  >{{ hasUnsavedChanges ? '有未保存的修改' : '已与磁盘同步' }}</span>
                  <span v-if="conflict" class="text-amber-700 font-semibold">
                    {{ conflictMessage || '文件在其他位置被更新' }}
                  </span>
                </div>
                <div class="flex items-center gap-2">
                  <span class="px-2 py-1 rounded bg-slate-100 border border-slate-200">
                    {{ readableUpdatedAt }}
                  </span>
                  <span class="px-2 py-1 rounded bg-slate-100 border border-slate-200">
                    校验和：{{ lastChecksum || configState.checksum }}
                  </span>
                </div>
              </div>
            </div>

            <div class="grid gap-4 md:grid-cols-2">
              <div class="bg-white rounded-xl shadow-sm border border-slate-100 p-4 space-y-3">
                <div class="flex items-center justify-between">
                  <h3 class="text-base font-semibold text-slate-900">模板摘要</h3>
                  <span class="text-xs text-slate-500">
                    默认计划模板：{{ configState.summary?.has_default_plan ? '已配置' : '缺失' }} /
                    摘要模板：{{ configState.summary?.has_default_summary ? '已配置' : '缺失' }}
                  </span>
                </div>
                <div class="flex flex-wrap gap-2">
                  <span
                    v-for="key in summaryBadges"
                    :key="key"
                    class="px-3 py-1 rounded-full bg-cyan-50 text-cyan-800 text-xs border border-cyan-100"
                  >
                    {{ key }}
                  </span>
                  <span v-if="!summaryBadges.length" class="text-sm text-slate-500">
                    暂无日志类型，保存后会实时解析摘要
                  </span>
                </div>
                <p class="text-xs text-slate-500 leading-5">
                  修改后保存即可刷新 Agent 的缓存；如果新增日志类型，请确保包含 plan_prompt 与 summary_prompt 字段。
                </p>
              </div>

              <div class="bg-white rounded-xl shadow-sm border border-slate-100 p-4 space-y-3">
                <div class="flex items-center justify-between">
                  <h3 class="text-base font-semibold text-slate-900">变更与安全</h3>
                  <button class="text-xs text-cyan-700 hover:underline" @click="handleReload">
                    检查磁盘版本
                  </button>
                </div>
                <ul class="space-y-2 text-sm text-slate-700">
                  <li class="flex items-center gap-2">
                    <span class="h-2 w-2 rounded-full bg-emerald-500"></span>
                    保存前会做 YAML 语法校验
                  </li>
                  <li class="flex items-center gap-2">
                    <span class="h-2 w-2 rounded-full bg-amber-500"></span>
                    检测到磁盘版本变化会提示强制保存
                  </li>
                  <li class="flex items-center gap-2">
                    <span class="h-2 w-2 rounded-full bg-slate-400"></span>
                    快捷键：Ctrl / Cmd + S 立即保存
                  </li>
                </ul>
                <div class="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                  提示：强制保存会覆盖磁盘版本，请确认无并发编辑后再使用。保存完成后 Agent 立即读取新模板，无需重启。
                </div>
              </div>
            </div>
          </div>

          <div class="space-y-4">
            <div class="bg-white rounded-xl shadow-sm border border-slate-100 p-4 space-y-3">
              <div class="flex items-center justify-between">
                <h3 class="text-base font-semibold text-slate-900">文件信息</h3>
                <button class="text-xs text-slate-500 hover:text-slate-700" @click="handleLogout">
                  退出
                </button>
              </div>
              <div class="space-y-2 text-sm text-slate-700">
                <div class="flex justify-between">
                  <span class="text-slate-500">路径</span>
                  <span class="font-mono text-xs text-slate-800">{{ configState.path }}</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-slate-500">大小</span>
                  <span>{{ formatBytes(configState.size) }}</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-slate-500">最近更新</span>
                  <span>{{ readableUpdatedAt }}</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-slate-500">校验和</span>
                  <span class="font-mono text-[11px] text-slate-600 break-all">
                    {{ configState.checksum }}
                  </span>
                </div>
              </div>
              <div class="flex gap-2">
                <button
                  class="flex-1 px-3 py-2 rounded-lg text-sm border border-slate-200 hover:bg-slate-50"
                  @click="handleReload"
                >
                  从磁盘刷新
                </button>
                <button
                  class="flex-1 px-3 py-2 rounded-lg text-sm border border-slate-200 text-amber-700 bg-amber-50 hover:bg-amber-100"
                  :disabled="saving"
                  @click="handleSave(true)"
                >
                  覆盖保存
                </button>
              </div>
            </div>

            <div class="bg-white rounded-xl shadow-sm border border-slate-100 p-4 space-y-3">
              <h3 class="text-base font-semibold text-slate-900">使用提示</h3>
              <ul class="list-disc pl-5 space-y-2 text-sm text-slate-700">
                <li>建议先复制一份内容备份再修改</li>
                <li>保持 YAML 缩进，避免混用 Tab</li>
                <li>新增日志类型时，务必提供描述与变量列表</li>
                <li>完成后可在日志分析 Agent 直接验证新模板</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
