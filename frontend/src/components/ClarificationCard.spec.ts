import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'

import ClarificationCard from '@/components/ClarificationCard.vue'
import { i18n, setI18nLocale } from '@/i18n'
import type { PendingClarification } from '@/types/agentTrace'

const pendingWithQuestions = (count: number): PendingClarification => ({
  request_id: 'package-confirmation',
  questions: Array.from({ length: count }, (_, index) => ({
    header: `file-${index + 1}`,
    question: `Map component-${index + 1}.bin`,
    options: [{ label: `component-${index + 1}` }, { label: 'exclude' }],
  })),
  draftSelected: Array.from({ length: count }, () => []),
  draftCustom: Array.from({ length: count }, () => ''),
})

describe('ClarificationCard', () => {
  it('renders all thirteen required mapping questions in a labelled scroll region', async () => {
    setI18nLocale('en')
    const app = createSSRApp({
      render: () => h(ClarificationCard, { pending: pendingWithQuestions(13) }),
    })
    app.use(i18n)

    const html = await renderToString(app)
    expect(html.match(/class="rw-clarify-q"/g)).toHaveLength(13)
    expect(html).toContain('aria-label="13 confirmation questions"')
    expect(html).toContain('tabindex="0"')
  })

  it('keeps the question region vertically scrollable within the viewport', () => {
    const source = readFileSync(
      fileURLToPath(new URL('./ClarificationCard.vue', import.meta.url)),
      'utf8',
    )
    expect(source).toMatch(/\.rw-clarify\s*\{[\s\S]*?max-height:\s*calc\(100vh - 32px\)/)
    expect(source).toMatch(/\.rw-clarify-body\s*\{[\s\S]*?overflow-y:\s*auto/)
  })
})
