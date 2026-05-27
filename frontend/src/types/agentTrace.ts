// AgentTraceEvent — TypeScript schema mirroring app/agents/log_analysis/trace.py.
//
// All events share `type`, `task_id`, `seq` (monotonic), `timestamp` (epoch
// seconds with 6 decimals). The discriminated union below lets callers
// narrow per event type. Optional fields are common-but-not-required so
// component code should treat missing fields defensively.

export type AgentTraceEventType =
  | 'run_start'
  | 'run_complete'
  | 'cancelled'
  | 'step_start'
  | 'step_delta'
  | 'step_end'
  | 'thinking_start'
  | 'thinking_delta'
  | 'thinking_end'
  | 'system_notice'
  | 'error'

export type StepStatus = 'ok' | 'error'

export interface TraceSummary {
  thought_duration_seconds: number
  tool_call_count: number
  thinking_chars: number
  [key: string]: unknown
}

interface BaseTraceEvent {
  task_id: string
  seq: number
  timestamp: number
}

export interface RunStartEvent extends BaseTraceEvent {
  type: 'run_start'
  model?: string
  provider?: string
  loaded_skills?: string[]
}

export interface RunCompleteEvent extends BaseTraceEvent {
  type: 'run_complete'
  trace_summary?: TraceSummary
  final_text?: string
}

export interface CancelledEvent extends BaseTraceEvent {
  type: 'cancelled'
  trace_summary?: TraceSummary
  message?: string
}

export interface ErrorEvent extends BaseTraceEvent {
  type: 'error'
  trace_summary?: TraceSummary
  error_kind?: string
  message?: string
}

export interface StepStartEvent extends BaseTraceEvent {
  type: 'step_start'
  step_id: string
  tool_name: string
  tool_input?: Record<string, unknown>
}

export interface StepDeltaEvent extends BaseTraceEvent {
  type: 'step_delta'
  step_id: string
  output_chunk: string
}

export interface StepEndEvent extends BaseTraceEvent {
  type: 'step_end'
  step_id: string
  status: StepStatus
  duration_seconds?: number
  output_excerpt?: string
}

export interface ThinkingStartEvent extends BaseTraceEvent {
  type: 'thinking_start'
  step_id: string
}

export interface ThinkingDeltaEvent extends BaseTraceEvent {
  type: 'thinking_delta'
  step_id: string
  text_chunk: string
}

export interface ThinkingEndEvent extends BaseTraceEvent {
  type: 'thinking_end'
  step_id: string
  text?: string
  duration_seconds?: number
}

export interface SystemNoticeEvent extends BaseTraceEvent {
  type: 'system_notice'
  kind?: string
  subtype?: string
  detail?: string
  loaded_skills?: string[]
}

export type AgentTraceEvent =
  | RunStartEvent
  | RunCompleteEvent
  | CancelledEvent
  | ErrorEvent
  | StepStartEvent
  | StepDeltaEvent
  | StepEndEvent
  | ThinkingStartEvent
  | ThinkingDeltaEvent
  | ThinkingEndEvent
  | SystemNoticeEvent

export type TerminalEventType = 'run_complete' | 'cancelled' | 'error'

export function isTerminalEvent(
  event: AgentTraceEvent,
): event is RunCompleteEvent | CancelledEvent | ErrorEvent {
  return (
    event.type === 'run_complete' ||
    event.type === 'cancelled' ||
    event.type === 'error'
  )
}
