import { defineStore } from 'pinia'
import { ref } from 'vue'
import { bugFixApi } from '@/api/bugFixes'
import type { BugFixTaskDetail, BugFixTaskSummary } from '@/types'

export const useBugFixStore = defineStore('bugFixes', () => {
  const tasks = ref<BugFixTaskSummary[]>([])
  const currentTask = ref<BugFixTaskDetail | null>(null)
  const loading = ref(false)
  const detailLoading = ref(false)
  const error = ref<string | null>(null)
  const pagination = ref({
    total: 0,
    page: 1,
    page_size: 20,
    pages: 0,
  })

  const parseError = (err: any, fallback: string) => {
    const detail = err?.response?.data?.detail || err?.response?.data?.message
    if (typeof detail === 'string') return detail
    return err?.message || fallback
  }

  const fetchTasks = async (params: { page?: number; page_size?: number } = {}) => {
    loading.value = true
    error.value = null
    try {
      const response = await bugFixApi.list({
        page: params.page ?? pagination.value.page,
        page_size: params.page_size ?? pagination.value.page_size,
      })
      if (!response?.success) {
        throw new Error(response?.message || '获取 Bug 修复任务失败')
      }
      const pageSize = response.page_size || params.page_size || pagination.value.page_size
      tasks.value = response.data || []
      pagination.value = {
        total: response.total || 0,
        page: response.page || params.page || 1,
        page_size: pageSize,
        pages: pageSize > 0 ? Math.ceil((response.total || 0) / pageSize) : 0,
      }
    } catch (err: any) {
      error.value = parseError(err, '获取 Bug 修复任务失败')
      throw err
    } finally {
      loading.value = false
    }
  }

  const fetchDetail = async (id: string) => {
    detailLoading.value = true
    error.value = null
    try {
      const response = await bugFixApi.detail(id)
      if (!response?.success || !response.data) {
        throw new Error(response?.message || '获取 Bug 修复详情失败')
      }
      currentTask.value = response.data
      return response.data
    } catch (err: any) {
      error.value = parseError(err, '获取 Bug 修复详情失败')
      throw err
    } finally {
      detailLoading.value = false
    }
  }

  const resetCurrent = () => {
    currentTask.value = null
  }

  return {
    tasks,
    currentTask,
    loading,
    detailLoading,
    error,
    pagination,
    fetchTasks,
    fetchDetail,
    resetCurrent,
  }
})
