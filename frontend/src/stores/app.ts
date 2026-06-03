import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { NotificationOptions } from '../types'
import { userApi } from '@/api/user'
import { useUserStore } from './user'
import {
  getActiveLocale,
  setI18nLocale,
  type AppLocale,
} from '@/i18n'

const getInitialAdminSidebarVisible = () => true

export const useAppStore = defineStore('app', () => {
  // 状态
  const loading = ref(false)
  const notifications = ref<(NotificationOptions & { id: string })[]>([])
  const adminSidebarVisible = ref(getInitialAdminSidebarVisible())
  // 登录弹窗请求信号：触发 WorkbenchLayout 打开登录框（值为 'login' 或 'register'）
  const loginModalRequest = ref<{ seq: number; mode: 'login' | 'register' }>({ seq: 0, mode: 'login' })
  // 当前激活语言。初值来自 i18n 模块（localStorage → 浏览器探测），
  // 登录后由 initLocale() 用 profile 偏好覆盖。
  const locale = ref<AppLocale>(getActiveLocale())

  // 操作
  const setLoading = (value: boolean) => {
    loading.value = value
  }

  /**
   * 切换语言：更新 store + localStorage + vue-i18n/Element Plus，
   * 已登录时同步 PATCH profile（除非 persistProfile === false）。
   */
  const setLocale = async (
    next: string,
    opts: { persistProfile?: boolean } = {},
  ): Promise<AppLocale> => {
    const resolved = setI18nLocale(next)
    locale.value = resolved
    if (opts.persistProfile !== false) {
      const userStore = useUserStore()
      if (userStore.isAuthenticated) {
        try {
          const resp = await userApi.updateProfile({ language: resolved })
          if (resp?.success && resp.data) {
            userStore.setProfile(resp.data)
          }
        } catch {
          // 网络失败时本地切换已生效，忽略远端持久化错误
        }
      }
    }
    return resolved
  }

  /**
   * 启动期语言解析：profile（已登录）→ localStorage → 浏览器探测。
   * localStorage/浏览器探测已折叠进 i18n 初值，此处只需在已登录且
   * profile 有偏好时优先采用 profile，并同步本地（不再回写 profile）。
   */
  const initLocale = () => {
    const userStore = useUserStore()
    const profileLang = userStore.profile?.language
    if (userStore.isAuthenticated && profileLang) {
      setI18nLocale(profileLang)
    }
    locale.value = getActiveLocale()
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
    locale,
    // 操作
    setLoading,
    showNotification,
    removeNotification,
    clearNotifications,
    setAdminSidebarVisible,
    toggleAdminSidebar,
    requestLoginModal,
    setLocale,
    initLocale,
  }
})
