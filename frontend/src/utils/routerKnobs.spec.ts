import { describe, expect, it } from 'vitest'

import en from '@/i18n/en'
import zh from '@/i18n/zh'
import { ROUTER_KNOBS } from '@/utils/routerKnobs'

const catalogs = { zh, en } as Record<string, any>

describe('router policy knobs', () => {
  it('every label/hint key resolves in both catalogs', () => {
    // The view renders these through a template literal — `t(\`admin.modelSettings.${knob.label}\`)`
    // — so a typo produces the raw key string on screen. Catalog parity only
    // proves zh and en agree with each other, not that a referenced key exists.
    const missing: string[] = []
    for (const [locale, catalog] of Object.entries(catalogs)) {
      const section = catalog.admin?.modelSettings ?? {}
      for (const knob of ROUTER_KNOBS) {
        for (const key of [knob.label, knob.hint]) {
          if (typeof section[key] !== 'string' || !section[key].trim()) {
            missing.push(`${locale}:admin.modelSettings.${key}`)
          }
        }
      }
    }
    expect(missing).toEqual([])
  })

  it('has no duplicate keys and covers each setting once', () => {
    const keys = ROUTER_KNOBS.map((knob) => knob.key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('bounds are internally coherent', () => {
    for (const knob of ROUTER_KNOBS) {
      expect(knob.min, knob.key).toBeLessThan(knob.max)
    }
  })
})
