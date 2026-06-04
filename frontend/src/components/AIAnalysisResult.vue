<template>
  <div class="ai-analysis-result" :class="{ loading: isLoading }">
    <div v-if="isLoading" class="loading-section">
      <div class="loading-header">
        <div class="loading-icon">
          <div class="pulse-ring"></div>
          <div class="pulse-core"></div>
        </div>
        <h2 class="loading-title">{{ t('aiAnalysis.loadingTitle') }}</h2>
        <p class="loading-subtitle">{{ t('aiAnalysis.loadingSubtitle') }}</p>
      </div>

      <div class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${progress}%` }"></div>
        </div>
        <span class="progress-text">{{ progress }}%</span>
      </div>

      <div v-if="currentStep" class="current-step">
        <span class="step-label">{{ t('aiAnalysis.currentStep') }}</span>
        <span class="step-content">{{ currentStep }}</span>
      </div>
    </div>

    <div v-else-if="result" class="result-section">
      <div class="result-header">
        <div class="status-indicator" :class="result.status || 'completed'">
          <component :is="getStatusIcon(result.status || 'completed')" class="status-icon" />
        </div>

        <div class="header-content">
          <h1 class="result-title">{{ t('aiAnalysis.resultTitle') }}</h1>
          <div class="result-meta">
            <span class="query-text">{{ result.query || t('aiAnalysis.unknownQuery') }}</span>
            <span class="timestamp">{{ formatTimestamp(result.timestamp || new Date().toISOString()) }}</span>
          </div>
        </div>

      </div>

      <div class="markdown-panel" ref="markdownPanel" v-html="renderedMarkdown"></div>

      <div class="metadata-line" v-if="result.metadata">
        <span v-if="typeof result.metadata.execution_time === 'number'">{{ t('aiAnalysis.executionTime', { time: formatDuration(result.metadata.execution_time) }) }}</span>
        <span v-if="result.metadata.model_used">{{ t('aiAnalysis.modelUsed', { model: result.metadata.model_used }) }}</span>
      </div>

      <div class="actions-section">
        <button @click="copyResult" class="action-btn secondary">
          <Copy class="btn-icon" />
          {{ t('aiAnalysis.copyResult') }}
        </button>
        <button @click="downloadResult" class="action-btn secondary">
          <Download class="btn-icon" />
          {{ t('aiAnalysis.downloadReport') }}
        </button>
        <button @click="$emit('restart')" class="action-btn outline">
          <RotateCcw class="btn-icon" />
          {{ t('aiAnalysis.reAnalyze') }}
        </button>
      </div>
    </div>

    <div v-else-if="error" class="error-section">
      <div class="error-icon">
        <AlertCircle />
      </div>
      <h2 class="error-title">{{ t('aiAnalysis.errorTitle') }}</h2>
      <p class="error-message">{{ error }}</p>
      <button @click="$emit('retry')" class="retry-btn">
        <RotateCcw class="btn-icon" />
        {{ t('aiAnalysis.retry') }}
      </button>
    </div>

    <div v-else class="empty-section">
      <div class="empty-icon">
        <Brain />
      </div>
      <h2 class="empty-title">{{ t('aiAnalysis.emptyTitle') }}</h2>
      <p class="empty-message">{{ t('aiAnalysis.emptyMessage') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  CheckCircle,
  Clock,
  XCircle,
  AlertCircle,
  Copy,
  Download,
  RotateCcw,
  Brain,
} from 'lucide-vue-next'
import { renderMarkdown, cleanContent, processMermaidBlocks } from '../utils/markdownRenderer'
import { copyToClipboard } from '../utils'

interface Props {
  result?: any
  isLoading?: boolean
  progress?: number
  currentStep?: string
  error?: string
}

const { t } = useI18n()

const props = withDefaults(defineProps<Props>(), {
  isLoading: false,
  progress: 0,
  currentStep: '',
  error: ''
})

defineEmits<{
  restart: []
  retry: []
}>()

const rawMarkdown = computed(() => {
  const r = props.result
  if (!r) return ''

  const content = r?.final_result?.content ?? r?.final_report ?? r?.content
  if (typeof content === 'string') return content

  if (typeof r === 'string') return r

  try {
    return JSON.stringify(content ?? r, null, 2)
  } catch {
    return String(content ?? '')
  }
})

const renderedMarkdown = computed(() =>
  renderMarkdown(rawMarkdown.value, {
    cleanXml: true,
    wrapperClass: 'markdown-content'
  })
)

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'completed':
      return CheckCircle
    case 'failed':
      return XCircle
    case 'processing':
      return Clock
    default:
      return Clock
  }
}

const formatTimestamp = (timestamp: string) => new Date(timestamp).toLocaleString('zh-CN')

const formatDuration = (seconds: number) => {
  if (seconds < 60) return t('aiAnalysis.durationSec', { seconds: seconds.toFixed(1) })
  if (seconds < 3600) return t('aiAnalysis.durationMin', { minutes: Math.floor(seconds / 60), seconds: Math.floor(seconds % 60) })
  return t('aiAnalysis.durationHour', { hours: Math.floor(seconds / 3600), minutes: Math.floor((seconds % 3600) / 60) })
}

const markdownPanel = ref<HTMLElement | null>(null)
let mermaidRenderScheduled = false

const scheduleMermaidRender = () => {
  if (props.isLoading || !props.result || mermaidRenderScheduled) return

  mermaidRenderScheduled = true
  nextTick(() => {
    mermaidRenderScheduled = false
    if (props.isLoading || !props.result) return
    void processMermaidBlocks(markdownPanel.value)
  })
}

watch(
  [renderedMarkdown, () => props.isLoading],
  scheduleMermaidRender,
  { immediate: true, flush: 'post' }
)

// 获取用户在分析结果面板内选中的文本，若无有效选区则返回空字符串
const getSelectedTextInPanel = (): string => {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
    return ''
  }

  const panel = markdownPanel.value
  if (!panel) return ''

  // 确保选区与分析结果面板有交集，避免复制到面板外的内容
  let intersectsPanel = false
  for (let i = 0; i < selection.rangeCount; i++) {
    const range = selection.getRangeAt(i)
    if (
      panel.contains(range.commonAncestorContainer) ||
      range.intersectsNode(panel)
    ) {
      intersectsPanel = true
      break
    }
  }
  if (!intersectsPanel) return ''

  return selection.toString().trim()
}

const copyResult = async () => {
  const selectedText = getSelectedTextInPanel()
  const isSelection = !!selectedText
  const text = isSelection ? selectedText : cleanContent(rawMarkdown.value)
  if (!text) {
    ElMessage.warning(t('aiAnalysis.noCopyContent'))
    return
  }

  const success = await copyToClipboard(text)
  if (success) {
    ElMessage.success(isSelection ? t('aiAnalysis.copySelectionSuccess') : t('aiAnalysis.copySuccess'))
  } else {
    ElMessage.error(t('aiAnalysis.copyFail'))
  }
}

const downloadResult = () => {
  const content = rawMarkdown.value
  if (!content) {
    ElMessage.warning(t('aiAnalysis.noDownloadContent'))
    return
  }

  const date = new Date().toISOString().slice(0, 10)
  const blob = new Blob([content], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = t('aiAnalysis.reportFilename', { date })
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)

  ElMessage.success(t('aiAnalysis.downloadSuccess'))
}
</script>

<style scoped>
@reference "tailwindcss";

.ai-analysis-result {
  @apply space-y-4;
}

.loading-section,
.result-section,
.error-section,
.empty-section {
  @apply rounded-xl border border-gray-200 bg-white p-6;
}

.loading-header {
  @apply mb-5 text-center;
}

.loading-icon {
  @apply relative mx-auto mb-4 h-12 w-12;
}

.pulse-ring {
  @apply absolute inset-0 rounded-full border-2 border-blue-300;
  animation: pulse-ring 1.8s ease-out infinite;
}

.pulse-core {
  @apply absolute left-1/2 top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-blue-500;
}

@keyframes pulse-ring {
  0% {
    transform: scale(0.8);
    opacity: 1;
  }
  100% {
    transform: scale(1.5);
    opacity: 0;
  }
}

.loading-title {
  @apply text-xl font-semibold text-gray-900;
}

.loading-subtitle {
  @apply mt-2 text-sm text-gray-500;
}

.progress-container {
  @apply mb-3 flex items-center gap-3;
}

.progress-bar {
  @apply h-2 flex-1 overflow-hidden rounded-full bg-gray-100;
}

.progress-fill {
  @apply h-full rounded-full bg-blue-500 transition-all duration-500;
}

.progress-text {
  @apply text-sm font-medium text-gray-700;
}

.current-step {
  @apply rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-700;
}

.step-label {
  @apply mr-1 font-medium;
}

.result-header {
  @apply mb-5 flex items-start gap-3;
}

.status-indicator {
  @apply rounded-lg bg-gray-100 p-2;
}

.status-indicator.completed {
  @apply bg-green-50 text-green-600;
}

.status-indicator.failed {
  @apply bg-red-50 text-red-600;
}

.status-indicator.processing {
  @apply bg-yellow-50 text-yellow-700;
}

.status-icon {
  @apply h-5 w-5;
}

.header-content {
  @apply min-w-0 flex-1;
}

.result-title {
  @apply text-xl font-semibold text-gray-900;
}

.result-meta {
  @apply mt-1 flex flex-wrap gap-3 text-sm text-gray-500;
}

.query-text {
  @apply truncate;
}

.markdown-panel {
  @apply rounded-lg border border-gray-200 bg-gray-50 p-4;
}

.metadata-line {
  @apply mt-4 flex flex-wrap gap-4 text-xs text-gray-500;
}

.actions-section {
  @apply mt-6 flex flex-wrap gap-3;
}

.action-btn {
  @apply inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors;
}

.action-btn.secondary {
  @apply border border-gray-200 bg-white text-gray-700 hover:bg-gray-50;
}

.action-btn.outline {
  @apply border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100;
}

.btn-icon {
  @apply h-4 w-4;
}

.error-section,
.empty-section {
  @apply text-center;
}

.error-icon,
.empty-icon {
  @apply mx-auto mb-3 h-8 w-8 text-gray-400;
}

.error-title,
.empty-title {
  @apply text-lg font-semibold text-gray-900;
}

.error-message,
.empty-message {
  @apply mt-2 text-sm text-gray-500;
}

.retry-btn {
  @apply mt-4 inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700;
}
</style>
