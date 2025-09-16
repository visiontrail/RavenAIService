<template>
  <div class="log-detail-page">
    <!-- 返回按钮 -->
    <div class="back-button mb-6">
      <el-button @click="$router.back()">
        <el-icon class="mr-1">
          <ArrowLeft />
        </el-icon>
        返回
      </el-button>
    </div>

    <div v-if="logStore.loading" class="loading-container">
      <el-skeleton :rows="8" animated />
    </div>

    <div v-else-if="logStore.currentLog" class="log-content">
      <!-- 文件信息卡片 -->
      <el-card class="mb-6">
        <template #header>
          <div class="flex items-center justify-between">
            <div class="flex items-center space-x-3">
              <el-icon class="text-blue-600" size="24">
                <Document />
              </el-icon>
              <div>
                <h1 class="text-xl font-bold text-gray-900">
                  {{ logStore.currentLog.filename }}
                </h1>
                <p class="text-sm text-gray-500">
                  文件ID: {{ logStore.currentLog.id }}
                </p>
              </div>
            </div>
            <div class="flex items-center space-x-2">
              <el-button type="primary" @click="handleDownload">
                <el-icon class="mr-1">
                  <Download />
                </el-icon>
                下载文件
              </el-button>
              <el-button type="danger" @click="handleDelete">
                <el-icon class="mr-1">
                  <Delete />
                </el-icon>
                删除
              </el-button>
            </div>
          </div>
        </template>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <div class="info-item">
            <div class="info-label">文件大小</div>
            <div class="info-value">
              {{ formatFileSize(logStore.currentLog.file_size) }}
            </div>
          </div>

          <div class="info-item">
            <div class="info-label">状态</div>
            <div class="info-value">
              <el-tag :type="getStatusColor(logStore.currentLog.status)">
                {{ getStatusText(logStore.currentLog.status) }}
              </el-tag>
            </div>
          </div>

          <div class="info-item">
            <div class="info-label">下载次数</div>
            <div class="info-value">
              {{ logStore.currentLog.download_count }}
            </div>
          </div>

          <div class="info-item">
            <div class="info-label">上传时间</div>
            <div class="info-value">
              {{ formatDateTime(logStore.currentLog.upload_time) }}
            </div>
          </div>
        </div>
      </el-card>

      <!-- 任务信息卡片 -->
      <el-card v-if="logStore.currentLog.task_id" class="mb-6">
        <template #header>
          <div class="flex items-center space-x-2">
            <el-icon class="text-green-600">
              <Operation />
            </el-icon>
            <span class="font-medium">任务信息</span>
          </div>
        </template>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div class="info-item">
            <div class="info-label">任务ID</div>
            <div class="info-value font-mono text-sm">
              {{ logStore.currentLog.task_id }}
            </div>
          </div>

          <div class="info-item">
            <div class="info-label">任务名称</div>
            <div class="info-value">
              {{ logStore.currentLog.task_name || '-' }}
            </div>
          </div>

          <div class="info-item md:col-span-2">
            <div class="info-label">任务描述</div>
            <div class="info-value">
              {{ logStore.currentLog.task_description || '-' }}
            </div>
          </div>
        </div>
      </el-card>

      <!-- 时间信息卡片 -->
      <el-card class="mb-6">
        <template #header>
          <div class="flex items-center space-x-2">
            <el-icon class="text-purple-600">
              <Clock />
            </el-icon>
            <span class="font-medium">时间信息</span>
          </div>
        </template>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div class="info-item">
            <div class="info-label">创建时间</div>
            <div class="info-value">
              {{ formatDateTime(logStore.currentLog.created_at) }}
            </div>
            <div class="info-relative">
              {{ formatRelativeTime(logStore.currentLog.created_at) }}
            </div>
          </div>

          <div class="info-item">
            <div class="info-label">更新时间</div>
            <div class="info-value">
              {{ formatDateTime(logStore.currentLog.updated_at) }}
            </div>
            <div class="info-relative">
              {{ formatRelativeTime(logStore.currentLog.updated_at) }}
            </div>
          </div>
        </div>
      </el-card>

      <!-- 操作历史 -->
      <el-card>
        <template #header>
          <div class="flex items-center space-x-2">
            <el-icon class="text-orange-600">
              <List />
            </el-icon>
            <span class="font-medium">操作历史</span>
          </div>
        </template>

        <el-timeline>
          <el-timeline-item
            timestamp="刚刚"
            type="primary"
          >
            查看文件详情
          </el-timeline-item>
          
          <el-timeline-item
            v-if="logStore.currentLog.download_count > 0"
            :timestamp="formatDateTime(logStore.currentLog.updated_at)"
            type="success"
          >
            文件被下载 {{ logStore.currentLog.download_count }} 次
          </el-timeline-item>

          <el-timeline-item
            v-if="logStore.currentLog.task_id"
            :timestamp="formatDateTime(logStore.currentLog.updated_at)"
            type="warning"
          >
            任务处理完成
          </el-timeline-item>

          <el-timeline-item
            :timestamp="formatDateTime(logStore.currentLog.upload_time)"
            type="info"
          >
            文件上传成功
          </el-timeline-item>

          <el-timeline-item
            :timestamp="formatDateTime(logStore.currentLog.created_at)"
            type="info"
          >
            创建文件记录
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </div>

    <!-- 文件不存在 -->
    <div v-else class="not-found">
      <el-result
        icon="warning"
        title="文件不存在"
        sub-title="请检查文件ID是否正确，或文件可能已被删除"
      >
        <template #extra>
          <el-button type="primary" @click="$router.push('/')">
            返回列表
          </el-button>
        </template>
      </el-result>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useLogStore } from '../stores/logs'
import { useAppStore } from '../stores/app'
import { 
  formatFileSize, 
  formatDateTime, 
  formatRelativeTime,
  getStatusColor, 
  getStatusText, 
  downloadFile 
} from '../utils'
import { logApi } from '../api'
import {
  ArrowLeft,
  Document,
  Download,
  Delete,
  Operation,
  Clock,
  List,
} from '@element-plus/icons-vue'

interface Props {
  id: string
}

const props = defineProps<Props>()
const route = useRoute()
const router = useRouter()
const logStore = useLogStore()
const appStore = useAppStore()

// 下载文件
const handleDownload = async () => {
  if (!logStore.currentLog) return

  try {
    appStore.setLoading(true)
    const blob = await logApi.downloadLog(logStore.currentLog.id)
    downloadFile(blob, logStore.currentLog.filename)
    appStore.showNotification({
      title: '下载成功',
      message: `文件 ${logStore.currentLog.filename} 已开始下载`,
      type: 'success',
    })
  } catch (error) {
    appStore.showNotification({
      title: '下载失败',
      message: '文件下载失败，请稍后重试',
      type: 'error',
    })
  } finally {
    appStore.setLoading(false)
  }
}

// 删除文件
const handleDelete = async () => {
  if (!logStore.currentLog) return

  try {
    await ElMessageBox.confirm(
      `确定要删除文件 "${logStore.currentLog.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    await logStore.deleteLog(logStore.currentLog.id)
    appStore.showNotification({
      title: '删除成功',
      message: `文件 ${logStore.currentLog.filename} 已删除`,
      type: 'success',
    })
    router.push('/')
  } catch (error) {
    if (error !== 'cancel') {
      appStore.showNotification({
        title: '删除失败',
        message: '文件删除失败，请稍后重试',
        type: 'error',
      })
    }
  }
}

onMounted(() => {
  const id = props.id || route.params.id as string
  if (id) {
    logStore.fetchLogDetail(id)
  }
})
</script>

<style scoped>
.log-detail-page {
  @apply max-w-6xl mx-auto;
}

.loading-container {
  @apply space-y-6;
}

.log-content {
  @apply space-y-6;
}

.info-item {
  @apply space-y-1;
}

.info-label {
  @apply text-sm font-medium text-gray-500;
}

.info-value {
  @apply text-base text-gray-900;
}

.info-relative {
  @apply text-xs text-gray-400;
}

.not-found {
  @apply flex items-center justify-center min-h-96;
}
</style>