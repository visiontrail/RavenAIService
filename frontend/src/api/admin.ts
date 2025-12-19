import axios from 'axios'
import { API_BASE_URL } from './index'
import type { AdminAuthData, ApiResponse, PromptsConfigData } from '@/types'

const ADMIN_TOKEN_KEY = 'raven_admin_token'

const getStorage = () => {
  if (typeof window === 'undefined') return undefined
  return window.sessionStorage
}

export const adminToken = {
  get(): string {
    const storage = getStorage()
    return storage?.getItem(ADMIN_TOKEN_KEY) || ''
  },
  set(token: string) {
    const storage = getStorage()
    if (storage) storage.setItem(ADMIN_TOKEN_KEY, token)
  },
  clear() {
    const storage = getStorage()
    if (storage) storage.removeItem(ADMIN_TOKEN_KEY)
  },
}

const adminClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
  headers: {
    'Content-Type': 'application/json',
  },
})

adminClient.interceptors.request.use((config) => {
  const token = adminToken.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

adminClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error?.response?.status === 401) {
      adminToken.clear()
    }
    return Promise.reject(error)
  }
)

export const adminApi = {
  login: (username: string, password: string): Promise<ApiResponse<AdminAuthData>> =>
    adminClient.post('/admin/auth/login', { username, password }),

  me: (): Promise<ApiResponse<{ username: string }>> => adminClient.get('/admin/auth/me'),

  logout: (): Promise<ApiResponse> => adminClient.post('/admin/auth/logout'),

  fetchPromptsConfig: (): Promise<ApiResponse<PromptsConfigData>> =>
    adminClient.get('/admin/prompts/config'),

  savePromptsConfig: (payload: {
    content: string
    expected_checksum?: string
    force?: boolean
  }): Promise<ApiResponse<PromptsConfigData>> => adminClient.put('/admin/prompts/config', payload),
}

export default adminApi
