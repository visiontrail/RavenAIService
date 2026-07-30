<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Database,
  LoaderCircle,
  Radio,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-vue-next'
import { api } from '@/api'
import type {
  ProbeListData,
  ProbeRangeFilter,
  ProbeRun,
  ProbeSourceFilter,
  ProbeStatusFilter,
} from '@/types'

const emit = defineEmits<{ backDashboard: [] }>()

const rangeFilter = ref<ProbeRangeFilter>('all')
const statusFilter = ref<ProbeStatusFilter>('all')
const sourceFilter = ref<ProbeSourceFilter>('all')
const pageSize = ref(50)
const page = ref(1)
const loading = ref(true)
const error = ref('')
const data = ref<ProbeListData | null>(null)
const expanded = ref<number | null>(null)
const purgeOpen = ref(false)
const purging = ref(false)
const purgeError = ref('')
const purgeNotice = ref('')

const rangeOptions: { value: ProbeRangeFilter; label: string }[] = [
  { value: '24h', label: '24 小时' },
  { value: '7d', label: '7 天' },
  { value: '30d', label: '30 天' },
  { value: 'all', label: '全部' },
]

const exportQuery = computed(() =>
  new URLSearchParams({
    range: rangeFilter.value,
    status: statusFilter.value,
    source: sourceFilter.value,
  }).toString(),
)

const filtersActive = computed(
  () =>
    rangeFilter.value !== 'all' ||
    statusFilter.value !== 'all' ||
    sourceFilter.value !== 'all',
)

const purgeScope = computed(() => {
  if (!data.value) return '数据库中的全部探测记录'
  if (filtersActive.value) {
    return `数据库中的全部探测记录（不只是当前筛选出的 ${formatNumber(data.value.total)} 条）`
  }
  if (!data.value.total) return '数据库中的全部探测记录（当前已无记录）'
  return `数据库中的全部 ${formatNumber(data.value.total)} 条探测记录`
})

const rangeStart = computed(() => {
  if (!data.value || !data.value.total) return 0
  return (data.value.page - 1) * data.value.page_size + 1
})
const rangeEnd = computed(() => {
  if (!data.value) return 0
  return Math.min(data.value.total, data.value.page * data.value.page_size)
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const response = await api.probes({
      page: page.value,
      page_size: pageSize.value,
      status: statusFilter.value,
      source: sourceFilter.value,
      range: rangeFilter.value,
    })
    data.value = response.data
    error.value = ''
    if (data.value && page.value > data.value.pages) {
      page.value = data.value.pages
      return
    }
  } catch (err: any) {
    error.value = err.message || '无法读取探测记录'
  } finally {
    loading.value = false
  }
}

function openPurge() {
  purgeError.value = ''
  purgeNotice.value = ''
  purgeOpen.value = true
}

function closePurge() {
  if (purging.value) return
  purgeOpen.value = false
}

async function purgeAll() {
  purging.value = true
  purgeError.value = ''
  try {
    const response = await api.purgeProbes()
    const deleted = Number(response.data?.deleted ?? 0)
    purgeOpen.value = false
    purgeNotice.value = `已清空全部探测数据，共删除 ${formatNumber(deleted)} 条记录。`
    expanded.value = null
    if (page.value !== 1) {
      page.value = 1
    } else {
      await load()
    }
  } catch (err: any) {
    purgeError.value = err.message || '清空数据失败'
  } finally {
    purging.value = false
  }
}

function resetFilters() {
  rangeFilter.value = 'all'
  statusFilter.value = 'all'
  sourceFilter.value = 'all'
  pageSize.value = 50
  page.value = 1
}

function goto(target: number) {
  if (!data.value) return
  const next = Math.min(Math.max(1, target), data.value.pages)
  if (next === page.value) return
  page.value = next
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function toggleDetail(run: ProbeRun) {
  expanded.value = expanded.value === run.id ? null : run.id
}

function formatDuration(value: number | null | undefined) {
  if (value == null) return '—'
  if (value >= 60000) return `${(value / 60000).toFixed(1)}m`
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${value}ms`
}

function formatNumber(value: number | null | undefined) {
  if (value == null) return '—'
  return new Intl.NumberFormat('zh-CN').format(value)
}

function formatTime(value: string | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function statusLabel(run: ProbeRun) {
  if (run.success && run.usable) return '可用'
  if (run.success) return '缓慢'
  if (run.error_kind === 'rate_limited') return '限流'
  if (run.error_kind === 'timeout' || run.error_kind === 'upstream_timeout') return '超时'
  return '失败'
}

function sourceLabel(source: string) {
  if (source === 'scheduled') return '定时'
  if (source === 'manual') return '手动'
  if (source === 'settings_test') return '设置测试'
  return source
}

watch([rangeFilter, statusFilter, sourceFilter, pageSize], () => {
  expanded.value = null
  if (page.value !== 1) {
    page.value = 1
    return
  }
  load()
})
watch(page, () => {
  expanded.value = null
  load()
})

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && purgeOpen.value) closePurge()
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="page probes-page">
    <div class="page-heading">
      <div>
        <button class="back-link" @click="emit('backDashboard')"><ArrowLeft :size="15" />返回运行态势</button>
        <span class="eyebrow"><i></i>EVENT ARCHIVE</span>
        <h1>全部 Agent 探测记录</h1>
        <p>按保留策略留存的完整探测流水，可按时间范围、结果与触发来源筛选并导出。</p>
      </div>
      <div class="heading-actions">
        <a class="button button--secondary" :href="`/api/probes/export?${exportQuery}`">
          <ArrowDownToLine :size="15" />导出当前筛选 CSV
        </a>
        <button class="button button--danger" @click="openPurge">
          <Trash2 :size="15" />清空全部数据
        </button>
      </div>
    </div>

    <div v-if="purgeNotice" class="settings-alert settings-alert--success">
      <CheckCircle2 :size="17" /><span>{{ purgeNotice }}</span>
      <button @click="purgeNotice = ''"><X :size="14" /></button>
    </div>

    <div v-if="error" class="error-state">
      <AlertTriangle :size="22" />
      <div><strong>探测记录暂不可读</strong><p>{{ error }}</p></div>
      <button class="button button--secondary" @click="load()">重试</button>
    </div>

    <section v-else class="panel recent-panel probes-panel">
      <header class="panel-head">
        <div>
          <span class="panel-eyebrow">PROBE HISTORY</span>
          <h2>探测流水</h2>
          <p>不保存完整模型回复，只留短摘要与性能元数据；点击任意行可展开详情。</p>
        </div>
        <span class="endpoint-chip">
          <Database :size="14" />
          {{ data ? `共 ${formatNumber(data.total)} 条` : '读取中' }}
        </span>
      </header>

      <div class="probes-filters">
        <div class="segmented small">
          <button v-for="item in rangeOptions" :key="item.value"
            :class="{ active: rangeFilter === item.value }" @click="rangeFilter = item.value">
            {{ item.label }}
          </button>
        </div>
        <label class="field field--inline">
          <span>结果</span>
          <select v-model="statusFilter">
            <option value="all">全部结果</option>
            <option value="usable">可用</option>
            <option value="slow">缓慢</option>
            <option value="failed">失败</option>
          </select>
        </label>
        <label class="field field--inline">
          <span>来源</span>
          <select v-model="sourceFilter">
            <option value="all">全部来源</option>
            <option value="scheduled">定时</option>
            <option value="manual">手动</option>
            <option value="settings_test">设置测试</option>
          </select>
        </label>
        <label class="field field--inline">
          <span>每页</span>
          <select v-model.number="pageSize">
            <option :value="20">20 条</option>
            <option :value="50">50 条</option>
            <option :value="100">100 条</option>
            <option :value="200">200 条</option>
          </select>
        </label>
        <button class="button button--secondary probes-reset" @click="resetFilters">
          <RotateCcw :size="14" />重置
        </button>
      </div>

      <div v-if="loading" class="probes-loading">
        <div class="skeleton" v-for="i in 6" :key="i"></div>
      </div>

      <template v-else-if="data && data.items.length">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>结果</th>
                <th>总耗时</th>
                <th>首 Token</th>
                <th>HTTP</th>
                <th>输入 / 输出</th>
                <th>Token</th>
                <th>来源</th>
                <th>模型</th>
                <th aria-label="展开"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="run in data.items" :key="run.id">
                <tr class="probes-row" :class="{ open: expanded === run.id }" @click="toggleDetail(run)">
                  <td><span class="mono">{{ formatTime(run.started_at) }}</span></td>
                  <td><span class="run-status" :class="{ ok: run.success && run.usable, slow: run.success && !run.usable, fail: !run.success }">
                    <Check v-if="run.success && run.usable" :size="13" />
                    <AlertTriangle v-else-if="run.success" :size="13" />
                    <X v-else :size="13" />{{ statusLabel(run) }}
                  </span></td>
                  <td>{{ formatDuration(run.latency_ms) }}</td>
                  <td>{{ formatDuration(run.ttft_ms) }}</td>
                  <td><span class="mono">{{ run.http_status ?? '—' }}</span></td>
                  <td>{{ formatNumber(run.input_tokens) }} / {{ formatNumber(run.output_tokens) }}</td>
                  <td>{{ formatNumber(run.total_tokens) }}</td>
                  <td>{{ sourceLabel(run.source) }}</td>
                  <td class="probes-model" :title="run.model">{{ run.model }}</td>
                  <td class="probes-caret"><ChevronDown :size="14" /></td>
                </tr>
                <tr v-if="expanded === run.id" class="probes-detail">
                  <td colspan="10">
                    <dl>
                      <div><dt>状态分类</dt><dd><span class="mono">{{ run.status_category }}</span></dd></div>
                      <div><dt>结束时间</dt><dd><span class="mono">{{ formatTime(run.finished_at) }}</span></dd></div>
                      <div><dt>首字节</dt><dd>{{ formatDuration(run.first_byte_ms) }}</dd></div>
                      <div><dt>错误类型</dt><dd><span class="mono">{{ run.error_kind || '—' }}</span></dd></div>
                      <div class="probes-detail__wide"><dt>端点</dt><dd><span class="mono">{{ run.endpoint }}</span></dd></div>
                      <div v-if="run.error_message" class="probes-detail__wide">
                        <dt>错误信息</dt><dd>{{ run.error_message }}</dd>
                      </div>
                      <div v-if="run.response_excerpt" class="probes-detail__wide">
                        <dt>回复摘要</dt><dd>{{ run.response_excerpt }}</dd>
                      </div>
                    </dl>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>

        <footer class="probes-pager">
          <span>第 {{ rangeStart }}–{{ rangeEnd }} 条 · 共 {{ formatNumber(data.total) }} 条</span>
          <div class="probes-pager__controls">
            <button class="button button--secondary" :disabled="data.page <= 1" @click="goto(data.page - 1)">
              <ChevronLeft :size="14" />上一页
            </button>
            <span class="probes-pager__index">{{ data.page }} / {{ data.pages }}</span>
            <button class="button button--secondary" :disabled="data.page >= data.pages" @click="goto(data.page + 1)">
              下一页<ChevronRight :size="14" />
            </button>
          </div>
        </footer>
      </template>

      <div v-else class="inline-empty">
        <Radio :size="20" />
        <div><strong>没有符合条件的探测记录</strong><p>调整筛选条件，或等待下一轮定时探测写入数据。</p></div>
      </div>
    </section>

    <div v-if="purgeOpen" class="dialog-overlay" @click.self="closePurge">
      <section class="dialog-card" role="dialog" aria-modal="true" aria-labelledby="purge-title">
        <header>
          <span class="dialog-icon"><AlertTriangle :size="19" /></span>
          <div>
            <span class="panel-eyebrow">DESTRUCTIVE ACTION</span>
            <h2 id="purge-title">清空全部探测数据</h2>
          </div>
        </header>
        <p>即将永久删除{{ purgeScope }}，包含定时、手动与设置测试三类来源。运行态势、可用率、热力图与最佳调用时窗都会归零。</p>
        <p class="dialog-hint">监控设置与已加密保存的 API Key 不受影响；调度器会在下一个周期重新开始积累数据。</p>
        <div v-if="purgeError" class="dialog-error"><AlertTriangle :size="14" />{{ purgeError }}</div>
        <footer>
          <button class="button button--secondary" :disabled="purging" @click="closePurge">取消</button>
          <button class="button button--danger" :disabled="purging" @click="purgeAll">
            <LoaderCircle v-if="purging" :size="16" class="spin" /><Trash2 v-else :size="15" />
            {{ purging ? '正在清空' : '确认清空' }}
          </button>
        </footer>
      </section>
    </div>
  </div>
</template>
