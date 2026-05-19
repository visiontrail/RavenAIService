<template>
  <div class="rw-page">
    <WorkbenchTopbar title="日志列表" :meta="`${logStore.pagination.total} 条记录`">
      <template #actions>
        <button class="rw-btn-secondary" @click="refreshData" :disabled="logStore.loading">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 0 1-9 9 9 9 0 0 1-6.36-2.64L3 16" />
            <path d="M3 12a9 9 0 0 1 9-9 9 9 0 0 1 6.36 2.64L21 8" />
            <path d="M21 3v5h-5" />
            <path d="M3 21v-5h5" />
          </svg>
          <span>刷新</span>
        </button>
      </template>
    </WorkbenchTopbar>

    <div class="rw-page-scroll">
      <!-- Desktop filter card -->
      <section class="rw-card filter-card desktop-only">
        <div class="filter-row">
          <el-input
            v-model="searchQuery"
            placeholder="搜索文件名或任务名称..."
            clearable
            @input="handleSearch"
            class="filter-input filter-search"
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
            class="filter-input filter-type"
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
            class="filter-input filter-status"
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
            class="filter-input filter-date"
            @change="handleDateRangeChange"
            clearable
          />
          <div class="filter-actions">
            <button class="rw-btn-primary" @click="applyFilters">搜索</button>
            <button class="rw-btn-secondary" @click="resetFilters">重置</button>
          </div>
        </div>
      </section>

      <!-- Mobile compact search -->
      <section class="rw-card mobile-only">
        <div class="mobile-search-row">
          <el-input
            v-model="searchQuery"
            placeholder="搜索文件名或任务名称..."
            clearable
            @input="handleSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
          <button class="rw-btn-secondary" @click="mobileFilterDrawerVisible = true">筛选</button>
        </div>
      </section>

      <!-- Batch action bar -->
      <div v-if="selectedLogs.length > 0" class="batch-bar">
        <span class="batch-info">已选择 {{ selectedLogs.length }} 项</span>
        <div class="batch-buttons">
          <button
            class="rw-btn-danger"
            @click="handleBatchDelete"
            :disabled="hasProcessingInSelection"
          >
            批量删除 ({{ selectedLogs.length }})
          </button>
          <button
            class="rw-btn-primary"
            @click="handleBatchDownload"
            :disabled="eligibleDownloadIds.length === 0"
          >
            批量下载 ({{ eligibleDownloadIds.length }})
          </button>
        </div>
      </div>

      <!-- Desktop table card -->
      <section class="rw-card table-card desktop-only">
        <div class="table-toolbar">
          <div class="sort-controls">
            <el-select v-model="sortBy" size="small" class="sort-select" @change="handleSortChange">
              <el-option label="按创建时间" value="created_at" />
              <el-option label="按文件大小" value="file_size" />
              <el-option label="按更新时间" value="updated_at" />
              <el-option label="按文件名" value="filename" />
            </el-select>
            <button class="rw-btn-secondary sort-toggle" @click="toggleSortOrder">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 6h18" />
                <path d="M7 12h10" />
                <path d="M11 18h4" />
              </svg>
              <span>{{ sortOrder === 'desc' ? '降序' : '升序' }}</span>
            </button>
          </div>
        </div>

        <div class="table-scroll-wrapper">
          <el-table
            v-loading="logStore.loading"
            :data="logStore.logs"
            @selection-change="handleSelectionChange"
            class="w-full"
            :default-sort="{ prop: 'created_at', order: sortOrder === 'desc' ? 'descending' : 'ascending' }"
            @sort-change="onTableSortChange"
            :border="false"
            resizable
          >
            <el-table-column type="selection" width="55" resizable />

            <el-table-column prop="filename" label="文件名" min-width="300" :show-overflow-tooltip="true" resizable>
              <template #default="{ row }">
                <div class="filename-cell">
                  <router-link
                    :to="`/log/${row.id}`"
                    class="filename-link"
                    :title="getDisplayFilename(row)"
                  >
                    {{ getDisplayFilename(row) }}
                  </router-link>
                  <button class="rw-icon-btn copy-btn" @click="copyLink(row)" title="复制链接">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                    </svg>
                  </button>
                </div>
              </template>
            </el-table-column>

            <el-table-column prop="log_type" label="日志类型" width="140" resizable>
              <template #default="{ row }">
                <span :class="['rw-pill', row.log_type === 'stack' ? 'rw-pill-success' : 'rw-pill-warning']">
                  {{ logTypeText(row.log_type) }}
                </span>
              </template>
            </el-table-column>

            <el-table-column prop="file_size" label="文件大小" width="120" sortable="custom" resizable>
              <template #default="{ row }">
                <span class="mono-cell">{{ formatFileSize(row.file_size) }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="status" label="状态" min-width="180" resizable>
              <template #default="{ row }">
                <div class="status-tags">
                  <span :class="['rw-pill', pillKindForStatus(row.status)]">
                    {{ getStatusDisplayText(row) }}
                  </span>
                  <span v-if="isAIAnalysisCompleted(row)" class="rw-pill rw-pill-preview">
                    AI已分析
                  </span>
                  <span v-if="hasManualAnalysis(row)" class="rw-pill rw-pill-info">
                    人工已分析
                  </span>
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
                <span class="muted-cell">{{ row.metadata?.service_name || '-' }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="download_count" label="下载次数" width="100" resizable>
              <template #default="{ row }">
                <span class="mono-cell">{{ row.download_count ?? 0 }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="created_at" label="创建时间" width="180" sortable="custom" resizable>
              <template #default="{ row }">
                <span class="mono-cell">{{ formatDateTime(row.created_at) }}</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="260" fixed="right" resizable>
              <template #default="{ row }">
                <div class="row-actions">
                  <button
                    class="rw-btn-primary rw-btn-xs"
                    @click="handleDownload(row)"
                    :disabled="row.status === 'processing'"
                  >
                    下载
                  </button>
                  <button
                    class="rw-btn-secondary rw-btn-xs"
                    @click="$router.push(`/log/${row.id}`)"
                  >
                    详情
                  </button>
                  <button
                    class="rw-btn-danger rw-btn-xs"
                    @click="handleDelete(row)"
                    :disabled="row.status === 'processing'"
                  >
                    删除
                  </button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="pagination-wrapper">
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
      </section>

      <!-- Mobile list -->
      <div class="mobile-only mobile-list-wrap">
        <div v-loading="logStore.loading">
          <div v-if="logStore.logs.length" class="mobile-log-list">
            <article v-for="row in logStore.logs" :key="row.id" class="mobile-log-card">
              <div class="mobile-log-card-head">
                <router-link :to="`/log/${row.id}`" class="mobile-log-name" :title="getDisplayFilename(row)">
                  {{ getDisplayFilename(row) }}
                </router-link>
              </div>

              <div class="mobile-log-tags">
                <span :class="['rw-pill', pillKindForStatus(row.status)]">
                  {{ getStatusDisplayText(row) }}
                </span>
                <span :class="['rw-pill', row.log_type === 'stack' ? 'rw-pill-success' : 'rw-pill-warning']">
                  {{ logTypeText(row.log_type) }}
                </span>
                <span v-if="isAIAnalysisCompleted(row)" class="rw-pill rw-pill-preview">AI已分析</span>
                <span v-if="hasManualAnalysis(row)" class="rw-pill rw-pill-info">人工已分析</span>
              </div>

              <div class="mobile-log-meta">
                <span>{{ formatFileSize(row.file_size) }}</span>
                <span>{{ formatDateTime(row.created_at) }}</span>
              </div>

              <div class="mobile-log-actions">
                <button class="rw-btn-secondary" @click="$router.push(`/log/${row.id}`)">详情</button>
                <button class="rw-btn-primary" :disabled="row.status === 'processing'" @click="handleDownload(row)">
                  下载
                </button>
              </div>
            </article>
          </div>
          <el-empty v-else description="暂无日志记录" />

          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="logStore.pagination.page"
              v-model:page-size="logStore.pagination.per_page"
              :total="logStore.pagination.total"
              :page-sizes="[10, 20, 50, 100]"
              layout="prev, pager, next"
              @size-change="handleSizeChange"
              @current-change="handleCurrentChange"
            />
          </div>
        </div>
      </div>
    </div>

    <el-drawer v-model="mobileFilterDrawerVisible" title="筛选日志" direction="btt" size="70%">
      <div class="mobile-filter-drawer">
        <el-select
          v-model="logTypeFilter"
          placeholder="日志类型"
          clearable
          @change="handleLogTypeFilter"
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
          @change="handleDateRangeChange"
          clearable
        />
        <el-select v-model="sortBy" placeholder="排序字段" @change="handleSortChange">
          <el-option label="按创建时间" value="created_at" />
          <el-option label="按文件大小" value="file_size" />
          <el-option label="按更新时间" value="updated_at" />
          <el-option label="按文件名" value="filename" />
        </el-select>
        <el-segmented
          v-model="sortOrder"
          :options="[
            { label: '降序', value: 'desc' },
            { label: '升序', value: 'asc' },
          ]"
          @change="applyFilters"
        />
        <div class="mobile-filter-actions">
          <button class="rw-btn-secondary" @click="resetFilters">重置</button>
          <button class="rw-btn-primary" @click="applyFilters(); mobileFilterDrawerVisible = false">应用</button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useLogStore } from '../stores/logs'
import { useAppStore } from '../stores/app'
import { formatFileSize, formatDateTime, getStatusText, downloadFile, debounce } from '../utils'
import { logApi } from '../api'
import type { LogRecord } from '../types'
import { Search } from '@element-plus/icons-vue'
import WorkbenchTopbar from '@/layouts/WorkbenchTopbar.vue'

const logStore = useLogStore()
const appStore = useAppStore()

const searchQuery = ref('')
const statusFilter = ref('')
const logTypeFilter = ref('')
const dateRange = ref<string[] | null>(null)
const selectedLogs = ref<LogRecord[]>([])
const mobileFilterDrawerVisible = ref(false)

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

const hasProcessingInSelection = computed(() => selectedLogs.value.some(l => l.status === 'processing'))
const eligibleDownloadIds = computed(() => selectedLogs.value.filter(l => l.status === 'completed').map(l => l.id))

const handleSearch = debounce(() => {
  logStore.setFilters({ search: searchQuery.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}, 500)

const handleLogTypeFilter = () => {
  logStore.setFilters({ log_type: logTypeFilter.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

const handleStatusFilter = () => {
  logStore.setFilters({ status: statusFilter.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

const handleDateRangeChange = () => {
  if (!dateRange.value || dateRange.value.length !== 2) {
    logStore.setFilters({ start_time: '', end_time: '' })
  } else {
    const [start, end] = dateRange.value
    logStore.setFilters({ start_time: start, end_time: end })
  }
}

const applyFilters = () => {
  logStore.setFilters({
    search: searchQuery.value,
    status: statusFilter.value,
    log_type: logTypeFilter.value,
    start_time: dateRange.value?.[0] || '',
    end_time: dateRange.value?.[1] || '',
    sort_by: sortBy.value,
    sort_order: sortOrder.value,
  })
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

const refreshData = () => {
  logStore.fetchLogs()
}

const handleSelectionChange = (selection: LogRecord[]) => {
  selectedLogs.value = selection
}

const handleSizeChange = (size: number) => {
  logStore.setPagination({ per_page: size })
  logStore.fetchLogs()
}

const handleCurrentChange = (page: number) => {
  logStore.setPagination({ page })
  logStore.fetchLogs()
}

const handleDownload = async (log: LogRecord) => {
  try {
    const downloadUrl = logApi.getDownloadUrl(log.id)
    downloadFile(downloadUrl, log.filename)

    appStore.showNotification({
      title: '下载开始',
      message: `文件 ${log.filename} 已开始下载`,
      type: 'success',
    })

    try {
      await logApi.incrementDownloadCount(log.id)
    } catch (error) {
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

const copyLink = async (log: LogRecord) => {
  const link = `${window.location.origin}/log/${log.id}`
  try {
    await navigator.clipboard.writeText(link)
    ElMessage.success('链接已复制到剪贴板')
  } catch (error) {
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

let timer: number | null = null
const startAutoRefresh = () => {
  stopAutoRefresh()
  timer = window.setInterval(() => {
    const hasProcessing = logStore.logs.some((l: any) => l.status === 'processing')
    if (hasProcessing) {
      logStore.fetchLogs()
    }
  }, 30000)
}
const stopAutoRefresh = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  logStore.fetchLogs().then(() => {
    startAutoRefresh()
  }).catch((error) => {
    console.error('初始数据加载失败:', error)
  })
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})

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

const getDisplayFilename = (row: LogRecord) => {
  if (row.original_filename) return row.original_filename
  const filename = row.filename
  const underscoreIndex = filename.indexOf('_')
  if (underscoreIndex > 0) {
    const prefix = filename.substring(0, underscoreIndex)
    if (prefix.length === 36 && prefix.includes('-')) {
      return filename.substring(underscoreIndex + 1)
    }
  }
  return filename
}

const isAIAnalysisCompleted = (log: LogRecord) => {
  const status = log.ai_analysis_status?.toLowerCase()
  if (status === 'completed' || status === 'succeeded') return true
  if (log.ai_analysis_result && status !== 'failed') return true
  return false
}

const getStatusDisplayText = (log: LogRecord) => {
  const isDecompressedLog = (log.log_type === 'stack' || log.log_type === 'full') && log.status === 'completed'
  if (isDecompressedLog) return '已解压'
  return getStatusText(log.status)
}

const hasManualAnalysis = (log: LogRecord) => {
  return Boolean(log.manual_analysis && log.manual_analysis.trim())
}

const pillKindForStatus = (status?: string) => {
  switch (status) {
    case 'completed':
      return 'rw-pill-success'
    case 'processing':
      return 'rw-pill-warning'
    case 'failed':
      return 'rw-pill-danger'
    case 'pending':
      return 'rw-pill-info'
    default:
      return 'rw-pill-neutral'
  }
}
</script>

<style scoped>
.rw-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--rw-canvas);
  font-family: var(--rw-sans);
  color: var(--rw-ink);
}

.rw-page-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 24px 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.rw-card {
  background: var(--rw-surface-card);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.desktop-only { display: block; }
.mobile-only { display: none; }

/* Buttons */
.rw-btn-primary,
.rw-btn-secondary,
.rw-btn-danger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  font-family: var(--rw-sans);
  cursor: pointer;
  transition: background-color 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  white-space: nowrap;
  border: none;
  line-height: 1;
}

.rw-btn-primary {
  background: var(--rw-primary);
  color: var(--rw-on-primary);
}
.rw-btn-primary:hover:not(:disabled) { background: var(--rw-primary-active); }

.rw-btn-secondary {
  background: var(--rw-canvas);
  color: var(--rw-ink);
  border: 1px solid var(--rw-hairline-strong);
}
.rw-btn-secondary:hover:not(:disabled) { background: var(--rw-surface-strong); }

.rw-btn-danger {
  background: #c0382b;
  color: #fff;
}
.rw-btn-danger:hover:not(:disabled) { background: #a02f24; }

.rw-btn-primary:disabled,
.rw-btn-secondary:disabled,
.rw-btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.rw-btn-xs {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
  border-radius: 6px;
}

.rw-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--rw-body);
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.rw-icon-btn:hover { background: var(--rw-surface-strong); color: var(--rw-ink); }

/* Pills */
.rw-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.2px;
  white-space: nowrap;
  line-height: 1;
}
.rw-pill-success { background: rgba(22, 163, 74, 0.12); color: #15803d; }
.rw-pill-info { background: var(--rw-surface-strong); color: var(--rw-ink); }
.rw-pill-warning { background: rgba(171, 100, 0, 0.10); color: #ab6400; }
.rw-pill-danger { background: rgba(192, 56, 43, 0.10); color: #c0382b; }
.rw-pill-neutral { background: var(--rw-surface-strong); color: var(--rw-body); }
.rw-pill-preview { background: rgba(129, 69, 181, 0.10); color: #8145b5; }

/* Filter card */
.filter-card { padding: 16px 20px; }
.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.filter-input { flex-shrink: 0; }
.filter-search { width: 280px; }
.filter-type { width: 160px; }
.filter-status { width: 140px; }
.filter-date { width: 360px; min-width: 240px; flex: 1; }
.filter-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* Mobile search row */
.mobile-search-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  align-items: center;
}

/* Batch bar */
.batch-bar {
  background: var(--rw-surface-strong);
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.batch-info { font-size: 13px; color: var(--rw-body); font-weight: 500; }
.batch-buttons { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

/* Table card */
.table-card { padding: 16px 20px 20px; }
.table-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--rw-hairline);
  margin-bottom: 6px;
}
.sort-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sort-select { width: 160px; }
.sort-toggle { height: 32px; }

.table-scroll-wrapper { width: 100%; }

/* Filename / cells */
.filename-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 100%;
}
.filename-link {
  color: var(--rw-ink);
  font-weight: 500;
  text-decoration: none;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
  font-size: 13px;
}
.filename-link:hover {
  text-decoration: underline;
  text-decoration-color: var(--rw-ink);
}
.copy-btn { flex-shrink: 0; }

.mono-cell {
  font-family: var(--rw-mono);
  font-size: 12.5px;
  color: var(--rw-body);
}
.muted-cell { color: var(--rw-body); font-size: 13px; }

.status-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* Pagination */
.pagination-wrapper {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}

/* Mobile list */
.mobile-list-wrap { display: none; }
.mobile-log-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mobile-log-card {
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  padding: 14px;
  background: var(--rw-canvas);
}
.mobile-log-card-head { min-width: 0; }
.mobile-log-name {
  display: block;
  font-weight: 600;
  color: var(--rw-ink);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}
.mobile-log-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.mobile-log-meta {
  margin-top: 10px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-family: var(--rw-mono);
  font-size: 12.5px;
  color: var(--rw-body);
}
.mobile-log-actions {
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

/* Mobile filter drawer */
.mobile-filter-drawer {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 0 16px;
}
.mobile-filter-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-top: 4px;
}

/* Element Plus overrides */
:deep(.el-input__wrapper),
:deep(.el-select .el-select__wrapper),
:deep(.el-range-editor.el-input__wrapper) {
  background: var(--rw-canvas) !important;
  border: 1px solid var(--rw-hairline-strong) !important;
  border-radius: 8px !important;
  box-shadow: none !important;
  padding: 0 12px;
  min-height: 36px;
  transition: border-color 0.15s ease;
}
:deep(.el-input__wrapper.is-focus),
:deep(.el-select .el-select__wrapper.is-focused),
:deep(.el-range-editor.el-input__wrapper.is-focus) {
  border-color: var(--rw-ink) !important;
  box-shadow: none !important;
}
:deep(.el-input__inner) {
  color: var(--rw-ink);
  font-family: var(--rw-sans);
  font-size: 13px;
}
:deep(.el-input__inner::placeholder) {
  color: var(--rw-muted);
}

/* Table overrides */
:deep(.el-table) {
  background: var(--rw-canvas);
  font-size: 13px;
  color: var(--rw-ink);
  --el-table-border-color: var(--rw-hairline);
  --el-table-header-bg-color: var(--rw-canvas-soft);
  --el-table-row-hover-bg-color: var(--rw-hairline-soft);
}
:deep(.el-table::before),
:deep(.el-table::after) {
  display: none;
}
:deep(.el-table th.el-table__cell) {
  background: var(--rw-canvas-soft);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  font-size: 10.5px;
  color: var(--rw-muted);
  font-weight: 600;
  padding: 12px 12px;
  border-bottom-color: var(--rw-hairline);
}
:deep(.el-table td.el-table__cell) {
  padding: 14px 12px;
  border-bottom-color: var(--rw-hairline-soft);
}
:deep(.el-table .el-table__cell.is-leaf) {
  border-bottom-color: var(--rw-hairline-soft);
}
:deep(.el-table .sort-caret.ascending) { border-bottom-color: var(--rw-body); }
:deep(.el-table .sort-caret.descending) { border-top-color: var(--rw-body); }
:deep(.el-table .ascending .sort-caret.ascending) { border-bottom-color: var(--rw-ink); }
:deep(.el-table .descending .sort-caret.descending) { border-top-color: var(--rw-ink); }

/* Pagination overrides */
:deep(.el-pagination) {
  font-size: 13px;
  color: var(--rw-body);
  --el-pagination-button-color: var(--rw-ink);
  --el-pagination-hover-color: var(--rw-ink);
}
:deep(.el-pagination .btn-prev),
:deep(.el-pagination .btn-next),
:deep(.el-pagination .el-pager li) {
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 6px;
  color: var(--rw-ink);
  margin: 0 2px;
  min-width: 30px;
  height: 30px;
}
:deep(.el-pagination .el-pager li.is-active) {
  background: var(--rw-ink);
  color: var(--rw-on-primary);
  border-color: var(--rw-ink);
}
:deep(.el-pagination .el-pager li:hover:not(.is-active)) {
  color: var(--rw-ink);
  background: var(--rw-surface-strong);
}

/* Drawer */
:deep(.el-drawer__header) {
  margin-bottom: 16px;
  padding: 16px 16px 0;
  color: var(--rw-ink);
  font-weight: 600;
}
:deep(.el-drawer__body) { padding: 0; }

/* Empty */
:deep(.el-empty__description p) { color: var(--rw-muted); font-size: 13px; }

/* Responsive */
@media (max-width: 1024px) {
  .filename-link { max-width: 200px; }
}

@media (max-width: 900px) {
  .rw-page-scroll { padding: 16px; gap: 16px; }
}

@media (max-width: 768px) {
  .desktop-only { display: none; }
  .mobile-only { display: block; }
  .mobile-list-wrap { display: block; }

  .table-scroll-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .filter-row { gap: 8px; }
  .filter-search,
  .filter-type,
  .filter-status,
  .filter-date {
    width: 100%;
    min-width: 0;
  }
  .filter-actions {
    width: 100%;
    margin-left: 0;
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .batch-bar {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
  }
  .batch-buttons { justify-content: center; }
}

@media (max-width: 640px) {
  .filename-link { max-width: 140px; }
  .pagination-wrapper :deep(.el-pagination) {
    flex-wrap: wrap;
    justify-content: center;
    row-gap: 8px;
  }
}
</style>
