import axios from 'axios'
import { API_BASE_URL, localeHeaderInterceptor } from './index'
import { adminToken } from './admin'
import type { ApiResponse, ReleaseItem } from '@/types'

const publicClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
})

publicClient.interceptors.request.use(localeHeaderInterceptor)

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
  return localeHeaderInterceptor(config)
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

  upload: async (payload: {
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
    const requestConfig = {
      headers: { 'Content-Type': 'multipart/form-data' },
    }

    const uploadRequest = (url: string): Promise<ApiResponse<ReleaseItem>> =>
      adminClient.post(url, formData, requestConfig) as Promise<ApiResponse<ReleaseItem>>

    try {
      return await uploadRequest('/admin/releases/upload')
    } catch (error: any) {
      // 兼容后端仅暴露 POST /admin/releases 的场景
      if (error?.response?.status === 405) {
        return uploadRequest('/admin/releases')
      }
      throw error
    }
  },

  remove: (releaseId: string): Promise<ApiResponse> =>
    adminClient.delete(`/admin/releases/${releaseId}`),
}
