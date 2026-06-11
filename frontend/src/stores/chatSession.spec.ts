import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useChatSessionStore } from '@/stores/chatSession'
import { userApi } from '@/api/user'
import type { ChatSessionSummary } from '@/types'

vi.mock('@/api/user', () => ({
  userApi: {
    listSessions: vi.fn(),
  },
}))

const now = new Date('2026-06-11T10:00:00.000Z').toISOString()

const session = (id: string, title: string): ChatSessionSummary => ({
  id,
  title,
  created_at: now,
  updated_at: now,
  last_message_at: now,
  message_count: 1,
})

const listSessionsMock = vi.mocked(userApi.listSessions)

describe('chatSession store load (stale-while-revalidate)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listSessionsMock.mockReset()
  })

  it('initial load is blocking: loading=true while in flight', async () => {
    const store = useChatSessionStore()
    let resolve!: (v: unknown) => void
    listSessionsMock.mockReturnValue(new Promise((r) => { resolve = r }) as any)

    const p = store.load()
    expect(store.loading).toBe(true)
    expect(store.refreshing).toBe(false)

    resolve({ success: true, data: [session('a', 'A')] })
    await p
    expect(store.loading).toBe(false)
    expect(store.sessions).toHaveLength(1)
  })

  it('refresh with existing sessions is background: list stays, loading stays false', async () => {
    const store = useChatSessionStore()
    store.sessions = [session('a', 'A')]
    let resolve!: (v: unknown) => void
    listSessionsMock.mockReturnValue(new Promise((r) => { resolve = r }) as any)

    const p = store.load()
    expect(store.loading).toBe(false)
    expect(store.refreshing).toBe(true)
    // The stale list must remain rendered while the refresh is in flight.
    expect(store.sessions).toHaveLength(1)

    resolve({ success: true, data: [session('a', 'A'), session('b', 'B')] })
    await p
    expect(store.refreshing).toBe(false)
    expect(store.sessions).toHaveLength(2)
  })

  it('failed background refresh keeps the stale list', async () => {
    const store = useChatSessionStore()
    store.sessions = [session('a', 'A')]
    listSessionsMock.mockRejectedValue(new Error('network down'))

    await expect(store.load()).rejects.toThrow('network down')
    expect(store.sessions).toHaveLength(1)
    expect(store.refreshing).toBe(false)
  })

  it('failed blocking load clears the list', async () => {
    const store = useChatSessionStore()
    listSessionsMock.mockRejectedValue(new Error('network down'))

    await expect(store.load()).rejects.toThrow('network down')
    expect(store.sessions).toHaveLength(0)
    expect(store.loading).toBe(false)
  })

  it('out-of-order responses cannot overwrite a newer load', async () => {
    const store = useChatSessionStore()
    store.sessions = [session('a', 'A')]
    let resolveSlow!: (v: unknown) => void
    let resolveFast!: (v: unknown) => void
    listSessionsMock
      .mockReturnValueOnce(new Promise((r) => { resolveSlow = r }) as any)
      .mockReturnValueOnce(new Promise((r) => { resolveFast = r }) as any)

    const slow = store.load()
    const fast = store.load()
    resolveFast({ success: true, data: [session('b', 'B')] })
    await fast
    resolveSlow({ success: true, data: [session('stale', 'Stale')] })
    await slow

    expect(store.sessions.map((s) => s.id)).toEqual(['b'])
    expect(store.refreshing).toBe(false)
  })

  it('reset invalidates in-flight loads', async () => {
    const store = useChatSessionStore()
    store.sessions = [session('a', 'A')]
    let resolve!: (v: unknown) => void
    listSessionsMock.mockReturnValue(new Promise((r) => { resolve = r }) as any)

    const p = store.load()
    store.reset()
    resolve({ success: true, data: [session('ghost', 'Ghost')] })
    await p

    expect(store.sessions).toHaveLength(0)
    expect(store.refreshing).toBe(false)
    expect(store.loading).toBe(false)
  })
})
