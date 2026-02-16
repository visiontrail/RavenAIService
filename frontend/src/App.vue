<script setup lang="ts">
import { computed, onMounted } from 'vue'
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
</script>

<template>
  <div id="app" class="min-h-screen bg-gray-50">
    <!-- 导航栏 - 仅在非 package-server 端口显示 -->
    <AppNavbar v-if="shouldShowNavbar" />
    
    <!-- 主要内容区域 -->
    <main
      :class="isChatRoute ? 'w-full h-[100dvh]' : 'container mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-6 mobile-safe-bottom'"
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
