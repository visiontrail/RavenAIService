<template>
  <div class="device-list-page">
    <div class="page-header">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">设备列表</h1>
          <p class="text-sm text-gray-500 mt-1">实时监控客户端长链连接状态与心跳</p>
        </div>
        <div class="header-actions">
          <div class="flex items-center gap-2">
            <el-tooltip content="每 15 秒自动刷新一次">
              <el-switch
                v-model="autoRefreshEnabled"
                inline-prompt
                active-text="自动刷新"
                inactive-text="手动刷新"
              />
            </el-tooltip>
            <el-button
              type="primary"
              size="small"
              :loading="loading"
              @click="fetchDevices()"
            >
              <el-icon class="mr-1">
                <Refresh />
              </el-icon>
              刷新
            </el-button>
          </div>
          <div class="last-updated">
            <el-icon class="text-gray-400">
              <Clock />
            </el-icon>
            <span>{{ lastUpdatedLabel }}</span>
          </div>
        </div>
      </div>
    </div>

    <el-card class="desktop-only">
      <div class="table-header">
        <div class="flex items-center gap-3 flex-wrap">
          <el-tag type="success" effect="light">
            在线 {{ onlineCount }}
          </el-tag>
          <el-tag type="info" effect="plain">
            总计 {{ devices.length }}
          </el-tag>
        </div>
        <div class="text-xs text-gray-500">
          自动刷新间隔：{{ refreshIntervalMs / 1000 }} 秒
        </div>
      </div>

      <div class="table-scroll-wrapper">
        <el-table
          v-loading="loading"
          :data="devices"
          border
          class="w-full"
          :empty-text="loading ? '加载中...' : '暂无设备连接'"
        >
        <el-table-column prop="name" label="设备" min-width="220">
          <template #default="{ row }">
            <router-link :to="`/devices/${row.id}`" class="flex flex-col name-link">
              <span class="text-gray-900 font-medium hover:text-blue-600">{{ row.name || row.id }}</span>
              <span class="text-xs text-gray-500">ID: {{ row.id }}</span>
            </router-link>
          </template>
        </el-table-column>

        <el-table-column prop="host" label="主机" min-width="180">
          <template #default="{ row }">
            <span class="text-gray-800">{{ row.host || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" effect="light">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="last_seen" label="最近心跳" min-width="200">
          <template #default="{ row }">
            <div class="flex flex-col">
              <span>{{ row.last_seen ? formatDateTime(row.last_seen) : '未上报' }}</span>
              <span v-if="row.last_seen" class="text-xs text-gray-500">
                {{ formatRelativeTime(row.last_seen) }}
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="models" label="可用模型" min-width="240">
          <template #default="{ row }">
            <div class="models-list">
              <el-tag
                v-for="model in row.models"
                :key="model"
                size="small"
                effect="plain"
              >
                {{ model }}
              </el-tag>
              <span v-if="!row.models || row.models.length === 0" class="text-gray-400 text-sm">
                -
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <div class="flex justify-end gap-2">
              <el-button
                size="small"
                plain
                type="primary"
                :loading="pingingId === row.id"
                @click="handlePing(row)"
              >
                <el-icon class="mr-1">
                  <Connection />
                </el-icon>
                Ping
              </el-button>
              <el-popconfirm
                width="200"
                confirm-button-text="删除"
                cancel-button-text="取消"
                confirm-button-type="danger"
                title="确定删除该设备记录？"
                @confirm="handleDelete(row)"
              >
                <template #reference>
                  <el-button
                    size="small"
                    plain
                    type="danger"
                    :loading="deletingId === row.id"
                  >
                    删除
                  </el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
        </el-table>
      </div>
    </el-card>

    <el-card class="mobile-only" v-loading="loading">
      <div class="table-header">
        <div class="flex items-center gap-3 flex-wrap">
          <el-tag type="success" effect="light">
            在线 {{ onlineCount }}
          </el-tag>
          <el-tag type="info" effect="plain">
            总计 {{ devices.length }}
          </el-tag>
        </div>
        <div class="text-xs text-gray-500">
          自动刷新间隔：{{ refreshIntervalMs / 1000 }} 秒
        </div>
      </div>

      <div v-if="devices.length" class="mobile-device-list">
        <router-link v-for="row in devices" :key="row.id" :to="`/devices/${row.id}`" class="mobile-device-card">
          <div class="mobile-device-head">
            <div class="mobile-device-name">{{ row.name || row.id }}</div>
            <el-tag :type="statusTagType(row.status)" effect="light" size="small">
              {{ statusText(row.status) }}
            </el-tag>
          </div>
          <div class="mobile-device-id">ID: {{ row.id }}</div>
          <div class="mobile-device-meta">主机：{{ row.host || '-' }}</div>
          <div class="mobile-device-meta">
            最近心跳：
            {{ row.last_seen ? `${formatRelativeTime(row.last_seen)} · ${formatDateTime(row.last_seen)}` : '未上报' }}
          </div>
          <div class="mobile-device-meta">可用模型：{{ row.models?.length || 0 }} 个</div>
          <div class="mobile-device-link">查看详情</div>
        </router-link>
      </div>
      <el-empty v-else :description="loading ? '加载中...' : '暂无设备连接'" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Clock, Connection, Refresh } from '@element-plus/icons-vue'
import { deviceLinkApi } from '@/api/deviceLink'
import { formatDateTime, formatRelativeTime } from '@/utils'
import type { DeviceInfo } from '@/types'

const devices = ref<DeviceInfo[]>([])
const loading = ref(false)
const pingingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const autoRefreshEnabled = ref(true)
const lastUpdated = ref<Date | null>(null)
const refreshIntervalMs = 15000
let timer: number | null = null

const onlineCount = computed(() => devices.value.filter((d) => d.status === 'online').length)

const lastUpdatedLabel = computed(() => {
  if (!lastUpdated.value) return '等待刷新'
  const isoString = lastUpdated.value.toISOString()
  return `${formatRelativeTime(isoString)} · ${formatDateTime(isoString)}`
})

const statusText = (status: DeviceInfo['status']) => (status === 'online' ? '在线' : '离线')
const statusTagType = (status: DeviceInfo['status']) => (status === 'online' ? 'success' : 'info')

const upsertDevice = (info: DeviceInfo) => {
  const idx = devices.value.findIndex((d) => d.id === info.id)
  if (idx !== -1) {
    devices.value[idx] = info
  } else {
    devices.value.push(info)
  }
}

const removeDevice = (deviceId: string) => {
  const idx = devices.value.findIndex((d) => d.id === deviceId)
  if (idx !== -1) {
    devices.value.splice(idx, 1)
  }
}

const fetchDevices = async (silent = false) => {
  if (!silent) loading.value = true
  try {
    const res = await deviceLinkApi.listDevices()
    devices.value = res.devices || []
    lastUpdated.value = new Date()
  } catch (error: any) {
    console.error('Failed to load devices:', error)
    if (!silent) {
      ElMessage.error(error?.message || '加载设备列表失败')
    }
  } finally {
    if (!silent) loading.value = false
  }
}

const handlePing = async (device: DeviceInfo) => {
  pingingId.value = device.id
  try {
    const updated = await deviceLinkApi.pingDevice(device.id)
    upsertDevice(updated)
    lastUpdated.value = new Date()
    ElMessage.success(`已向 ${device.name || device.id} 发送 ping`)
  } catch (error: any) {
    console.error('Ping device failed:', error)
    const detail = error?.response?.data?.detail || error?.message || 'Ping 失败'
    ElMessage.error(detail)
  } finally {
    pingingId.value = null
  }
}

const handleDelete = async (device: DeviceInfo) => {
  deletingId.value = device.id
  try {
    await deviceLinkApi.deleteDevice(device.id)
    removeDevice(device.id)
    lastUpdated.value = new Date()
    ElMessage.success(`已删除 ${device.name || device.id}`)
  } catch (error: any) {
    console.error('Delete device failed:', error)
    const detail = error?.response?.data?.detail || error?.message || '删除失败'
    ElMessage.error(detail)
  } finally {
    deletingId.value = null
  }
}

const startAutoRefresh = () => {
  stopAutoRefresh()
  if (!autoRefreshEnabled.value) return
  timer = window.setInterval(() => fetchDevices(true), refreshIntervalMs)
}

const stopAutoRefresh = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

watch(autoRefreshEnabled, (enabled) => {
  if (enabled) {
    fetchDevices(true)
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
})

onMounted(() => {
  fetchDevices().finally(() => startAutoRefresh())
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.device-list-page > * + * {
  margin-top: 1.5rem;
}

.desktop-only {
  display: block;
}

.mobile-only {
  display: none;
}

.page-header {
  margin-bottom: 1rem;
}

.header-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.5rem;
}

.last-updated {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.875rem;
  color: #6b7280;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid #e5e7eb;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.models-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.name-link {
  text-decoration: none;
}

.mobile-device-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.mobile-device-card {
  display: block;
  border: 1px solid #e5e7eb;
  border-radius: 0.75rem;
  padding: 0.75rem;
  text-decoration: none;
  color: inherit;
  background: #fff;
}

.mobile-device-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.75rem;
}

.mobile-device-name {
  font-weight: 600;
  color: #111827;
}

.mobile-device-id {
  margin-top: 0.375rem;
  font-size: 0.75rem;
  color: #6b7280;
}

.mobile-device-meta {
  margin-top: 0.375rem;
  font-size: 0.8125rem;
  color: #4b5563;
}

.mobile-device-link {
  margin-top: 0.625rem;
  font-size: 0.8125rem;
  color: #2563eb;
  font-weight: 500;
}

@media (max-width: 768px) {
  .desktop-only {
    display: none;
  }

  .mobile-only {
    display: block;
  }

  .table-scroll-wrapper {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .table-scroll-wrapper :deep(.el-table) {
    min-width: 980px;
  }
}

@media (min-width: 640px) {
  .header-actions {
    align-items: flex-end;
  }
}
</style>
