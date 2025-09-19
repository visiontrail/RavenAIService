<template>
  <div class="log-detail-page min-h-screen bg-gray-50">
    <!-- 导航栏 -->
    <header class="bg-white shadow-sm border-b border-gray-200">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex items-center justify-between h-16">
          <!-- 返回按钮和Logo -->
          <div class="flex items-center space-x-4">
            <el-button 
              @click="$router.back()" 
              type="text" 
              class="text-gray-600 hover:text-gray-900"
            >
              <el-icon class="mr-2" size="18">
                <ArrowLeft />
              </el-icon>
              返回列表
            </el-button>
            <div class="h-8 w-px bg-gray-300"></div>
            <div class="flex items-center space-x-2">
              <el-icon class="text-blue-600" size="24">
                <Document />
              </el-icon>
              <span class="text-lg font-semibold text-gray-900">日志管理系统</span>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- 主要内容区域 -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div v-if="logStore.loading" class="loading-container">
        <el-skeleton :rows="8" animated />
      </div>

      <div v-else-if="logStore.currentLog" class="space-y-6">
        <!-- 日志标题区域 -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between space-y-4 sm:space-y-0">
            <div class="flex-1">
              <div class="flex items-center space-x-3 mb-2">
                <h1 class="text-2xl font-bold text-gray-900 truncate">
                  {{ logStore.currentLog.filename }}
                </h1>
                <el-tag 
                  :type="getLogTypeTagType(logStore.currentLog.log_type)"
                  size="large"
                  class="ml-2"
                >
                  {{ getLogTypeLabel(logStore.currentLog.log_type) }}
                </el-tag>
              </div>
              <p class="text-sm text-gray-500">
                文件ID: {{ logStore.currentLog.id }}
              </p>
            </div>
            <!-- 状态指示器 -->
            <div class="flex items-center space-x-2">
              <el-tag 
                :type="getStatusTagType(logStore.currentLog.status)"
                size="large"
                :effect="logStore.currentLog.status === 'processing' ? 'plain' : 'dark'"
              >
                <el-icon v-if="logStore.currentLog.status === 'processing'" class="mr-1">
                  <Loading />
                </el-icon>
                {{ getStatusLabel(logStore.currentLog.status) }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 基本信息卡片 -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div class="flex items-center space-x-2 mb-6">
            <el-icon class="text-blue-600" size="20">
              <InfoFilled />
            </el-icon>
            <h2 class="text-lg font-semibold text-gray-900">基本信息</h2>
          </div>
          
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <!-- 文件名 -->
            <div class="space-y-2">
              <label class="text-sm font-medium text-gray-500">文件名</label>
              <div class="text-sm text-gray-900 font-mono bg-gray-50 p-2 rounded border">
                {{ logStore.currentLog.filename }}
              </div>
            </div>

            <!-- 原始文件名 -->
            <div class="space-y-2" v-if="logStore.currentLog.original_filename">
              <label class="text-sm font-medium text-gray-500">原始文件名</label>
              <div class="text-sm text-gray-900 bg-gray-50 p-2 rounded border">
                {{ logStore.currentLog.original_filename }}
              </div>
            </div>

            <!-- 文件大小 -->
            <div class="space-y-2">
              <label class="text-sm font-medium text-gray-500">文件大小</label>
              <div class="text-sm text-gray-900 font-semibold">
                {{ formatFileSize(logStore.currentLog.file_size) }}
              </div>
            </div>

            <!-- 创建时间 -->
            <div class="space-y-2">
              <label class="text-sm font-medium text-gray-500">创建时间</label>
              <div class="text-sm text-gray-900">
                {{ formatDateTime(logStore.currentLog.created_at) }}
              </div>
            </div>

            <!-- 更新时间 -->
            <div class="space-y-2">
              <label class="text-sm font-medium text-gray-500">更新时间</label>
              <div class="text-sm text-gray-900">
                {{ formatDateTime(logStore.currentLog.updated_at) }}
              </div>
            </div>

            <!-- 处理状态 -->
            <div class="space-y-2">
              <label class="text-sm font-medium text-gray-500">处理状态</label>
              <div>
                <el-tag 
                  :type="getStatusTagType(logStore.currentLog.status)"
                  size="default"
                >
                  <el-icon v-if="logStore.currentLog.status === 'processing'" class="mr-1">
                    <Loading />
                  </el-icon>
                  {{ getStatusLabel(logStore.currentLog.status) }}
                </el-tag>
              </div>
            </div>

            <!-- 协议栈日志处理进度 -->
            <div class="space-y-2 md:col-span-2 lg:col-span-3" v-if="logStore.currentLog.log_type === 'stack' && logStore.currentLog.status === 'processing'">
              <label class="text-sm font-medium text-gray-500">处理进度</label>
              <div class="space-y-2">
                <el-progress 
                  :percentage="logStore.currentLog.progress || 0" 
                  :status="logStore.currentLog.progress === 100 ? 'success' : undefined"
                  :stroke-width="8"
                />
                <div class="text-xs text-gray-500">
                  {{ logStore.currentLog.progress || 0 }}% 完成
                </div>
              </div>
            </div>

            <!-- 下载次数 -->
            <div class="space-y-2">
              <label class="text-sm font-medium text-gray-500">下载次数</label>
              <div class="text-sm text-gray-900 font-semibold">
                {{ logStore.currentLog.download_count }}
              </div>
            </div>
          </div>
        </div>

        <!-- AI分析结果区域（预留） -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div class="flex items-center space-x-2 mb-6">
            <el-icon class="text-purple-600" size="20">
              <MagicStick />
            </el-icon>
            <h2 class="text-lg font-semibold text-gray-900">AI分析结果</h2>
            <el-tag type="info" size="small">预留功能</el-tag>
          </div>
          
          <div class="text-center py-12">
            <el-icon class="text-gray-300 mb-4" size="48">
              <MagicStick />
            </el-icon>
            <p class="text-gray-500 mb-4">AI分析功能即将上线</p>
            <p class="text-sm text-gray-400">将为您提供智能日志分析、异常检测和优化建议</p>
          </div>
        </div>

        <!-- 操作按钮组 -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <div class="flex items-center space-x-2 mb-6">
            <el-icon class="text-green-600" size="20">
              <Operation />
            </el-icon>
            <h2 class="text-lg font-semibold text-gray-900">操作</h2>
          </div>
          
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <!-- 下载按钮 -->
            <el-button 
              type="primary" 
              @click="handleDownload"
              :loading="downloadLoading"
              class="w-full"
            >
              <el-icon class="mr-2">
                <Download />
              </el-icon>
              下载文件
            </el-button>

            <!-- 删除按钮 -->
            <el-button 
              type="danger" 
              @click="handleDelete"
              :loading="deleteLoading"
              class="w-full"
            >
              <el-icon class="mr-2">
                <Delete />
              </el-icon>
              删除文件
            </el-button>

            <!-- 分享页面按钮 -->
            <el-button 
              type="success" 
              @click="handleShare"
              class="w-full"
            >
              <el-icon class="mr-2">
                <Share />
              </el-icon>
              分享页面
            </el-button>

            <!-- 复制链接按钮 -->
            <el-button 
              type="info" 
              @click="handleCopyLink"
              class="w-full"
            >
              <el-icon class="mr-2">
                <CopyDocument />
              </el-icon>
              复制链接
            </el-button>

            <!-- AI分析按钮 -->
            <el-button 
              type="warning" 
              @click="handleAIAnalysis"
              disabled
              class="w-full"
            >
              <el-icon class="mr-2">
                <MagicStick />
              </el-icon>
              AI分析
              <el-tag type="info" size="small" class="ml-2">敬请期待</el-tag>
            </el-button>
          </div>
        </div>
      </div>
      <!-- 文件不存在（必须与 v-if/v-else-if 同级且紧随其后） -->
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
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useLogStore } from '../stores/logs'
import { useAppStore } from '../stores/app'
import { 
  formatFileSize, 
  formatDateTime, 
  formatRelativeTime,
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
  InfoFilled,
  MagicStick,
  Share,
  CopyDocument,
  Loading,
} from '@element-plus/icons-vue'

interface Props {
  id: string
}

const props = defineProps<Props>()
const route = useRoute()
const router = useRouter()
const logStore = useLogStore()
const appStore = useAppStore()

// 响应式变量
const downloadLoading = ref(false)
const deleteLoading = ref(false)

// 计算属性
const pageTitle = computed(() => {
  if (logStore.currentLog) {
    return `${logStore.currentLog.filename} - 日志详情`
  }
  return '日志详情'
})

// 获取日志类型标签类型
const getLogTypeTagType = (logType?: string) => {
  switch (logType) {
    case 'stack':
      return 'primary'
    case 'oam_antenna':
      return 'success'
    default:
      return 'info'
  }
}

// 获取日志类型标签文本
const getLogTypeLabel = (logType?: string) => {
  switch (logType) {
    case 'stack':
      return '协议栈日志'
    case 'oam_antenna':
      return 'OAM天线日志'
    default:
      return '未知类型'
  }
}

// 获取状态标签类型
const getStatusTagType = (status: string) => {
  switch (status) {
    case 'completed':
      return 'success'
    case 'processing':
      return 'warning'
    case 'failed':
      return 'danger'
    case 'pending':
      return 'info'
    default:
      return 'info'
  }
}

// 获取状态标签文本
const getStatusLabel = (status: string) => {
  switch (status) {
    case 'completed':
      return '处理完成'
    case 'processing':
      return '处理中'
    case 'failed':
      return '处理失败'
    case 'pending':
      return '等待处理'
    default:
      return '未知状态'
  }
}

// 下载文件
const handleDownload = async () => {
  if (!logStore.currentLog) return

  try {
    downloadLoading.value = true
    const blob = await logApi.downloadLog(logStore.currentLog.id)
    downloadFile(blob, logStore.currentLog.filename)
    ElMessage.success(`文件 ${logStore.currentLog.filename} 已开始下载`)
    
    // 更新下载次数
    if (logStore.currentLog) {
      logStore.currentLog.download_count += 1
    }
  } catch (error) {
    ElMessage.error('文件下载失败，请稍后重试')
  } finally {
    downloadLoading.value = false
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
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: false,
      }
    )

    deleteLoading.value = true
    await logStore.deleteLog(logStore.currentLog.id)
    ElMessage.success(`文件 ${logStore.currentLog.filename} 已删除`)
    router.push('/')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('文件删除失败，请稍后重试')
    }
  } finally {
    deleteLoading.value = false
  }
}

// 分享页面
const handleShare = async () => {
  if (!logStore.currentLog) return

  const shareData = {
    title: `日志文件: ${logStore.currentLog.filename}`,
    text: `查看日志文件详情 - ${logStore.currentLog.filename}\n文件大小: ${formatFileSize(logStore.currentLog.file_size)}\n状态: ${getStatusLabel(logStore.currentLog.status)}`,
    url: window.location.href
  }

  try {
    if (navigator.share && navigator.canShare && navigator.canShare(shareData)) {
      await navigator.share(shareData)
      ElMessage.success('分享成功')
    } else {
      // 降级到复制链接
      await handleCopyLink()
    }
  } catch (error) {
    if (error.name !== 'AbortError') {
      ElMessage.error('分享失败，请稍后重试')
    }
  }
}

// 复制链接
const handleCopyLink = async () => {
  try {
    await navigator.clipboard.writeText(window.location.href)
    ElMessage.success('链接已复制到剪贴板')
  } catch (error) {
    // 降级方案
    const textArea = document.createElement('textarea')
    textArea.value = window.location.href
    document.body.appendChild(textArea)
    textArea.select()
    try {
      document.execCommand('copy')
      ElMessage.success('链接已复制到剪贴板')
    } catch (err) {
      ElMessage.error('复制失败，请手动复制链接')
    }
    document.body.removeChild(textArea)
  }
}

// AI分析（预留功能）
const handleAIAnalysis = () => {
  ElMessage.info('AI分析功能即将上线，敬请期待！')
}

// SEO优化和页面标题设置
const updatePageMeta = () => {
  if (logStore.currentLog) {
    // 设置页面标题
    document.title = pageTitle.value
    
    // 设置meta描述
    const metaDescription = document.querySelector('meta[name="description"]')
    if (metaDescription) {
      metaDescription.setAttribute('content', 
        `查看日志文件 ${logStore.currentLog.filename} 的详细信息，文件大小 ${formatFileSize(logStore.currentLog.file_size)}，状态 ${getStatusLabel(logStore.currentLog.status)}`
      )
    } else {
      const meta = document.createElement('meta')
      meta.name = 'description'
      meta.content = `查看日志文件 ${logStore.currentLog.filename} 的详细信息，文件大小 ${formatFileSize(logStore.currentLog.file_size)}，状态 ${getStatusLabel(logStore.currentLog.status)}`
      document.head.appendChild(meta)
    }

    // 设置Open Graph标签
    const setOGMeta = (property: string, content: string) => {
      let meta = document.querySelector(`meta[property="${property}"]`)
      if (meta) {
        meta.setAttribute('content', content)
      } else {
        meta = document.createElement('meta')
        meta.setAttribute('property', property)
        meta.setAttribute('content', content)
        document.head.appendChild(meta)
      }
    }

    setOGMeta('og:title', pageTitle.value)
    setOGMeta('og:description', `查看日志文件详情 - ${logStore.currentLog.filename}`)
    setOGMeta('og:url', window.location.href)
    setOGMeta('og:type', 'website')
  }
}

onMounted(async () => {
  const id = props.id || route.params.id as string
  if (id) {
    await logStore.fetchLogDetail(id)
    updatePageMeta()
  }
})
</script>

<style scoped>
.log-detail {
  @apply min-h-screen bg-gray-50;
}

.detail-header {
  @apply bg-white border-b border-gray-200 px-6 py-4;
}

.header-content {
  @apply max-w-7xl mx-auto flex items-center justify-between;
}

.back-button {
  @apply flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors;
}

.header-title {
  @apply text-xl font-semibold text-gray-900;
}

.detail-main {
  @apply max-w-7xl mx-auto px-6 py-8;
}

.title-section {
  @apply mb-8;
}

.log-title {
  @apply text-3xl font-bold text-gray-900 mb-4;
}

.log-meta {
  @apply flex flex-wrap items-center gap-4;
}

.content-grid {
  @apply grid grid-cols-1 lg:grid-cols-3 gap-8;
}

.main-content {
  @apply lg:col-span-2 space-y-6;
}

.sidebar {
  @apply space-y-6;
}

.info-grid {
  @apply grid grid-cols-1 sm:grid-cols-2 gap-4;
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

.action-buttons {
  @apply flex flex-wrap gap-3;
}

.ai-analysis {
  @apply bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg p-6;
}

.ai-placeholder {
  @apply text-center py-8;
}

.ai-icon {
  @apply text-4xl mb-4;
}

.not-found {
  @apply flex items-center justify-center min-h-96;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .detail-header {
    @apply px-4 py-3;
  }
  
  .detail-main {
    @apply px-4 py-6;
  }
  
  .log-title {
    @apply text-2xl;
  }
  
  .content-grid {
    @apply grid-cols-1;
  }
  
  .action-buttons {
    @apply flex-col;
  }
  
  .action-buttons .el-button {
    @apply w-full;
  }
}
</style>