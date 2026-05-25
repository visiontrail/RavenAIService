import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useConversationRunsStore } from '@/stores/conversationRuns'
import { userApi } from '@/api/user'
import { resolveChatPermission } from '@/api/chat'
import type { ChatEntry, PendingPermission } from '@/stores/conversationRuns'
import type { AgentTraceEvent } from '@/types/agentTrace'

vi.mock('@/api/chat', () => ({
  resolveChatPermission: vi.fn(),
}))

const flushPromises = () => new Promise((resolve) => setTimeout(resolve, 0))

const sseResponse = (events: Record<string, unknown>[]) => {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }
      controller.close()
    },
  })
  return new Response(body, { status: 200 })
}

const openSseResponse = (events: Record<string, unknown>[]) => {
  const encoder = new TextEncoder()
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c
      for (const event of events) {
        c.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }
    },
  })
  return {
    response: new Response(body, { status: 200 }),
    close: () => controller?.close(),
  }
}

const traceEvent = (
  runId: string,
  sessionId: string,
  seq: number,
  type: AgentTraceEvent['type'],
): Record<string, unknown> => ({
  event: type,
  type,
  task_id: runId,
  run_id: runId,
  session_id: sessionId,
  seq,
  timestamp: seq,
})

describe('conversationRuns store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('routes streamed events by session/run and keeps another selected session clean', () => {
    const store = useConversationRunsStore()
    const sessionA = store.ensureState('session-a')
    const sessionB = store.ensureState('session-b')

    store.mergeSnapshot(sessionA, {
      run_id: 'run-a',
      session_id: 'session-a',
      status: 'running',
      agent_kind: 'device',
      answer_so_far: 'A 正在处理',
      trace_events: [traceEvent('run-a', 'session-a', 1, 'run_start')],
    })
    sessionB.messages.push({ id: 'b-user', role: 'user', content: 'B message', kind: 'user' })

    store.applyEventToState(sessionA, traceEvent('run-a', 'session-a', 2, 'step_delta'))
    store.applyEventToState(sessionB, traceEvent('run-a', 'session-a', 3, 'step_delta'))
    store.applyEventToState(sessionB, traceEvent('run-b', 'session-b', 1, 'step_delta'))

    const aAnswer = sessionA.messages.find((m: ChatEntry) => m.id === 'run:run-a:assistant')
    const bAnswer = sessionB.messages.find((m: ChatEntry) => m.id === 'run:run-b:assistant')

    expect(aAnswer?.traceEvents?.map((e: AgentTraceEvent) => e.seq)).toEqual([1, 2])
    expect(sessionB.messages.some((m: ChatEntry) => m.id === 'run:run-a:assistant')).toBe(false)
    expect(bAnswer?.traceEvents?.map((e: AgentTraceEvent) => e.seq)).toEqual([1])
    expect(sessionA.seenSeq['run-a:1']).toBe(1)
    expect(sessionB.seenSeq['run-b:1']).toBe(1)
  })

  it('allows a device run in session B while session A log analysis is still running', async () => {
    const store = useConversationRunsStore()
    const sessionA = store.ensureState('session-a')

    store.mergeSnapshot(sessionA, {
      run_id: 'run-a',
      session_id: 'session-a',
      status: 'running',
      agent_kind: 'log_analysis',
      trace_events: [traceEvent('run-a', 'session-a', 1, 'run_start')],
    })

    const fetchMock = vi.fn().mockResolvedValue(sseResponse([
      { event: 'session', session_id: 'session-b', run_id: 'run-b' },
      traceEvent('run-b', 'session-b', 1, 'run_start'),
      { ...traceEvent('run-b', 'session-b', 2, 'run_complete'), final_text: 'B final' },
      { event: 'done', session_id: 'session-b', run_id: 'run-b', answer: 'B final' },
    ]))
    vi.stubGlobal('fetch', fetchMock)

    await store.startDeviceRun('session-b', { message: 'hello from B' })

    const sessionB = store.ensureState('session-b')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/ai-chat/chat/stream'),
      expect.objectContaining({ method: 'POST' }),
    )
    expect(sessionA.isSending).toBe(true)
    expect(sessionA.activeRunId).toBe('run-a')
    expect(sessionB.isSending).toBe(false)
    expect(sessionB.runStatus).toBe('succeeded')
    expect(sessionB.messages.map((m: ChatEntry) => m.content)).toContain('hello from B')
    expect(sessionB.messages.map((m: ChatEntry) => m.content)).toContain('B final')
    expect(store.localRunningSessionIds).toEqual(['session-a'])
  })

  it('restores a log-analysis run snapshot and cancels only that run id', async () => {
    const store = useConversationRunsStore()
    const sessionA = store.ensureState('session-a')
    const traceEvents = Array.from({ length: 10 }, (_, idx) =>
      traceEvent('log-run-a', 'session-a', idx + 1, idx === 0 ? 'run_start' : 'step_delta'),
    )

    store.mergeSnapshot(sessionA, {
      run_id: 'log-run-a',
      session_id: 'session-a',
      status: 'running',
      agent_kind: 'log_analysis',
      answer_so_far: '日志分析中',
      trace_events: traceEvents,
      pending_permissions: [
        {
          request_id: 'req-a',
          tool_name: 'Read',
          risk: 'read',
          tool_input: { path: 'a.log' },
          run_id: 'log-run-a',
          session_id: 'session-a',
        },
      ],
    })

    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await store.cancelActiveRun('session-a')

    const answer = sessionA.messages.find((m: ChatEntry) => m.id === 'run:log-run-a:assistant')
    expect(sessionA.runAgentKind).toBe('log_analysis')
    expect(sessionA.isSending).toBe(true)
    expect(answer?.traceEvents).toHaveLength(10)
    expect(sessionA.pendingPermissions[0]).toMatchObject({
      request_id: 'req-a',
      run_id: 'log-run-a',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/ai-chat/chat/runs/log-run-a/cancel'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('loads DB history, restores active-run trace, and finishes from the resumed stream', async () => {
    const store = useConversationRunsStore()
    const traceEvents = Array.from({ length: 10 }, (_, idx) =>
      traceEvent('run-a', 'session-a', idx + 1, idx === 0 ? 'run_start' : 'step_delta'),
    )

    vi.spyOn(userApi, 'fetchMessages').mockResolvedValue({
      success: true,
      data: [
        {
          id: 'msg-user-a',
          session_id: 'session-a',
          role: 'user',
          content: '请检查设备状态',
          created_at: '2026-05-25T10:00:00.000Z',
          updated_at: '2026-05-25T10:00:00.000Z',
        },
      ],
    } as any)

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        run_id: 'run-a',
        session_id: 'session-a',
        status: 'running',
        agent_kind: 'device',
        answer_so_far: '已读取设备信息',
        trace_events: traceEvents,
        pending_permissions: [
          {
            request_id: 'req-a',
            tool_name: 'Write',
            risk: 'write',
            tool_input: { command: 'reset' },
            run_id: 'run-a',
            session_id: 'session-a',
          },
        ],
      }), { status: 200 }))
      .mockResolvedValueOnce(sseResponse([
        traceEvent('run-a', 'session-a', 11, 'step_delta'),
        { ...traceEvent('run-a', 'session-a', 12, 'run_complete'), final_text: '设备状态正常' },
        { event: 'done', session_id: 'session-a', run_id: 'run-a', answer: '设备状态正常' },
      ]))
    vi.stubGlobal('fetch', fetchMock)

    const state = await store.loadSession('session-a', { isLoggedIn: true, authToken: 'token', force: true })
    await flushPromises()
    const answer = state.messages.find((m: ChatEntry) => m.id === 'run:run-a:assistant')

    expect(userApi.fetchMessages).toHaveBeenCalledWith('session-a')
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('/api/v1/ai-chat/chat/sessions/session-a/active-run'),
      expect.objectContaining({ credentials: 'include' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('/api/v1/ai-chat/chat/runs/run-a/stream'),
      expect.objectContaining({ credentials: 'include' }),
    )
    expect(state.messages[0]).toMatchObject({ id: 'msg-user-a', role: 'user' })
    expect(answer?.content).toBe('设备状态正常')
    expect(answer?.traceEvents?.map((e: AgentTraceEvent) => e.seq)).toEqual([...Array(12)].map((_, i) => i + 1))
    expect(state.pendingPermissions[0]).toMatchObject({ request_id: 'req-a', run_id: 'run-a' })
    expect(state.isSending).toBe(false)
    expect(state.runStatus).toBe('succeeded')
    expect(store.localRunningSessionIds).toEqual([])
  })

  it('returns from loadSession after restoring a running snapshot without waiting for stream terminal', async () => {
    const store = useConversationRunsStore()
    const openStream = openSseResponse([
      traceEvent('run-a', 'session-a', 2, 'step_delta'),
    ])

    vi.spyOn(userApi, 'fetchMessages').mockResolvedValue({
      success: true,
      data: [
        {
          id: 'msg-user-a',
          session_id: 'session-a',
          role: 'user',
          content: '继续检查设备',
          created_at: '2026-05-25T10:00:00.000Z',
          updated_at: '2026-05-25T10:00:00.000Z',
        },
      ],
    } as any)

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        run_id: 'run-a',
        session_id: 'session-a',
        status: 'running',
        agent_kind: 'device',
        answer_so_far: '正在读取设备状态',
        trace_events: [traceEvent('run-a', 'session-a', 1, 'run_start')],
        pending_permissions: [],
      }), { status: 200 }))
      .mockResolvedValueOnce(openStream.response)
    vi.stubGlobal('fetch', fetchMock)

    const state = await store.loadSession('session-a', { isLoggedIn: true, authToken: 'token', force: true })
    const answer = state.messages.find((m: ChatEntry) => m.id === 'run:run-a:assistant')

    expect(state.loadingMessages).toBe(false)
    expect(state.isSending).toBe(true)
    expect(answer?.content).toBe('正在读取设备状态')
    expect(fetchMock).toHaveBeenCalledTimes(2)

    openStream.close()
  })

  it('submits restored HITL decisions with run_id and clears only that request', async () => {
    const store = useConversationRunsStore()
    const sessionA = store.ensureState('session-a')
    store.mergeSnapshot(sessionA, {
      run_id: 'run-a',
      session_id: 'session-a',
      status: 'running',
      agent_kind: 'device',
      pending_permissions: [
        {
          request_id: 'req-a',
          tool_name: 'Write',
          risk: 'write',
          tool_input: { command: 'reset' },
          run_id: 'run-a',
          session_id: 'session-a',
        },
        {
          request_id: 'req-b',
          tool_name: 'Read',
          risk: 'read',
          tool_input: { path: '/tmp/log' },
          run_id: 'run-a',
          session_id: 'session-a',
        },
      ],
    })
    vi.mocked(resolveChatPermission).mockResolvedValue({
      success: true,
      message: 'ok',
      request_id: 'req-a',
      decision: 'allow',
    })

    await store.submitPermission('session-a', 'req-a', 'allow', {
      updatedArgs: { command: 'status' },
      authToken: 'token',
    })

    expect(resolveChatPermission).toHaveBeenCalledWith(
      'req-a',
      {
        decision: 'allow',
        updated_args: { command: 'status' },
        session_id: 'session-a',
        run_id: 'run-a',
      },
      'token',
    )
    expect(sessionA.pendingPermissions.map((p: PendingPermission) => p.request_id)).toEqual(['req-b'])
  })

  it('restores the user message from snapshot when DB history lacks it (log-analysis resume)', () => {
    const store = useConversationRunsStore()
    const sessionA = store.ensureState('session-a')

    // Simulates the post-DB-fetch state for a log-analysis run that is still
    // in flight: the chat_messages row hasn't been written yet because the
    // log-analysis service only persists user+assistant together at terminal.
    store.mergeSnapshot(sessionA, {
      run_id: 'log-run-a',
      session_id: 'session-a',
      status: 'running',
      agent_kind: 'log_analysis',
      answer_so_far: '日志分析中',
      user_message: '请分析这个日志包',
      trace_events: [traceEvent('log-run-a', 'session-a', 1, 'run_start')],
    })

    const userMsg = sessionA.messages.find((m: ChatEntry) => m.role === 'user')
    const answerMsg = sessionA.messages.find((m: ChatEntry) => m.id === 'run:log-run-a:assistant')

    expect(userMsg).toMatchObject({
      id: 'run:log-run-a:user',
      role: 'user',
      content: '请分析这个日志包',
    })
    // User message must be ordered before the assistant placeholder.
    const userIdx = sessionA.messages.findIndex((m: ChatEntry) => m.id === 'run:log-run-a:user')
    const aiIdx = sessionA.messages.findIndex((m: ChatEntry) => m.id === 'run:log-run-a:assistant')
    expect(userIdx).toBeLessThan(aiIdx)
    expect(answerMsg?.content).toBe('日志分析中')
  })

  it('does not duplicate the user message when DB history already has it', () => {
    const store = useConversationRunsStore()
    const sessionA = store.ensureState('session-a')
    // Simulate post-DB-fetch state: backend already persisted the user msg
    // (DeviceAgent path commits the user message before the SSE stream
    // starts), so loadSession's fetchMessages has it in state.messages.
    sessionA.messages.push({
      id: 'msg-user-a',
      role: 'user',
      content: '请检查设备状态',
      kind: 'user',
    })

    store.mergeSnapshot(sessionA, {
      run_id: 'run-a',
      session_id: 'session-a',
      status: 'running',
      agent_kind: 'device',
      user_message: '请检查设备状态',
      trace_events: [traceEvent('run-a', 'session-a', 1, 'run_start')],
    })

    const userMsgs = sessionA.messages.filter((m: ChatEntry) => m.role === 'user')
    expect(userMsgs).toHaveLength(1)
    expect(userMsgs[0].id).toBe('msg-user-a')
  })
})
