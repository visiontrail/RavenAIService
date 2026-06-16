import axios from 'axios'
import { API_BASE_URL, localeHeaderInterceptor } from './index'
import { userToken } from './user'
import type { ApiResponse, PublicShareSnapshot, ShareInfo } from '@/types'

// Authenticated client for owner-side share management (create / get / revoke).
// Mirrors the userClient pattern: attaches the stored bearer token + locale.
const ownerClient = axios.create({ baseURL: API_BASE_URL, timeout: 20000 })

ownerClient.interceptors.request.use((config) => {
  const token = userToken.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return localeHeaderInterceptor(config)
})

ownerClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
)

// Public client for the unauthenticated read-only page. It MUST NOT send an
// Authorization header so the public surface stays identity-free end to end.
const publicClient = axios.create({ baseURL: API_BASE_URL, timeout: 20000 })

publicClient.interceptors.request.use(localeHeaderInterceptor)

publicClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
)

export const shareApi = {
  // Create a new public share or refresh the session's existing one.
  createOrRefresh: (sessionId: string): Promise<ApiResponse<ShareInfo>> =>
    ownerClient.post(`/api/v1/users/chat-sessions/${sessionId}/share`),

  // Query the current share status for a session (unshared state if none).
  get: (sessionId: string): Promise<ApiResponse<ShareInfo>> =>
    ownerClient.get(`/api/v1/users/chat-sessions/${sessionId}/share`),

  // Revoke the session's active share; the public link 404s immediately.
  revoke: (sessionId: string): Promise<ApiResponse<ShareInfo>> =>
    ownerClient.delete(`/api/v1/users/chat-sessions/${sessionId}/share`),

  // Public, no-auth read of a snapshot by token. Returns the flat snapshot body
  // directly (the response interceptor unwraps `response.data`).
  getPublic: (token: string): Promise<PublicShareSnapshot> =>
    publicClient.get(`/api/v1/share/${encodeURIComponent(token)}`),
}

export default shareApi
