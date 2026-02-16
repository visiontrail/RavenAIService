<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from './stores/app'
import AppNavbar from './components/AppNavbar.vue'
import AppNotifications from './components/AppNotifications.vue'
import AppLoading from './components/AppLoading.vue'
import AIOrb from './components/AIOrb.vue'

const appStore = useAppStore()
const route = useRoute()

// 判断是否是 AI Chat 路由
const isChatRoute = computed(() => route.name === 'AIChat' || route.path === '/ai-chat')

// 判断是否应该显示 AI Orb
const showAIOrb = computed(() => {
  // 不在 AI Chat 页面时，都显示 Orb
  // 当切换到 AI Chat 时，该值变为 false，触发淡出效果
  return !isChatRoute.value
})

// 判断是否应该显示导航栏
const shouldShowNavbar = computed(() => {
  if (typeof window === 'undefined') return true
  
  const configuredPort = (window as any).__RAVEN_SERVER_PORT__ || '8083'
  const currentPort = window.location.port
  
  // 如果当前端口是 package-server 端口（默认 8083），则不显示 NavBar
  if (currentPort === configuredPort) {
    return false
  }
  
  // 如果访问路径是 /logs，也不显示 NavBar
  if (route.path === '/logs') {
    return false
  }

  // 后台管理路径不显示主导航，避免暴露入口
  if (route.path.startsWith('/admin')) {
    return false
  }

  // 如果是 AI Chat 页面，不显示 NavBar
  if (route.name === 'AIChat' || route.path === '/ai-chat') {
    return false
  }
  
  return true
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

const shouldLockChatPage = () => isChatRoute.value && !isMobileViewport()

const chatMainStyle = computed(() => {
  if (!isChatRoute.value) return undefined
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

watch(isChatRoute, (isChat) => {
  applyChatPageLock(isChat && !isMobileViewport())
  if (isChat) updateChatViewportHeight()
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
    <!-- 导航栏 - 仅在非 package-server 端口显示 -->
    <AppNavbar v-if="shouldShowNavbar" />
    
    <!-- 主要内容区域 -->
    <main
      :class="isChatRoute ? 'w-full' : 'container mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-6 mobile-safe-bottom'"
      :style="chatMainStyle"
    >
      <router-view />
    </main>
    
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
