<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Menu, PanelLeftClose, RefreshCw, X } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import type {
  MetricsRawEvent,
  MetricsSystemOverview,
  MetricsUserDetail,
  MetricsUserRow,
} from '@/types'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = adminNavItems

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)

const authForm = reactive({ username: '', password: '' })

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))

// ==================== Controls ====================

type RangePreset = '24h' | '7d' | '30d'
type Bucket = 'hour' | 'day'

const rangePreset = ref<RangePreset>('7d')
const bucket = ref<Bucket>('day')

const rangePresets: { key: RangePreset; label: string }[] = [
  { key: '24h', label: '近 24 小时' },
  { key: '7d', label: '近 7 天' },
  { key: '30d', label: '近 30 天' },
]

const computeRange = (): { from: string; to: string } => {
  const to = new Date()
  const from = new Date(to)
  if (rangePreset.value === '24h') from.setHours(from.getHours() - 24)
  else if (rangePreset.value === '30d') from.setDate(from.getDate() - 30)
  else from.setDate(from.getDate() - 7)
  return { from: from.toISOString(), to: to.toISOString() }
}

// ==================== Data state ====================

const loadingOverview = ref(false)
const overview = ref<MetricsSystemOverview | null>(null)

const loadingUsers = ref(false)
const users = ref<MetricsUserRow[]>([])
const userTotal = ref(0)
const userPage = ref(1)
const userPerPage = 20
const userSort = ref('total_tokens')

const detailVisible = ref(false)
const loadingDetail = ref(false)
const detail = ref<MetricsUserDetail | null>(null)

const loadingEvents = ref(false)
const events = ref<MetricsRawEvent[]>([])
const eventsTotal = ref(0)
const eventsPage = ref(1)
const eventsPerPage = 50
const eventSourceFilter = ref('')

// ==================== Helpers ====================

const parseErrorMessage = (err: any) => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
}

const formatTimestamp = (value?: string | null) => {
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

const formatNumber = (value?: number | null) => {
  if (value === null || value === undefined) return '0'
  return value.toLocaleString('en-US')
}

const formatBytes = (value?: number | null) => {
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = value
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`
}

const formatCost = (overviewOrDetail: { estimated_cost_usd: number | null; cost_estimated: boolean } | null) => {
  if (!overviewOrDetail || !overviewOrDetail.cost_estimated || overviewOrDetail.estimated_cost_usd === null) {
    return '未配置价格'
  }
  return `$${overviewOrDetail.estimated_cost_usd.toFixed(4)}`
}

const formatBucketLabel = (value: string) => {
  if (!value) return '--'
  try {
    const d = new Date(value)
    if (bucket.value === 'hour') {
      return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', hour12: false })
    }
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  } catch {
    return value
  }
}

const objToPairs = (obj?: Record<string, number> | null) =>
  Object.entries(obj || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])

const maxSeriesTokens = computed(() => {
  const series = overview.value?.time_series || []
  return series.reduce((m, b) => Math.max(m, b.total_tokens), 0) || 1
})

// ==================== Loaders ====================

const loadOverview = async () => {
  if (!isAuthenticated.value) return
  loadingOverview.value = true
  try {
    const { from, to } = computeRange()
    const resp = await adminApi.metricsOverview({ from, to, bucket: bucket.value })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '加载概览失败')
    overview.value = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingOverview.value = false
  }
}

const loadUsers = async () => {
  if (!isAuthenticated.value) return
  loadingUsers.value = true
  try {
    const { from, to } = computeRange()
    const resp = await adminApi.metricsUsers({
      from,
      to,
      page: userPage.value,
      per_page: userPerPage,
      sort: userSort.value,
    })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '加载用户列表失败')
    users.value = resp.data.rows
    userTotal.value = resp.data.total
    userPage.value = resp.data.page
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingUsers.value = false
  }
}

const loadEvents = async () => {
  if (!isAuthenticated.value) return
  loadingEvents.value = true
  try {
    const { from, to } = computeRange()
    const resp = await adminApi.metricsEvents({
      from,
      to,
      source: eventSourceFilter.value || undefined,
      page: eventsPage.value,
      per_page: eventsPerPage,
    })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '加载事件失败')
    events.value = resp.data.events
    eventsTotal.value = resp.data.total
    eventsPage.value = resp.data.page
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingEvents.value = false
  }
}

const openUserDetail = async (row: MetricsUserRow) => {
  detailVisible.value = true
  loadingDetail.value = true
  detail.value = null
  try {
    const { from, to } = computeRange()
    const resp = await adminApi.metricsUserDetail(row.user_id, { from, to, bucket: bucket.value })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '加载用户详情失败')
    detail.value = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
    detailVisible.value = false
  } finally {
    loadingDetail.value = false
  }
}

const closeDetail = () => {
  detailVisible.value = false
  detail.value = null
}

const refreshAll = async () => {
  userPage.value = 1
  eventsPage.value = 1
  await Promise.all([loadOverview(), loadUsers(), loadEvents()])
}

const applyRange = async (preset: RangePreset) => {
  rangePreset.value = preset
  await refreshAll()
}

const applyBucket = async (value: Bucket) => {
  bucket.value = value
  await loadOverview()
}

const changeSort = async (sort: string) => {
  userSort.value = sort
  userPage.value = 1
  await loadUsers()
}

const userPageCount = computed(() => Math.max(1, Math.ceil(userTotal.value / userPerPage)))
const eventsPageCount = computed(() => Math.max(1, Math.ceil(eventsTotal.value / eventsPerPage)))

const gotoUserPage = async (page: number) => {
  if (page < 1 || page > userPageCount.value) return
  userPage.value = page
  await loadUsers()
}

const gotoEventsPage = async (page: number) => {
  if (page < 1 || page > eventsPageCount.value) return
  eventsPage.value = page
  await loadEvents()
}

const applyEventFilter = async () => {
  eventsPage.value = 1
  await loadEvents()
}

// ==================== Auth ====================

const handleNavClick = (item: (typeof navItems)[number]) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => appStore.toggleAdminSidebar()

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({ title: '请输入用户名和密码', type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '登录失败')
    adminToken.set(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: '登录成功', message: `欢迎，${resp.data.username}`, type: 'success' })
    await refreshAll()
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
    overview.value = null
    users.value = []
    events.value = []
    appStore.showNotification({ title: '已退出登录', type: 'info' })
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await refreshAll()
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
  <div class="admin-console admin-metrics-page">
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
            <p class="admin-subtitle">数据指标看板</p>
          </div>
        </div>
        <div class="admin-topbar-right">
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
    ></button>

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
      <!-- Login gate -->
      <section v-if="!isAuthenticated" class="admin-login-wrap">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">登录后台</h2>
              <p class="text-sm text-slate-500">请输入管理员凭证查看数据指标</p>
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
        <!-- Controls -->
        <div class="metrics-toolbar">
          <div class="metrics-control-group">
            <span class="metrics-control-label">时间范围</span>
            <div class="metrics-segment">
              <button
                v-for="preset in rangePresets"
                :key="preset.key"
                class="metrics-segment-btn"
                :class="{ 'is-active': rangePreset === preset.key }"
                @click="applyRange(preset.key)"
              >
                {{ preset.label }}
              </button>
            </div>
          </div>
          <div class="metrics-control-group">
            <span class="metrics-control-label">粒度</span>
            <div class="metrics-segment">
              <button class="metrics-segment-btn" :class="{ 'is-active': bucket === 'hour' }" @click="applyBucket('hour')">小时</button>
              <button class="metrics-segment-btn" :class="{ 'is-active': bucket === 'day' }" @click="applyBucket('day')">天</button>
            </div>
          </div>
          <button class="metrics-refresh-btn" :disabled="loadingOverview" @click="refreshAll">
            <RefreshCw :size="14" :class="{ 'animate-spin': loadingOverview }" />
            <span>刷新</span>
          </button>
        </div>

        <!-- KPI cards -->
        <div class="metrics-kpi-grid">
          <div class="metrics-card metrics-kpi">
            <span class="metrics-kpi-label">总 Token</span>
            <span class="metrics-kpi-value">{{ formatNumber(overview?.tokens.total_tokens) }}</span>
            <span class="metrics-kpi-sub">
              输入 {{ formatNumber(overview?.tokens.input_tokens) }} · 输出 {{ formatNumber(overview?.tokens.output_tokens) }}
            </span>
          </div>
          <div class="metrics-card metrics-kpi">
            <span class="metrics-kpi-label">调用次数</span>
            <span class="metrics-kpi-value">{{ formatNumber(overview?.invocation_count) }}</span>
            <span class="metrics-kpi-sub">
              成功 {{ formatNumber(overview?.status_counts.succeeded) }} · 失败 {{ formatNumber(overview?.status_counts.failed) }}
            </span>
          </div>
          <div class="metrics-card metrics-kpi">
            <span class="metrics-kpi-label">估算成本</span>
            <span class="metrics-kpi-value">{{ formatCost(overview) }}</span>
            <span class="metrics-kpi-sub">缓存读 {{ formatNumber(overview?.tokens.cache_read_tokens) }}</span>
          </div>
          <div class="metrics-card metrics-kpi">
            <span class="metrics-kpi-label">耗时 (ms)</span>
            <span class="metrics-kpi-value">{{ overview?.duration_ms_avg ? Math.round(overview.duration_ms_avg) : '--' }}</span>
            <span class="metrics-kpi-sub">P95 {{ overview?.duration_ms_p95 ? Math.round(overview.duration_ms_p95) : '--' }} · 错误 {{ formatNumber(overview?.error_count) }}</span>
          </div>
        </div>

        <!-- Time series -->
        <div class="metrics-card">
          <h3 class="metrics-card-title">Token 时间序列</h3>
          <div v-if="!overview || !overview.time_series.length" class="metrics-empty">暂无数据</div>
          <div v-else class="metrics-chart">
            <div
              v-for="(b, i) in overview.time_series"
              :key="i"
              class="metrics-bar-col"
              :title="`${formatBucketLabel(b.bucket_start)}\nToken: ${formatNumber(b.total_tokens)}\n调用: ${formatNumber(b.invocation_count)}`"
            >
              <div class="metrics-bar-track">
                <div
                  class="metrics-bar-fill"
                  :style="{ height: `${Math.max(2, (b.total_tokens / maxSeriesTokens) * 100)}%` }"
                ></div>
              </div>
              <span class="metrics-bar-label">{{ formatBucketLabel(b.bucket_start) }}</span>
            </div>
          </div>
        </div>

        <!-- Distributions -->
        <div class="metrics-two-col">
          <div class="metrics-card">
            <h3 class="metrics-card-title">按来源 (Source)</h3>
            <table class="metrics-mini-table">
              <thead><tr><th>Source</th><th class="text-right">调用</th><th class="text-right">Token</th></tr></thead>
              <tbody>
                <tr v-for="g in overview?.invocations_by_source || []" :key="g.key || 'unknown'">
                  <td>{{ g.key || '未知' }}</td>
                  <td class="text-right">{{ formatNumber(g.invocation_count) }}</td>
                  <td class="text-right">{{ formatNumber(g.total_tokens) }}</td>
                </tr>
                <tr v-if="!overview?.invocations_by_source?.length"><td colspan="3" class="metrics-empty">暂无数据</td></tr>
              </tbody>
            </table>
          </div>
          <div class="metrics-card">
            <h3 class="metrics-card-title">按模型 (Model)</h3>
            <table class="metrics-mini-table">
              <thead><tr><th>Model</th><th class="text-right">调用</th><th class="text-right">Token</th></tr></thead>
              <tbody>
                <tr v-for="g in overview?.invocations_by_model || []" :key="g.key || 'unknown'">
                  <td>{{ g.key || '未知' }}</td>
                  <td class="text-right">{{ formatNumber(g.invocation_count) }}</td>
                  <td class="text-right">{{ formatNumber(g.total_tokens) }}</td>
                </tr>
                <tr v-if="!overview?.invocations_by_model?.length"><td colspan="3" class="metrics-empty">暂无数据</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Business summaries -->
        <div class="metrics-biz-grid">
          <div class="metrics-card">
            <h3 class="metrics-card-title">聊天 / 用户</h3>
            <ul class="metrics-stat-list">
              <li><span>总用户</span><b>{{ formatNumber(overview?.chat.total_users) }}</b></li>
              <li><span>活跃用户</span><b>{{ formatNumber(overview?.chat.active_users) }}</b></li>
              <li><span>会话数</span><b>{{ formatNumber(overview?.chat.chat_session_count) }}</b></li>
              <li><span>消息数</span><b>{{ formatNumber(overview?.chat.chat_message_count) }}</b></li>
            </ul>
          </div>
          <div class="metrics-card">
            <h3 class="metrics-card-title">日志</h3>
            <ul class="metrics-stat-list">
              <li><span>上传数</span><b>{{ formatNumber(overview?.logs.upload_count) }}</b></li>
              <li><span>上传字节</span><b>{{ formatBytes(overview?.logs.uploaded_bytes) }}</b></li>
              <li v-for="[k, v] in objToPairs(overview?.logs.ai_analysis_counts)" :key="k">
                <span>AI 分析 · {{ k }}</span><b>{{ formatNumber(v) }}</b>
              </li>
            </ul>
          </div>
          <div class="metrics-card">
            <h3 class="metrics-card-title">软件包</h3>
            <ul class="metrics-stat-list">
              <li><span>包总数</span><b>{{ formatNumber(overview?.packages.package_count) }}</b></li>
              <li><span>总大小</span><b>{{ formatBytes(overview?.packages.total_bytes) }}</b></li>
              <li><span>搜索次数</span><b>{{ formatNumber(overview?.packages.search_count) }}</b></li>
            </ul>
          </div>
          <div class="metrics-card">
            <h3 class="metrics-card-title">设备连接</h3>
            <ul class="metrics-stat-list">
              <li v-for="[k, v] in objToPairs(overview?.devices.counts_by_state)" :key="k">
                <span>{{ k }}</span><b>{{ formatNumber(v) }}</b>
              </li>
              <li v-if="!objToPairs(overview?.devices.counts_by_state).length" class="metrics-empty-li">暂无连接</li>
            </ul>
          </div>
        </div>

        <!-- User ranking -->
        <div class="metrics-card">
          <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h3 class="metrics-card-title mb-0">用户用量排名</h3>
            <div class="flex items-center gap-2">
              <span class="text-xs text-slate-500">排序：</span>
              <div class="metrics-segment">
                <button class="metrics-segment-btn" :class="{ 'is-active': userSort === 'total_tokens' }" @click="changeSort('total_tokens')">Token</button>
                <button class="metrics-segment-btn" :class="{ 'is-active': userSort === 'run_count' }" @click="changeSort('run_count')">调用数</button>
              </div>
            </div>
          </div>
          <div v-if="loadingUsers" class="metrics-empty">加载中…</div>
          <div v-else-if="!users.length" class="metrics-empty">暂无用户用量数据</div>
          <div v-else class="overflow-x-auto">
            <table class="metrics-table">
              <thead>
                <tr>
                  <th>用户</th>
                  <th class="text-right">总 Token</th>
                  <th class="text-right">输入</th>
                  <th class="text-right">输出</th>
                  <th class="text-right">调用</th>
                  <th class="text-right">成功/失败</th>
                  <th>最近活跃</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in users" :key="row.user_id" class="metrics-row" @click="openUserDetail(row)">
                  <td>
                    <div class="font-medium text-slate-900">{{ row.display_name || row.username || row.user_id }}</div>
                    <div class="text-xs text-slate-400">{{ row.username || row.user_id }}</div>
                  </td>
                  <td class="text-right font-semibold">{{ formatNumber(row.total_tokens) }}</td>
                  <td class="text-right">{{ formatNumber(row.input_tokens) }}</td>
                  <td class="text-right">{{ formatNumber(row.output_tokens) }}</td>
                  <td class="text-right">{{ formatNumber(row.run_count) }}</td>
                  <td class="text-right">{{ formatNumber(row.success_count) }} / {{ formatNumber(row.failure_count) }}</td>
                  <td class="text-slate-500 text-xs">{{ formatTimestamp(row.last_active_at) }}</td>
                  <td class="text-right"><span class="metrics-link">详情</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="userTotal > userPerPage" class="metrics-pager">
            <button :disabled="userPage <= 1" @click="gotoUserPage(userPage - 1)">上一页</button>
            <span>{{ userPage }} / {{ userPageCount }}</span>
            <button :disabled="userPage >= userPageCount" @click="gotoUserPage(userPage + 1)">下一页</button>
          </div>
        </div>

        <!-- Raw events -->
        <div class="metrics-card">
          <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
            <h3 class="metrics-card-title mb-0">原始事件（已脱敏）</h3>
            <div class="flex items-center gap-2">
              <input
                v-model="eventSourceFilter"
                type="text"
                placeholder="按 source 过滤，如 device_agent"
                class="rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                @keyup.enter="applyEventFilter"
              />
              <button class="metrics-mini-btn" @click="applyEventFilter">过滤</button>
            </div>
          </div>
          <div v-if="loadingEvents" class="metrics-empty">加载中…</div>
          <div v-else-if="!events.length" class="metrics-empty">暂无事件</div>
          <div v-else class="overflow-x-auto">
            <table class="metrics-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>类型</th>
                  <th>Source</th>
                  <th>Model</th>
                  <th>状态</th>
                  <th class="text-right">Token</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="ev in events" :key="ev.id">
                  <td class="text-xs text-slate-500">{{ formatTimestamp(ev.occurred_at) }}</td>
                  <td class="text-xs">{{ ev.event_type }}</td>
                  <td class="text-xs">{{ ev.source }}</td>
                  <td class="text-xs">{{ ev.model || '--' }}</td>
                  <td><span class="metrics-status" :class="`is-${ev.status || 'unknown'}`">{{ ev.status || '--' }}</span></td>
                  <td class="text-right">{{ formatNumber(ev.total_tokens) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="eventsTotal > eventsPerPage" class="metrics-pager">
            <button :disabled="eventsPage <= 1" @click="gotoEventsPage(eventsPage - 1)">上一页</button>
            <span>{{ eventsPage }} / {{ eventsPageCount }}</span>
            <button :disabled="eventsPage >= eventsPageCount" @click="gotoEventsPage(eventsPage + 1)">下一页</button>
          </div>
        </div>
      </section>
    </main>

    <!-- User detail drawer -->
    <div v-if="detailVisible" class="admin-modal-backdrop" @click="closeDetail">
      <div class="metrics-drawer" @click.stop>
        <div class="flex items-center justify-between mb-4">
          <div>
            <h3 class="text-base font-semibold text-slate-900">
              {{ detail?.display_name || detail?.username || detail?.user_id || '用户详情' }}
            </h3>
            <p class="text-xs text-slate-400">{{ detail?.username || detail?.user_id }}</p>
          </div>
          <button class="admin-icon-btn !text-slate-600 !bg-slate-100 !border-slate-200" @click="closeDetail"><X :size="16" /></button>
        </div>

        <div v-if="loadingDetail" class="metrics-empty">加载中…</div>
        <div v-else-if="detail" class="space-y-4">
          <div class="metrics-kpi-grid">
            <div class="metrics-card metrics-kpi">
              <span class="metrics-kpi-label">总 Token</span>
              <span class="metrics-kpi-value">{{ formatNumber(detail.tokens.total_tokens) }}</span>
            </div>
            <div class="metrics-card metrics-kpi">
              <span class="metrics-kpi-label">调用</span>
              <span class="metrics-kpi-value">{{ formatNumber(detail.invocation_count) }}</span>
            </div>
            <div class="metrics-card metrics-kpi">
              <span class="metrics-kpi-label">成功/失败</span>
              <span class="metrics-kpi-value">{{ formatNumber(detail.status_counts.succeeded) }}/{{ formatNumber(detail.status_counts.failed) }}</span>
            </div>
            <div class="metrics-card metrics-kpi">
              <span class="metrics-kpi-label">估算成本</span>
              <span class="metrics-kpi-value">{{ formatCost(detail) }}</span>
            </div>
          </div>

          <div class="metrics-card">
            <h3 class="metrics-card-title">按 Agent 类型</h3>
            <table class="metrics-mini-table">
              <thead><tr><th>Agent</th><th class="text-right">调用</th><th class="text-right">Token</th></tr></thead>
              <tbody>
                <tr v-for="g in detail.invocations_by_agent_kind" :key="g.key || 'unknown'">
                  <td>{{ g.key || '未知' }}</td>
                  <td class="text-right">{{ formatNumber(g.invocation_count) }}</td>
                  <td class="text-right">{{ formatNumber(g.total_tokens) }}</td>
                </tr>
                <tr v-if="!detail.invocations_by_agent_kind.length"><td colspan="3" class="metrics-empty">暂无数据</td></tr>
              </tbody>
            </table>
          </div>

          <div v-if="detail.errors_by_kind.length" class="metrics-card">
            <h3 class="metrics-card-title">错误分类</h3>
            <table class="metrics-mini-table">
              <thead><tr><th>错误类型</th><th class="text-right">次数</th></tr></thead>
              <tbody>
                <tr v-for="g in detail.errors_by_kind" :key="g.key || 'unknown'">
                  <td>{{ g.key || '未知' }}</td>
                  <td class="text-right">{{ formatNumber(g.invocation_count) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="metrics-card">
            <h3 class="metrics-card-title">最近事件</h3>
            <div v-if="!detail.recent_events.length" class="metrics-empty">暂无事件</div>
            <table v-else class="metrics-mini-table">
              <thead><tr><th>时间</th><th>Source</th><th>状态</th><th class="text-right">Token</th></tr></thead>
              <tbody>
                <tr v-for="ev in detail.recent_events" :key="ev.id">
                  <td class="text-xs text-slate-500">{{ formatTimestamp(ev.occurred_at) }}</td>
                  <td class="text-xs">{{ ev.source }}</td>
                  <td><span class="metrics-status" :class="`is-${ev.status || 'unknown'}`">{{ ev.status || '--' }}</span></td>
                  <td class="text-right">{{ formatNumber(ev.total_tokens) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
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
  max-width: 960px;
  margin: 1.25rem auto 0;
}

.admin-sidebar-backdrop {
  display: none;
}

.admin-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(2, 6, 23, 0.5);
  display: flex;
  align-items: stretch;
  justify-content: flex-end;
  padding: 0;
}

/* ==================== Metrics-specific ==================== */

.metrics-toolbar {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  flex-wrap: wrap;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  padding: 0.75rem 1rem;
}

.metrics-control-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.metrics-control-label {
  font-size: 0.75rem;
  color: #64748b;
  font-weight: 600;
}

.metrics-segment {
  display: inline-flex;
  border: 1px solid #cbd5e1;
  border-radius: 0.6rem;
  overflow: hidden;
}

.metrics-segment-btn {
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  color: #475569;
  background: #f8fafc;
  border-left: 1px solid #e2e8f0;
}

.metrics-segment-btn:first-child {
  border-left: none;
}

.metrics-segment-btn.is-active {
  background: #0891b2;
  color: #ffffff;
}

.metrics-refresh-btn {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.85rem;
  border-radius: 0.6rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  font-size: 0.8rem;
  color: #334155;
}

.metrics-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 1rem;
  padding: 1rem 1.1rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.metrics-card-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 0.75rem;
}

.metrics-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.85rem;
}

.metrics-kpi {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.metrics-kpi-label {
  font-size: 0.75rem;
  color: #64748b;
}

.metrics-kpi-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.metrics-kpi-sub {
  font-size: 0.72rem;
  color: #94a3b8;
}

.metrics-chart {
  display: flex;
  align-items: flex-end;
  gap: 0.35rem;
  height: 180px;
  overflow-x: auto;
  padding-top: 0.5rem;
}

.metrics-bar-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  min-width: 28px;
  flex: 1;
  height: 100%;
}

.metrics-bar-track {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  max-width: 36px;
}

.metrics-bar-fill {
  width: 100%;
  background: linear-gradient(180deg, #22d3ee 0%, #0891b2 100%);
  border-radius: 0.35rem 0.35rem 0 0;
  min-height: 2px;
}

.metrics-bar-label {
  font-size: 0.62rem;
  color: #94a3b8;
  white-space: nowrap;
  transform: rotate(-30deg);
  transform-origin: center;
}

.metrics-two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
}

.metrics-biz-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.85rem;
}

.metrics-stat-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.metrics-stat-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.82rem;
  color: #475569;
}

.metrics-stat-list b {
  color: #0f172a;
  font-weight: 600;
}

.metrics-empty,
.metrics-empty-li {
  color: #94a3b8;
  font-size: 0.85rem;
  text-align: center;
  padding: 1rem 0;
}

.metrics-mini-table,
.metrics-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  color: #334155;
}

.metrics-mini-table th,
.metrics-table th {
  text-align: left;
  font-weight: 600;
  color: #64748b;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid #e2e8f0;
  font-size: 0.75rem;
}

.metrics-mini-table td,
.metrics-table td {
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid #f1f5f9;
}

.text-right {
  text-align: right;
}

.metrics-row {
  cursor: pointer;
}

.metrics-row:hover {
  background: #f8fafc;
}

.metrics-link {
  color: #0891b2;
  font-size: 0.78rem;
  font-weight: 600;
}

.metrics-status {
  display: inline-block;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  background: #f1f5f9;
  color: #64748b;
}

.metrics-status.is-succeeded {
  background: #dcfce7;
  color: #15803d;
}

.metrics-status.is-failed,
.metrics-status.is-timeout {
  background: #fee2e2;
  color: #b91c1c;
}

.metrics-status.is-cancelled,
.metrics-status.is-stale {
  background: #fef3c7;
  color: #b45309;
}

.metrics-pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 0.85rem;
  font-size: 0.8rem;
  color: #64748b;
}

.metrics-pager button {
  padding: 0.3rem 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
}

.metrics-pager button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.metrics-mini-btn {
  padding: 0.35rem 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid #0891b2;
  color: #0891b2;
  background: #ffffff;
  font-size: 0.8rem;
}

.metrics-drawer {
  width: min(640px, 100%);
  height: 100vh;
  background: #f8fafc;
  box-shadow: -20px 0 45px rgba(15, 23, 42, 0.25);
  padding: 1.25rem;
  overflow-y: auto;
}

@media (max-width: 1024px) {
  .metrics-kpi-grid,
  .metrics-biz-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metrics-two-col {
    grid-template-columns: minmax(0, 1fr);
  }
  .admin-topbar-inner {
    padding: 0 0.75rem;
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
  .metrics-kpi-grid,
  .metrics-biz-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
