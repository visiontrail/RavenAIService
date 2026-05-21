<template>
  <nav class="bg-white shadow-sm border-b border-gray-200 app-navbar mobile-sticky-header">
    <div class="container mx-auto px-4">
      <div class="flex justify-between items-center h-16 navbar-inner">
        <!-- Logo和标题 -->
        <div class="flex items-center space-x-4 navbar-brand-wrap">
          <router-link to="/" class="flex items-center space-x-2 navbar-brand-link">
            <img
              :src="ravenLogo"
              alt="Raven Logo"
              class="h-9 w-9 rounded-xl shadow-sm ring-1 ring-gray-200 object-contain"
            />
            <span class="text-xl font-semibold text-gray-900 navbar-title">Raven智能测试平台</span>
          </router-link>
        </div>

        <!-- 导航菜单 -->
        <div class="flex items-center space-x-1 navbar-menu">
          <router-link
            to="/logs"
            class="nav-link"
            :class="{ 'nav-link-active': $route.name === 'Logs' }"
          >
            <el-icon class="mr-2">
              <List />
            </el-icon>
            <span class="font-medium">日志列表</span>
          </router-link>
          
          <router-link
            to="/devices"
            class="nav-link"
            :class="{ 'nav-link-active': isDeviceRoute }"
          >
            <el-icon class="mr-2">
              <Monitor />
            </el-icon>
            <span class="font-medium">设备机柜</span>
          </router-link>

          <router-link
            to="/raven-manager"
            class="nav-link"
            :class="{ 'nav-link-active': isRavenRoute }"
          >
            <el-icon class="mr-2">
              <Box />
            </el-icon>
            <span class="font-medium">重构包仓库</span>
          </router-link>
        </div>

        <!-- 用户操作区域 -->
        <div class="flex items-center space-x-4">
        </div>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Box, List, Monitor } from '@element-plus/icons-vue'
import ravenLogo from '@/assets/raven-logo.png'

const route = useRoute()
const isRavenRoute = computed(() =>
  ['RavenManager', 'RavenPackageDetail'].includes((route.name as string) || '')
)
const isDeviceRoute = computed(() => ['DeviceList', 'DeviceDetail'].includes((route.name as string) || ''))
</script>

<style scoped>
.nav-link {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #6b7280;
  border-radius: 0.5rem;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  text-decoration: none;
  position: relative;
  overflow: hidden;
}

.nav-link::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(120deg, rgba(37, 99, 235, 0.1), rgba(37, 99, 235, 0.05));
  opacity: 0;
  transition: opacity 0.3s ease;
  z-index: -1;
}

.nav-link:hover {
  color: #111827;
  background-color: #f9fafb;
  transform: translateY(-2px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
}

.nav-link:hover::before {
  opacity: 1;
}

.nav-link-active {
  color: #2563eb;
  background-color: #eff6ff;
  font-weight: 600;
}

.nav-link-active::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 25%;
  width: 50%;
  height: 3px;
  background: linear-gradient(90deg, #3b82f6, #2563eb);
  border-radius: 2px;
}

@media (max-width: 900px) {
  .navbar-title {
    font-size: 1rem;
  }
}

@media (max-width: 768px) {
  .app-navbar {
    background: rgba(255, 255, 255, 0.94);
  }

  .navbar-inner {
    height: auto;
    min-height: 4rem;
    flex-wrap: wrap;
    gap: 0.5rem;
    padding: 0.5rem 0;
    justify-content: center;
  }

  .navbar-brand-wrap {
    display: none;
  }

  .navbar-menu {
    width: 100%;
    justify-content: center;
    overflow-x: auto;
    white-space: nowrap;
    scroll-snap-type: x mandatory;
    padding-bottom: 0.25rem;
  }

  .navbar-menu::-webkit-scrollbar {
    display: none;
  }

  .nav-link {
    flex-shrink: 0;
    min-height: 2.5rem;
    padding: 0.55rem 0.9rem;
    scroll-snap-align: start;
  }

  .navbar-title {
    font-size: 0.95rem;
  }
}

@media (max-width: 420px) {
  .navbar-title {
    display: none;
  }
}
</style>
