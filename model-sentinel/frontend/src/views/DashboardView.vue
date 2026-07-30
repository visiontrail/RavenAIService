<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowRight,
  Bolt,
  Check,
  CircleGauge,
  Clock3,
  Gauge,
  KeyRound,
  LoaderCircle,
  Play,
  Radio,
  ServerCog,
  ShieldCheck,
  Sparkles,
  TimerReset,
  X,
  Zap,
} from 'lucide-vue-next'
import { api } from '@/api'
import AvailabilityHeatmap from '@/components/AvailabilityHeatmap.vue'
import MetricCard from '@/components/MetricCard.vue'
import StatusPill from '@/components/StatusPill.vue'
import TrendChart from '@/components/TrendChart.vue'
import type { DashboardData, ProbeRun } from '@/types'

const emit = defineEmits<{ openSettings: []; openProbes: [] }>()

const range = ref<'24h' | '7d' | '30d'>('24h')
const granularity = ref<'hourly' | 'daily'>('hourly')
const loading = ref(true)
const running = ref(false)
const error = ref('')
const actionMessage = ref('')
const data = ref<DashboardData | null>(null)
let refreshTimer: number | undefined

const metrics = computed(() => data.value?.overview)
const exportPeriods = computed(() => {
  if (granularity.value === 'daily') return range.value === '30d' ? 30 : range.value === '7d' ? 7 : 1
  return range.value === '30d' ? 720 : range.value === '7d' ? 168 : 24
})

const lastProbe = computed(() => data.value?.recent[0] ?? null)
const uptimeTone = computed(() => {
  const uptime = metrics.value?.uptime_pct
  if (uptime == null) return 'neutral'
  if (uptime >= 99) return 'good'
  if (uptime >= 95) return 'warning'
  return 'danger'
})

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const response = await api.dashboard(range.value, granularity.value)
    data.value = response.data
    error.value = ''
  } catch (err: any) {
    error.value = err.message || '无法读取监控数据'
  } finally {
    loading.value = false
  }
}

async function runNow() {
  running.value = true
  actionMessage.value = ''
  try {
    const response = await api.runProbe()
    const result = response.data as ProbeRun
    actionMessage.value = result.success
      ? `探测完成 · 总耗时 ${formatDuration(result.latency_ms)}`
      : `探测失败 · ${result.error_message || result.error_kind}`
    await load(true)
  } catch (err: any) {
    actionMessage.value = err.message || '探测未能执行'
  } finally {
    running.value = false
  }
}

function selectRange(value: '24h' | '7d' | '30d') {
  range.value = value
  granularity.value = value === '30d' ? 'daily' : 'hourly'
}

function formatDuration(value: number | null | undefined) {
  if (value == null) return '—'
  if (value >= 60000) return `${(value / 60000).toFixed(1)}m`
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`
  return `${value}ms`
}

function formatNumber(value: number | null | undefined) {
  if (value == null) return '—'
  return new Intl.NumberFormat('zh-CN', { notation: value > 9999 ? 'compact' : 'standard' }).format(value)
}

function formatTime(value: string | undefined) {
  if (!value) return '尚未探测'
  return new Intl.DateTimeFormat('zh-CN', {
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
  if (run.error_kind === 'timeout') return '超时'
  return '失败'
}

watch([range, granularity], () => load())
onMounted(() => {
  load()
  refreshTimer = window.setInterval(() => load(true), 30000)
})
onBeforeUnmount(() => window.clearInterval(refreshTimer))
</script>

<template>
  <div class="page dashboard-page">
    <div class="page-heading">
      <div>
        <span class="eyebrow"><i></i>MODEL OPERATIONS</span>
        <h1>模型服务器全天候观测</h1>
        <p>模拟真实 Agent 调用工况，定位稳定可用时窗，为扩容与流量调度提供证据。</p>
      </div>
      <div class="heading-actions">
        <div class="segmented range-segmented">
          <button v-for="item in ['24h', '7d', '30d']" :key="item"
            :class="{ active: range === item }" @click="selectRange(item as any)">
            {{ item === '24h' ? '24 小时' : item === '7d' ? '7 天' : '30 天' }}
          </button>
        </div>
        <button class="button button--primary"
          :disabled="running || !data?.settings.api_key_set || data?.state.level === 'starting'"
          @click="runNow">
          <LoaderCircle v-if="running" :size="16" class="spin" />
          <Play v-else :size="15" fill="currentColor" />
          {{ running ? 'Agent 调用中' : '立即探测' }}
        </button>
      </div>
    </div>

    <div v-if="actionMessage" class="action-banner">
      <Radio :size="15" /><span>{{ actionMessage }}</span>
      <button aria-label="关闭提示" @click="actionMessage = ''"><X :size="14" /></button>
    </div>

    <div v-if="error" class="error-state">
      <AlertTriangle :size="22" />
      <div><strong>监控数据暂不可读</strong><p>{{ error }}</p></div>
      <button class="button button--secondary" @click="load()">重试</button>
    </div>

    <div v-else-if="loading" class="dashboard-loading">
      <div class="skeleton skeleton--hero"></div>
      <div class="skeleton-row"><i v-for="i in 4" :key="i"></i></div>
      <div class="skeleton skeleton--chart"></div>
    </div>

    <template v-else-if="data">
      <section class="live-deck reveal-section">
        <div class="live-deck__atmosphere"></div>
        <div class="live-deck__main">
          <StatusPill :level="data.state.level" :label="data.state.label" />
          <p class="live-deck__kicker">当前可用性</p>
          <strong class="live-deck__value">
            {{ metrics?.uptime_pct == null ? '—' : `${metrics.uptime_pct}%` }}
          </strong>
          <p class="live-deck__detail">{{ data.state.detail }}</p>
          <div class="live-deck__meta">
            <span><i></i>{{ data.settings.target_name }}</span>
            <span><i></i>{{ data.settings.model }}</span>
            <span><i></i>每 {{ Math.round(data.settings.interval_seconds / 60) }} 分钟</span>
          </div>
        </div>
        <div class="live-deck__side">
          <div>
            <span>最近探测</span>
            <strong>{{ formatTime(lastProbe?.started_at) }}</strong>
          </div>
          <div>
            <span>最近耗时</span>
            <strong>{{ formatDuration(lastProbe?.latency_ms) }}</strong>
          </div>
          <div>
            <span>观测样本</span>
            <strong>{{ metrics?.calls ?? 0 }} 次</strong>
          </div>
          <div class="live-wave" aria-hidden="true">
            <i v-for="i in 16" :key="i" :style="{ '--i': i }"></i>
          </div>
        </div>
      </section>

      <section v-if="!data.settings.api_key_set" class="setup-callout">
        <span class="setup-callout__icon"><KeyRound :size="22" /></span>
        <div>
          <strong>还差一步：配置模型 API Key</strong>
          <p>端点和模型已沿用 Raven 主力模型。设置 Key 后，7×24 调度会自动开始。</p>
        </div>
        <button class="button button--primary" @click="emit('openSettings')">前往设置</button>
      </section>

      <section class="metric-grid">
        <MetricCard
          label="可用调用"
          :value="metrics?.usable_pct == null ? '—' : `${metrics.usable_pct}%`"
          :hint="`${metrics?.usable_calls ?? 0} / ${metrics?.calls ?? 0} 次满足延迟阈值`"
          :icon="ShieldCheck"
          :tone="uptimeTone"
        />
        <MetricCard
          label="模型总延迟（P95）"
          :value="formatDuration(metrics?.p95_latency_ms)"
          :hint="`阈值 ${formatDuration(data.settings.alert_latency_ms)}`"
          :icon="Gauge"
          :tone="(metrics?.p95_latency_ms ?? 0) > data.settings.alert_latency_ms ? 'warning' : 'neutral'"
        />
        <MetricCard
          label="P95 首 Token"
          :value="formatDuration(metrics?.p95_ttft_ms)"
          hint="真实流式响应首个文本片段"
          :icon="Zap"
        />
        <MetricCard
          label="限流占比"
          :value="metrics?.rate_limit_pct == null ? '—' : `${metrics.rate_limit_pct}%`"
          :hint="`${metrics?.rate_limited ?? 0} 次 429 · ${formatNumber(metrics?.total_tokens)} Token`"
          :icon="TimerReset"
          :tone="(metrics?.rate_limit_pct ?? 0) >= 1 ? 'danger' : 'neutral'"
        />
      </section>

      <section class="analysis-grid">
        <article class="panel trend-panel">
          <header class="panel-head">
            <div>
              <span class="panel-eyebrow">SERVICE CURVE</span>
              <h2>可用率与尾延迟</h2>
              <p>柱形表示成功率，折线追踪 95% Agent 完整调用能够达到的总延迟。</p>
            </div>
            <div class="segmented small">
              <button :class="{ active: granularity === 'hourly' }" @click="granularity = 'hourly'">每小时</button>
              <button :class="{ active: granularity === 'daily' }" @click="granularity = 'daily'">每天</button>
            </div>
          </header>
          <TrendChart :points="data.series" :latency-threshold="data.settings.alert_latency_ms" />
        </article>

        <article class="panel decision-panel" :class="`decision-panel--${data.capacity_signal.level}`">
          <header class="decision-panel__head">
            <span><Bolt :size="16" />CAPACITY SIGNAL</span>
            <i></i>
          </header>
          <div class="decision-panel__body">
            <span class="decision-icon">
              <Check v-if="data.capacity_signal.level === 'healthy'" :size="24" />
              <CircleGauge v-else-if="data.capacity_signal.level === 'insufficient'" :size="24" />
              <AlertTriangle v-else :size="24" />
            </span>
            <h2>{{ data.capacity_signal.title }}</h2>
            <p>{{ data.capacity_signal.detail }}</p>
          </div>
          <dl>
            <div><dt>失败调用</dt><dd>{{ metrics?.failures ?? 0 }}</dd></div>
            <div><dt>服务端异常</dt><dd>{{ metrics?.server_errors ?? 0 }}</dd></div>
            <div><dt>平均耗时</dt><dd>{{ formatDuration(metrics?.avg_latency_ms) }}</dd></div>
          </dl>
        </article>
      </section>

      <section class="panel window-panel">
        <header class="panel-head">
          <div>
            <span class="panel-eyebrow">ROUTING WINDOW</span>
            <h2>推荐调用时窗</h2>
            <p>综合同一时段的成功率、P95 延迟和样本置信度，为负载均衡提供路由依据。</p>
          </div>
          <span class="sample-confidence">
            <Sparkles :size="14" />
            {{ data.calling_windows.sample_count }} / {{ data.calling_windows.minimum_samples }} 个基础样本
          </span>
        </header>
        <div v-if="data.calling_windows.windows.length" class="window-list">
          <article v-for="(window, index) in data.calling_windows.windows" :key="window.hour">
            <span class="window-rank">0{{ index + 1 }}</span>
            <div>
              <strong>{{ window.label }}</strong>
              <p>{{ window.samples }} 次样本 · P95 {{ formatDuration(window.p95_latency_ms) }}</p>
            </div>
            <div class="window-score">
              <span><i :style="{ width: `${Math.min(100, window.score)}%` }"></i></span>
              <strong>{{ window.score }}</strong>
            </div>
            <span class="window-uptime">{{ window.uptime_pct ?? 0 }}% 可用</span>
          </article>
        </div>
        <div v-else class="inline-empty">
          <Clock3 :size="20" />
          <div><strong>正在建立时段基线</strong><p>数据会在常驻监控开始后自动形成，无需手工维护。</p></div>
        </div>
        <p v-if="!data.calling_windows.ready && data.calling_windows.windows.length" class="confidence-note">
          当前为低置信度趋势；覆盖至少 2 个小时且达到 12 个样本后，会标记为可执行建议。
        </p>
      </section>

      <section class="panel heatmap-panel">
        <header class="panel-head">
          <div>
            <span class="panel-eyebrow">WEEKLY RHYTHM</span>
            <h2>一周小时可用性</h2>
            <p>横向 0–23 时，纵向为日期。颜色越深，当前小时越稳定。</p>
          </div>
          <a class="button button--secondary"
            :href="`/api/export?granularity=${granularity}&periods=${exportPeriods}`">
            <ArrowDownToLine :size="15" />导出 {{ granularity === 'hourly' ? '小时' : '每日' }} CSV
          </a>
        </header>
        <AvailabilityHeatmap :points="data.heatmap" />
      </section>

      <section class="panel recent-panel">
        <header class="panel-head">
          <div>
            <span class="panel-eyebrow">EVENT STREAM</span>
            <h2>最近 Agent 探测</h2>
            <p>不保存完整模型回复，只留短摘要与性能元数据。</p>
          </div>
          <div class="recent-panel__actions">
            <span class="endpoint-chip"><ServerCog :size="14" />{{ data.settings.protocol === 'anthropic' ? 'Anthropic Messages' : 'OpenAI Chat' }}</span>
            <button class="button button--secondary" @click="emit('openProbes')">
              查看更多<ArrowRight :size="15" />
            </button>
          </div>
        </header>
        <div v-if="data.recent.length" class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>结果</th><th>总耗时</th><th>首 Token</th><th>Token</th><th>来源</th></tr></thead>
            <tbody>
              <tr v-for="run in data.recent" :key="run.id">
                <td><span class="mono">{{ formatTime(run.started_at) }}</span></td>
                <td><span class="run-status" :class="{ ok: run.success && run.usable, slow: run.success && !run.usable, fail: !run.success }">
                  <Check v-if="run.success && run.usable" :size="13" />
                  <AlertTriangle v-else-if="run.success" :size="13" />
                  <X v-else :size="13" />{{ statusLabel(run) }}
                </span></td>
                <td>{{ formatDuration(run.latency_ms) }}</td>
                <td>{{ formatDuration(run.ttft_ms) }}</td>
                <td>{{ formatNumber(run.total_tokens) }}</td>
                <td>{{ run.source === 'scheduled' ? '定时' : run.source === 'manual' ? '手动' : '设置测试' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="inline-empty">
          <Radio :size="20" />
          <div><strong>尚无探测记录</strong><p>配置 API Key 后首轮探测会自动开始。</p></div>
        </div>
      </section>
    </template>
  </div>
</template>
