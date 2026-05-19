import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { userApi } from '@/api/user'
import type { ChatSessionSummary } from '@/types'

export const useChatSessionStore = defineStore('chatSession', () => {
  const sessions = ref<ChatSessionSummary[]>([])
  const selectedSessionId = ref<string | null>(null)
  const loading = ref(false)
  const newChatToken = ref(0)
  const selectSessionToken = ref(0)

  const load = async () => {
    loading.value = true
    try {
      const resp = await userApi.listSessions()
      sessions.value = resp?.success && resp.data ? resp.data : []
    } catch (error) {
      console.error('加载会话失败', error)
      sessions.value = []
      throw error
    } finally {
      loading.value = false
    }
  }

  const reset = () => {
    sessions.value = []
    selectedSessionId.value = null
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
      if (selectedSessionId.value === id) startNewChat()
      return true
    }
    return false
  }

  const setSelected = (id: string | null) => {
    selectedSessionId.value = id
  }

  const currentTitle = computed(() => {
    if (!selectedSessionId.value) return null
    return sessions.value.find((s) => s.id === selectedSessionId.value)?.title || null
  })

  return {
    sessions,
    selectedSessionId,
    loading,
    newChatToken,
    selectSessionToken,
    currentTitle,
    load,
    reset,
    selectSession,
    startNewChat,
    removeSession,
    setSelected,
  }
})
