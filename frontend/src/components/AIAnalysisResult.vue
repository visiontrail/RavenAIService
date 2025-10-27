<template>
  <div class="ai-analysis-result" :class="{ 'loading': isLoading }">
    <!-- 加载状态 -->
    <div v-if="isLoading" class="loading-section">
      <div class="loading-header">
        <div class="loading-icon">
          <div class="pulse-ring"></div>
          <div class="pulse-core"></div>
        </div>
        <h2 class="loading-title">AI正在分析日志</h2>
        <p class="loading-subtitle">请稍候，这可能需要几分钟时间...</p>
      </div>
      
      <div class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${progress}%` }"></div>
        </div>
        <span class="progress-text">{{ progress }}%</span>
      </div>
      
      <div v-if="currentStep" class="current-step">
        <span class="step-label">当前步骤:</span>
        <span class="step-content">{{ currentStep }}</span>
      </div>
    </div>

    <!-- 分析结果 -->
    <div v-else-if="result" class="result-section">
      <!-- 主结果区域 -->
      <div class="main-result">
        <div class="result-header">
          <div class="status-indicator" :class="result.status">
            <component :is="getStatusIcon(result.status)" class="status-icon" />
          </div>
          <div class="header-content">
            <h1 class="result-title">分析结果</h1>
            <div class="result-meta">
              <span class="query-text">{{ result.query }}</span>
              <span class="timestamp">{{ formatTimestamp(result.timestamp) }}</span>
            </div>
          </div>
          <div class="confidence-badge" v-if="result.final_result.confidence">
            <span class="confidence-label">置信度</span>
            <span class="confidence-value">{{ Math.round(result.final_result.confidence * 100) }}%</span>
          </div>
        </div>

        <!-- 执行摘要 -->
        <div class="summary-section">
          <h2 class="summary-title">📊 执行摘要</h2>
          <p class="summary-content">{{ result.final_result.summary }}</p>
        </div>

        <!-- 主要发现 -->
        <div class="findings-section">
          <h2 class="findings-title">🔍 主要发现</h2>
          <div class="findings-content prose prose-gray max-w-none" v-html="formatMarkdown(result.final_result.content)"></div>
        </div>

        <!-- 建议措施 -->
        <div v-if="result.final_result.recommendations?.length" class="recommendations-section">
          <h2 class="recommendations-title">💡 建议措施</h2>
          <ul class="recommendations-list">
            <li v-for="(rec, index) in result.final_result.recommendations" :key="index" class="recommendation-item">
              <span class="rec-number">{{ index + 1 }}</span>
              <span class="rec-content">{{ rec }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- 执行计划区域 -->
      <div class="plan-section">
        <div class="section-header" @click="toggleSection('plan')" :class="{ active: expandedSections.plan }">
          <h3 class="section-title">📋 执行计划</h3>
          <div class="progress-indicator">
            <span class="progress-fraction">{{ result.plan.completed_steps }}/{{ result.plan.total_steps }}</span>
            <div class="mini-progress">
              <div class="mini-progress-fill" :style="{ width: `${(result.plan.completed_steps / result.plan.total_steps) * 100}%` }"></div>
            </div>
          </div>
          <ChevronDown class="toggle-icon" :class="{ rotated: expandedSections.plan }" />
        </div>
        
        <Transition name="slide-fade">
          <div v-show="expandedSections.plan" class="section-content">
            <div class="plan-content" v-html="formatMarkdown(result.plan.content)"></div>
            
            <div class="steps-list">
              <div v-for="step in result.plan.steps" :key="step.id" class="step-item" :class="step.status">
                <div class="step-indicator">
                  <component :is="getStepIcon(step.status)" class="step-icon" />
                </div>
                <div class="step-content">
                  <h4 class="step-title">{{ step.title }}</h4>
                  <p class="step-description">{{ step.description }}</p>
                </div>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- 详细执行过程 -->
      <div class="acts-section">
        <div class="section-header" @click="toggleSection('acts')" :class="{ active: expandedSections.acts }">
          <h3 class="section-title">⚙️ 执行过程</h3>
          <span class="acts-count">{{ result.acts.length }} 个步骤</span>
          <ChevronDown class="toggle-icon" :class="{ rotated: expandedSections.acts }" />
        </div>
        
        <Transition name="slide-fade">
          <div v-show="expandedSections.acts" class="section-content">
            <div v-for="act in result.acts" :key="act.step_id" class="act-item">
              <div class="act-header" @click="toggleAct(act.step_id)" :class="{ active: expandedActs[act.step_id] }">
                <div class="act-status" :class="act.status">
                  <component :is="getActIcon(act.status)" class="act-icon" />
                </div>
                <h4 class="act-title">{{ act.title }}</h4>
                <span class="act-timestamp">{{ formatTime(act.timestamp) }}</span>
                <ChevronDown class="act-toggle-icon" :class="{ rotated: expandedActs[act.step_id] }" />
              </div>
              
              <Transition name="slide-fade">
                <div v-show="expandedActs[act.step_id]" class="act-content">
                  <!-- 思考过程 -->
                  <div class="thought-section">
                    <div class="subsection-header" @click="toggleActSubsection(act.step_id, 'thought')" 
                         :class="{ active: expandedActSubsections[act.step_id]?.thought }">
                      <h5 class="subsection-title">🤔 思考过程</h5>
                      <ChevronDown class="subsection-toggle" :class="{ rotated: expandedActSubsections[act.step_id]?.thought }" />
                    </div>
                    <Transition name="slide-fade">
                      <div v-show="expandedActSubsections[act.step_id]?.thought" class="subsection-content">
                        <div class="thought-item">
                          <strong>推理过程:</strong>
                          <p>{{ act.thought.reasoning }}</p>
                        </div>
                        <div class="thought-item">
                          <strong>采用方法:</strong>
                          <p>{{ act.thought.approach }}</p>
                        </div>
                        <div class="thought-item">
                          <strong>预期结果:</strong>
                          <p>{{ act.thought.expected_outcome }}</p>
                        </div>
                      </div>
                    </Transition>
                  </div>

                  <!-- 执行结果 -->
                  <div class="execution-section">
                    <div class="subsection-header" @click="toggleActSubsection(act.step_id, 'execution')" 
                         :class="{ active: expandedActSubsections[act.step_id]?.execution }">
                      <h5 class="subsection-title">⚡ 执行结果</h5>
                      <span class="tool-badge">{{ act.execution.tool_used }}</span>
                      <ChevronDown class="subsection-toggle" :class="{ rotated: expandedActSubsections[act.step_id]?.execution }" />
                    </div>
                    <Transition name="slide-fade">
                      <div v-show="expandedActSubsections[act.step_id]?.execution" class="subsection-content">
                      <div class="execution-result prose prose-sm max-w-none" v-html="formatMarkdown(act.execution.processed_output)"></div>
                        
                        <div v-if="showRawOutput[act.step_id]" class="raw-output">
                          <h6 class="raw-output-title">原始输出:</h6>
                          <pre class="raw-output-content">{{ act.execution.raw_output }}</pre>
                        </div>
                        
                        <button @click="toggleRawOutput(act.step_id)" class="raw-output-toggle">
                          {{ showRawOutput[act.step_id] ? '隐藏' : '显示' }}原始输出
                        </button>
                      </div>
                    </Transition>
                  </div>

                  <!-- 步骤总结 -->
                  <div class="act-summary">
                    <h5 class="summary-label">📝 步骤总结</h5>
                    <p class="summary-text">{{ act.summary }}</p>
                  </div>
                </div>
              </Transition>
            </div>
          </div>
        </Transition>
      </div>

      <!-- 元数据信息 -->
      <div class="metadata-section">
        <div class="section-header" @click="toggleSection('metadata')" :class="{ active: expandedSections.metadata }">
          <h3 class="section-title">📊 分析信息</h3>
          <ChevronDown class="toggle-icon" :class="{ rotated: expandedSections.metadata }" />
        </div>
        
        <Transition name="slide-fade">
          <div v-show="expandedSections.metadata" class="section-content">
            <div class="metadata-grid">
              <div class="metadata-item">
                <span class="metadata-label">执行时间</span>
                <span class="metadata-value">{{ formatDuration(result.metadata.execution_time) }}</span>
              </div>
              <div class="metadata-item">
                <span class="metadata-label">使用模型</span>
                <span class="metadata-value">{{ result.metadata.model_used }}</span>
              </div>
              <div class="metadata-item">
                <span class="metadata-label">Token消耗</span>
                <span class="metadata-value">{{ result.metadata.tokens_used || 'N/A' }}</span>
              </div>
              <div class="metadata-item">
                <span class="metadata-label">分析ID</span>
                <span class="metadata-value">{{ result.id }}</span>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- 操作按钮 -->
      <div class="actions-section">
        <button @click="copyResult" class="action-btn primary">
          <Copy class="btn-icon" />
          复制结果
        </button>
        <button @click="downloadResult" class="action-btn secondary">
          <Download class="btn-icon" />
          下载报告
        </button>
        <button @click="shareResult" class="action-btn secondary">
          <Share class="btn-icon" />
          分享结果
        </button>
        <button @click="$emit('restart')" class="action-btn outline">
          <RotateCcw class="btn-icon" />
          重新分析
        </button>
      </div>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="error-section">
      <div class="error-icon">
        <AlertCircle />
      </div>
      <h2 class="error-title">分析失败</h2>
      <p class="error-message">{{ error }}</p>
      <button @click="$emit('retry')" class="retry-btn">
        <RotateCcw class="btn-icon" />
        重试
      </button>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-section">
      <div class="empty-icon">
        <Brain />
      </div>
      <h2 class="empty-title">准备开始AI分析</h2>
      <p class="empty-message">请输入分析查询以开始智能日志分析</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { 
  ChevronDown, 
  CheckCircle, 
  Clock, 
  XCircle, 
  AlertCircle,
  Copy,
  Download,
  Share,
  RotateCcw,
  Brain,
  Play,
  Pause
} from 'lucide-vue-next'

// Props
interface Props {
  result?: any
  isLoading?: boolean
  progress?: number
  currentStep?: string
  error?: string
}

const props = withDefaults(defineProps<Props>(), {
  isLoading: false,
  progress: 0,
  currentStep: '',
  error: ''
})

// Emits
const emit = defineEmits<{
  restart: []
  retry: []
}>()

// 响应式状态
const expandedSections = reactive({
  plan: false,
  acts: false,
  metadata: false
})

const expandedActs = ref<Record<string, boolean>>({})
const expandedActSubsections = ref<Record<string, { thought?: boolean, execution?: boolean }>>({})
const showRawOutput = ref<Record<string, boolean>>({})

// 方法

const toggleActSubsection = (actId: string, subsection: 'thought' | 'execution') => {
  if (!expandedActSubsections.value[actId]) {
    expandedActSubsections.value[actId] = {}
  }
  expandedActSubsections.value[actId][subsection] = !expandedActSubsections.value[actId][subsection]
}

const toggleRawOutput = (actId: string) => {
  showRawOutput.value[actId] = !showRawOutput.value[actId]
}

const getStatusIcon = (status: string) => {
  switch (status) {
    case 'completed': return CheckCircle
    case 'processing': return Clock
    case 'failed': return XCircle
    default: return Clock
  }
}

const getStepIcon = (status: string) => {
  switch (status) {
    case 'completed': return CheckCircle
    case 'in_progress': return Play
    case 'failed': return XCircle
    default: return Clock
  }
}

const getActIcon = (status: string) => {
  switch (status) {
    case 'completed': return CheckCircle
    case 'failed': return XCircle
    default: return Clock
  }
}

const formatTimestamp = (timestamp: string) => {
  return new Date(timestamp).toLocaleString('zh-CN')
}

const formatTime = (timestamp: string) => {
  return new Date(timestamp).toLocaleTimeString('zh-CN')
}

const formatDuration = (seconds: number) => {
  if (seconds < 60) {
    return `${seconds.toFixed(1)}秒`
  } else if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}分${Math.floor(seconds % 60)}秒`
  } else {
    return `${Math.floor(seconds / 3600)}小时${Math.floor((seconds % 3600) / 60)}分钟`
  }
}

const formatMarkdown = (content: string) => {
  if (!content) return ''
  
  // 简单的markdown转HTML处理
  return content
    .replace(/^# (.*$)/gim, '<h1>$1</h1>')
    .replace(/^## (.*$)/gim, '<h2>$1</h2>')
    .replace(/^### (.*$)/gim, '<h3>$1</h3>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/`(.*?)`/g, '<code>$1</code>')
    .replace(/^\- (.*$)/gim, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
    .replace(/\n/g, '<br>')
}

const copyResult = async () => {
  if (!props.result) return
  
  try {
    const text = `
分析查询: ${props.result.query}
执行摘要: ${props.result.final_result.summary}

详细结果:
${props.result.final_result.content}

建议措施:
${props.result.final_result.recommendations?.join('\n') || '无'}
    `.trim()
    
    await navigator.clipboard.writeText(text)
    ElMessage.success('分析结果已复制到剪贴板')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

const downloadResult = () => {
  if (!props.result) return
  
  const content = `# AI日志分析报告

## 基本信息
- 分析查询: ${props.result.query}
- 分析时间: ${formatTimestamp(props.result.timestamp)}
- 执行时长: ${formatDuration(props.result.metadata.execution_time)}
- 置信度: ${Math.round(props.result.final_result.confidence * 100)}%

## 执行摘要
${props.result.final_result.summary}

## 详细分析
${props.result.final_result.content}

## 建议措施
${props.result.final_result.recommendations?.map((rec: string, i: number) => `${i + 1}. ${rec}`).join('\n') || '无'}

## 执行过程
${props.result.acts.map((act: any) => `
### ${act.title}
**状态**: ${act.status === 'completed' ? '已完成' : '失败'}
**工具**: ${act.execution.tool_used}
**总结**: ${act.summary}
`).join('\n')}
`

  const blob = new Blob([content], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `AI分析报告_${new Date().toISOString().slice(0, 10)}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  
  ElMessage.success('报告已下载')
}

const shareResult = async () => {
  if (!props.result) return
  
  const shareData = {
    title: 'AI日志分析结果',
    text: `AI分析摘要: ${props.result.final_result.summary}`,
    url: window.location.href
  }
  
  try {
    if (navigator.share) {
      await navigator.share(shareData)
    } else {
      await navigator.clipboard.writeText(window.location.href)
      ElMessage.success('链接已复制到剪贴板')
    }
  } catch (error) {
    ElMessage.error('分享失败')
  }
}

// 高级交互功能
const isAnimating = ref(false)
const lastInteractionTime = ref(Date.now())
const autoSaveTimer = ref<number | null>(null)

// 键盘导航支持
const handleKeydown = (event: KeyboardEvent) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
    return // 不在输入框中处理快捷键
  }

  switch (event.key) {
    case 'p':
    case 'P':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        toggleSection('plan')
      }
      break
    case 'a':
    case 'A':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        toggleSection('acts')
      }
      break
    case 'm':
    case 'M':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        toggleSection('metadata')
      }
      break
    case 'c':
    case 'C':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        copyResult()
      }
      break
    case 'd':
    case 'D':
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault()
        downloadResult()
      }
      break
    case 'Escape':
      // 折叠所有展开的部分
      Object.keys(expandedSections).forEach(key => {
        expandedSections[key as keyof typeof expandedSections] = false
      })
      break
  }
}

// 状态持久化
const saveState = () => {
  if (!props.result) return
  
  const state = {
    expandedSections: { ...expandedSections },
    expandedActs: { ...expandedActs.value },
    expandedActSubsections: { ...expandedActSubsections.value },
    showRawOutput: { ...showRawOutput.value },
    timestamp: Date.now()
  }
  
  localStorage.setItem(`ai-analysis-state-${props.result.id}`, JSON.stringify(state))
}

const loadState = () => {
  if (!props.result) return
  
  try {
    const saved = localStorage.getItem(`ai-analysis-state-${props.result.id}`)
    if (saved) {
      const state = JSON.parse(saved)
      // 只加载24小时内的状态
      if (Date.now() - state.timestamp < 24 * 60 * 60 * 1000) {
        Object.assign(expandedSections, state.expandedSections)
        expandedActs.value = state.expandedActs || {}
        expandedActSubsections.value = state.expandedActSubsections || {}
        showRawOutput.value = state.showRawOutput || {}
      }
    }
  } catch (error) {
    console.warn('Failed to load saved state:', error)
  }
}

// 防抖保存状态
const debouncedSaveState = () => {
  if (autoSaveTimer.value) {
    clearTimeout(autoSaveTimer.value)
  }
  autoSaveTimer.value = setTimeout(saveState, 500)
}

// 性能优化的切换函数
const toggleSectionOptimized = (section: keyof typeof expandedSections) => {
  if (isAnimating.value) return
  
  isAnimating.value = true
  expandedSections[section] = !expandedSections[section]
  lastInteractionTime.value = Date.now()
  
  // 延迟重置动画状态
  setTimeout(() => {
    isAnimating.value = false
  }, 400)
  
  debouncedSaveState()
}

const toggleActOptimized = (actId: string) => {
  if (isAnimating.value) return
  
  isAnimating.value = true
  expandedActs.value[actId] = !expandedActs.value[actId]
  if (!expandedActSubsections.value[actId]) {
    expandedActSubsections.value[actId] = {}
  }
  lastInteractionTime.value = Date.now()
  
  setTimeout(() => {
    isAnimating.value = false
  }, 400)
  
  debouncedSaveState()
}

// 智能展开/折叠所有
const toggleAllSections = () => {
  const allExpanded = Object.values(expandedSections).every(Boolean)
  const newState = !allExpanded
  
  Object.keys(expandedSections).forEach(key => {
    expandedSections[key as keyof typeof expandedSections] = newState
  })
  
  debouncedSaveState()
}

// 复制特定部分
const copySection = async (sectionType: string, content: string) => {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success(`${sectionType}已复制到剪贴板`)
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

// 分享特定部分
const shareSection = async (sectionType: string, content: string) => {
  const shareData = {
    title: `AI分析结果 - ${sectionType}`,
    text: content,
    url: window.location.href
  }
  
  try {
    if (navigator.share) {
      await navigator.share(shareData)
    } else {
      await copySection(sectionType, content)
    }
  } catch (error) {
    ElMessage.error('分享失败')
  }
}

// 初始化展开状态和事件监听
onMounted(() => {
  if (props.result) {
    // 加载保存的状态
    loadState()
    
    // 如果没有保存的状态，默认展开主要部分
    if (!Object.values(expandedSections).some(Boolean)) {
      expandedSections.plan = true
    }
  }
  
  // 添加键盘事件监听
  document.addEventListener('keydown', handleKeydown)
})

// 清理事件监听器
onUnmounted(() => {
  document.removeEventListener('keydown', handleKeydown)
  if (autoSaveTimer.value) {
    clearTimeout(autoSaveTimer.value)
  }
})

// 重写原有的切换函数以使用优化版本
const toggleSection = toggleSectionOptimized
const toggleAct = toggleActOptimized
</script>

<style scoped>
@reference "tailwindcss";

/* 主容器样式 */
.ai-analysis-result {
  @apply max-w-none mx-auto bg-white rounded-2xl shadow-sm border border-gray-100;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* 加载状态样式 */
.loading-section {
  @apply p-12 text-center;
}

.loading-header {
  @apply mb-8;
}

.loading-icon {
  @apply relative inline-block w-16 h-16 mb-6;
}

.pulse-ring {
  @apply absolute inset-0 border-4 border-blue-200 rounded-full animate-ping;
}

.pulse-core {
  @apply absolute inset-2 bg-blue-500 rounded-full;
}

.loading-title {
  @apply text-2xl font-semibold text-gray-900 mb-2;
}

.loading-subtitle {
  @apply text-gray-600;
}

.progress-container {
  @apply flex items-center justify-center gap-4 mb-6;
}

.progress-bar {
  @apply w-64 h-2 bg-gray-200 rounded-full overflow-hidden;
}

.progress-fill {
  @apply h-full bg-gradient-to-r from-blue-500 to-blue-600 transition-all duration-300 ease-out;
}

.progress-text {
  @apply text-sm font-medium text-gray-700;
}

.current-step {
  @apply text-sm text-gray-600;
}

.step-label {
  @apply font-medium;
}

/* 主结果区域样式 */
.main-result {
  @apply p-8 border-b border-gray-100;
}

.result-header {
  @apply flex items-start gap-4 mb-8;
}

.status-indicator {
  @apply flex-shrink-0 w-12 h-12 rounded-full flex items-center justify-center;
}

.status-indicator.completed {
  @apply bg-green-100 text-green-600;
}

.status-indicator.processing {
  @apply bg-blue-100 text-blue-600;
}

.status-indicator.failed {
  @apply bg-red-100 text-red-600;
}

.status-icon {
  @apply w-6 h-6;
}

.header-content {
  @apply flex-1;
}

.result-title {
  @apply text-3xl font-bold text-gray-900 mb-2;
}

.result-meta {
  @apply flex flex-col gap-1;
}

.query-text {
  @apply text-lg text-gray-700 font-medium;
}

.timestamp {
  @apply text-sm text-gray-500;
}

.confidence-badge {
  @apply flex-shrink-0 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-xl px-4 py-2 text-center;
}

.confidence-label {
  @apply block text-xs text-blue-600 font-medium;
}

.confidence-value {
  @apply block text-lg font-bold text-blue-700;
}

/* 内容区域样式 */
.summary-section, .findings-section, .recommendations-section {
  @apply mb-8;
}

.summary-title, .findings-title, .recommendations-title {
  @apply text-xl font-semibold text-gray-900 mb-4;
}

.summary-content {
  @apply text-lg text-gray-700 leading-relaxed;
}

.findings-content {
  @apply max-w-none;
}

.recommendations-list {
  @apply space-y-3;
}

.recommendation-item {
  @apply flex items-start gap-3 p-4 bg-blue-50 rounded-lg border border-blue-100;
}

.rec-number {
  @apply flex-shrink-0 w-6 h-6 bg-blue-500 text-white text-sm font-bold rounded-full flex items-center justify-center;
}

.rec-content {
  @apply text-gray-700 leading-relaxed;
}

/* 可折叠区域样式 */
.plan-section, .acts-section, .metadata-section {
  @apply border-b border-gray-100;
}

.section-header {
  @apply flex items-center gap-4 p-6 cursor-pointer hover:bg-gray-50 transition-colors duration-200;
}

.section-header.active {
  @apply bg-gray-50;
}

.section-title {
  @apply text-lg font-semibold text-gray-900 flex-1;
}

.progress-indicator {
  @apply flex items-center gap-2;
}

.progress-fraction {
  @apply text-sm font-medium text-gray-600;
}

.mini-progress {
  @apply w-16 h-1 bg-gray-200 rounded-full overflow-hidden;
}

.mini-progress-fill {
  @apply h-full bg-blue-500 transition-all duration-300;
}

.acts-count {
  @apply text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded-full;
}

.toggle-icon {
  @apply w-5 h-5 text-gray-400 transition-transform duration-200;
}

.toggle-icon.rotated {
  @apply transform rotate-180;
}

.section-content {
  @apply px-6 pb-6;
}

/* 步骤列表样式 */
.steps-list {
  @apply space-y-3 mt-6;
}

.step-item {
  @apply flex items-start gap-3 p-4 rounded-lg border;
}

.step-item.completed {
  @apply bg-green-50 border-green-200;
}

.step-item.in_progress {
  @apply bg-blue-50 border-blue-200;
}

.step-item.failed {
  @apply bg-red-50 border-red-200;
}

.step-item.pending {
  @apply bg-gray-50 border-gray-200;
}

.step-indicator {
  @apply flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center;
}

.step-item.completed .step-indicator {
  @apply bg-green-100 text-green-600;
}

.step-item.in_progress .step-indicator {
  @apply bg-blue-100 text-blue-600;
}

.step-item.failed .step-indicator {
  @apply bg-red-100 text-red-600;
}

.step-item.pending .step-indicator {
  @apply bg-gray-100 text-gray-400;
}

.step-icon {
  @apply w-4 h-4;
}

.step-title {
  @apply font-medium text-gray-900 mb-1;
}

.step-description {
  @apply text-sm text-gray-600;
}

/* Act项目样式 */
.act-item {
  @apply border border-gray-200 rounded-lg mb-4 overflow-hidden;
}

.act-header {
  @apply flex items-center gap-3 p-4 cursor-pointer hover:bg-gray-50 transition-colors duration-200;
}

.act-header.active {
  @apply bg-gray-50;
}

.act-status {
  @apply flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center;
}

.act-status.completed {
  @apply bg-green-100 text-green-600;
}

.act-status.failed {
  @apply bg-red-100 text-red-600;
}

.act-icon {
  @apply w-4 h-4;
}

.act-title {
  @apply flex-1 font-medium text-gray-900;
}

.act-timestamp {
  @apply text-xs text-gray-500;
}

.act-toggle-icon {
  @apply w-4 h-4 text-gray-400 transition-transform duration-200;
}

.act-toggle-icon.rotated {
  @apply transform rotate-180;
}

.act-content {
  @apply p-4 pt-0 space-y-4;
}

/* 子区域样式 */
.thought-section, .execution-section {
  @apply border border-gray-100 rounded-lg overflow-hidden;
}

.subsection-header {
  @apply flex items-center gap-2 p-3 bg-gray-50 cursor-pointer hover:bg-gray-100 transition-colors duration-200;
}

.subsection-header.active {
  @apply bg-gray-100;
}

.subsection-title {
  @apply flex-1 text-sm font-medium text-gray-700;
}

.tool-badge {
  @apply text-xs bg-blue-100 text-blue-700 px-2 py-1 rounded-full;
}

.subsection-toggle {
  @apply w-4 h-4 text-gray-400 transition-transform duration-200;
}

.subsection-toggle.rotated {
  @apply transform rotate-180;
}

.subsection-content {
  @apply p-3 space-y-3;
}

.thought-item {
  @apply space-y-1;
}

.thought-item strong {
  @apply text-sm font-medium text-gray-700;
}

.thought-item p {
  @apply text-sm text-gray-600;
}

.execution-result {
  @apply max-w-none;
}

.raw-output {
  @apply mt-3 p-3 bg-gray-50 rounded border;
}

.raw-output-title {
  @apply text-xs font-medium text-gray-700 mb-2;
}

.raw-output-content {
  @apply text-xs text-gray-600 whitespace-pre-wrap;
}

.raw-output-toggle {
  @apply text-xs text-blue-600 hover:text-blue-700 font-medium;
}

.act-summary {
  @apply p-3 bg-blue-50 rounded-lg;
}

.summary-label {
  @apply text-sm font-medium text-blue-700 mb-1;
}

.summary-text {
  @apply text-sm text-blue-600;
}

/* 元数据样式 */
.metadata-grid {
  @apply grid grid-cols-1 md:grid-cols-2 gap-4;
}

.metadata-item {
  @apply flex justify-between items-center p-3 bg-gray-50 rounded-lg;
}

.metadata-label {
  @apply text-sm font-medium text-gray-700;
}

.metadata-value {
  @apply text-sm text-gray-900 font-mono;
}

/* 操作按钮样式 */
.actions-section {
  @apply p-6 bg-gray-50 flex flex-wrap gap-3;
}

.action-btn {
  @apply flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all duration-200;
}

.action-btn.primary {
  @apply bg-blue-600 text-white hover:bg-blue-700 shadow-sm;
}

.action-btn.secondary {
  @apply bg-gray-600 text-white hover:bg-gray-700 shadow-sm;
}

.action-btn.outline {
  @apply border border-gray-300 text-gray-700 hover:bg-gray-50;
}

.btn-icon {
  @apply w-4 h-4;
}

/* 错误和空状态样式 */
.error-section, .empty-section {
  @apply p-12 text-center;
}

.error-icon, .empty-icon {
  @apply w-16 h-16 mx-auto mb-4 text-gray-400;
}

.error-title, .empty-title {
  @apply text-xl font-semibold text-gray-900 mb-2;
}

.error-message, .empty-message {
  @apply text-gray-600 mb-6;
}

.retry-btn {
  @apply inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors duration-200;
}

/* 高级动画和微交互 */
.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.slide-fade-enter-from {
  opacity: 0;
  transform: translateY(-15px) scale(0.98);
}

.slide-fade-leave-to {
  opacity: 0;
  transform: translateY(-15px) scale(0.98);
}

/* 弹性动画 */
.bounce-in-enter-active {
  animation: bounceIn 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55);
}

@keyframes bounceIn {
  0% {
    opacity: 0;
    transform: scale(0.3) translateY(20px);
  }
  50% {
    opacity: 0.8;
    transform: scale(1.05) translateY(-5px);
  }
  70% {
    transform: scale(0.98) translateY(2px);
  }
  100% {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

/* 渐入动画 */
.fade-in-up-enter-active {
  animation: fadeInUp 0.5s ease-out;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 脉冲效果增强 */
@keyframes pulse-enhanced {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.05);
    opacity: 0.8;
  }
}

/* 悬停微交互 */
.section-header:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.act-header:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.step-item:hover {
  transform: translateX(4px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.action-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
}

.action-btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

/* 加载动画增强 */
.loading-section {
  animation: fadeInUp 0.6s ease-out;
}

.pulse-ring {
  animation: pulse-ring 2s cubic-bezier(0.455, 0.03, 0.515, 0.955) infinite;
}

.pulse-core {
  animation: pulse-core 2s cubic-bezier(0.455, 0.03, 0.515, 0.955) infinite;
}

@keyframes pulse-ring {
  0% {
    transform: scale(0.8);
    opacity: 1;
  }
  100% {
    transform: scale(2.4);
    opacity: 0;
  }
}

@keyframes pulse-core {
  0%, 100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.1);
  }
}

/* 进度条动画 */
.progress-fill {
  transition: width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  background: linear-gradient(90deg, #3b82f6, #1d4ed8, #3b82f6);
  background-size: 200% 100%;
  animation: shimmer 2s infinite;
}

@keyframes shimmer {
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
}

/* 状态指示器动画 */
.status-indicator {
  transition: all 0.3s ease;
}

.status-indicator.success {
  animation: pulse-success 2s infinite;
}

.status-indicator.error {
  animation: pulse-error 2s infinite;
}

.status-indicator.warning {
  animation: pulse-warning 2s infinite;
}

@keyframes pulse-success {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(34, 197, 94, 0);
  }
}

@keyframes pulse-error {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(239, 68, 68, 0);
  }
}

@keyframes pulse-warning {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(245, 158, 11, 0);
  }
}

/* 置信度徽章动画 */
.confidence-badge {
  transition: all 0.3s ease;
  animation: slideInRight 0.6s ease-out 0.3s both;
}

@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(30px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

/* 建议列表动画 */
.recommendation-item {
  transition: all 0.3s ease;
  animation: fadeInUp 0.5s ease-out both;
}

.recommendation-item:nth-child(1) { animation-delay: 0.1s; }
.recommendation-item:nth-child(2) { animation-delay: 0.2s; }
.recommendation-item:nth-child(3) { animation-delay: 0.3s; }
.recommendation-item:nth-child(4) { animation-delay: 0.4s; }
.recommendation-item:nth-child(5) { animation-delay: 0.5s; }

.recommendation-item:hover {
  transform: translateX(8px);
  background-color: rgba(59, 130, 246, 0.05);
}

/* 步骤列表动画 */
.step-item {
  transition: all 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  animation: slideInLeft 0.5s ease-out both;
}

.step-item:nth-child(1) { animation-delay: 0.1s; }
.step-item:nth-child(2) { animation-delay: 0.2s; }
.step-item:nth-child(3) { animation-delay: 0.3s; }
.step-item:nth-child(4) { animation-delay: 0.4s; }

@keyframes slideInLeft {
  from {
    opacity: 0;
    transform: translateX(-30px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

/* 图标旋转动画 */
.toggle-icon, .act-toggle-icon, .subsection-toggle {
  transition: transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}

.toggle-icon.rotated, .act-toggle-icon.rotated, .subsection-toggle.rotated {
  transform: rotate(180deg);
}

/* 焦点状态增强 */
.section-header:focus,
.act-header:focus,
.subsection-header:focus,
.action-btn:focus {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
}

/* 选择状态 */
.section-header:active,
.act-header:active,
.subsection-header:active {
  transform: scale(0.98);
}

/* 内容区域动画 */
.section-content,
.act-content,
.subsection-content {
  overflow: hidden;
}

/* 元数据网格动画 */
.metadata-item {
  transition: all 0.3s ease;
  animation: fadeInUp 0.5s ease-out both;
}

.metadata-item:nth-child(odd) { animation-delay: 0.1s; }
.metadata-item:nth-child(even) { animation-delay: 0.2s; }

.metadata-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

/* 响应式设计 */
@media (max-width: 768px) {
  .ai-analysis-result {
    @apply mx-2 rounded-xl;
  }
  
  .main-result {
    @apply p-4;
  }
  
  .result-header {
    @apply flex-col gap-3;
  }
  
  .result-title {
    @apply text-2xl;
  }
  
  .confidence-badge {
    @apply self-start;
  }
  
  .section-header {
    @apply p-3;
  }
  
  .section-content {
    @apply p-3;
  }
  
  .actions-section {
    @apply flex-col p-4;
  }
  
  .action-btn {
    @apply w-full justify-center py-3;
  }
  
  .metadata-grid {
    @apply grid-cols-1;
  }
  
  .step-item {
    @apply p-3;
  }
  
  .act-header {
    @apply p-3;
  }
  
  .act-content {
    @apply p-3;
  }
  
  /* 移动端触摸优化 */
  .section-header,
  .act-header,
  .subsection-header {
    @apply min-h-[48px] touch-manipulation;
  }
  
  .action-btn {
    @apply min-h-[44px] touch-manipulation;
  }
  
  /* 移动端字体调整 */
  .loading-title {
    @apply text-xl;
  }
  
  .summary-section h2,
  .findings-title,
  .recommendations-title {
    @apply text-lg;
  }
}

/* 平板设备优化 */
@media (min-width: 769px) and (max-width: 1024px) {
  .ai-analysis-result {
    @apply mx-4;
  }
  
  .metadata-grid {
    @apply grid-cols-2;
  }
  
  .actions-section {
    @apply flex-row flex-wrap;
  }
  
  .action-btn {
    @apply flex-1 min-w-[120px];
  }
}

/* 大屏幕优化 */
@media (min-width: 1440px) {
  .ai-analysis-result {
    @apply max-w-6xl;
  }
  
  .main-result {
    @apply p-10;
  }
  
  .section-content {
    @apply p-6;
  }
  
  .metadata-grid {
    @apply grid-cols-3;
  }
}

/* 触摸设备优化 */
@media (hover: none) and (pointer: coarse) {
  .section-header:hover,
  .act-header:hover,
  .step-item:hover,
  .action-btn:hover,
  .metadata-item:hover,
  .recommendation-item:hover {
    transform: none;
    box-shadow: none;
  }
  
  .section-header:active,
  .act-header:active,
  .action-btn:active {
    transform: scale(0.98);
    transition: transform 0.1s ease;
  }
}

/* 高分辨率屏幕优化 */
@media (-webkit-min-device-pixel-ratio: 2), (min-resolution: 192dpi) {
  .pulse-ring,
  .pulse-core {
    @apply border-2;
  }
  
  .status-indicator {
    @apply border border-gray-200;
  }
}

/* 无障碍访问 */
@media (prefers-reduced-motion: reduce) {
  .slide-fade-enter-active,
  .slide-fade-leave-active,
  .toggle-icon,
  .act-toggle-icon,
  .subsection-toggle {
    transition: none;
  }
  
  .pulse-ring {
    animation: none;
  }
}

/* 高对比度模式 */
@media (prefers-contrast: high) {
  .ai-analysis-result {
    @apply border-2 border-gray-900;
  }
  
  .section-header:hover,
  .act-header:hover,
  .subsection-header:hover {
    @apply bg-gray-200;
  }
}

/* 动画性能优化 */
.ai-analysis-result {
  /* 启用硬件加速 */
  transform: translateZ(0);
  backface-visibility: hidden;
  perspective: 1000px;
}

.ai-analysis-result * {
  will-change: auto;
}

.section-header,
.act-header,
.action-btn,
.step-item,
.metadata-item,
.recommendation-item {
  will-change: transform, opacity;
  /* 优化重绘性能 */
  contain: layout style paint;
}

.loading-spinner,
.pulse-ring,
.pulse-core,
.progress-bar,
.status-indicator {
  will-change: transform;
  /* 强制GPU加速 */
  transform: translateZ(0);
}

/* 减少重排重绘 */
.section-content,
.act-content,
.raw-output {
  contain: layout;
}

/* 优化滚动性能 */
.section-content,
.act-content {
  overflow-anchor: none;
}

/* 预加载关键动画 */
@keyframes preload-animations {
  0% { transform: translateY(0); opacity: 1; }
  1% { transform: translateY(-1px); opacity: 0.99; }
  100% { transform: translateY(0); opacity: 1; }
}

.ai-analysis-result::before {
  content: '';
  animation: preload-animations 0.01s;
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

/* 防止动画卡顿 */
@media (prefers-reduced-motion: no-preference) {
  .section-header,
  .act-header,
  .action-btn,
  .step-item {
    transition-timing-function: cubic-bezier(0.4, 0, 0.2, 1);
  }
}

/* 低性能设备优化 */
@media (max-width: 768px) and (max-height: 1024px) {
  .section-header:hover,
  .act-header:hover,
  .action-btn:hover,
  .step-item:hover {
    transform: none;
  }
  
  .loading-spinner {
    animation-duration: 1.5s;
  }
  
  .pulse-ring {
    animation-duration: 2.5s;
  }
}

/* 打印样式 */
@media print {
  .actions-section,
  .toggle-icon,
  .act-toggle-icon,
  .subsection-toggle {
    @apply hidden;
  }
  
  .section-content,
  .act-content,
  .subsection-content {
    @apply !block;
  }
}
</style>