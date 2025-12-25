import axios from 'axios'
import { API_BASE_URL } from './index'
import type {
  ApiResponse,
  UserAuthPayload,
  UserProfile,
  ChatSessionSummary,
  ChatMessageRecord,
} from '@/types'

const USER_TOKEN_KEY = 'raven_user_token'

const getStorage = () => {
  if (typeof window === 'undefined') return undefined
  return window.localStorage
}

export const userToken = {
  get(): string {
    const storage = getStorage()
    return storage?.getItem(USER_TOKEN_KEY) || ''
  },
  set(token: string) {
    const storage = getStorage()
    if (storage) storage.setItem(USER_TOKEN_KEY, token)
  },
  clear() {
    const storage = getStorage()
    if (storage) storage.removeItem(USER_TOKEN_KEY)
  },
}

const userClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
})

userClient.interceptors.request.use((config) => {
  const token = userToken.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

userClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error)
)

export const userApi = {
  login: (username: string, password: string): Promise<ApiResponse<UserAuthPayload>> =>
    userClient.post('/api/v1/users/auth/login', { username, password }),

  me: (): Promise<ApiResponse<UserProfile>> => userClient.get('/api/v1/users/auth/me'),

  listSessions: (): Promise<ApiResponse<ChatSessionSummary[]>> =>
    userClient.get('/api/v1/users/chat-sessions'),

  fetchMessages: (sessionId: string): Promise<ApiResponse<ChatMessageRecord[]>> =>
    userClient.get(`/api/v1/users/chat-sessions/${sessionId}/messages`),

  deleteSession: (sessionId: string): Promise<ApiResponse<ChatSessionSummary[]>> =>
    userClient.delete(`/api/v1/users/chat-sessions/${sessionId}`),

  saveMessages: (sessionId: string, userContent: string, aiContent: string, titleHint?: string): Promise<ApiResponse<{ session_id: string }>> =>
    userClient.post(`/api/v1/users/chat-sessions/${sessionId}/messages`, {
      user_content: userContent,
      ai_content: aiContent,
      title_hint: titleHint,
    }),
}

export default userApi
