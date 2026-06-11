<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElConfigProvider } from 'element-plus'
import { useRoute } from 'vue-router'
import { useAppStore } from './stores/app'
import { getElementLocale } from './i18n'
import AppNotifications from './components/AppNotifications.vue'
import AppLoading from './components/AppLoading.vue'
import AIOrb from './components/AIOrb.vue'

const appStore = useAppStore()
const route = useRoute()

// Element Plus 语言包随激活 locale 响应式切换。
const elementLocale = computed(() => getElementLocale(appStore.locale))

// Workbench routes share the WorkbenchLayout (sidebar + main pane).
const workbenchRouteNames = new Set([
  'Workbench',
  'Logs',
  'LogDetail',
  'DeviceList',
  'DeviceDetail',
  'RavenManager',
  'RavenPackageDetail',
  'BugFixList',
  'BugFixDetail',
  'Upload',
  'Download',
  'About',
  'Changelog',
  'Privacy',
  'Terms',
  'NotFound',
])
const isWorkbenchRoute = computed(() => {
  const name = (route.name as string) || ''
  if (workbenchRouteNames.has(name)) return true
  // path aliases for legacy entry points
  return (
    route.path === '/workbench' ||
    route.path === '/ai-chat' ||
    route.path === '/logs' ||
    route.path.startsWith('/log/') ||
    route.path === '/log-list' ||
    route.path === '/devices' ||
    route.path.startsWith('/devices/') ||
    route.path === '/raven-manager' ||
    route.path === '/raven' ||
    route.path === '/raven/' ||
    route.path.startsWith('/raven/package/') ||
    route.path.startsWith('/package/') ||
    route.path === '/bug-fixes' ||
    route.path.startsWith('/bug-fixes/') ||
    route.path === '/upload' ||
    route.path === '/download'
  )
})

const isAdminRoute = computed(() => route.path.startsWith('/admin'))

// 判断是否应该显示 AI Orb
const showAIOrb = computed(() => {
  // 工作台与后台管理页面都不显示 Orb
  return !isWorkbenchRoute.value && !isAdminRoute.value
})

const mainClass = computed(() => {
  if (isWorkbenchRoute.value) return 'w-full'
  if (isAdminRoute.value) return 'w-full mobile-safe-bottom'
  return 'container mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-6 mobile-safe-bottom'
})

onMounted(() => {
  // 应用初始化逻辑
})

const chatViewportHeight = ref<string>('100dvh')
let isChatPageLocked = false
const savedPageStyles = {
  htmlOverflow: '',
  htmlHeight: '',
  bodyOverflow: '',
  bodyHeight: '',
  bodyOverscrollBehavior: '',
}

const isMobileViewport = () => {
  if (typeof window === 'undefined') return false
  return window.matchMedia('(max-width: 768px)').matches
}

const shouldLockChatPage = () => isWorkbenchRoute.value && !isMobileViewport()

const chatMainStyle = computed(() => {
  if (!isWorkbenchRoute.value) return undefined
  if (isMobileViewport()) {
    return { height: '100dvh', minHeight: '100dvh' }
  }
  return { height: chatViewportHeight.value, minHeight: chatViewportHeight.value }
})

const updateChatViewportHeight = () => {
  if (typeof window === 'undefined') return
  const viewportHeight = window.visualViewport?.height ?? window.innerHeight
  if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) return
  chatViewportHeight.value = `${Math.round(viewportHeight)}px`
  applyChatPageLock(shouldLockChatPage())
}

const applyChatPageLock = (locked: boolean) => {
  if (typeof document === 'undefined') return
  if (locked === isChatPageLocked) return

  const { documentElement, body } = document

  if (locked) {
    savedPageStyles.htmlOverflow = documentElement.style.overflow
    savedPageStyles.htmlHeight = documentElement.style.height
    savedPageStyles.bodyOverflow = body.style.overflow
    savedPageStyles.bodyHeight = body.style.height
    savedPageStyles.bodyOverscrollBehavior = body.style.overscrollBehavior

    documentElement.style.overflow = 'hidden'
    documentElement.style.height = '100%'
    body.style.overflow = 'hidden'
    body.style.height = '100%'
    body.style.overscrollBehavior = 'none'
    isChatPageLocked = true
    return
  }

  documentElement.style.overflow = savedPageStyles.htmlOverflow
  documentElement.style.height = savedPageStyles.htmlHeight
  body.style.overflow = savedPageStyles.bodyOverflow
  body.style.height = savedPageStyles.bodyHeight
  body.style.overscrollBehavior = savedPageStyles.bodyOverscrollBehavior
  isChatPageLocked = false
}

onMounted(() => {
  updateChatViewportHeight()
  window.addEventListener('resize', updateChatViewportHeight, { passive: true })
  window.addEventListener('orientationchange', updateChatViewportHeight, { passive: true })
  window.visualViewport?.addEventListener('resize', updateChatViewportHeight, { passive: true })
  window.visualViewport?.addEventListener('scroll', updateChatViewportHeight, { passive: true })
  applyChatPageLock(shouldLockChatPage())
})

watch(isWorkbenchRoute, (isWb) => {
  applyChatPageLock(isWb && !isMobileViewport())
  if (isWb) updateChatViewportHeight()
})

onUnmounted(() => {
  window.removeEventListener('resize', updateChatViewportHeight)
  window.removeEventListener('orientationchange', updateChatViewportHeight)
  window.visualViewport?.removeEventListener('resize', updateChatViewportHeight)
  window.visualViewport?.removeEventListener('scroll', updateChatViewportHeight)
  applyChatPageLock(false)
})
</script>

<template>
  <el-config-provider :locale="elementLocale">
    <div id="app" class="min-h-screen bg-gray-50">
      <!-- 主要内容区域 -->
      <main
        :class="mainClass"
        :style="chatMainStyle"
      >
        <router-view />
      </main>

      <!-- 全局通知 -->
      <AppNotifications :class="{ 'notifications-container--admin': isAdminRoute }" />

      <!-- 全局加载状态 -->
      <AppLoading v-if="appStore.loading" />

      <!-- AI Assistant Orb -->
      <AIOrb :visible="showAIOrb" />
    </div>
  </el-config-provider>
</template>

<style>
/* 全局样式可以在这里添加 */
</style>
