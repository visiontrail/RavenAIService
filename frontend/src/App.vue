<script setup lang="ts">
import { onMounted } from 'vue'
import { useAppStore } from './stores/app'
import AppNavbar from './components/AppNavbar.vue'
import AppNotifications from './components/AppNotifications.vue'
import AppLoading from './components/AppLoading.vue'

const appStore = useAppStore()

onMounted(() => {
  // 应用初始化逻辑
})
</script>

<template>
  <div id="app" class="min-h-screen bg-gray-50">
    <!-- 导航栏 -->
    <AppNavbar />
    
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
