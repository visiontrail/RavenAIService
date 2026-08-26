import { describe, expect, it } from 'vitest'
import { formatAnalysisTriggerUser } from './logAnalysisTrigger'

describe('formatAnalysisTriggerUser', () => {
  it('uses the documented identity fallback order', () => {
    expect(formatAnalysisTriggerUser({
      user: {
        id: 'user-1',
        username: 'alice',
        display_name: 'Alice Chen',
        email: 'alice@example.com',
      },
    }, 'Anonymous')).toBe('Alice Chen')

    expect(formatAnalysisTriggerUser({
      user: { id: 'user-1', username: 'alice', display_name: ' ' },
    }, 'Anonymous')).toBe('alice')

    expect(formatAnalysisTriggerUser({
      user: { id: 'user-1', email: 'alice@example.com' },
    }, 'Anonymous')).toBe('alice@example.com')

    expect(formatAnalysisTriggerUser({ user: { id: 'user-1' } }, 'Anonymous'))
      .toBe('user-1')
  })

  it('distinguishes anonymous triggers from unavailable attribution', () => {
    expect(formatAnalysisTriggerUser({ source: 'log_detail', user: {} }, 'Anonymous'))
      .toBe('Anonymous')
    expect(formatAnalysisTriggerUser({ source: 'log_detail' }, 'Anonymous'))
      .toBe('Anonymous')
    expect(formatAnalysisTriggerUser(null, 'Anonymous')).toBe('-')
    expect(formatAnalysisTriggerUser(undefined, 'Anonymous')).toBe('-')
  })
})
