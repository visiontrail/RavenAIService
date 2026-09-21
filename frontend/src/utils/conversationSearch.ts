/** 返回纯文本片段；由 Vue 插值渲染，绝不把对话内容作为 HTML 执行。 */
export function highlightSearchText(text: string, query: string) {
  const needle = query.trim().toLowerCase()
  if (!needle) return [{ text, match: false }]
  const parts: { text: string; match: boolean }[] = []
  const lower = text.toLowerCase()
  let cursor = 0
  let position = lower.indexOf(needle)
  while (position !== -1) {
    if (position > cursor) parts.push({ text: text.slice(cursor, position), match: false })
    parts.push({ text: text.slice(position, position + needle.length), match: true })
    cursor = position + needle.length
    position = lower.indexOf(needle, cursor)
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), match: false })
  return parts
}

export function searchDateGroup(timestamp: string, now = new Date()) {
  // 后端历史时间为无时区 UTC；按用户本地日期分组。
  const value = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp) ? timestamp : `${timestamp}Z`).getTime()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  const week = new Date(today); week.setDate(today.getDate() - 7)
  if (value >= today.getTime()) return 'today'
  if (value >= yesterday.getTime()) return 'yesterday'
  if (value >= week.getTime()) return 'thisWeek'
  return 'earlier'
}
