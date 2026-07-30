export type LiveLevel =
  | 'configuring'
  | 'paused'
  | 'starting'
  | 'stale'
  | 'down'
  | 'degraded'
  | 'healthy'

export interface AggregateMetrics {
  calls: number
  successes: number
  failures: number
  usable_calls: number
  uptime_pct: number | null
  usable_pct: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  p95_ttft_ms: number | null
  rate_limited: number
  rate_limit_pct: number | null
  server_errors: number
  total_tokens: number
}

export interface SeriesPoint extends AggregateMetrics {
  key: string
  label: string
  local_time: string
}

export interface ProbeRun {
  id: number
  source: string
  started_at: string
  finished_at: string
  success: boolean
  usable: boolean
  status_category: string
  http_status: number | null
  latency_ms: number
  first_byte_ms: number | null
  ttft_ms: number | null
  input_tokens: number
  output_tokens: number
  total_tokens: number
  error_kind: string | null
  error_message: string | null
  response_excerpt: string | null
  model: string
  endpoint: string
}

export type ProbeStatusFilter = 'all' | 'usable' | 'slow' | 'failed'
export type ProbeSourceFilter = 'all' | 'scheduled' | 'manual' | 'settings_test'
export type ProbeRangeFilter = '24h' | '7d' | '30d' | 'all'

export interface ProbeListData {
  items: ProbeRun[]
  total: number
  page: number
  page_size: number
  pages: number
  filters: {
    status: ProbeStatusFilter
    source: ProbeSourceFilter
    range: ProbeRangeFilter
  }
}

export interface HeatmapPoint {
  date: string
  date_label: string
  hour: number
  calls: number
  uptime_pct: number | null
  p95_latency_ms: number | null
}

export interface CallingWindow {
  hour: number
  label: string
  score: number
  samples: number
  uptime_pct: number | null
  p95_latency_ms: number | null
}

export interface DashboardData {
  range: '24h' | '7d' | '30d'
  granularity: 'hourly' | 'daily'
  generated_at: string
  state: {
    level: LiveLevel
    label: string
    detail: string
  }
  settings: {
    target_name: string
    protocol: 'anthropic' | 'openai'
    base_url: string
    model: string
    enabled: boolean
    interval_seconds: number
    alert_latency_ms: number
    timezone: string
    api_key_set: boolean
  }
  overview: AggregateMetrics
  series: SeriesPoint[]
  heatmap: HeatmapPoint[]
  calling_windows: {
    ready: boolean
    sample_count: number
    minimum_samples: number
    windows: CallingWindow[]
  }
  capacity_signal: {
    level: 'insufficient' | 'healthy' | 'warning' | 'critical'
    title: string
    detail: string
  }
  recent: ProbeRun[]
}

export interface MonitorSettings {
  id: number
  target_name: string
  protocol: 'anthropic' | 'openai'
  base_url: string
  model: string
  enabled: boolean
  interval_seconds: number
  timeout_seconds: number
  max_tokens: number
  alert_latency_ms: number
  retention_days: number
  timezone: string
  agent_prompt: string
  api_key_set: boolean
  created_at: string
  updated_at: string
}

