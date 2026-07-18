import axios from 'axios'
import { API_BASE_URL, localeHeaderInterceptor } from './index'
import { userToken } from './user'
import type { BugFixTaskDetailResponse, BugFixTaskListResponse } from '@/types'

const bugFixClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
  headers: {
    'Content-Type': 'application/json',
  },
})

bugFixClient.interceptors.request.use((config) => {
  const token = userToken.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return localeHeaderInterceptor(config)
})

bugFixClient.interceptors.response.use(
  (response) => response.data,
  (error) => Promise.reject(error)
)

export const bugFixApi = {
  list: (params: {
    page?: number
    page_size?: number
  } = {}): Promise<BugFixTaskListResponse> =>
    bugFixClient.get('/api/v1/bug-fixes', { params }),

  detail: (id: string): Promise<BugFixTaskDetailResponse> =>
    bugFixClient.get(`/api/v1/bug-fixes/${id}`),

  retry: (id: string): Promise<BugFixTaskDetailResponse> =>
    bugFixClient.post(`/api/v1/bug-fixes/${id}/retry`),
}

export default bugFixApi
