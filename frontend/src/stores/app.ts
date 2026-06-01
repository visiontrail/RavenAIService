import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { NotificationOptions } from '../types'

const getInitialAdminSidebarVisible = () => true

export const useAppStore = defineStore('app', () => {
  // 状态
  const loading = ref(false)
  const notifications = ref<(NotificationOptions & { id: string })[]>([])
  const adminSidebarVisible = ref(getInitialAdminSidebarVisible())
  // 登录弹窗请求信号：触发 WorkbenchLayout 打开登录框（值为 'login' 或 'register'）
  const loginModalRequest = ref<{ seq: number; mode: 'login' | 'register' }>({ seq: 0, mode: 'login' })

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

  const setAdminSidebarVisible = (visible: boolean) => {
    adminSidebarVisible.value = visible
  }

  const toggleAdminSidebar = () => {
    setAdminSidebarVisible(!adminSidebarVisible.value)
  }

  const requestLoginModal = (mode: 'login' | 'register' = 'login') => {
    loginModalRequest.value = { seq: loginModalRequest.value.seq + 1, mode }
  }

  return {
    // 状态
    loading,
    notifications,
    adminSidebarVisible,
    loginModalRequest,
    // 操作
    setLoading,
    showNotification,
    removeNotification,
    clearNotifications,
    setAdminSidebarVisible,
    toggleAdminSidebar,
    requestLoginModal,
  }
})
