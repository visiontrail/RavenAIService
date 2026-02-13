<template>
  <div class="device-detail-page">
    <div class="page-header">
      <div class="flex items-center gap-3 flex-wrap">
        <el-button text @click="goBack" class="!px-0">
          <el-icon><ArrowLeft /></el-icon>
          返回设备列表
        </el-button>
        <el-tag :type="statusTagType(device?.status)" effect="light">
          {{ statusText(device?.status) }}
        </el-tag>
        <el-tag v-if="device?.host" effect="plain">{{ device.host }}</el-tag>
      </div>
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between mt-4">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">{{ device?.name || deviceId }}</h1>
          <p class="text-sm text-gray-500 mt-1">设备 ID：{{ deviceId }}</p>
          <p class="text-xs text-gray-400 mt-1">
            最近心跳：{{ device?.last_seen ? formatDateTime(device.last_seen) : '未上报' }}
            <span v-if="device?.last_seen" class="ml-2 text-gray-400">
              ({{ formatRelativeTime(device.last_seen) }})
            </span>
          </p>
        </div>
        <div class="flex items-center gap-2">
          <el-button @click="fetchDevice" :loading="loading" type="primary">
            <el-icon class="mr-1"><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>
    </div>

    <el-row :gutter="16" v-if="device">
      <el-col :span="8" :xs="24">
        <el-card shadow="never" class="info-card">
          <div class="card-title">基础信息</div>
          <div class="info-item">
            <span class="label">主机</span>
            <span class="value">{{ device.host || '-' }}</span>
          </div>
          <div class="info-item">
            <span class="label">状态</span>
            <el-tag :type="statusTagType(device.status)" effect="light">
              {{ statusText(device.status) }}
            </el-tag>
          </div>
          <div class="info-item">
            <span class="label">可用模型</span>
            <div class="value models">
              <el-tag
                v-for="model in device.models"
                :key="model"
                size="small"
                effect="plain"
              >
                {{ model }}
              </el-tag>
              <span v-if="!device.models || device.models.length === 0" class="text-gray-400">-</span>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="16" :xs="24">
        <el-card shadow="never" class="info-card">
          <div class="card-title flex items-center justify-between">
            <span>MCP 能力</span>
            <el-tag effect="plain" type="info">
              共 {{ mcpServers.length }} 个 MCP 服务
            </el-tag>
          </div>

          <div v-if="mcpServers.length === 0" class="empty-capability">
            暂无上报的 MCP 能力
          </div>

          <el-collapse v-else accordion>
            <el-collapse-item v-for="server in mcpServers" :key="server.id" :name="server.id">
              <template #title>
                <div class="flex items-center gap-3">
                  <div class="font-semibold text-gray-900">{{ server.name || server.id }}</div>
                  <el-tag size="small" effect="plain" v-if="server.provider">{{ server.provider }}</el-tag>
                  <el-tag size="small" effect="light" v-if="server.type">{{ server.type }}</el-tag>
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
    <div v-if="loading" class="text-center text-gray-500 py-10">加载中...</div>
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

const route = useRoute()
const router = useRouter()
const deviceId = computed(() => (route.params.id as string) || '')
const device = ref<DeviceInfo | null>(null)
const loading = ref(false)

const statusText = (status?: DeviceInfo['status']) => (status === 'online' ? '在线' : '离线')
const statusTagType = (status?: DeviceInfo['status']) => (status === 'online' ? 'success' : 'info')

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
.device-detail-page > * + * {
  margin-top: 1.25rem;
}

.page-header {
  margin-bottom: 0.5rem;
}

.info-card {
  border: 1px solid #e5e7eb;
}

.card-title {
  font-weight: 600;
  color: #111827;
  margin-bottom: 0.75rem;
}

.info-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0;
  border-bottom: 1px dashed #f3f4f6;
}

.info-item:last-child {
  border-bottom: none;
}

.label {
  color: #6b7280;
  font-size: 0.9rem;
}

.value {
  color: #111827;
  font-weight: 500;
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.models .el-tag {
  margin-right: 0.35rem;
}

.empty-capability {
  color: #6b7280;
  font-size: 0.95rem;
  padding: 1rem 0;
}

.section {
  margin-top: 0.75rem;
}

.section-title {
  font-weight: 600;
  color: #374151;
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
  color: #111827;
  display: block;
  line-height: 1.3;
}

.chip-desc {
  font-size: 0.85rem;
  color: #6b7280;
  display: block;
  line-height: 1.5;
}

@media (max-width: 768px) {
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
