import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { LogRecord } from '../types'
import { logApi } from '../api'

export const useLogStore = defineStore('logs', () => {
  // 状态
  const logs = ref<LogRecord[]>([])
  const currentLog = ref<LogRecord | null>(null)
  const loading = ref(false)
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

  // 操作
  const fetchLogs = async (params: Partial<typeof filters.value & typeof pagination.value> = {}) => {
    loading.value = true
    try {
      const query = {
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

      const response = await logApi.getLogList(query)
      if (response.success && response.data) {
        logs.value = response.data.logs
        pagination.value = {
          total: response.data.pagination.total,
          page: response.data.pagination.page,
          per_page: response.data.pagination.per_page,
          pages: response.data.pagination.pages,
        }
      }
    } catch (error) {
      console.error('Failed to fetch logs:', error)
    } finally {
      loading.value = false
    }
  }

  const fetchLogDetail = async (id: string) => {
    loading.value = true
    try {
      const response = await logApi.getLogDetail(id)
      if (response.success && response.data) {
        currentLog.value = response.data
      }
    } catch (error) {
      console.error('Failed to fetch log detail:', error)
    } finally {
      loading.value = false
    }
  }

  const uploadLog = async (file: File, onProgress?: (progress: number) => void) => {
    try {
      const response = await logApi.uploadLog(file, onProgress)
      if (response.success && response.data) {
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
    pagination,
    filters,
    // 操作
    fetchLogs,
    fetchLogDetail,
    uploadLog,
    deleteLog,
    batchDeleteLogs,
    setFilters,
    setPagination,
  }
})