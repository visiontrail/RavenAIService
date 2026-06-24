import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the share API client so the composable's state machine can be tested
// in isolation (the node test harness has no real backend or DOM).
const get = vi.fn()
const createOrRefresh = vi.fn()
const revoke = vi.fn()
const copyToClipboard = vi.fn()

vi.mock('@/api/share', () => ({
  shareApi: {
    get: (...args: unknown[]) => get(...args),
    createOrRefresh: (...args: unknown[]) => createOrRefresh(...args),
    revoke: (...args: unknown[]) => revoke(...args),
    getPublic: vi.fn(),
  },
}))

vi.mock('@/utils', () => ({
  copyToClipboard: (...args: unknown[]) => copyToClipboard(...args),
}))

import { useConversationShare } from '@/composables/useConversationShare'

const SID = 'session-123'

describe('useConversationShare', () => {
  beforeEach(() => {
    get.mockReset()
    createOrRefresh.mockReset()
    revoke.mockReset()
    copyToClipboard.mockReset()
  })

  it('loads the unshared state for a never-shared session', async () => {
    get.mockResolvedValue({ data: { is_active: false } })
    const share = useConversationShare()

    await share.load(SID)

    expect(get).toHaveBeenCalledWith(SID)
    expect(share.isShared.value).toBe(false)
    expect(share.shareUrl.value).toBe('')
  })

  it('transitions unshared → shared on generate', async () => {
    get.mockResolvedValue({ data: { is_active: false } })
    createOrRefresh.mockResolvedValue({
      data: {
        is_active: true,
        token: 'tok_abc',
        share_url: 'https://ravenai.example.com/share/tok_abc',
        shared_at: '2026-06-16T10:00:00Z',
        message_count: 4,
      },
    })
    const share = useConversationShare()
    await share.load(SID)
    expect(share.isShared.value).toBe(false)

    const ok = await share.generate(SID)

    expect(ok).toBe(true)
    expect(createOrRefresh).toHaveBeenCalledWith(SID)
    expect(share.isShared.value).toBe(true)
    expect(share.shareUrl.value).toBe('https://ravenai.example.com/share/tok_abc')
    expect(share.messageCount.value).toBe(4)
  })

  it('refresh keeps the link and updates the snapshot time', async () => {
    createOrRefresh
      .mockResolvedValueOnce({
        data: {
          is_active: true,
          token: 'tok_same',
          share_url: 'https://ravenai.example.com/share/tok_same',
          shared_at: '2026-06-16T10:00:00Z',
          message_count: 2,
        },
      })
      .mockResolvedValueOnce({
        data: {
          is_active: true,
          token: 'tok_same',
          share_url: 'https://ravenai.example.com/share/tok_same',
          shared_at: '2026-06-16T12:30:00Z',
          message_count: 5,
        },
      })
    const share = useConversationShare()

    await share.generate(SID)
    const firstSharedAt = share.sharedAt.value
    await share.generate(SID)

    expect(share.shareUrl.value).toBe('https://ravenai.example.com/share/tok_same')
    expect(share.sharedAt.value).not.toBe(firstSharedAt)
    expect(share.sharedAt.value).toBe('2026-06-16T12:30:00Z')
  })

  it('transitions shared → unshared on revoke', async () => {
    createOrRefresh.mockResolvedValue({
      data: {
        is_active: true,
        token: 'tok_x',
        share_url: 'https://ravenai.example.com/share/tok_x',
        shared_at: '2026-06-16T10:00:00Z',
        message_count: 3,
      },
    })
    revoke.mockResolvedValue({ data: { is_active: false } })
    const share = useConversationShare()
    await share.generate(SID)
    expect(share.isShared.value).toBe(true)

    const ok = await share.revoke(SID)

    expect(ok).toBe(true)
    expect(revoke).toHaveBeenCalledWith(SID)
    expect(share.isShared.value).toBe(false)
    expect(share.shareUrl.value).toBe('')
  })

  it('copy writes the public link via the injected clipboard writer', async () => {
    const written: string[] = []
    createOrRefresh.mockResolvedValue({
      data: {
        is_active: true,
        token: 'tok_c',
        share_url: 'https://ravenai.example.com/share/tok_c',
        shared_at: '2026-06-16T10:00:00Z',
        message_count: 1,
      },
    })
    const share = useConversationShare({
      copyText: async (text: string) => {
        written.push(text)
      },
    })
    await share.generate(SID)

    const ok = await share.copy()

    expect(ok).toBe(true)
    expect(written).toEqual(['https://ravenai.example.com/share/tok_c'])
  })

  it('copy uses the default clipboard helper when no writer is injected', async () => {
    copyToClipboard.mockResolvedValue(true)
    createOrRefresh.mockResolvedValue({
      data: {
        is_active: true,
        token: 'tok_default',
        share_url: 'http://10.60.11.3:8085/share/tok_default',
        shared_at: '2026-06-16T10:00:00Z',
        message_count: 1,
      },
    })
    const share = useConversationShare()
    await share.generate(SID)

    const ok = await share.copy()

    expect(ok).toBe(true)
    expect(copyToClipboard).toHaveBeenCalledWith('http://10.60.11.3:8085/share/tok_default')
  })

  it('rebuilds the link from the live origin, identical for load (GET) and generate (POST)', async () => {
    // Reproduces the port-dropping regression: the backend builds share_url from
    // the request Origin (present on the POST) but falls back to a proxy-rewritten
    // Host on the same-origin GET. Simulate that by returning a port-less URL from
    // get and a full one from createOrRefresh; the composable must surface the
    // browser-origin URL for both so the port never disappears on re-open.
    const origin = 'http://10.60.11.3:8085'
    vi.stubGlobal('window', { location: { origin } })
    try {
      get.mockResolvedValue({
        data: { is_active: true, token: 'tok_p', share_url: 'http://10.60.11.3/share/tok_p' },
      })
      createOrRefresh.mockResolvedValue({
        data: { is_active: true, token: 'tok_p', share_url: `${origin}/share/tok_p` },
      })
      const share = useConversationShare()

      await share.load(SID)
      expect(share.shareUrl.value).toBe(`${origin}/share/tok_p`)

      await share.generate(SID)
      expect(share.shareUrl.value).toBe(`${origin}/share/tok_p`)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('copy returns false when there is no link yet', async () => {
    const share = useConversationShare({ copyText: async () => {} })
    expect(await share.copy()).toBe(false)
  })

  it('records an error when generate fails', async () => {
    createOrRefresh.mockRejectedValue(new Error('boom'))
    const share = useConversationShare()

    const ok = await share.generate(SID)

    expect(ok).toBe(false)
    expect(share.error.value).toBe('generate_failed')
    expect(share.isShared.value).toBe(false)
  })
})
