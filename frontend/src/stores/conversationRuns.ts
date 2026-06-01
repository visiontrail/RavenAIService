import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { API_BASE_URL } from '@/api'
import { userApi } from '@/api/user'
import { projectExpertStream, resolveChatPermission } from '@/api/chat'
import type { AgentTraceEvent } from '@/types/agentTrace'
import type { ChatMessageRecord } from '@/types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ChatRole = 'user' | 'ai' | 'system'

export type ChatEntry = {
  id: string
  role: ChatRole
  content: string
  kind?: 'plan' | 'device_action' | 'answer' | 'user'
  traceEvents?: AgentTraceEvent[]
  traceRunning?: boolean
}

export type PendingPermission = {
  request_id: string
  tool_name: string
  risk: 'read' | 'write' | 'destructive'
  rationale?: string
  tool_input?: Record<string, unknown>
  session_id?: string
  run_id?: string
  editingArgs: string
  editingError?: string | null
}

export type AgentKind = 'device' | 'log_analysis' | 'project_expert' | 'package'

export type RunStatus = 'idle' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'stale'

export type ConversationState = {
  sessionId: string
  messages: ChatEntry[]
  loadingMessages: boolean
  isSending: boolean
  activeRunId: string | null
  runStatus: RunStatus
  runAgentKind: AgentKind | null
  /**
   * GeneralAgent 的结构化路由建议（device|log_analysis|package_search|
   * project_expert）。非空时表示用户最新请求更适合用对应专门 Agent，前端据此
   * 给出醒目提示与一键切换。每开始新一轮 run 重置为 null。
   */
  suggestedAgentType: string | null
  pendingPermissions: PendingPermission[]
  /** Map of `${runId}:${seq}` -> 1 so replayed frames are deduped. */
  seenSeq: Record<string, number>
  /** Stable assistant placeholder id for the current run: `run:<run_id>:assistant`. */
  currentAnswerId: string | null
  /** Abort-controller for the running SSE pump; aborting drops the reader, not the backend job. */
  subscription: AbortController | null
  /** Loaded once per session-id so loadSession + selectSessionToken don't both refetch. */
  loaded: boolean
}

export type StartDeviceRunPayload = {
  message: string
  history?: { role: string; content: string }[]
  target_device_id?: string | null
  target_device_name?: string | null
  remember?: boolean
}

export type StartLogAnalysisPayload = {
  message: string
  history?: { role: string; content: string }[]
  file?: File | null
  project_repo_id?: number | null
  remember?: boolean
}

export type StartProjectExpertPayload = {
  message: string
  history?: { role: string; content: string }[]
  project_repo_id: number
  remember?: boolean
}

const DEVICE_TRACE_TYPES = new Set([
  'run_start',
  'run_complete',
  'cancelled',
  'step_start',
  'step_delta',
  'step_end',
  'thinking_start',
  'thinking_delta',
  'thinking_end',
  'system_notice',
  'tool_permission_request',
  'tool_permission_resolved',
  'result_validation',
])

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

const getServiceUrl = (path: string) => {
  if (API_BASE_URL && /^https?:\/\//i.test(API_BASE_URL)) {
    return `${API_BASE_URL.replace(/\/$/, '')}${path}`
  }
  if (typeof window !== 'undefined') {
    return `http://${window.location.hostname}:8085${path}`
  }
  return path
}

const formatPlan = (steps: any[]) => {
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

const formatDeviceAction = (payload: any) => {
  const order = typeof payload?.step_index === 'number' ? payload.step_index + 1 : null
  const label = payload?.step_id || (order ? `步骤${order}` : '设备动作')
  const goal = payload?.step_goal ? `：${payload.step_goal}` : ''
  const lines: string[] = [`**设备动作 ${label}${goal}**`]
  const answerText =
    typeof payload?.answer === 'string' ? payload.answer : payload?.answer ? String(payload.answer) : ''
  if (answerText) lines.push(answerText)
  else if (payload?.raw) lines.push(String(payload.raw))
  else lines.push('无返回内容')
  if (payload?.topic_id) lines.push(`- 话题ID: ${payload.topic_id}`)
  return lines.join('\n')
}

export const useConversationRunsStore = defineStore('conversationRuns', () => {
  const bySession = reactive<Record<string, ConversationState>>({})
  const localRunningSet = ref<Set<string>>(new Set())

  const ensureState = (sessionId: string): ConversationState => {
    let state = bySession[sessionId]
    if (!state) {
      state = {
        sessionId,
        messages: [],
        loadingMessages: false,
        isSending: false,
        activeRunId: null,
        runStatus: 'idle',
        runAgentKind: null,
        suggestedAgentType: null,
        pendingPermissions: [],
        seenSeq: {},
        currentAnswerId: null,
        subscription: null,
        loaded: false,
      }
      bySession[sessionId] = state
    }
    return state
  }

  const localRunningSessionIds = computed(() => Array.from(localRunningSet.value))

  // ---- message helpers ----------------------------------------------------

  const findMessageIndex = (state: ConversationState, id: string) =>
    state.messages.findIndex((m) => m.id === id)

  const ensureAnswerMessage = (state: ConversationState, answerId: string): ChatEntry => {
    const idx = findMessageIndex(state, answerId)
    if (idx !== -1) return state.messages[idx]
    const placeholder: ChatEntry = { id: answerId, role: 'ai', content: '正在思考...', kind: 'answer' }
    state.messages.push(placeholder)
    return placeholder
  }

  const insertBeforeAnswer = (state: ConversationState, answerId: string, entry: ChatEntry) => {
    const idx = findMessageIndex(state, answerId)
    if (idx === -1) state.messages.push(entry)
    else state.messages.splice(idx, 0, entry)
  }

  // Specialist agents GeneralAgent may route the user to. Unknown values are
  // ignored so a future backend key can't crash the panel.
  const VALID_SUGGESTED_AGENTS = new Set([
    'device',
    'log_analysis',
    'package_search',
    'project_expert',
  ])

  const applySuggestedAgent = (state: ConversationState, raw: unknown) => {
    if (typeof raw === 'string' && VALID_SUGGESTED_AGENTS.has(raw)) {
      state.suggestedAgentType = raw
    }
  }

  // ---- event application --------------------------------------------------

  const applyEventToState = (state: ConversationState, payload: any) => {
    const type = payload?.event || payload?.type
    const eventRunId: string | undefined = payload?.run_id
    const eventSessionId: string | undefined = payload?.session_id

    // Reject events that explicitly target a different session — defense in
    // depth so stale subscriptions can't write into the wrong panel.
    if (eventSessionId && eventSessionId !== state.sessionId) return

    // Reject events from a different run unless we have no current run yet.
    if (eventRunId && state.activeRunId && eventRunId !== state.activeRunId) return

    // Latch run_id from the first event that carries it, e.g. backend's
    // ``{"event":"session","run_id":"..."}`` prologue or run_start.
    if (eventRunId && !state.activeRunId) {
      state.activeRunId = eventRunId
      state.runStatus = 'running'
      // New run starts: clear any prior agent-routing suggestion.
      state.suggestedAgentType = null
      if (!state.currentAnswerId) {
        state.currentAnswerId = `run:${eventRunId}:assistant`
      }
    }

    // Dedupe by `(run_id, seq)` so replay+follow doesn't double-render.
    const seq = typeof payload?.seq === 'number' ? payload.seq : null
    if (eventRunId && seq !== null) {
      const key = `${eventRunId}:${seq}`
      if (state.seenSeq[key]) return
      state.seenSeq[key] = 1
    }

    const answerId = state.currentAnswerId || `run:${eventRunId || 'pending'}:assistant`
    if (!state.currentAnswerId) state.currentAnswerId = answerId

    if (type === 'session') return

    if (type === 'plan') {
      insertBeforeAnswer(state, answerId, {
        id: generateUUID(),
        role: 'ai',
        content: formatPlan(payload?.plan),
        kind: 'plan',
      })
      return
    }
    if (type === 'device_action') {
      insertBeforeAnswer(state, answerId, {
        id: generateUUID(),
        role: 'ai',
        content: formatDeviceAction(payload),
        kind: 'device_action',
      })
      return
    }
    if (type === 'log_analysis_status') {
      const target = ensureAnswerMessage(state, answerId)
      const statusText = payload?.message || 'Log Analysis Agent 正在处理...'
      target.content = `**日志分析 Agent**\n\n${statusText}`
      return
    }
    if (type === 'log_analysis_context') return

    if (type === 'agent_trace') {
      const target = ensureAnswerMessage(state, answerId)
      if (!target.traceEvents) target.traceEvents = []
      target.traceRunning = true
      const { event: _evt, ...trace } = payload as Record<string, unknown>
      if (trace && typeof trace.seq === 'number' && typeof trace.type === 'string') {
        target.traceEvents.push(trace as unknown as AgentTraceEvent)
        if (trace.type === 'run_complete') {
          state.runStatus = 'succeeded'
          target.traceRunning = false
        } else if (trace.type === 'cancelled') {
          state.runStatus = 'cancelled'
          target.traceRunning = false
        } else if (trace.type === 'error') {
          state.runStatus = 'failed'
          target.traceRunning = false
        }
      }
      return
    }

    // Final-answer body increment. Emitted by all three agents when the
    // provider supports partial streaming. Appended live to the assistant
    // bubble; `run_complete.final_text` later does the authoritative
    // correction (see run_complete handling below). Dedup by `(run_id, seq)`
    // is already handled above. We deliberately do NOT push this into
    // `traceEvents` — it is answer prose, not a trace step.
    if (type === 'answer_delta') {
      const chunk = typeof payload?.text_chunk === 'string' ? payload.text_chunk : ''
      if (!chunk) return
      const target = ensureAnswerMessage(state, answerId)
      // First delta clears the "正在思考..." placeholder before appending.
      if (target.content === '正在思考...') {
        target.content = chunk.replace(/^\s+/, '')
      } else {
        target.content += chunk
      }
      target.kind = 'answer'
      target.traceRunning = true
      return
    }

    if (typeof type === 'string' && DEVICE_TRACE_TYPES.has(type)) {
      const target = ensureAnswerMessage(state, answerId)
      if (!target.traceEvents) target.traceEvents = []
      if (type === 'run_start') target.traceRunning = true
      const { event: _evt, ...trace } = payload as Record<string, unknown>
      if (trace && typeof trace.seq === 'number' && typeof trace.type === 'string') {
        target.traceEvents.push(trace as unknown as AgentTraceEvent)
      }
      if (type === 'run_complete') {
        // Authoritative correction: `final_text` is the de-sensitised /
        // trimmed full answer. Overwrite whatever the `answer_delta` stream
        // accumulated so the rendered bubble matches the persisted text. When
        // no `answer_delta` arrived this run (e.g. provider downgrade), this is
        // also the whole-segment render path — behaviour identical to before.
        const finalText = (payload as any)?.final_text
        if (typeof finalText === 'string' && finalText.trim()) target.content = finalText.trimStart()
        applySuggestedAgent(state, (payload as any)?.suggested_agent_type)
        state.runStatus = 'succeeded'
        target.traceRunning = false
      } else if (type === 'cancelled') {
        state.runStatus = 'cancelled'
        target.traceRunning = false
      }
      if (type === 'tool_permission_request') {
        const requestId = String(payload?.request_id || '')
        if (requestId) {
          const toolInput = payload?.tool_input
          state.pendingPermissions.push({
            request_id: requestId,
            tool_name: String(payload?.tool_name || ''),
            risk: (payload?.risk || 'write') as PendingPermission['risk'],
            rationale: payload?.rationale || undefined,
            tool_input: toolInput && typeof toolInput === 'object' ? toolInput : undefined,
            session_id: payload?.session_id || state.sessionId,
            run_id: payload?.run_id || state.activeRunId || undefined,
            editingArgs: toolInput ? JSON.stringify(toolInput, null, 2) : '{}',
            editingError: null,
          })
        }
      } else if (type === 'tool_permission_resolved') {
        const requestId = String(payload?.request_id || '')
        if (requestId) {
          state.pendingPermissions = state.pendingPermissions.filter(
            (p) => p.request_id !== requestId,
          )
        }
      }
      return
    }

    const target = ensureAnswerMessage(state, answerId)
    if (type === 'chunk' && typeof payload?.content === 'string') {
      const chunk = payload.content
      if (target.content === '正在思考...') {
        const trimmedChunk = chunk.trimStart()
        if (trimmedChunk) target.content = trimmedChunk
      } else {
        target.content += chunk
      }
    } else if (type === 'done') {
      if (typeof payload?.answer === 'string' && payload.answer) target.content = payload.answer.trimStart()
      else if (!target.content || target.content === '正在思考...') target.content = '（无回复内容）'
      applySuggestedAgent(state, payload?.suggested_agent_type)
      const resultStatus = String(payload?.result?.status || '').toLowerCase()
      if (resultStatus === 'cancelled') state.runStatus = 'cancelled'
      else if (resultStatus === 'stale') state.runStatus = 'stale'
      else if (resultStatus === 'failed' || resultStatus === 'error') state.runStatus = 'failed'
      else if (state.runStatus !== 'cancelled' && state.runStatus !== 'failed') state.runStatus = 'succeeded'
      target.traceRunning = false
    } else if (type === 'error') {
      // The backend already returns a user-facing, friendly message for known
      // cases (e.g. missing metadata.json). Render it verbatim; only fall back
      // to a generic friendly line when no message was provided.
      const backendMsg = typeof payload?.message === 'string' ? payload.message.trim() : ''
      target.content = backendMsg || '抱歉，处理这条请求时遇到了问题，请稍后重试。'
      state.runStatus = 'failed'
      target.traceRunning = false
    }
  }

  const markTerminal = (state: ConversationState, status: RunStatus) => {
    state.isSending = false
    state.runStatus = status
    localRunningSet.value.delete(state.sessionId)
    state.activeRunId = null
    state.currentAnswerId = null
    state.runAgentKind = null
    state.subscription = null
    // Keep seenSeq so a future reconnect to the same run still dedupes; the
    // map is small and cleared on session reload.
  }

  const terminalStatus = (state: ConversationState): RunStatus => {
    if (state.runStatus === 'cancelled' || state.runStatus === 'failed' || state.runStatus === 'stale') {
      return state.runStatus
    }
    return 'succeeded'
  }

  // ---- snapshot merge -----------------------------------------------------

  const mergeSnapshot = (state: ConversationState, snapshot: any) => {
    if (!snapshot || typeof snapshot !== 'object') return
    const runId = snapshot.run_id
    if (!runId) return
    state.activeRunId = runId
    state.runStatus = (snapshot.status || 'running') as RunStatus
    state.runAgentKind = (snapshot.agent_kind || null) as AgentKind | null
    applySuggestedAgent(state, snapshot.suggested_agent_type)
    state.currentAnswerId = `run:${runId}:assistant`
    if (state.runStatus === 'running') {
      state.isSending = true
      localRunningSet.value.add(state.sessionId)
    }

    // Pending permissions from snapshot.
    const pending = Array.isArray(snapshot.pending_permissions) ? snapshot.pending_permissions : []
    for (const p of pending) {
      const requestId = String(p?.request_id || '')
      if (!requestId) continue
      if (state.pendingPermissions.some((x) => x.request_id === requestId)) continue
      const toolInput = p?.tool_input
      state.pendingPermissions.push({
        request_id: requestId,
        tool_name: String(p?.tool_name || ''),
        risk: (p?.risk || 'write') as PendingPermission['risk'],
        rationale: p?.rationale || undefined,
        tool_input: toolInput && typeof toolInput === 'object' ? toolInput : undefined,
        session_id: p?.session_id || state.sessionId,
        run_id: p?.run_id || runId,
        editingArgs: toolInput ? JSON.stringify(toolInput, null, 2) : '{}',
        editingError: null,
      })
    }

    // Restore the user message that initiated this run. The backend snapshot
    // always carries ``user_message``, but the DB-side ``chat_messages`` row
    // may not exist yet (log-analysis writes user+assistant together at run
    // terminal via ``_persist_exchange``). Without this restore, switching
    // away from an in-flight session and back would show only the assistant
    // bubble — the user's own prompt would silently disappear.
    const snapshotUserMessage =
      typeof snapshot.user_message === 'string' ? snapshot.user_message : ''
    const trimmedUserMessage = snapshotUserMessage.trim()
    if (trimmedUserMessage) {
      const userMsgId = `run:${runId}:user`
      const alreadyPresent = state.messages.some(
        (m) =>
          m.role === 'user' &&
          (m.id === userMsgId ||
            (m.content || '').trim().startsWith(trimmedUserMessage)),
      )
      if (!alreadyPresent) {
        state.messages.push({
          id: userMsgId,
          role: 'user',
          content: snapshotUserMessage,
          kind: 'user',
        })
      }
    }

    // Replay trace events into the assistant placeholder. Snapshot already
    // deduplicates server-side, so we can clear and rebuild.
    const trace: any[] = Array.isArray(snapshot.trace_events) ? snapshot.trace_events : []
    const target = ensureAnswerMessage(state, state.currentAnswerId)
    target.traceEvents = []
    target.traceRunning = state.runStatus === 'running'
    for (const ev of trace) {
      if (ev && typeof ev.seq === 'number' && typeof ev.type === 'string') {
        target.traceEvents.push(ev as AgentTraceEvent)
        const key = `${runId}:${ev.seq}`
        state.seenSeq[key] = 1
      }
    }
    // If the snapshot has an answer-so-far, render it.
    const answerSoFar = snapshot.answer_so_far
    if (typeof answerSoFar === 'string' && answerSoFar.trim()) {
      target.content = answerSoFar.trimStart()
    }
  }

  // ---- SSE pump -----------------------------------------------------------

  const pumpSSE = async (
    state: ConversationState,
    response: Response,
    abortSignal: AbortSignal,
  ): Promise<{ terminal: boolean }> => {
    if (!response.body) throw new Error('响应体为空，无法流式读取')
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
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
          applyEventToState(state, payload)
          const type = payload?.event || payload?.type
          if (type === 'done' || type === 'error' || type === 'run_complete' || type === 'cancelled') {
            terminal = true
          }
        } catch (err) {
          console.error('解析流式数据失败', err, jsonStr)
        }
      }
      buffer = remaining
    }

    try {
      while (true) {
        if (abortSignal.aborted) break
        const { value, done } = await reader.read()
        if (value) processChunk(decoder.decode(value, { stream: !done }))
        if (done) break
      }
      if (buffer.trim()) processChunk('\n\n')
    } catch (err: any) {
      if (err?.name === 'AbortError') return { terminal: false }
      throw err
    }
    return { terminal }
  }

  // ---- public API ---------------------------------------------------------

  const buildAuthHeaders = (authToken?: string | null): Record<string, string> => {
    const headers: Record<string, string> = {}
    if (authToken) headers.Authorization = `Bearer ${authToken}`
    return headers
  }

  /** Drop the in-memory state for a session (e.g. after deletion). */
  const clearSession = (sessionId: string) => {
    const state = bySession[sessionId]
    if (state?.subscription) {
      try {
        state.subscription.abort()
      } catch {
        // ignore
      }
    }
    delete bySession[sessionId]
    localRunningSet.value.delete(sessionId)
  }

  /** Abort the SSE reader for this session without cancelling the backend run. */
  const abortSubscription = (sessionId: string) => {
    const state = bySession[sessionId]
    if (state?.subscription) {
      try {
        state.subscription.abort()
      } catch {
        // ignore
      }
      state.subscription = null
    }
  }

  /**
   * Load DB messages + query active-run snapshot. If a run is in flight,
   * merge a virtual assistant message and subscribe to the run stream.
   *
   * Caller should pass `force=true` after sending a new message to refresh.
   */
  const loadSession = async (
    sessionId: string,
    opts: { authToken?: string | null; isLoggedIn?: boolean; force?: boolean } = {},
  ) => {
    const state = ensureState(sessionId)
    if (state.loaded && !opts.force) return state

    state.loadingMessages = true
    let subscribeRunId: string | null = null
    try {
      if (opts.isLoggedIn) {
        try {
          const resp = await userApi.fetchMessages(sessionId)
          if (resp?.success && Array.isArray(resp.data)) {
            state.messages = (resp.data as ChatMessageRecord[]).map((item) => ({
              id: item.id || generateUUID(),
              role: item.role as ChatRole,
              content: item.content || '',
              kind: item.role === 'user' ? 'user' : 'answer',
              traceEvents: Array.isArray(item.trace_events)
                ? (item.trace_events as AgentTraceEvent[])
                : undefined,
              traceRunning: item.run_status === 'running',
            }))
          }
        } catch (err) {
          console.warn('加载会话消息失败', err)
        }
      }

      // Query active-run regardless of auth state — backend handles owner_scope.
      try {
        const resp = await fetch(
          getServiceUrl(`/api/v1/ai-chat/chat/sessions/${encodeURIComponent(sessionId)}/active-run`),
          { headers: buildAuthHeaders(opts.authToken), credentials: 'include' },
        )
        if (resp.ok) {
          const snapshot = await resp.json()
          mergeSnapshot(state, snapshot)
          if (state.activeRunId && state.runStatus === 'running') {
            subscribeRunId = state.activeRunId
          } else if (state.activeRunId) {
            markTerminal(state, terminalStatus(state))
          }
        } else if (resp.status === 404 && (state.activeRunId || state.isSending)) {
          markTerminal(state, terminalStatus(state))
        }
      } catch (err) {
        // 404 = no active run; anything else is just a warning.
        if ((err as any)?.name !== 'AbortError') {
          console.debug('active-run query skipped', err)
        }
      }

      state.loaded = true
    } finally {
      state.loadingMessages = false
    }
    if (subscribeRunId) {
      void subscribeRun(sessionId, subscribeRunId, { authToken: opts.authToken })
    }
    return state
  }

  const subscribeRun = async (
    sessionId: string,
    runId: string,
    opts: { authToken?: string | null } = {},
  ) => {
    const state = ensureState(sessionId)
    // Replace any existing subscription on this session.
    if (state.subscription) {
      try { state.subscription.abort() } catch { /* ignore */ }
    }
    const ac = new AbortController()
    state.subscription = ac
    state.isSending = true
    localRunningSet.value.add(sessionId)

    try {
      const resp = await fetch(
        getServiceUrl(`/api/v1/ai-chat/chat/runs/${encodeURIComponent(runId)}/stream`),
        {
          headers: buildAuthHeaders(opts.authToken),
          credentials: 'include',
          signal: ac.signal,
        },
      )
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const { terminal } = await pumpSSE(state, resp, ac.signal)
      if (terminal) markTerminal(state, state.runStatus === 'idle' ? 'succeeded' : state.runStatus)
    } catch (err: any) {
      if (err?.name === 'AbortError') return
      console.warn('订阅 run 失败', err)
      markTerminal(state, 'failed')
    } finally {
      if (state.subscription === ac) state.subscription = null
    }
  }

  /**
   * Create-or-subscribe via POST /chat/stream. The endpoint resolves to one
   * of: 200 SSE (new run created, or resuming), 409 (active run exists -
   * caller should switch to subscribeRun), 4xx/5xx on error.
   */
  const startDeviceRun = async (
    sessionId: string,
    payload: StartDeviceRunPayload,
    opts: { authToken?: string | null } = {},
  ) => {
    const state = ensureState(sessionId)
    if (state.isSending) return

    // Optimistic local append: user message + assistant placeholder. Stable
    // assistant id keeps the placeholder in place even after run_id arrives,
    // since the backend's session+run_id prologue will overwrite ours.
    const userDisplay = payload.message
    const userMessageId = generateUUID()
    state.messages.push({
      id: userMessageId,
      role: 'user',
      content: userDisplay,
      kind: 'user',
    })
    const pendingAnswerId = `run:pending:${generateUUID()}:assistant`
    state.currentAnswerId = pendingAnswerId
    state.messages.push({
      id: pendingAnswerId,
      role: 'ai',
      content: '正在思考...',
      kind: 'answer',
      traceEvents: [],
      traceRunning: true,
    })
    state.isSending = true
    state.runStatus = 'running'
    state.runAgentKind = 'device'
    localRunningSet.value.add(sessionId)

    const ac = new AbortController()
    state.subscription = ac

    const body = {
      message: payload.message,
      session_id: sessionId,
      history: payload.history || [],
      remember: payload.remember ?? true,
      target_device_id: payload.target_device_id || undefined,
      target_device_name: payload.target_device_name || undefined,
    }
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...buildAuthHeaders(opts.authToken),
    }

    try {
      const resp = await fetch(getServiceUrl('/api/v1/ai-chat/chat/stream'), {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        credentials: 'include',
        signal: ac.signal,
      })

      if (resp.status === 409) {
        // Active run already exists — switch to subscribe.
        let activeRunId: string | null = null
        try {
          const errBody = await resp.json()
          activeRunId = errBody?.active_run_id || errBody?.detail?.active_run_id || null
        } catch { /* ignore */ }
        // Roll back the optimistic append since backend is rejecting create.
        state.messages = state.messages.filter((m) => m.id !== pendingAnswerId && m.id !== userMessageId)
        state.isSending = false
        localRunningSet.value.delete(sessionId)
        if (activeRunId) {
          await subscribeRun(sessionId, activeRunId, opts)
        }
        return
      }

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      // Remap our pending placeholder to the run_id-keyed id once the backend
      // ``session`` frame arrives. We do this inline in pumpSSE via
      // applyEventToState (currentAnswerId starts as pendingAnswerId; the
      // first ``session`` frame with run_id sets activeRunId and we then
      // re-key the placeholder).
      const reKeyPump = async () => {
        if (!resp.body) throw new Error('响应体为空，无法流式读取')
        const reader = resp.body.getReader()
        const decoder = new TextDecoder('utf-8')
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
              const evPayload = JSON.parse(jsonStr)
              // Re-key the pending assistant placeholder to use run_id once known.
              const newRunId = evPayload?.run_id
              if (
                newRunId &&
                state.currentAnswerId === pendingAnswerId
              ) {
                const stableId = `run:${newRunId}:assistant`
                const target = state.messages.find((m) => m.id === pendingAnswerId)
                if (target) target.id = stableId
                state.currentAnswerId = stableId
              }
              applyEventToState(state, evPayload)
              const t = evPayload?.event || evPayload?.type
              if (t === 'done' || t === 'error' || t === 'run_complete' || t === 'cancelled') {
                terminal = true
              }
            } catch (err) {
              console.error('解析流式数据失败', err, jsonStr)
            }
          }
          buffer = remaining
        }
        try {
          while (true) {
            if (ac.signal.aborted) break
            const { value, done } = await reader.read()
            if (value) processChunk(decoder.decode(value, { stream: !done }))
            if (done) break
          }
          if (buffer.trim()) processChunk('\n\n')
        } catch (err: any) {
          if (err?.name === 'AbortError') return
          throw err
        }
        return terminal
      }

      const terminal = await reKeyPump()
      if (terminal) markTerminal(state, terminalStatus(state))
    } catch (err: any) {
      if (err?.name === 'AbortError') return
      console.error('启动 DeviceAgent run 失败', err)
      const target = state.messages.find((m) => m.id === state.currentAnswerId)
      if (target) {
        target.content = `调用后端失败：${err?.message || String(err)}`
        target.traceRunning = false
      }
      markTerminal(state, 'failed')
    } finally {
      if (state.subscription === ac) state.subscription = null
    }
  }

  /**
   * Start a Log Analysis Agent run via the existing multipart endpoint.
   * The backend projects status into chat_agent_runs so the unified
   * active-run/snapshot flow works for resume.
   */
  const startLogAnalysisRun = async (
    sessionId: string,
    payload: StartLogAnalysisPayload,
    opts: { authToken?: string | null } = {},
  ) => {
    const state = ensureState(sessionId)
    if (state.isSending) return

    const userDisplay = payload.file
      ? `${payload.message || '请分析这个日志包。'}\n\n附件：${payload.file.name}`
      : payload.message
    state.messages.push({
      id: generateUUID(),
      role: 'user',
      content: userDisplay,
      kind: 'user',
    })
    const pendingAnswerId = `run:pending:${generateUUID()}:assistant`
    state.currentAnswerId = pendingAnswerId
    state.messages.push({
      id: pendingAnswerId,
      role: 'ai',
      content: '正在思考...',
      kind: 'answer',
      traceEvents: [],
      traceRunning: true,
    })
    state.isSending = true
    state.runStatus = 'running'
    state.runAgentKind = 'log_analysis'
    localRunningSet.value.add(sessionId)

    const ac = new AbortController()
    state.subscription = ac

    const formData = new FormData()
    formData.append('message', payload.message || '')
    formData.append('session_id', sessionId)
    formData.append('remember', String(payload.remember ?? true))
    if (payload.history) formData.append('history', JSON.stringify(payload.history))
    if (payload.file) formData.append('file', payload.file)
    if (payload.project_repo_id != null) {
      formData.append('project_repo_id', String(payload.project_repo_id))
    }

    try {
      const resp = await fetch(getServiceUrl('/api/v1/ai-chat/log-analysis/stream'), {
        method: 'POST',
        headers: buildAuthHeaders(opts.authToken),
        body: formData,
        credentials: 'include',
        signal: ac.signal,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      // Re-key inline as we discover run_id. The log-analysis stream may not
      // emit a session prologue frame; we accept either run_id or session_id
      // attribution.
      if (!resp.body) throw new Error('响应体为空，无法流式读取')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
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
            const evPayload = JSON.parse(jsonStr)
            const newRunId = evPayload?.run_id
            if (newRunId && state.currentAnswerId === pendingAnswerId) {
              const stableId = `run:${newRunId}:assistant`
              const target = state.messages.find((m) => m.id === pendingAnswerId)
              if (target) target.id = stableId
              state.currentAnswerId = stableId
            }
            applyEventToState(state, evPayload)
            const t = evPayload?.event || evPayload?.type
            if (t === 'done' || t === 'error') terminal = true
          } catch (err) {
            console.error('解析流式数据失败', err, jsonStr)
          }
        }
        buffer = remaining
      }
      try {
        while (true) {
          if (ac.signal.aborted) break
          const { value, done } = await reader.read()
          if (value) processChunk(decoder.decode(value, { stream: !done }))
          if (done) break
        }
        if (buffer.trim()) processChunk('\n\n')
      } catch (err: any) {
        if (err?.name !== 'AbortError') throw err
      }

      if (terminal) {
        markTerminal(state, terminalStatus(state))
      } else {
        // SSE closed early without terminal — leave state.isSending true so the
        // sidebar spinner keeps spinning; user can re-select the session to
        // resume via active-run snapshot.
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') return
      console.error('启动日志分析 run 失败', err)
      const target = state.messages.find((m) => m.id === state.currentAnswerId)
      if (target) {
        // Transport-level failure (network / non-2xx). Keep it friendly and
        // actionable rather than surfacing the raw error string.
        target.content = '抱歉，日志分析服务暂时无法连接，请检查网络后稍后重试。'
        target.traceRunning = false
      }
      markTerminal(state, 'failed')
    } finally {
      if (state.subscription === ac) state.subscription = null
    }
  }

  /**
   * Start a Project Expert Agent run. It uses the same trace/SSE renderer as
   * log-analysis, but requires an explicit project repo and never sends files.
   */
  const startProjectExpertRun = async (
    sessionId: string,
    payload: StartProjectExpertPayload,
    opts: { authToken?: string | null } = {},
  ) => {
    const state = ensureState(sessionId)
    if (state.isSending) return

    state.messages.push({
      id: generateUUID(),
      role: 'user',
      content: payload.message,
      kind: 'user',
    })
    const pendingAnswerId = `run:pending:${generateUUID()}:assistant`
    state.currentAnswerId = pendingAnswerId
    state.messages.push({
      id: pendingAnswerId,
      role: 'ai',
      content: '正在思考...',
      kind: 'answer',
      traceEvents: [],
      traceRunning: true,
    })
    state.isSending = true
    state.runStatus = 'running'
    state.runAgentKind = 'project_expert'
    localRunningSet.value.add(sessionId)

    const ac = new AbortController()
    state.subscription = ac

    try {
      const resp = await projectExpertStream({
        message: payload.message || '',
        sessionId,
        history: payload.history,
        remember: payload.remember ?? true,
        projectRepoId: payload.project_repo_id,
        authToken: opts.authToken || null,
        signal: ac.signal,
      })
      if (!resp.ok) {
        let detail = ''
        try {
          const body = await resp.json()
          detail = body?.detail?.message || body?.detail?.reason || body?.message || ''
        } catch {
          // ignore non-JSON error bodies
        }
        throw new Error(detail || `HTTP ${resp.status}`)
      }

      if (!resp.body) throw new Error('响应体为空，无法流式读取')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
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
            const evPayload = JSON.parse(jsonStr)
            const newRunId = evPayload?.run_id
            if (newRunId && state.currentAnswerId === pendingAnswerId) {
              const stableId = `run:${newRunId}:assistant`
              const target = state.messages.find((m) => m.id === pendingAnswerId)
              if (target) target.id = stableId
              state.currentAnswerId = stableId
            }
            applyEventToState(state, evPayload)
            const t = evPayload?.event || evPayload?.type
            if (t === 'done' || t === 'error' || t === 'run_complete' || t === 'cancelled') {
              terminal = true
            }
          } catch (err) {
            console.error('解析项目专家流式数据失败', err, jsonStr)
          }
        }
        buffer = remaining
      }
      try {
        while (true) {
          if (ac.signal.aborted) break
          const { value, done } = await reader.read()
          if (value) processChunk(decoder.decode(value, { stream: !done }))
          if (done) break
        }
        if (buffer.trim()) processChunk('\n\n')
      } catch (err: any) {
        if (err?.name !== 'AbortError') throw err
      }

      if (terminal) {
        markTerminal(state, terminalStatus(state))
      }
    } catch (err: any) {
      if (err?.name === 'AbortError') return
      console.error('启动项目专家 run 失败', err)
      const target = state.messages.find((m) => m.id === state.currentAnswerId)
      if (target) {
        target.content = `项目专家调用失败：${err?.message || String(err)}`
        target.traceRunning = false
      }
      markTerminal(state, 'failed')
    } finally {
      if (state.subscription === ac) state.subscription = null
    }
  }

  /** Cancel the currently-running run on this session via the unified endpoint. */
  const cancelActiveRun = async (
    sessionId: string,
    opts: { authToken?: string | null } = {},
  ) => {
    const state = ensureState(sessionId)
    const runId = state.activeRunId
    if (!runId) return
    try {
      await fetch(getServiceUrl(`/api/v1/ai-chat/chat/runs/${encodeURIComponent(runId)}/cancel`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...buildAuthHeaders(opts.authToken) },
        credentials: 'include',
      })
    } catch (err) {
      console.warn('取消 run 请求失败', err)
    }
  }

  /** Submit a HITL permission decision. Removes the entry locally on success. */
  const submitPermission = async (
    sessionId: string,
    requestId: string,
    decision: 'allow' | 'deny',
    options: { updatedArgs?: Record<string, unknown> | null; authToken?: string | null } = {},
  ) => {
    const state = ensureState(sessionId)
    const head = state.pendingPermissions.find((p) => p.request_id === requestId)
    if (!head) return
    try {
      await resolveChatPermission(
        requestId,
        {
          decision,
          updated_args: options.updatedArgs ?? null,
          session_id: head.session_id || sessionId,
          // Add run_id when known. Backend prefers it over session_id.
          ...(head.run_id ? { run_id: head.run_id } : {}),
        },
        options.authToken || null,
      )
      state.pendingPermissions = state.pendingPermissions.filter((p) => p.request_id !== requestId)
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 404) {
        state.pendingPermissions = state.pendingPermissions.filter((p) => p.request_id !== requestId)
        return
      }
      if (head) {
        head.editingError = `提交失败：${err?.response?.data?.detail || err?.message || String(err)}`
      }
      throw err
    }
  }

  const reset = () => {
    for (const id of Object.keys(bySession)) clearSession(id)
  }

  return {
    bySession,
    localRunningSessionIds,
    ensureState,
    loadSession,
    subscribeRun,
    startDeviceRun,
    startLogAnalysisRun,
    startProjectExpertRun,
    cancelActiveRun,
    submitPermission,
    abortSubscription,
    clearSession,
    reset,
    // exposed for unit testing & integration glue
    applyEventToState,
    mergeSnapshot,
    markTerminal,
  }
})
