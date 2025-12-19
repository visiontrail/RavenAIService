import axios from 'axios'
import type { ApiResponse, LogRecord } from '@/types'
import type { LogListData, DownloadInfo } from '@/types'

const normalizeBase = (value?: string | null) => (value ? value.replace(/\/+$/, '') : '')
const defaultBase = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8085'
const runtimeLogBase = typeof window !== 'undefined' ? (window as any).__LOG_API_BASE_URL__ : undefined
const envLogBase =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (typeof (globalThis as any).__VITE_API_BASE_URL__ !== 'undefined'
    ? ((globalThis as any).__VITE_API_BASE_URL__ as string | undefined)
    : undefined)
const computedBaseURL =
  normalizeBase(runtimeLogBase) ||
  normalizeBase(envLogBase) ||
  normalizeBase(defaultBase)

export const API_BASE_URL = computedBaseURL

// 创建axios实例
const api = axios.create({
  baseURL: computedBaseURL,
  timeout: 300000, // 增加到5分钟超时，用于大文件上传
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    // 可以在这里添加认证token等
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

// 日志相关API
export const logApi = {
  // 获取日志列表
  getLogList: (params: {
    page?: number
    per_page?: number
    log_type?: string
    status?: string
    start_time?: string
    end_time?: string
    search?: string
    sort_by?: 'created_at' | 'file_size' | 'updated_at' | 'filename'
    sort_order?: 'asc' | 'desc'
  } = {}): Promise<ApiResponse<LogListData>> => {
    return api.get('/api/v1/logs', { params })
  },

  // 获取日志详情
  getLogDetail: (id: string): Promise<ApiResponse<LogRecord>> => {
    return api.get(`/api/v1/logs/${id}`)
  },

  // 上传日志文件
  uploadLog: (file: File, onProgress?: (progress: number) => void): Promise<ApiResponse<LogRecord>> => {
    const formData = new FormData()
    formData.append('file', file)

    // 使用简化的上传端点进行测试
    return api.post('/api/v1/logs/upload-simple', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (progressEvent.total && onProgress) {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          onProgress(progress)
        }
      },
    })
  },

  // 下载日志文件 - 返回Blob（旧方式，保留兼容性）
  downloadLog: (id: string): Promise<Blob> => {
    return api.get(`/api/v1/logs/${id}/download`, {
      responseType: 'blob',
    })
  },

  // 获取下载URL - 直接下载，不等待响应（推荐方式）
  getDownloadUrl: (id: string): string => {
    return `${computedBaseURL}/api/v1/logs/${id}/download`
  },

  // 异步更新下载次数 - 用于在直接URL下载后更新计数
  incrementDownloadCount: (id: string) => 
    api.post(`/api/v1/logs/${id}/download-count`),

  // 删除日志
  deleteLog: (id: string): Promise<ApiResponse> => {
    return api.delete(`/api/v1/logs/${id}`)
  },

  // 批量删除日志
  batchDeleteLogs: (ids: string[]): Promise<ApiResponse> => {
    return api.post('/api/v1/logs/batch/delete', { log_ids: ids, force: false })
  },

  // 批量下载日志
  batchDownloadLogs: (ids: string[]): Promise<ApiResponse<DownloadInfo>> => {
    return api.post('/api/v1/logs/batch/download', { log_ids: ids, compress: true, include_metadata: false })
  },

  // AI分析日志
  analyzeLog: (id: string, query: string): Promise<ApiResponse<any>> => {
    const formData = new FormData()
    formData.append('query', query)
    return api.post(`/api/v1/logs/${id}/analyze`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },

  // 获取AI分析状态
  getAIAnalysisStatus: (id: string): Promise<ApiResponse<any>> => {
    return api.get(`/api/v1/logs/${id}/analysis/status`)
  },
}

// 任务相关API
export const taskApi = {
  // 获取任务列表
  getTaskList: (): Promise<ApiResponse<any[]>> => {
    return api.get('/api/v1/tasks')
  },

  // 获取任务状态
  getTaskStatus: (taskId: string): Promise<ApiResponse<any>> => {
    return api.get(`/api/v1/tasks/${taskId}/status`)
  },
}

// 健康检查API
export const healthApi = {
  check: (): Promise<ApiResponse> => {
    return api.get('/health')
  },
}

export default api
