import { describe, expect, it } from 'vitest'
import { extractVisualAnalysis, parseAgentMessage } from './agentResultSummary'

describe('parseAgentMessage', () => {
  it('moves the completion preamble out of a specialist answer', () => {
    const view = parseAgentMessage([
      '**项目专家 Agent** 已完成本轮分析。',
      '',
      '- 项目：`RavenAI`',
      '- 问题：为什么启动失败？',
      '- 状态：`ok`',
      '- 模型：`claude-sonnet-4-5`，耗时：12.34s',
      '- 上下文：工作区已保留。',
      '',
      '## 回答',
      '',
      '启动失败是因为配置缺失。',
      '',
      '## 关键词',
      '`config`',
    ].join('\n'))

    expect(view.displayMarkdown).toBe(
      '启动失败是因为配置缺失。\n\n## 关键词\n`config`',
    )
    expect(view.completionSummary).toMatchObject({
      title: '项目专家 Agent',
      model: 'claude-sonnet-4-5',
      duration: '12.34s',
    })
    expect(view.completionSummary?.fields).toContainEqual({
      label: '项目',
      value: 'RavenAI',
    })
  })

  it('leaves ordinary assistant Markdown unchanged', () => {
    const content = '## 回答\n\n普通回复'
    expect(parseAgentMessage(content)).toEqual({
      displayMarkdown: content,
      completionSummary: null,
    })
  })

  it('supports the package-search completion wording', () => {
    const view = parseAgentMessage([
      '**重构包检索 Agent** 已完成本轮检索。',
      '',
      '- 模型：`qwen-max`',
      '',
      '## 回答',
      '找到两个结果。',
    ].join('\n'))
    expect(view.displayMarkdown).toBe('找到两个结果。')
    expect(view.completionSummary?.model).toBe('qwen-max')
    expect(view.completionSummary?.duration).toBeUndefined()
  })
})

describe('extractVisualAnalysis', () => {
  it('recovers the OCR text and image count from persisted user content', () => {
    expect(extractVisualAnalysis([
      '请分析截图',
      '',
      '<user_image_ocr note="素材" image_count="2">',
      '[图片 1]',
      'Error: timeout',
      '</user_image_ocr>',
    ].join('\n'))).toEqual({
      text: '[图片 1]\nError: timeout',
      imageCount: 2,
    })
  })
})
