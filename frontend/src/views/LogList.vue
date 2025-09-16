<template>
  <div class="log-list-page">
    <!-- 页面标题和操作栏 -->
    <div class="page-header">
      <div class="flex justify-between items-center">
        <h1 class="text-2xl font-bold text-gray-900">日志列表</h1>
        <el-button type="primary" @click="$router.push('/upload')">
          <el-icon class="mr-1">
            <Upload />
          </el-icon>
          上传日志
        </el-button>
      </div>
    </div>

    <!-- 搜索和筛选 -->
    <div class="filter-section">
      <el-card class="mb-6">
        <div class="flex flex-wrap gap-4 items-center">
          <div class="flex-1 min-w-64">
            <el-input
              v-model="searchQuery"
              placeholder="搜索文件名或任务名称..."
              clearable
              @input="handleSearch"
            >
              <template #prefix>
                <el-icon>
                  <Search />
                </el-icon>
              </template>
            </el-input>
          </div>
          
          <el-select
            v-model="statusFilter"
            placeholder="状态筛选"
            clearable
            @change="handleStatusFilter"
            class="w-32"
          >
            <el-option label="待处理" value="pending" />
            <el-option label="处理中" value="processing" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
          </el-select>

          <el-button @click="refreshData">
            <el-icon class="mr-1">
              <Refresh />
            </el-icon>
            刷新
          </el-button>
        </div>
      </el-card>
    </div>

    <!-- 日志列表 -->
    <el-card>
      <div class="table-header mb-4">
        <div class="flex justify-between items-center">
          <span class="text-sm text-gray-600">
            共 {{ logStore.pagination.total }} 条记录
          </span>
          <div class="flex items-center space-x-2">
            <el-button
              v-if="selectedLogs.length > 0"
              type="danger"
              size="small"
              @click="handleBatchDelete"
            >
              批量删除 ({{ selectedLogs.length }})
            </el-button>
          </div>
        </div>
      </div>

      <el-table
        v-loading="logStore.loading"
        :data="logStore.logs"
        @selection-change="handleSelectionChange"
        class="w-full"
      >
        <el-table-column type="selection" width="55" />
        
        <el-table-column prop="filename" label="文件名" min-width="200">
          <template #default="{ row }">
            <div class="flex items-center space-x-2">
              <el-icon class="text-blue-600">
                <Document />
              </el-icon>
              <router-link
                :to="`/log/${row.id}`"
                class="text-blue-600 hover:text-blue-800 font-medium"
              >
                {{ row.filename }}
              </router-link>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="file_size" label="文件大小" width="120">
          <template #default="{ row }">
            {{ formatFileSize(row.file_size) }}
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusColor(row.status)">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="task_name" label="任务名称" width="150">
          <template #default="{ row }">
            <span v-if="row.task_name" class="text-gray-700">
              {{ row.task_name }}
            </span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>

        <el-table-column prop="download_count" label="下载次数" width="100" />

        <el-table-column prop="upload_time" label="上传时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.upload_time) }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <div class="flex space-x-2">
              <el-button
                type="primary"
                size="small"
                @click="handleDownload(row)"
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
          v-model:page-size="logStore.pagination.size"
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
import { ref, onMounted } from 'vue'
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
} from '@element-plus/icons-vue'

const logStore = useLogStore()
const appStore = useAppStore()

const searchQuery = ref('')
const statusFilter = ref('')
const selectedLogs = ref<LogRecord[]>([])

// 搜索防抖
const handleSearch = debounce(() => {
  logStore.setFilters({ search: searchQuery.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}, 500)

// 状态筛选
const handleStatusFilter = () => {
  logStore.setFilters({ status: statusFilter.value })
  logStore.setPagination({ page: 1 })
  logStore.fetchLogs()
}

// 刷新数据
const refreshData = () => {
  logStore.fetchLogs()
}

// 选择变化
const handleSelectionChange = (selection: LogRecord[]) => {
  selectedLogs.value = selection
}

// 分页变化
const handleSizeChange = (size: number) => {
  logStore.setPagination({ size })
  logStore.fetchLogs()
}

const handleCurrentChange = (page: number) => {
  logStore.setPagination({ page })
  logStore.fetchLogs()
}

// 下载文件
const handleDownload = async (log: LogRecord) => {
  try {
    appStore.setLoading(true)
    const blob = await logApi.downloadLog(log.id)
    downloadFile(blob, log.filename)
    appStore.showNotification({
      title: '下载成功',
      message: `文件 ${log.filename} 已开始下载`,
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

onMounted(() => {
  logStore.fetchLogs()
})
</script>

<style scoped>
.log-list-page {
  @apply space-y-6;
}

.page-header {
  @apply mb-6;
}

.filter-section {
  @apply mb-6;
}

.table-header {
  @apply border-b border-gray-200 pb-4;
}

.pagination-wrapper {
  @apply flex justify-center;
}
</style>