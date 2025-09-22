<template>
  <div class="upload-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="text-2xl font-bold text-gray-900 mb-2">上传日志文件</h1>
      <p class="text-gray-600">支持上传日志文件进行分析处理</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- 上传区域 -->
      <div class="upload-section">
        <el-card>
          <template #header>
            <div class="flex items-center space-x-2">
              <el-icon class="text-blue-600">
                <Upload />
              </el-icon>
              <span class="font-medium">文件上传</span>
            </div>
          </template>

          <div class="upload-area">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :on-change="handleFileChange"
              :on-remove="handleFileRemove"
              :before-upload="beforeUpload"
              :file-list="fileList"
              drag
              multiple
              class="upload-dragger"
            >
              <div class="upload-content">
                <el-icon class="upload-icon" size="48">
                  <UploadFilled />
                </el-icon>
                <div class="upload-text">
                  <p class="text-lg font-medium text-gray-700">
                    将文件拖拽到此处，或
                    <span class="text-blue-600">点击上传</span>
                  </p>
                  <p class="text-sm text-gray-500 mt-2">
                    支持 .log, .txt, .json, .tgz, .tar.gz 等格式，单个文件不超过 {{ maxFileSize }}MB
                  </p>
                </div>
              </div>
            </el-upload>

            <!-- 上传按钮 -->
            <div class="upload-actions mt-4">
              <el-button
                type="primary"
                size="large"
                :disabled="fileList.length === 0 || uploading"
                :loading="uploading"
                @click="handleUpload"
                class="w-full"
              >
                <el-icon class="mr-1" v-if="!uploading">
                  <Upload />
                </el-icon>
                {{ uploading ? '上传中...' : `上传文件 (${fileList.length})` }}
              </el-button>
            </div>
          </div>
        </el-card>

        <!-- 上传说明 -->
        <el-card class="mt-6">
          <template #header>
            <div class="flex items-center space-x-2">
              <el-icon class="text-green-600">
                <InfoFilled />
              </el-icon>
              <span class="font-medium">上传说明</span>
            </div>
          </template>

          <div class="upload-tips">
            <ul class="space-y-2 text-sm text-gray-600">
              <li class="flex items-start space-x-2">
                <el-icon class="text-green-500 mt-0.5" size="14">
                  <Check />
                </el-icon>
                <span>支持批量上传多个文件</span>
              </li>
              <li class="flex items-start space-x-2">
                <el-icon class="text-green-500 mt-0.5" size="14">
                  <Check />
                </el-icon>
                <span>支持 .log、.txt、.json、.tgz、.tar.gz 等格式</span>
              </li>
              <li class="flex items-start space-x-2">
                <el-icon class="text-green-500 mt-0.5" size="14">
                  <Check />
                </el-icon>
                <span>单个文件大小不超过 {{ maxFileSize }}MB</span>
              </li>
              <li class="flex items-start space-x-2">
                <el-icon class="text-green-500 mt-0.5" size="14">
                  <Check />
                </el-icon>
                <span>上传后将自动进行日志分析处理</span>
              </li>
            </ul>
          </div>
        </el-card>
      </div>

      <!-- 上传进度和历史 -->
      <div class="progress-section">
        <!-- 上传进度 -->
        <el-card v-if="uploadProgress.length > 0">
          <template #header>
            <div class="flex items-center space-x-2">
              <el-icon class="text-blue-600">
                <Loading />
              </el-icon>
              <span class="font-medium">上传进度</span>
            </div>
          </template>

          <div class="progress-list space-y-4">
            <div
              v-for="item in uploadProgress"
              :key="item.file.name"
              class="progress-item"
            >
              <div class="flex items-center justify-between mb-2">
                <span class="text-sm font-medium text-gray-700 truncate flex-1">
                  {{ item.file.name }}
                </span>
                <span class="text-sm text-gray-500 ml-2">
                  {{ item.progress }}%
                </span>
              </div>
              <el-progress
                :percentage="item.progress"
                :status="getProgressStatus(item.status)"
                :stroke-width="6"
              />
              <div v-if="item.error" class="text-xs text-red-500 mt-1">
                {{ item.error }}
              </div>
            </div>
          </div>
        </el-card>

        <!-- 最近上传 -->
        <el-card :class="{ 'mt-6': uploadProgress.length > 0 }">
          <template #header>
            <div class="flex items-center justify-between">
              <div class="flex items-center space-x-2">
                <el-icon class="text-green-600">
                  <Document />
                </el-icon>
                <span class="font-medium">最近上传</span>
              </div>
              <el-button
                type="text"
                size="small"
                @click="$router.push('/')"
              >
                查看全部
              </el-button>
            </div>
          </template>

          <div v-if="recentUploads.length > 0" class="recent-uploads space-y-3">
            <div
              v-for="log in recentUploads"
              :key="log.id"
              class="recent-item flex items-center justify-between p-3 bg-gray-50 rounded-lg"
            >
              <div class="flex items-center space-x-3">
                <el-icon class="text-blue-600">
                  <Document />
                </el-icon>
                <div>
                  <p class="text-sm font-medium text-gray-900">
                    {{ log.filename }}
                  </p>
                  <p class="text-xs text-gray-500">
                    {{ formatDateTime(log.upload_time) }}
                  </p>
                </div>
              </div>
              <div class="flex items-center space-x-2">
                <el-tag :type="getStatusColor(log.status)" size="small">
                  {{ getStatusText(log.status) }}
                </el-tag>
                <el-button
                  type="text"
                  size="small"
                  @click="$router.push(`/log/${log.id}`)"
                >
                  查看
                </el-button>
              </div>
            </div>
          </div>
          <div v-else class="text-center py-8 text-gray-500">
            <el-icon size="48" class="mb-2">
              <Document />
            </el-icon>
            <p>暂无上传记录</p>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile, UploadFiles, UploadInstance } from 'element-plus'
import { useLogStore } from '../stores/logs'
import { useAppStore } from '../stores/app'
import { formatDateTime, getStatusColor, getStatusText } from '../utils'
import type { UploadFile as CustomUploadFile } from '../types'
import {
  Upload,
  UploadFilled,
  InfoFilled,
  Check,
  Loading,
  Document,
} from '@element-plus/icons-vue'

const logStore = useLogStore()
const appStore = useAppStore()

const uploadRef = ref<UploadInstance>()
const fileList = ref<UploadFile[]>([])
const uploading = ref(false)
const uploadProgress = ref<CustomUploadFile[]>([])

const maxFileSize = computed(() => {
  return parseInt(import.meta.env.VITE_MAX_FILE_SIZE || '1024')
})

const recentUploads = computed(() => {
  return logStore.logs.slice(0, 5)
})

// 文件变化处理
const handleFileChange = (_file: UploadFile, files: UploadFiles) => {
  fileList.value = files
}

// 文件移除处理
const handleFileRemove = (_file: UploadFile, files: UploadFiles) => {
  fileList.value = files
}

// 上传前验证
const beforeUpload = (file: File) => {
  // 检查文件大小
  const isLtMaxSize = file.size / 1024 / 1024 < maxFileSize.value
  if (!isLtMaxSize) {
    ElMessage.error(`文件大小不能超过 ${maxFileSize.value}MB!`)
    return false
  }

  // 检查文件类型
  const allowedTypes = ['.log', '.txt', '.json', '.tgz']
  const fileName = file.name.toLowerCase()
  
  // 检查是否为支持的格式
  const isValidType = allowedTypes.some(type => fileName.endsWith(type)) || 
                     fileName.endsWith('.tar.gz')
  
  if (!isValidType) {
    ElMessage.error('只支持 .log、.txt、.json、.tgz、.tar.gz 格式的文件!')
    return false
  }

  return true
}

// 获取进度状态
const getProgressStatus = (status: string) => {
  const statusMap: Record<string, any> = {
    pending: undefined,
    uploading: undefined,
    success: 'success',
    error: 'exception',
  }
  return statusMap[status]
}

// 处理上传
const handleUpload = async () => {
  if (fileList.value.length === 0) {
    ElMessage.warning('请先选择要上传的文件')
    return
  }

  uploading.value = true
  uploadProgress.value = fileList.value.map((file: UploadFile) => ({
    file: file.raw!,
    progress: 0,
    status: 'pending',
  }))

  try {
    for (let i = 0; i < uploadProgress.value.length; i++) {
      const item = uploadProgress.value[i]
      item.status = 'uploading'

      try {
        await logStore.uploadLog(item.file, (progress: number) => {
          item.progress = progress
        })

        item.status = 'success'
        item.progress = 100

        appStore.showNotification({
          title: '上传成功',
          message: `文件 ${item.file.name} 上传成功`,
          type: 'success',
        })
      } catch (error) {
        item.status = 'error'
        item.error = '上传失败'

        appStore.showNotification({
          title: '上传失败',
          message: `文件 ${item.file.name} 上传失败`,
          type: 'error',
        })
      }
    }

    // 清空文件列表
    fileList.value = []
    uploadRef.value?.clearFiles()

    // 延迟清空进度
    setTimeout(() => {
      uploadProgress.value = []
    }, 3000)

  } finally {
    uploading.value = false
  }
}

onMounted(() => {
  // 获取最近上传的文件
  logStore.fetchLogs({ page: 1, size: 5 })
})
</script>

<style scoped>
@reference "tailwindcss";

.upload-page {
  @apply space-y-6;
}

.page-header {
  @apply mb-8;
}

.upload-area {
  @apply space-y-4;
}

.upload-dragger {
  @apply w-full;
}

.upload-content {
  @apply text-center py-12;
}

.upload-icon {
  @apply text-gray-400 mb-4;
}

.upload-text {
  @apply space-y-2;
}

.upload-actions {
  @apply pt-4 border-t border-gray-200;
}

.upload-tips ul {
  @apply list-none;
}

.progress-item {
  @apply p-4 bg-gray-50 rounded-lg;
}

.recent-item {
  @apply transition-colors hover:bg-gray-100;
}
</style>