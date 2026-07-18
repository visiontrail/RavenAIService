import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { bugFixApi } from '@/api/bugFixes'
import { useBugFixStore } from '@/stores/bugFixes'
import type { BugFixTaskDetail } from '@/types'

vi.mock('@/api/bugFixes', () => ({
  bugFixApi: {
    list: vi.fn(),
    detail: vi.fn(),
    retry: vi.fn(),
  },
}))

const failedTask = (): BugFixTaskDetail => ({
  id: 'bug-fix-1',
  title: 'Fix crash',
  status: 'failed',
  merge_request_count: 0,
  error: 'agent_failed',
  proposed_fixes: [{ title: 'Guard missing state' }],
  fix_outcomes: [{ fix_index: 1, outcome: 'failed' }],
  merge_requests: [],
  finished_at: '2026-07-17T10:00:00',
})

const retryMock = vi.mocked(bugFixApi.retry)

describe('bug fix retry store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    retryMock.mockReset()
  })

  it('replaces the failed detail with the pending retry response', async () => {
    const store = useBugFixStore()
    store.currentTask = failedTask()
    retryMock.mockResolvedValue({
      success: true,
      data: {
        ...failedTask(),
        status: 'pending',
        error: null,
        fix_outcomes: [],
        finished_at: null,
      },
    })

    const request = store.retryTask('bug-fix-1')
    expect(store.retrying).toBe(true)
    await request

    expect(retryMock).toHaveBeenCalledOnce()
    expect(store.currentTask?.status).toBe('pending')
    expect(store.currentTask?.error).toBeNull()
    expect(store.retrying).toBe(false)
  })

  it('keeps the failed detail available when retry submission fails', async () => {
    const store = useBugFixStore()
    store.currentTask = failedTask()
    retryMock.mockRejectedValue({ response: { data: { detail: '队列不可用' } } })

    await expect(store.retryTask('bug-fix-1')).rejects.toBeTruthy()

    expect(store.currentTask?.status).toBe('failed')
    expect(store.error).toBe('队列不可用')
    expect(store.retrying).toBe(false)
  })
})
