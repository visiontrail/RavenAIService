import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ApiResponse, LogListData, LogRecord } from '../types'
import { logApi } from '../api'
import { userToken } from '../api/user'
import { getActiveLocale } from '../i18n/runtime'

const FRESH_MS = 30_000
const RETAIN_MS = 5 * 60_000
const MAX_PAGES = 10

export const useLogStore = defineStore('logs', () => {
  // 状态
  const logs = ref<LogRecord[]>([])
  const currentLog = ref<LogRecord | null>(null)
  const loading = ref(false)
  const refreshing = ref(false)
  const detailLoading = ref(false)
  const pagination = ref({
    total: 0,
    page: 1,
    per_page: 10,
    pages: 0,
  })
  const filters = ref({
    status: '',
    project_id: '' as number | '',
    search: '',
    start_time: '',
    end_time: '',
    sort_by: 'created_at' as 'created_at' | 'file_size' | 'updated_at' | 'filename',
    sort_order: 'desc' as 'asc' | 'desc',
  })

  // 只缓存当前应用生命周期内的摘要，避免把日志内容长期留在磁盘上。
  const cache = new Map<string, { data: LogListData; fetchedAt: number }>()
  const pending = new Map<string, Promise<ApiResponse<LogListData>>>()
  let requestSeq = 0
  let generation = 0
  let visibleKey = ''
  const readScope = () => JSON.stringify([userToken.get(), getActiveLocale()])
  let scope = readScope()

  const invalidateList = () => {
    generation++
    requestSeq++
    cache.clear()
    pending.clear()
    loading.value = false
    refreshing.value = false
  }

  const applyList = (data: LogListData, key: string) => {
    logs.value = data.logs
    pagination.value = { ...data.pagination }
    visibleKey = key
  }

  const fetchLogs = async (
    params: Partial<typeof filters.value & typeof pagination.value> = {},
    options: { force?: boolean } = {},
  ) => {
    const nextScope = readScope()
    if (scope !== nextScope) {
      invalidateList()
      logs.value = []
      visibleKey = ''
      scope = nextScope
    }
    const query = {
      compact: true,
      page: params.page ?? pagination.value.page,
      per_page: params.per_page ?? pagination.value.per_page,
      project_id: ((params.project_id ?? filters.value.project_id) === '' || (params.project_id ?? filters.value.project_id) === undefined)
        ? undefined
        : Number(params.project_id ?? filters.value.project_id),
      status: (params.status ?? filters.value.status) || undefined,
      start_time: (params.start_time ?? filters.value.start_time) || undefined,
      end_time: (params.end_time ?? filters.value.end_time) || undefined,
      search: (params.search ?? filters.value.search) || undefined,
      sort_by: params.sort_by ?? filters.value.sort_by,
      sort_order: params.sort_order ?? filters.value.sort_order,
    }
    const key = JSON.stringify(query)
    const seq = ++requestSeq
    const startedGeneration = generation
    const now = Date.now()
    for (const [cachedKey, entry] of cache) {
      if (now - entry.fetchedAt >= RETAIN_MS) cache.delete(cachedKey)
    }
    const cached = cache.get(key)
    if (cached) {
      // 访问时更新 LRU 次序，但不延长数据新鲜期。
      cache.delete(key)
      cache.set(key, cached)
      applyList(cached.data, key)
    } else if (visibleKey !== key) {
      logs.value = []
      // 保留总数直到响应返回；置零会让分页组件把目标页强制改回第一页。
      pagination.value = { ...pagination.value, page: query.page, per_page: query.per_page }
    }
    loading.value = !cached && visibleKey !== key
    refreshing.value = !loading.value
    if (cached && now - cached.fetchedAt < FRESH_MS && !options.force && !pending.has(key)) {
      loading.value = false
      refreshing.value = false
      return
    }

    try {
      let request = pending.get(key)
      if (!request) {
        request = logApi.getLogList(query).then(response => {
          if (generation === startedGeneration && scope === readScope() && response.success && response.data) {
            cache.delete(key)
            cache.set(key, { data: response.data, fetchedAt: Date.now() })
            while (cache.size > MAX_PAGES) cache.delete(cache.keys().next().value!)
          }
          return response
        }).finally(() => {
          if (pending.get(key) === request) pending.delete(key)
        })
        pending.set(key, request)
      }
      const response = await request
      if (seq === requestSeq && generation === startedGeneration && scope === readScope() && response.success && response.data) {
        applyList(response.data, key)
      }
    } catch (error) {
      console.error('Failed to fetch logs:', error)
    } finally {
      if (seq === requestSeq) {
        loading.value = false
        refreshing.value = false
      }
    }
  }

  const fetchLogDetail = async (id: string) => {
    detailLoading.value = true
    try {
      const response = await logApi.getLogDetail(id)
      if (response.success && response.data) {
        currentLog.value = response.data
      }
    } catch (error) {
      console.error('Failed to fetch log detail:', error)
    } finally {
      detailLoading.value = false
    }
  }

  const uploadLog = async (file: File, onProgress?: (progress: number) => void) => {
    try {
      const response = await logApi.uploadLog(file, onProgress)
      if (response.success && response.data) {
        invalidateList()
        logs.value.unshift(response.data)
        return response.data
      }
    } catch (error) {
      console.error('Failed to upload log:', error)
      throw error
    }
  }

  const deleteLog = async (id: string) => {
    try {
      const response = await logApi.deleteLog(id)
      if (response.success) {
        invalidateList()
        logs.value = logs.value.filter((log: LogRecord) => log.id !== id)
        // 删除后刷新分页数据
        await fetchLogs()
        return true
      }
    } catch (error) {
      console.error('Failed to delete log:', error)
      throw error
    }
  }

  const batchDeleteLogs = async (ids: string[]) => {
    try {
      const response = await logApi.batchDeleteLogs(ids)
      if (response.success) {
        invalidateList()
        logs.value = logs.value.filter((log: LogRecord) => !ids.includes(log.id))
        await fetchLogs()
        return true
      }
    } catch (error) {
      console.error('Failed to batch delete logs:', error)
      throw error
    }
  }

  const setFilters = (newFilters: Partial<typeof filters.value>) => {
    filters.value = { ...filters.value, ...newFilters }
  }

  const setPagination = (newPagination: Partial<typeof pagination.value>) => {
    pagination.value = { ...pagination.value, ...newPagination }
  }

  return {
    // 状态
    logs,
    currentLog,
    loading,
    refreshing,
    detailLoading,
    pagination,
    filters,
    // 操作
    fetchLogs,
    invalidateList,
    fetchLogDetail,
    uploadLog,
    deleteLog,
    batchDeleteLogs,
    setFilters,
    setPagination,
  }
})
