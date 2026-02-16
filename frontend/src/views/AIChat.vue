<script setup lang="ts">
import { computed, onMounted, onUnmounted, nextTick, reactive, ref, watch } from 'vue'
import {
  Menu,
  Plus,
  MessageSquare,
  HelpCircle,
  Send,
  Mic,
  Image as ImageIcon,
  List,
  Box,
  LogOut,
  ExternalLink,
  X,
  LogIn,
  RefreshCw,
  Trash2,
  Loader2
} from 'lucide-vue-next'
import { deviceLinkApi } from '@/api/deviceLink'
import { intelligentSearchPackages, ravenBaseUrl } from '@/api/raven'
import { userApi } from '@/api/user'
import type { DeviceInfo, RavenPackage, RavenSearchResult, ChatMessageRecord, ChatSessionSummary } from '@/types'
import { renderMarkdown } from '@/utils/markdownRenderer'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'

type MentionOption =
  | { type: 'agent'; id: string; name: string; description?: string; agentType: 'package-manager' }
  | { type: 'device'; id: string; name: string; status: DeviceInfo['status']; device: DeviceInfo }

const packageAgentOption: MentionOption = {
  type: 'agent',
  id: 'package-manager',
  name: '重构包配置管理员',
  agentType: 'package-manager',
  description: '调用重构包智能搜索，返回详情、下载链接与重构提示词'
}

const userStore = useUserStore()
const appStore = useAppStore()

type ChatRole = 'user' | 'ai' | 'system'
type ChatEntry = {
  id: string
  role: ChatRole
  content: string
  kind?: 'plan' | 'device_action' | 'answer' | 'user'
}

// 生成兼容的 UUID
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

const sidebarOpen = ref(true)
const inputMessage = ref('')
const showUserMenu = ref(false)
const chatContainerRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const inputAreaRef = ref<HTMLElement | null>(null)
const mentionDropdownRef = ref<HTMLElement | null>(null)
const userMenuRef = ref<HTMLElement | null>(null)
const userButtonRef = ref<HTMLElement | null>(null)
const devices = ref<DeviceInfo[]>([])
const isLoadingDevices = ref(false)
const mentionVisible = ref(false)
const mentionKeyword = ref('')
const mentionSelectedIndex = ref(0)
const mentionOptionRefs = ref<(HTMLElement | null)[]>([])
const mentionStart = ref<number | null>(null)
const targetDeviceId = ref<string | null>(null)
const targetDeviceName = ref<string | null>(null)
const targetAgent = ref<{ id: string; name: string; agentType: 'package-manager' } | null>(null)
const chatSessions = ref<ChatSessionSummary[]>([])
const selectedSessionId = ref<string | null>(null)
const loadingSessions = ref(false)
const loadingMessages = ref(false)
const showLoginModal = ref(false)
const loginForm = reactive({
  username: '',
  password: '',
})
const isLoggingIn = ref(false)

// Handle click outside to close menu
const handleClickOutside = (event: MouseEvent) => {
  if (showUserMenu.value &&
      userMenuRef.value &&
      userButtonRef.value &&
      !userMenuRef.value.contains(event.target as Node) && 
      !userButtonRef.value.contains(event.target as Node)) {
    showUserMenu.value = false
  }

  if (
    mentionVisible.value &&
    mentionDropdownRef.value &&
    inputAreaRef.value &&
    !mentionDropdownRef.value.contains(event.target as Node) &&
    !inputAreaRef.value.contains(event.target as Node)
  ) {
    mentionVisible.value = false
    mentionKeyword.value = ''
    mentionStart.value = null
  }
}

const handleViewportForSidebar = () => {
  if (window.innerWidth <= 768) {
    sidebarOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  handleViewportForSidebar()
  window.addEventListener('resize', handleViewportForSidebar, { passive: true })
  fetchDevices()
  bootstrapUser()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('resize', handleViewportForSidebar)
})

const chatHistory = ref<ChatEntry[]>([])
const sessionId = ref<string | null>(null)
const isSending = ref(false)
const isLoggedIn = computed(() => userStore.isAuthenticated)
const currentUserName = computed(() => userStore.profile?.display_name || userStore.profile?.username || '用户')
const currentUserEmail = computed(() => userStore.profile?.email || '')
const userInitial = computed(() => (currentUserName.value || 'U').slice(0, 1).toUpperCase())

const toggleSidebar = () => {
  sidebarOpen.value = !sidebarOpen.value
}

const toggleUserMenu = () => {
  showUserMenu.value = !showUserMenu.value
}

const scrollToBottom = async () => {
  await nextTick()
  if (chatContainerRef.value) {
    chatContainerRef.value.scrollTop = chatContainerRef.value.scrollHeight
  }
}

// Watch for chat history changes to scroll to bottom
watch(chatHistory, () => {
  scrollToBottom()
}, { deep: true })

watch(isLoggedIn, (loggedIn) => {
  if (loggedIn) {
    loadSessions()
  } else {
    chatSessions.value = []
    selectedSessionId.value = null
    sessionId.value = null
  }
})

// Construct 8085 URLs dynamically based on current hostname
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

const loadSessions = async () => {
  if (!isLoggedIn.value) return
  loadingSessions.value = true
  try {
    const resp = await userApi.listSessions()
    if (resp?.success && resp.data) {
      chatSessions.value = resp.data
    } else {
      chatSessions.value = []
    }
  } catch (error) {
    console.error('加载会话失败', error)
    chatSessions.value = []
    appStore.showNotification({
      title: '同步会话失败',
      type: 'error',
    })
  } finally {
    loadingSessions.value = false
  }
}

const loadMessages = async (id: string) => {
  if (!isLoggedIn.value) return
  loadingMessages.value = true
  chatHistory.value = []
  sessionId.value = id
  selectedSessionId.value = id
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
    appStore.showNotification({
      title: '加载消息失败',
      type: 'error',
    })
  } finally {
    loadingMessages.value = false
  }
}

const handleSelectSession = async (session: ChatSessionSummary) => {
  await loadMessages(session.id)
}

const startNewChat = () => {
  selectedSessionId.value = null
  sessionId.value = null
  chatHistory.value = []
}

const handleUserLogin = async () => {
  if (!loginForm.username || !loginForm.password) {
    appStore.showNotification({
      title: '请输入用户名和密码',
      type: 'warning',
    })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await userApi.login(loginForm.username.trim(), loginForm.password)
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '登录失败')
    }
    userStore.setToken(resp.data.token)
    userStore.setProfile(resp.data.user)
    appStore.showNotification({
      title: '登录成功',
      type: 'success',
    })
    showLoginModal.value = false
    loginForm.username = ''
    loginForm.password = ''
    await loadSessions()
  } catch (error: any) {
    appStore.showNotification({
      title: '登录失败',
      message: error?.message || '请检查账号密码',
      type: 'error',
    })
  } finally {
    isLoggingIn.value = false
  }
}

const handleUserLogout = () => {
  userStore.clear()
  chatSessions.value = []
  selectedSessionId.value = null
  sessionId.value = null
  chatHistory.value = []
  showUserMenu.value = false
}

const deleteSession = async (id: string) => {
  const confirmed = window.confirm('确定要删除该对话吗？此操作不可恢复。')
  if (!confirmed) return
  try {
    const resp = await userApi.deleteSession(id)
    if (resp?.success && Array.isArray(resp.data)) {
      chatSessions.value = resp.data
      if (selectedSessionId.value === id) {
        startNewChat()
      }
      appStore.showNotification({
        title: '会话已删除',
        type: 'success',
      })
    }
  } catch (error) {
    console.error('删除会话失败', error)
    appStore.showNotification({
      title: '删除失败',
      type: 'error',
    })
  }
}

async function bootstrapUser() {
  await userStore.bootstrap()
  if (isLoggedIn.value) {
    await loadSessions()
  }
}

const mentionOptions = computed<MentionOption[]>(() => {
  const deviceOptions: MentionOption[] = devices.value
    .slice()
    .sort((a, b) => {
      if (a.status === b.status) return 0
      return a.status === 'online' ? -1 : 1
    })
    .map((device) => ({
      type: 'device',
      id: device.id,
      name: device.name || device.id,
      status: device.status,
      device,
    }))

  return [packageAgentOption, ...deviceOptions]
})

const filteredMentionOptions = computed(() => {
  const keyword = mentionKeyword.value.trim().toLowerCase()
  const list = mentionOptions.value
  if (!keyword) return list
  return list.filter((option) => {
    const text = `${option.name} ${option.id}`.toLowerCase()
    return text.includes(keyword)
  })
})

watch(filteredMentionOptions, (list) => {
  if (mentionSelectedIndex.value >= list.length) {
    mentionSelectedIndex.value = 0
  }
  mentionOptionRefs.value = []
})

watch(mentionSelectedIndex, (idx) => {
  const el = mentionOptionRefs.value[idx]
  if (el?.scrollIntoView) {
    el.scrollIntoView({ block: 'nearest' })
  }
})

const deviceStatusDotClass = (status: DeviceInfo['status']) =>
  status === 'online' ? 'bg-green-500' : 'bg-gray-300'

const targetAgentName = computed(() => targetAgent.value?.name || null)
const isPackageAgentSelected = computed(() => targetAgent.value?.agentType === 'package-manager')

const resetMentionState = () => {
  mentionVisible.value = false
  mentionKeyword.value = ''
  mentionSelectedIndex.value = 0
  mentionStart.value = null
}

const renderAiMessage = (content: string) =>
  renderMarkdown(content || '', {
    wrapperClass: 'markdown-content text-gray-900'
  })

const formatTime = (value?: string | null) => {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return value
  }
}

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
  return {
    detailLink,
    downloadLink,
    prompt: buildRebuildPrompt(downloadLink),
  }
}

const formatPackageAgentAnswer = (result: RavenSearchResult, rawQuery: string) => {
  const query = rawQuery.trim() || '（未提供查询）'
  const packages = result.relevantPackages || []
  const recommendedIdSet = new Set(result.recommendedPackageIds || [])
  const recommendedPackages = packages.filter((pkg) => recommendedIdSet.has(pkg.id))
  const lines: string[] = [
    `**重构包配置管理员** 已为你执行智能搜索：\`${query}\``
  ]

  const pushPackageLines = (pkg: RavenPackage, isRecommended = false) => {
    const links = buildPackageLinks(pkg)
    const recommendedLabel = isRecommended ? ' ⭐ AI 推荐' : ''
    lines.push(
      `## ${pkg.name || pkg.id}${recommendedLabel} （${packageTypeText(pkg.packageType)} · v${pkg.version || '未知'}）`
    )
    if (pkg.metadata?.description) {
      lines.push(`- 描述：${pkg.metadata.description}`)
    }
    lines.push(
      `- 详情链接：[${links.detailLink}](${links.detailLink})`,
      `- 下载链接：[${links.downloadLink}](${links.downloadLink})`,
      '- 重构提示词：',
      `  \`${links.prompt}\``
    )
  }

  if (result.answer) {
    lines.push('', result.answer)
  }

  if (recommendedPackages.length > 0) {
    lines.push('', `# Raven AI 推荐的重构包（${recommendedPackages.length} 个）：`)
    recommendedPackages.forEach((pkg) => pushPackageLines(pkg, true))
  } else {
    const hasPackages = packages.length > 0
    lines.push('', hasPackages ? '暂无 AI 推荐的重构包。' : '未找到匹配的重构包。')
  }

  return lines.join('\n')
}

const updateMentionState = (event?: Event) => {
  const value = inputMessage.value
  const target = (event?.target as HTMLTextAreaElement | null) || textareaRef.value
  const cursor = target?.selectionStart ?? value.length
  const lastAt = value.lastIndexOf('@', cursor - 1)
  if (lastAt === -1) {
    resetMentionState()
    return
  }
  const afterAt = value.slice(lastAt + 1, cursor)
  if (afterAt.includes(' ') || afterAt.includes('\n') || afterAt.includes('\t')) {
    resetMentionState()
    return
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
    targetAgent.value = {
      id: option.id,
      name: option.name,
      agentType: option.agentType
    }
    targetDeviceId.value = null
    targetDeviceName.value = null
  }

  // Replace the mention keyword with the selected device name for clarity
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

const clearTargetDevice = () => {
  targetDeviceId.value = null
  targetDeviceName.value = null
}

const clearTargetAgent = () => {
  targetAgent.value = null
}

const findMessageIndex = (id: string) => chatHistory.value.findIndex((msg) => msg.id === id)

const ensureAnswerMessage = (answerId: string): ChatEntry => {
  const idx = findMessageIndex(answerId)
  if (idx !== -1) {
    return chatHistory.value[idx]
  }
  const fallback: ChatEntry = { id: answerId, role: 'ai', content: '正在思考...', kind: 'answer' }
  chatHistory.value.push(fallback)
  return fallback
}

const insertBeforeAnswer = (answerId: string, entry: ChatEntry) => {
  const idx = findMessageIndex(answerId)
  if (idx === -1) {
    chatHistory.value.push(entry)
  } else {
    chatHistory.value.splice(idx, 0, entry)
  }
}

const formatPlanMessage = (steps: any[]) => {
  if (!Array.isArray(steps) || steps.length === 0) {
    return '未生成计划。'
  }
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
    typeof payload?.answer === 'string'
      ? payload.answer
      : payload?.answer
        ? String(payload.answer)
        : ''
  if (answerText) {
    lines.push(answerText)
  } else if (payload?.raw) {
    lines.push(String(payload.raw))
  } else {
    lines.push('无返回内容')
  }
  if (payload?.topic_id) {
    lines.push(`- 话题ID: ${payload.topic_id}`)
  }
  return lines.join('\n')
}

const applyStreamEvent = (payload: any, answerId: string) => {
  const type = payload?.event || payload?.type
  if (payload?.session_id) {
    sessionId.value = payload.session_id
    selectedSessionId.value = payload.session_id
  }

  if (type === 'plan') {
    const content = formatPlanMessage(payload?.plan)
    insertBeforeAnswer(answerId, { id: generateUUID(), role: 'ai', content, kind: 'plan' })
    return
  }

  if (type === 'device_action') {
    const content = formatDeviceActionMessage(payload)
    insertBeforeAnswer(answerId, { id: generateUUID(), role: 'ai', content, kind: 'device_action' })
    return
  }

  if (type === 'session') return

  const targetMessage = ensureAnswerMessage(answerId)

  if (type === 'chunk' && typeof payload?.content === 'string') {
    const chunk = payload.content
    if (targetMessage.content === '正在思考...') {
      const trimmedChunk = chunk.trimStart()
      if (trimmedChunk) {
        targetMessage.content = trimmedChunk
      }
    } else {
      targetMessage.content += chunk
    }
  } else if (type === 'done') {
    if (typeof payload?.answer === 'string' && payload.answer) {
      targetMessage.content = payload.answer.trimStart()
    } else if (!targetMessage.content || targetMessage.content === '正在思考...') {
      targetMessage.content = '（无回复内容）'
    }
  } else if (type === 'error') {
    targetMessage.content = `调用后端失败：${payload?.message || '未知错误'}`
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
    try {
      const payload = JSON.parse(jsonStr)
      applyStreamEvent(payload, answerId)
    } catch (err) {
      console.error('解析流式数据失败', err, jsonStr)
    }
  }
  return remaining
}

const handleKeydown = (event: KeyboardEvent) => {
  if (mentionVisible.value && filteredMentionOptions.value.length > 0) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      mentionSelectedIndex.value =
        (mentionSelectedIndex.value + 1) % filteredMentionOptions.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      mentionSelectedIndex.value =
        (mentionSelectedIndex.value - 1 + filteredMentionOptions.value.length) % filteredMentionOptions.value.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      const option = filteredMentionOptions.value[mentionSelectedIndex.value]
      if (option) applyMentionSelection(option)
      return
    }
  }

  if (event.key === 'Escape' && mentionVisible.value) {
    resetMentionState()
    return
  }

  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

const handleInput = (event: Event) => {
  updateMentionState(event)
}

const extractPackageQuery = (content: string) =>
  content.replace(/@重构包配置管理员/g, '').trim()

const runPackageAgent = async (content: string, answerId: string) => {
  const query = extractPackageQuery(content)
  const targetMessage = ensureAnswerMessage(answerId)
  if (!query) {
    targetMessage.content = '请描述需要查找的重构包需求，例如型号、版本或用途。'
    return
  }

  try {
    const { data } = await intelligentSearchPackages(query, 6)
    if (!data?.success || !data.data) {
      throw new Error(data?.message || '智能搜索失败')
    }
    const aiContent = formatPackageAgentAnswer(data.data, query)
    targetMessage.content = aiContent

    // 已登录用户：保存到数据库
    if (isLoggedIn.value) {
      // 如果没有 sessionId，创建一个新的
      if (!sessionId.value) {
        sessionId.value = generateUUID()
        selectedSessionId.value = sessionId.value
      }

      try {
        await userApi.saveMessages(
          sessionId.value,
          content,
          aiContent,
          content.slice(0, 60)
        )
        // 保存成功后刷新会话列表
        await loadSessions()
      } catch (error: any) {
        console.warn('保存重构包配置管理员对话失败', error)
        // 不影响用户体验，静默失败
      }
    }
  } catch (error: any) {
    console.error('重构包配置管理员调用失败', error)
    targetMessage.content = `重构包配置管理员调用失败：${error?.message || String(error)}`
  }
}

const sendMessage = async () => {
  if (isSending.value) return
  const content = inputMessage.value.trim()
  if (!content) return

  const shouldUsePackageAgent =
    isPackageAgentSelected.value || content.includes(`@${packageAgentOption.name}`)

  // 如果用户手动输入了 @重构包配置管理员，则自动选中该助手并清空设备目标
  if (shouldUsePackageAgent && !isPackageAgentSelected.value) {
    targetAgent.value = {
      id: packageAgentOption.id,
      name: packageAgentOption.name,
      agentType: packageAgentOption.agentType,
    }
    targetDeviceId.value = null
    targetDeviceName.value = null
  }

  // 记录用户消息
  const userMessage: ChatEntry = {
    id: generateUUID(),
    role: 'user',
    content,
    kind: 'user',
  }
  chatHistory.value.push(userMessage)

  // 构造历史（不含当前用户消息，因为会通过message字段单独发送）
  // 只发送之前的对话历史
  const historyPayload = isLoggedIn.value
    ? []
    : chatHistory.value.slice(0, -1).map(msg => ({
        role: msg.role,
        content: msg.content
      }))

  // 占位回复
  const answerMessageId = generateUUID()
  chatHistory.value.push({
    id: answerMessageId,
    role: 'ai',
    content: '正在思考...',
    kind: 'answer',
  })

  inputMessage.value = ''
  resetMentionState()
  isSending.value = true

  try {
    if (shouldUsePackageAgent) {
      await runPackageAgent(content, answerMessageId)
      return
    }

    const payload = {
      message: content,
      session_id: sessionId.value || undefined,
      history: historyPayload,
      remember: true,
      target_device_id: targetDeviceId.value || undefined,
      target_device_name: targetDeviceName.value || undefined
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    }
    const authToken = userStore.token as unknown as string
    if (isLoggedIn.value && authToken) {
      headers.Authorization = `Bearer ${authToken}`
    }

    const resp = await fetch(getServiceUrl('/api/v1/ai-chat/chat/stream'), {
      method: 'POST',
      headers,
      body: JSON.stringify(payload)
    })

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`)
    }

    if (!resp.body) {
      throw new Error('响应体为空，无法流式读取')
    }

    console.log('[SSE] resp.body 存在，开始流式读取')
    console.log('[SSE] TextDecoderStream 支持:', typeof TextDecoderStream !== 'undefined')

    const textStream = resp.body && typeof TextDecoderStream !== 'undefined'
      ? resp.body.pipeThrough(new TextDecoderStream())
      : null

    const reader = textStream
      ? textStream.getReader()
      : null
    const binaryReader = !textStream && resp.body ? resp.body.getReader() : null
    const decoder = !textStream ? new TextDecoder('utf-8') : null
    let buffer = ''

    console.log('[SSE] reader:', !!reader, 'binaryReader:', !!binaryReader)

    if (reader) {
      console.log('[SSE] 使用 TextDecoderStream reader')
      while (true) {
        const { value, done } = await reader.read()
        console.log('[SSE] read result - done:', done, 'value length:', value?.length)
        if (value) {
          console.log('[SSE] 收到数据:', value.substring(0, 200))
          buffer += value
          buffer = processSseBuffer(buffer, answerMessageId)
        }
        if (done) break
      }
    } else if (binaryReader && decoder) {
      console.log('[SSE] 使用 binary reader')
      while (true) {
        const { value, done } = await binaryReader.read()
        console.log('[SSE] read result - done:', done, 'value:', value?.length)
        if (value) {
          const decoded = decoder.decode(value, { stream: !done })
          console.log('[SSE] 解码后数据:', decoded.substring(0, 200))
          buffer += decoded
          buffer = processSseBuffer(buffer, answerMessageId)
        }
        if (done) break
      }
    } else {
      console.error('[SSE] 没有可用的 reader!')
    }

    console.log('[SSE] 循环结束，剩余 buffer:', buffer)

    if (buffer.trim()) {
      processSseBuffer(buffer + '\n\n', answerMessageId)
    }

    const answerMessage = ensureAnswerMessage(answerMessageId)
    if (answerMessage.content === '正在思考...') {
      answerMessage.content = '（无回复内容）'
    }

    if (isLoggedIn.value) {
      try {
        await loadSessions()
      } catch (error) {
        console.warn('刷新会话列表失败', error)
      }
    }
  } catch (error: any) {
    console.error('===== 请求失败 =====')
    console.error('错误信息:', error)
    ensureAnswerMessage(answerMessageId).content = `调用后端失败：${error?.message || String(error)}`
  } finally {
    isSending.value = false
    console.log('===== 请求结束 =====')
  }
}
</script>

<template>
  <div class="flex h-full bg-white text-gray-900 font-sans overflow-hidden ai-chat-page">
    <!-- Sidebar -->
    <div
      class="ai-sidebar"
      :class="[
        'flex flex-col bg-[#F0F4F9] transition-all duration-300 ease-in-out',
        sidebarOpen ? 'w-64 is-mobile-open' : 'w-16 is-mobile-closed'
      ]"
    >
      <div class="p-4 flex items-center justify-between">
        <button @click="toggleSidebar" class="p-2 hover:bg-gray-200 rounded-full text-gray-500 hover:text-gray-900 transition-colors">
          <Menu class="w-5 h-5" />
        </button>
      </div>

      <div class="px-3 py-2">
        <button 
          class="flex items-center gap-3 w-full p-3 rounded-full bg-[#DDE3EA] hover:bg-gray-200 text-gray-700 hover:text-gray-900 transition-colors border border-transparent hover:border-gray-300"
          :class="{ 'justify-center': !sidebarOpen }"
          @click="startNewChat"
          :title="sidebarOpen ? '' : '新对话'"
          :aria-label="sidebarOpen ? undefined : '新对话'"
        >
          <Plus class="w-4 h-4 text-gray-500" />
          <span v-if="sidebarOpen" class="text-sm font-medium">新对话</span>
        </button>
      </div>

      <div class="flex-1 overflow-y-auto mt-4 px-3 space-y-3">
        <div
          v-if="!isLoggedIn && sidebarOpen"
          class="bg-white rounded-xl border border-gray-200 p-3 shadow-sm"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="text-sm font-medium text-gray-900">登录可同步历史对话</div>
            <button
              class="text-xs text-blue-600 hover:text-blue-700 font-semibold"
              @click="showLoginModal = true"
            >
              立即登录
            </button>
          </div>
          <p class="text-xs text-gray-500 mt-2">
            登录后，最近对话会自动保存并可在任意设备查看
          </p>
        </div>

        <div>
          <div
            v-if="sidebarOpen"
            class="mb-2 px-3 text-xs font-medium text-gray-500 flex items-center justify-between"
          >
            <span>最近对话</span>
            <button
              v-if="isLoggedIn"
              class="text-[11px] text-blue-600 hover:text-blue-700"
              @click="loadSessions"
              :disabled="loadingSessions"
            >
              {{ loadingSessions ? '刷新中…' : '刷新' }}
            </button>
          </div>
          <div v-else-if="isLoggedIn" class="mb-2 px-1 flex justify-center">
            <button
              class="p-2 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors"
              @click="loadSessions"
              :disabled="loadingSessions"
              :title="loadingSessions ? '刷新中…' : '刷新会话'"
              :aria-label="loadingSessions ? '刷新中' : '刷新会话'"
            >
              <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': loadingSessions }" />
            </button>
          </div>

          <div class="space-y-1">
            <template v-if="isLoggedIn">
              <div v-if="loadingSessions && sidebarOpen" class="text-xs text-gray-500 px-3 py-2">会话加载中...</div>
              <div v-else-if="!chatSessions.length && sidebarOpen" class="text-xs text-gray-500 px-3 py-2">
                暂无会话，开始新的对话吧
              </div>
              <button 
                v-for="session in chatSessions" 
                :key="session.id"
                class="flex items-center gap-3 w-full p-2 rounded-full hover:bg-gray-200 text-gray-700 hover:text-gray-900 transition-colors group text-left"
                :class="[
                  { 'justify-center': !sidebarOpen },
                  selectedSessionId === session.id ? 'bg-white shadow-sm border border-gray-200' : ''
                ]"
                @click="handleSelectSession(session)"
                :title="sidebarOpen ? '' : (session.title || '未命名对话')"
                :aria-label="sidebarOpen ? undefined : (session.title || '未命名对话')"
              >
                <MessageSquare class="w-4 h-4 text-gray-500" />
                <div v-if="sidebarOpen" class="flex-1 min-w-0">
                  <div class="text-sm truncate font-medium text-gray-900">{{ session.title || '未命名对话' }}</div>
                  <div class="flex items-center justify-between text-[11px] text-gray-500">
                    <span>消息 {{ session.message_count }}</span>
                    <span>{{ formatTime(session.last_message_at) }}</span>
                  </div>
                </div>
                <button
                  v-if="sidebarOpen"
                  class="ml-auto opacity-0 group-hover:opacity-100 p-1 hover:text-gray-900 text-gray-500"
                  @click.stop="deleteSession(session.id)"
                  title="删除对话"
                >
                  <Trash2 class="w-3 h-3" />
                </button>
              </button>
            </template>
            <template v-else>
              <div v-if="sidebarOpen" class="text-xs text-gray-500 px-3 py-2">登录后查看和管理历史对话</div>
              <button
                v-else
                class="w-full flex items-center justify-center p-2 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors"
                @click="showLoginModal = true"
                title="登录后查看历史对话"
                aria-label="登录后查看历史对话"
              >
                <LogIn class="w-4 h-4" />
              </button>
            </template>
          </div>
        </div>
      </div>

      <div class="p-3 mt-auto relative">
        <!-- User Menu Dropdown -->
        <div ref="userMenuRef" v-if="showUserMenu && sidebarOpen" class="absolute bottom-full left-3 w-56 mb-2 bg-[#F0F4F9] rounded-xl shadow-xl overflow-hidden border border-gray-200 z-50">
          <div class="py-1">
            <button class="flex items-center gap-3 px-4 py-3 text-sm text-gray-700 hover:bg-gray-200 transition-colors w-full text-left">
              <HelpCircle class="w-4 h-4 text-gray-500" />
              <span>帮助</span>
            </button>
            <div class="h-px bg-gray-200 my-1"></div>
            <a :href="getServiceUrl('/')" class="flex items-center gap-3 px-4 py-3 text-sm text-gray-700 hover:bg-gray-200 transition-colors">
              <List class="w-4 h-4 text-gray-500" />
              <span>日志列表</span>
            </a>
            <a :href="getServiceUrl('/raven-manager')" class="flex items-center gap-3 px-4 py-3 text-sm text-gray-700 hover:bg-gray-200 transition-colors">
              <Box class="w-4 h-4 text-gray-500" />
              <span>Raven 包管理</span>
            </a>
            <div class="h-px bg-gray-200 my-1"></div>
             <button
               class="flex items-center gap-3 px-4 py-3 text-sm text-gray-500 hover:bg-gray-200 transition-colors w-full text-left"
               @click="isLoggedIn ? handleUserLogout() : (showLoginModal = true)"
             >
              <component :is="isLoggedIn ? LogOut : LogIn" class="w-4 h-4" />
              <span>{{ isLoggedIn ? '退出登录' : '立即登录' }}</span>
            </button>
          </div>
        </div>

        <!-- User Profile / Activity -->
        <div 
          ref="userButtonRef"
          @click="toggleUserMenu"
          class="mt-2 flex items-center gap-3 p-2 rounded-full hover:bg-gray-200 cursor-pointer relative" 
          :class="{ 'justify-center': !sidebarOpen, 'bg-gray-200': showUserMenu }"
          :title="sidebarOpen ? '' : `${currentUserName}${isLoggedIn ? '' : '（未登录）'}`"
          :aria-label="sidebarOpen ? undefined : `${currentUserName}${isLoggedIn ? '' : '（未登录）'}`"
        >
           <div class="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-purple-600 flex items-center justify-center text-xs font-bold text-white">
             {{ userInitial }}
           </div>
           <div v-if="sidebarOpen" class="text-xs text-gray-700">
             <div class="font-semibold text-gray-900">{{ currentUserName }}</div>
             <div class="text-[10px] text-gray-500">
               <span v-if="isLoggedIn">{{ currentUserEmail || '已登录' }}</span>
               <span v-else class="text-blue-600">未登录 · 点击登录</span>
             </div>
           </div>
        </div>
      </div>
    </div>

    <div
      v-if="sidebarOpen"
      class="ai-sidebar-backdrop md:hidden"
      @click="sidebarOpen = false"
    ></div>

    <!-- Main Content -->
    <div class="flex-1 flex flex-col h-full relative ai-main">
      <!-- Top Bar -->
      <div class="h-16 flex items-center justify-between px-6 ai-topbar">
        <button
          v-if="!sidebarOpen"
          class="md:hidden inline-flex items-center justify-center p-2 rounded-full bg-[#F0F4F9] text-gray-600 hover:text-gray-900"
          @click="sidebarOpen = true"
          aria-label="打开侧边栏"
          type="button"
        >
          <Menu class="w-5 h-5" />
        </button>
        <div class="flex items-center gap-3 ai-topbar-main-group">
          <div class="flex items-center gap-2">
            <span class="text-xl font-medium bg-gradient-to-r from-blue-400 via-purple-400 to-red-400 bg-clip-text text-transparent">Raven AI</span>
          </div>
          <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#F0F4F9] text-xs text-gray-700 ai-topbar-target">
            <span class="font-medium text-gray-800">当前目标</span>
            <template v-if="targetAgentName">
              <span
                class="px-2 py-0.5 rounded-full bg-white border border-blue-200 text-blue-700 font-semibold flex items-center gap-1"
              >
                <Box class="w-3.5 h-3.5" />
                {{ targetAgentName }}
              </span>
              <button
                class="p-1 rounded-full hover:bg-gray-200 text-gray-500"
                @click="clearTargetAgent"
                title="清除已选助手"
                type="button"
              >
                <X class="w-3.5 h-3.5" />
              </button>
            </template>
            <template v-else-if="targetDeviceName">
              <span
                class="px-2 py-0.5 rounded-full bg-white border border-gray-200 text-gray-900 font-semibold"
              >
                {{ targetDeviceName }}
              </span>
              <button
                class="p-1 rounded-full hover:bg-gray-200 text-gray-500"
                @click="clearTargetDevice"
                title="清除已选设备"
                type="button"
              >
                <X class="w-3.5 h-3.5" />
              </button>
            </template>
            <span v-else class="text-gray-500">未选择</span>
          </div>
        </div>
        <div class="flex items-center gap-4 ai-topbar-platform-link-wrap">
            <a 
              :href="getServiceUrl('/')" 
              class="flex items-center gap-2 px-4 py-2 rounded-full bg-black text-white text-sm font-medium hover:bg-gray-800 transition-colors shadow-sm ai-topbar-platform-link"
            >
                <span>返回平台</span>
                <ExternalLink class="w-3.5 h-3.5" />
            </a>
        </div>
      </div>

      <!-- Chat Area -->
      <div ref="chatContainerRef" class="flex-1 overflow-y-auto px-4 md:px-20 py-6 scrollbar-hide scroll-smooth">
        <div class="max-w-3xl mx-auto space-y-8">
          
          <template v-if="chatHistory.length === 0 && !loadingMessages">
            <div class="mt-8 sm:mt-20">
              <h1 class="text-3xl sm:text-5xl font-medium bg-gradient-to-r from-blue-500 via-purple-500 to-red-500 bg-clip-text text-transparent w-fit mb-2">你好，{{ currentUserName }}</h1>
              <h2 class="text-3xl sm:text-5xl font-medium text-[#444746] mb-8 sm:mb-12">今天有什么我可以帮你的吗？</h2>
            </div>
          </template>

          <template v-else-if="loadingMessages">
            <div class="text-center text-gray-500 text-sm mt-12">正在加载历史对话...</div>
          </template>

          <template v-else>
             <div 
               v-for="(msg, idx) in chatHistory" 
               :key="msg.id || idx" 
               class="flex gap-4 group w-full"
               :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
             >
               <!-- AI Avatar (Left side only) -->
               <div 
                 v-if="msg.role === 'ai'"
                 class="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center mt-1"
               >
                 <div class="w-6 h-6 rounded-full bg-gradient-to-tr from-blue-500 via-purple-500 to-red-500 animate-pulse-slow"></div>
               </div>

               <!-- Message Content Bubble -->
               <div 
                 class="max-w-[80%] rounded-2xl px-5 py-3 text-base leading-relaxed"
                 :class="[
                   msg.role === 'user' 
                     ? 'bg-[#F0F4F9] text-gray-900 rounded-tr-sm whitespace-pre-wrap' 
                     : 'bg-transparent text-gray-900 px-0'
                 ]"
               >
                 <template v-if="msg.content === '正在思考...'">
                   <span class="thinking-text">正在思考...</span>
                 </template>
                 <template v-else-if="msg.role === 'ai'">
                   <div v-html="renderAiMessage(msg.content)"></div>
                 </template>
                 <template v-else>
                   {{ msg.content }}
                 </template>
               </div>
             </div>
          </template>

        </div>
      </div>

      <!-- Input Area -->
      <div class="p-4 md:pb-6">
        <div
          ref="inputAreaRef"
          class="max-w-3xl mx-auto bg-[#F0F4F9] rounded-3xl p-2 md:p-3 relative group focus-within:bg-gray-100 transition-colors"
        >
          <div
            v-if="mentionVisible"
            ref="mentionDropdownRef"
            class="absolute left-0 right-0 bottom-full mb-3 bg-white border border-gray-200 rounded-2xl shadow-xl overflow-y-auto max-h-64 z-30"
          >
            <div class="px-4 py-3 text-sm text-gray-600 border-b border-gray-100 flex items-center justify-between">
              <span>选择目标（设备或重构包配置管理员）</span>
              <span class="text-xs text-gray-400">输入 @ 或名称进行过滤</span>
            </div>
            <div v-if="isLoadingDevices" class="px-4 py-3 text-sm text-gray-500">设备列表加载中...</div>
            <div v-if="!filteredMentionOptions.length" class="px-4 py-3 text-sm text-gray-500">暂无匹配的目标</div>
            <template v-else>
              <button
                v-for="(option, idx) in filteredMentionOptions"
                :key="`${option.type}-${option.id}`"
                type="button"
                class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                :class="{ 'bg-gray-100': idx === mentionSelectedIndex }"
                :ref="(el) => setMentionOptionRef(el, idx)"
                @mousedown.prevent="applyMentionSelection(option)"
                @mouseenter="mentionSelectedIndex = idx"
              >
                <template v-if="option.type === 'device'">
                  <span
                    class="w-2 h-2 rounded-full"
                    :class="deviceStatusDotClass(option.status)"
                  ></span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="font-medium text-gray-900 truncate">{{ option.name }}</span>
                      <span class="text-[11px] text-gray-500 uppercase">{{ option.status === 'online' ? '在线' : '离线' }}</span>
                    </div>
                    <div class="text-xs text-gray-500 truncate">ID: {{ option.id }}</div>
                  </div>
                  <div v-if="option.device.models?.length" class="text-[11px] text-gray-500 truncate max-w-[120px] text-right">
                    {{ option.device.models.slice(0, 2).join(', ') }}<span v-if="option.device.models.length > 2"> ...</span>
                  </div>
                </template>
                <template v-else>
                  <div class="w-8 h-8 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center">
                    <Box class="w-4 h-4" />
                  </div>
                  <div class="flex-1 min-w-0">
                    <div class="font-medium text-gray-900">{{ option.name }}</div>
                    <div class="text-xs text-gray-500 truncate">
                      {{ option.description || '智能搜索重构包，返回详情、下载与提示词' }}
                    </div>
                  </div>
                </template>
              </button>
            </template>
          </div>
          <div
            v-if="targetDeviceName || targetAgentName"
            class="flex items-center gap-2 mb-2 px-3 py-2 rounded-2xl bg-white border border-gray-200 text-sm text-gray-700"
          >
            <span class="text-gray-500">当前目标</span>
            <span class="font-semibold text-gray-900 flex items-center gap-1">
              <template v-if="targetAgentName">
                <Box class="w-4 h-4 text-blue-600" />
                {{ targetAgentName }}
              </template>
              <template v-else>
                {{ targetDeviceName }}
              </template>
            </span>
            <button
              class="ml-auto p-1 rounded-full hover:bg-gray-100 text-gray-500"
              type="button"
              @click="targetAgentName ? clearTargetAgent() : clearTargetDevice()"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
          <div class="flex items-end gap-2">
            <button class="p-2 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors">
              <ImageIcon class="w-5 h-5" />
            </button>
            
            <textarea 
              v-model="inputMessage"
              ref="textareaRef"
              @keydown="handleKeydown"
              @input="handleInput"
              placeholder="在这里输入指令"
              class="flex-1 bg-transparent border-0 focus:ring-0 text-gray-900 resize-none max-h-32 py-2 scrollbar-hide placeholder-gray-500"
              rows="1"
              style="min-height: 44px;"
            ></textarea>
            
            <button class="p-2 rounded-full hover:bg-gray-200 text-gray-500 hover:text-gray-900 transition-colors" v-if="!inputMessage">
              <Mic class="w-5 h-5" />
            </button>
            
            <button 
              @click="sendMessage"
              class="p-2 rounded-full transition-colors"
              :class="inputMessage ? 'bg-black text-white hover:bg-gray-800' : 'text-gray-400 hover:text-gray-600'"
            >
              <Send class="w-5 h-5" />
            </button>
          </div>
        </div>
        <div class="text-center text-xs text-gray-500 mt-2">
          Raven AI 可能会犯错。请核对重要信息 · 输入 @ 选择设备或重构包配置管理员。
        </div>
      </div>
    </div>

    <!-- Login Modal -->
    <div
      v-if="showLoginModal"
      class="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50 px-4"
    >
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-5 border border-gray-100">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="text-lg font-semibold text-gray-900">登录账户</h3>
            <p class="text-xs text-gray-500 mt-1">登录可同步历史对话</p>
          </div>
          <button
            class="text-gray-500 hover:text-gray-700 rounded-full p-1"
            @click="showLoginModal = false"
            aria-label="关闭登录"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="space-y-4">
          <label class="block text-sm text-gray-700">
            <span class="text-xs text-gray-600">用户名</span>
            <input
              v-model="loginForm.username"
              type="text"
              class="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none"
              placeholder="输入用户名"
              autocomplete="username"
            />
          </label>
          <label class="block text-sm text-gray-700">
            <span class="text-xs text-gray-600">密码</span>
            <input
              v-model="loginForm.password"
              type="password"
              class="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none"
              placeholder="输入密码"
              autocomplete="current-password"
            />
          </label>
        </div>

        <div class="flex items-center gap-3">
          <button
            class="px-4 py-2 bg-black text-white rounded-lg text-sm font-semibold hover:bg-gray-800 transition disabled:opacity-60 flex items-center gap-2"
            :disabled="isLoggingIn"
            @click="handleUserLogin"
          >
            <Loader2 v-if="isLoggingIn" class="w-4 h-4 animate-spin" />
            <span>{{ isLoggingIn ? '登录中…' : '立即登录' }}</span>
          </button>
          <button
            class="px-4 py-2 rounded-lg border border-gray-200 text-sm text-gray-700 hover:bg-gray-50"
            @click="showLoginModal = false"
          >
            取消
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scrollbar-hide::-webkit-scrollbar {
    display: none;
}
.scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
}
.animate-pulse-slow {
  animation: pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: .7;
  }
}
.thinking-text {
  display: inline-block;
  background: linear-gradient(90deg, #9ca3af 0%, #e5e7eb 50%, #9ca3af 100%);
  background-size: 200% 100%;
  background-repeat: no-repeat;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: thinking-shimmer 1.6s ease-in-out infinite;
  font-weight: 600;
}
@keyframes thinking-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

@media (max-width: 768px) {
  .ai-chat-page {
    position: relative;
  }

  .ai-sidebar-backdrop {
    position: absolute;
    inset: 0;
    background: rgba(15, 23, 42, 0.35);
    z-index: 30;
  }

  .ai-sidebar {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 40;
    border-right: 1px solid #e5e7eb;
    box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12);
    transition: transform 0.3s ease, width 0.3s ease;
  }

  .ai-sidebar.is-mobile-open {
    transform: translateX(0);
    pointer-events: auto;
  }

  .ai-sidebar.is-mobile-closed {
    transform: translateX(-100%);
    pointer-events: none;
  }

  .ai-sidebar.w-16 {
    width: 3.5rem !important;
  }

  .ai-sidebar.w-64 {
    width: min(82vw, 320px) !important;
  }

  .ai-main {
    width: 100%;
  }

  .ai-topbar {
    min-height: 3.5rem;
    padding: 0.75rem;
    gap: 0.5rem;
    align-items: center;
    flex-direction: row;
    flex-wrap: nowrap;
  }

  .ai-topbar-main-group {
    min-width: 0;
    flex: 1 1 auto;
    flex-wrap: nowrap;
    overflow: hidden;
  }

  .ai-topbar-target {
    min-width: 0;
    overflow: hidden;
  }

  .ai-topbar-platform-link-wrap {
    flex: 0 0 auto;
  }

  .ai-topbar-platform-link {
    white-space: nowrap;
    padding: 0.45rem 0.7rem;
    font-size: 0.75rem;
  }
}
</style>
