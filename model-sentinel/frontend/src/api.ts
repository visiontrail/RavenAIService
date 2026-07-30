async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    const message = Array.isArray(detail)
      ? detail.map((item: any) => item.msg).join('；')
      : detail || payload?.message || `请求失败（HTTP ${response.status}）`
    throw new Error(message)
  }
  return payload as T
}

export const api = {
  dashboard: (range: string, granularity: string) =>
    request<any>(`/api/dashboard?range=${range}&granularity=${granularity}`),
  probes: (params: {
    page: number
    page_size: number
    status: string
    source: string
    range: string
  }) => request<any>(`/api/probes?${new URLSearchParams(params as any).toString()}`),
  purgeProbes: () =>
    request<any>('/api/probes?confirm=true', {
      method: 'DELETE',
    }),
  settings: () => request<any>('/api/settings'),
  saveSettings: (data: unknown) =>
    request<any>('/api/settings', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  testSettings: (data: unknown) =>
    request<any>('/api/settings/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  runProbe: () =>
    request<any>('/api/probes/run', {
      method: 'POST',
    }),
}

