import axios from 'axios'
import { API_BASE_URL } from './index'
import { adminToken } from './admin'
import type { ApiResponse, ReleaseItem } from '@/types'

const publicClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
})

publicClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error),
)

const adminClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 300000,
})

adminClient.interceptors.request.use((config) => {
  const token = adminToken.get()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

adminClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error?.response?.status === 401) adminToken.clear()
    return Promise.reject(error)
  },
)

export interface ReleaseListResponse extends ApiResponse<ReleaseItem[]> {}

export const releasesPublicApi = {
  list: (): Promise<ReleaseListResponse> => publicClient.get('/api/v1/releases'),

  getDownloadUrl: (releaseId: string): string =>
    `${API_BASE_URL}/api/v1/releases/${releaseId}/download`,
}

export const releasesAdminApi = {
  list: (): Promise<ReleaseListResponse> => adminClient.get('/admin/releases'),

  upload: (payload: {
    platform: string
    version: string
    description?: string
    file: File
  }): Promise<ApiResponse<ReleaseItem>> => {
    const formData = new FormData()
    formData.append('platform', payload.platform)
    formData.append('version', payload.version)
    formData.append('description', payload.description || '')
    formData.append('file', payload.file)
    return adminClient.post('/admin/releases/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  remove: (releaseId: string): Promise<ApiResponse> =>
    adminClient.delete(`/admin/releases/${releaseId}`),
}
