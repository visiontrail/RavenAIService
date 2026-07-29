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

