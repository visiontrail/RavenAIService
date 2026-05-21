<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from './stores/app'
import AppNavbar from './components/AppNavbar.vue'
import AppFooter from './components/AppFooter.vue'
import AppNotifications from './components/AppNotifications.vue'
import AppLoading from './components/AppLoading.vue'
import AIOrb from './components/AIOrb.vue'

const appStore = useAppStore()
const route = useRoute()

// Workbench routes share the WorkbenchLayout (sidebar + main pane).
const workbenchRouteNames = new Set(['Workbench', 'Logs', 'LogDetail', 'DeviceList', 'RavenManager', 'RavenPackageDetail'])
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
    route.path === '/raven-manager' ||
    route.path === '/raven' ||
    route.path === '/raven/' ||
    route.path.startsWith('/raven/package/') ||
    route.path.startsWith('/package/')
  )
})

const isAdminRoute = computed(() => route.path.startsWith('/admin'))

// 判断是否应该显示 AI Orb
const showAIOrb = computed(() => {
  // 工作台与后台管理页面都不显示 Orb
  return !isWorkbenchRoute.value && !isAdminRoute.value
})

// 判断是否应该显示导航栏
const shouldShowNavbar = computed(() => {
  if (typeof window === 'undefined') return true

  const configuredPort = (window as any).__RAVEN_SERVER_PORT__
  const currentPort = window.location.port

  // 兼容历史独立包服务端口；统一后端部署默认不再设置该值
  if (configuredPort && currentPort === String(configuredPort)) {
    return false
  }

  // 后台管理路径不显示主导航，避免暴露入口
  if (route.path.startsWith('/admin')) {
    return false
  }

  // 工作台壳已包含左侧导航，不再叠加平台顶部栏
  if (isWorkbenchRoute.value) {
    return false
  }

  return true
})

const shouldShowFooter = computed(() => !isWorkbenchRoute.value && !isAdminRoute.value)

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
  <div id="app" class="min-h-screen bg-gray-50">
    <!-- 导航栏 - 兼容历史独立 Raven 端口时隐藏 -->
    <AppNavbar v-if="shouldShowNavbar" />
    
    <!-- 主要内容区域 -->
    <main
      :class="mainClass"
      :style="chatMainStyle"
    >
      <router-view />
    </main>

    <AppFooter v-if="shouldShowFooter" />
    
    <!-- 全局通知 -->
    <AppNotifications />
    
    <!-- 全局加载状态 -->
    <AppLoading v-if="appStore.loading" />
    
    <!-- AI Assistant Orb -->
    <AIOrb :visible="showAIOrb" />
  </div>
</template>

<style>
/* 全局样式可以在这里添加 */
</style>
