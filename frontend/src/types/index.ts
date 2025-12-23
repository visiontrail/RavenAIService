// 日志元数据类型
export interface LogMetadata {
  source?: string
  environment?: string
  service_name?: string
  version?: string
  tags?: string[]
  extra_fields?: Record<string, any>
}

// 日志记录类型
export interface LogRecord {
  id: string
  filename: string
  original_filename?: string
  file_size: number
  file_path?: string
  log_type?: 'stack' | 'oam_antenna' | 'full'
  status: 'pending' | 'processing' | 'completed' | 'failed'
  progress?: number
  task_id?: string
  task_name?: string
  task_description?: string
  retry_count?: number
  processing_started_at?: string
  processed_at?: string
  checksum?: string
  mime_type?: string
  log_level?: 'debug' | 'info' | 'warn' | 'error' | 'fatal'
  metadata?: LogMetadata
  error_message?: string
  issue_description?: string
  manual_analysis?: string
  manual_analysis_updated_at?: string
  download_count: number
  download_url?: string
  file_size_human?: string
  ai_analysis_result?: any
  ai_analysis_task_id?: string
  ai_analysis_status?: string
  ai_analysis_progress?: number
  ai_analysis_error?: string
  ai_analysis_query?: string
  ai_analysis_started_at?: string
  ai_analysis_finished_at?: string
  // 兼容旧字段
  upload_time?: string
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

// 分页响应类型（后端统一格式）
export interface PaginationInfo {
  page: number
  per_page: number
  total: number
  pages: number
}

export interface LogListData {
  logs: LogRecord[]
  pagination: PaginationInfo
}

export interface DownloadInfo {
  download_url: string
  filename: string
  file_size: number
  expires_at: string
}

// 设备长链类型
export type DeviceStatus = 'online' | 'offline'

export interface DeviceInfo {
  id: string
  name: string
  host?: string | null
  models: string[]
  capabilities: Record<string, any>
  last_seen?: string | null
  status: DeviceStatus
}

export interface DeviceListResponse {
  devices: DeviceInfo[]
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

// 重构包列表类型
export interface RavenComponent {
  name: string
  version?: string
}

export interface RavenMetadata {
  description?: string
  tags?: string[]
  components?: RavenComponent[]
  sha256?: string
  isPatch?: boolean | string
}

export interface RavenPackage {
  id: string
  name: string
  version?: string
  packageType?: string
  size: number
  createdAt: string
  path?: string
  metadata?: RavenMetadata
}

export interface RavenPagination {
  currentPage: number
  totalPages: number
  totalItems: number
  itemsPerPage: number
}

export interface RavenPackageList {
  packages: RavenPackage[]
  pagination: RavenPagination
}

export interface RavenUploadMetadata {
  isPatch?: boolean
  description?: string
  packageType?: string
  version?: string
  tags?: string[]
  components?: RavenComponent[]
}

export interface RavenSearchStatus {
  initialized: boolean
  vectorStoreExists: boolean
  rebuilding: boolean
  totalPackages: number
}

export interface RavenSearchResult {
  answer: string
  relevantPackages: RavenPackage[]
  query: string
  recommendedPackageIds?: string[]
  searchResultsCount?: number
}

// 管理端
export interface AdminAuthData {
  username: string
  token: string
  expires_at: string
  ttl_minutes: number
}

export interface PromptsSummary {
  log_type_keys: string[]
  has_default_plan: boolean
  has_default_summary: boolean
}

export interface PromptsConfigData {
  path: string
  content: string
  updated_at: string
  size: number
  checksum: string
  summary: PromptsSummary
}

// 用户与会话
export interface UserProfile {
  id: string
  username: string
  display_name?: string | null
  email?: string | null
  is_active: boolean
  last_login_at?: string | null
  created_at: string
  updated_at: string
}

export interface UserAuthPayload {
  token: string
  expires_at: number
  user: UserProfile
}

export interface ChatSessionSummary {
  id: string
  title: string
  last_message_at: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ChatMessageRecord {
  id: string
  session_id: string
  role: 'user' | 'ai' | 'system'
  content: string
  created_at: string
  updated_at: string
}
