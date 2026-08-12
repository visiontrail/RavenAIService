export type LogWorkspaceReplacementDecision = 'replace' | 'new-chat' | 'stay'

export type LogWorkspaceReplacementCheck = {
  hasExistingLogWorkspace: boolean
  isLogAnalysisRequest: boolean
  logFileCount: number
}

/**
 * Persisted log-analysis user messages include this backend-owned marker.
 * Keep recognition in one place so history hydration does not depend on
 * translated frontend attachment labels.
 */
export const hasPersistedLogAttachmentMarker = (content: unknown): boolean =>
  typeof content === 'string' && /\[\u65e5\u5fd7\u9644\u4ef6\](?:\s|$)/.test(content)

/** Only a new log upload can replace the current log-analysis workspace. */
export const requiresLogWorkspaceReplacementConfirmation = ({
  hasExistingLogWorkspace,
  isLogAnalysisRequest,
  logFileCount,
}: LogWorkspaceReplacementCheck): boolean =>
  hasExistingLogWorkspace && isLogAnalysisRequest && logFileCount > 0

/** Normalize Element Plus MessageBox outcomes into domain-level decisions. */
export const resolveLogWorkspaceReplacementAction = (
  action: unknown,
): LogWorkspaceReplacementDecision => {
  // The safe route is the dialog's primary/default action; replacing the
  // workspace is intentionally the secondary action.
  if (action === 'confirm') return 'new-chat'
  if (action === 'cancel') return 'replace'
  return 'stay'
}

type LogWorkspaceReplacementFlow = {
  requiresConfirmation: boolean
  requestDecision: () => Promise<LogWorkspaceReplacementDecision>
  startNewConversation: () => Promise<void> | void
}

/**
 * Return true only when the caller may continue the original send. A new-chat
 * decision performs navigation but deliberately returns false so no request is
 * sent before the user has a chance to add every log needed for correlation.
 */
export const proceedAfterLogWorkspaceReplacementCheck = async ({
  requiresConfirmation,
  requestDecision,
  startNewConversation,
}: LogWorkspaceReplacementFlow): Promise<boolean> => {
  if (!requiresConfirmation) return true
  const decision = await requestDecision()
  if (decision === 'replace') return true
  if (decision === 'new-chat') await startNewConversation()
  return false
}
