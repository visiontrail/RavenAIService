<template>
  <div class="rw-page">
    <WorkbenchTopbar title="设备详情" :meta="device?.name || deviceId">
      <template #actions>
        <button type="button" class="rw-btn-secondary" @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          <span>返回列表</span>
        </button>
        <button type="button" class="rw-btn-primary" :disabled="loading" @click="fetchDevice">
          <el-icon><Refresh /></el-icon>
          <span>{{ loading ? '刷新中…' : '刷新' }}</span>
        </button>
      </template>
    </WorkbenchTopbar>

    <div class="rw-page-scroll">
      <div class="detail-head">
        <div class="detail-title-block">
          <div class="detail-kicker">DEVICE NODE</div>
          <h1>{{ device?.name || deviceId }}</h1>
          <p>设备 ID：{{ deviceId }}</p>
        </div>
        <div class="detail-badges">
          <span class="rw-pill" :class="pillVariant(device?.status)">
            {{ statusText(device?.status) }}
          </span>
          <span v-if="device?.host" class="rw-chip">{{ device.host }}</span>
        </div>
      </div>

      <section class="rw-card heartbeat-card" v-if="device">
        <div class="heartbeat-main">
          <span class="heartbeat-label">最近心跳</span>
          <span class="heartbeat-value">
            最近心跳：{{ device?.last_seen ? formatDateTime(device.last_seen) : '未上报' }}
            <span v-if="device?.last_seen" class="heartbeat-relative">
              ({{ formatRelativeTime(device.last_seen) }})
            </span>
          </span>
        </div>
      </section>

      <el-row :gutter="16" v-if="device">
        <el-col :span="8" :xs="24">
          <el-card shadow="never" class="rw-card info-card">
            <div class="card-title">基础信息</div>
            <div class="info-item">
              <span class="label">主机</span>
              <span class="value">{{ device.host || '-' }}</span>
            </div>
            <div class="info-item">
              <span class="label">状态</span>
              <span class="rw-pill" :class="pillVariant(device.status)">
                {{ statusText(device.status) }}
              </span>
            </div>
            <div class="info-item">
              <span class="label">可用模型</span>
              <div class="value models">
                <span v-for="model in device.models" :key="model" class="rw-chip">
                  {{ model }}
                </span>
                <span v-if="!device.models || device.models.length === 0" class="empty-value">-</span>
              </div>
            </div>
          </el-card>
        </el-col>

        <el-col :span="16" :xs="24">
          <el-card shadow="never" class="rw-card info-card">
            <div class="card-title flex items-center justify-between">
              <span>MCP 能力</span>
              <span class="rw-chip">共 {{ mcpServers.length }} 个 MCP 服务</span>
            </div>

            <div v-if="mcpServers.length === 0" class="empty-capability">
              暂无上报的 MCP 能力
            </div>

            <el-collapse v-else accordion>
              <el-collapse-item v-for="server in mcpServers" :key="server.id" :name="server.id">
                <template #title>
                  <div class="server-title">
                    <span>{{ server.name || server.id }}</span>
                    <span class="rw-chip" v-if="server.provider">{{ server.provider }}</span>
                    <span class="rw-chip" v-if="server.type">{{ server.type }}</span>
                  </div>
                </template>

                <div class="server-meta mb-3">
                  <div class="text-sm text-gray-600" v-if="server.description">{{ server.description }}</div>
                  <div class="text-xs text-gray-500" v-if="server.baseUrl">Base URL: {{ server.baseUrl }}</div>
                </div>

                <div class="section">
                  <div class="section-title">工具 ({{ server.tools?.length || 0 }})</div>
                  <div v-if="server.tools?.length" class="chips">
                    <el-tag v-for="tool in server.tools" :key="tool.name" effect="plain" class="chip">
                      <div class="chip-title">{{ tool.name }}</div>
                      <div class="chip-desc" v-if="tool.description">{{ tool.description }}</div>
                    </el-tag>
                  </div>
                  <div v-else class="text-gray-400 text-sm">未上报工具</div>
                </div>

                <div class="section">
                  <div class="section-title">提示词 ({{ server.prompts?.length || 0 }})</div>
                  <div v-if="server.prompts?.length" class="chips">
                    <el-tag v-for="prompt in server.prompts" :key="prompt.name" effect="plain" class="chip">
                      <div class="chip-title">{{ prompt.name }}</div>
                      <div class="chip-desc" v-if="prompt.description">{{ prompt.description }}</div>
                    </el-tag>
                  </div>
                  <div v-else class="text-gray-400 text-sm">未上报提示词</div>
                </div>

                <div class="section">
                  <div class="section-title">资源 ({{ server.resources?.length || 0 }})</div>
                  <div v-if="server.resources?.length" class="chips">
                    <el-tag
                      v-for="resource in server.resources"
                      :key="resource.uri || resource.name"
                      effect="plain"
                      class="chip"
                    >
                      <div class="chip-title">{{ resource.name || resource.uri }}</div>
                      <div class="chip-desc" v-if="resource.description">{{ resource.description }}</div>
                    </el-tag>
                  </div>
                  <div v-else class="text-gray-400 text-sm">未上报资源</div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-card>
        </el-col>
      </el-row>

      <el-empty v-else-if="!loading" description="未找到设备信息" />
      <div v-if="loading" class="loading-state">加载中...</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { deviceLinkApi } from '@/api/deviceLink'
import { formatDateTime, formatRelativeTime } from '@/utils'
import type { DeviceInfo } from '@/types'
import WorkbenchTopbar from '@/layouts/WorkbenchTopbar.vue'

const route = useRoute()
const router = useRouter()
const deviceId = computed(() => (route.params.id as string) || '')
const device = ref<DeviceInfo | null>(null)
const loading = ref(false)

const statusText = (status?: DeviceInfo['status']) => (status === 'online' ? '在线' : '离线')
const pillVariant = (status?: DeviceInfo['status']) => (status === 'online' ? 'is-success' : 'is-neutral')

const mcpServers = computed(() => {
  const mcp = (device.value?.capabilities as any)?.mcp
  return (mcp?.servers as any[]) || []
})

const goBack = () => {
  router.push({ name: 'DeviceList' })
}

const fetchDevice = async () => {
  loading.value = true
  try {
    const res = await deviceLinkApi.getDevice(deviceId.value)
    device.value = res
    if (!res) {
      ElMessage.warning('未找到设备信息')
    }
  } catch (error: any) {
    console.error('Failed to load device detail:', error)
    ElMessage.error(error?.message || '加载设备详情失败')
  } finally {
    loading.value = false
  }
}

onMounted(fetchDevice)
</script>

<style scoped>
.rw-page {
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--rw-canvas, #ffffff);
}

.rw-page-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 24px 28px 36px;
}

.rw-page-scroll > * + * {
  margin-top: 16px;
}

.detail-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding-bottom: 6px;
}

.detail-kicker {
  color: var(--rw-muted, #999999);
  font-family: var(--rw-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  margin-bottom: 6px;
}

.detail-title-block h1 {
  margin: 0;
  color: var(--rw-ink, #171717);
  font-size: 26px;
  line-height: 1.2;
  font-weight: 650;
}

.detail-title-block p {
  margin: 6px 0 0;
  color: var(--rw-body, #60646c);
  font-size: 13px;
  font-family: var(--rw-mono, monospace);
}

.detail-badges {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.rw-card {
  border: 1px solid var(--rw-hairline, #f0f0f3);
  border-radius: 8px;
  background: var(--rw-canvas, #ffffff);
  box-shadow: none;
}

.info-card {
  min-height: 100%;
}

.heartbeat-card {
  padding: 14px 16px;
}

.heartbeat-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.heartbeat-label {
  color: var(--rw-muted, #999999);
  font-size: 12px;
  font-weight: 600;
}

.heartbeat-value {
  color: var(--rw-ink, #171717);
  font-size: 13px;
  font-family: var(--rw-mono, monospace);
}

.heartbeat-relative {
  color: var(--rw-muted, #999999);
}

.card-title {
  font-weight: 600;
  color: var(--rw-ink, #171717);
  margin-bottom: 0.75rem;
}

.info-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0;
  border-bottom: 1px dashed var(--rw-hairline, #f0f0f3);
  gap: 12px;
}

.info-item:last-child {
  border-bottom: none;
}

.label {
  color: var(--rw-body, #60646c);
  font-size: 0.9rem;
}

.value {
  color: var(--rw-ink, #171717);
  font-weight: 500;
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.rw-pill,
.rw-chip {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  border-radius: 999px;
  padding: 0 9px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.rw-pill.is-success {
  color: #146c2e;
  background: #ecfdf3;
  border: 1px solid #bbf7d0;
}

.rw-pill.is-neutral,
.rw-chip {
  color: var(--rw-body, #60646c);
  background: var(--rw-canvas-soft, #fafafa);
  border: 1px solid var(--rw-hairline-strong, #dcdee0);
}

.empty-value {
  color: var(--rw-muted, #999999);
}

.empty-capability {
  color: var(--rw-body, #60646c);
  font-size: 0.95rem;
  padding: 1rem 0;
}

.section {
  margin-top: 0.75rem;
}

.section-title {
  font-weight: 600;
  color: var(--rw-ink, #171717);
  margin-bottom: 0.25rem;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.25rem;
  height: auto;
  white-space: normal;
  word-break: break-all;
  line-height: 1.4;
  padding: 0.55rem 0.7rem;
  flex: 1 1 260px;
  box-sizing: border-box;
}

.chip-title {
  font-weight: 600;
  color: var(--rw-ink, #171717);
  display: block;
  line-height: 1.3;
}

.chip-desc {
  font-size: 0.85rem;
  color: var(--rw-body, #60646c);
  display: block;
  line-height: 1.5;
}

.server-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-weight: 600;
  color: var(--rw-ink, #171717);
}

.loading-state {
  padding: 42px 0;
  text-align: center;
  color: var(--rw-muted, #999999);
  font-size: 13px;
}

.rw-btn-primary,
.rw-btn-secondary {
  height: 34px;
  border-radius: 8px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.rw-btn-primary {
  border: 1px solid var(--rw-primary, #171717);
  background: var(--rw-primary, #171717);
  color: var(--rw-on-primary, #ffffff);
}

.rw-btn-primary:hover:not(:disabled) {
  background: var(--rw-primary-hover, #2e2e2e);
  color: var(--rw-on-primary, #ffffff);
}

.rw-btn-primary:disabled {
  opacity: 0.6;
  cursor: default;
}

.rw-btn-secondary {
  border: 1px solid var(--rw-hairline-strong, #dcdee0);
  background: var(--rw-canvas, #ffffff);
  color: var(--rw-ink, #171717);
}

.rw-btn-secondary:hover {
  background: var(--rw-surface-strong, #f0f0f3);
}

:deep(.el-card__body) {
  padding: 18px;
}

:deep(.el-collapse) {
  --el-collapse-border-color: var(--rw-hairline, #f0f0f3);
}

@media (max-width: 768px) {
  .rw-page-scroll {
    padding: 18px 16px 28px;
  }

  .detail-head,
  .heartbeat-main {
    align-items: flex-start;
    flex-direction: column;
  }

  .detail-badges {
    justify-content: flex-start;
  }

  .info-item {
    align-items: flex-start;
    flex-direction: column;
    gap: 0.35rem;
  }

  .value {
    justify-content: flex-start;
    width: 100%;
  }

  .chip {
    flex-basis: 100%;
  }
}
</style>
