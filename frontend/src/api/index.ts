import axios from 'axios'
import type { ApiResponse, LogRecord, PaginatedResponse } from '@/types'

// 创建axios实例
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8085',
  timeout: 30000,
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
    size?: number
    status?: string
    search?: string
  } = {}): Promise<ApiResponse<PaginatedResponse<LogRecord>>> => {
    return api.get('/api/logs', { params })
  },

  // 获取日志详情
  getLogDetail: (id: string): Promise<ApiResponse<LogRecord>> => {
    return api.get(`/api/logs/${id}`)
  },

  // 上传日志文件
  uploadLog: (file: File, onProgress?: (progress: number) => void): Promise<ApiResponse<LogRecord>> => {
    const formData = new FormData()
    formData.append('file', file)

    return api.post('/api/logs/upload', formData, {
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

  // 下载日志文件
  downloadLog: (id: string): Promise<Blob> => {
    return api.get(`/api/logs/${id}/download`, {
      responseType: 'blob',
    })
  },

  // 删除日志
  deleteLog: (id: string): Promise<ApiResponse> => {
    return api.delete(`/api/logs/${id}`)
  },

  // 批量删除日志
  batchDeleteLogs: (ids: string[]): Promise<ApiResponse> => {
    return api.post('/api/logs/batch-delete', { ids })
  },
}

// 任务相关API
export const taskApi = {
  // 获取任务列表
  getTaskList: (): Promise<ApiResponse<any[]>> => {
    return api.get('/api/tasks')
  },

  // 获取任务状态
  getTaskStatus: (taskId: string): Promise<ApiResponse<any>> => {
    return api.get(`/api/tasks/${taskId}/status`)
  },
}

// 健康检查API
export const healthApi = {
  check: (): Promise<ApiResponse> => {
    return api.get('/api/health')
  },
}

export default api