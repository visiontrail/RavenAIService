import axios from 'axios'
import { localeHeaderInterceptor } from '@/api'
import { getActiveLocale, LOCALE_HEADER } from '@/i18n/runtime'
import type {
  ApiResponse,
  PackageAgentSearchResponse,
  PackageAgentTraceEvent,
  RavenPackage,
  RavenPackageList,
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

ravenApi.interceptors.request.use(localeHeaderInterceptor)

export const listRavenPackages = (params: {
  page?: number
  limit?: number
  search?: string
  projectCode?: string
  tags?: string
  version?: string
  isPatch?: string | boolean
}) => ravenApi.get<ApiResponse<RavenPackageList>>('/packages', { params })

export const getRavenPackageDetail = (id: string) =>
  ravenApi.get<ApiResponse<RavenPackage>>(`/packages/${encodeURIComponent(id)}`)

export const deleteRavenPackage = (id: string) =>
  ravenApi.delete<ApiResponse>(`/packages/${encodeURIComponent(id)}`)

export interface AgentSearchOptions {
  sessionId?: string
  projectRepoId?: number
  signal?: AbortSignal
}

/**
 * Non-streaming Claude Agent driven package search. Calls
 * `POST /raven/packages/agent-search` with `stream: false` and returns the
 * decoded JSON body. The response shape matches `PackageAgentSearchResponse`.
 */
export const searchPackagesByAgent = (query: string, opts: AgentSearchOptions = {}) =>
  ravenApi.post<PackageAgentSearchResponse>(
    '/packages/agent-search',
    {
      query,
      session_id: opts.sessionId,
      project_repo_id: opts.projectRepoId,
      stream: false,
    },
    { signal: opts.signal }
  )

export interface AgentSearchStreamHandlers {
  onEvent: (event: PackageAgentTraceEvent) => void
  onError?: (err: Error) => void
  projectRepoId: number
  signal?: AbortSignal
  sessionId?: string
}

/**
 * Open an SSE stream to `POST /raven/packages/agent-search` with
 * `stream: true`. Each parsed event (one `data:` line per `\n\n` boundary)
 * is forwarded to `onEvent`. The promise resolves when the server closes
 * the stream and rejects on transport errors (AbortError is swallowed).
 */
export const streamPackagesAgentSearch = async (
  query: string,
  handlers: AgentSearchStreamHandlers
): Promise<void> => {
  const url = `${ravenApiBase}/packages/agent-search`
  const body = JSON.stringify({
    query,
    session_id: handlers.sessionId,
    project_repo_id: handlers.projectRepoId,
    stream: true,
  })
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    [LOCALE_HEADER]: getActiveLocale(),
  }

  let resp: Response
  try {
    resp = await fetch(url, {
      method: 'POST',
      headers,
      body,
      signal: handlers.signal,
    })
  } catch (err: any) {
    if (err?.name === 'AbortError') return
    throw err
  }
  if (!resp.ok || !resp.body) {
    throw new Error(`agent-search stream failed: HTTP ${resp.status}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const processChunk = (chunk: string) => {
    buffer += chunk
    let remaining = buffer.replace(/\r\n/g, '\n')
    while (true) {
      const idx = remaining.indexOf('\n\n')
      if (idx === -1) break
      const raw = remaining.slice(0, idx)
      remaining = remaining.slice(idx + 2)
      const lines = raw.split('\n')
      const dataLines = lines
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.replace(/^data:\s?/, ''))
      if (dataLines.length === 0) continue
      const payload = dataLines.join('\n').trim()
      if (!payload) continue
      try {
        const parsed = JSON.parse(payload) as PackageAgentTraceEvent
        handlers.onEvent(parsed)
      } catch (err) {
        handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
      }
    }
    buffer = remaining
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (value) processChunk(decoder.decode(value, { stream: !done }))
      if (done) break
    }
    if (buffer.trim()) processChunk('\n\n')
  } catch (err: any) {
    if (err?.name === 'AbortError') return
    handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
    throw err
  }
}

/**
 * 返回直接可下载的链接，避免先在前端拉取完整 Blob 造成等待
 */
export const getRavenPackageDownloadUrl = (id: string) =>
  `${ravenApiBase}/download/${encodeURIComponent(id)}`

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
    if (metadata.projectCode) {
      formData.append('projectCode', metadata.projectCode)
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
