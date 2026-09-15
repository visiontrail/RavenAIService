import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamAdminFollowUp } from './adminFollowUp'

vi.mock('./index', () => ({ API_BASE_URL: '', localeHeaderInterceptor: (value: unknown) => value }))
vi.mock('./admin', () => ({ adminToken: { get: () => 'admin-test', clear: vi.fn() } }))
afterEach(() => vi.unstubAllGlobals())

function mockStream(chunks: string[]) {
  const encoder = new TextEncoder()
  const fetcher = vi.fn(async () => new Response(new ReadableStream({
    start(controller) {
      for (const text of chunks) controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })))
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}

describe('temporary admin follow-up', () => {
  it('handles split frames and sends only explicit temporary history', async () => {
    const fetcher = mockStream(['data: {"type":"sta', 'rt"}\n\ndata: {"type":"delta","text":"你好"}\n\n',
      'data: {"type":"done","answer":"你好！"}\n\n'])
    const onText = vi.fn()
    const signal = new AbortController().signal
    const answer = await streamAdminFollowUp('event/id', 'why', [], signal, onText)
    expect(answer).toBe('你好！')
    expect(onText).toHaveBeenLastCalledWith('你好！')
    const [url, request] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('event%2Fid/conversation/follow-up')
    expect(JSON.parse(request.body as string)).toEqual({ question: 'why', history: [] })
    expect(request.signal).toBe(signal)
    expect(request.cache).toBe('no-store')
  })

  it('rejects interrupted streams instead of saving partial answers', async () => {
    mockStream(['data: {"type":"delta","text":"partial"}\n\n'])
    await expect(streamAdminFollowUp('id', 'why', [], new AbortController().signal, vi.fn())).rejects.toThrow('before the answer completed')
  })

  it('reports server errors', async () => {
    mockStream(['data: {"type":"error","message":"workspace unavailable"}\n\n'])
    await expect(streamAdminFollowUp('id', 'why', [], new AbortController().signal, vi.fn())).rejects.toThrow('workspace unavailable')
  })
})
