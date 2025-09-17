import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
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
    size: 10,
    pages: 0,
  })
  const filters = ref({
    status: '',
    search: '',
  })

  // 计算属性
  const filteredLogs = computed(() => {
    return logs.value.filter((log: LogRecord) => {
      const matchesStatus = !filters.value.status || log.status === filters.value.status
      const matchesSearch = !filters.value.search || 
        log.filename.toLowerCase().includes(filters.value.search.toLowerCase()) ||
        log.task_name?.toLowerCase().includes(filters.value.search.toLowerCase())
      return matchesStatus && matchesSearch
    })
  })

  // 操作
  const fetchLogs = async (params: {
    page?: number
    size?: number
    status?: string
    search?: string
  } = {}) => {
    loading.value = true
    try {
      const response = await logApi.getLogList({
        page: params.page || pagination.value.page,
        size: params.size || pagination.value.size,
        status: params.status || filters.value.status,
        search: params.search || filters.value.search,
      })
      
      if (response.success && response.data) {
        logs.value = response.data.items
        pagination.value = {
          total: response.data.total,
          page: response.data.page,
          size: response.data.size,
          pages: response.data.pages,
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
    // 计算属性
    filteredLogs,
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