import axios from 'axios'
import { API_BASE_URL, localeHeaderInterceptor } from './index'
import { userToken } from './user'
import type {
  AdminAuthData,
  AdminIdentity,
  AgentSkill,
  AgentSkillAgentInfo,
  ApiResponse,
  MetricsRawEventsData,
  MetricsSystemOverview,
  MetricsUserDetail,
  MetricsUserListData,
  PromptsConfigData,
  ProjectMember,
  ProjectRepo,
  ProjectRepoPayload,
  ProjectSystemPrompt,
  SkillFileContent,
  SkillFileTree,
  TestConnectionResult,
  UserProfile,
} from '@/types'

export interface MetricsTimeRangeParams {
  from?: string
  to?: string
  bucket?: 'hour' | 'day'
  project_repo_id?: number | string
}

const ADMIN_TOKEN_KEY = 'raven_admin_token'

const getStorage = () => {
  if (typeof window === 'undefined') return undefined
  return window.sessionStorage
}

export const adminToken = {
  get(): string {
    const storage = getStorage()
    return storage?.getItem(ADMIN_TOKEN_KEY) || userToken.get()
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
  return localeHeaderInterceptor(config)
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

  me: (): Promise<ApiResponse<AdminIdentity>> => adminClient.get('/admin/auth/me'),

  logout: (): Promise<ApiResponse> => adminClient.post('/admin/auth/logout'),

  fetchPromptsConfig: (): Promise<ApiResponse<PromptsConfigData>> =>
    adminClient.get('/admin/prompts/config'),

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
    role?: 'user' | 'admin'
  }): Promise<ApiResponse<UserProfile>> => adminClient.post('/api/v1/users', payload),

  updateUser: (
    userId: string,
    payload: {
      display_name?: string
      email?: string
      is_active?: boolean
      password?: string
      role?: 'user' | 'admin'
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

  listProjectRepoMembers: (repoId: number): Promise<ApiResponse<ProjectMember[]>> =>
    adminClient.get(`/admin/project-repos/${repoId}/members`),

  addProjectRepoMember: (
    repoId: number,
    userId: string
  ): Promise<ApiResponse<ProjectMember[]>> =>
    adminClient.post(`/admin/project-repos/${repoId}/members`, { user_id: userId }),

  removeProjectRepoMember: (repoId: number, userId: string): Promise<void> =>
    adminClient.delete(`/admin/project-repos/${repoId}/members/${userId}`),

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

  // ==================== 项目级 Skill ====================

  listProjectSkills: (projectCode: string): Promise<ApiResponse<AgentSkill[]>> =>
    adminClient.get(`/admin/project-repos/${projectCode}/skills`),

  uploadProjectSkill: (
    projectCode: string,
    file: File,
    overwrite = false,
    onProgress?: (percent: number) => void
  ): Promise<ApiResponse<AgentSkill>> => {
    const form = new FormData()
    form.append('file', file)
    return adminClient.post(`/admin/project-repos/${projectCode}/skills`, form, {
      params: { overwrite },
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
      onUploadProgress: (e) => {
        if (!onProgress || !e.total) return
        onProgress(Math.round((e.loaded / e.total) * 100))
      },
    })
  },

  updateProjectSkill: (
    projectCode: string,
    skillId: string,
    payload: { enabled: boolean }
  ): Promise<ApiResponse<AgentSkill>> =>
    adminClient.patch(`/admin/project-repos/${projectCode}/skills/${skillId}`, payload),

  deleteProjectSkill: (projectCode: string, skillId: string): Promise<void> =>
    adminClient.delete(`/admin/project-repos/${projectCode}/skills/${skillId}`),

  listProjectSkillFiles: (
    projectCode: string,
    skillId: string
  ): Promise<ApiResponse<SkillFileTree>> =>
    adminClient.get(`/admin/project-repos/${projectCode}/skills/${skillId}/files`),

  readProjectSkillFile: (
    projectCode: string,
    skillId: string,
    path: string
  ): Promise<ApiResponse<SkillFileContent>> =>
    adminClient.get(`/admin/project-repos/${projectCode}/skills/${skillId}/file`, {
      params: { path },
    }),

  // ==================== 项目级系统提示词 ====================

  getProjectSystemPrompt: (
    projectCode: string,
    agent?: string | null
  ): Promise<ApiResponse<ProjectSystemPrompt>> =>
    adminClient.get(`/admin/project-repos/${projectCode}/system-prompt`, {
      params: agent ? { agent } : undefined,
    }),

  updateProjectSystemPrompt: (
    projectCode: string,
    content: string,
    agent?: string | null
  ): Promise<ApiResponse<ProjectSystemPrompt>> =>
    adminClient.put(
      `/admin/project-repos/${projectCode}/system-prompt`,
      { content },
      { params: agent ? { agent } : undefined }
    ),

  // ==================== 系统/用户指标 (Metrics) ====================

  metricsOverview: (
    params?: MetricsTimeRangeParams
  ): Promise<ApiResponse<MetricsSystemOverview>> =>
    adminClient.get('/admin/metrics/overview', { params }),

  metricsUsers: (params?: {
    from?: string
    to?: string
    project_repo_id?: number | string
    page?: number
    per_page?: number
    sort?: string
  }): Promise<ApiResponse<MetricsUserListData>> =>
    adminClient.get('/admin/metrics/users', { params }),

  metricsUserDetail: (
    userId: string,
    params?: MetricsTimeRangeParams
  ): Promise<ApiResponse<MetricsUserDetail>> =>
    adminClient.get(`/admin/metrics/users/${userId}`, { params }),

  metricsEvents: (params?: {
    from?: string
    to?: string
    event_type?: string
    source?: string
    user_id?: string
    project_repo_id?: number | string
    page?: number
    per_page?: number
  }): Promise<ApiResponse<MetricsRawEventsData>> =>
    adminClient.get('/admin/metrics/events', { params }),
}

export default adminApi
