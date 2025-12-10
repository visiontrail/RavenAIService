import axios from 'axios'
import type {
  ApiResponse,
  RavenPackage,
  RavenPackageList,
  RavenSearchResult,
  RavenSearchStatus,
  RavenUploadMetadata,
} from '@/types'

const defaultHost = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8085'

const normalizeBasePath = (path?: string | null) => {
  if (!path) return '/raven'
  let normalized = path.trim()
  if (!normalized.startsWith('/')) normalized = `/${normalized}`
  normalized = normalized.replace(/\/+$/, '')
  return normalized || '/raven'
}

const envBasePath =
  (import.meta.env.VITE_RAVEN_BASE_PATH as string | undefined) ||
  (typeof window !== 'undefined' ? (window as any).__RAVEN_BASE_PATH__ : undefined) ||
  '/raven'

const ravenBasePath = normalizeBasePath(envBasePath)
const ravenHostRaw = (import.meta.env.VITE_RAVEN_HOST as string | undefined) || defaultHost
const ravenHost = ravenHostRaw.replace(/\/+$/, '')
const ravenBaseUrl = `${ravenHost}${ravenBasePath}`
const apiBaseOverride = (import.meta.env.VITE_RAVEN_API_BASE_URL as string | undefined)?.replace(/\/+$/, '')
const ravenApiBase = apiBaseOverride || `${ravenBaseUrl}/api`

const ravenApi = axios.create({
  baseURL: ravenApiBase,
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const listRavenPackages = (params: {
  page?: number
  limit?: number
  search?: string
  type?: string
  tags?: string
  version?: string
  isPatch?: string | boolean
}) => ravenApi.get<ApiResponse<RavenPackageList>>('/packages', { params })

export const getRavenPackageDetail = (id: string) =>
  ravenApi.get<ApiResponse<RavenPackage>>(`/packages/${encodeURIComponent(id)}`)

export const deleteRavenPackage = (id: string) =>
  ravenApi.delete<ApiResponse>(`/packages/${encodeURIComponent(id)}`)

export const rebuildRavenIndex = () => ravenApi.post<ApiResponse>('/search/rebuild-index')

export const getRavenSearchStatus = () => ravenApi.get<ApiResponse<RavenSearchStatus>>('/search/status')

export const intelligentSearchPackages = (query: string, limit = 5) =>
  ravenApi.post<ApiResponse<RavenSearchResult>>('/search/intelligent', { query, limit })

export const fetchRavenSuggestions = (query: string) =>
  ravenApi.post<ApiResponse<string[]>>('/search/suggestions', { query })

export const downloadRavenPackage = (id: string) =>
  ravenApi.get<Blob>(`/download/${encodeURIComponent(id)}`, {
    responseType: 'blob',
  })

export const uploadRavenPackages = async (
  files: File[],
  metadata?: RavenUploadMetadata,
  onProgress?: (payload: { percent: number; speedText?: string; etaSeconds?: number }) => void,
  signal?: AbortSignal
) => {
  if (!files.length) {
    throw new Error('请先选择要上传的文件')
  }

  const formData = new FormData()
  files.forEach((file) => formData.append('file', file))

  if (metadata) {
    if (metadata.isPatch !== undefined) {
      formData.append('isPatch', String(metadata.isPatch))
    }
    if (metadata.description) {
      formData.append('description', metadata.description)
    }
    if (metadata.packageType) {
      formData.append('packageType', metadata.packageType)
    }
    if (metadata.version) {
      formData.append('version', metadata.version)
    }
    if (metadata.components?.length) {
      formData.append('components', JSON.stringify(metadata.components))
    }
    if (metadata.tags?.length) {
      formData.append('tags', JSON.stringify(metadata.tags))
    }
  }

  const startTime = Date.now()
  let lastLoaded = 0
  let lastTick = startTime

  const endpoint = files.length > 1 ? '/upload/batch' : '/upload'
  const response = await ravenApi.post<ApiResponse>(
    endpoint,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      signal,
      onUploadProgress: (event) => {
        if (!event.total) return
        const percent = Math.round((event.loaded * 100) / event.total)

        const now = Date.now()
        const deltaTime = now - lastTick

        if (deltaTime >= 400 && onProgress) {
          const deltaBytes = event.loaded - lastLoaded
          const speed = deltaBytes / (deltaTime / 1000)
          const remaining = event.total - event.loaded
          const etaSeconds = speed > 0 ? remaining / speed : 0
          onProgress({
            percent,
            speedText: formatSpeed(speed),
            etaSeconds,
          })
          lastLoaded = event.loaded
          lastTick = now
        } else if (onProgress) {
          onProgress({ percent })
        }
      },
    }
  )

  return response.data
}

const formatSpeed = (bytesPerSecond: number) => {
  if (bytesPerSecond < 1024) return `${bytesPerSecond.toFixed(0)} B/s`
  if (bytesPerSecond < 1024 * 1024) return `${(bytesPerSecond / 1024).toFixed(1)} KB/s`
  return `${(bytesPerSecond / (1024 * 1024)).toFixed(1)} MB/s`
}

export { ravenApi, ravenBasePath, ravenBaseUrl, ravenApiBase }
