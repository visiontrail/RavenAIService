import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { userApi, userToken } from '@/api/user'
import { useAnnouncementStore } from '@/stores/announcement'
import type { SystemAnnouncement } from '@/types'

vi.mock('@/api/user', () => ({
  userApi: {
    getPendingAnnouncement: vi.fn(),
    dismissAnnouncement: vi.fn(),
  },
  userToken: {
    get: vi.fn(() => 'token'),
  },
}))

const announcement = (id: string, title = 'Notice'): SystemAnnouncement => ({
  id,
  title,
  content: 'Announcement body',
  published_at: '2026-07-14T10:00:00Z',
  published_by: 'admin',
  active: true,
})

const pendingMock = vi.mocked(userApi.getPendingAnnouncement)
const dismissMock = vi.mocked(userApi.dismissAnnouncement)
const tokenMock = vi.mocked(userToken.get)

describe('announcement store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    pendingMock.mockReset()
    dismissMock.mockReset()
    tokenMock.mockReset()
    tokenMock.mockReturnValue('token')
  })

  it('loads a pending announcement for an authenticated user', async () => {
    const store = useAnnouncementStore()
    pendingMock.mockResolvedValue({ success: true, data: announcement('a-1') })

    await store.checkPending()

    expect(store.pending?.id).toBe('a-1')
    expect(store.checking).toBe(false)
  })

  it('deduplicates concurrent pending checks', async () => {
    const store = useAnnouncementStore()
    let resolve!: (value: unknown) => void
    pendingMock.mockReturnValue(new Promise((done) => { resolve = done }) as any)

    const first = store.checkPending()
    const second = store.checkPending()
    resolve({ success: true, data: announcement('a-1') })
    await Promise.all([first, second])

    expect(pendingMock).toHaveBeenCalledTimes(1)
  })

  it('clears the dialog only after dismissal is persisted', async () => {
    const store = useAnnouncementStore()
    store.pending = announcement('a-1')
    dismissMock.mockResolvedValue({
      success: true,
      data: { announcement_id: 'a-1', dismissed: true },
    })

    await expect(store.dismiss()).resolves.toBe(true)
    expect(store.pending).toBeNull()
  })

  it('keeps the announcement visible when dismissal fails', async () => {
    const store = useAnnouncementStore()
    store.pending = announcement('a-1')
    dismissMock.mockRejectedValue(new Error('network down'))

    await expect(store.dismiss()).rejects.toThrow('network down')
    expect(store.pending?.id).toBe('a-1')
  })

  it('loads the replacement after a stale-id conflict', async () => {
    const store = useAnnouncementStore()
    store.pending = announcement('a-1')
    dismissMock.mockRejectedValue({ response: { status: 409 } })
    pendingMock.mockResolvedValue({ success: true, data: announcement('a-2', 'New') })

    await expect(store.dismiss()).rejects.toBeTruthy()
    expect(store.pending?.id).toBe('a-2')
  })

  it('does not request announcements while logged out', async () => {
    const store = useAnnouncementStore()
    tokenMock.mockReturnValue('')

    await expect(store.checkPending()).resolves.toBeNull()
    expect(pendingMock).not.toHaveBeenCalled()
  })

  it('reset prevents an in-flight response from reopening the dialog', async () => {
    const store = useAnnouncementStore()
    let resolve!: (value: unknown) => void
    pendingMock.mockReturnValue(new Promise((done) => { resolve = done }) as any)

    const request = store.checkPending()
    store.reset()
    resolve({ success: true, data: announcement('late') })
    await request

    expect(store.pending).toBeNull()
    expect(store.checking).toBe(false)
  })
})
