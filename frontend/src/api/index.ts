import axios from 'axios'
import type { ApiResponse, LogRecord } from '@/types'
import type { LogListData, DownloadInfo } from '@/types'

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

    return api.post('/api/v1/logs/upload', formData, {
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
    return api.get(`/api/v1/logs/${id}/download`, {
      responseType: 'blob',
    })
  },

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
    return api.get('/api/v1/health')
  },
}

export default api