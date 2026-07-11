import { i18n } from '@/i18n'
// Maps raw Claude Agent SDK tool names to friendly Chinese display names.
// Unknown tool names fall back to the raw string — callers MUST NOT drop
// the event.

const DEFAULT_TOOL_DISPLAY_NAMES: Record<string, string> = {
  Bash: i18n.global.t('tools.Bash'),
  Read: i18n.global.t('tools.Read'),
  Write: i18n.global.t('tools.Write'),
  Edit: i18n.global.t('tools.Edit'),
  Grep: i18n.global.t('tools.Grep'),
  Glob: i18n.global.t('tools.Glob'),
  Skill: i18n.global.t('tools.Skill'),
  Task: i18n.global.t('tools.Task'),
  WebFetch: i18n.global.t('tools.WebFetch'),
  WebSearch: i18n.global.t('tools.WebSearch'),
  mcp__project_repo__lookup_project_repo: i18n.global.t('tools.ProjectRepo'),
  mcp__project_repo__discover_projects: i18n.global.t('tools.ProjectDiscovery'),
}

export type ToolNameMap = Record<string, string>

const LOG_PATH_RE = /(^|[\\/])logs?([\\/]|$)|\.(?:log|trace)(?:$|[?#])/i
const PATH_HINT_KEYS = ['path', 'file_path', 'file', 'filename', 'glob', 'include']

function collectPathHints(input: unknown): string[] {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return []

  const record = input as Record<string, unknown>
  const hints: string[] = []
  for (const key of PATH_HINT_KEYS) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) {
      hints.push(value.trim())
    } else if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === 'string' && item.trim()) hints.push(item.trim())
      }
    }
  }
  return hints
}

export function isLogSearchInput(input: unknown): boolean {
  return collectPathHints(input).some((hint) => LOG_PATH_RE.test(hint))
}

export function useToolDisplayName(overrides?: ToolNameMap) {
  const merged: ToolNameMap = { ...DEFAULT_TOOL_DISPLAY_NAMES, ...(overrides || {}) }
  const resolve = (rawName: string | undefined | null, toolInput?: unknown): string => {
    if (!rawName) return ''
    if (rawName === 'Grep' && isLogSearchInput(toolInput)) return i18n.global.t('tools.LogSearch')
    return merged[rawName] || rawName
  }
  return { resolve, map: merged }
}

export { DEFAULT_TOOL_DISPLAY_NAMES }
