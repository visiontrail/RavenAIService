<template>
  <nav class="bg-white shadow-sm border-b border-gray-200">
    <div class="container mx-auto px-4">
      <div class="flex justify-between items-center h-16">
        <!-- Logo和标题 -->
        <div class="flex items-center space-x-4">
          <router-link to="/" class="flex items-center space-x-2">
            <el-icon size="24" class="text-blue-600">
              <Document />
            </el-icon>
            <span class="text-xl font-semibold text-gray-900">日志管理系统</span>
          </router-link>
        </div>

        <!-- 导航菜单 -->
        <div class="flex items-center space-x-6">
          <router-link
            to="/"
            class="nav-link"
            :class="{ 'nav-link-active': $route.name === 'LogList' }"
          >
            <el-icon class="mr-1">
              <List />
            </el-icon>
            日志列表
          </router-link>
          
          <router-link
            to="/upload"
            class="nav-link"
            :class="{ 'nav-link-active': $route.name === 'Upload' }"
          >
            <el-icon class="mr-1">
              <Upload />
            </el-icon>
            上传日志
          </router-link>
        </div>

        <!-- 用户操作区域 -->
        <div class="flex items-center space-x-4">
          <el-button
            type="primary"
            size="small"
            @click="$router.push('/upload')"
          >
            <el-icon class="mr-1">
              <Plus />
            </el-icon>
            上传文件
          </el-button>
        </div>
      </div>
    </div>
  </nav>
</template>

<script setup lang="ts">
import { Document, List, Upload, Plus } from '@element-plus/icons-vue'
</script>

<style scoped>
.nav-link {
  display: flex;
  align-items: center;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #6b7280;
  border-radius: 0.375rem;
  transition: all 0.2s;
  text-decoration: none;
}

.nav-link:hover {
  color: #111827;
  background-color: #f9fafb;
}

.nav-link-active {
  color: #2563eb;
  background-color: #eff6ff;
}
</style>