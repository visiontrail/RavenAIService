import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { userApi, userToken } from '@/api/user'
import type { UserProfile } from '@/types'

export const useUserStore = defineStore('user', () => {
  const token = ref(userToken.get())
  const profile = ref<UserProfile | null>(null)
  const isAuthenticated = computed(() => Boolean(token.value))

  const setToken = (value: string) => {
    token.value = value
    if (value) {
      userToken.set(value)
    } else {
      userToken.clear()
    }
  }

  const setProfile = (value: UserProfile | null) => {
    profile.value = value
  }

  const clear = () => {
    setToken('')
    setProfile(null)
  }

  const bootstrap = async () => {
    const existing = userToken.get()
    if (!existing) return
    token.value = existing
    try {
      const resp = await userApi.me()
      if (resp?.success && resp.data) {
        profile.value = resp.data
      } else {
        clear()
      }
    } catch {
      clear()
    }
  }

  return {
    token,
    profile,
    isAuthenticated,
    setToken,
    setProfile,
    clear,
    bootstrap,
  }
})
