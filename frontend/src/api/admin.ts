import axios from 'axios'
import { API_BASE_URL } from './index'
import type {
  AdminAuthData,
  ApiResponse,
  PromptsConfigData,
  ProjectRepo,
  ProjectRepoPayload,
  RepoSettingsData,
  TestConnectionResult,
  UserProfile,
} from '@/types'

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

  listUsers: (): Promise<ApiResponse<UserProfile[]>> => adminClient.get('/api/v1/users'),

  createUser: (payload: {
    username: string
    password: string
    display_name?: string
    email?: string
  }): Promise<ApiResponse<UserProfile>> => adminClient.post('/api/v1/users', payload),

  updateUser: (
    userId: string,
    payload: {
      display_name?: string
      email?: string
      is_active?: boolean
      password?: string
    }
  ): Promise<ApiResponse<UserProfile>> => adminClient.patch(`/api/v1/users/${userId}`, payload),

  disableUser: (userId: string): Promise<ApiResponse<UserProfile>> =>
    adminClient.delete(`/api/v1/users/${userId}`),

  fetchRepoSettings: (): Promise<ApiResponse<RepoSettingsData>> =>
    adminClient.get('/admin/repo-settings'),

  saveRepoSettings: (payload: {
    oam_url?: string | null
    stack_url?: string | null
    git_token?: string | null
    clone_depth?: number
    clear_token?: boolean
  }): Promise<ApiResponse<RepoSettingsData>> =>
    adminClient.put('/admin/repo-settings', payload),

  testRepoConnection: (payload: {
    url: string
    token?: string | null
  }): Promise<ApiResponse<TestConnectionResult>> =>
    adminClient.post('/admin/repo-settings/test-connection', payload),

  listProjectRepos: (params?: {
    include_disabled?: boolean
    offset?: number
    limit?: number
  }): Promise<ApiResponse<ProjectRepo[]>> =>
    adminClient.get('/admin/project-repos', { params }),

  createProjectRepo: (payload: ProjectRepoPayload): Promise<ApiResponse<ProjectRepo>> =>
    adminClient.post('/admin/project-repos', payload),

  updateProjectRepo: (
    repoId: number,
    payload: ProjectRepoPayload
  ): Promise<ApiResponse<ProjectRepo>> =>
    adminClient.put(`/admin/project-repos/${repoId}`, payload),

  deleteProjectRepo: (repoId: number): Promise<void> =>
    adminClient.delete(`/admin/project-repos/${repoId}`),

  testProjectRepoConnection: (repoId: number): Promise<ApiResponse<TestConnectionResult>> =>
    adminClient.post(`/admin/project-repos/${repoId}/test-connection`),
}

export default adminApi
