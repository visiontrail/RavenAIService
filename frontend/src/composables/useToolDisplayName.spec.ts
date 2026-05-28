import { describe, expect, it } from 'vitest'

import { isLogSearchInput, useToolDisplayName } from '@/composables/useToolDisplayName'

describe('useToolDisplayName', () => {
  it('labels Grep over logs files as log search', () => {
    const { resolve } = useToolDisplayName()

    expect(resolve('Grep', {
      pattern: '[Aa]ntenna|[Uu]pdate|UPDATE_KA',
      path: 'logs/Irun_oam.log',
      output_mode: 'content',
      '-n': true,
    })).toBe('日志搜索')
  })

  it('keeps Grep as code search for repository paths', () => {
    const { resolve } = useToolDisplayName()

    expect(resolve('Grep', {
      pattern: 'Oam_Smc_UpdateResultGetRsp',
      path: 'repo/src/P_OAM_Udp_SMC.c',
      output_mode: 'content',
    })).toBe('代码搜索')
  })

  it('recognises log path hints from common input keys', () => {
    expect(isLogSearchInput({ file_path: '/tmp/workspace/logs/raven.trace' })).toBe(true)
    expect(isLogSearchInput({ include: ['repo/**/*.ts'] })).toBe(false)
  })
})
