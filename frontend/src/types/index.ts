// 日志记录类型
export interface LogRecord {
  id: string
  filename: string
  file_size: number
  upload_time: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  task_id?: string
  task_name?: string
  task_description?: string
  download_count: number
  created_at: string
  updated_at: string
}

// API响应类型
export interface ApiResponse<T = any> {
  success: boolean
  data?: T
  message?: string
  error?: string
}

// 分页响应类型
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  size: number
  pages: number
}

// 上传文件类型
export interface UploadFile {
  file: File
  progress: number
  status: 'pending' | 'uploading' | 'success' | 'error'
  error?: string
}

// 路由参数类型
export interface RouteParams {
  id?: string
}

// 通知类型
export interface NotificationOptions {
  title: string
  message?: string
  type: 'success' | 'warning' | 'info' | 'error'
  duration?: number
}