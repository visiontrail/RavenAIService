<template>
  <div class="rw-page">
    <WorkbenchTopbar :title="t('device.listTitle')" :meta="t('device.listMeta', { online: onlineCount, total: devices.length })">
      <template #actions>
        <span class="rw-meta">{{ lastUpdatedLabel }}</span>
        <button
          type="button"
          class="rw-toggle"
          :class="{ 'is-active': autoRefreshEnabled }"
          :aria-pressed="autoRefreshEnabled"
          :title="t('device.autoRefreshHint')"
          @click="autoRefreshEnabled = !autoRefreshEnabled"
        >
          <span class="rw-toggle-track">
            <span class="rw-toggle-dot" />
          </span>
          <span class="rw-toggle-label">{{ t('device.autoRefresh') }}</span>
        </button>
        <button
          type="button"
          class="rw-btn-primary"
          :disabled="loading"
          @click="fetchDevices()"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 0 1 15.5-6.4L21 8" />
            <path d="M21 3v5h-5" />
            <path d="M21 12a9 9 0 0 1-15.5 6.4L3 16" />
            <path d="M3 21v-5h5" />
          </svg>
          <span>{{ loading ? t('device.refreshing') : t('common.refresh') }}</span>
        </button>
      </template>
    </WorkbenchTopbar>

    <div class="rw-page-scroll">
      <div class="rw-stat-row">
        <span class="rw-pill rw-pill-success">{{ t('device.onlineCount', { count: onlineCount }) }}</span>
        <span class="rw-pill rw-pill-neutral">{{ t('device.totalCount', { count: devices.length }) }}</span>
        <span class="rw-meta rw-stat-meta">{{ t('device.refreshInterval', { interval: refreshIntervalMs / 1000 }) }}</span>
      </div>

      <section class="rw-card desktop-only">
        <div class="rw-table-scroll">
          <el-table
            v-loading="loading"
            :data="devices"
            :border="false"
            :stripe="false"
            class="rw-table"
            :empty-text="loading ? t('device.loadingText') : t('device.empty')"
          >
            <el-table-column prop="name" :label="t('device.colDevice')" min-width="220">
              <template #default="{ row }">
                <router-link :to="`/devices/${row.id}`" class="name-link">
                  <span class="name-link-title">{{ row.name || row.id }}</span>
                  <span class="name-link-id">ID: {{ row.id }}</span>
                </router-link>
              </template>
            </el-table-column>

            <el-table-column prop="host" :label="t('device.colHost')" min-width="180">
              <template #default="{ row }">
                <span class="cell-host">{{ row.host || '-' }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="status" :label="t('device.colStatus')" width="120">
              <template #default="{ row }">
                <span class="rw-pill" :class="pillVariant(row.status)">
                  {{ statusText(row.status) }}
                </span>
              </template>
            </el-table-column>

            <el-table-column prop="last_seen" :label="t('device.colLastSeen')" min-width="200">
              <template #default="{ row }">
                <div class="cell-stacked">
                  <span class="cell-primary">
                    {{ row.last_seen ? formatDateTime(row.last_seen) : t('device.notReported') }}
                  </span>
                  <span v-if="row.last_seen" class="cell-sub">
                    {{ formatRelativeTime(row.last_seen) }}
                  </span>
                </div>
              </template>
            </el-table-column>

            <el-table-column prop="models" :label="t('device.colModels')" min-width="240">
              <template #default="{ row }">
                <div class="rw-chip-row">
                  <span
                    v-for="model in row.models"
                    :key="model"
                    class="rw-chip"
                  >
                    {{ model }}
                  </span>
                  <span v-if="!row.models || row.models.length === 0" class="cell-muted">
                    -
                  </span>
                </div>
              </template>
            </el-table-column>

            <el-table-column :label="t('common.actions')" width="220" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <button
                    type="button"
                    class="rw-btn-secondary"
                    :disabled="pingingId === row.id"
                    @click="handlePing(row)"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M5 12.55a11 11 0 0 1 14 0" />
                      <path d="M8.5 16.05a6 6 0 0 1 7 0" />
                      <path d="M2 8.82a15 15 0 0 1 20 0" />
                      <line x1="12" y1="20" x2="12.01" y2="20" />
                    </svg>
                    <span>{{ pingingId === row.id ? 'Ping…' : 'Ping' }}</span>
                  </button>
                  <el-popconfirm
                    width="220"
                    :confirm-button-text="t('common.delete')"
                    :cancel-button-text="t('common.cancel')"
                    confirm-button-type="danger"
                    :title="t('device.deleteConfirm')"
                    @confirm="handleDelete(row)"
                  >
                    <template #reference>
                      <button
                        type="button"
                        class="rw-btn-danger"
                        :disabled="deletingId === row.id"
                      >
                        {{ deletingId === row.id ? t('device.deleting') : t('common.delete') }}
                      </button>
                    </template>
                  </el-popconfirm>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>

      <section class="mobile-only" v-loading="loading">
        <div v-if="devices.length" class="mobile-device-list">
          <router-link
            v-for="row in devices"
            :key="row.id"
            :to="`/devices/${row.id}`"
            class="mobile-device-card"
          >
            <div class="mobile-device-head">
              <div class="mobile-device-name">{{ row.name || row.id }}</div>
              <span class="rw-pill" :class="pillVariant(row.status)">
                {{ statusText(row.status) }}
              </span>
            </div>
            <div class="mobile-device-id">ID: {{ row.id }}</div>
            <div class="mobile-device-meta">
              <span class="mobile-meta-label">{{ t('device.colHost') }}</span>
              <span>{{ row.host || '-' }}</span>
            </div>
            <div class="mobile-device-meta">
              <span class="mobile-meta-label">{{ t('device.colLastSeen') }}</span>
              <span>
                {{ row.last_seen ? `${formatRelativeTime(row.last_seen)} · ${formatDateTime(row.last_seen)}` : t('device.notReported') }}
              </span>
            </div>
            <div class="mobile-device-meta">
              <span class="mobile-meta-label">{{ t('device.colModels') }}</span>
              <span>{{ t('device.modelCount', { count: row.models?.length || 0 }) }}</span>
            </div>
            <div class="mobile-device-link">{{ t('device.viewDetail') }}</div>
          </router-link>
        </div>
        <el-empty v-else :description="loading ? t('device.loadingText') : t('device.empty')" />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import WorkbenchTopbar from '@/layouts/WorkbenchTopbar.vue'
import { deviceLinkApi } from '@/api/deviceLink'
import { formatDateTime, formatRelativeTime } from '@/utils'
import type { DeviceInfo } from '@/types'

const { t } = useI18n()

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
  if (!lastUpdated.value) return t('device.waitingRefresh')
  const isoString = lastUpdated.value.toISOString()
  return `${formatRelativeTime(isoString)} · ${formatDateTime(isoString)}`
})

const statusText = (status: DeviceInfo['status']) =>
  status === 'online' ? t('device.status.online') : t('device.status.offline')
const statusTagType = (status: DeviceInfo['status']) => (status === 'online' ? 'success' : 'info')
const pillVariant = (status: DeviceInfo['status']) =>
  statusTagType(status) === 'success' ? 'rw-pill-success' : 'rw-pill-neutral'

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
      ElMessage.error(error?.message || t('device.loadListFail'))
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
    ElMessage.success(t('device.pingSuccess', { name: device.name || device.id }))
  } catch (error: any) {
    console.error('Ping device failed:', error)
    const detail = error?.response?.data?.detail || error?.message || t('device.pingFail')
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
    ElMessage.success(t('device.deleteSuccess', { name: device.name || device.id }))
  } catch (error: any) {
    console.error('Delete device failed:', error)
    const detail = error?.response?.data?.detail || error?.message || t('device.deleteFail')
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
}

.rw-meta {
  font-size: 12px;
  color: var(--rw-muted);
  font-family: var(--rw-mono);
}

.rw-stat-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 16px;
}

.rw-stat-meta {
  margin-left: auto;
}

.rw-card {
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  padding: 20px;
}

.rw-table-scroll {
  width: 100%;
}

.rw-btn-primary {
  height: 32px;
  padding: 0 14px;
  background: var(--rw-primary);
  color: var(--rw-on-primary);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: background 0.15s ease;
}
.rw-btn-primary:hover:not(:disabled) {
  background: var(--rw-primary-active);
}
.rw-btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.rw-btn-secondary {
  height: 32px;
  padding: 0 14px;
  background: var(--rw-canvas);
  color: var(--rw-ink);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: background 0.15s ease;
}
.rw-btn-secondary:hover:not(:disabled) {
  background: var(--rw-surface-strong);
}
.rw-btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.rw-btn-danger {
  height: 32px;
  padding: 0 14px;
  background: #c0382b;
  color: #fff;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: background 0.15s ease;
}
.rw-btn-danger:hover:not(:disabled) {
  background: #a52e22;
}
.rw-btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.rw-icon-btn {
  width: 30px;
  height: 30px;
  border-radius: 6px;
  background: transparent;
  border: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--rw-body);
}
.rw-icon-btn:hover {
  background: var(--rw-surface-strong);
}

.rw-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;
  padding: 0 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.2px;
  line-height: 1;
}
.rw-pill-success {
  background: rgba(22, 163, 74, 0.12);
  color: #15803d;
}
.rw-pill-success::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: var(--rw-success);
  flex-shrink: 0;
}
.rw-pill-neutral {
  background: var(--rw-surface-strong);
  color: var(--rw-body);
}
.rw-pill-neutral::before {
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: var(--rw-muted-soft);
  flex-shrink: 0;
}

.rw-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: none;
  padding: 0 6px;
  height: 32px;
  cursor: pointer;
  color: var(--rw-body);
  font-family: inherit;
}
.rw-toggle-track {
  position: relative;
  width: 36px;
  height: 20px;
  border-radius: 999px;
  border: 1px solid var(--rw-hairline-strong);
  background: var(--rw-canvas);
  transition: background 0.15s ease, border-color 0.15s ease;
  flex-shrink: 0;
}
.rw-toggle-dot {
  position: absolute;
  top: 50%;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 999px;
  background: var(--rw-muted-soft);
  transform: translateY(-50%);
  transition: left 0.15s ease, background 0.15s ease;
}
.rw-toggle.is-active .rw-toggle-track {
  background: var(--rw-ink);
  border-color: var(--rw-ink);
}
.rw-toggle.is-active .rw-toggle-dot {
  left: 18px;
  background: var(--rw-on-ink);
}
.rw-toggle-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--rw-body);
}

.rw-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rw-chip {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 6px;
  background: var(--rw-surface-strong);
  color: var(--rw-ink);
  font-family: var(--rw-mono);
  font-size: 11.5px;
}

.name-link {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  text-decoration: none;
}
.name-link-title {
  color: var(--rw-ink);
  font-weight: 500;
  font-size: 13px;
}
.name-link:hover .name-link-title {
  color: var(--rw-primary-active);
}
.name-link-id {
  font-family: var(--rw-mono);
  font-size: 11.5px;
  color: var(--rw-muted);
}

.cell-host {
  color: var(--rw-ink);
  font-size: 13px;
}
.cell-stacked {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cell-primary {
  color: var(--rw-ink);
  font-size: 13px;
}
.cell-sub {
  font-size: 11.5px;
  color: var(--rw-muted);
  font-family: var(--rw-mono);
}
.cell-muted {
  color: var(--rw-muted);
  font-size: 13px;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.desktop-only {
  display: block;
}
.mobile-only {
  display: none;
}

.mobile-device-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mobile-device-card {
  display: block;
  background: var(--rw-canvas);
  border: 1px solid var(--rw-hairline-strong);
  border-radius: 12px;
  padding: 14px;
  text-decoration: none;
  color: inherit;
}
.mobile-device-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}
.mobile-device-name {
  font-weight: 600;
  color: var(--rw-ink);
  font-size: 14px;
}
.mobile-device-id {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--rw-muted);
  font-family: var(--rw-mono);
}
.mobile-device-meta {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--rw-body);
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.mobile-meta-label {
  color: var(--rw-muted);
  font-size: 11.5px;
  text-transform: uppercase;
  letter-spacing: 0.4px;
}
.mobile-device-link {
  margin-top: 12px;
  font-size: 12.5px;
  color: var(--rw-ink);
  font-weight: 500;
}

:deep(.el-table) {
  --el-table-border-color: var(--rw-hairline);
  --el-table-header-bg-color: var(--rw-canvas-soft);
  --el-table-row-hover-bg-color: var(--rw-hairline-soft);
  background: var(--rw-canvas);
  font-size: 13px;
  color: var(--rw-ink);
}
:deep(.el-table::before),
:deep(.el-table::after) {
  background-color: transparent;
}
:deep(.el-table th.el-table__cell) {
  background: var(--rw-canvas-soft);
  text-transform: uppercase;
  letter-spacing: 0.6px;
  font-size: 10.5px;
  color: var(--rw-muted);
  font-weight: 600;
  padding: 12px;
  border-bottom: 1px solid var(--rw-hairline);
}
:deep(.el-table td.el-table__cell) {
  padding: 14px 12px;
  border-bottom: 1px solid var(--rw-hairline-soft);
}
:deep(.el-table tr) {
  background: var(--rw-canvas);
}
:deep(.el-table--enable-row-hover .el-table__body tr:hover > td.el-table__cell) {
  background: var(--rw-hairline-soft);
}
:deep(.el-table .cell) {
  line-height: 1.4;
}
:deep(.el-popconfirm__main) {
  font-size: 13px;
}

@media (max-width: 768px) {
  .rw-page-scroll {
    padding: 16px;
  }
  .desktop-only {
    display: none;
  }
  .mobile-only {
    display: block;
  }
  .rw-stat-row {
    flex-wrap: wrap;
  }
  .rw-stat-meta {
    margin-left: 0;
    width: 100%;
  }
}
</style>
