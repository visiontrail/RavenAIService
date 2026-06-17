import { computed, ref } from 'vue'
import { shareApi } from '@/api/share'
import { copyToClipboard } from '@/utils'
import type { ShareInfo } from '@/types'

/**
 * Owner-side conversation share lifecycle, decoupled from the modal markup so
 * the state machine (unshared ↔ shared) and clipboard behaviour are unit
 * testable in the SSR/node test harness.
 *
 * The single create/refresh endpoint backs both "generate" (unshared → shared)
 * and "update snapshot" (shared → shared, refreshes ``shared_at``).
 */
export interface UseConversationShareOptions {
  // Injectable clipboard writer (defaults to ``navigator.clipboard``) so copy
  // can be exercised in environments without a real clipboard.
  copyText?: (text: string) => Promise<void>
}

const defaultCopyText = async (text: string): Promise<void> => {
  const copied = await copyToClipboard(text)
  if (!copied) {
    throw new Error('clipboard-unavailable')
  }
}

export function useConversationShare(options: UseConversationShareOptions = {}) {
  const copyText = options.copyText || defaultCopyText

  const loading = ref(false) // initial status fetch in flight
  const working = ref(false) // create / refresh / revoke in flight
  const error = ref<string | null>(null)
  const info = ref<ShareInfo>({ is_active: false })

  const isShared = computed(() => !!info.value.is_active && !!info.value.share_url)
  const shareUrl = computed(() => info.value.share_url || '')
  const sharedAt = computed(() => info.value.shared_at || null)
  const messageCount = computed(() => info.value.message_count ?? 0)

  const reset = () => {
    info.value = { is_active: false }
    error.value = null
    loading.value = false
    working.value = false
  }

  /** Fetch the current share status for a session. */
  const load = async (sessionId: string): Promise<void> => {
    loading.value = true
    error.value = null
    try {
      const resp = await shareApi.get(sessionId)
      info.value = resp.data || { is_active: false }
    } catch {
      error.value = 'load_failed'
      info.value = { is_active: false }
    } finally {
      loading.value = false
    }
  }

  /** Create a new share or refresh the existing snapshot; same token reused. */
  const generate = async (sessionId: string): Promise<boolean> => {
    working.value = true
    error.value = null
    try {
      const resp = await shareApi.createOrRefresh(sessionId)
      info.value = resp.data || { is_active: false }
      return true
    } catch {
      error.value = 'generate_failed'
      return false
    } finally {
      working.value = false
    }
  }

  /** Revoke the active share; the public link 404s immediately afterwards. */
  const revoke = async (sessionId: string): Promise<boolean> => {
    working.value = true
    error.value = null
    try {
      await shareApi.revoke(sessionId)
      info.value = { is_active: false }
      return true
    } catch {
      error.value = 'revoke_failed'
      return false
    } finally {
      working.value = false
    }
  }

  /** Copy the current public link to the clipboard. */
  const copy = async (): Promise<boolean> => {
    const url = shareUrl.value
    if (!url) return false
    try {
      await copyText(url)
      return true
    } catch {
      return false
    }
  }

  return {
    loading,
    working,
    error,
    info,
    isShared,
    shareUrl,
    sharedAt,
    messageCount,
    load,
    generate,
    revoke,
    copy,
    reset,
  }
}
