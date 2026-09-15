import { API_BASE_URL, localeHeaderInterceptor } from './index'
import { adminToken } from './admin'

export interface TemporaryTurn {
  role: 'user' | 'assistant'
  content: string
}

/** Transient SSE transport: no stores, localStorage, session IDs or retry. */
export async function streamAdminFollowUp(
  eventId: string,
  question: string,
  history: TemporaryTurn[],
  signal: AbortSignal,
  onText: (text: string) => void,
): Promise<string> {
  const headers = localeHeaderInterceptor({ headers: new Headers({
    'Content-Type': 'application/json',
    Authorization: `Bearer ${adminToken.get() || ''}`,
  }) }).headers
  const response = await fetch(`${API_BASE_URL}/admin/metrics/events/${encodeURIComponent(eventId)}/conversation/follow-up`, {
    method: 'POST', headers, body: JSON.stringify({ question, history }), signal,
    cache: 'no-store',
  })
  if (!response.ok) {
    if (response.status === 401) adminToken.clear()
    const error = await response.json().catch(() => null)
    throw new Error(typeof error?.detail === 'string' ? error.detail : `HTTP ${response.status}`)
  }
  if (!response.body) throw new Error('Empty response stream')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let text = ''
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replace(/\r\n/g, '\n')
      let end: number
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
        if (!data) continue
        const event = JSON.parse(data)
        if (event.type === 'error') throw new Error(event.message)
        if (event.type === 'delta') {
          text += event.text
          onText(text)
        }
        if (event.type === 'done') {
          onText(event.answer)
          return event.answer
        }
      }
      if (done) throw new Error('Connection ended before the answer completed')
    }
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
