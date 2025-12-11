<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from './stores/app'
import AppNavbar from './components/AppNavbar.vue'
import AppNotifications from './components/AppNotifications.vue'
import AppLoading from './components/AppLoading.vue'

const appStore = useAppStore()
const route = useRoute()

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
    <main class="container mx-auto px-4 py-6">
      <router-view />
    </main>
    
    <!-- 全局通知 -->
    <AppNotifications />
    
    <!-- 全局加载状态 -->
    <AppLoading v-if="appStore.loading" />
  </div>
</template>

<style>
/* 全局样式可以在这里添加 */
</style>
