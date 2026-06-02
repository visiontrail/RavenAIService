<script setup lang="ts">
import { computed, onMounted, onUnmounted, nextTick, ref, watch } from 'vue'
import { deviceLinkApi } from '@/api/deviceLink'
import {
  streamPackagesAgentSearch,
  getRavenPackageDetail,
  ravenBaseUrl,
} from '@/api/raven'
import { userApi } from '@/api/user'
import type {
  DeviceInfo,
  PackageAgentSearchResponse,
  PackageAgentTraceEvent,
  RavenPackage,
} from '@/types'
import { renderMarkdown, processMermaidBlocks } from '@/utils/markdownRenderer'
import { loadMermaid } from '@/utils/mermaidLoader'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
import { useChatSessionStore } from '@/stores/chatSession'
import {
  useConversationRunsStore,
  type ChatEntry,
  type PendingPermission,
} from '@/stores/conversationRuns'
import AgentTraceStream from '@/components/AgentTraceStream.vue'
import { projectRepoApi, type ProjectRepoOption } from '@/api'
import { downloadFile } from '@/utils'

type AgentOption = {
  id: string
  name: string
  description?: string
  agentType: 'package-manager' | 'log-analysis' | 'project-expert'
}

const packageAgentOption: AgentOption = {
  id: 'package-manager',
  name: '重构包配置管理员',
  agentType: 'package-manager',
  description: '调用重构包智能搜索，返回详情、下载链接与重构提示词'
}

const logAnalysisAgentOption: AgentOption = {
  id: 'log-analysis',
  name: '日志分析',
  agentType: 'log-analysis',
  description: '上传日志包并调用 Log Analysis Agent，保留工作区支持追问'
}

const projectExpertAgentOption: AgentOption = {
  id: 'project-expert',
  name: '项目专家',
  agentType: 'project-expert',
  description: '选择已登记项目后直接提问，复用项目源码工作区支持追问'
}

const acceptedLogArchiveTypes = '.zip,.tar,.tgz,.gz,.tar.gz,.tar.bz2,.bz2,.tar.xz,.xz,.7z,.rar'

const userStore = useUserStore()
const appStore = useAppStore()
const sessionStore = useChatSessionStore()
const runsStore = useConversationRunsStore()

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
const deviceMenuRef = ref<HTMLElement | null>(null)
const deviceMenuBtnRef = ref<HTMLElement | null>(null)
const topMoreMenuRef = ref<HTMLElement | null>(null)
const topMoreBtnRef = ref<HTMLElement | null>(null)
const logFileInputRef = ref<HTMLInputElement | null>(null)

const devices = ref<DeviceInfo[]>([])
const isLoadingDevices = ref(false)

const deviceMenuVisible = ref(false)
const deviceKeyword = ref('')

const targetDeviceId = ref<string | null>(null)
const targetDeviceName = ref<string | null>(null)
const targetAgent = ref<AgentOption | null>(null)
const selectedLogFile = ref<File | null>(null)
const isLogFileDragOver = ref(false)
let logFileDragDepth = 0

const showTopMoreMenu = ref(false)
const showRenameModal = ref(false)
const renameModalTitle = ref('')
const renameModalInputRef = ref<HTMLInputElement | null>(null)
const renameModalInFlight = ref(false)

// Local session id used until the user sends the first message; once a run is
// created or a history session is selected, the sessionStore drives this.
const localSessionId = ref<string | null>(null)
const cancelInFlight = ref(false)
const loadedSessionId = ref<string | null>(null)

// All per-conversation state (messages, isSending, pendingPermissions,
// activeRunId, runAgentKind, subscription) now lives in the runs store keyed
// by session id. The template binds to ``currentConversation`` so the panel
// only ever reflects the selected session.
const effectiveSessionId = computed<string | null>(
  () => sessionStore.selectedSessionId || localSessionId.value,
)
const currentConversation = computed(() => {
  const id = effectiveSessionId.value
  return id ? runsStore.ensureState(id) : null
})
const chatHistory = computed<ChatEntry[]>(() => currentConversation.value?.messages || [])
const loadingMessages = computed(() => !!currentConversation.value?.loadingMessages)
const isSending = computed(() => !!currentConversation.value?.isSending)
const pendingPermissions = computed<PendingPermission[]>(
  () => currentConversation.value?.pendingPermissions || [],
)
const currentPermission = computed<PendingPermission | null>(() =>
  pendingPermissions.value.length > 0 ? pendingPermissions.value[0] : null,
)
const permissionDecisionInFlight = ref(false)
// Sidebar cancel button only when the current session has an active run.
const activeTraceAgentSessionId = computed(() => {
  const s = currentConversation.value
  return s && s.runStatus === 'running' && (
    s.runAgentKind === 'log_analysis' || s.runAgentKind === 'project_expert'
  ) ? s.sessionId : null
})

// 关联项目（用于在日志分析 Agent 中显式指定项目身份；留空则回退到 metadata.json）
const projectRepoOptions = ref<ProjectRepoOption[]>([])
const projectRepoOptionsLoading = ref(false)
const projectRepoOptionsLoaded = ref(false)
const selectedProjectRepoId = ref<number | null>(null)

const ensureProjectRepoOptions = async () => {
  if (projectRepoOptionsLoading.value || projectRepoOptionsLoaded.value) return
  projectRepoOptionsLoading.value = true
  try {
    const response = await projectRepoApi.listEnabled()
    projectRepoOptions.value = Array.isArray(response?.data) ? response.data : []
    projectRepoOptionsLoaded.value = true
  } catch (err) {
    console.warn('加载项目列表失败:', err)
    projectRepoOptions.value = []
  } finally {
    projectRepoOptionsLoading.value = false
  }
}

const isLoggedIn = computed(() => userStore.isAuthenticated)
const currentUserName = computed(() => userStore.profile?.display_name || userStore.profile?.username || '用户')

const isWelcomeMode = computed(() => chatHistory.value.length === 0 && !loadingMessages.value)

const handleClickOutside = (event: MouseEvent) => {
  const target = event.target as Node

  if (showTopMoreMenu.value && topMoreMenuRef.value && topMoreBtnRef.value &&
      !topMoreMenuRef.value.contains(target) && !topMoreBtnRef.value.contains(target)) {
    showTopMoreMenu.value = false
  }

  if (deviceMenuVisible.value && deviceMenuRef.value && deviceMenuBtnRef.value &&
      !deviceMenuRef.value.contains(target) && !deviceMenuBtnRef.value.contains(target)) {
    deviceMenuVisible.value = false
  }
}

const handleKey = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    showTopMoreMenu.value = false
    deviceMenuVisible.value = false
    showRenameModal.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKey)
  fetchDevices()
  // Load the currently-selected session's messages on mount.
  if (sessionStore.selectedSessionId) {
    loadMessages(sessionStore.selectedSessionId)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKey)
  const id = loadedSessionId.value || effectiveSessionId.value
  if (id) runsStore.abortSubscription(id)
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
  if (id) loadMessages(id)
})

watch(() => sessionStore.newChatToken, () => {
  resetPanel()
})

watch(isLoggedIn, (loggedIn) => {
  if (!loggedIn) {
    runsStore.reset()
    localSessionId.value = null
  }
})

watch(selectedProjectRepoId, () => {
  saveAgentSelectionToState()
})

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

const agentKindToOption: Record<string, AgentOption> = {
  log_analysis: logAnalysisAgentOption,
  package: packageAgentOption,
  project_expert: projectExpertAgentOption,
}

const saveAgentSelectionToState = (sessionId?: string | null) => {
  const sid = sessionId ?? effectiveSessionId.value
  if (!sid) return
  const state = runsStore.ensureState(sid)
  const kind = targetAgent.value?.agentType === 'log-analysis' ? 'log_analysis'
    : targetAgent.value?.agentType === 'project-expert' ? 'project_expert'
    : targetAgent.value?.agentType === 'package-manager' ? 'package'
    : null
  state.lastAgentKind = kind as import('@/stores/conversationRuns').AgentKind | null
  state.lastProjectRepoId = selectedProjectRepoId.value
}

const restoreAgentSelectionFromState = (state: ReturnType<typeof runsStore.ensureState>) => {
  const agentKind = state.runAgentKind || state.lastAgentKind
  if (agentKind && agentKindToOption[agentKind]) {
    targetAgent.value = agentKindToOption[agentKind]
    if (agentKind === 'log_analysis' || agentKind === 'project_expert') {
      ensureProjectRepoOptions()
    }
  } else {
    targetAgent.value = null
  }
  selectedProjectRepoId.value = state.lastProjectRepoId ?? null
}

const loadMessages = async (id: string) => {
  if (loadedSessionId.value && loadedSessionId.value !== id) {
    saveAgentSelectionToState(loadedSessionId.value)
    runsStore.abortSubscription(loadedSessionId.value)
  }
  loadedSessionId.value = id
  localSessionId.value = id
  try {
    await runsStore.loadSession(id, {
      authToken: (userStore.token as unknown as string) || null,
      isLoggedIn: isLoggedIn.value,
      force: true,
    })
    const state = runsStore.ensureState(id)
    restoreAgentSelectionFromState(state)
  } catch (error) {
    console.error('加载会话消息失败', error)
    appStore.showNotification({ title: '加载消息失败', type: 'error' })
  }
}

const resetPanel = () => {
  saveAgentSelectionToState()
  const id = loadedSessionId.value || effectiveSessionId.value
  if (id) runsStore.abortSubscription(id)
  loadedSessionId.value = null
  localSessionId.value = null
  inputMessage.value = ''
  targetAgent.value = null
  targetDeviceId.value = null
  targetDeviceName.value = null
  selectedProjectRepoId.value = null
  selectedLogFile.value = null
  deviceMenuVisible.value = false
  nextTick(() => textareaRef.value?.focus())
}

const clearCurrentMessages = () => {
  showTopMoreMenu.value = false
  const state = currentConversation.value
  if (!state || !state.messages.length) return
  if (!window.confirm('确定要清空当前消息吗？')) return
  state.messages = []
}

const deleteCurrentSession = async () => {
  showTopMoreMenu.value = false
  const id = sessionStore.selectedSessionId
  if (!id) return
  const confirmed = window.confirm('确定要删除该对话吗？此操作不可恢复。')
  if (!confirmed) return
  try {
    await sessionStore.removeSession(id)
    runsStore.clearSession(id)
    appStore.showNotification({ title: '会话已删除', type: 'success' })
  } catch (error) {
    console.error('删除会话失败', error)
    appStore.showNotification({ title: '删除失败', type: 'error' })
  }
}

const currentSessionPinned = computed(() => {
  const id = sessionStore.selectedSessionId
  if (!id) return false
  return Boolean(sessionStore.sessions.find((s) => s.id === id)?.is_pinned)
})

const toggleCurrentPin = async () => {
  showTopMoreMenu.value = false
  const id = sessionStore.selectedSessionId
  if (!id) {
    appStore.showNotification({ title: '请先保存对话后再置顶', type: 'warning' })
    return
  }
  const wasPinned = currentSessionPinned.value
  try {
    const ok = await sessionStore.togglePin(id)
    if (ok) {
      appStore.showNotification({
        title: wasPinned ? '已取消置顶' : '已置顶对话',
        type: 'success',
      })
    }
  } catch (error) {
    console.error('置顶操作失败', error)
    appStore.showNotification({ title: '操作失败', type: 'error' })
  }
}

const openRenameModal = () => {
  showTopMoreMenu.value = false
  const id = sessionStore.selectedSessionId
  if (!id) {
    appStore.showNotification({ title: '请先保存对话后再重命名', type: 'warning' })
    return
  }
  renameModalTitle.value = sessionStore.currentTitle || ''
  showRenameModal.value = true
  nextTick(() => {
    renameModalInputRef.value?.select()
  })
}

const commitRenameFromModal = async () => {
  const id = sessionStore.selectedSessionId
  if (!id || renameModalInFlight.value) return
  const title = renameModalTitle.value.trim()
  if (!title) {
    appStore.showNotification({ title: '名称不能为空', type: 'warning' })
    return
  }
  renameModalInFlight.value = true
  try {
    const ok = await sessionStore.renameSession(id, title)
    if (ok) {
      showRenameModal.value = false
      appStore.showNotification({ title: '已重命名', type: 'success' })
    }
  } catch {
    appStore.showNotification({ title: '重命名失败', type: 'error' })
  } finally {
    renameModalInFlight.value = false
  }
}

const padDatePart = (value: number) => String(value).padStart(2, '0')

const formatExportDateTime = (date: Date) => {
  const year = date.getFullYear()
  const month = padDatePart(date.getMonth() + 1)
  const day = padDatePart(date.getDate())
  const hour = padDatePart(date.getHours())
  const minute = padDatePart(date.getMinutes())
  const second = padDatePart(date.getSeconds())
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`
}

const formatExportFileStamp = (date: Date) =>
  formatExportDateTime(date).replace(/[-:]/g, '').replace(' ', '-')

const sanitizeMarkdownFilename = (name: string) => {
  const cleaned = name
    .replace(/[\\/:*?"<>|]+/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80)
  return cleaned || 'RavenAI-对话'
}

const messageSpeakerName = (role: ChatEntry['role']) => {
  if (role === 'user') return currentUserName.value
  if (role === 'ai') return 'RAVENAI'
  return '系统'
}

const buildConversationMarkdown = (exportedAt: Date) => {
  const title = currentChatTitle.value || 'RavenAI 对话'
  const lines: string[] = [
    `# ${title}`,
    '',
    `- 导出时间：${formatExportDateTime(exportedAt)}`,
    `- 会话 ID：${effectiveSessionId.value || '本地新对话'}`,
    `- 消息数：${chatHistory.value.length}`,
    '',
    '---',
  ]

  chatHistory.value.forEach((message, index) => {
    const content = (message.content || '').trim() || '（空消息）'
    lines.push(
      '',
      `## ${index + 1}. ${messageSpeakerName(message.role)}`,
      '',
      content,
    )
  })

  return `${lines.join('\n').trimEnd()}\n`
}

const exportCurrentConversationMarkdown = () => {
  showTopMoreMenu.value = false
  if (!chatHistory.value.length) {
    appStore.showNotification({ title: '暂无可导出的消息', type: 'warning' })
    return
  }

  const exportedAt = new Date()
  const markdown = buildConversationMarkdown(exportedAt)
  const filename = `${sanitizeMarkdownFilename(currentChatTitle.value || 'RavenAI-对话')}-${formatExportFileStamp(exportedAt)}.md`
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  downloadFile(blob, filename)
  appStore.showNotification({ title: 'Markdown 已导出', type: 'success' })
}

const sortedDevices = computed<DeviceInfo[]>(() =>
  devices.value
    .slice()
    .sort((a, b) => (a.status === b.status ? 0 : a.status === 'online' ? -1 : 1)),
)

const filteredDeviceOptions = computed<DeviceInfo[]>(() => {
  const keyword = deviceKeyword.value.trim().toLowerCase()
  const list = sortedDevices.value
  if (!keyword) return list
  return list.filter((device) =>
    `${device.name || ''} ${device.id}`.toLowerCase().includes(keyword),
  )
})

const targetAgentName = computed(() => targetAgent.value?.name || null)
const isPackageAgentSelected = computed(() => targetAgent.value?.agentType === 'package-manager')
const isProjectExpertAgentSelected = computed(() => targetAgent.value?.agentType === 'project-expert')
const isLogAnalysisAgentSelected = computed(() =>
  targetAgent.value?.agentType === 'log-analysis' || !!selectedLogFile.value
)
const isProjectRepoSelectVisible = computed(() =>
  isLogAnalysisAgentSelected.value || isProjectExpertAgentSelected.value
)
const isLogFileUploadDisabled = computed(() =>
  isPackageAgentSelected.value || isProjectExpertAgentSelected.value
)
const isProjectRepoRequiredMissing = computed(() =>
  isProjectExpertAgentSelected.value && selectedProjectRepoId.value === null
)

// ZIP inspection: read central directory to check if metadata.json is present
const zipMetadataCheckResult = ref<boolean | null>(null) // null=unknown/non-zip, true=present, false=absent

async function checkZipForMetadata(file: File): Promise<boolean | null> {
  if (!file.name.toLowerCase().endsWith('.zip')) return null
  try {
    const maxTail = Math.min(file.size, 22 + 65535)
    const tailBuf = await file.slice(file.size - maxTail).arrayBuffer()
    const tail = new DataView(tailBuf)
    let eocdPos = -1
    for (let i = tailBuf.byteLength - 22; i >= 0; i--) {
      if (tail.getUint32(i, true) === 0x06054b50) { eocdPos = i; break }
    }
    if (eocdPos < 0) return null
    const cdSize = tail.getUint32(eocdPos + 12, true)
    const cdOff  = tail.getUint32(eocdPos + 16, true)
    if (cdOff + cdSize > file.size) return null
    const cdBuf = await file.slice(cdOff, cdOff + cdSize).arrayBuffer()
    const cd = new DataView(cdBuf)
    const dec = new TextDecoder('utf-8', { fatal: false })
    let p = 0
    while (p + 46 <= cdBuf.byteLength) {
      if (cd.getUint32(p, true) !== 0x02014b50) break
      const fnLen  = cd.getUint16(p + 28, true)
      const extLen = cd.getUint16(p + 30, true)
      const cmtLen = cd.getUint16(p + 32, true)
      if (p + 46 + fnLen > cdBuf.byteLength) break
      const name = dec.decode(new Uint8Array(cdBuf, p + 46, fnLen))
      if (name === 'metadata.json' || name.endsWith('/metadata.json')) return true
      p += 46 + fnLen + extLen + cmtLen
    }
    return false
  } catch { return null }
}

watch(selectedLogFile, async (file) => {
  zipMetadataCheckResult.value = null
  if (file) zipMetadataCheckResult.value = await checkZipForMetadata(file)
})

// Warning: log-analysis agent active but no file attached in the composer.
// Only relevant before the first submission — once the conversation already
// has messages, a log-analysis request has been sent and follow-up questions
// don't need a new attachment. This also prevents the reminder from
// re-appearing after send, when the composer's file selection is cleared.
const logAnalysisNoAttachmentWarning = computed(() =>
  targetAgent.value?.agentType === 'log-analysis' &&
  !selectedLogFile.value &&
  chatHistory.value.length === 0
)

// Error: ZIP file has no metadata.json and no project manually selected → cannot identify project
const logAnalysisMetadataError = computed(() =>
  isLogAnalysisAgentSelected.value &&
  !!selectedLogFile.value &&
  zipMetadataCheckResult.value === false &&
  selectedProjectRepoId.value === null
)

const sendDisabled = computed(() =>
  !isLoggedIn.value ||
  isSending.value ||
  (!inputMessage.value.trim() && !selectedLogFile.value) ||
  isProjectRepoRequiredMissing.value ||
  logAnalysisMetadataError.value
)

const setTargetAgent = (option: AgentOption) => {
  targetAgent.value = option
  targetDeviceId.value = null
  targetDeviceName.value = null
  if (option.agentType === 'log-analysis' || option.agentType === 'project-expert') {
    ensureProjectRepoOptions()
  }
  saveAgentSelectionToState()
}

// ── GeneralAgent 路由建议（suggested_agent_type）的展示与一键切换 ──
// 当用户未选专门 Agent、通用 Agent 判定请求更适合某个专门 Agent 时，后端会回带
// suggested_agent_type；这里给出醒目提示并支持一键切换（设备操作走独立入口，
// 仅文字引导）。
const SUGGESTED_AGENT_LABELS: Record<string, string> = {
  device: '设备操作',
  log_analysis: '日志分析',
  package_search: '重构包配置管理员',
  project_expert: '项目专家',
}

const suggestedAgentType = computed(() => currentConversation.value?.suggestedAgentType || null)

// 用户已经切到对应 Agent 后无需再提示。
const suggestedAgentAlreadySelected = computed(() => {
  const key = suggestedAgentType.value
  const at = targetAgent.value?.agentType
  return (
    (key === 'log_analysis' && at === 'log-analysis') ||
    (key === 'package_search' && at === 'package-manager') ||
    (key === 'project_expert' && at === 'project-expert')
  )
})

const suggestedAgentLabel = computed(() => {
  const key = suggestedAgentType.value
  if (!key || suggestedAgentAlreadySelected.value) return null
  return SUGGESTED_AGENT_LABELS[key] || null
})

// 设备操作通过独立下拉选择，不在 AgentOption 体系内，故不提供一键切换。
const suggestedAgentSwitchable = computed(() => {
  const key = suggestedAgentType.value
  return key === 'log_analysis' || key === 'package_search' || key === 'project_expert'
})

const chooseSuggestedAgent = () => {
  switch (suggestedAgentType.value) {
    case 'log_analysis':
      setTargetAgent(logAnalysisAgentOption)
      break
    case 'package_search':
      setTargetAgent(packageAgentOption)
      break
    case 'project_expert':
      setTargetAgent(projectExpertAgentOption)
      break
    default:
      break
  }
}

// 渲染结果按内容缓存，确保相同内容在组件多次重渲染时返回**完全相同**的 HTML
// 字符串。否则 markdownRenderer 内部的自增计数器会让每次渲染生成不同的
// mermaid 容器 id，导致 v-html 字符串变化、Vue 重新 patch innerHTML，
// 从而抹掉 processMermaidBlocks() 异步插入的 SVG（表现为图表一直“渲染中…”）。
const aiMessageHtmlCache = new Map<string, string>()
const AI_MESSAGE_CACHE_LIMIT = 200

const renderAiMessage = (content: string) => {
  const key = content || ''
  const cached = aiMessageHtmlCache.get(key)
  if (cached !== undefined) return cached
  const html = renderMarkdown(key, { wrapperClass: 'markdown-content text-ink' })
  // 简单 FIFO 上限，避免流式过程中逐 token 的中间内容无限堆积。
  if (aiMessageHtmlCache.size >= AI_MESSAGE_CACHE_LIMIT) {
    const oldest = aiMessageHtmlCache.keys().next().value
    if (oldest !== undefined) aiMessageHtmlCache.delete(oldest)
  }
  aiMessageHtmlCache.set(key, html)
  return html
}

// ─── Mermaid 图表渲染 ───────────────────────────────────────────────
// 消息内容通过 v-html 插入后，占位的 .mermaid-container 需异步渲染为 SVG。
// 仅在流式输出结束（!isSending）后处理，避免未闭合的代码块反复渲染与闪烁。
const mermaidDialogVisible = ref(false)
const mermaidDialogContainerRef = ref<HTMLElement | null>(null)
let mermaidZoomSource = ''

watch(
  [chatHistory, isSending],
  () => {
    if (isSending.value) return
    nextTick(() => {
      void processMermaidBlocks(chatContainerRef.value)
    })
  },
  // immediate: 会话在挂载时可能已加载（store 缓存/恢复），此时 chatHistory
  // 不会再触发变更事件，需主动渲染一次已存在的 Mermaid 占位块。
  { deep: true, immediate: true }
)

// 事件委托：处理 Mermaid 图表的「复制源码」与「点击放大」交互。
const onThreadClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement | null
  if (!target) return

  const copyBtn = target.closest('.mermaid-copy-btn')
  if (copyBtn) {
    event.stopPropagation()
    const container = copyBtn.closest('.mermaid-container') as HTMLElement | null
    const source = container?.dataset.mermaidSource || ''
    if (!source) return
    navigator.clipboard.writeText(source).then(
      () => ElMessage.success('已复制 Mermaid 源码'),
      () => ElMessage.error('复制失败，请手动选择源码')
    )
    return
  }

  const rendered = target.closest('.mermaid-container.is-rendered') as HTMLElement | null
  if (rendered) {
    openMermaidZoom(rendered)
  }
}

const openMermaidZoom = (container: HTMLElement) => {
  mermaidZoomSource = container.dataset.mermaidSource || ''
  if (!mermaidZoomSource) return
  mermaidZoomScale.value = 1
  mermaidDialogVisible.value = true
  nextTick(async () => {
    const host = mermaidDialogContainerRef.value
    if (!host) return
    host.innerHTML = '<div class="mermaid-loading">图表渲染中…</div>'
    try {
      const mermaid = await loadMermaid()
      const { svg } = await mermaid.render(`mermaid-zoom-${Date.now()}`, mermaidZoomSource)
      host.innerHTML = svg
      applyMermaidZoom()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      host.innerHTML = `<div class="mermaid-error">⚠ 图表渲染失败：${message}</div>`
    }
  })
}

// ─── 放大弹窗：缩放控制 ───────────────────────────────────────────────
const mermaidZoomScale = ref(1)
const MERMAID_ZOOM_MIN = 0.25
const MERMAID_ZOOM_MAX = 5
const MERMAID_ZOOM_STEP = 0.2

const getZoomSvgElement = (): SVGSVGElement | null =>
  mermaidDialogContainerRef.value?.querySelector('svg') ?? null

const applyMermaidZoom = () => {
  const svg = getZoomSvgElement()
  if (!svg) return
  svg.style.transformOrigin = 'top center'
  svg.style.transform = `scale(${mermaidZoomScale.value})`
}

const setMermaidZoom = (value: number) => {
  mermaidZoomScale.value = Math.min(
    MERMAID_ZOOM_MAX,
    Math.max(MERMAID_ZOOM_MIN, Math.round(value * 100) / 100)
  )
  applyMermaidZoom()
}

const zoomInMermaid = () => setMermaidZoom(mermaidZoomScale.value + MERMAID_ZOOM_STEP)
const zoomOutMermaid = () => setMermaidZoom(mermaidZoomScale.value - MERMAID_ZOOM_STEP)
const resetMermaidZoom = () => setMermaidZoom(1)

// Ctrl/⌘ + 滚轮：以当前位置为中心平滑缩放
const onMermaidZoomWheel = (event: WheelEvent) => {
  if (!event.ctrlKey && !event.metaKey) return
  event.preventDefault()
  const delta = event.deltaY > 0 ? -MERMAID_ZOOM_STEP : MERMAID_ZOOM_STEP
  setMermaidZoom(mermaidZoomScale.value + delta)
}

// ─── 放大弹窗：拖拽平移 ───────────────────────────────────────────────
// 放大超过 100% 后，图表会溢出可视区域，通过鼠标拖拽滚动 body 查看细节。
const mermaidIsPanning = ref(false)
let panStartX = 0
let panStartY = 0
let panStartScrollLeft = 0
let panStartScrollTop = 0

// 仅当存在可滚动溢出（即放大后超出视口）时才允许拖拽
const isMermaidPannable = (): boolean => {
  const host = mermaidDialogContainerRef.value
  if (!host) return false
  return host.scrollWidth > host.clientWidth || host.scrollHeight > host.clientHeight
}

const onMermaidPanStart = (event: MouseEvent) => {
  if (event.button !== 0) return // 仅响应左键
  const host = mermaidDialogContainerRef.value
  if (!host || !isMermaidPannable()) return
  event.preventDefault()
  mermaidIsPanning.value = true
  panStartX = event.clientX
  panStartY = event.clientY
  panStartScrollLeft = host.scrollLeft
  panStartScrollTop = host.scrollTop
  window.addEventListener('mousemove', onMermaidPanMove)
  window.addEventListener('mouseup', onMermaidPanEnd)
}

const onMermaidPanMove = (event: MouseEvent) => {
  const host = mermaidDialogContainerRef.value
  if (!host || !mermaidIsPanning.value) return
  host.scrollLeft = panStartScrollLeft - (event.clientX - panStartX)
  host.scrollTop = panStartScrollTop - (event.clientY - panStartY)
}

const onMermaidPanEnd = () => {
  mermaidIsPanning.value = false
  window.removeEventListener('mousemove', onMermaidPanMove)
  window.removeEventListener('mouseup', onMermaidPanEnd)
}

// ─── 放大弹窗：导出图片（下载 / 复制）────────────────────────────────
// 将渲染后的 SVG 光栅化为 PNG。2x 缩放保证清晰度，白色底避免透明背景。
const mermaidSvgToCanvas = async (svgEl: SVGSVGElement): Promise<HTMLCanvasElement> => {
  const clone = svgEl.cloneNode(true) as SVGSVGElement
  clone.style.transform = '' // 去除缩放，导出原始尺寸

  const viewBox = svgEl.viewBox?.baseVal
  const rect = svgEl.getBoundingClientRect()
  const width =
    (viewBox && viewBox.width) ||
    parseFloat(svgEl.getAttribute('width') || '') ||
    rect.width ||
    800
  const height =
    (viewBox && viewBox.height) ||
    parseFloat(svgEl.getAttribute('height') || '') ||
    rect.height ||
    600

  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))
  if (!clone.getAttribute('xmlns')) {
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  }

  const xml = new XMLSerializer().serializeToString(clone)
  const src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(xml)

  const img = new Image()
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve()
    img.onerror = () => reject(new Error('SVG 加载失败'))
    img.src = src
  })

  const dpr = 2
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(width * dpr))
  canvas.height = Math.max(1, Math.round(height * dpr))
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('无法创建画布上下文')
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.scale(dpr, dpr)
  ctx.drawImage(img, 0, 0, width, height)
  return canvas
}

const canvasToBlob = (canvas: HTMLCanvasElement): Promise<Blob | null> =>
  new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))

const downloadMermaidImage = async () => {
  const svg = getZoomSvgElement()
  if (!svg) return
  try {
    const canvas = await mermaidSvgToCanvas(svg)
    const blob = await canvasToBlob(canvas)
    if (!blob) throw new Error('导出失败')
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `mermaid-${Date.now()}.png`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('已下载图片')
  } catch (err) {
    console.warn('Mermaid 图片下载失败:', err)
    ElMessage.error('图片下载失败')
  }
}

const copyMermaidImage = async () => {
  const svg = getZoomSvgElement()
  if (!svg) return
  if (typeof ClipboardItem === 'undefined' || !navigator.clipboard?.write) {
    ElMessage.warning('当前浏览器不支持复制图片，请使用下载')
    return
  }
  try {
    const canvas = await mermaidSvgToCanvas(svg)
    const blob = await canvasToBlob(canvas)
    if (!blob) throw new Error('导出失败')
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
    ElMessage.success('已复制图片到剪贴板')
  } catch (err) {
    console.warn('Mermaid 图片复制失败:', err)
    ElMessage.error('图片复制失败')
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

const toggleDeviceMenu = () => {
  if (isSending.value) return
  deviceMenuVisible.value = !deviceMenuVisible.value
  if (deviceMenuVisible.value) {
    deviceKeyword.value = ''
    showTopMoreMenu.value = false
    if (!devices.value.length && !isLoadingDevices.value) fetchDevices()
    nextTick(() => deviceMenuRef.value?.querySelector('input')?.focus?.())
  }
}

const selectDevice = (device: DeviceInfo) => {
  targetDeviceId.value = device.id
  targetDeviceName.value = device.name || device.id
  // 设备操作与重构包 / 日志分析 Agent 互斥
  clearTargetAgent()
  selectedLogFile.value = null
  deviceMenuVisible.value = false
}

const isDeviceSelected = computed(() => !!targetDeviceId.value)
const clearTargetDevice = () => { targetDeviceId.value = null; targetDeviceName.value = null }
const clearTargetAgent = () => {
  targetAgent.value = null
  selectedProjectRepoId.value = null
  saveAgentSelectionToState()
}
const clearSelectedLogFile = () => { selectedLogFile.value = null }

const triggerLogFilePicker = () => {
  if (isSending.value || isLogFileUploadDisabled.value) return
  setTargetAgent(logAnalysisAgentOption)
  ensureProjectRepoOptions()
  logFileInputRef.value?.click()
}

const selectLogFile = (file: File) => {
  selectedLogFile.value = file
  setTargetAgent(logAnalysisAgentOption)
  ensureProjectRepoOptions()
}

const handleLogFileChange = (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] || null
  if (file) {
    selectLogFile(file)
  }
  input.value = ''
}

const isFileDragEvent = (event: DragEvent) =>
  Array.from(event.dataTransfer?.types || []).includes('Files')

const handleLogFileDragEnter = (event: DragEvent) => {
  if (isSending.value || isLogFileUploadDisabled.value || !isFileDragEvent(event)) return
  logFileDragDepth += 1
  isLogFileDragOver.value = true
}

const handleLogFileDragOver = (event: DragEvent) => {
  if (!isFileDragEvent(event) || !event.dataTransfer) return
  if (isSending.value || isLogFileUploadDisabled.value) {
    event.dataTransfer.dropEffect = 'none'
    return
  }
  event.dataTransfer.dropEffect = 'copy'
}

const handleLogFileDragLeave = (event: DragEvent) => {
  if (!isFileDragEvent(event)) return
  logFileDragDepth = Math.max(0, logFileDragDepth - 1)
  if (logFileDragDepth === 0) isLogFileDragOver.value = false
}

const handleLogFileDrop = (event: DragEvent) => {
  logFileDragDepth = 0
  isLogFileDragOver.value = false
  if (isSending.value || isLogFileUploadDisabled.value) return
  const file = event.dataTransfer?.files?.[0] || null
  if (file) selectLogFile(file)
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
  ensureProjectRepoOptions()
}

const toggleProjectExpertAgent = () => {
  if (isProjectExpertAgentSelected.value) {
    clearTargetAgent()
    return
  }
  selectedLogFile.value = null
  setTargetAgent(projectExpertAgentOption)
  ensureProjectRepoOptions()
}

// NOTE: stream event handling, plan/device-action formatting, message
// upserts, and SSE buffer parsing have all moved to
// ``stores/conversationRuns.ts``. The remaining helpers here only support the
// synchronous package-agent path (which doesn't go through ChatRunService).

const submitPermissionDecision = async (
  decision: 'allow' | 'deny',
  options: { useEdited?: boolean } = {},
) => {
  const head = currentPermission.value
  const sid = effectiveSessionId.value
  if (!head || !sid || permissionDecisionInFlight.value) return

  let updatedArgs: Record<string, unknown> | null = null
  if (decision === 'allow' && options.useEdited) {
    try {
      const parsed = JSON.parse(head.editingArgs || '{}')
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        head.editingError = '参数必须是 JSON 对象'
        return
      }
      updatedArgs = parsed as Record<string, unknown>
      head.editingError = null
    } catch (err: any) {
      head.editingError = `JSON 解析失败：${err?.message || String(err)}`
      return
    }
  }

  permissionDecisionInFlight.value = true
  try {
    const authToken = userStore.token as unknown as string | undefined
    await runsStore.submitPermission(sid, head.request_id, decision, {
      updatedArgs,
      authToken: authToken || null,
    })
  } catch {
    // store has already recorded ``editingError`` on the entry
  } finally {
    permissionDecisionInFlight.value = false
  }
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

const extractPackageQuery = (content: string) => content.replace(/@重构包配置管理员/g, '').trim()

const runPackageAgent = async (content: string, sid: string, state: ReturnType<typeof runsStore.ensureState>) => {
  // Streaming package-agent path. Trace + ``answer_delta`` events flow through
  // the same ``conversationRuns`` render pipeline as Device / log-analysis so
  // the bubble updates live instead of stalling on "正在思考...". The terminal
  // ``final`` event carries the structured result, which we use to render the
  // recommended-package cards and persist the exchange.
  const query = extractPackageQuery(content)
  const answerId = state.currentAnswerId
  const targetMessage = answerId ? state.messages.find((m) => m.id === answerId) : null
  if (!targetMessage) return
  if (!query) {
    targetMessage.content = '请描述需要查找的重构包需求，例如型号、版本或用途。'
    return
  }
  if (!targetMessage.traceEvents) targetMessage.traceEvents = []

  const ac = new AbortController()
  state.subscription = ac

  let finalData: PackageAgentSearchResponse | null = null

  const handleFinal = async (data: PackageAgentSearchResponse) => {
    finalData = data
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
    // Authoritative correction: replace the streamed prose with the formatted
    // answer (recommended-package cards + links).
    targetMessage.content = formatPackageAgentAnswer(data, recommendedPackages, query)
    targetMessage.traceRunning = false
  }

  try {
    await streamPackagesAgentSearch(query, {
      sessionId: sid,
      signal: ac.signal,
      onEvent: (event: PackageAgentTraceEvent) => {
        if (event?.type === 'final') {
          // Handled after the stream resolves so the structured answer wins
          // over the run_complete final_text. Detail fetches are async, so we
          // stash the payload and await it once the stream closes.
          finalData = (event as { data: PackageAgentSearchResponse }).data
          return
        }
        // Forward trace + answer_delta to the unified renderer.
        runsStore.applyEventToState(state, event)
      },
      onError: (err) => {
        console.warn('重构包流式事件解析失败', err)
      },
    })
    if (finalData) {
      await handleFinal(finalData)
    } else if (targetMessage.content === '正在思考...') {
      targetMessage.content = '（无回复内容）'
    }
    targetMessage.traceRunning = false
    state.runStatus = 'succeeded'

    if (isLoggedIn.value && finalData) {
      try {
        await userApi.saveMessages(sid, content, targetMessage.content, content.slice(0, 60))
        await sessionStore.load()
      } catch (error: any) {
        console.warn('保存重构包配置管理员对话失败', error)
      }
    }
  } catch (error: any) {
    if (error?.name === 'AbortError') return
    console.error('重构包配置管理员调用失败', error)
    targetMessage.content = `重构包配置管理员调用失败：${error?.message || String(error)}`
    targetMessage.traceRunning = false
    state.runStatus = 'failed'
  } finally {
    if (state.subscription === ac) state.subscription = null
  }
}

const cancelActiveTraceAgent = async () => {
  const sid = effectiveSessionId.value
  if (!sid || cancelInFlight.value) return
  cancelInFlight.value = true
  try {
    await runsStore.cancelActiveRun(sid, {
      authToken: (userStore.token as unknown as string) || null,
    })
  } finally {
    cancelInFlight.value = false
  }
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
  if (!isLoggedIn.value) {
    appStore.requestLoginModal('login')
    return
  }
  // Only block the current session — other sessions running in the
  // background do not affect this one.
  if (currentConversation.value?.isSending) return
  const content = inputMessage.value.trim()
  const fileForRequest = selectedLogFile.value
  if (!content && !fileForRequest) return

  // Allocate a session id locally if this is a brand-new conversation. The
  // run service / DB layer will keep the same id for persistence.
  let sid = effectiveSessionId.value
  if (!sid) {
    sid = generateUUID()
    localSessionId.value = sid
    sessionStore.setSelected(sid)
  }
  // Ensure a state object exists for the session before any local writes.
  const state = runsStore.ensureState(sid)

  // Fire-and-forget sidebar title summary.
  if (content) {
    triggerSessionSummary(content, sid)
  }

  const shouldUseProjectExpertAgent =
    isProjectExpertAgentSelected.value || content.includes(`@${projectExpertAgentOption.name}`)

  const shouldUseLogAnalysisAgent =
    !shouldUseProjectExpertAgent &&
    (isLogAnalysisAgentSelected.value || content.includes(`@${logAnalysisAgentOption.name}`) || !!fileForRequest)

  const shouldUsePackageAgent =
    !shouldUseProjectExpertAgent &&
    !shouldUseLogAnalysisAgent &&
    (isPackageAgentSelected.value || content.includes(`@${packageAgentOption.name}`))

  if (shouldUseProjectExpertAgent && !isProjectExpertAgentSelected.value) {
    setTargetAgent(projectExpertAgentOption)
  }
  if (shouldUseLogAnalysisAgent && targetAgent.value?.agentType !== 'log-analysis') {
    setTargetAgent(logAnalysisAgentOption)
  }
  if (shouldUsePackageAgent && !isPackageAgentSelected.value) {
    setTargetAgent(packageAgentOption)
  }

  if (shouldUseProjectExpertAgent && selectedProjectRepoId.value === null) {
    ensureProjectRepoOptions()
    appStore.showNotification({ title: '请先选择关联项目', type: 'warning' })
    return
  }

  const outgoingContent = content || '请分析这个日志包。'
  const authToken = (userStore.token as unknown as string) || null

  // History payload only for anonymous sessions; logged-in sessions reuse
  // the DB transcript on the backend.
  const historyPayload = isLoggedIn.value
    ? []
    : state.messages.map((msg) => ({ role: msg.role, content: msg.content }))

  inputMessage.value = ''
  deviceMenuVisible.value = false

  try {
    if (shouldUseProjectExpertAgent) {
      selectedLogFile.value = null
      await runsStore.startProjectExpertRun(
        sid,
        {
          message: outgoingContent,
          history: historyPayload,
          project_repo_id: selectedProjectRepoId.value as number,
          remember: true,
        },
        { authToken },
      )
    } else if (shouldUseLogAnalysisAgent) {
      const fileSnapshot = fileForRequest
      // Clear the file from the composer; runLogAnalysisRun will append the
      // user message with attachment info.
      if (fileSnapshot) selectedLogFile.value = null
      try {
        await runsStore.startLogAnalysisRun(
          sid,
          {
            message: outgoingContent,
            history: historyPayload,
            file: fileSnapshot,
            project_repo_id: selectedProjectRepoId.value,
            remember: true,
          },
          { authToken },
        )
      } catch (err) {
        if (fileSnapshot) selectedLogFile.value = fileSnapshot
        throw err
      }
    } else if (shouldUsePackageAgent) {
      // Package agent: append local user + placeholder, then open the SSE
      // stream. Trace + answer_delta render through the unified pipeline.
      state.messages.push({
        id: generateUUID(),
        role: 'user',
        content: outgoingContent,
        kind: 'user',
      })
      const placeholderId = generateUUID()
      state.currentAnswerId = placeholderId
      state.messages.push({
        id: placeholderId,
        role: 'ai',
        content: '正在思考...',
        kind: 'answer',
        traceEvents: [],
        traceRunning: true,
      })
      state.isSending = true
      state.runStatus = 'running'
      state.runAgentKind = 'package'
      try {
        await runPackageAgent(outgoingContent, sid, state)
      } finally {
        state.isSending = false
        state.currentAnswerId = null
        state.runAgentKind = null
      }
    } else {
      // DeviceAgent — fully delegated to the run store.
      await runsStore.startDeviceRun(
        sid,
        {
          message: outgoingContent,
          history: historyPayload,
          target_device_id: targetDeviceId.value,
          target_device_name: targetDeviceName.value,
          remember: true,
        },
        { authToken },
      )
    }

    if (isLoggedIn.value) {
      try { await sessionStore.load() } catch (error) { console.warn('刷新会话列表失败', error) }
    }
  } catch (error: any) {
    console.error('请求失败', error)
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

type CapabilityCard = {
  icon: string
  label: string
  kind: 'package' | 'device' | 'log'
  desc: string
  // 多个同义不同表达，重复点击时循环切换，引导用户填写自己的场景
  prompts: string[]
}

const capabilityCards: CapabilityCard[] = [
  { icon: 'box', label: '检索重构包', kind: 'package',
    desc: '按版本、组件或修复内容找到正确的基带包，并对比 changelog。',
    prompts: [
      '帮我找一个基带包，具体需求是……',
      '我想检索一个重构包，筛选条件是……',
      '帮我定位某个版本的基带包，要求是……',
    ] },
  { icon: 'device', label: '自然语言控设备', kind: 'device',
    desc: '说人话即可下发参数；下发前会展示差异并请你确认。',
    prompts: [
      '帮我把某台设备调整一下，目标状态是……',
      '我想给设备下发一组参数，具体是……',
      '请帮我配置一台设备，需求是……',
    ] },
  { icon: 'logs', label: '智能日志分析', kind: 'log',
    desc: '粘贴或上传日志，自动定位异常并给出回流建议。',
    prompts: [
      '请分析这个日志包，具体现象是……',
      '帮我看看这份日志哪里出了问题，现象是……',
      '这段日志麻烦你诊断一下，表现为……',
    ] },
]

// 记录每张卡片当前展示到第几条表达，重复点击则推进到下一条
const capabilityVariantIdx: number[] = capabilityCards.map(() => -1)
// 上次由卡片自动填入的原文，用于判断输入框是否被用户改动过
const lastInjectedPrompt = ref('')

const onPickCapability = (card: CapabilityCard, i: number) => {
  if (card.kind === 'log') setTargetAgent(logAnalysisAgentOption)
  else if (card.kind === 'package') setTargetAgent(packageAgentOption)
  // 设备操作走独立下拉，不在 AgentOption 体系内，故清除已选中的任何 Agent
  else clearTargetAgent()

  // 仅当输入框为空、或仍是上次自动填入的原文时才覆盖/循环；用户已改动则保留其内容
  const untouched = inputMessage.value === '' || inputMessage.value === lastInjectedPrompt.value
  if (untouched) {
    const next = (capabilityVariantIdx[i] + 1) % card.prompts.length
    capabilityVariantIdx[i] = next
    inputMessage.value = card.prompts[next]
    lastInjectedPrompt.value = card.prompts[next]
  }
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
          {{ devices.filter(d => d.status === 'online').length }} 在线 / {{ devices.length || 0 }} 台设备
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
            <button class="rw-menu-item" @click="openRenameModal">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4l10-10-4-4L4 16zM14 6l4 4"/></svg>
              重命名对话 <span class="rw-kbd-right">F2</span>
            </button>
            <button class="rw-menu-item" @click="toggleCurrentPin">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v6M9 8h6l2 6H7zM12 14v8"/></svg>
              {{ currentSessionPinned ? '取消置顶' : '固定到顶部' }}
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
            <button class="rw-menu-item" @click="exportCurrentConversationMarkdown">
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
    <div ref="chatContainerRef" class="rw-scroll" @click="onThreadClick">
      <!-- Welcome -->
      <div v-if="isWelcomeMode" class="rw-welcome">
        <div class="rw-welcome-badge">
          <span class="rw-dot-success"></span>
          {{ devices.filter(d => d.status === 'online').length }} 台在线 / {{ devices.length || 0 }} 台设备
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
            @click="onPickCapability(c, i)"
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
                :on-cancel="msg.traceRunning ? cancelActiveTraceAgent : undefined"
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
      <!-- 未登录提示 -->
      <div v-if="!isLoggedIn" class="rw-composer-alert is-login">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>
        <span>
          AI 功能需要登录后才能使用。
          <button type="button" class="rw-alert-link" @click="appStore.requestLoginModal('login')">立即登录</button>
          或
          <button type="button" class="rw-alert-link" @click="appStore.requestLoginModal('register')">注册账户</button>
        </span>
      </div>
      <!-- Log analysis inline warnings — placed above the composer so the input
           box, tool chips and project dropdown stay anchored to the bottom and
           do not shift under the cursor when an alert appears/disappears. -->
      <!-- GeneralAgent 路由建议：提示用户该请求需切换到对应专门 Agent。 -->
      <div v-if="suggestedAgentLabel" class="rw-composer-alert is-suggest">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
        <span>
          该请求需要使用 <strong>{{ suggestedAgentLabel }}</strong> 才能处理，请先在上方选择对应 Agent 后再发送你的请求。
          <button v-if="suggestedAgentSwitchable" type="button" class="rw-alert-link" @click="chooseSuggestedAgent">切换到{{ suggestedAgentLabel }}</button>
        </span>
      </div>
      <div v-if="logAnalysisMetadataError" class="rw-composer-alert is-error">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <span>
          日志包中未找到 <code>metadata.json</code>，无法自动识别项目。请在下方「关联项目」下拉菜单中手动选择关联项目，或更换包含 <code>metadata.json</code> 的日志包后重试。
        </span>
      </div>
      <div v-else-if="logAnalysisNoAttachmentWarning" class="rw-composer-alert is-warn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;margin-top:1px"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <span>
          <strong>日志分析</strong> 需要上传日志压缩包作为附件，支持格式：<code>.zip</code> <code>.tar</code> <code>.tgz</code> <code>.gz</code> <code>.tar.gz</code> <code>.tar.bz2</code> <code>.bz2</code> <code>.tar.xz</code> <code>.xz</code> <code>.7z</code> <code>.rar</code>。如需直接提问，可切换至
          <button type="button" class="rw-alert-link" @click="toggleProjectExpertAgent">项目专家</button>。
        </span>
      </div>
      <div
        ref="inputAreaRef"
        class="rw-composer"
        :class="{ 'is-log-drag-over': isLogFileDragOver }"
        @dragenter.prevent="handleLogFileDragEnter"
        @dragover.prevent="handleLogFileDragOver"
        @dragleave.prevent="handleLogFileDragLeave"
        @drop.prevent="handleLogFileDrop"
      >
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

        <div v-if="selectedLogFile" class="rw-file-chip rw-file-chip--above">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21 11.5-9.5 9.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5L9.5 18.5a2 2 0 0 1-3-3L15 7"/></svg>
          <span>{{ selectedLogFile.name }}</span>
          <button type="button" aria-label="移除附件" @click="clearSelectedLogFile">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
          </button>
        </div>

        <textarea
          v-model="inputMessage"
          ref="textareaRef"
          class="rw-textarea"
          :placeholder="isLoggedIn ? '给 RavenAI 说点什么，或粘贴一段日志…' : '请先登录后再使用 AI 功能'"
          rows="2"
          :readonly="!isLoggedIn"
          @keydown="handleKeydown"
          @click="!isLoggedIn && appStore.requestLoginModal('login')"
        ></textarea>

        <div class="rw-composer-row">
          <button
            class="rw-mini-btn"
            :disabled="isLogFileUploadDisabled"
            :title="isLogFileUploadDisabled ? '当前智能体不支持附件上传' : '附加日志包'"
            aria-label="附加日志包"
            @click="triggerLogFilePicker"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21 11.5-9.5 9.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5L9.5 18.5a2 2 0 0 1-3-3L15 7"/></svg>
          </button>
          <input
            ref="logFileInputRef"
            class="rw-file-input"
            type="file"
            :accept="acceptedLogArchiveTypes"
            @change="handleLogFileChange"
          />
          <div class="rw-device-wrap">
            <button
              ref="deviceMenuBtnRef"
              class="rw-tool-chip"
              :class="{ active: isDeviceSelected || deviceMenuVisible }"
              type="button"
              aria-haspopup="listbox"
              :aria-expanded="deviceMenuVisible"
              @click="toggleDeviceMenu"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="11" rx="1.5"/><path d="M8 21h8M12 17v4"/><circle cx="7" cy="11" r="0.4" fill="currentColor"/></svg>
              设备操作
              <svg class="rw-chip-caret" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
            <div
              v-if="deviceMenuVisible"
              ref="deviceMenuRef"
              class="rw-device-menu"
              role="listbox"
            >
              <div class="rw-device-search">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
                <input
                  v-model="deviceKeyword"
                  type="text"
                  placeholder="搜索设备名称或 ID…"
                  @keydown.stop
                />
              </div>
              <div v-if="isLoadingDevices" class="rw-device-empty">设备列表加载中…</div>
              <div v-else-if="!filteredDeviceOptions.length" class="rw-device-empty">暂无匹配的设备</div>
              <template v-else>
                <button
                  v-for="device in filteredDeviceOptions"
                  :key="device.id"
                  type="button"
                  class="rw-device-row"
                  :class="{ active: device.id === targetDeviceId }"
                  role="option"
                  :aria-selected="device.id === targetDeviceId"
                  @click="selectDevice(device)"
                >
                  <span class="rw-status-dot" :class="device.status === 'online' ? 'online' : 'offline'"></span>
                  <div class="rw-device-meta">
                    <div class="rw-device-title">
                      {{ device.name || device.id }}
                      <span class="rw-device-tag">{{ device.status === 'online' ? '在线' : '离线' }}</span>
                    </div>
                    <div class="rw-device-sub">ID: {{ device.id }}</div>
                  </div>
                </button>
              </template>
            </div>
          </div>
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
          <button
            class="rw-tool-chip"
            :class="{ active: isProjectExpertAgentSelected }"
            @click="toggleProjectExpertAgent"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5V6.75A2.75 2.75 0 0 1 6.75 4H20v13H6.75A2.75 2.75 0 0 0 4 19.5Z"/><path d="M8 8h8M8 12h6"/></svg>
            项目专家
          </button>
          <select
            v-if="isProjectRepoSelectVisible"
            v-model="selectedProjectRepoId"
            class="rw-project-select"
            :class="{ required: isProjectRepoRequiredMissing }"
            :disabled="projectRepoOptionsLoading"
            :title="projectRepoOptionsLoading
              ? '加载项目列表中…'
              : isProjectExpertAgentSelected
                ? '必选：项目专家需要一个已登记项目'
                : '可选：选择关联项目；留空则后端从日志包内 metadata.json 自动识别'"
          >
            <option :value="null">
              {{ projectRepoOptionsLoading
                ? '加载项目中…'
                : isProjectExpertAgentSelected ? '选择关联项目（必选）' : '关联项目（自动识别）' }}
            </option>
            <option
              v-for="repo in projectRepoOptions"
              :key="repo.id"
              :value="repo.id"
            >
              {{ repo.project_name }}（{{ repo.project_code }}）
            </option>
          </select>
          <button
            class="rw-send-btn"
            :disabled="activeTraceAgentSessionId ? cancelInFlight : sendDisabled"
            :title="activeTraceAgentSessionId ? (cancelInFlight ? '正在取消...' : '取消当前任务') : ''"
            @click="activeTraceAgentSessionId ? cancelActiveTraceAgent() : sendMessage()"
          >
            <svg v-if="isSending" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="spin"><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>
            <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12 19 5l-3 15-5-7-6-1Z"/></svg>
          </button>
        </div>
      </div>
      <div class="rw-composer-hint">RavenAI 可能会出错。涉及在线设备的下发操作均需你二次确认。</div>
    </div>

    <!-- Rename modal -->
    <div v-if="showRenameModal" class="rw-rename-backdrop" @click.self="showRenameModal = false">
      <div class="rw-modal rw-rename-modal">
        <div class="rw-modal-head">
          <div>
            <h3 class="rw-modal-title">重命名对话</h3>
            <p class="rw-modal-sub">为该对话设置一个新的名称</p>
          </div>
          <button class="rw-modal-close" @click="showRenameModal = false" aria-label="关闭">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12M18 6 6 18"/></svg>
          </button>
        </div>
        <div class="rw-rename-modal-body">
          <label class="rw-form-field">
            <span class="rw-form-label">对话名称</span>
            <input
              ref="renameModalInputRef"
              v-model="renameModalTitle"
              type="text"
              class="rw-input"
              placeholder="输入新名称…"
              maxlength="80"
              @keydown.enter.prevent="commitRenameFromModal"
              @keydown.esc.prevent="showRenameModal = false"
            />
          </label>
        </div>
        <div class="rw-modal-actions">
          <button
            type="button"
            class="rw-btn-primary"
            :disabled="renameModalInFlight || !renameModalTitle.trim()"
            @click="commitRenameFromModal"
          >{{ renameModalInFlight ? '保存中…' : '保存' }}</button>
          <button type="button" class="rw-btn-ghost" @click="showRenameModal = false">取消</button>
        </div>
      </div>
    </div>

    <!-- DeviceAgent HITL: tool permission modal -->
    <div v-if="currentPermission" class="rw-modal-backdrop rw-hitl-backdrop">
      <div class="rw-modal rw-hitl-modal">
        <div class="rw-modal-head">
          <div>
            <h3 class="rw-modal-title">设备工具调用待确认</h3>
            <p class="rw-modal-sub">
              <span class="rw-hitl-risk" :class="`risk-${currentPermission.risk}`">
                {{ currentPermission.risk === 'destructive' ? '破坏性' : currentPermission.risk === 'write' ? '写入' : '读取' }}
              </span>
              <span class="rw-hitl-tool mono">{{ currentPermission.tool_name }}</span>
            </p>
          </div>
        </div>
        <div class="rw-hitl-body">
          <div v-if="currentPermission.rationale" class="rw-hitl-rationale">
            {{ currentPermission.rationale }}
          </div>
          <label class="rw-form-field">
            <span class="rw-form-label">参数（可编辑后再批准）</span>
            <textarea
              v-model="currentPermission.editingArgs"
              class="rw-input rw-hitl-args mono"
              rows="8"
              spellcheck="false"
            ></textarea>
          </label>
          <div v-if="currentPermission.editingError" class="rw-hitl-error">
            {{ currentPermission.editingError }}
          </div>
          <p class="rw-hitl-warn">
            模型希望调用该工具，请确认参数无误后允许执行，或拒绝以取消本次调用。
          </p>
        </div>
        <div class="rw-modal-actions rw-hitl-actions">
          <button
            type="button"
            class="rw-btn-ghost"
            :disabled="permissionDecisionInFlight"
            @click="submitPermissionDecision('deny')"
          >拒绝</button>
          <button
            type="button"
            class="rw-btn-ghost"
            :disabled="permissionDecisionInFlight"
            @click="submitPermissionDecision('allow', { useEdited: true })"
          >按编辑后的参数允许</button>
          <button
            type="button"
            class="rw-btn-primary"
            :disabled="permissionDecisionInFlight"
            @click="submitPermissionDecision('allow')"
          >允许</button>
        </div>
      </div>
    </div>

    <!-- Mermaid 图表放大查看 -->
    <el-dialog
      v-model="mermaidDialogVisible"
      width="80%"
      top="6vh"
      append-to-body
      class="mermaid-zoom-dialog"
    >
      <template #header>
        <div class="mermaid-zoom-header">
          <span class="mermaid-zoom-title">图表查看</span>
          <div class="mermaid-zoom-toolbar">
            <button class="mz-btn" type="button" title="缩小" @click="zoomOutMermaid">−</button>
            <span class="mz-scale">{{ Math.round(mermaidZoomScale * 100) }}%</span>
            <button class="mz-btn" type="button" title="放大" @click="zoomInMermaid">＋</button>
            <button class="mz-btn" type="button" title="重置缩放" @click="resetMermaidZoom">重置</button>
            <span class="mz-divider"></span>
            <button class="mz-btn" type="button" title="复制图片" @click="copyMermaidImage">复制图片</button>
            <button class="mz-btn mz-btn-primary" type="button" title="下载图片" @click="downloadMermaidImage">下载图片</button>
          </div>
        </div>
      </template>
      <div
        ref="mermaidDialogContainerRef"
        class="mermaid-zoom-body"
        :class="{ 'is-pannable': mermaidZoomScale > 1, 'is-panning': mermaidIsPanning }"
        @wheel="onMermaidZoomWheel"
        @mousedown="onMermaidPanStart"
      ></div>
    </el-dialog>
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
.rw-composer.is-log-drag-over {
  border-color: var(--rw-ink);
  background: var(--rw-surface-strong);
  box-shadow: 0 0 0 3px rgba(23, 23, 23, .08), 0 8px 24px rgba(0,0,0,.08);
}
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
.rw-mini-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.rw-mini-btn:disabled:hover { background: none; color: var(--rw-body); }
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
.rw-file-chip--above {
  max-width: 100%; align-self: flex-start;
  border: 1px solid var(--rw-hairline-strong);
  background: var(--rw-canvas);
  padding: 0 8px 0 8px;
}

.rw-project-select {
  height: 28px; max-width: 220px; padding: 0 26px 0 10px;
  border: 1px solid var(--rw-hairline-strong);
  background: var(--rw-canvas); color: var(--rw-ink);
  border-radius: 999px; font-size: 12.5px; font-weight: 500;
  cursor: pointer; transition: border-color .15s;
  appearance: none; -webkit-appearance: none; -moz-appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%23555' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>");
  background-repeat: no-repeat;
  background-position: right 10px center;
}
.rw-project-select:hover { border-color: var(--rw-ink); }
.rw-project-select:disabled { opacity: .6; cursor: not-allowed; }
.rw-project-select.required { border-color: var(--rw-danger, #b91c1c); }

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

.rw-composer-alert {
  display: flex; align-items: flex-start; gap: 8px;
  max-width: 820px; margin: 0 auto 8px;
  padding: 9px 12px; border-radius: 8px;
  font-size: 12.5px; line-height: 1.55;
}
.rw-composer-alert.is-warn {
  background: #fffbeb; color: #92400e;
  border: 1px solid #fcd34d;
}
.rw-composer-alert.is-error {
  background: #fef2f2; color: #991b1b;
  border: 1px solid #fca5a5;
}
.rw-composer-alert.is-suggest {
  background: #eff6ff; color: #1e40af;
  border: 1px solid #93c5fd;
}
.rw-composer-alert.is-suggest .rw-alert-link {
  font-weight: 600; margin-left: 2px;
}
.rw-composer-alert.is-login {
  background: #f5f3ff; color: #4c1d95;
  border: 1px solid #c4b5fd;
}
.rw-composer-alert.is-login .rw-alert-link {
  font-weight: 600;
}
.rw-composer-alert code {
  font-family: var(--rw-mono); font-size: 11.5px;
  background: rgba(0,0,0,.06); border-radius: 3px; padding: 1px 4px;
}
.rw-alert-link {
  background: none; border: none; padding: 0; cursor: pointer;
  color: inherit; text-decoration: underline; font-size: inherit;
  font-family: inherit;
}

/* Device operation dropdown */
.rw-device-wrap { position: relative; display: inline-flex; }
.rw-chip-caret { margin-left: 1px; opacity: .65; }
.rw-device-menu {
  position: absolute; left: 0;
  bottom: calc(100% + 8px);
  width: 280px; max-height: 300px; overflow: auto;
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0,0,0,.12), 0 2px 6px rgba(0,0,0,.04);
  z-index: 30;
}
.rw-device-search {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 12px; border-bottom: 1px solid var(--rw-hairline);
  color: var(--rw-muted);
  position: sticky; top: 0; background: var(--rw-canvas); z-index: 1;
}
.rw-device-search input {
  flex: 1; min-width: 0; border: none; outline: none; background: transparent;
  font-size: 12.5px; color: var(--rw-ink); font-family: var(--rw-sans);
}
.rw-device-search input::placeholder { color: var(--rw-muted); }
.rw-device-empty { padding: 12px 14px; font-size: 12.5px; color: var(--rw-muted); }
.rw-device-row {
  display: flex; align-items: center; gap: 10px;
  width: 100%; padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid var(--rw-hairline-soft);
  background: none; border-left: none; border-right: none; border-top: none;
  cursor: pointer;
}
.rw-device-row:last-child { border-bottom: none; }
.rw-device-row:hover { background: var(--rw-hairline-soft); }
.rw-device-row.active { background: var(--rw-surface-strong); }
.rw-status-dot { width: 7px; height: 7px; border-radius: 999px; flex-shrink: 0; }
.rw-status-dot.online { background: var(--rw-success); }
.rw-status-dot.offline { background: var(--rw-muted-soft); }
.rw-device-meta { flex: 1; min-width: 0; }
.rw-device-title {
  font-size: 13.5px; font-weight: 600; color: var(--rw-ink);
  display: flex; align-items: center; gap: 6px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rw-device-tag {
  font-family: var(--rw-mono); font-size: 10.5px;
  text-transform: uppercase; color: var(--rw-muted);
  font-weight: 500;
}
.rw-device-sub { font-size: 12px; color: var(--rw-muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

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
.rw-device-menu::-webkit-scrollbar { width: 10px; height: 10px; }
.rw-scroll::-webkit-scrollbar-track,
.rw-device-menu::-webkit-scrollbar-track { background: transparent; }
.rw-scroll::-webkit-scrollbar-thumb,
.rw-device-menu::-webkit-scrollbar-thumb {
  background: #e6e6ea; border-radius: 999px; border: 2px solid var(--rw-canvas);
}
.rw-scroll::-webkit-scrollbar-thumb:hover,
.rw-device-menu::-webkit-scrollbar-thumb:hover { background: var(--rw-muted-soft); }

/* DeviceAgent HITL modal */
.rw-hitl-backdrop {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.42);
  display: flex; align-items: center; justify-content: center;
  z-index: 80;
}
.rw-hitl-modal {
  width: min(520px, 92vw);
  background: var(--rw-canvas, #fff);
  border-radius: 12px;
  padding: 20px 22px;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.18);
  display: flex; flex-direction: column; gap: 14px;
}
.rw-hitl-risk {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 600; margin-right: 8px;
}
.rw-hitl-risk.risk-read { background: #e0f2fe; color: #0369a1; }
.rw-hitl-risk.risk-write { background: #fef3c7; color: #92400e; }
.rw-hitl-risk.risk-destructive { background: #fee2e2; color: #b91c1c; }
.rw-hitl-tool { font-size: 13px; color: var(--rw-ink, #111827); }
.rw-hitl-body { display: flex; flex-direction: column; gap: 10px; }
.rw-hitl-rationale {
  font-size: 13px; color: var(--rw-muted, #6b7280);
  background: var(--rw-canvas-soft, #fafafa);
  padding: 8px 10px; border-radius: 8px;
}
.rw-hitl-args {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px; line-height: 1.5;
  min-height: 140px; resize: vertical;
}
.rw-hitl-error {
  color: #b91c1c; font-size: 12px;
  background: #fee2e2; padding: 6px 10px; border-radius: 6px;
}
.rw-hitl-warn { font-size: 12px; color: var(--rw-muted, #6b7280); margin: 0; }
.rw-hitl-actions { display: flex; gap: 8px; justify-content: flex-end; }

/* Rename modal */
.rw-rename-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.4);
  backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
  padding: 16px; z-index: 100;
}
.rw-modal {
  width: 100%; max-width: 380px;
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 14px;
  padding: 22px;
  box-shadow: 0 24px 64px rgba(0,0,0,.18);
}
.rw-modal-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.rw-modal-title { font-size: 16px; font-weight: 600; color: var(--rw-ink); margin: 0; }
.rw-modal-sub { font-size: 12px; color: var(--rw-muted); margin: 4px 0 0; }
.rw-modal-close { width: 28px; height: 28px; border-radius: 6px; display: grid; place-items: center; color: var(--rw-body); }
.rw-modal-close:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-rename-modal-body { margin-top: 16px; }
.rw-modal-actions { display: flex; gap: 10px; padding-top: 16px; }
.rw-form-field { display: flex; flex-direction: column; gap: 6px; }
.rw-form-label { font-size: 12px; color: var(--rw-body); font-weight: 500; }
.rw-input {
  width: 100%; height: 38px;
  border: 1px solid var(--rw-hairline-strong); border-radius: 8px;
  padding: 0 12px; font-size: 13.5px; outline: none;
  background: var(--rw-canvas); color: var(--rw-ink);
  font-family: inherit;
}
.rw-input:focus { border-color: var(--rw-ink); }
.rw-btn-primary {
  height: 36px; padding: 0 16px;
  background: var(--rw-primary); color: var(--rw-on-primary);
  border-radius: 8px; font-size: 13.5px; font-weight: 500;
  border: none; cursor: pointer;
  transition: background .15s, color .15s;
}
.rw-btn-primary:hover:not(:disabled) { background: var(--rw-primary-hover); }
.rw-btn-primary:active:not(:disabled) { background: var(--rw-primary-active); }
.rw-btn-primary:disabled { opacity: .6; cursor: default; }
.rw-btn-ghost {
  height: 36px; padding: 0 14px;
  background: var(--rw-canvas); color: var(--rw-ink);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 8px; font-size: 13.5px; font-weight: 500;
  cursor: pointer;
}
.rw-btn-ghost:hover { background: var(--rw-surface-strong); }

/* Responsive */
@media (max-width: 900px) {
  .rw-thread, .rw-composer { padding-left: 16px; padding-right: 16px; }
  .rw-composer-wrap { padding-left: 16px; padding-right: 16px; }
  .rw-topbar { padding: 0 16px; }
  .rw-cap-grid { grid-template-columns: 1fr; max-width: 480px; }
  .rw-welcome-title { font-size: 32px; letter-spacing: -0.8px; }
}
</style>
