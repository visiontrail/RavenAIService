<script setup lang="ts">
import { computed, onMounted, onUnmounted, nextTick, ref, watch } from 'vue'
import { deviceLinkApi } from '@/api/deviceLink'
import { searchPackagesByAgent, getRavenPackageDetail, ravenBaseUrl } from '@/api/raven'
import { userApi } from '@/api/user'
import type {
  DeviceInfo,
  PackageAgentSearchResponse,
  RavenPackage,
  ChatMessageRecord,
} from '@/types'
import { renderMarkdown } from '@/utils/markdownRenderer'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
import { useChatSessionStore } from '@/stores/chatSession'
import AgentTraceStream from '@/components/AgentTraceStream.vue'
import type { AgentTraceEvent } from '@/types/agentTrace'

type MentionOption =
  | { type: 'agent'; id: string; name: string; description?: string; agentType: 'package-manager' | 'log-analysis' }
  | { type: 'device'; id: string; name: string; status: DeviceInfo['status']; device: DeviceInfo }

const packageAgentOption: MentionOption = {
  type: 'agent',
  id: 'package-manager',
  name: '重构包配置管理员',
  agentType: 'package-manager',
  description: '调用重构包智能搜索，返回详情、下载链接与重构提示词'
}

const logAnalysisAgentOption: MentionOption = {
  type: 'agent',
  id: 'log-analysis',
  name: '日志分析',
  agentType: 'log-analysis',
  description: '上传日志包并调用 Log Analysis Agent，保留工作区支持追问'
}

const userStore = useUserStore()
const appStore = useAppStore()
const sessionStore = useChatSessionStore()

type ChatRole = 'user' | 'ai' | 'system'
type ChatEntry = {
  id: string
  role: ChatRole
  content: string
  kind?: 'plan' | 'device_action' | 'answer' | 'user'
  traceEvents?: AgentTraceEvent[]
  traceRunning?: boolean
}

const generateUUID = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

const inputMessage = ref('')
const chatContainerRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const inputAreaRef = ref<HTMLElement | null>(null)
const mentionDropdownRef = ref<HTMLElement | null>(null)
const topMoreMenuRef = ref<HTMLElement | null>(null)
const topMoreBtnRef = ref<HTMLElement | null>(null)
const logFileInputRef = ref<HTMLInputElement | null>(null)

const devices = ref<DeviceInfo[]>([])
const isLoadingDevices = ref(false)

const mentionVisible = ref(false)
const mentionKeyword = ref('')
const mentionSelectedIndex = ref(0)
const mentionOptionRefs = ref<(HTMLElement | null)[]>([])
const mentionStart = ref<number | null>(null)

const targetDeviceId = ref<string | null>(null)
const targetDeviceName = ref<string | null>(null)
const targetAgent = ref<{ id: string; name: string; agentType: 'package-manager' | 'log-analysis' } | null>(null)
const selectedLogFile = ref<File | null>(null)

const showTopMoreMenu = ref(false)

const loadingMessages = ref(false)
const chatHistory = ref<ChatEntry[]>([])
const sessionId = ref<string | null>(null)
const isSending = ref(false)
const activeLogAnalysisSessionId = ref<string | null>(null)
const cancelInFlight = ref(false)

const isLoggedIn = computed(() => userStore.isAuthenticated)
const currentUserName = computed(() => userStore.profile?.display_name || userStore.profile?.username || '用户')

const isWelcomeMode = computed(() => chatHistory.value.length === 0 && !loadingMessages.value)

const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as Node

  if (showTopMoreMenu.value && topMoreMenuRef.value && topMoreBtnRef.value &&
      !topMoreMenuRef.value.contains(target) && !topMoreBtnRef.value.contains(target)) {
    showTopMoreMenu.value = false
  }

  if (mentionVisible.value && mentionDropdownRef.value && inputAreaRef.value &&
      !mentionDropdownRef.value.contains(target) && !inputAreaRef.value.contains(target)) {
    mentionVisible.value = false
    mentionKeyword.value = ''
    mentionStart.value = null
  }
}

const handleKey = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    showTopMoreMenu.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKey)
  fetchDevices()
  // If sidebar previously selected a session, load its messages now that the panel is mounted.
  if (sessionStore.selectedSessionId && isLoggedIn.value) {
    loadMessages(sessionStore.selectedSessionId)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKey)
})

const scrollToBottom = async () => {
  await nextTick()
  if (chatContainerRef.value) {
    chatContainerRef.value.scrollTop = chatContainerRef.value.scrollHeight
  }
}

watch(chatHistory, () => { scrollToBottom() }, { deep: true })

watch(() => sessionStore.selectSessionToken, () => {
  const id = sessionStore.selectedSessionId
  if (id && isLoggedIn.value) loadMessages(id)
})

watch(() => sessionStore.newChatToken, () => {
  resetPanel()
})

watch(isLoggedIn, (loggedIn) => {
  if (!loggedIn) {
    chatHistory.value = []
    sessionId.value = null
  }
})

const getServiceUrl = (path: string) => {
  const hostname = window.location.hostname
  return `http://${hostname}:8085${path}`
}

const fetchDevices = async () => {
  isLoadingDevices.value = true
  try {
    const res = await deviceLinkApi.listDevices()
    devices.value = res.devices || []
  } catch (error) {
    console.error('加载设备列表失败', error)
  } finally {
    isLoadingDevices.value = false
  }
}

const loadMessages = async (id: string) => {
  if (!isLoggedIn.value) return
  loadingMessages.value = true
  chatHistory.value = []
  sessionId.value = id
  try {
    const resp = await userApi.fetchMessages(id)
    if (resp?.success && Array.isArray(resp.data)) {
      chatHistory.value = (resp.data as ChatMessageRecord[]).map((item) => ({
        id: item.id || generateUUID(),
        role: (item.role === 'assistant' ? 'ai' : item.role) as ChatRole,
        content: item.content || '',
        kind: item.role === 'user' ? 'user' : 'answer',
      }))
    }
  } catch (error) {
    console.error('加载会话消息失败', error)
    appStore.showNotification({ title: '加载消息失败', type: 'error' })
  } finally {
    loadingMessages.value = false
  }
}

const resetPanel = () => {
  sessionId.value = null
  chatHistory.value = []
  inputMessage.value = ''
  resetMentionState()
  nextTick(() => textareaRef.value?.focus())
}

const clearCurrentMessages = () => {
  showTopMoreMenu.value = false
  if (!chatHistory.value.length) return
  if (!window.confirm('确定要清空当前消息吗？')) return
  chatHistory.value = []
}

const deleteCurrentSession = async () => {
  showTopMoreMenu.value = false
  const id = sessionStore.selectedSessionId
  if (!id) return
  const confirmed = window.confirm('确定要删除该对话吗？此操作不可恢复。')
  if (!confirmed) return
  try {
    await sessionStore.removeSession(id)
    appStore.showNotification({ title: '会话已删除', type: 'success' })
  } catch (error) {
    console.error('删除会话失败', error)
    appStore.showNotification({ title: '删除失败', type: 'error' })
  }
}

const mentionOptions = computed<MentionOption[]>(() => {
  const deviceOptions: MentionOption[] = devices.value
    .slice()
    .sort((a, b) => (a.status === b.status ? 0 : a.status === 'online' ? -1 : 1))
    .map((device) => ({
      type: 'device',
      id: device.id,
      name: device.name || device.id,
      status: device.status,
      device,
    }))
  return [packageAgentOption, logAnalysisAgentOption, ...deviceOptions]
})

const filteredMentionOptions = computed(() => {
  const keyword = mentionKeyword.value.trim().toLowerCase()
  const list = mentionOptions.value
  if (!keyword) return list
  return list.filter((option) => `${option.name} ${option.id}`.toLowerCase().includes(keyword))
})

watch(filteredMentionOptions, (list) => {
  if (mentionSelectedIndex.value >= list.length) mentionSelectedIndex.value = 0
  mentionOptionRefs.value = []
})

watch(mentionSelectedIndex, (idx) => {
  const el = mentionOptionRefs.value[idx]
  if (el?.scrollIntoView) el.scrollIntoView({ block: 'nearest' })
})

const targetAgentName = computed(() => targetAgent.value?.name || null)
const isPackageAgentSelected = computed(() => targetAgent.value?.agentType === 'package-manager')
const isLogAnalysisAgentSelected = computed(() =>
  targetAgent.value?.agentType === 'log-analysis' || !!selectedLogFile.value
)

const resetMentionState = () => {
  mentionVisible.value = false
  mentionKeyword.value = ''
  mentionSelectedIndex.value = 0
  mentionStart.value = null
}

const setTargetAgent = (option: MentionOption & { type: 'agent' }) => {
  targetAgent.value = { id: option.id, name: option.name, agentType: option.agentType }
  targetDeviceId.value = null
  targetDeviceName.value = null
}

const renderAiMessage = (content: string) =>
  renderMarkdown(content || '', { wrapperClass: 'markdown-content text-ink' })

const packageTypeText = (type?: string) => {
  const map: Record<string, string> = {
    'lingxi-10': 'LingXi-10',
    'lingxi-07a': 'LingXi-07A',
    'ka-tx': 'KaTx',
    'ka-rx': 'KaRx',
    config: '配置包',
    'lingxi-06-thrid': 'LingXi-06-TRD',
  }
  return map[type || ''] || type || '未知类型'
}

const buildRebuildPrompt = (downloadLink: string) =>
  `请你帮忙下载${downloadLink}并上传到设备ftp，然后请向基带处理机发送重构包下载请求后，启动卫星升级流程`

const buildPackageLinks = (pkg: RavenPackage) => {
  const detailLink = `${ravenBaseUrl}/package/${encodeURIComponent(pkg.id)}`
  const downloadLink = `${ravenBaseUrl}/api/download/${encodeURIComponent(pkg.id)}`
  return { detailLink, downloadLink, prompt: buildRebuildPrompt(downloadLink) }
}

const formatPackageAgentAnswer = (
  result: PackageAgentSearchResponse,
  recommendedPackages: RavenPackage[],
  rawQuery: string
) => {
  const query = rawQuery.trim() || '（未提供查询）'
  const lines: string[] = [`**重构包配置管理员** 已为你执行智能搜索：\`${query}\``]

  const pushPackageLines = (pkg: RavenPackage) => {
    const links = buildPackageLinks(pkg)
    lines.push(
      `## ${pkg.name || pkg.id} ⭐ AI 推荐 （${packageTypeText(pkg.packageType)} · v${pkg.version || '未知'}）`
    )
    if (pkg.metadata?.description) lines.push(`- 描述：${pkg.metadata.description}`)
    lines.push(
      `- 详情链接：[${links.detailLink}](${links.detailLink})`,
      `- 下载链接：[${links.downloadLink}](${links.downloadLink})`,
      '- 重构提示词：',
      `  \`${links.prompt}\``
    )
  }

  if (result.answer) lines.push('', result.answer)
  if (recommendedPackages.length > 0) {
    lines.push('', `# Raven AI 推荐的重构包（${recommendedPackages.length} 个）：`)
    recommendedPackages.forEach(pushPackageLines)
  } else {
    lines.push('', '未找到匹配的重构包。')
  }
  return lines.join('\n')
}

const updateMentionState = (event?: Event) => {
  const value = inputMessage.value
  const target = (event?.target as HTMLTextAreaElement | null) || textareaRef.value
  const cursor = target?.selectionStart ?? value.length
  const lastAt = value.lastIndexOf('@', cursor - 1)
  if (lastAt === -1) { resetMentionState(); return }
  const afterAt = value.slice(lastAt + 1, cursor)
  if (afterAt.includes(' ') || afterAt.includes('\n') || afterAt.includes('\t')) {
    resetMentionState(); return
  }
  mentionVisible.value = true
  mentionKeyword.value = afterAt
  mentionSelectedIndex.value = 0
  mentionStart.value = lastAt
}

const setMentionOptionRef = (el: Element | null, idx: number) => {
  mentionOptionRefs.value[idx] = el as HTMLElement | null
}

const applyMentionSelection = (option: MentionOption) => {
  if (option.type === 'device') {
    targetDeviceId.value = option.id
    targetDeviceName.value = option.name
    targetAgent.value = null
  } else {
    setTargetAgent(option)
  }

  const value = inputMessage.value
  const cursor = textareaRef.value?.selectionStart ?? value.length
  if (mentionStart.value !== null) {
    const before = value.slice(0, mentionStart.value)
    const after = value.slice(cursor)
    const insertion = `@${option.name} `
    inputMessage.value = `${before}${insertion}${after}`
    nextTick(() => {
      const pos = before.length + insertion.length
      textareaRef.value?.setSelectionRange(pos, pos)
    })
  } else {
    const insertion = `@${option.name} `
    inputMessage.value = value ? `${value} ${insertion}` : insertion
  }
  resetMentionState()
}

const clearTargetDevice = () => { targetDeviceId.value = null; targetDeviceName.value = null }
const clearTargetAgent = () => { targetAgent.value = null }
const clearSelectedLogFile = () => { selectedLogFile.value = null }

const triggerLogFilePicker = () => {
  if (isSending.value) return
  setTargetAgent(logAnalysisAgentOption)
  logFileInputRef.value?.click()
}

const handleLogFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  if (file) {
    selectedLogFile.value = file
    setTargetAgent(logAnalysisAgentOption)
  }
  input.value = ''
}

const togglePackageAgent = () => {
  if (isPackageAgentSelected.value) {
    clearTargetAgent()
    return
  }
  selectedLogFile.value = null
  setTargetAgent(packageAgentOption)
}

const toggleLogAnalysisAgent = () => {
  if (targetAgent.value?.agentType === 'log-analysis' && !selectedLogFile.value) {
    clearTargetAgent()
    return
  }
  setTargetAgent(logAnalysisAgentOption)
}

const findMessageIndex = (id: string) => chatHistory.value.findIndex((msg) => msg.id === id)

const ensureAnswerMessage = (answerId: string): ChatEntry => {
  const idx = findMessageIndex(answerId)
  if (idx !== -1) return chatHistory.value[idx]
  const fallback: ChatEntry = { id: answerId, role: 'ai', content: '正在思考...', kind: 'answer' }
  chatHistory.value.push(fallback)
  return fallback
}

const insertBeforeAnswer = (answerId: string, entry: ChatEntry) => {
  const idx = findMessageIndex(answerId)
  if (idx === -1) chatHistory.value.push(entry)
  else chatHistory.value.splice(idx, 0, entry)
}

const formatPlanMessage = (steps: any[]) => {
  if (!Array.isArray(steps) || steps.length === 0) return '未生成计划。'
  const lines: string[] = ['**计划步骤**']
  steps.forEach((step, index) => {
    const id = step?.id || `S${index + 1}`
    const type = step?.type ? ` (${step.type})` : ''
    const goal = step?.goal || '无描述'
    lines.push(`- ${id}${type}: ${goal}`)
    if (Array.isArray(step?.success_criteria) && step.success_criteria.length) {
      lines.push(`  - 验证: ${step.success_criteria.join('; ')}`)
    }
  })
  return lines.join('\n')
}

const formatDeviceActionMessage = (payload: any) => {
  const order = typeof payload?.step_index === 'number' ? payload.step_index + 1 : null
  const label = payload?.step_id || (order ? `步骤${order}` : '设备动作')
  const goal = payload?.step_goal ? `：${payload.step_goal}` : ''
  const lines: string[] = [`**设备动作 ${label}${goal}**`]
  const answerText =
    typeof payload?.answer === 'string' ? payload.answer
      : payload?.answer ? String(payload.answer) : ''
  if (answerText) lines.push(answerText)
  else if (payload?.raw) lines.push(String(payload.raw))
  else lines.push('无返回内容')
  if (payload?.topic_id) lines.push(`- 话题ID: ${payload.topic_id}`)
  return lines.join('\n')
}

const applyStreamEvent = (payload: any, answerId: string) => {
  const type = payload?.event || payload?.type
  if (payload?.session_id) {
    sessionId.value = payload.session_id
    sessionStore.setSelected(payload.session_id)
  }
  if (type === 'plan') {
    insertBeforeAnswer(answerId, { id: generateUUID(), role: 'ai', content: formatPlanMessage(payload?.plan), kind: 'plan' })
    return
  }
  if (type === 'device_action') {
    insertBeforeAnswer(answerId, { id: generateUUID(), role: 'ai', content: formatDeviceActionMessage(payload), kind: 'device_action' })
    return
  }
  if (type === 'log_analysis_status') {
    const targetMessage = ensureAnswerMessage(answerId)
    const statusText = payload?.message || 'Log Analysis Agent 正在处理...'
    targetMessage.content = `**日志分析 Agent**\n\n${statusText}`
    return
  }
  if (type === 'agent_trace') {
    const targetMessage = ensureAnswerMessage(answerId)
    if (!targetMessage.traceEvents) targetMessage.traceEvents = []
    targetMessage.traceRunning = true
    // Strip the SSE-level `event` field; the inner `type` is the trace
    // event variant. Composable de-dupes by seq, so replayed frames on
    // reconnect are safe.
    const { event: _evt, ...trace } = payload as Record<string, unknown>
    if (trace && typeof trace.seq === 'number' && typeof trace.type === 'string') {
      targetMessage.traceEvents.push(trace as unknown as AgentTraceEvent)
    }
    return
  }
  if (type === 'log_analysis_context') return
  if (type === 'session') return
  const targetMessage = ensureAnswerMessage(answerId)
  if (type === 'chunk' && typeof payload?.content === 'string') {
    const chunk = payload.content
    if (targetMessage.content === '正在思考...') {
      const trimmedChunk = chunk.trimStart()
      if (trimmedChunk) targetMessage.content = trimmedChunk
    } else {
      targetMessage.content += chunk
    }
  } else if (type === 'done') {
    if (typeof payload?.answer === 'string' && payload.answer) targetMessage.content = payload.answer.trimStart()
    else if (!targetMessage.content || targetMessage.content === '正在思考...') targetMessage.content = '（无回复内容）'
    targetMessage.traceRunning = false
  } else if (type === 'error') {
    targetMessage.content = `调用后端失败：${payload?.message || '未知错误'}`
    targetMessage.traceRunning = false
  }
}

const processSseBuffer = (buffer: string, answerId: string) => {
  let remaining = buffer.replace(/\r\n/g, '\n')
  while (true) {
    const idx = remaining.indexOf('\n\n')
    if (idx === -1) break
    const raw = remaining.slice(0, idx)
    remaining = remaining.slice(idx + 2)
    const trimmed = raw.trim()
    if (!trimmed.startsWith('data:')) continue
    const jsonStr = trimmed.replace(/^data:\s*/, '')
    if (!jsonStr) continue
    try { applyStreamEvent(JSON.parse(jsonStr), answerId) }
    catch (err) { console.error('解析流式数据失败', err, jsonStr) }
  }
  return remaining
}

const handleKeydown = (event: KeyboardEvent) => {
  if (mentionVisible.value && filteredMentionOptions.value.length > 0) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      mentionSelectedIndex.value = (mentionSelectedIndex.value + 1) % filteredMentionOptions.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      mentionSelectedIndex.value = (mentionSelectedIndex.value - 1 + filteredMentionOptions.value.length) % filteredMentionOptions.value.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      const option = filteredMentionOptions.value[mentionSelectedIndex.value]
      if (option) applyMentionSelection(option)
      return
    }
  }
  if (event.key === 'Escape' && mentionVisible.value) { resetMentionState(); return }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

const handleInput = (event: Event) => updateMentionState(event)

const extractPackageQuery = (content: string) => content.replace(/@重构包配置管理员/g, '').trim()
const extractLogAnalysisQuery = (content: string) => content.replace(/@日志分析/g, '').trim()

const runPackageAgent = async (content: string, answerId: string) => {
  const query = extractPackageQuery(content)
  const targetMessage = ensureAnswerMessage(answerId)
  if (!query) {
    targetMessage.content = '请描述需要查找的重构包需求，例如型号、版本或用途。'
    return
  }
  try {
    const { data } = await searchPackagesByAgent(query)
    if (!data) throw new Error('智能搜索返回为空')
    const recommendedIds = data.recommended_package_ids || []
    const recommendedPackages: RavenPackage[] = []
    for (const id of recommendedIds) {
      try {
        const detail = await getRavenPackageDetail(id)
        if (detail.data?.success && detail.data.data) recommendedPackages.push(detail.data.data)
      } catch (err) {
        console.warn('拉取推荐包详情失败', id, err)
      }
    }
    const aiContent = formatPackageAgentAnswer(data, recommendedPackages, query)
    targetMessage.content = aiContent
    if (isLoggedIn.value) {
      if (!sessionId.value) {
        sessionId.value = generateUUID()
        sessionStore.setSelected(sessionId.value)
      }
      try {
        await userApi.saveMessages(sessionId.value, content, aiContent, content.slice(0, 60))
        await sessionStore.load()
      } catch (error: any) {
        console.warn('保存重构包配置管理员对话失败', error)
      }
    }
  } catch (error: any) {
    console.error('重构包配置管理员调用失败', error)
    targetMessage.content = `重构包配置管理员调用失败：${error?.message || String(error)}`
  }
}

const buildAuthHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {}
  const authToken = userStore.token as unknown as string
  if (isLoggedIn.value && authToken) headers.Authorization = `Bearer ${authToken}`
  return headers
}

const consumeLogAnalysisStream = async (
  resp: Response,
  answerId: string,
): Promise<{ done: boolean }> => {
  // Reads the SSE body and returns { done: true } if the server emitted a
  // terminal `done`/`error` event; otherwise { done: false } meaning the
  // connection ended early and the caller should reconnect or poll.
  if (!resp.body) throw new Error('响应体为空，无法流式读取')

  const textStream = typeof TextDecoderStream !== 'undefined'
    ? resp.body.pipeThrough(new TextDecoderStream()) : null
  const reader = textStream ? textStream.getReader() : null
  const binaryReader = !textStream ? resp.body.getReader() : null
  const decoder = !textStream ? new TextDecoder('utf-8') : null
  let buffer = ''
  let terminal = false

  const processChunk = (chunk: string) => {
    buffer += chunk
    let remaining = buffer.replace(/\r\n/g, '\n')
    while (true) {
      const idx = remaining.indexOf('\n\n')
      if (idx === -1) break
      const raw = remaining.slice(0, idx)
      remaining = remaining.slice(idx + 2)
      const trimmed = raw.trim()
      if (!trimmed.startsWith('data:')) continue
      const jsonStr = trimmed.replace(/^data:\s*/, '')
      if (!jsonStr) continue
      try {
        const payload = JSON.parse(jsonStr)
        applyStreamEvent(payload, answerId)
        const type = payload?.event || payload?.type
        if (type === 'done' || type === 'error') terminal = true
      } catch (err) {
        console.error('解析流式数据失败', err, jsonStr)
      }
    }
    buffer = remaining
  }

  if (reader) {
    while (true) {
      const { value, done } = await reader.read()
      if (value) processChunk(value)
      if (done) break
    }
  } else if (binaryReader && decoder) {
    while (true) {
      const { value, done } = await binaryReader.read()
      if (value) processChunk(decoder.decode(value, { stream: !done }))
      if (done) break
    }
  }
  if (buffer.trim()) processChunk('\n\n')
  return { done: terminal }
}

const pollLogAnalysisResult = async (
  pollSessionId: string,
  answerId: string,
): Promise<boolean> => {
  // Last-resort fallback when SSE keeps failing. Polls `/result` until the
  // server reports the Job is done, then renders the final events.
  let renderedCount = 0
  const headers = buildAuthHeaders()
  const startedAt = Date.now()
  const maxMs = 60 * 60 * 1000

  while (Date.now() - startedAt < maxMs) {
    try {
      const resp = await fetch(
        getServiceUrl(`/api/v1/ai-chat/log-analysis/result?session_id=${encodeURIComponent(pollSessionId)}`),
        { headers },
      )
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const snapshot = await resp.json()
      const events: any[] = Array.isArray(snapshot?.events) ? snapshot.events : []
      for (let i = renderedCount; i < events.length; i++) {
        applyStreamEvent(events[i], answerId)
      }
      renderedCount = events.length
      if (snapshot?.status === 'done') return true
      if (snapshot?.status === 'not_found') {
        // Job dropped from registry (process restart / retention expired).
        return false
      }
    } catch (err) {
      console.warn('轮询日志分析结果失败，将重试', err)
    }
    await new Promise(resolve => setTimeout(resolve, 3000))
  }
  return false
}

const runLogAnalysisAgent = async (
  content: string,
  answerId: string,
  historyPayload: { role: string; content: string }[],
  fileForRequest: File | null,
) => {
  const query = extractLogAnalysisQuery(content) || (fileForRequest
    ? '请分析这个日志包，给出概览、可疑异常和下一步建议。'
    : '')
  const targetMessage = ensureAnswerMessage(answerId)
  if (!query && !fileForRequest) {
    targetMessage.content = '请先上传日志包，或基于当前日志分析上下文输入一个追问。'
    return
  }

  if (!sessionId.value) {
    sessionId.value = generateUUID()
    sessionStore.setSelected(sessionId.value)
  }
  activeLogAnalysisSessionId.value = sessionId.value

  const formData = new FormData()
  formData.append('message', query)
  formData.append('session_id', sessionId.value)
  formData.append('remember', 'true')
  formData.append('history', JSON.stringify(historyPayload))
  if (fileForRequest) formData.append('file', fileForRequest)

  if (fileForRequest) selectedLogFile.value = null

  const headers = buildAuthHeaders()

  try {
    let resp: Response
    try {
      resp = await fetch(getServiceUrl('/api/v1/ai-chat/log-analysis/stream'), {
        method: 'POST',
        headers,
        body: formData,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    } catch (initialError) {
      // Initial request itself failed (server unreachable, etc.). Restore the
      // file so the user can retry.
      if (fileForRequest) selectedLogFile.value = fileForRequest
      throw initialError
    }

    let result = await consumeLogAnalysisStream(resp, answerId).catch(err => {
      console.warn('SSE 流读取中断，将尝试重连', err)
      return { done: false }
    })

    // The Agent Job lives on the server independent of this SSE. If the SSE
    // closed early without a terminal event, reconnect with the same
    // session_id (no file) to resume; on repeated failure, poll /result.
    let attempts = 0
    const maxReconnects = 3
    while (!result.done && attempts < maxReconnects) {
      attempts += 1
      await new Promise(resolve => setTimeout(resolve, 1000 * attempts))
      try {
        const reconnectForm = new FormData()
        reconnectForm.append('message', '')
        reconnectForm.append('session_id', sessionId.value!)
        reconnectForm.append('remember', 'false')
        const r2 = await fetch(getServiceUrl('/api/v1/ai-chat/log-analysis/stream'), {
          method: 'POST',
          headers,
          body: reconnectForm,
        })
        if (!r2.ok) throw new Error(`HTTP ${r2.status}`)
        result = await consumeLogAnalysisStream(r2, answerId)
      } catch (err) {
        console.warn(`SSE 重连第 ${attempts} 次失败`, err)
      }
    }

    if (!result.done) {
      // Reconnect exhausted — fall back to polling.
      const polled = await pollLogAnalysisResult(sessionId.value!, answerId)
      if (!polled) {
        const fallback = ensureAnswerMessage(answerId)
        if (fallback.content === '正在思考...') {
          fallback.content = '分析任务运行时间过长或被服务端清理，请稍后查询会话历史。'
        }
      }
    }

    const answerMessage = ensureAnswerMessage(answerId)
    if (answerMessage.content === '正在思考...') answerMessage.content = '（无回复内容）'

    if (isLoggedIn.value) {
      try { await sessionStore.load() } catch (error) { console.warn('刷新会话列表失败', error) }
    }
  } catch (error: any) {
    console.error('日志分析调用失败', error)
    if (fileForRequest) selectedLogFile.value = fileForRequest
    targetMessage.content = `日志分析调用失败：${error?.message || String(error)}`
  } finally {
    if (activeLogAnalysisSessionId.value === sessionId.value) {
      activeLogAnalysisSessionId.value = null
    }
    cancelInFlight.value = false
  }
}

const cancelLogAnalysis = async () => {
  const sid = activeLogAnalysisSessionId.value
  if (!sid || cancelInFlight.value) return
  cancelInFlight.value = true
  try {
    const resp = await fetch(getServiceUrl('/api/v1/ai-chat/log-analysis/cancel'), {
      method: 'POST',
      headers: { ...buildAuthHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid }),
    })
    if (!resp.ok) {
      console.warn('取消日志分析失败', await resp.text())
    }
  } catch (err) {
    console.warn('取消日志分析请求失败', err)
  }
  // cancelInFlight stays true until the agent emits its `done` event;
  // runLogAnalysisAgent's finally block clears it.
}

const triggerSessionSummary = (userContent: string, sid: string | null) => {
  if (!userContent || !userContent.trim()) return
  // Fire-and-forget: lightweight model 立即生成会话摘要，作为历史侧边栏标题。
  userApi
    .summarizeUserMessage({
      user_content: userContent,
      session_id: sid || undefined,
      max_length: 16,
      persist: isLoggedIn.value,
    })
    .then((resp) => {
      const summary = (resp?.summary || '').trim()
      const resolvedId = resp?.session_id || sid
      if (!summary || !resolvedId) return
      if (isLoggedIn.value) {
        sessionStore.upsertSessionTitle(resolvedId, summary)
      }
    })
    .catch((err) => {
      console.warn('生成会话摘要失败', err)
    })
}

const sendMessage = async () => {
  if (isSending.value) return
  const content = inputMessage.value.trim()
  const fileForRequest = selectedLogFile.value
  if (!content && !fileForRequest) return

  // 预分配 session_id，确保摘要与对话流引用同一会话。
  if (!sessionId.value) {
    sessionId.value = generateUUID()
    sessionStore.setSelected(sessionId.value)
  }
  // 立即触发轻量级模型摘要，更新历史侧边栏标题。
  if (content) {
    triggerSessionSummary(content, sessionId.value)
  }

  const shouldUseLogAnalysisAgent =
    isLogAnalysisAgentSelected.value || content.includes(`@${logAnalysisAgentOption.name}`) || !!fileForRequest

  const shouldUsePackageAgent =
    !shouldUseLogAnalysisAgent &&
    (isPackageAgentSelected.value || content.includes(`@${packageAgentOption.name}`))

  if (shouldUseLogAnalysisAgent && targetAgent.value?.agentType !== 'log-analysis') {
    setTargetAgent(logAnalysisAgentOption)
  }

  if (shouldUsePackageAgent && !isPackageAgentSelected.value) {
    setTargetAgent(packageAgentOption)
  }

  const outgoingContent = content || '请分析这个日志包。'
  const userDisplayContent = fileForRequest
    ? `${outgoingContent}\n\n附件：${fileForRequest.name}`
    : outgoingContent
  const userMessage: ChatEntry = { id: generateUUID(), role: 'user', content: userDisplayContent, kind: 'user' }
  chatHistory.value.push(userMessage)

  const historyPayload = isLoggedIn.value
    ? []
    : chatHistory.value.slice(0, -1).map(msg => ({ role: msg.role, content: msg.content }))

  const answerMessageId = generateUUID()
  chatHistory.value.push({
    id: answerMessageId,
    role: 'ai',
    content: '正在思考...',
    kind: 'answer',
    traceEvents: shouldUseLogAnalysisAgent ? [] : undefined,
    traceRunning: shouldUseLogAnalysisAgent ? true : undefined,
  })

  inputMessage.value = ''
  resetMentionState()
  isSending.value = true

  try {
    if (shouldUseLogAnalysisAgent) {
      await runLogAnalysisAgent(outgoingContent, answerMessageId, historyPayload, fileForRequest)
      return
    }

    if (shouldUsePackageAgent) {
      await runPackageAgent(outgoingContent, answerMessageId)
      return
    }

    const payload = {
      message: outgoingContent,
      session_id: sessionId.value || undefined,
      history: historyPayload,
      remember: true,
      target_device_id: targetDeviceId.value || undefined,
      target_device_name: targetDeviceName.value || undefined
    }
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    const authToken = userStore.token as unknown as string
    if (isLoggedIn.value && authToken) headers.Authorization = `Bearer ${authToken}`

    const resp = await fetch(getServiceUrl('/api/v1/ai-chat/chat/stream'), {
      method: 'POST', headers, body: JSON.stringify(payload)
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    if (!resp.body) throw new Error('响应体为空，无法流式读取')

    const textStream = resp.body && typeof TextDecoderStream !== 'undefined'
      ? resp.body.pipeThrough(new TextDecoderStream()) : null
    const reader = textStream ? textStream.getReader() : null
    const binaryReader = !textStream && resp.body ? resp.body.getReader() : null
    const decoder = !textStream ? new TextDecoder('utf-8') : null
    let buffer = ''

    if (reader) {
      while (true) {
        const { value, done } = await reader.read()
        if (value) { buffer += value; buffer = processSseBuffer(buffer, answerMessageId) }
        if (done) break
      }
    } else if (binaryReader && decoder) {
      while (true) {
        const { value, done } = await binaryReader.read()
        if (value) {
          const decoded = decoder.decode(value, { stream: !done })
          buffer += decoded
          buffer = processSseBuffer(buffer, answerMessageId)
        }
        if (done) break
      }
    }
    if (buffer.trim()) processSseBuffer(buffer + '\n\n', answerMessageId)

    const answerMessage = ensureAnswerMessage(answerMessageId)
    if (answerMessage.content === '正在思考...') answerMessage.content = '（无回复内容）'

    if (isLoggedIn.value) {
      try { await sessionStore.load() } catch (error) { console.warn('刷新会话列表失败', error) }
    }
  } catch (error: any) {
    console.error('请求失败', error)
    ensureAnswerMessage(answerMessageId).content = `调用后端失败：${error?.message || String(error)}`
  } finally {
    isSending.value = false
  }
}

const welcomeGreeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '凌晨好'
  if (h < 11) return '早上好'
  if (h < 13) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const capabilityCards = [
  { icon: 'box', label: '检索重构包',
    desc: '按版本、组件或修复内容找到正确的基带包，并对比 changelog。',
    prompt: '帮我找一下 V3.2.1 之后修过 LDPC 译码器的基带包。' },
  { icon: 'device', label: '自然语言控设备',
    desc: '说人话即可下发参数；下发前会展示差异并请你确认。',
    prompt: '把 SAT-Node-07 切到 LDPC 闭环回环模式，码率 1/2。' },
  { icon: 'logs', label: '智能日志分析',
    desc: '粘贴或上传日志，自动定位异常并给出回流建议。',
    prompt: '分析一下这段失锁告警日志，看看根因和相关提交。' },
]

const onPickCapability = (prompt: string) => {
  inputMessage.value = prompt
  if (prompt.includes('日志')) setTargetAgent(logAnalysisAgentOption)
  nextTick(() => textareaRef.value?.focus())
}

const currentChatTitle = computed(() => {
  if (sessionStore.currentTitle) return sessionStore.currentTitle
  if (isWelcomeMode.value) return '新对话'
  return '当前对话'
})

const sessionMessageCount = computed(() => chatHistory.value.length)
</script>

<template>
  <div class="rw-chat-panel">
    <!-- Topbar -->
    <header class="rw-topbar">
      <div class="rw-topbar-left">
        <span class="rw-crumb">{{ currentChatTitle }}</span>
        <span v-if="!isWelcomeMode" class="rw-crumb-meta">· {{ sessionMessageCount }} 条消息</span>
      </div>
      <div class="rw-topbar-right">
        <button class="rw-model-pill" type="button">
          <span class="rw-model-dot"></span>
          Raven-Sat <span class="mono">1.2</span>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
        </button>
        <div class="rw-top-more-wrap">
          <button
            ref="topMoreBtnRef"
            class="rw-top-action"
            @click="showTopMoreMenu = !showTopMoreMenu"
            aria-haspopup="menu"
            :aria-expanded="showTopMoreMenu"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></svg>
          </button>
          <div
            v-if="showTopMoreMenu"
            ref="topMoreMenuRef"
            class="rw-top-menu"
            role="menu"
          >
            <div class="rw-top-menu-group">对话</div>
            <button class="rw-menu-item" @click="showTopMoreMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4l10-10-4-4L4 16zM14 6l4 4"/></svg>
              重命名对话 <span class="rw-kbd-right">F2</span>
            </button>
            <button class="rw-menu-item" @click="showTopMoreMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v6M9 8h6l2 6H7zM12 14v8"/></svg>
              固定到顶部
            </button>

            <div class="rw-menu-divider"/>
            <div class="rw-top-menu-group">导出</div>
            <button class="rw-menu-item" @click="showTopMoreMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 14h2M9 17h6"/></svg>
              生成测试报告 <span class="rw-kbd-right">PDF</span>
            </button>
            <button class="rw-menu-item" @click="showTopMoreMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v14"/></svg>
              分享对话
            </button>
            <button class="rw-menu-item" @click="showTopMoreMenu = false">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 15v-6l3 3 3-3v6M17 9v6M14 12l3 3 3-3"/></svg>
              导出 Markdown
            </button>

            <div class="rw-menu-divider"/>
            <button class="rw-menu-item" @click="clearCurrentMessages">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>
              清空消息
            </button>
            <button
              v-if="sessionStore.selectedSessionId"
              class="rw-menu-item is-danger"
              @click="deleteCurrentSession"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>
              删除对话
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- Scroll body -->
    <div ref="chatContainerRef" class="rw-scroll">
      <!-- Welcome -->
      <div v-if="isWelcomeMode" class="rw-welcome">
        <div class="rw-welcome-badge">
          <span class="rw-dot-success"></span>
          Raven-Sat 1.2 · 已连接 {{ devices.filter(d => d.status === 'online').length }} / {{ devices.length || 0 }} 设备
        </div>
        <h1 class="rw-welcome-title">
          {{ welcomeGreeting }}，{{ currentUserName }}。<br/>今天想做哪件事？
        </h1>
        <div class="rw-welcome-sub">
          RavenAI 把代码提交、版本包、设备控制和测试日志串成一个闭环。在下方说出你的需求，或选一个常用入口开始。
        </div>
        <div class="rw-cap-grid">
          <div
            v-for="(c, i) in capabilityCards"
            :key="i"
            class="rw-cap-card"
            @click="onPickCapability(c.prompt)"
          >
            <div class="rw-cap-label">
              <svg v-if="c.icon === 'logs'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h10M4 18h16"/><circle cx="18" cy="12" r="1.4"/></svg>
              <svg v-else-if="c.icon === 'device'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="11" rx="1.5"/><path d="M8 21h8M12 17v4"/><circle cx="7" cy="11" r="0.4" fill="currentColor"/></svg>
              <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/></svg>
              {{ c.label }}
            </div>
            <div class="rw-cap-desc">{{ c.desc }}</div>
          </div>
        </div>
      </div>

      <!-- Loading -->
      <div v-else-if="loadingMessages" class="rw-loading">正在加载历史对话…</div>

      <!-- Thread -->
      <div v-else class="rw-thread">
        <div
          v-for="msg in chatHistory"
          :key="msg.id"
          :class="['rw-msg', msg.role === 'user' ? 'is-user' : 'is-ai']"
        >
          <template v-if="msg.role === 'user'">
            <div class="rw-user-bubble">{{ msg.content }}</div>
            <div class="rw-user-meta-line">{{ currentUserName }}</div>
          </template>
          <template v-else>
            <div class="rw-ai-avatar" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M5 14 19 6"/>
                <path d="M5 14a7 7 0 0 0 9.5 5"/>
                <circle cx="6" cy="18" r="1.5" fill="currentColor" stroke="none"/>
              </svg>
            </div>
            <div class="rw-ai-body">
              <div class="rw-ai-name">RAVENAI</div>
              <AgentTraceStream
                v-if="msg.traceEvents && msg.traceEvents.length > 0 || msg.traceRunning"
                class="rw-ai-trace"
                :events="msg.traceEvents || []"
                :running="!!msg.traceRunning"
                :on-cancel="msg.traceRunning ? cancelLogAnalysis : undefined"
              />
              <template v-if="msg.content === '正在思考...'">
                <div v-if="!msg.traceRunning" class="rw-thinking">正在思考…</div>
              </template>
              <template v-else>
                <div class="rw-ai-text" v-html="renderAiMessage(msg.content)"></div>
              </template>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- Composer -->
    <div class="rw-composer-wrap">
      <div
        ref="inputAreaRef"
        class="rw-composer"
      >
        <!-- Mention dropdown -->
        <div
          v-if="mentionVisible"
          ref="mentionDropdownRef"
          class="rw-mention"
        >
          <div class="rw-mention-head">
            <span>选择目标（设备、重构包或日志分析）</span>
            <span class="rw-mention-hint">输入 @ 或名称过滤</span>
          </div>
          <div v-if="isLoadingDevices" class="rw-mention-empty">设备列表加载中…</div>
          <div v-else-if="!filteredMentionOptions.length" class="rw-mention-empty">暂无匹配的目标</div>
          <template v-else>
            <button
              v-for="(option, idx) in filteredMentionOptions"
              :key="`${option.type}-${option.id}`"
              type="button"
              class="rw-mention-row"
              :class="{ active: idx === mentionSelectedIndex }"
              :ref="(el) => setMentionOptionRef(el, idx)"
              @mousedown.prevent="applyMentionSelection(option)"
              @mouseenter="mentionSelectedIndex = idx"
            >
              <template v-if="option.type === 'device'">
                <span class="rw-status-dot" :class="option.status === 'online' ? 'online' : 'offline'"></span>
                <div class="rw-mention-meta">
                  <div class="rw-mention-title">
                    {{ option.name }}
                    <span class="rw-mention-tag">{{ option.status === 'online' ? '在线' : '离线' }}</span>
                  </div>
                  <div class="rw-mention-sub">ID: {{ option.id }}</div>
                </div>
              </template>
              <template v-else>
                <span class="rw-mention-agent-ico">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/></svg>
                </span>
                <div class="rw-mention-meta">
                  <div class="rw-mention-title">{{ option.name }}</div>
                  <div class="rw-mention-sub">{{ option.description || '智能搜索重构包' }}</div>
                </div>
              </template>
            </button>
          </template>
        </div>

        <!-- Target chip -->
        <div v-if="targetAgentName || targetDeviceName" class="rw-target-chip">
          <span class="rw-target-label">当前目标</span>
          <span class="rw-target-value">
            <template v-if="targetAgentName">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/></svg>
              {{ targetAgentName }}
            </template>
            <template v-else>{{ targetDeviceName }}</template>
          </span>
          <button
            class="rw-target-clear"
            type="button"
            @click="targetAgentName ? clearTargetAgent() : clearTargetDevice()"
            aria-label="清除目标"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
          </button>
        </div>

        <textarea
          v-model="inputMessage"
          ref="textareaRef"
          class="rw-textarea"
          placeholder="给 RavenAI 说点什么，或粘贴一段日志…（输入 @ 选择设备、重构包或日志分析）"
          rows="2"
          @keydown="handleKeydown"
          @input="handleInput"
        ></textarea>

        <div class="rw-composer-row">
          <button class="rw-mini-btn" title="附加日志包" aria-label="附加日志包" @click="triggerLogFilePicker">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21 11.5-9.5 9.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5L9.5 18.5a2 2 0 0 1-3-3L15 7"/></svg>
          </button>
          <input
            ref="logFileInputRef"
            class="rw-file-input"
            type="file"
            accept=".zip,.tar,.tgz,.gz,.tar.gz,.tar.bz2,.bz2"
            @change="handleLogFileChange"
          />
          <button
            class="rw-tool-chip"
            :class="{ active: isPackageAgentSelected }"
            @click="togglePackageAgent"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/></svg>
            检索重构包
          </button>
          <button
            class="rw-tool-chip"
            :class="{ active: isLogAnalysisAgentSelected }"
            @click="toggleLogAnalysisAgent"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M4 12h10M4 18h16"/><circle cx="18" cy="12" r="1.4"/></svg>
            日志分析
          </button>
          <div v-if="selectedLogFile" class="rw-file-chip">
            <span>{{ selectedLogFile.name }}</span>
            <button type="button" aria-label="移除附件" @click="clearSelectedLogFile">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
            </button>
          </div>
          <button
            v-if="activeLogAnalysisSessionId"
            class="rw-cancel-btn"
            :disabled="cancelInFlight"
            type="button"
            :title="cancelInFlight ? '正在取消...' : '取消当前日志分析'"
            @click="cancelLogAnalysis"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>
            {{ cancelInFlight ? '取消中…' : '取消分析' }}
          </button>
          <button class="rw-send-btn" :disabled="(!inputMessage.trim() && !selectedLogFile) || isSending" @click="sendMessage">
            <svg v-if="isSending" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="spin"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>
            <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12 19 5l-3 15-5-7-6-1Z"/></svg>
          </button>
        </div>
      </div>
      <div class="rw-composer-hint">RavenAI 可能会出错。涉及在线设备的下发操作均需你二次确认。</div>
    </div>
  </div>
</template>

<style scoped>
.rw-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--rw-canvas, #ffffff);
  color: var(--rw-ink, #171717);
}

.mono { font-family: var(--rw-mono); font-weight: 500; }
.spin { animation: rw-spin 1s linear infinite; }
@keyframes rw-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

/* Topbar */
.rw-topbar {
  height: 56px; flex-shrink: 0;
  border-bottom: 1px solid var(--rw-hairline);
  display: flex; align-items: center;
  padding: 0 28px; gap: 14px;
  background: var(--rw-canvas);
}
.rw-topbar-left { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.rw-crumb { font-size: 14.5px; font-weight: 600; color: var(--rw-ink); letter-spacing: -0.1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-crumb-meta { font-size: 12px; color: var(--rw-muted); font-family: var(--rw-mono); flex-shrink: 0; }
.rw-topbar-right { display: flex; align-items: center; gap: 8px; }
.rw-model-pill {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--rw-surface-strong); color: var(--rw-ink);
  height: 28px; padding: 0 10px; border-radius: 999px;
  font-size: 12px; font-weight: 500;
}
.rw-model-pill:hover { background: var(--rw-hairline-strong); }
.rw-model-dot { width: 6px; height: 6px; border-radius: 999px; background: var(--rw-success); }
.rw-top-action {
  height: 30px; padding: 0 8px;
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--rw-hairline-strong);
  background: var(--rw-canvas);
  border-radius: 8px;
  font-size: 13px; font-weight: 500; color: var(--rw-ink);
}
.rw-top-action:hover { background: var(--rw-surface-strong); }
.rw-top-more-wrap { position: relative; }
.rw-top-menu {
  position: absolute; top: calc(100% + 6px); right: 0;
  width: 240px; background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong); border-radius: 10px;
  padding: 4px;
  box-shadow: 0 12px 32px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.04);
  z-index: 30;
}
.rw-top-menu-group {
  padding: 6px 10px 2px;
  font-size: 10.5px; font-weight: 600; letter-spacing: 0.6px;
  text-transform: uppercase; color: var(--rw-muted);
}
.rw-menu-item {
  display: flex; align-items: center; gap: 9px;
  width: 100%; height: 30px; padding: 0 10px;
  border-radius: 5px; font-size: 12.5px; font-weight: 500;
  color: var(--rw-ink); cursor: pointer; background: none; border: none;
  text-align: left;
}
.rw-menu-item:hover { background: var(--rw-surface-strong); }
.rw-menu-item.is-danger { color: var(--rw-danger); }
.rw-menu-item.is-danger:hover { background: rgba(192,56,43,.06); }
.rw-menu-divider { height: 1px; background: var(--rw-hairline); margin: 4px 6px; }
.rw-kbd-right { margin-left: auto; font-family: var(--rw-mono); font-size: 11px; color: var(--rw-muted); }

/* Scroll area */
.rw-scroll { flex: 1; min-height: 0; overflow: auto; padding: 32px 0 24px; }

/* Welcome */
.rw-welcome {
  height: 100%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 22px;
  padding: 0 32px; text-align: center;
}
.rw-welcome-badge {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--rw-surface-strong);
  padding: 5px 12px; border-radius: 999px;
  font-size: 11px; font-weight: 600;
  letter-spacing: 0.8px; text-transform: uppercase;
  color: var(--rw-ink);
}
.rw-dot-success { width: 6px; height: 6px; border-radius: 999px; background: var(--rw-success); }
.rw-welcome-title {
  font-size: 40px; font-weight: 600; letter-spacing: -1.2px;
  line-height: 1.1; color: var(--rw-ink); max-width: 680px;
  margin: 0;
}
.rw-welcome-sub {
  font-size: 15.5px; color: var(--rw-body);
  max-width: 540px; line-height: 1.55; font-weight: 400;
}
.rw-cap-grid {
  margin-top: 8px;
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px; width: 100%; max-width: 720px;
}
.rw-cap-card {
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  padding: 14px 16px;
  background: var(--rw-canvas);
  text-align: left;
  display: flex; flex-direction: column; gap: 6px;
  cursor: pointer; transition: all .15s;
}
.rw-cap-card:hover {
  border-color: var(--rw-ink);
  box-shadow: 0 4px 12px rgba(0,0,0,.04);
}
.rw-cap-label { font-size: 13px; font-weight: 600; color: var(--rw-ink); display: inline-flex; align-items: center; gap: 8px; }
.rw-cap-desc { font-size: 12.5px; color: var(--rw-body); line-height: 1.5; }

/* Loading */
.rw-loading { text-align: center; color: var(--rw-muted); font-size: 13px; padding-top: 48px; }

/* Thread */
.rw-thread {
  max-width: 820px; margin: 0 auto;
  padding: 0 32px;
  display: flex; flex-direction: column; gap: 28px;
}
.rw-msg.is-user { display: flex; flex-direction: column; align-items: flex-end; }
.rw-user-bubble {
  background: var(--rw-surface-strong); color: var(--rw-ink);
  padding: 12px 16px; border-radius: 12px;
  font-size: 14.5px; line-height: 1.55;
  max-width: 85%; white-space: pre-wrap;
  word-break: break-word;
}
.rw-user-meta-line { font-size: 11px; color: var(--rw-muted); margin-top: 6px; font-weight: 500; }
.rw-msg.is-ai { display: flex; gap: 14px; align-items: flex-start; }
.rw-ai-avatar {
  width: 28px; height: 28px; border-radius: 8px;
  background: var(--rw-surface-dark); color: var(--rw-on-primary);
  display: grid; place-items: center;
  flex-shrink: 0; margin-top: 2px;
}
.rw-ai-body { flex: 1; min-width: 0; }
.rw-ai-name {
  font-size: 12.5px; color: var(--rw-muted); font-weight: 600;
  margin-bottom: 6px; letter-spacing: 0.2px; text-transform: uppercase;
}
.rw-ai-trace { margin-bottom: 12px; }
.rw-ai-text { font-size: 14.5px; color: var(--rw-ink); line-height: 1.62; }
.rw-thinking {
  display: inline-block;
  background: linear-gradient(90deg, #9ca3af 0%, #e5e7eb 50%, #9ca3af 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text; background-clip: text;
  color: transparent; font-weight: 600;
  animation: rw-shimmer 1.6s ease-in-out infinite;
}
@keyframes rw-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* Markdown content adjustments */
.rw-ai-text :deep(p) { margin: 0 0 10px; }
.rw-ai-text :deep(p:last-child) { margin-bottom: 0; }
.rw-ai-text :deep(code) {
  font-family: var(--rw-mono); font-size: 12.5px;
  background: var(--rw-surface-strong); color: var(--rw-ink);
  padding: 1px 6px; border-radius: 4px;
}
.rw-ai-text :deep(pre) {
  background: var(--rw-surface-dark); color: #fff;
  padding: 14px; border-radius: 8px;
  font-family: var(--rw-mono); font-size: 12.5px; line-height: 1.55;
  overflow: auto; margin: 10px 0;
}
.rw-ai-text :deep(pre code) {
  background: transparent; color: inherit; padding: 0; border-radius: 0;
  font-size: inherit;
}
.rw-ai-text :deep(h1),
.rw-ai-text :deep(h2),
.rw-ai-text :deep(h3) {
  color: var(--rw-ink); font-weight: 600; letter-spacing: -0.2px;
  margin: 16px 0 8px;
}
.rw-ai-text :deep(h1) { font-size: 18px; }
.rw-ai-text :deep(h2) { font-size: 16px; }
.rw-ai-text :deep(h3) { font-size: 14.5px; }
.rw-ai-text :deep(ul),
.rw-ai-text :deep(ol) { padding-left: 22px; margin: 8px 0; }
.rw-ai-text :deep(li) { margin: 4px 0; }
.rw-ai-text :deep(a) { color: #0d74ce; text-decoration: none; }
.rw-ai-text :deep(a:hover) { text-decoration: underline; }

/* Composer */
.rw-composer-wrap { flex-shrink: 0; padding: 12px 32px 24px; background: var(--rw-canvas); }
.rw-composer {
  max-width: 820px; margin: 0 auto;
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 14px;
  background: var(--rw-canvas);
  box-shadow: 0 1px 2px rgba(0,0,0,.02), 0 6px 22px rgba(0,0,0,.05);
  padding: 12px 14px 10px;
  display: flex; flex-direction: column; gap: 8px;
  position: relative;
}
.rw-composer:focus-within { border-color: var(--rw-ink); }
.rw-textarea {
  width: 100%; min-height: 50px;
  border: none; outline: none; resize: none;
  font-size: 14.5px; line-height: 1.55;
  font-family: var(--rw-sans);
  background: transparent; color: var(--rw-ink);
}
.rw-textarea::placeholder { color: var(--rw-muted); }

.rw-composer-row { display: flex; align-items: center; gap: 6px; }
.rw-mini-btn {
  width: 30px; height: 30px; border-radius: 6px;
  display: grid; place-items: center;
  color: var(--rw-body); transition: background .12s, color .12s;
  background: none; border: none; cursor: pointer;
}
.rw-mini-btn:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-file-input { display: none; }
.rw-tool-chip {
  height: 28px; padding: 0 11px;
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--rw-hairline-strong);
  background: var(--rw-canvas); color: var(--rw-ink);
  border-radius: 999px; font-size: 12.5px; font-weight: 500;
  cursor: pointer; transition: all .15s;
}
.rw-tool-chip:hover { border-color: var(--rw-ink); }
.rw-tool-chip.active { background: var(--rw-ink); color: var(--rw-on-primary); border-color: var(--rw-ink); }
.rw-file-chip {
  min-width: 0; max-width: 260px; height: 28px; padding: 0 8px 0 10px;
  display: inline-flex; align-items: center; gap: 7px;
  border-radius: 999px; background: var(--rw-surface-strong);
  color: var(--rw-ink); font-size: 12px; font-weight: 500;
}
.rw-file-chip span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rw-file-chip button {
  width: 18px; height: 18px; border-radius: 999px;
  display: grid; place-items: center; flex-shrink: 0;
  color: var(--rw-muted); background: none; border: none; cursor: pointer;
}
.rw-file-chip button:hover { background: var(--rw-hairline-strong); color: var(--rw-ink); }

.rw-cancel-btn {
  height: 32px; padding: 0 10px; border-radius: 8px;
  background: transparent; color: var(--rw-ink);
  display: inline-flex; align-items: center; gap: 6px;
  margin-left: auto;
  font-size: 12px; font-weight: 500;
  border: 1px solid var(--rw-hairline-strong, #d4d4d4);
  cursor: pointer;
  transition: background .15s, color .15s, border-color .15s;
}
.rw-cancel-btn:hover:not(:disabled) {
  background: var(--rw-surface-strong, #f5f5f5);
  border-color: var(--rw-ink, #171717);
}
.rw-cancel-btn:disabled { color: var(--rw-muted); cursor: not-allowed; }
.rw-cancel-btn + .rw-send-btn { margin-left: 8px; }

.rw-send-btn {
  width: 36px; height: 32px; border-radius: 8px;
  background: var(--rw-primary); color: var(--rw-on-primary);
  display: inline-flex; align-items: center; justify-content: center;
  margin-left: auto;
  transition: background .15s;
  border: none; cursor: pointer;
}
.rw-send-btn:hover:not(:disabled) { background: var(--rw-primary-active); }
.rw-send-btn:disabled {
  background: var(--rw-surface-strong); color: var(--rw-muted);
  cursor: not-allowed;
}

.rw-composer-hint {
  max-width: 820px; margin: 8px auto 0;
  font-size: 11.5px; color: var(--rw-muted);
  text-align: center; font-family: var(--rw-mono);
}

/* Mention */
.rw-mention {
  position: absolute; left: 14px; right: 14px;
  bottom: calc(100% + 6px);
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  max-height: 260px; overflow: auto;
  box-shadow: 0 12px 32px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.04);
  z-index: 30;
}
.rw-mention-head {
  padding: 10px 14px; border-bottom: 1px solid var(--rw-hairline);
  font-size: 12.5px; color: var(--rw-body);
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.rw-mention-hint { font-size: 11px; color: var(--rw-muted); }
.rw-mention-empty { padding: 12px 14px; font-size: 12.5px; color: var(--rw-muted); }
.rw-mention-row {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--rw-hairline-soft);
  background: none; border-left: none; border-right: none; border-top: none;
  cursor: pointer;
}
.rw-mention-row:last-child { border-bottom: none; }
.rw-mention-row:hover, .rw-mention-row.active { background: var(--rw-hairline-soft); }
.rw-status-dot { width: 7px; height: 7px; border-radius: 999px; flex-shrink: 0; }
.rw-status-dot.online { background: var(--rw-success); }
.rw-status-dot.offline { background: var(--rw-muted-soft); }
.rw-mention-agent-ico {
  width: 28px; height: 28px; border-radius: 8px;
  background: var(--rw-surface-strong); color: var(--rw-ink);
  display: grid; place-items: center; flex-shrink: 0;
}
.rw-mention-meta { flex: 1; min-width: 0; }
.rw-mention-title {
  font-size: 13.5px; font-weight: 600; color: var(--rw-ink);
  display: flex; align-items: center; gap: 6px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rw-mention-tag {
  font-family: var(--rw-mono); font-size: 10.5px;
  text-transform: uppercase; color: var(--rw-muted);
  font-weight: 500;
}
.rw-mention-sub { font-size: 12px; color: var(--rw-muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Target chip */
.rw-target-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; border-radius: 999px;
  background: var(--rw-surface-strong);
  font-size: 12.5px; align-self: flex-start;
}
.rw-target-label { color: var(--rw-muted); font-family: var(--rw-mono); font-size: 11.5px; }
.rw-target-value {
  display: inline-flex; align-items: center; gap: 6px;
  font-weight: 600; color: var(--rw-ink);
}
.rw-target-clear {
  width: 20px; height: 20px; border-radius: 999px;
  display: grid; place-items: center; color: var(--rw-body);
  background: none; border: none; cursor: pointer;
}
.rw-target-clear:hover { background: var(--rw-hairline-strong); }

/* Scrollbar */
.rw-scroll::-webkit-scrollbar,
.rw-mention::-webkit-scrollbar { width: 10px; height: 10px; }
.rw-scroll::-webkit-scrollbar-track,
.rw-mention::-webkit-scrollbar-track { background: transparent; }
.rw-scroll::-webkit-scrollbar-thumb,
.rw-mention::-webkit-scrollbar-thumb {
  background: #e6e6ea; border-radius: 999px; border: 2px solid var(--rw-canvas);
}
.rw-scroll::-webkit-scrollbar-thumb:hover,
.rw-mention::-webkit-scrollbar-thumb:hover { background: var(--rw-muted-soft); }

/* Responsive */
@media (max-width: 900px) {
  .rw-thread, .rw-composer { padding-left: 16px; padding-right: 16px; }
  .rw-composer-wrap { padding-left: 16px; padding-right: 16px; }
  .rw-topbar { padding: 0 16px; }
  .rw-cap-grid { grid-template-columns: 1fr; max-width: 480px; }
  .rw-welcome-title { font-size: 32px; letter-spacing: -0.8px; }
}
</style>
