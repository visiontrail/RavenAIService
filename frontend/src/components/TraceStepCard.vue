<template>
  <div
    class="trace-card"
    :class="[
      `trace-card--${card.kind}`,
      `trace-card--${card.status}`,
      { 'trace-card--collapsed': collapsed },
    ]"
  >
    <div class="trace-card__header">
      <button
        type="button"
        class="trace-card__toggle"
        :aria-expanded="!collapsed"
        @click="toggle"
      >
        <span class="trace-card__icon" aria-hidden="true">
          <Loader2 v-if="card.status === 'running'" class="trace-card__icon-svg trace-card__icon-svg--spin" />
          <Check v-else-if="card.status === 'ok'" class="trace-card__icon-svg" />
          <X v-else-if="card.status === 'error'" class="trace-card__icon-svg" />
          <Ban v-else-if="card.status === 'cancelled'" class="trace-card__icon-svg" />
        </span>
        <span class="trace-card__label">
          <span class="trace-card__title">{{ headerTitle }}</span>
          <span v-if="headerSubtitle" class="trace-card__subtitle">{{ headerSubtitle }}</span>
        </span>
        <span v-if="card.durationSeconds !== undefined" class="trace-card__duration">
          {{ card.durationSeconds.toFixed(1) }}s
        </span>
        <ChevronDown
          class="trace-card__chevron"
          :class="{ 'trace-card__chevron--open': !collapsed }"
          aria-hidden="true"
        />
      </button>
      <button
        v-if="!collapsed"
        type="button"
        class="trace-card__copy"
        :class="{ 'trace-card__copy--copied': copied }"
        :title="copyLabel"
        :aria-label="copyLabel"
        @click="copyCardContent"
      >
        <Check v-if="copied" class="trace-card__copy-icon" aria-hidden="true" />
        <Copy v-else class="trace-card__copy-icon" aria-hidden="true" />
      </button>
    </div>
    <div v-if="!collapsed" class="trace-card__body">
      <div v-if="card.kind === 'tool'" class="trace-card__tool-body">
        <div v-if="card.toolInput" class="trace-card__section">
          <div class="trace-card__section-label">输入</div>
          <pre class="trace-card__code">{{ formattedInput }}</pre>
        </div>
        <div v-if="effectiveOutput" class="trace-card__section">
          <div class="trace-card__section-label">输出</div>
          <pre class="trace-card__code trace-card__code--output">{{ effectiveOutput }}<span
            v-if="card.status === 'running'"
            class="trace-card__cursor"
            aria-hidden="true"
          >▍</span></pre>
        </div>
      </div>
      <div v-else class="trace-card__thinking-body">
        <div class="trace-card__section-label">Thinking</div>
        <div class="trace-card__thinking-text">
          {{ card.thinkingText }}
          <span
            v-if="card.status === 'running'"
            class="trace-card__cursor"
            aria-hidden="true"
          >▍</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Ban, Check, ChevronDown, Copy, Loader2, X } from 'lucide-vue-next'
import type { TraceCard, TraceCardStatus } from '@/composables/useAgentTraceStream'

const props = defineProps<{
  card: TraceCard
  displayName: string
}>()

// Each card keeps its own collapsed state. Running -> expanded by default,
// terminal -> collapsed by default. Once the user toggles, their preference
// sticks until the component is destroyed.
const userTouched = ref(false)
const collapsed = ref(props.card.status === 'running' ? false : true)
const copied = ref(false)
let copiedTimer: number | undefined

watch(
  () => props.card.status,
  (status: TraceCardStatus, prev: TraceCardStatus | undefined) => {
    if (userTouched.value) return
    if (prev === 'running' && status !== 'running') {
      collapsed.value = true
    } else if (prev !== 'running' && status === 'running') {
      collapsed.value = false
    }
  },
)

onBeforeUnmount(() => {
  if (copiedTimer !== undefined) window.clearTimeout(copiedTimer)
})

function toggle() {
  userTouched.value = true
  collapsed.value = !collapsed.value
}

const headerTitle = computed(() => {
  if (props.card.kind === 'thinking') return 'Thinking'
  return props.displayName || props.card.toolName || '工具'
})

const inputSummary = computed(() => {
  const input = props.card.toolInput
  if (!input) return ''
  const candidates: string[] = []
  for (const key of ['command', 'cmd', 'path', 'file_path', 'query', 'pattern']) {
    const v = (input as Record<string, unknown>)[key]
    if (typeof v === 'string' && v.length > 0) {
      candidates.push(v)
      break
    }
  }
  if (candidates.length === 0) {
    try {
      const json = JSON.stringify(input)
      if (json && json !== '{}') candidates.push(json)
    } catch {
      // ignore
    }
  }
  const summary = candidates[0] || ''
  return summary.length > 80 ? summary.slice(0, 77) + '…' : summary
})

const headerSubtitle = computed(() => {
  if (props.card.kind === 'thinking') {
    if (!collapsed.value) return ''
    const txt = props.card.thinkingText
    if (!txt) return ''
    return txt.length > 60 ? txt.slice(0, 57) + '…' : txt
  }
  return inputSummary.value
})

const formattedInput = computed(() => {
  if (!props.card.toolInput) return ''
  try {
    return JSON.stringify(props.card.toolInput, null, 2)
  } catch {
    return String(props.card.toolInput)
  }
})

const effectiveOutput = computed(() => {
  if (props.card.output) return props.card.output
  return props.card.outputExcerpt || ''
})

const copyLabel = computed(() => (copied.value ? '已复制' : '复制'))

const copyText = computed(() => {
  if (props.card.kind === 'thinking') {
    return ['Thinking', props.card.thinkingText].filter(Boolean).join('\n\n')
  }

  const sections = [headerTitle.value]
  if (formattedInput.value) sections.push(`输入\n${formattedInput.value}`)
  if (effectiveOutput.value) sections.push(`输出\n${effectiveOutput.value}`)
  return sections.filter(Boolean).join('\n\n')
})

async function copyToClipboard(text: string) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

async function copyCardContent() {
  const text = copyText.value.trim()
  if (!text) return

  await copyToClipboard(text)
  copied.value = true
  if (copiedTimer !== undefined) window.clearTimeout(copiedTimer)
  copiedTimer = window.setTimeout(() => {
    copied.value = false
    copiedTimer = undefined
  }, 1200)
}
</script>

<style scoped>
.trace-card {
  border: 1px solid var(--el-border-color-lighter, #e5e7eb);
  border-radius: 8px;
  background: var(--el-bg-color, #ffffff);
  overflow: hidden;
  transition: border-color 0.15s ease;
}

.trace-card--thinking {
  border-style: dashed;
}

.trace-card--running {
  border-color: #3b82f6;
}

.trace-card--ok {
  border-color: #d1fae5;
}

.trace-card--error {
  border-color: #fecaca;
}

.trace-card--cancelled {
  border-color: #e5e7eb;
}

.trace-card__header {
  display: flex;
  align-items: center;
  width: 100%;
  background: transparent;
}

.trace-card__header:hover {
  background: var(--el-fill-color-light, #f5f7fa);
}

.trace-card__toggle {
  display: flex;
  align-items: center;
  flex: 1 1 auto;
  gap: 8px;
  min-width: 0;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
}

.trace-card__copy {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-right: 8px;
  flex: 0 0 auto;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--el-text-color-secondary, #6b7280);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}

.trace-card__copy:hover {
  background: var(--el-bg-color, #ffffff);
  border-color: var(--el-border-color-light, #dcdfe6);
  color: var(--el-text-color-primary, #111827);
}

.trace-card__copy--copied {
  color: #10b981;
}

.trace-card__copy-icon {
  width: 14px;
  height: 14px;
}

.trace-card__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.trace-card__icon-svg {
  width: 16px;
  height: 16px;
}

.trace-card__icon-svg--spin {
  animation: trace-card-spin 0.9s linear infinite;
}

@keyframes trace-card-spin {
  to { transform: rotate(360deg); }
}

.trace-card--running .trace-card__icon-svg { color: #3b82f6; }
.trace-card--ok .trace-card__icon-svg { color: #10b981; }
.trace-card--error .trace-card__icon-svg { color: #ef4444; }
.trace-card--cancelled .trace-card__icon-svg { color: #6b7280; }

.trace-card__label {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.trace-card__title {
  font-weight: 500;
  font-size: 13px;
  color: var(--el-text-color-primary, #111827);
}

.trace-card__subtitle {
  font-size: 12px;
  color: var(--el-text-color-secondary, #6b7280);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-card__duration {
  font-size: 12px;
  color: var(--el-text-color-regular, #4b5563);
  font-variant-numeric: tabular-nums;
}

.trace-card__chevron {
  width: 14px;
  height: 14px;
  transition: transform 0.15s ease;
  color: var(--el-text-color-secondary, #6b7280);
}

.trace-card__chevron--open {
  transform: rotate(180deg);
}

.trace-card__body {
  padding: 0 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trace-card__section-label {
  font-size: 11px;
  color: var(--el-text-color-secondary, #6b7280);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.trace-card__code {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px;
  padding: 8px 10px;
  max-height: 260px;
  overflow: auto;
}

.trace-card__code--output {
  background: #0f172a;
  color: #e2e8f0;
}

.trace-card__thinking-text {
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-primary, #111827);
  white-space: pre-wrap;
}

.trace-card__cursor {
  display: inline-block;
  margin-left: 1px;
  animation: trace-card-blink 0.9s steps(2, start) infinite;
}

@keyframes trace-card-blink {
  to { visibility: hidden; }
}
</style>
