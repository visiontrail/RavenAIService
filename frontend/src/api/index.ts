import axios from 'axios'
import type { ApiResponse, LogRecord } from '@/types'
import type { LogListData, DownloadInfo } from '@/types'
import { getActiveLocale, LOCALE_HEADER } from '@/i18n/runtime'

const normalizeBase = (value?: string | null) => (value ? value.replace(/\/+$/, '') : '')
const defaultBase = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8085'
const runtimeLogBase = typeof window !== 'undefined' ? (window as any).__LOG_API_BASE_URL__ : undefined
const envLogBase =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  (typeof (globalThis as any).__VITE_API_BASE_URL__ !== 'undefined'
    ? ((globalThis as any).__VITE_API_BASE_URL__ as string | undefined)
    : undefined)
const computedBaseURL =
  normalizeBase(envLogBase) ||
  normalizeBase(runtimeLogBase) ||
  normalizeBase(defaultBase)

export const API_BASE_URL = computedBaseURL

// 共享请求拦截器：在每个请求上携带当前激活语言（X-App-Locale），
// 供后端解析 locale。各 axios 实例都应注册此拦截器。
export const localeHeaderInterceptor = <T extends { headers: any }>(config: T): T => {
  config.headers?.set?.(LOCALE_HEADER, getActiveLocale())
  return config
}

// 读取用户登录 token（与 src/api/user.ts 的 userToken 使用相同存储键；
// 这里不直接 import 以避免 index.ts <-> user.ts 循环依赖）
const USER_TOKEN_KEY = 'raven_user_token'
const readUserToken = (): string => {
  try {
    const stored = window.localStorage?.getItem(USER_TOKEN_KEY)
    if (stored) return stored
  } catch {
    // localStorage 不可用时降级到 cookie
  }
  if (typeof document === 'undefined') return ''
  const prefix = `${USER_TOKEN_KEY}=`
  const item = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
  if (!item) return ''
  try {
    return decodeURIComponent(item.slice(prefix.length))
  } catch {
    return item.slice(prefix.length)
  }
}

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
  localeHeaderInterceptor,
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
    project_id?: number
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
  analyzeLog: (
    id: string,
    query: string,
    projectRepoId?: number | null,
  ): Promise<ApiResponse<any>> => {
    const formData = new FormData()
    formData.append('query', query)
    if (projectRepoId !== undefined && projectRepoId !== null) {
      formData.append('project_repo_id', String(projectRepoId))
    }
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

  // 保存人工分析（携带登录态，后端据此记录添加人信息）
  saveManualAnalysis: (id: string, content: string): Promise<ApiResponse<any>> => {
    const headers: Record<string, string> = {}
    const token = readUserToken()
    if (token) headers.Authorization = `Bearer ${token}`
    return api.post(`/api/v1/logs/${id}/manual-analysis`, { content }, { headers })
  },

  // 更新问题描述
  updateIssueDescription: (id: string, issue_description: string | null): Promise<ApiResponse<any>> => {
    return api.put(`/api/v1/logs/${id}/issue-description`, { issue_description })
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

// 项目（只读，供 AI 分析时选择项目使用）
export interface ProjectRepoOption {
  id: number
  project_code: string
  project_name: string
  default_branch: string
  // 是否关联了代码仓库。未关联的项目仅项目专家可见。
  has_repo?: boolean
  enabled_agent_keys?: string[]
  project_card: string
}

export const projectRepoApi = {
  // 列出所有已启用的项目仓库
  listEnabled: (params?: { agent_key?: string }): Promise<ApiResponse<ProjectRepoOption[]>> => {
    return api.get('/api/v1/project-repos', { params })
  },
}

// 健康检查API
export const healthApi = {
  check: (): Promise<ApiResponse> => {
    return api.get('/health')
  },
}

export default api
