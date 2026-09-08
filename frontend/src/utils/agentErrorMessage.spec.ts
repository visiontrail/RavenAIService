import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zh from '../i18n/zh'
import en from '../i18n/en'
import { formatAgentErrorMessage } from './agentErrorMessage'
const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh, en } })
const failure = 'Claude Code returned an error result: API Error: 500 upstream error: do request failed (request id: 202609080333325463303858268d9d6Yigb6FkS). This is a server-side issue, usually temporary — try again in a moment. If it persists, check your inference gateway (oneapi.yhroot.com). (exit code: 1)'
describe('agent error presentation', () => {
  it('explains the production failure with its diagnostic ID', () => {
    const result = formatAgentErrorMessage(failure, i18n.global.t)
    expect(result).toContain(zh.agentError.upstream)
    expect(result).toContain('HTTP 500')
    expect(result).toContain('202609080333325463303858268d9d6Yigb6FkS')
    expect(result).not.toMatch(/Claude Code|exit code|oneapi|自动重试|超时/)
  })
  it.each([[429, 'rateLimit'], [402, 'balance'], [401, 'auth'], [403, 'auth'], [413, 'tooLarge'], [408, 'timeout'], [400, 'rejected'], [503, 'upstream']])('classifies HTTP %s', (status, key) => {
    expect(formatAgentErrorMessage(`API Error: ${status} details`, i18n.global.t)).toContain(i18n.global.t(`agentError.${key}`))
  })
  it('preserves ordinary answers and quoted diagnostics', () => {
    for (const source of ['Analysis:\n' + failure, '```\n' + failure + '\n```', 'File not found', 'The server reported API Error: 500.']) {
      expect(formatAgentErrorMessage(source, i18n.global.t)).toBe(source)
    }
  })
  it('hides raw details and unsafe request IDs', () => {
    expect(formatAgentErrorMessage('API Error: 500 secret=token (request id: <script>)', i18n.global.t)).not.toMatch(/secret|token|script|请求编号：/)
  })
  it('distinguishes execution limits and unknown SDK failures', () => {
    expect(formatAgentErrorMessage('Claude Code returned an error result: Reached maximum number of turns (150)', i18n.global.t)).toContain('150 轮')
    expect(formatAgentErrorMessage('Claude Code returned an error result: success', i18n.global.t)).toBe(zh.agentError.unknown)
  })
  it('uses the active language for stored errors', () => {
    i18n.global.locale.value = 'en'
    expect(formatAgentErrorMessage(failure, i18n.global.t)).toContain(en.agentError.upstream)
    i18n.global.locale.value = 'zh'
  })
})
