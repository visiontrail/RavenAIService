import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { NotificationOptions } from '../types'
import { userApi } from '@/api/user'
import { useUserStore } from './user'
import {
  getActiveLocale,
  setI18nLocale,
  type AppLocale,
} from '@/i18n'

const getInitialAdminSidebarVisible = () => true

/** 主题偏好：明 / 暗 / 跟随系统。与 index.html 内联脚本共用同一存储键。 */
export type ThemePreference = 'light' | 'dark' | 'system'

export const THEME_STORAGE_KEY = 'raven-theme'

const isThemePreference = (value: unknown): value is ThemePreference =>
  value === 'light' || value === 'dark' || value === 'system'

const getStoredTheme = (): ThemePreference => {
  if (typeof window === 'undefined') return 'system'
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isThemePreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

const getSystemPrefersDark = (): boolean => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

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
  // 主题偏好与系统深色探测。html.dark class 由 applyTheme() 维护；
  // 首屏由 index.html 内联脚本预置，避免闪烁。
  const theme = ref<ThemePreference>(getStoredTheme())
  const systemPrefersDark = ref(getSystemPrefersDark())
  const resolvedTheme = computed<'light' | 'dark'>(() =>
    theme.value === 'system' ? (systemPrefersDark.value ? 'dark' : 'light') : theme.value,
  )

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

  /** 把 resolvedTheme 同步到 <html> 的 dark/light class（部分组件依赖 light 钩子）。 */
  const applyTheme = () => {
    if (typeof document === 'undefined') return
    const dark = resolvedTheme.value === 'dark'
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.classList.toggle('light', !dark)
  }

  /** 切换主题偏好：更新 store + localStorage + html class。 */
  const setTheme = (next: ThemePreference) => {
    theme.value = next
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next)
      } catch {
        // 隐私模式等场景下写入失败，仅本次会话生效
      }
    }
    applyTheme()
  }

  /**
   * 启动期主题初始化：同步一次 html class，并在“跟随系统”时
   * 监听系统深浅色变化。返回清理函数（App 卸载时调用）。
   */
  const initTheme = (): (() => void) => {
    applyTheme()
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return () => {}
    }
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (event: MediaQueryListEvent) => {
      systemPrefersDark.value = event.matches
      applyTheme()
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
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
    theme,
    resolvedTheme,
    // 操作
    setTheme,
    initTheme,
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
