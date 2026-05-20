// useAgentTraceStream — folds an array of AgentTraceEvent into a
// presentation-ready list of step / thinking cards.
//
// Inputs:
//   eventsRef: Ref<AgentTraceEvent[]>  — the raw event stream (append-only;
//     duplicates and out-of-order events are tolerated; we de-dupe by `seq`
//     and re-order on the fly so the view is deterministic).
//
// Outputs:
//   cards:    ordered list of step / thinking views with status
//   running:  true until a terminal event arrives
//   summary:  trace_summary from the terminal event, or a computed
//             fallback when the stream is still running
//   terminal: the terminal event (run_complete | cancelled | error) or null

import { computed, type ComputedRef, type Ref } from 'vue'
import type {
  AgentTraceEvent,
  CancelledEvent,
  ErrorEvent,
  RunCompleteEvent,
  TraceSummary,
} from '@/types/agentTrace'
import { isTerminalEvent } from '@/types/agentTrace'

export type TraceCardKind = 'tool' | 'thinking'
export type TraceCardStatus = 'running' | 'ok' | 'error' | 'cancelled'

export interface TraceCard {
  kind: TraceCardKind
  stepId: string
  status: TraceCardStatus
  // tool cards
  toolName?: string
  toolInput?: Record<string, unknown>
  output: string // streamed concatenation of step_delta.output_chunk
  outputExcerpt?: string // final excerpt set on step_end
  // thinking cards
  thinkingText: string
  // shared metadata
  durationSeconds?: number
  startedAt: number
  endedAt?: number
  startSeq: number
}

export type TerminalTraceEvent = RunCompleteEvent | CancelledEvent | ErrorEvent

export interface AgentTraceStreamView {
  cards: ComputedRef<TraceCard[]>
  running: ComputedRef<boolean>
  summary: ComputedRef<TraceSummary | null>
  terminal: ComputedRef<TerminalTraceEvent | null>
}

const TERMINAL_STATUS_BY_TYPE: Record<TerminalTraceEvent['type'], TraceCardStatus> = {
  run_complete: 'ok',
  cancelled: 'cancelled',
  error: 'error',
}

function normaliseEvents(raw: AgentTraceEvent[]): AgentTraceEvent[] {
  // De-dupe by seq, then sort ascending. We tolerate non-numeric seq
  // defensively, in which case the event is dropped.
  const bySeq = new Map<number, AgentTraceEvent>()
  for (const event of raw) {
    if (!event || typeof event.seq !== 'number') continue
    if (bySeq.has(event.seq)) continue
    bySeq.set(event.seq, event)
  }
  return Array.from(bySeq.values()).sort((a, b) => a.seq - b.seq)
}

function buildCards(events: AgentTraceEvent[]): {
  cards: TraceCard[]
  terminal: TerminalTraceEvent | null
} {
  const cardById = new Map<string, TraceCard>()
  const order: string[] = []
  let terminal: TerminalTraceEvent | null = null

  const ensureCard = (stepId: string, seed: TraceCard): TraceCard => {
    const existing = cardById.get(stepId)
    if (existing) return existing
    cardById.set(stepId, seed)
    order.push(stepId)
    return seed
  }

  for (const event of events) {
    switch (event.type) {
      case 'step_start': {
        ensureCard(event.step_id, {
          kind: 'tool',
          stepId: event.step_id,
          status: 'running',
          toolName: event.tool_name,
          toolInput: event.tool_input,
          output: '',
          thinkingText: '',
          startedAt: event.timestamp,
          startSeq: event.seq,
        })
        break
      }
      case 'step_delta': {
        const card = cardById.get(event.step_id)
        if (!card) {
          // Out-of-order delta with no preceding start — synthesise a
          // placeholder so we don't drop the output text.
          ensureCard(event.step_id, {
            kind: 'tool',
            stepId: event.step_id,
            status: 'running',
            output: event.output_chunk || '',
            thinkingText: '',
            startedAt: event.timestamp,
            startSeq: event.seq,
          })
        } else {
          card.output += event.output_chunk || ''
        }
        break
      }
      case 'step_end': {
        const card = cardById.get(event.step_id)
        const finalStatus: TraceCardStatus =
          event.status === 'error' ? 'error' : 'ok'
        if (!card) {
          ensureCard(event.step_id, {
            kind: 'tool',
            stepId: event.step_id,
            status: finalStatus,
            output: event.output_excerpt || '',
            outputExcerpt: event.output_excerpt,
            thinkingText: '',
            durationSeconds: event.duration_seconds,
            startedAt: event.timestamp,
            endedAt: event.timestamp,
            startSeq: event.seq,
          })
        } else {
          card.status = finalStatus
          card.outputExcerpt = event.output_excerpt
          card.durationSeconds = event.duration_seconds
          card.endedAt = event.timestamp
        }
        break
      }
      case 'thinking_start': {
        ensureCard(event.step_id, {
          kind: 'thinking',
          stepId: event.step_id,
          status: 'running',
          output: '',
          thinkingText: '',
          startedAt: event.timestamp,
          startSeq: event.seq,
        })
        break
      }
      case 'thinking_delta': {
        const card = cardById.get(event.step_id)
        if (!card) {
          ensureCard(event.step_id, {
            kind: 'thinking',
            stepId: event.step_id,
            status: 'running',
            output: '',
            thinkingText: event.text_chunk || '',
            startedAt: event.timestamp,
            startSeq: event.seq,
          })
        } else {
          card.thinkingText += event.text_chunk || ''
        }
        break
      }
      case 'thinking_end': {
        const card = cardById.get(event.step_id)
        if (!card) {
          ensureCard(event.step_id, {
            kind: 'thinking',
            stepId: event.step_id,
            status: 'ok',
            output: '',
            thinkingText: event.text || '',
            durationSeconds: event.duration_seconds,
            startedAt: event.timestamp,
            endedAt: event.timestamp,
            startSeq: event.seq,
          })
        } else {
          card.status = 'ok'
          if (event.text && !card.thinkingText) {
            card.thinkingText = event.text
          }
          card.durationSeconds = event.duration_seconds
          card.endedAt = event.timestamp
        }
        break
      }
      case 'run_complete':
      case 'cancelled':
      case 'error': {
        terminal = event as TerminalTraceEvent
        break
      }
      default:
        // run_start / system_notice: nothing to render directly here.
        break
    }
  }

  if (terminal) {
    // Cards still in `running` when the run ends inherit the terminal
    // status — they were interrupted before their step_end / thinking_end
    // arrived.
    const overlay = TERMINAL_STATUS_BY_TYPE[terminal.type]
    for (const card of cardById.values()) {
      if (card.status === 'running') {
        card.status = overlay
      }
    }
  }

  return { cards: order.map((id) => cardById.get(id)!), terminal }
}

function computeFallbackSummary(
  events: AgentTraceEvent[],
  cards: TraceCard[],
): TraceSummary {
  let thinkingChars = 0
  let toolCalls = 0
  let firstTs = Number.POSITIVE_INFINITY
  let lastTs = Number.NEGATIVE_INFINITY
  for (const event of events) {
    if (typeof event.timestamp === 'number') {
      if (event.timestamp < firstTs) firstTs = event.timestamp
      if (event.timestamp > lastTs) lastTs = event.timestamp
    }
    if (event.type === 'thinking_delta') {
      thinkingChars += (event.text_chunk || '').length
    }
  }
  // If the stream had thinking_end but no deltas, fall back to assembled
  // thinking text length on cards.
  if (thinkingChars === 0) {
    for (const card of cards) {
      if (card.kind === 'thinking') thinkingChars += card.thinkingText.length
    }
  }
  for (const card of cards) {
    if (card.kind === 'tool' && card.status !== 'running') toolCalls += 1
  }
  const duration =
    firstTs !== Number.POSITIVE_INFINITY && lastTs !== Number.NEGATIVE_INFINITY && lastTs > firstTs
      ? Math.round((lastTs - firstTs) * 1000) / 1000
      : 0
  return {
    thought_duration_seconds: duration,
    tool_call_count: toolCalls,
    thinking_chars: thinkingChars,
  }
}

export function useAgentTraceStream(
  eventsRef: Ref<AgentTraceEvent[]>,
): AgentTraceStreamView {
  const normalised = computed(() => normaliseEvents(eventsRef.value || []))
  const built = computed(() => buildCards(normalised.value))

  const cards = computed(() => built.value.cards)
  const terminal = computed<TerminalTraceEvent | null>(() => built.value.terminal)
  const running = computed(() => terminal.value === null)

  const summary = computed<TraceSummary | null>(() => {
    const term = terminal.value
    if (term && term.trace_summary) {
      return term.trace_summary
    }
    if (!term && normalised.value.length === 0) return null
    return computeFallbackSummary(normalised.value, built.value.cards)
  })

  return { cards, running, summary, terminal }
}

// Exported for testing / fixtures.
export { normaliseEvents, buildCards, computeFallbackSummary, isTerminalEvent }
