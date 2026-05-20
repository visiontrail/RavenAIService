// Hand-crafted AgentTraceEvent sequences for visual / manual testing of
// <AgentTraceStream>. Each fixture is a list ready to be `ref()`-ed and
// passed to the component.

import type { AgentTraceEvent } from '@/types/agentTrace'

const TASK_ID = 'fixture-task'
let nextSeq = 0
function seq(): number {
  nextSeq += 1
  return nextSeq
}
function ts(offset: number): number {
  return 1_700_000_000 + offset
}

function resetSeq() {
  nextSeq = 0
}

function step(stepId: string, tool: string, input: Record<string, unknown>, offset: number): AgentTraceEvent[] {
  return [
    {
      type: 'step_start',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(offset),
      step_id: stepId,
      tool_name: tool,
      tool_input: input,
    },
    {
      type: 'step_delta',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(offset + 0.1),
      step_id: stepId,
      output_chunk: '正在执行…\n',
    },
    {
      type: 'step_delta',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(offset + 0.3),
      step_id: stepId,
      output_chunk: '已读取 12 行。\n',
    },
    {
      type: 'step_end',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(offset + 0.5),
      step_id: stepId,
      status: 'ok',
      duration_seconds: 0.5,
      output_excerpt: '正在执行…\n已读取 12 行。\n',
    },
  ]
}

function thinking(stepId: string, text: string, offset: number): AgentTraceEvent[] {
  return [
    {
      type: 'thinking_start',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(offset),
      step_id: stepId,
    },
    {
      type: 'thinking_delta',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(offset + 0.05),
      step_id: stepId,
      text_chunk: text,
    },
    {
      type: 'thinking_end',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(offset + 0.2),
      step_id: stepId,
      text,
      duration_seconds: 0.2,
    },
  ]
}

function build(builder: () => AgentTraceEvent[]): AgentTraceEvent[] {
  resetSeq()
  return builder()
}

// --- normal: 1 thinking + 2 tool calls + run_complete -----------------------
export const normalFixture: AgentTraceEvent[] = build(() => [
  {
    type: 'run_start',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0),
    model: 'claude-opus-4-7',
    provider: 'anthropic',
  },
  ...thinking('think-1', '先看一下日志结构再决定怎么切片。', 0.1),
  ...step('step-1', 'Read', { file_path: '/tmp/log.txt' }, 0.5),
  ...step('step-2', 'Bash', { command: 'grep ERROR /tmp/log.txt | head -n 5' }, 1.2),
  {
    type: 'run_complete',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(2.0),
    trace_summary: {
      thought_duration_seconds: 2.0,
      tool_call_count: 2,
      thinking_chars: 18,
    },
    final_text: '日志显示反复出现 ERROR 行；建议检查上游服务。',
  },
])

// --- cancelled: 1 tool ok + 1 tool interrupted ------------------------------
export const cancelledFixture: AgentTraceEvent[] = build(() => [
  {
    type: 'run_start',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0),
  },
  ...step('step-1', 'Read', { file_path: '/tmp/log.txt' }, 0.1),
  {
    type: 'step_start',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0.8),
    step_id: 'step-2',
    tool_name: 'Bash',
    tool_input: { command: 'git clone https://***@example.com/repo.git' },
  },
  {
    type: 'step_delta',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0.9),
    step_id: 'step-2',
    output_chunk: 'Cloning into "repo"…\n',
  },
  {
    type: 'system_notice',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(1.0),
    kind: 'cancel_requested',
    detail: '用户点击取消',
  },
  {
    type: 'cancelled',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(1.1),
    trace_summary: {
      thought_duration_seconds: 1.1,
      tool_call_count: 1,
      thinking_chars: 0,
    },
    message: '任务被用户取消',
  },
])

// --- error: tool fails midway -----------------------------------------------
export const errorFixture: AgentTraceEvent[] = build(() => [
  {
    type: 'run_start',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0),
  },
  {
    type: 'step_start',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0.1),
    step_id: 'step-1',
    tool_name: 'Bash',
    tool_input: { command: 'cat /no/such/file' },
  },
  {
    type: 'step_delta',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0.2),
    step_id: 'step-1',
    output_chunk: 'cat: /no/such/file: No such file or directory\n',
  },
  {
    type: 'step_end',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0.3),
    step_id: 'step-1',
    status: 'error',
    duration_seconds: 0.2,
    output_excerpt: 'cat: /no/such/file: No such file or directory\n',
  },
  {
    type: 'error',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0.4),
    error_kind: 'ToolExecutionError',
    message: '工具执行失败',
    trace_summary: {
      thought_duration_seconds: 0.4,
      tool_call_count: 1,
      thinking_chars: 0,
    },
  },
])

// --- thinking-heavy: many thinking deltas, no tool call ---------------------
export const heavyThinkingFixture: AgentTraceEvent[] = build(() => {
  const evts: AgentTraceEvent[] = [
    {
      type: 'run_start',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(0),
    },
  ]
  evts.push({
    type: 'thinking_start',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(0.1),
    step_id: 'think-1',
  })
  for (let i = 0; i < 12; i += 1) {
    evts.push({
      type: 'thinking_delta',
      task_id: TASK_ID,
      seq: seq(),
      timestamp: ts(0.1 + i * 0.05),
      step_id: 'think-1',
      text_chunk: `第 ${i + 1} 段思考：先观察样本再决定切片策略。\n`,
    })
  }
  evts.push({
    type: 'thinking_end',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(1.0),
    step_id: 'think-1',
    duration_seconds: 0.9,
  })
  evts.push({
    type: 'run_complete',
    task_id: TASK_ID,
    seq: seq(),
    timestamp: ts(1.1),
    trace_summary: {
      thought_duration_seconds: 1.1,
      tool_call_count: 0,
      thinking_chars: 360,
    },
  })
  return evts
})
