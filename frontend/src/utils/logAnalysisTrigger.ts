import type { AnalysisTriggerInfo } from '@/types'

const firstText = (...values: unknown[]): string => {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number') return String(value)
  }
  return ''
}

export const formatAnalysisTriggerUser = (
  trigger: AnalysisTriggerInfo | null | undefined,
  anonymousLabel: string,
): string => {
  if (!trigger || typeof trigger !== 'object') return '-'

  const user = trigger.user
  if (!user || typeof user !== 'object') return anonymousLabel

  return firstText(
    user.display_name,
    user.username,
    user.email,
    user.id,
  ) || anonymousLabel
}
