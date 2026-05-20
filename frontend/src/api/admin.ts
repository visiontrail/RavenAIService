import axios from 'axios'
import { API_BASE_URL } from './index'
import type {
  AdminAuthData,
  AgentSkill,
  AgentSkillAgentInfo,
  ApiResponse,
  LightModelSettings,
  PromptsConfigData,
  ProjectRepo,
  ProjectRepoPayload,
  SkillFileContent,
  SkillFileTree,
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

  fetchLightModelSettings: (): Promise<ApiResponse<LightModelSettings>> =>
    adminClient.get('/admin/settings/light-model'),

  updateLightModelSettings: (payload: {
    model_name?: string | null
    base_url?: string | null
    api_key?: string | null
    temperature?: number | null
    clear_api_key?: boolean
  }): Promise<ApiResponse<LightModelSettings>> =>
    adminClient.put('/admin/settings/light-model', payload),

  savePromptsConfig: (payload: {
    content?: string
    prompts?: Array<{ id: string; content: string }>
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

  listSkillAgents: (): Promise<ApiResponse<AgentSkillAgentInfo[]>> =>
    adminClient.get('/admin/agents'),

  listAgentSkills: (agentKey: string): Promise<ApiResponse<AgentSkill[]>> =>
    adminClient.get(`/admin/agents/${agentKey}/skills`),

  uploadAgentSkill: (
    agentKey: string,
    file: File,
    overwrite = false,
    onProgress?: (percent: number) => void
  ): Promise<ApiResponse<AgentSkill>> => {
    const form = new FormData()
    form.append('file', file)
    return adminClient.post(`/admin/agents/${agentKey}/skills`, form, {
      params: { overwrite },
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
      onUploadProgress: (e) => {
        if (!onProgress || !e.total) return
        onProgress(Math.round((e.loaded / e.total) * 100))
      },
    })
  },

  updateAgentSkill: (
    agentKey: string,
    skillId: string,
    payload: { enabled: boolean }
  ): Promise<ApiResponse<AgentSkill>> =>
    adminClient.patch(`/admin/agents/${agentKey}/skills/${skillId}`, payload),

  deleteAgentSkill: (agentKey: string, skillId: string): Promise<void> =>
    adminClient.delete(`/admin/agents/${agentKey}/skills/${skillId}`),

  listSkillFiles: (
    agentKey: string,
    skillId: string
  ): Promise<ApiResponse<SkillFileTree>> =>
    adminClient.get(`/admin/agents/${agentKey}/skills/${skillId}/files`),

  readSkillFile: (
    agentKey: string,
    skillId: string,
    path: string
  ): Promise<ApiResponse<SkillFileContent>> =>
    adminClient.get(`/admin/agents/${agentKey}/skills/${skillId}/file`, {
      params: { path },
    }),
}

export default adminApi
