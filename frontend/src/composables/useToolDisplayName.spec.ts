import { describe, expect, it } from 'vitest'

import { isLogSearchInput, useToolDisplayName } from '@/composables/useToolDisplayName'
import { i18n } from '@/i18n'

describe('useToolDisplayName', () => {
  it('labels Grep over logs files as log search', () => {
    const { resolve } = useToolDisplayName()

    expect(resolve('Grep', {
      pattern: '[Aa]ntenna|[Uu]pdate|UPDATE_KA',
      path: 'logs/Irun_oam.log',
      output_mode: 'content',
      '-n': true,
    })).toBe(i18n.global.t('tools.LogSearch'))
  })

  it('keeps Grep as code search for repository paths', () => {
    const { resolve } = useToolDisplayName()

    expect(resolve('Grep', {
      pattern: 'Oam_Smc_UpdateResultGetRsp',
      path: 'repo/src/P_OAM_Udp_SMC.c',
      output_mode: 'content',
    })).toBe(i18n.global.t('tools.Grep'))
  })

  it('recognises log path hints from common input keys', () => {
    expect(isLogSearchInput({ file_path: '/tmp/workspace/logs/raven.trace' })).toBe(true)
    expect(isLogSearchInput({ include: ['repo/**/*.ts'] })).toBe(false)
  })

  it('labels project catalog discovery separately from credentialed repo lookup', () => {
    const { resolve } = useToolDisplayName()

    expect(resolve('mcp__project_repo__discover_projects')).toBe(i18n.global.t('tools.ProjectDiscovery'))
    expect(resolve('mcp__project_repo__lookup_project_repo')).toBe(i18n.global.t('tools.ProjectRepo'))
    expect(resolve('mcp__project_repo__clone_project_repo')).toBe(i18n.global.t('tools.ProjectClone'))
  })
})
