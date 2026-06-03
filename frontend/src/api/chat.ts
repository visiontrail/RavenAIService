import axios from 'axios'
import { API_BASE_URL, localeHeaderInterceptor } from '@/api'

export type ChatPermissionDecision = 'allow' | 'deny'

export interface ChatPermissionResolvePayload {
  decision: ChatPermissionDecision
  updated_args?: Record<string, unknown> | null
  message?: string | null
  session_id?: string | null
  run_id?: string | null
}

export interface ChatPermissionResolveResponse {
  success: boolean
  message: string
  request_id: string
  decision: ChatPermissionDecision
}

export interface ToolPermissionRequestEvent {
  event: 'tool_permission_request'
  request_id: string
  tool_name: string
  tool_input?: Record<string, unknown>
  risk: 'read' | 'write' | 'destructive'
  rationale?: string
  session_id?: string
  run_id?: string
  seq?: number
  ts?: string
}

export interface ToolPermissionResolvedEvent {
  event: 'tool_permission_resolved'
  request_id: string
  decision: ChatPermissionDecision
  reason?: string | null
  updated_args?: Record<string, unknown> | null
  message?: string | null
  session_id?: string
  run_id?: string
  seq?: number
  ts?: string
}

export interface ResultValidationEvent {
  event: 'result_validation'
  status: 'ok' | 'schema_mismatch' | 'result_too_large' | string
  reason?: string | null
  tool_name?: string
  session_id?: string
  seq?: number
  ts?: string
}

export interface ProjectExpertStreamPayload {
  message: string
  sessionId: string
  history?: { role: string; content: string }[]
  remember?: boolean
  projectRepoId: number
  authToken?: string | null
  signal?: AbortSignal
}

export interface ProjectExpertCancelResponse {
  session_id: string
  cancelled: boolean
  message?: string
}

export interface ProjectExpertResultResponse {
  session_id: string
  status: string
  answer?: string | null
  result?: Record<string, unknown> | null
}

const getChatServiceUrl = (path: string) => {
  if (API_BASE_URL && /^https?:\/\//i.test(API_BASE_URL)) {
    return `${API_BASE_URL.replace(/\/$/, '')}${path}`
  }
  if (typeof window !== 'undefined') {
    return `http://${window.location.hostname}:8085${path}`
  }
  return path
}

const chatApi = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

chatApi.interceptors.request.use(localeHeaderInterceptor)

/**
 * Submit the user's HITL decision for a DeviceAgent tool-permission request.
 * Backend route: POST /api/v1/ai-chat/chat/permissions/{request_id}/resolve
 *
 * Returns 200 on resolved, 404 if the request_id has already been resolved,
 * timed out, or never existed. Network/HTTP errors propagate to the caller.
 */
export const resolveChatPermission = (
  requestId: string,
  payload: ChatPermissionResolvePayload,
  authToken?: string | null,
): Promise<ChatPermissionResolveResponse> => {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  return chatApi.post(
    `/api/v1/ai-chat/chat/permissions/${encodeURIComponent(requestId)}/resolve`,
    payload,
    { headers },
  ).then((resp) => resp.data as ChatPermissionResolveResponse)
}

export const projectExpertStream = (payload: ProjectExpertStreamPayload): Promise<Response> => {
  const formData = new FormData()
  formData.append('message', payload.message || '')
  formData.append('session_id', payload.sessionId)
  formData.append('remember', String(payload.remember ?? true))
  formData.append('project_repo_id', String(payload.projectRepoId))
  if (payload.history) formData.append('history', JSON.stringify(payload.history))

  const headers: Record<string, string> = {}
  if (payload.authToken) headers.Authorization = `Bearer ${payload.authToken}`

  return fetch(getChatServiceUrl('/api/v1/ai-chat/project-expert/stream'), {
    method: 'POST',
    headers,
    body: formData,
    credentials: 'include',
    signal: payload.signal,
  })
}

export const projectExpertCancel = (
  sessionId: string,
  authToken?: string | null,
): Promise<ProjectExpertCancelResponse> => {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  return fetch(getChatServiceUrl('/api/v1/ai-chat/project-expert/cancel'), {
    method: 'POST',
    headers,
    body: JSON.stringify({ session_id: sessionId }),
    credentials: 'include',
  }).then((resp) => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    return resp.json() as Promise<ProjectExpertCancelResponse>
  })
}

export const projectExpertResult = (
  sessionId: string,
  authToken?: string | null,
): Promise<ProjectExpertResultResponse> => {
  const headers: Record<string, string> = {}
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  return fetch(
    getChatServiceUrl(`/api/v1/ai-chat/project-expert/result?session_id=${encodeURIComponent(sessionId)}`),
    { headers, credentials: 'include' },
  ).then((resp) => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    return resp.json() as Promise<ProjectExpertResultResponse>
  })
}
