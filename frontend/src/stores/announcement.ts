import { defineStore } from 'pinia'
import { ref } from 'vue'
import { userApi, userToken } from '@/api/user'
import type { SystemAnnouncement } from '@/types'

export const useAnnouncementStore = defineStore('announcement', () => {
  const pending = ref<SystemAnnouncement | null>(null)
  const checking = ref(false)
  const dismissing = ref(false)
  let checkPromise: Promise<SystemAnnouncement | null> | null = null
  let checkSeq = 0

  const checkPending = async (): Promise<SystemAnnouncement | null> => {
    if (!userToken.get()) {
      pending.value = null
      return null
    }
    if (checkPromise) return checkPromise

    const seq = ++checkSeq
    checking.value = true
    const request = (async () => {
      const resp = await userApi.getPendingAnnouncement()
      const result = resp?.success ? (resp.data ?? null) : null
      if (seq === checkSeq && userToken.get()) pending.value = result
      return result
    })()
    checkPromise = request
    try {
      return await request
    } finally {
      if (seq === checkSeq) checking.value = false
      if (checkPromise === request) checkPromise = null
    }
  }

  const dismiss = async (): Promise<boolean> => {
    const target = pending.value
    if (!target || dismissing.value) return false
    dismissing.value = true
    try {
      const resp = await userApi.dismissAnnouncement(target.id)
      if (!resp?.success || !resp.data?.dismissed) return false
      if (pending.value?.id === target.id) pending.value = null
      return true
    } catch (error: any) {
      if (error?.response?.status === 409) {
        pending.value = null
        try {
          await checkPending()
        } catch {
          // Preserve the original conflict for the caller's notification.
        }
      }
      throw error
    } finally {
      dismissing.value = false
    }
  }

  const reset = () => {
    checkSeq += 1
    pending.value = null
    checking.value = false
    dismissing.value = false
    checkPromise = null
  }

  return { pending, checking, dismissing, checkPending, dismiss, reset }
})
