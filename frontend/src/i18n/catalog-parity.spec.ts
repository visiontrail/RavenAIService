/**
 * Catalog parity: zh.ts and en.ts must have exactly the same set of keys.
 *
 * Mirrors the backend `missing_keys()` check in app/i18n/messages.py.
 * Add every new key to BOTH catalogs; this test enforces it.
 */
import { describe, it, expect } from 'vitest'
import zh from './zh'
import en from './en'

type NestedRecord = Record<string, unknown>

function flattenKeys(obj: NestedRecord, prefix = ''): string[] {
  const keys: string[] = []
  for (const [k, v] of Object.entries(obj)) {
    const full = prefix ? `${prefix}.${k}` : k
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      keys.push(...flattenKeys(v as NestedRecord, full))
    } else {
      keys.push(full)
    }
  }
  return keys
}

describe('Frontend catalog parity', () => {
  const zhKeys = new Set(flattenKeys(zh as NestedRecord))
  const enKeys = new Set(flattenKeys(en as NestedRecord))

  it('en.ts contains every key that zh.ts has', () => {
    const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k))
    expect(missingInEn, `Keys in zh but missing in en:\n${missingInEn.join('\n')}`).toHaveLength(0)
  })

  it('zh.ts contains every key that en.ts has', () => {
    const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k))
    expect(missingInZh, `Keys in en but missing in zh:\n${missingInZh.join('\n')}`).toHaveLength(0)
  })

  it('catalogs have identical key counts', () => {
    expect(enKeys.size).toBe(zhKeys.size)
  })
})
