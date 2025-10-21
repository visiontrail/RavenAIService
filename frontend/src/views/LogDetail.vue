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
            <!-- <div class="space-y-2">
              <label class="text-sm font-medium text-gray-500">更新时间</label>
              <div class="text-sm text-gray-900">
                {{ formatDateTime(logStore.currentLog.updated_at) }}
              </div>
            </div> -->

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
            <div class="space-y-2 md:col-span-2 lg:col-span-3" v-if="(logStore.currentLog.log_type === 'stack' || logStore.currentLog.log_type === 'full') && logStore.currentLog.status === 'processing'">
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
            <!-- 文件校验和 -->
            <div class="space-y-2 md:col-span-2" v-if="logStore.currentLog.checksum">
              <label class="text-sm font-medium text-gray-500">文件校验和 (SHA256)</label>
              <div class="text-xs text-gray-900 font-mono bg-gray-50 p-3 rounded border break-all leading-relaxed">
                {{ logStore.currentLog.checksum }}
              </div>
            </div>

            <!-- 任务ID -->
            <div class="space-y-2" v-if="logStore.currentLog.task_id">
              <label class="text-sm font-medium text-gray-500">任务ID</label>
              <div class="text-sm text-gray-900 font-mono bg-gray-50 p-2 rounded border">
                {{ logStore.currentLog.task_id }}
              </div>
            </div>

            <!-- 重试次数 -->
            <div class="space-y-2" v-if="logStore.currentLog.retry_count !== undefined && logStore.currentLog.retry_count > 0">
              <label class="text-sm font-medium text-gray-500">重试次数</label>
              <div class="text-sm text-gray-900 font-semibold">
                {{ logStore.currentLog.retry_count }}
              </div>
            </div>

            <!-- 处理开始时间 -->
            <!-- <div class="space-y-2" v-if="logStore.currentLog.processing_started_at">
              <label class="text-sm font-medium text-gray-500">处理开始时间</label>
              <div class="text-sm text-gray-900">
                {{ formatDateTime(logStore.currentLog.processing_started_at) }}
              </div>
            </div> -->

            <!-- 处理完成时间 -->
            <!-- <div class="space-y-2" v-if="logStore.currentLog.processed_at">
              <label class="text-sm font-medium text-gray-500">处理完成时间</label>
              <div class="text-sm text-gray-900">
                {{ formatDateTime(logStore.currentLog.processed_at) }}
              </div>
            </div> -->

            <!-- 问题描述 -->
            <div class="space-y-2 md:col-span-2 lg:col-span-3" v-if="logStore.currentLog.issue_description">
              <label class="text-sm font-medium text-gray-500">问题描述</label>
              <div class="text-sm text-gray-900 bg-blue-50 p-3 rounded border border-blue-200">
                {{ logStore.currentLog.issue_description }}
              </div>
            </div>

            <!-- 错误信息 -->
            <div class="space-y-2 md:col-span-2 lg:col-span-3" v-if="logStore.currentLog.error_message">
              <label class="text-sm font-medium text-gray-500">错误信息</label>
              <div class="text-sm text-red-700 bg-red-50 p-3 rounded border border-red-200">
                {{ logStore.currentLog.error_message }}
              </div>
            </div>

            <!-- 元数据信息 -->
            <div class="space-y-2 md:col-span-2 lg:col-span-3" v-if="logStore.currentLog.metadata && hasMetadata(logStore.currentLog.metadata)">
              <label class="text-sm font-medium text-gray-500">元数据信息</label>
              <div class="bg-gray-50 p-3 rounded border">
                <!-- 日志来源 -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div v-if="logStore.currentLog.metadata.source" class="space-y-1">
                    <label class="text-xs font-medium text-gray-400">日志来源</label>
                    <div class="text-sm text-gray-900">{{ logStore.currentLog.metadata.source }}</div>
                  </div>
                  
                  <!-- 环境信息 -->
                  <div v-if="logStore.currentLog.metadata.environment" class="space-y-1">
                    <label class="text-xs font-medium text-gray-400">环境信息</label>
                    <div class="text-sm text-gray-900">{{ logStore.currentLog.metadata.environment }}</div>
                  </div>
                  
                  <!-- 服务名称 -->
                  <div v-if="logStore.currentLog.metadata.service_name" class="space-y-1">
                    <label class="text-xs font-medium text-gray-400">研发分析</label>
                    <div class="text-sm text-gray-900">{{ logStore.currentLog.metadata.service_name }}</div>
                  </div>
                  
                  <!-- 版本信息 -->
                  <div v-if="logStore.currentLog.metadata.version_info || logStore.currentLog.metadata.version" class="space-y-1 md:col-span-2">
                    <label class="text-xs font-medium text-gray-400">版本信息</label>
                    
                    <!-- 如果有详细的版本信息 -->
                    <div v-if="logStore.currentLog.metadata.version_info && logStore.currentLog.metadata.version_info.raw_content" class="version-info-container">
                      <el-collapse v-model="activeVersionCollapse" class="version-collapse">
                        <el-collapse-item title="GNB系统组件版本详情" name="version-details">
                          <template #title>
                            <div class="flex items-center space-x-2">
                              <el-icon class="text-blue-600">
                                <InfoFilled />
                              </el-icon>
                              <span class="font-medium">GNB系统组件版本详情</span>
                              <el-tag size="small" type="info">{{ getVersionBoardCount(logStore.currentLog.metadata.version_info.raw_content) }}个板卡</el-tag>
                            </div>
                          </template>
                          
                          <div class="version-content">
                            <div v-for="(board, index) in parseVersionInfo(logStore.currentLog.metadata.version_info.raw_content)" :key="index" class="board-info mb-6 last:mb-0">
                              <!-- 板卡标题 -->
                              <div class="board-header flex items-center justify-between p-4 bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 mb-3">
                                <div class="flex items-center space-x-3">
                                  <el-icon class="text-blue-600" size="20">
                                    <Cpu />
                                  </el-icon>
                                  <div>
                                    <h4 class="font-semibold text-gray-900">{{ board.title }}</h4>
                                    <p class="text-sm text-gray-600">Slot ID: {{ board.slotId }} | CPU ID: {{ board.cpuId }}</p>
                                  </div>
                                </div>
                                <el-tag :type="board.type === 'main' ? 'success' : 'info'" size="small">
                                  {{ board.type === 'main' ? '主控板' : '子板' }}
                                </el-tag>
                              </div>
                              
                              <!-- 版本详情 -->
                              <div class="board-details grid grid-cols-1 md:grid-cols-2 gap-4">
                                <!-- OAM版本 -->
                                <div v-if="board.oamVersion" class="version-section bg-white p-4 rounded-lg border border-gray-200">
                                  <div class="flex items-center space-x-2 mb-3">
                                    <el-icon class="text-green-600" size="16">
                                      <Setting />
                                    </el-icon>
                                    <h5 class="font-medium text-gray-900">OAM版本</h5>
                                  </div>
                                  <div class="space-y-2 text-sm">
                                    <div class="flex justify-between">
                                      <span class="text-gray-600">版本号:</span>
                                      <span class="font-mono text-gray-900">{{ board.oamVersion.version }}</span>
                                    </div>
                                    <div class="flex justify-between">
                                      <span class="text-gray-600">Git版本:</span>
                                      <span class="font-mono text-gray-900">{{ board.oamVersion.gitVersion }}</span>
                                    </div>
                                    <div class="flex justify-between">
                                      <span class="text-gray-600">分支:</span>
                                      <span class="font-mono text-gray-900">{{ board.oamVersion.branch }}</span>
                                    </div>
                                    <div class="flex justify-between">
                                      <span class="text-gray-600">构建时间:</span>
                                      <span class="font-mono text-gray-900">{{ board.oamVersion.buildTime }}</span>
                                    </div>
                                  </div>
                                </div>
                                
                                <!-- 协议栈版本 -->
                                <div v-if="board.protocolVersion" class="version-section bg-white p-4 rounded-lg border border-gray-200">
                                  <div class="flex items-center space-x-2 mb-3">
                                    <el-icon class="text-purple-600" size="16">
                                      <Connection />
                                    </el-icon>
                                    <h5 class="font-medium text-gray-900">协议栈版本</h5>
                                  </div>
                                  <div class="space-y-2 text-sm">
                                    <div v-if="board.protocolVersion.cucp" class="flex justify-between">
                                      <span class="text-gray-600">CUCP版本:</span>
                                      <span class="font-mono text-gray-900">{{ board.protocolVersion.cucp }}</span>
                                    </div>
                                    <div v-if="board.protocolVersion.status" class="flex justify-between">
                                      <span class="text-gray-600">状态:</span>
                                      <el-tag size="small" :type="board.protocolVersion.status === 'Not applicable for this SOM type' ? 'info' : 'success'">
                                        {{ board.protocolVersion.status }}
                                      </el-tag>
                                    </div>
                                  </div>
                                </div>
                                
                                <!-- FPGA版本 -->
                                <div v-if="board.fpgaVersion" class="version-section bg-white p-4 rounded-lg border border-gray-200">
                                  <div class="flex items-center space-x-2 mb-3">
                                    <el-icon class="text-orange-600" size="16">
                                      <Cpu />
                                    </el-icon>
                                    <h5 class="font-medium text-gray-900">FPGA版本</h5>
                                  </div>
                                  <div class="text-sm">
                                    <el-tag size="small" type="warning">{{ board.fpgaVersion }}</el-tag>
                                  </div>
                                </div>
                                
                                <!-- 组件数量 -->
                                <div v-if="board.componentCount" class="version-section bg-white p-4 rounded-lg border border-gray-200">
                                  <div class="flex items-center space-x-2 mb-3">
                                    <el-icon class="text-blue-600" size="16">
                                      <Grid />
                                    </el-icon>
                                    <h5 class="font-medium text-gray-900">组件信息</h5>
                                  </div>
                                  <div class="text-sm">
                                    <div class="flex justify-between">
                                      <span class="text-gray-600">组件数量:</span>
                                      <span class="font-semibold text-blue-600">{{ board.componentCount }}</span>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    
                    <!-- 如果只有简单版本号 -->
                    <div v-else-if="logStore.currentLog.metadata.version" class="text-sm text-gray-900 font-mono bg-gray-50 p-2 rounded border">
                      {{ logStore.currentLog.metadata.version }}
                    </div>
                  </div>
                </div>
                
                <!-- 标签列表 -->
                <div v-if="logStore.currentLog.metadata.tags && logStore.currentLog.metadata.tags.length > 0" class="mt-3 space-y-1">
                  <label class="text-xs font-medium text-gray-400">标签</label>
                  <div class="flex flex-wrap gap-1">
                    <el-tag 
                      v-for="tag in logStore.currentLog.metadata.tags" 
                      :key="tag" 
                      size="small" 
                      type="info"
                    >
                      {{ tag }}
                    </el-tag>
                  </div>
                </div>
                
                <!-- 额外字段 -->
                <!-- <div v-if="logStore.currentLog.metadata.extra_fields && Object.keys(logStore.currentLog.metadata.extra_fields).length > 0" class="mt-3 space-y-1">
                  <label class="text-xs font-medium text-gray-400">额外字段</label>
                  <div class="text-xs text-gray-700 font-mono bg-white p-2 rounded border">
                    {{ JSON.stringify(logStore.currentLog.metadata.extra_fields, null, 2) }}
                  </div>
                </div> -->
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
  Cpu,
  Setting,
  Connection,
  Grid,
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
const activeVersionCollapse = ref(['version-details'])

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
    case 'full':
      return 'warning'
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
    case 'full':
      return '全量日志'
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

// 获取日志级别标签类型
const getLogLevelTagType = (logLevel?: string) => {
  switch (logLevel) {
    case 'fatal':
    case 'error':
      return 'danger'
    case 'warn':
      return 'warning'
    case 'info':
      return 'primary'
    case 'debug':
      return 'info'
    default:
      return 'info'
  }
}

// 获取日志级别标签文本
const getLogLevelLabel = (logLevel?: string) => {
  switch (logLevel) {
    case 'fatal':
      return '致命错误'
    case 'error':
      return '错误'
    case 'warn':
      return '警告'
    case 'info':
      return '信息'
    case 'debug':
      return '调试'
    default:
      return '未知级别'
  }
}

// 检查是否有元数据内容
const hasMetadata = (metadata: any) => {
  if (!metadata || typeof metadata !== 'object') return false
  
  return !!(
    metadata.source ||
    metadata.environment ||
    metadata.service_name ||
    metadata.version ||
    (metadata.tags && metadata.tags.length > 0) ||
    (metadata.extra_fields && Object.keys(metadata.extra_fields).length > 0)
  )
}

// 解析版本信息
const parseVersionInfo = (rawContent: string) => {
  const boards = []
  const sections = rawContent.split('-----------------------------------------------------------------')
  
  for (const section of sections) {
    if (!section.trim()) continue
    
    const lines = section.split('\n').map(line => line.trim()).filter(line => line)
    
    let board: any = {
      title: '',
      slotId: '',
      cpuId: '',
      type: 'sub',
      oamVersion: null,
      protocolVersion: null,
      fpgaVersion: null,
      componentCount: null
    }
    
    // 解析板卡信息
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]
      
      if (line.includes('[Main Control Board Information]')) {
        board.title = 'Main Control Board Information'
        board.type = 'main'
      } else if (line.includes('[Sub Board Information]')) {
        board.title = 'Sub Board Information'
        board.type = 'sub'
      } else if (line.startsWith('Slot ID:')) {
        board.slotId = line.split(':')[1]?.trim()
      } else if (line.startsWith('CPU ID:')) {
        board.cpuId = line.split(':')[1]?.trim()
      } else if (line.startsWith('Component Count:')) {
        board.componentCount = line.split(':')[1]?.trim()
      } else if (line.includes('[OAM Version]')) {
        // 解析OAM版本信息
        board.oamVersion = {}
        for (let j = i + 1; j < lines.length && !lines[j].startsWith('['); j++) {
          const versionLine = lines[j]
          if (versionLine.startsWith('version:')) {
            board.oamVersion.version = versionLine.split(':')[1]?.trim()
          } else if (versionLine.startsWith('git version:')) {
            board.oamVersion.gitVersion = versionLine.split(':')[1]?.trim()
          } else if (versionLine.startsWith('branch:')) {
            board.oamVersion.branch = versionLine.split(':')[1]?.trim()
          } else if (versionLine.startsWith('build time:')) {
            board.oamVersion.buildTime = versionLine.split(':')[1]?.trim()
          }
        }
      } else if (line.includes('[CUCP Protocol Stack Version]') || line.includes('[Protocol Stack Version]')) {
        // 解析协议栈版本信息
        board.protocolVersion = {}
        for (let j = i + 1; j < lines.length && !lines[j].startsWith('['); j++) {
          const protocolLine = lines[j]
          if (protocolLine.startsWith('cucp_version=')) {
            board.protocolVersion.cucp = protocolLine.split('=')[1]?.trim()
          } else if (protocolLine.includes('Not applicable for this SOM type')) {
            board.protocolVersion.status = 'Not applicable for this SOM type'
          }
        }
      } else if (line.includes('[MOM FPGA Version]')) {
        // 解析FPGA版本信息
        for (let j = i + 1; j < lines.length && !lines[j].startsWith('['); j++) {
          const fpgaLine = lines[j]
          if (fpgaLine.trim() && !fpgaLine.includes('Unavailable')) {
            board.fpgaVersion = fpgaLine.trim()
          } else if (fpgaLine.includes('Unavailable')) {
            board.fpgaVersion = 'Unavailable'
          }
        }
      }
    }
    
    // 只添加有效的板卡信息
    if (board.slotId && board.cpuId) {
      boards.push(board)
    }
  }
  
  return boards
}

// 获取版本信息中的板卡数量
const getVersionBoardCount = (rawContent: string) => {
  const boards = parseVersionInfo(rawContent)
  return boards.length
}

// 下载文件 - 使用直接URL下载，立即触发
const handleDownload = async () => {
  if (!logStore.currentLog) return

  try {
    downloadLoading.value = true
    
    // 直接使用URL下载，立即触发浏览器下载
    const downloadUrl = logApi.getDownloadUrl(logStore.currentLog.id)
    downloadFile(downloadUrl, logStore.currentLog.filename)
    ElMessage.success(`文件 ${logStore.currentLog.filename} 已开始下载`)
    
    // 异步更新下载次数，不影响下载体验
    try {
      const response = await logApi.incrementDownloadCount(logStore.currentLog.id)
      // 更新本地下载次数
      if (logStore.currentLog && response.data?.data?.download_count) {
        logStore.currentLog.download_count = response.data.data.download_count
      }
    } catch (error) {
      // 忽略计数更新失败，不影响用户体验
      console.warn('下载计数更新失败:', error)
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
@reference "tailwindcss";

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

/* 版本信息样式 */
.version-info-container {
  @apply mt-2;
}

.version-collapse {
  @apply border border-gray-200 rounded-lg overflow-hidden;
}

.version-collapse :deep(.el-collapse-item__header) {
  @apply bg-gray-50 px-4 py-3 border-b border-gray-200;
}

.version-collapse :deep(.el-collapse-item__content) {
  @apply p-4 bg-white;
}

.board-info {
  @apply border border-gray-100 rounded-lg p-4 bg-gray-50;
}

.board-header {
  @apply shadow-sm;
}

.version-section {
  @apply shadow-sm hover:shadow-md transition-shadow duration-200;
}

.version-section h5 {
  @apply text-sm;
}

/* 响应式版本信息 */
@media (max-width: 768px) {
  .board-details {
    @apply grid-cols-1;
  }
  
  .version-section {
    @apply p-3;
  }
  
  .board-header {
    @apply flex-col items-start space-y-2;
  }
  
  .board-header > div:first-child {
    @apply space-x-2;
  }
}
</style>