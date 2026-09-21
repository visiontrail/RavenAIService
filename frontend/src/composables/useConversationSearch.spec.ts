import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { userApi } from '@/api/user'
import { useConversationSearch } from './useConversationSearch'

vi.mock('@/api/user', () => ({ userApi: { searchSessions: vi.fn() } }))
const page = (id: string, more = false) => ({ success: true, data: { items: [{ id, title: id, snippet: id }], has_more: more } })
const search = vi.mocked(userApi.searchSessions)
const scopes: ReturnType<typeof effectScope>[] = []
const setup = () => {
  const scope = effectScope(); scopes.push(scope)
  return scope.run(useConversationSearch)!
}
afterEach(() => { scopes.forEach(scope => scope.stop()); scopes.length = 0; vi.useRealTimers(); vi.resetAllMocks() })

describe('conversation search requests', () => {
  it('debounces edits and ignores old responses even before the next request starts', async () => {
    vi.useFakeTimers()
    let finish!: (value: any) => void
    search.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const state = setup()
    await vi.advanceTimersByTimeAsync(0)
    const signal = search.mock.calls[0][2]!
    state.query.value = '部署'
    expect(signal.aborted).toBe(true)
    finish(page('stale'))
    await Promise.resolve()
    expect(state.items.value).toEqual([])
    search.mockResolvedValueOnce(page('fresh') as any)
    await vi.advanceTimersByTimeAsync(249)
    expect(search).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(state.items.value[0].id).toBe('fresh')
  })
  it('waits for IME composition and cancels requests when closed', async () => {
    vi.useFakeTimers()
    search.mockResolvedValue(page('recent') as any)
    const state = setup()
    await vi.advanceTimersByTimeAsync(0)
    state.composing.value = true
    state.query.value = 'zhong'
    await vi.advanceTimersByTimeAsync(400)
    expect(search).toHaveBeenCalledTimes(1)
    state.query.value = '中文'
    state.composing.value = false
    await vi.advanceTimersByTimeAsync(250)
    expect(search.mock.calls[1][0]).toBe('中文')
    scopes[0].stop()
    expect(search.mock.calls[1][2]!.aborted).toBe(true)
  })
  it('retains earlier pages after failure and retries the correct offset', async () => {
    vi.useFakeTimers()
    search.mockResolvedValueOnce(page('a', true) as any)
    const state = setup()
    await vi.advanceTimersByTimeAsync(0)
    search.mockRejectedValueOnce(new Error('offline'))
    state.loadMore()
    await vi.advanceTimersByTimeAsync(0)
    expect(state.error.value).toBe(true)
    expect(state.items.value[0].id).toBe('a')
    search.mockResolvedValueOnce({ success: true, data: { items: [page('a').data.items[0], page('b').data.items[0]], has_more: false } } as any)
    await state.retry()
    expect(search.mock.calls[2][1]).toBe(1)
    expect(state.items.value.map(item => item.id)).toEqual(['a', 'b'])
    expect(state.error.value).toBe(false)
  })
})
