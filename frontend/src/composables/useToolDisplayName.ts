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

export function useToolDisplayName(overrides?: ToolNameMap) {
  const merged: ToolNameMap = { ...DEFAULT_TOOL_DISPLAY_NAMES, ...(overrides || {}) }
  const resolve = (rawName: string | undefined | null): string => {
    if (!rawName) return ''
    return merged[rawName] || rawName
  }
  return { resolve, map: merged }
}

export { DEFAULT_TOOL_DISPLAY_NAMES }
