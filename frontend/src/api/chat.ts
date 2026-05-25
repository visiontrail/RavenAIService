import axios from 'axios'
import { API_BASE_URL } from '@/api'

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

const chatApi = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

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
