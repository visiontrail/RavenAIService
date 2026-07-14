import { afterEach, describe, expect, it } from 'vitest'
import { setI18nLocale } from '@/i18n'
import {
  localizeProjectAgent,
  localizePromptAgent,
  localizePromptFunction,
  localizePromptPreviewLayer,
} from './adminPromptMetadata'

describe('admin prompt metadata localization', () => {
  afterEach(() => setI18nLocale('zh'))

  it('localizes backend prompt metadata using stable keys', () => {
    setI18nLocale('en')

    expect(localizePromptFunction('claude_agent_log_analysis', '日志分析').name)
      .toBe('Log Analysis')
    expect(localizePromptAgent(
      'claude_agent_log_analysis',
      'generic',
      '通用日志分析 Agent',
    ).name).toBe('General Log Analysis Agent')
    expect(localizeProjectAgent('project_expert', '项目专家').name)
      .toBe('Project Expert')
    expect(localizePromptPreviewLayer('base', 'Agent 基础层'))
      .toBe('Agent base layer')
  })

  it('keeps backend metadata as the fallback for unknown entries', () => {
    setI18nLocale('en')

    expect(localizePromptFunction('custom_function', 'Custom Function').name)
      .toBe('Custom Function')
    expect(localizePromptAgent('custom_function', 'custom', 'Custom Agent').name)
      .toBe('Custom Agent')
    expect(localizePromptPreviewLayer('custom', 'Custom layer'))
      .toBe('Custom layer')
  })
})
