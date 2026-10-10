import { afterEach, describe, expect, it, vi } from 'vitest'
import type { InternalAxiosRequestConfig } from 'axios'
import api, { logApi } from '@/api'

const originalAdapter = api.defaults.adapter

describe('authenticated log analysis Fork', () => {
  afterEach(() => {
    api.defaults.adapter = originalAdapter
    vi.unstubAllGlobals()
  })

  it.each(['localStorage', 'cookie'])('carries the current user token from %s', async (storage) => {
    vi.stubGlobal('window', {
      localStorage: { getItem: () => storage === 'localStorage' ? 'reader-token' : null },
    })
    vi.stubGlobal('document', { cookie: 'raven_user_token=reader-token' })
    let sent: InternalAxiosRequestConfig | undefined
    api.defaults.adapter = async (config) => {
      sent = config
      return { data: { success: true, data: { id: 'new-owned-session' } }, status: 201, statusText: 'Created', headers: {}, config }
    }
    const result = await logApi.forkAnalysis('source-log')
    expect(sent?.headers.get('Authorization')).toBe('Bearer reader-token')
    expect(sent?.url).toBe('/api/v1/logs/source-log/analysis/fork')
    expect(result.data?.id).toBe('new-owned-session')
  })
})
