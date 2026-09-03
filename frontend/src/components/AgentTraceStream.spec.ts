import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { describe, expect, it } from 'vitest'

import AgentTraceStream from '@/components/AgentTraceStream.vue'
import { i18n, setI18nLocale } from '@/i18n'
import type { AgentTraceEvent } from '@/types/agentTrace'

describe('AgentTraceStream', () => {
  it('keeps the full available Skill catalog collapsed by default', async () => {
    setI18nLocale('zh')
    const events: AgentTraceEvent[] = [
      {
        type: 'run_start',
        task_id: 'task-1',
        seq: 1,
        timestamp: 1,
        available_skills: [
          'ka-phased-array-antenna',
          'payload-management-unit',
          'tcpt027-db-modify',
        ],
        loaded_skills: ['ka-phased-array-antenna'],
      },
      {
        type: 'step_start',
        task_id: 'task-1',
        seq: 2,
        timestamp: 2,
        step_id: 'skill-1',
        tool_name: 'Skill',
        tool_input: { skill: 'ka-phased-array-antenna' },
      },
    ]
    const app = createSSRApp({
      render: () => h(AgentTraceStream, { events, running: true }),
    })
    app.use(i18n)

    const html = await renderToString(app)
    const detailsTag = html.match(/<details[^>]*agent-trace__available-skills[^>]*>/)?.[0]
    const availableSection = html.match(/<details[^>]*>[\s\S]*?<\/details>/)?.[0] || ''
    const loadedSection = html.match(
      /<div class="agent-trace__skills"[^>]*>[\s\S]*?<\/div>/,
    )?.[0] || ''

    expect(detailsTag).toBeTruthy()
    expect(detailsTag).not.toMatch(/\sopen(?:=|\s|>)/)
    expect(html).toContain('可用 Skills')
    expect(html).toMatch(/agent-trace__available-count"[^>]*>3<\/span>/)
    expect(html).toContain('已加载 Skills')
    expect(availableSection).toContain('ka-phased-array-antenna')
    expect(availableSection).toContain('payload-management-unit')
    expect(availableSection).toContain('tcpt027-db-modify')
    expect(loadedSection).toContain('ka-phased-array-antenna')
    expect(loadedSection).not.toContain('payload-management-unit')
    expect(loadedSection).not.toContain('tcpt027-db-modify')
  })
})
