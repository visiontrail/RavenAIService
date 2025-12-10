<template>
  <nav class="bg-white shadow-sm border-b border-gray-200">
    <div class="container mx-auto px-4">
      <div class="flex justify-between items-center h-16">
        <!-- Logo和标题 -->
        <div class="flex items-center space-x-4">
          <router-link to="/" class="flex items-center space-x-2">
            <img
              :src="ravenLogo"
              alt="Raven Logo"
              class="h-9 w-9 rounded-xl shadow-sm ring-1 ring-gray-200 object-contain"
            />
            <span class="text-xl font-semibold text-gray-900">Raven智能测试平台</span>
          </router-link>
        </div>

        <!-- 导航菜单 -->
        <div class="flex items-center space-x-1">
          <router-link
            to="/"
            class="nav-link"
            :class="{ 'nav-link-active': $route.name === 'LogList' }"
          >
            <el-icon class="mr-2">
              <List />
            </el-icon>
            <span class="font-medium">日志列表</span>
          </router-link>

          <router-link
            to="/raven-manager"
            class="nav-link"
            :class="{ 'nav-link-active': isRavenRoute }"
          >
            <el-icon class="mr-2">
              <Box />
            </el-icon>
            <span class="font-medium">重构包列表</span>
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
import { Box, List } from '@element-plus/icons-vue'
import ravenLogo from '@/assets/raven-logo.png'

const route = useRoute()
const isRavenRoute = computed(() =>
  ['RavenManager', 'RavenPackageDetail'].includes((route.name as string) || '')
)
</script>

<style scoped>
.nav-link {
  display: flex;
  align-items: center;
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
</style>
