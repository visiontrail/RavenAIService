type Translate = (key: string, values?: Record<string, string | number>) => string

/** Convert only standalone SDK/API failures; never rewrite quoted errors in an answer. */
export function formatAgentErrorMessage(content: string, t: Translate): string {
  const source = content.trim()
  const match = /^(?:Claude Code returned an error result:\s*)?API Error:\s*(\d{3})\b[^\n]*$/i.exec(source)
  if (!match) {
    if (/^Claude Code returned an error result:[^\n]*$/i.test(source)) {
      const turns = /Reached maximum number of turns \((\d+)\)/i.exec(source)
      return turns ? t('agentError.turns', { count: turns[1]! }) : t('agentError.unknown')
    }
    return content
  }
  const status = Number(match[1])
  const reason = status >= 500 ? 'upstream'
    : status === 429 ? 'rateLimit'
    : status === 402 ? 'balance'
    : status === 401 || status === 403 ? 'auth'
    : status === 413 ? 'tooLarge'
    : status === 408 ? 'timeout' : 'rejected'
  const requestId = /\brequest id:\s*([a-zA-Z0-9_-]{1,128})(?=[\s)]|$)/i.exec(source)?.[1]
  const parts = [t(`agentError.${reason}`), t('agentError.status', { status })]
  if (requestId) parts.push(t('agentError.requestId', { requestId }))
  return parts.join('\n\n')
}
