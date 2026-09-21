import { describe, expect, it } from 'vitest'
import { highlightSearchText, searchDateGroup } from './conversationSearch'

describe('search presentation', () => {
  it('matches literal characters without interpreting HTML or regular expressions', () => {
    const text = '<img onerror=alert(1)> 100%_[x] 100%_[x] 中文'
    const parts = highlightSearchText(text, '100%_[x]')
    expect(parts.filter(p => p.match).map(p => p.text)).toEqual(['100%_[x]', '100%_[x]'])
    expect(parts.map(p => p.text).join('')).toBe(text)
    expect(highlightSearchText('DoCkEr docker', 'DOCKER').filter(p => p.match)).toHaveLength(2)
    expect(highlightSearchText('遥测 中文', '中文').slice(-1)[0]).toEqual({ text: '中文', match: true })
  })
  it('groups history at local day boundaries', () => {
    const now = new Date(2026, 8, 21, 14)
    expect(searchDateGroup(new Date(2026, 8, 21, 1).toISOString(), now)).toBe('today')
    expect(searchDateGroup(new Date(2026, 8, 20, 1).toISOString(), now)).toBe('yesterday')
    expect(searchDateGroup(new Date(2026, 8, 17, 1).toISOString(), now)).toBe('thisWeek')
    expect(searchDateGroup('2020-01-01T00:00:00', now)).toBe('earlier')
  })
})
