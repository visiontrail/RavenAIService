// Maps raw Claude Agent SDK tool names to friendly Chinese display names.
// Unknown tool names fall back to the raw string — callers MUST NOT drop
// the event.

const DEFAULT_TOOL_DISPLAY_NAMES: Record<string, string> = {
  Bash: '终端',
  Read: '读文件',
  Write: '写文件',
  Edit: '编辑文件',
  Grep: '代码搜索',
  Glob: '文件查找',
  Skill: '调用技能',
  Task: '子任务',
  WebFetch: '网页抓取',
  WebSearch: '联网搜索',
  mcp__project_repo__lookup_project_repo: '项目仓库查询',
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
    if (rawName === 'Grep' && isLogSearchInput(toolInput)) return '日志搜索'
    return merged[rawName] || rawName
  }
  return { resolve, map: merged }
}

export { DEFAULT_TOOL_DISPLAY_NAMES }
