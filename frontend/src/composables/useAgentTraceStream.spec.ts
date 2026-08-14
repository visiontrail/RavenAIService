import { describe, expect, it } from 'vitest'
import { ref } from 'vue'

import type { AgentTraceEvent } from '@/types/agentTrace'
import {
  buildCards,
  collectLoadedSkills,
  computeFallbackSummary,
  normaliseEvents,
  useAgentTraceStream,
} from '@/composables/useAgentTraceStream'

const TASK_ID = 'test-task'

function stepEvents(
  stepId: string,
  toolName: string,
  startSeq: number,
  startTs: number,
  chunks: string[],
  endStatus: 'ok' | 'error' = 'ok',
): AgentTraceEvent[] {
  const out: AgentTraceEvent[] = [
    {
      type: 'step_start',
      task_id: TASK_ID,
      seq: startSeq,
      timestamp: startTs,
      step_id: stepId,
      tool_name: toolName,
      tool_input: { foo: 'bar' },
    },
  ]
  chunks.forEach((chunk, idx) => {
    out.push({
      type: 'step_delta',
      task_id: TASK_ID,
      seq: startSeq + 1 + idx,
      timestamp: startTs + 0.05 * (idx + 1),
      step_id: stepId,
      output_chunk: chunk,
    })
  })
  out.push({
    type: 'step_end',
    task_id: TASK_ID,
    seq: startSeq + 1 + chunks.length,
    timestamp: startTs + 0.05 * (chunks.length + 1),
    step_id: stepId,
    status: endStatus,
    duration_seconds: 0.05 * (chunks.length + 1),
    output_excerpt: chunks.join(''),
  })
  return out
}

describe('normaliseEvents', () => {
  it('drops duplicate seq values and sorts ascending', () => {
    const e: AgentTraceEvent[] = [
      { type: 'run_start', task_id: TASK_ID, seq: 3, timestamp: 3 },
      { type: 'run_start', task_id: TASK_ID, seq: 1, timestamp: 1 },
      { type: 'run_start', task_id: TASK_ID, seq: 2, timestamp: 2 },
      // duplicate of seq=1; second occurrence must be dropped
      { type: 'run_start', task_id: TASK_ID, seq: 1, timestamp: 99 },
    ]
    const out = normaliseEvents(e)
    expect(out.map((x) => x.seq)).toEqual([1, 2, 3])
    expect(out[0].timestamp).toBe(1)
  })

  it('drops events without a numeric seq', () => {
    const bad = { type: 'run_start', task_id: TASK_ID, timestamp: 1 } as unknown as AgentTraceEvent
    const good: AgentTraceEvent = { type: 'run_start', task_id: TASK_ID, seq: 5, timestamp: 5 }
    expect(normaliseEvents([bad, good])).toEqual([good])
  })
})

describe('collectLoadedSkills', () => {
  it('aggregates run metadata, skills_loaded notices, and historical Skill calls', () => {
    const events: AgentTraceEvent[] = [
      {
        type: 'run_start',
        task_id: TASK_ID,
        seq: 1,
        timestamp: 1,
        loaded_skills: ['full-package-build', 'shared-skill'],
      },
      {
        type: 'system_notice',
        task_id: TASK_ID,
        seq: 2,
        timestamp: 2,
        kind: 'skills_loaded',
        loaded_skills: ['project-override', 'shared-skill'],
      },
      {
        type: 'step_start',
        task_id: TASK_ID,
        seq: 3,
        timestamp: 3,
        step_id: 'skill-call',
        tool_name: 'Skill',
        tool_input: { skill: 'legacy-invoked-skill' },
      },
    ]

    expect(collectLoadedSkills(events)).toEqual([
      'full-package-build',
      'shared-skill',
      'project-override',
      'legacy-invoked-skill',
    ])
  })
})

describe('buildCards — step lifecycle', () => {
  it('accumulates step_delta chunks into card.output and finalises on step_end', () => {
    const events = stepEvents('s1', 'Bash', 1, 0, ['hello ', 'world\n'])
    const { cards, terminal } = buildCards(events)
    expect(cards).toHaveLength(1)
    expect(cards[0]).toMatchObject({
      kind: 'tool',
      stepId: 's1',
      toolName: 'Bash',
      output: 'hello world\n',
      outputExcerpt: 'hello world\n',
      status: 'ok',
    })
    expect(cards[0].durationSeconds).toBeCloseTo(0.15, 5)
    expect(terminal).toBeNull()
  })

  it('marks card as error when step_end.status is error', () => {
    const events = stepEvents('s1', 'Bash', 1, 0, ['oops'], 'error')
    const { cards } = buildCards(events)
    expect(cards[0].status).toBe('error')
  })

  it('synthesises a placeholder when step_delta arrives before step_start (out-of-order)', () => {
    const events: AgentTraceEvent[] = [
      {
        type: 'step_delta',
        task_id: TASK_ID,
        seq: 2,
        timestamp: 0.1,
        step_id: 'late',
        output_chunk: 'orphan',
      },
      {
        type: 'step_start',
        task_id: TASK_ID,
        seq: 1,
        timestamp: 0,
        step_id: 'late',
        tool_name: 'Read',
      },
    ]
    // After normalisation seq 1 (start) precedes seq 2 (delta) so the
    // synthesised-placeholder branch should not actually fire here. Verify
    // we get a clean card.
    const sorted = normaliseEvents(events)
    const { cards } = buildCards(sorted)
    expect(cards).toHaveLength(1)
    expect(cards[0].output).toBe('orphan')
    expect(cards[0].toolName).toBe('Read')
  })

  it('handles a delta with no preceding start (after normalisation) by synthesising a card', () => {
    // Force the orphan path: only a delta is provided, no start at all.
    const events: AgentTraceEvent[] = [
      {
        type: 'step_delta',
        task_id: TASK_ID,
        seq: 1,
        timestamp: 0,
        step_id: 'orphan',
        output_chunk: 'lonely',
      },
    ]
    const { cards } = buildCards(events)
    expect(cards).toHaveLength(1)
    expect(cards[0]).toMatchObject({
      stepId: 'orphan',
      output: 'lonely',
      status: 'running',
    })
  })
})

describe('buildCards — thinking lifecycle', () => {
  it('accumulates thinking_delta chunks and finalises on thinking_end', () => {
    const events: AgentTraceEvent[] = [
      { type: 'thinking_start', task_id: TASK_ID, seq: 1, timestamp: 0, step_id: 't1' },
      {
        type: 'thinking_delta',
        task_id: TASK_ID,
        seq: 2,
        timestamp: 0.1,
        step_id: 't1',
        text_chunk: 'first ',
      },
      {
        type: 'thinking_delta',
        task_id: TASK_ID,
        seq: 3,
        timestamp: 0.2,
        step_id: 't1',
        text_chunk: 'second',
      },
      {
        type: 'thinking_end',
        task_id: TASK_ID,
        seq: 4,
        timestamp: 0.3,
        step_id: 't1',
        duration_seconds: 0.3,
      },
    ]
    const { cards } = buildCards(events)
    expect(cards).toHaveLength(1)
    expect(cards[0]).toMatchObject({
      kind: 'thinking',
      thinkingText: 'first second',
      status: 'ok',
      durationSeconds: 0.3,
    })
  })

  it('thinking_end populates thinkingText when no deltas were observed', () => {
    const events: AgentTraceEvent[] = [
      {
        type: 'thinking_end',
        task_id: TASK_ID,
        seq: 1,
        timestamp: 0,
        step_id: 't1',
        text: 'full thought',
        duration_seconds: 0.1,
      },
    ]
    const { cards } = buildCards(events)
    expect(cards[0].thinkingText).toBe('full thought')
    expect(cards[0].status).toBe('ok')
  })
})

describe('buildCards — terminal events', () => {
  it('returns a terminal event when run_complete is present', () => {
    const events: AgentTraceEvent[] = [
      { type: 'run_start', task_id: TASK_ID, seq: 1, timestamp: 0 },
      {
        type: 'run_complete',
        task_id: TASK_ID,
        seq: 2,
        timestamp: 1,
        trace_summary: { thought_duration_seconds: 1, tool_call_count: 0, thinking_chars: 0 },
      },
    ]
    const { terminal } = buildCards(events)
    expect(terminal?.type).toBe('run_complete')
  })

  it('overlays cancelled status on running cards when cancelled event arrives', () => {
    const events: AgentTraceEvent[] = [
      {
        type: 'step_start',
        task_id: TASK_ID,
        seq: 1,
        timestamp: 0,
        step_id: 's1',
        tool_name: 'Bash',
      },
      // no step_end — interrupted
      { type: 'cancelled', task_id: TASK_ID, seq: 2, timestamp: 1, message: 'aborted' },
    ]
    const { cards, terminal } = buildCards(events)
    expect(terminal?.type).toBe('cancelled')
    expect(cards[0].status).toBe('cancelled')
  })

  it('overlays error status on running cards when error event arrives', () => {
    const events: AgentTraceEvent[] = [
      { type: 'thinking_start', task_id: TASK_ID, seq: 1, timestamp: 0, step_id: 't1' },
      { type: 'error', task_id: TASK_ID, seq: 2, timestamp: 0.5, message: 'boom' },
    ]
    const { cards, terminal } = buildCards(events)
    expect(terminal?.type).toBe('error')
    expect(cards[0].status).toBe('error')
  })

  it('does not overlay cards that already finished cleanly', () => {
    const stepOk = stepEvents('s1', 'Read', 1, 0, ['done'], 'ok')
    const stepRunning: AgentTraceEvent = {
      type: 'step_start',
      task_id: TASK_ID,
      seq: 100,
      timestamp: 0.5,
      step_id: 's2',
      tool_name: 'Bash',
    }
    const cancelled: AgentTraceEvent = {
      type: 'cancelled',
      task_id: TASK_ID,
      seq: 101,
      timestamp: 0.6,
      message: 'aborted',
    }
    const { cards } = buildCards([...stepOk, stepRunning, cancelled])
    const s1 = cards.find((c) => c.stepId === 's1')!
    const s2 = cards.find((c) => c.stepId === 's2')!
    expect(s1.status).toBe('ok')
    expect(s2.status).toBe('cancelled')
  })
})

describe('computeFallbackSummary', () => {
  it('counts completed tool calls and accumulates thinking chars from deltas', () => {
    const events: AgentTraceEvent[] = [
      ...stepEvents('s1', 'Bash', 1, 0, ['x']),
      {
        type: 'thinking_delta',
        task_id: TASK_ID,
        seq: 50,
        timestamp: 0.5,
        step_id: 't1',
        text_chunk: 'abcde',
      },
    ]
    const { cards } = buildCards(events)
    const summary = computeFallbackSummary(events, cards)
    expect(summary.tool_call_count).toBe(1)
    expect(summary.thinking_chars).toBe(5)
    expect(summary.thought_duration_seconds).toBeGreaterThan(0)
  })

  it('only counts non-running tool cards in tool_call_count', () => {
    const events: AgentTraceEvent[] = [
      {
        type: 'step_start',
        task_id: TASK_ID,
        seq: 1,
        timestamp: 0,
        step_id: 's1',
        tool_name: 'Bash',
      },
    ]
    const { cards } = buildCards(events)
    expect(computeFallbackSummary(events, cards).tool_call_count).toBe(0)
  })

  it('falls back to assembled thinking text length when no deltas were observed', () => {
    const events: AgentTraceEvent[] = [
      {
        type: 'thinking_end',
        task_id: TASK_ID,
        seq: 1,
        timestamp: 0,
        step_id: 't1',
        text: 'hello',
      },
    ]
    const { cards } = buildCards(events)
    expect(computeFallbackSummary(events, cards).thinking_chars).toBe(5)
  })
})

describe('useAgentTraceStream — reactive composable', () => {
  it('exposes running=true with no terminal event and switches to false once run_complete arrives', () => {
    const events = ref<AgentTraceEvent[]>([
      { type: 'run_start', task_id: TASK_ID, seq: 1, timestamp: 0 },
    ])
    const view = useAgentTraceStream(events)
    expect(view.running.value).toBe(true)
    expect(view.terminal.value).toBeNull()

    events.value = [
      ...events.value,
      {
        type: 'run_complete',
        task_id: TASK_ID,
        seq: 2,
        timestamp: 1,
        trace_summary: { thought_duration_seconds: 1, tool_call_count: 0, thinking_chars: 0 },
      },
    ]
    expect(view.running.value).toBe(false)
    expect(view.terminal.value?.type).toBe('run_complete')
  })

  it('prefers terminal trace_summary over the computed fallback', () => {
    const supplied = { thought_duration_seconds: 42, tool_call_count: 7, thinking_chars: 13 }
    const events = ref<AgentTraceEvent[]>([
      ...stepEvents('s1', 'Read', 1, 0, ['x']),
      {
        type: 'run_complete',
        task_id: TASK_ID,
        seq: 50,
        timestamp: 1,
        trace_summary: supplied,
      },
    ])
    const view = useAgentTraceStream(events)
    expect(view.summary.value).toEqual(supplied)
  })

  it('falls back to a computed summary when terminal omits trace_summary', () => {
    const events = ref<AgentTraceEvent[]>([
      ...stepEvents('s1', 'Read', 1, 0, ['x']),
      { type: 'cancelled', task_id: TASK_ID, seq: 50, timestamp: 1 },
    ])
    const view = useAgentTraceStream(events)
    const summary = view.summary.value
    expect(summary).not.toBeNull()
    expect(summary!.tool_call_count).toBe(1)
  })

  it('returns a summary while still running (no terminal yet) using fallback', () => {
    const events = ref<AgentTraceEvent[]>(stepEvents('s1', 'Read', 1, 0, ['x']))
    const view = useAgentTraceStream(events)
    expect(view.running.value).toBe(true)
    expect(view.summary.value?.tool_call_count).toBe(1)
  })

  it('dedupes out-of-order duplicate seq events', () => {
    const events = ref<AgentTraceEvent[]>([
      {
        type: 'step_start',
        task_id: TASK_ID,
        seq: 2,
        timestamp: 0.1,
        step_id: 's1',
        tool_name: 'Bash',
      },
      // arrives later but lower seq
      { type: 'run_start', task_id: TASK_ID, seq: 1, timestamp: 0 },
      // duplicate seq=2 — must be ignored
      {
        type: 'step_start',
        task_id: TASK_ID,
        seq: 2,
        timestamp: 999,
        step_id: 's1',
        tool_name: 'Grep',
      },
    ])
    const view = useAgentTraceStream(events)
    expect(view.cards.value).toHaveLength(1)
    // The first seq=2 wins; the duplicate is dropped.
    expect(view.cards.value[0].toolName).toBe('Bash')
  })
})
