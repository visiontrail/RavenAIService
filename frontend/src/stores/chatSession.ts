import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { userApi } from '@/api/user'
import { resetImageCache } from '@/stores/conversationRuns'
import type { ChatSessionSummary } from '@/types'

export const useChatSessionStore = defineStore('chatSession', () => {
  const sessions = ref<ChatSessionSummary[]>([])
  const selectedSessionId = ref<string | null>(null)
  /** Blocking load: list is empty and the sidebar shows a placeholder. */
  const loading = ref(false)
  /** Background refresh: the current list stays rendered while we refetch. */
  const refreshing = ref(false)
  const newChatToken = ref(0)
  const selectSessionToken = ref(0)
  /** Monotonic guard so out-of-order responses can't overwrite newer state. */
  let loadSeq = 0

  /**
   * Stale-while-revalidate: once we have a list, subsequent loads (status
   * polling, post-send refresh, manual refresh) run as background refreshes —
   * the old list stays on screen instead of flashing the loading placeholder,
   * and a failed refresh keeps the stale list rather than blanking it.
   */
  const load = async (opts: { background?: boolean } = {}) => {
    const background = opts.background ?? sessions.value.length > 0
    const seq = ++loadSeq
    if (background) refreshing.value = true
    else loading.value = true
    try {
      const resp = await userApi.listSessions()
      if (seq !== loadSeq) return
      sessions.value = resp?.success && resp.data ? resp.data : []
    } catch (error) {
      console.error('Failed to load chat sessions', error)
      // Only clear when this was a blocking load — a failed background
      // refresh keeps showing the stale list.
      if (seq === loadSeq && !background) sessions.value = []
      throw error
    } finally {
      if (seq === loadSeq) {
        loading.value = false
        refreshing.value = false
      }
    }
  }

  const reset = () => {
    loadSeq += 1
    sessions.value = []
    selectedSessionId.value = null
    loading.value = false
    refreshing.value = false
  }

  const selectSession = (id: string) => {
    selectedSessionId.value = id
    selectSessionToken.value += 1
  }

  const startNewChat = () => {
    selectedSessionId.value = null
    newChatToken.value += 1
  }

  const removeSession = async (id: string) => {
    const resp = await userApi.deleteSession(id)
    if (resp?.success && Array.isArray(resp.data)) {
      sessions.value = resp.data
      // The backend drops this session's image files; release the blob object
      // URLs we were holding for them so they do not leak for the page's life.
      resetImageCache(id)
      if (selectedSessionId.value === id) startNewChat()
      return true
    }
    return false
  }

  const togglePin = async (id: string) => {
    const target = sessions.value.find((s) => s.id === id)
    if (!target) return false
    const nextPinned = !target.is_pinned
    const resp = await userApi.pinSession(id, nextPinned)
    if (resp?.success && Array.isArray(resp.data)) {
      sessions.value = resp.data
      return true
    }
    return false
  }

  const renameSession = async (id: string, title: string): Promise<boolean> => {
    const trimmed = (title || '').trim()
    if (!trimmed) return false
    const resp = await userApi.renameSession(id, trimmed)
    if (resp?.success && Array.isArray(resp.data)) {
      sessions.value = resp.data
      return true
    }
    return false
  }

  const setSelected = (id: string | null) => {
    selectedSessionId.value = id
  }

  const upsertSessionTitle = (id: string, title: string) => {
    const trimmed = (title || '').trim()
    if (!id || !trimmed) return
    const existing = sessions.value.find((s) => s.id === id)
    const nowIso = new Date().toISOString()
    if (existing) {
      existing.title = trimmed
      existing.last_message_at = existing.last_message_at || nowIso
      return
    }
    sessions.value = [
      {
        id,
        title: trimmed,
        last_message_at: nowIso,
        created_at: nowIso,
        updated_at: nowIso,
        message_count: 0,
      } as ChatSessionSummary,
      ...sessions.value,
    ]
  }

  const currentTitle = computed(() => {
    if (!selectedSessionId.value) return null
    return sessions.value.find((s) => s.id === selectedSessionId.value)?.title || null
  })

  return {
    sessions,
    selectedSessionId,
    loading,
    refreshing,
    newChatToken,
    selectSessionToken,
    currentTitle,
    load,
    reset,
    selectSession,
    startNewChat,
    removeSession,
    togglePin,
    renameSession,
    setSelected,
    upsertSessionTitle,
  }
})
