<template>
  <div class="log-list-page">
    <!-- 页面标题和操作栏 -->
    <div class="page-header">
      <div class="flex justify-between items-center">
        <h1 class="text-2xl font-bold text-gray-900">日志列表</h1>
      </div>
    </div>

    <!-- 搜索和筛选 -->
    <div class="filter-section">
      <el-card class="mb-6">
        <div class="flex flex-wrap items-center gap-3 w-full" style="gap: 0.75rem;">
          <el-input
            v-model="searchQuery"
            placeholder="搜索文件名或任务名称..."
            clearable
            @input="handleSearch"
            class="w-64"
            style="width: 280px"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <el-select
            v-model="logTypeFilter"
            placeholder="日志类型"
            clearable
            @change="handleLogTypeFilter"
            class="w-36"
            style="width: 150px"
          >
            <el-option label="协议栈日志" value="stack" />
            <el-option label="OAM与天线日志" value="oam_antenna" />
            <el-option label="全量日志" value="full" />
          </el-select>
          <el-select
            v-model="statusFilter"
            placeholder="状态筛选"
            clearable
            @change="handleStatusFilter"
            class="w-32"
            style="width: 130px"
          >
            <el-option label="待处理" value="pending" />
            <el-option label="处理中" value="processing" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            :shortcuts="dateShortcuts"
            value-format="YYYY-MM-DDTHH:mm:ss[Z]"
            class="w-80 flex-grow"
            style="width: 360px"
            @change="handleDateRangeChange"
            clearable
          />
          <div class="flex items-center gap-2">
            <el-button type="primary" @click="applyFilters">
              <el-icon class="mr-1"><Search /></el-icon>
              搜索
            </el-button>
            <el-button @click="resetFilters">
              重置
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 日志列表 -->
    <el-card>
      <div class="table-header mb-4">
        <!-- 记录统计信息与操作控件区域 - 同一行布局 -->
        <div class="header-row flex justify-between items-center mb-3">
          <!-- 记录统计信息 -->
          <div class="stats-info">
            <span class="text-sm text-gray-600">
              共 {{ logStore.pagination.total }} 条记录
            </span>
          </div>
          
          <!-- 操作控件区域 - 响应式布局 -->
          <div class="controls-container">
            <!-- 排序和基础操作 -->
            <div class="controls-row">
              <div class="sort-controls">
                <el-select v-model="sortBy" size="small" class="sort-select" @change="handleSortChange">
                  <el-option label="按创建时间" value="created_at" />
                  <el-option label="按文件大小" value="file_size" />
                  <el-option label="按更新时间" value="updated_at" />
                  <el-option label="按文件名" value="filename" />
                </el-select>
                <el-button @click="toggleSortOrder" size="small" class="sort-order-btn">
                  <el-icon class="mr-1"><Sort /></el-icon>
                  <span class="hidden sm:inline">{{ sortOrder === 'desc' ? '降序' : '升序' }}</span>
                  <span class="sm:hidden">{{ sortOrder === 'desc' ? '↓' : '↑' }}</span>
                </el-button>
              </div>
              
              <div class="basic-actions">
                <el-button @click="refreshData" size="small" class="refresh-btn">
                  <el-icon class="mr-1"><Refresh /></el-icon>
                  <span class="hidden sm:inline">刷新</span>
                </el-button>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 批量操作按钮 - 当有选中项时显示 -->
        <div v-if="selectedLogs.length > 0" class="batch-actions">
          <div class="batch-info">
            <span class="text-sm text-gray-600">已选择 {{ selectedLogs.length }} 项</span>
          </div>
          <div class="batch-buttons">
            <el-button
              type="danger"
              size="small"
              @click="handleBatchDelete"
              :disabled="hasProcessingInSelection"
              class="batch-delete-btn"
            >
              <span class="hidden sm:inline">批量删除 ({{ selectedLogs.length }})</span>
              <span class="sm:hidden">删除 ({{ selectedLogs.length }})</span>
            </el-button>
            <el-button
              type="primary"
              size="small"
              @click="handleBatchDownload"
              :disabled="eligibleDownloadIds.length === 0"
              class="batch-download-btn"
            >
              <span class="hidden sm:inline">批量下载 ({{ eligibleDownloadIds.length }})</span>
              <span class="sm:hidden">下载 ({{ eligibleDownloadIds.length }})</span>
            </el-button>
          </div>
        </div>
      </div>

      <el-table
        v-loading="logStore.loading"
        :data="logStore.logs"
        @selection-change="handleSelectionChange"
        class="w-full"
        :default-sort="{ prop: 'created_at', order: sortOrder === 'desc' ? 'descending' : 'ascending' }"
        @sort-change="onTableSortChange"
        border
        resizable
      >
        <el-table-column type="selection" width="55" resizable />

        <el-table-column prop="filename" label="文件名" min-width="300" :show-overflow-tooltip="true" resizable>
          <template #default="{ row }">
            <div class="flex items-center space-x-2 filename-cell">
              <el-icon class="text-blue-600 flex-shrink-0">
                <Document />
              </el-icon>
              <router-link
                :to="`/log/${row.id}`"
                class="text-blue-600 hover:text-blue-800 font-medium filename-link truncate"
                :title="getDisplayFilename(row)"
              >
                {{ getDisplayFilename(row) }}
              </router-link>
              <el-button link type="primary" size="small" class="flex-shrink-0 copy-link-btn" @click="copyLink(row)">
                <el-icon><CopyDocument /></el-icon>
              </el-button>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="log_type" label="日志类型" width="140" resizable>
          <template #default="{ row }">
            <el-tag :type="row.log_type === 'stack' ? 'success' : 'warning'">{{ logTypeText(row.log_type) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="file_size" label="文件大小" width="120" sortable="custom" resizable>
          <template #default="{ row }">
            {{ formatFileSize(row.file_size) }}
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" min-width="160" resizable>
          <template #default="{ row }">
            <div class="status-tags">
              <el-tag :type="getStatusColor(row.status)" size="small">
                {{ getStatusText(row.status) }}
              </el-tag>
              <el-tag
                v-if="isAIAnalysisCompleted(row)"
                type="success"
                effect="plain"
                size="small"
              >
                AI已分析
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column
          prop="metadata.service_name"
          label="研发分析"
          width="140"
          :show-overflow-tooltip="true"
          resizable
        >
          <template #default="{ row }">
            <span>{{ row.metadata?.service_name || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="download_count" label="下载次数" width="100" resizable>
        </el-table-column>

        <el-table-column prop="created_at" label="创建时间" width="180" sortable="custom" resizable>
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="260" fixed="right" resizable>
          <template #default="{ row }">
            <div class="flex space-x-2">
              <el-button
                type="primary"
                size="small"
                @click="handleDownload(row)"
                :disabled="row.status === 'processing'"
              >
                下载
              </el-button>
              <el-button
                size="small"
                @click="$router.push(`/log/${row.id}`)"
              >
                详情
              </el-button>
              <el-button
                type="danger"
                size="small"
                @click="handleDelete(row)"
                :disabled="row.status === 'processing'"
              >
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper mt-6">
        <el-pagination
          v-model:current-page="logStore.pagination.page"
          v-model:page-size="logStore.pagination.per_page"
          :total="logStore.pagination.total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleSizeChange"
          @current-change="handleCurrentChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useLogStore } from '../stores/logs'
import { useAppStore } from '../stores/app'
import { formatFileSize, formatDateTime, getStatusColor, getStatusText, downloadFile, debounce } from '../utils'
import { logApi } from '../api'
import type { LogRecord } from '../types'
import {
  Upload,
  Search,
  Refresh,
  Document,
  Sort,
  CopyDocument,
} from '@element-plus/icons-vue'

const logStore = useLogStore()
const appStore = useAppStore()

const searchQuery = ref('')
const statusFilter = ref('')
const logTypeFilter = ref('')
const dateRange = ref<string[] | null>(null)
const selectedLogs = ref<LogRecord[]>([])

const sortBy = ref<'created_at' | 'file_size' | 'updated_at' | 'filename'>(logStore.filters.sort_by)
const sortOrder = ref<'asc' | 'desc'>(logStore.filters.sort_order)

const dateShortcuts = [
  {
    text: '最近24小时',
    value: () => {
      const end = new Date()
      const start = new Date()
      start.setTime(start.getTime() - 3600 * 1000 * 24)
      return [start, end]
    },
  },
  {
    text: '最近7天',
    value: () => {
      const end = new Date()
      const start = new Date()
      start.setTime(start.getTime() - 3600 * 1000 * 24 * 7)
      return [start, end]
    },
  },
]

// 选中项中是否包含处理中
const hasProcessingInSelection = computed(() => selectedLogs.value.some(l => l.status === 'processing'))

// 仅统计可下载（已完成）的ID
const eligibleDownloadIds = computed(() => selectedLogs.value.filter(l => l.status === 'completed').map(l => l.id))

// 搜索防抖
const handleSearch = debounce(() => {
  console.log('🔍 [handleSearch] 搜索触发:', {
    searchQuery: searchQuery.value,
    timestamp: new Date().toLocaleTimeString()
  })
  logStore.setFilters({ search: searchQuery.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}, 500)

// 类型筛选
const handleLogTypeFilter = () => {
  logStore.setFilters({ log_type: logTypeFilter.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

// 状态筛选
const handleStatusFilter = () => {
  logStore.setFilters({ status: statusFilter.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

// 时间范围变更
const handleDateRangeChange = () => {
  if (!dateRange.value || dateRange.value.length !== 2) {
    logStore.setFilters({ start_time: '', end_time: '' })
  } else {
    const [start, end] = dateRange.value
    logStore.setFilters({ start_time: start, end_time: end })
  }
}

const applyFilters = () => {
  const filters = {
    search: searchQuery.value,
    status: statusFilter.value,
    log_type: logTypeFilter.value,
    start_time: dateRange.value?.[0] || '',
    end_time: dateRange.value?.[1] || '',
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
  }
  
  console.log('🎯 [applyFilters] 应用筛选条件:', {
    filters,
    dateRange: dateRange.value,
    timestamp: new Date().toLocaleTimeString()
  })
  
  logStore.setFilters(filters)
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

const resetFilters = () => {
  searchQuery.value = ''
  statusFilter.value = ''
  logTypeFilter.value = ''
  dateRange.value = null
  sortBy.value = 'created_at'
  sortOrder.value = 'desc'
  logStore.setFilters({
    search: '',
    status: '',
    log_type: '',
    start_time: '',
    end_time: '',
    sort_by: 'created_at',
    sort_order: 'desc',
  })
  logStore.setPagination({ page: 1, per_page: 10 })
  logStore.fetchLogs()
}

// 排序
const handleSortChange = () => {
  logStore.setFilters({ sort_by: sortBy.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

const toggleSortOrder = () => {
  const newOrder = sortOrder.value === 'asc' ? 'desc' : 'asc'
  sortOrder.value = newOrder
  logStore.setFilters({ sort_order: newOrder })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

const onTableSortChange = (sort: { prop: string; order: 'ascending' | 'descending' | null }) => {
  if (!sort.prop || !sort.order) return
  const order = sort.order === 'ascending' ? 'asc' : 'desc'
  const prop = (['created_at', 'file_size', 'updated_at', 'filename'].includes(sort.prop) ? sort.prop : 'created_at') as 'created_at' | 'file_size' | 'updated_at' | 'filename'
  sortBy.value = prop
  sortOrder.value = order
  logStore.setFilters({ sort_by: prop, sort_order: order })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

// 刷新数据
const refreshData = () => {
  console.log('🔄 [refreshData] 手动刷新数据开始')
  console.log('📊 当前状态:', {
    currentPage: logStore.pagination.page,
    pageSize: logStore.pagination.per_page,
    total: logStore.pagination.total,
    filters: logStore.filters,
    loading: logStore.loading
  })
  logStore.fetchLogs()
}

// 选择变化
const handleSelectionChange = (selection: LogRecord[]) => {
  selectedLogs.value = selection
}

// 分页变化
const handleSizeChange = (size: number) => {
  logStore.setPagination({ per_page: size })
  logStore.fetchLogs()
}

const handleCurrentChange = (page: number) => {
  logStore.setPagination({ page })
  logStore.fetchLogs()
}

// 下载文件 - 使用直接URL下载，立即触发
const handleDownload = async (log: LogRecord) => {
  try {
    // 直接使用URL下载，不需要等待响应，立即触发浏览器下载
    const downloadUrl = logApi.getDownloadUrl(log.id)
    downloadFile(downloadUrl, log.filename)
    
    appStore.showNotification({
      title: '下载开始',
      message: `文件 ${log.filename} 已开始下载`,
      type: 'success',
    })
    
    // 异步更新下载次数，不影响下载体验
    try {
      await logApi.incrementDownloadCount(log.id)
    } catch (error) {
      // 忽略计数更新失败，不影响用户体验
      console.warn('下载计数更新失败:', error)
    }
  } catch (error) {
    appStore.showNotification({
      title: '下载失败',
      message: '文件下载失败，请稍后重试',
      type: 'error',
    })
  }
}

// 复制链接
const copyLink = async (log: LogRecord) => {
  const link = `${window.location.origin}/log/${log.id}`
  try {
    await navigator.clipboard.writeText(link)
    ElMessage.success('链接已复制到剪贴板')
  } catch (error) {
    // 降级方案
    const textArea = document.createElement('textarea')
    textArea.value = link
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

// 批量下载
const handleBatchDownload = async () => {
  try {
    if (eligibleDownloadIds.value.length === 0) {
      ElMessage.warning('请选择已完成的文件进行打包下载')
      return
    }
    appStore.setLoading(true)
    const res = await logApi.batchDownloadLogs(eligibleDownloadIds.value)
    if (res.success && res.data) {
      const url = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8085') + res.data.download_url
      window.open(url, '_blank')
      appStore.showNotification({
        title: '打包成功',
        message: `正在下载 ${res.data.filename}`,
        type: 'success',
      })
    }
  } catch (e) {
    appStore.showNotification({
      title: '打包失败',
      message: '批量下载失败，请稍后重试',
      type: 'error',
    })
  } finally {
    appStore.setLoading(false)
  }
}

// 删除单个文件
const handleDelete = async (log: LogRecord) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除文件 "${log.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    await logStore.deleteLog(log.id)
    appStore.showNotification({
      title: '删除成功',
      message: `文件 ${log.filename} 已删除`,
      type: 'success',
    })
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

// 批量删除
const handleBatchDelete = async () => {
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedLogs.value.length} 个文件吗？此操作不可恢复。`,
      '确认批量删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    const ids = selectedLogs.value.map(log => log.id)
    await logStore.batchDeleteLogs(ids)
    selectedLogs.value = []
    appStore.showNotification({
      title: '批量删除成功',
      message: `已删除 ${ids.length} 个文件`,
      type: 'success',
    })
  } catch (error) {
    if (error !== 'cancel') {
      appStore.showNotification({
        title: '批量删除失败',
        message: '批量删除失败，请稍后重试',
        type: 'error',
      })
    }
  }
}

// 自动刷新处理中的状态
let timer: number | null = null
const startAutoRefresh = () => {
  console.log('⏰ [startAutoRefresh] 启动自动刷新定时器')
  stopAutoRefresh()
  timer = window.setInterval(() => {
    const hasProcessing = logStore.logs.some((l: any) => l.status === 'processing')
    const processingCount = logStore.logs.filter((l: any) => l.status === 'processing').length
    
    console.log('🔍 [autoRefresh] 检查处理中的任务:', {
      hasProcessing,
      processingCount,
      totalLogs: logStore.logs.length,
      timestamp: new Date().toLocaleTimeString()
    })
    
    if (hasProcessing) {
      console.log('🔄 [autoRefresh] 发现处理中的任务，触发自动刷新')
      logStore.fetchLogs()
    } else {
      console.log('✅ [autoRefresh] 无处理中的任务，跳过刷新')
    }
  }, 30000)
}
const stopAutoRefresh = () => {
  if (timer) {
    console.log('⏹️ [stopAutoRefresh] 停止自动刷新定时器')
    clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  console.log('🚀 [onMounted] LogList组件已挂载，开始初始化')
  console.log('📋 初始化参数:', {
    searchQuery: searchQuery.value,
    statusFilter: statusFilter.value,
    logTypeFilter: logTypeFilter.value,
    sortBy: sortBy.value,
    sortOrder: sortOrder.value
  })
  
  logStore.fetchLogs().then(() => {
    console.log('✅ [onMounted] 初始数据加载完成，启动自动刷新')
    startAutoRefresh()
  }).catch((error) => {
    console.error('❌ [onMounted] 初始数据加载失败:', error)
  })
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})

// 文本映射
const logTypeText = (t?: string) => {
  switch (t) {
    case 'oam_antenna':
      return 'OAM与天线日志'
    case 'full':
      return '全量日志'
    default:
      return '协议栈日志'
  }
}

// 获取显示用的文件名（去除日志ID前缀）
const getDisplayFilename = (row: LogRecord) => {
  console.group(`🔍 [getDisplayFilename] 处理文件名 - ID: ${row.id}`)
  console.log('📄 原始数据:', {
    id: row.id,
    filename: row.filename,
    original_filename: row.original_filename,
    log_type: row.log_type
  })
  
  // 如果有original_filename字段，优先使用
  if (row.original_filename) {
    console.log('✅ 使用 original_filename:', row.original_filename)
    console.groupEnd()
    return row.original_filename
  }
  
  // 否则从filename中提取，去除UUID前缀
  // 文件名格式通常是: {uuid}_{original_filename}
  const filename = row.filename
  const underscoreIndex = filename.indexOf('_')
  
  console.log('🔍 分析filename:', {
    filename,
    underscoreIndex,
    hasUnderscore: underscoreIndex > 0
  })
  
  if (underscoreIndex > 0) {
    // 检查下划线前的部分是否像UUID（包含连字符的36字符字符串）
    const prefix = filename.substring(0, underscoreIndex)
    const extractedName = filename.substring(underscoreIndex + 1)
    
    console.log('🧩 UUID检查:', {
      prefix,
      prefixLength: prefix.length,
      hasHyphen: prefix.includes('-'),
      isUUIDLike: prefix.length === 36 && prefix.includes('-'),
      extractedName
    })
    
    if (prefix.length === 36 && prefix.includes('-')) {
      console.log('✅ 检测到UUID前缀，返回提取的文件名:', extractedName)
      console.groupEnd()
      return extractedName
    }
  }
  
  // 如果不符合预期格式，返回原文件名
  console.log('⚠️ 不符合预期格式，返回原文件名:', filename)
  console.groupEnd()
  return filename
}

const isAIAnalysisCompleted = (log: LogRecord) => {
  const status = log.ai_analysis_status?.toLowerCase()
  if (status === 'completed' || status === 'succeeded') return true
  if (log.ai_analysis_result && status !== 'failed') return true
  return false
}
</script>

<style scoped>
.log-list-page > * + * {
  margin-top: 1.5rem;
}

.page-header {
  margin-bottom: 1.5rem;
}

.filter-section {
  margin-bottom: 1.5rem;
}

.table-header {
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 1rem;
}

.pagination-wrapper {
  display: flex;
  justify-content: center;
}

.status-tags {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-wrap: wrap;
}

/* 响应式控件容器 */
.controls-container {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* 基础控件行 */
.controls-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}

/* 排序控件组 */
.sort-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.sort-select {
  width: 10rem;
  min-width: 8rem;
  flex-shrink: 0;
}

.sort-order-btn {
  flex-shrink: 0;
}

/* 基础操作组 */
.basic-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.refresh-btn {
  flex-shrink: 0;
}

/* 批量操作区域 */
.batch-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.75rem;
  background-color: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 0.375rem;
}

.batch-info {
  flex-shrink: 0;
}

.batch-buttons {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.batch-delete-btn,
.batch-download-btn {
  flex-shrink: 0;
}

/* 小屏幕适配 */
@media (max-width: 640px) {
  .controls-row {
    flex-direction: column;
    align-items: stretch;
  }
  
  .sort-controls {
    justify-content: center;
  }
  
  .basic-actions {
    justify-content: center;
  }
  
  .batch-actions {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
  }
  
  .batch-buttons {
    justify-content: center;
  }
  
  .sort-select {
    width: 100%;
    max-width: 12rem;
  }
}

/* 中等屏幕适配 */
@media (max-width: 768px) {
  .controls-row {
    gap: 0.75rem;
  }
  
  .sort-controls,
  .basic-actions {
    flex: 1;
    min-width: 0;
  }
  
  .sort-controls {
    justify-content: flex-start;
  }
  
  .basic-actions {
    justify-content: flex-end;
  }
}

/* 大屏幕优化 */
@media (min-width: 1024px) {
  .controls-container {
    gap: 1rem;
  }
  
  .batch-actions {
    padding: 1rem;
  }
}

/* 确保表格在小屏幕上可以横向滚动 */
@media (max-width: 768px) {
  :deep(.el-table) {
    font-size: 0.875rem;
  }
  
  :deep(.el-table .el-table__cell) {
    padding: 8px 4px;
  }
}

/* 文件名列样式优化 */
.filename-cell {
  max-width: 100%;
  min-width: 0; /* 允许flex子项收缩 */
}

.filename-link {
  flex: 1;
  min-width: 0; /* 允许文本截断 */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

/* 响应式文件名显示 */
@media (max-width: 1024px) {
  .filename-link {
    max-width: 150px;
  }
}

@media (max-width: 768px) {
  .filename-link {
    max-width: 120px;
  }
}

@media (max-width: 640px) {
  .filename-link {
    max-width: 100px;
  }
}
</style>
