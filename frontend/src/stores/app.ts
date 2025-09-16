import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { NotificationOptions } from '../types'

export const useAppStore = defineStore('app', () => {
  // 状态
  const loading = ref(false)
  const notifications = ref<(NotificationOptions & { id: string })[]>([])

  // 操作
  const setLoading = (value: boolean) => {
    loading.value = value
  }

  const showNotification = (options: NotificationOptions) => {
    const id = Date.now().toString()
    const notification = { ...options, id }
    notifications.value.push(notification)

    // 自动移除通知
    const duration = options.duration || 3000
    setTimeout(() => {
      removeNotification(id)
    }, duration)

    return id
  }

  const removeNotification = (id: string) => {
    const index = notifications.value.findIndex(n => n.id === id)
    if (index > -1) {
      notifications.value.splice(index, 1)
    }
  }

  const clearNotifications = () => {
    notifications.value = []
  }

  return {
    // 状态
    loading,
    notifications,
    // 操作
    setLoading,
    showNotification,
    removeNotification,
    clearNotifications,
  }
})