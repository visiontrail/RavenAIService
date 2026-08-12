import { describe, expect, it } from 'vitest'
import enCatalog from '@/i18n/en'
import zhCatalog from '@/i18n/zh'

import {
  hasPersistedLogAttachmentMarker,
  proceedAfterLogWorkspaceReplacementCheck,
  requiresLogWorkspaceReplacementConfirmation,
  resolveLogWorkspaceReplacementAction,
} from '@/utils/logWorkspaceReplacement'

describe('log workspace replacement helpers', () => {
  it('keeps replacement copy in the AIChat namespace for both locales', () => {
    expect(zhCatalog.aiChat.logWorkspaceReplacement.title).toContain('日志工作区')
    expect(enCatalog.aiChat.logWorkspaceReplacement.title).toContain('log workspace')
  })

  it('recognizes the stable attachment marker persisted by the backend', () => {
    expect(hasPersistedLogAttachmentMarker('请分析\n\n[日志附件] first.zip')).toBe(true)
    expect(hasPersistedLogAttachmentMarker('[日志附件]\nfirst.zip')).toBe(true)
    expect(hasPersistedLogAttachmentMarker('普通日志分析追问')).toBe(false)
    expect(hasPersistedLogAttachmentMarker(null)).toBe(false)
  })

  it.each([
    {
      name: 'first log upload',
      input: { hasExistingLogWorkspace: false, isLogAnalysisRequest: true, logFileCount: 1 },
      expected: false,
    },
    {
      name: 'replacement log upload',
      input: { hasExistingLogWorkspace: true, isLogAnalysisRequest: true, logFileCount: 1 },
      expected: true,
    },
    {
      name: 'log follow-up without a new file',
      input: { hasExistingLogWorkspace: true, isLogAnalysisRequest: true, logFileCount: 0 },
      expected: false,
    },
    {
      name: 'image-only or another agent request',
      input: { hasExistingLogWorkspace: true, isLogAnalysisRequest: false, logFileCount: 0 },
      expected: false,
    },
  ])('$name -> $expected', ({ input, expected }) => {
    expect(requiresLogWorkspaceReplacementConfirmation(input)).toBe(expected)
  })

  it('maps the safe primary action, replacement secondary action and close', () => {
    expect(resolveLogWorkspaceReplacementAction('confirm')).toBe('new-chat')
    expect(resolveLogWorkspaceReplacementAction('cancel')).toBe('replace')
    expect(resolveLogWorkspaceReplacementAction('close')).toBe('stay')
    expect(resolveLogWorkspaceReplacementAction(new Error('dismissed'))).toBe('stay')
  })

  it('continues without opening a prompt for a first upload', async () => {
    let prompted = false
    const proceed = await proceedAfterLogWorkspaceReplacementCheck({
      requiresConfirmation: false,
      requestDecision: async () => {
        prompted = true
        return 'replace'
      },
      startNewConversation: () => undefined,
    })
    expect(proceed).toBe(true)
    expect(prompted).toBe(false)
  })

  it('continues the original send only after explicit replacement consent', async () => {
    const proceed = await proceedAfterLogWorkspaceReplacementCheck({
      requiresConfirmation: true,
      requestDecision: async () => 'replace',
      startNewConversation: () => undefined,
    })
    expect(proceed).toBe(true)
  })

  it('closes without sending or changing conversation', async () => {
    let openedNewChat = false
    const proceed = await proceedAfterLogWorkspaceReplacementCheck({
      requiresConfirmation: true,
      requestDecision: async () => 'stay',
      startNewConversation: () => { openedNewChat = true },
    })
    expect(proceed).toBe(false)
    expect(openedNewChat).toBe(false)
  })

  it('opens a new conversation but prevents automatic sending', async () => {
    let openedNewChat = false
    const proceed = await proceedAfterLogWorkspaceReplacementCheck({
      requiresConfirmation: true,
      requestDecision: async () => 'new-chat',
      startNewConversation: () => { openedNewChat = true },
    })
    expect(proceed).toBe(false)
    expect(openedNewChat).toBe(true)
  })
})
