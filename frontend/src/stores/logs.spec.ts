import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { logApi } from '@/api'
import { userToken } from '@/api/user'
import { useLogStore } from './logs'
import type { ApiResponse, LogListData } from '@/types'

vi.mock('@/api', () => ({
  logApi: {
    getLogList: vi.fn(), getLogDetail: vi.fn(), deleteLog: vi.fn(),
    batchDeleteLogs: vi.fn(), uploadLog: vi.fn(),
  },
}))
vi.mock('@/api/user', () => ({ userToken: { get: vi.fn(() => 'user-a') } }))

const list = (id: string, page = 1): ApiResponse<LogListData> => ({
  success: true,
  data: {
    logs: [{ id, filename: `${id}.log`, file_size: 10, status: 'completed', download_count: 0, created_at: '', updated_at: '' }],
    pagination: { page, per_page: 10, total: 120, pages: 12 },
  },
})
const deferred = () => {
  let resolve!: (response: ApiResponse<LogListData>) => void
  const promise = new Promise<ApiResponse<LogListData>>(r => { resolve = r })
  return { promise, resolve }
}
const getList = vi.mocked(logApi.getLogList)

describe('log list cache', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-14T00:00:00Z'))
    vi.clearAllMocks()
    getList.mockReset()
    vi.mocked(userToken.get).mockReturnValue('user-a')
  })
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

  it('requests compact rows, deduplicates concurrent loads, and reuses fresh pages', async () => {
    const store = useLogStore()
    const response = deferred()
    getList.mockReturnValue(response.promise)
    const first = store.fetchLogs()
    const second = store.fetchLogs()
    expect(store.loading).toBe(true)
    expect(getList).toHaveBeenCalledTimes(1)
    expect(getList.mock.calls[0][0]).toMatchObject({ compact: true, page: 1 })
    response.resolve(list('a'))
    await Promise.all([first, second])
    await store.fetchLogs()
    expect(getList).toHaveBeenCalledTimes(1)
    expect(store.logs[0].id).toBe('a')
    expect(store.loading).toBe(false)
    expect(store.refreshing).toBe(false)
  })

  it('renders stale rows immediately and refreshes without a blocking overlay', async () => {
    const store = useLogStore()
    getList.mockResolvedValueOnce(list('old'))
    await store.fetchLogs()
    vi.advanceTimersByTime(31_000)
    const response = deferred()
    getList.mockReturnValueOnce(response.promise)
    const refresh = store.fetchLogs()
    expect(store.logs[0].id).toBe('old')
    expect(store.loading).toBe(false)
    expect(store.refreshing).toBe(true)
    response.resolve(list('new'))
    await refresh
    expect(store.logs[0].id).toBe('new')
    expect(store.refreshing).toBe(false)
  })

  it('manual refresh bypasses freshness and keeps rows if the network fails', async () => {
    const store = useLogStore()
    getList.mockResolvedValueOnce(list('a'))
    await store.fetchLogs()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    getList.mockRejectedValueOnce(new Error('offline'))
    await store.fetchLogs({}, { force: true })
    expect(getList).toHaveBeenCalledTimes(2)
    expect(store.logs[0].id).toBe('a')
    expect(store.loading || store.refreshing).toBe(false)
  })

  it('does not let a slow previous filter overwrite the active result', async () => {
    const store = useLogStore()
    const slow = deferred()
    getList.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(list('b'))
    const previous = store.fetchLogs({ search: 'a' })
    await store.fetchLogs({ search: 'b' })
    slow.resolve(list('a'))
    await previous
    expect(store.logs[0].id).toBe('b')
    await store.fetchLogs({ search: 'a' })
    expect(store.logs[0].id).toBe('a')
    expect(getList).toHaveBeenCalledTimes(2)
  })

  it('preserves the known page count while loading a different page', async () => {
    const store = useLogStore()
    getList.mockResolvedValueOnce(list('first'))
    await store.fetchLogs()
    const response = deferred()
    getList.mockReturnValueOnce(response.promise)
    const nextPage = store.fetchLogs({ page: 2 })
    expect(store.pagination).toMatchObject({ page: 2, total: 120, pages: 12 })
    expect(store.logs).toEqual([])
    expect(store.loading).toBe(true)
    response.resolve(list('second', 2))
    await nextPage
    expect(store.pagination.page).toBe(2)
    expect(store.logs[0].id).toBe('second')
  })

  it('cannot resurrect deleted rows from a pre-delete request or cached page', async () => {
    const store = useLogStore()
    getList.mockResolvedValueOnce(list('deleted'))
    await store.fetchLogs()
    const slow = deferred()
    getList.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(list('remaining'))
    const previous = store.fetchLogs({}, { force: true })
    vi.mocked(logApi.deleteLog).mockResolvedValueOnce({ success: true })
    await store.deleteLog('deleted')
    slow.resolve(list('deleted'))
    await previous
    await store.fetchLogs()
    expect(store.logs[0].id).toBe('remaining')
    expect(getList).toHaveBeenCalledTimes(3)
  })

  it('expires old pages and bounds the cache to ten pages', async () => {
    const store = useLogStore()
    getList.mockImplementation(async params => list(`p${params?.page}`, params?.page))
    for (let page = 1; page <= 11; page++) await store.fetchLogs({ page })
    await store.fetchLogs({ page: 1 })
    expect(getList).toHaveBeenCalledTimes(12)
    await store.fetchLogs({ page: 11 })
    expect(getList).toHaveBeenCalledTimes(12)
    vi.advanceTimersByTime(5 * 60_000)
    await store.fetchLogs({ page: 1 })
    expect(getList).toHaveBeenCalledTimes(13)
  })

  it('separates page size, project, sort, status and date filters', async () => {
    const store = useLogStore()
    getList.mockResolvedValue(list('a'))
    for (const query of [
      {}, { project_id: 2 }, { per_page: 20 }, { status: 'failed' },
      { sort_by: 'filename' as const }, { sort_order: 'asc' as const },
      { start_time: '2026-01-01' }, { end_time: '2026-12-31' },
    ]) await store.fetchLogs(query)
    expect(getList).toHaveBeenCalledTimes(8)
  })

  it('clears old-account rows and ignores its pending response after account changes', async () => {
    const store = useLogStore()
    getList.mockResolvedValueOnce(list('account-a'))
    await store.fetchLogs()
    const previous = deferred()
    const current = deferred()
    getList.mockReturnValueOnce(previous.promise).mockReturnValueOnce(current.promise)
    const oldRequest = store.fetchLogs({}, { force: true })
    vi.mocked(userToken.get).mockReturnValue('user-b')
    const newRequest = store.fetchLogs()
    expect(store.logs).toEqual([])
    expect(store.loading).toBe(true)
    previous.resolve(list('account-a'))
    await oldRequest
    expect(store.logs).toEqual([])
    expect(store.loading).toBe(true)
    current.resolve(list('account-b'))
    await newRequest
    expect(store.logs[0].id).toBe('account-b')
  })
})
