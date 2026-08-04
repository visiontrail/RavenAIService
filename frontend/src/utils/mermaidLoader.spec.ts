import { afterEach, describe, expect, it } from 'vitest'

import { currentMermaidThemeMode } from '@/utils/mermaidLoader'

/** vitest 跑在 node 环境（无 DOM），按需伪造 <html> 的 classList。 */
function stubDocument(classes: string[] | null): void {
  if (classes === null) {
    delete (globalThis as Record<string, unknown>).document
    return
  }
  ;(globalThis as Record<string, unknown>).document = {
    documentElement: { classList: { contains: (c: string) => classes.includes(c) } },
  }
}

afterEach(() => {
  stubDocument(null)
})

describe('currentMermaidThemeMode', () => {
  it('follows the dark class on <html>', () => {
    stubDocument(['dark'])
    expect(currentMermaidThemeMode()).toBe('dark')
  })

  it('reports light when the dark class is absent', () => {
    stubDocument(['light'])
    expect(currentMermaidThemeMode()).toBe('light')
  })

  it('falls back to light without a document (SSR / tests)', () => {
    stubDocument(null)
    expect(currentMermaidThemeMode()).toBe('light')
  })
})
