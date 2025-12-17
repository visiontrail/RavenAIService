<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getRavenPackageDetail,
  downloadRavenPackage,
  ravenBaseUrl,
} from '@/api/raven'
import { copyToClipboard, downloadFile, formatDateTime, formatFileSize } from '@/utils'
import { renderMarkdown } from '@/utils/markdownRenderer'
import type { RavenComponent, RavenPackage } from '@/types'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const pkg = ref<RavenPackage | null>(null)
const errorMessage = ref('')

const packageId = computed(() => String(route.params.id || ''))

const shareLink = computed(() =>
  pkg.value ? `${ravenBaseUrl}/package/${encodeURIComponent(pkg.value.id)}` : ''
)
const downloadLink = computed(() =>
  pkg.value ? `${ravenBaseUrl}/api/download/${encodeURIComponent(pkg.value.id)}` : ''
)

const normalizeTags = (value?: unknown) => {
  if (!value) return []
  if (Array.isArray(value)) return value.map((t) => String(t)).filter(Boolean)
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed.map((t) => String(t)).filter(Boolean)
    } catch {
      return value
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
    }
  }
  return []
}

const normalizeComponents = (value?: unknown): RavenComponent[] => {
  if (!value) return []
  let components: any[] = []
  if (Array.isArray(value)) {
    components = value
  } else if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) components = parsed
    } catch {
      components = []
    }
  }

  return components
    .map((item) => {
      if (typeof item === 'string') return { name: item }
      if (item && typeof item === 'object') {
        const name = (item as any).name
        const version = (item as any).version
        if (!name) return null
        return version ? { name, version: String(version) } : { name: String(name) }
      }
      return null
    })
    .filter(Boolean) as RavenComponent[]
}

const isPatchPackage = (value?: RavenPackage | null) => {
  if (!value?.metadata) return false
  const flag = value.metadata.isPatch
  return flag === true || flag === 'true'
}

const humanizePatch = (value?: RavenPackage | null) => (isPatchPackage(value) ? '补丁包' : '正式包')

const packageTypeText = (type?: string) => {
  const map: Record<string, string> = {
    'lingxi-10': 'LingXi-10',
    'lingxi-07a': 'LingXi-07A',
    'ka-tx': 'KaTx',
    'ka-rx': 'KaRx',
    config: '配置包',
    'lingxi-06-thrid': 'LingXi-06-TRD',
  }
  return map[type || ''] || type || '未知类型'
}

const packageTypeTag = (type?: string) => {
  const map: Record<string, string> = {
    'lingxi-10': 'primary',
    'lingxi-07a': 'success',
    'ka-tx': 'danger',
    'ka-rx': 'warning',
    config: 'info',
    'lingxi-06-thrid': 'warning',
  }
  return map[type || ''] || 'info'
}

const renderedDescription = computed(() =>
  renderMarkdown(pkg.value?.metadata?.description || '暂无描述', { cleanXml: true })
)

const fetchDetail = async () => {
  if (!packageId.value) {
    errorMessage.value = '未找到包 ID'
    return
  }
  loading.value = true
  errorMessage.value = ''
  pkg.value = null
  try {
    const { data } = await getRavenPackageDetail(packageId.value)
    if (data?.success && data.data) {
      pkg.value = data.data
    } else {
      throw new Error(data?.message || '获取包详情失败')
    }
  } catch (error: any) {
    console.error(error)
    errorMessage.value = error.message || '加载包详情失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

const goBack = () => {
  // 如果有历史记录，则返回上一页；否则跳转到重构包列表
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push({ name: 'RavenManager' })
  }
}

const copyShareLink = async (link: string) => {
  if (!link) return
  const ok = await copyToClipboard(link)
  if (ok) {
    ElMessage.success('链接已复制')
  } else {
    ElMessage.warning('复制失败，请手动复制')
  }
}

const copyRebuildPrompt = async () => {
  if (!pkg.value || !downloadLink.value) {
    ElMessage.warning('暂无可用的下载链接')
    return
  }
  const prompt = `请你帮忙下载${downloadLink.value}并上传到设备ftp，然后请向基带处理机发送重构包下载请求后，启动卫星升级流程`
  const ok = await copyToClipboard(prompt)
  if (ok) {
    ElMessage.success('提示词已复制')
  } else {
    ElMessage.warning('复制失败，请手动复制')
  }
}

const downloadPackage = async (value: RavenPackage) => {
  try {
    const response = await downloadRavenPackage(value.id)
    const contentDisposition = (response.headers['content-disposition'] || '') as string
    const filenameMatch = contentDisposition.match(/filename=\"(.+)\"/)
    const fallbackName = value.name ? `${value.name}.tgz` : 'package.tgz'
    const filename = filenameMatch ? filenameMatch[1] : fallbackName
    downloadFile(response.data, filename)
    ElMessage.success('下载开始')
  } catch (error: any) {
    console.error(error)
    ElMessage.error(error.message || '下载失败')
  }
}

onMounted(fetchDetail)

watch(
  () => route.params.id,
  () => fetchDetail()
)
</script>

<template>
  <div class="space-y-6 raven-detail-page">
    <div class="flex items-center justify-between flex-wrap gap-3">
      <div class="flex items-center gap-3">
        <el-button text @click="goBack" class="text-gray-600 hover:text-gray-900">
          <el-icon class="mr-1" size="18">
            <ArrowLeft />
          </el-icon>
          返回列表
        </el-button>
        <div class="h-6 w-px bg-gray-200" />
        <div>
          <p class="text-sm text-gray-500">Raven 包详情</p>
          <div class="flex items-center gap-2">
            <h1 class="text-2xl font-bold text-gray-900">{{ pkg?.name || '加载中...' }}</h1>
            <el-tag v-if="pkg" size="small" effect="plain" type="info">
              v{{ pkg.version || '未知' }}
            </el-tag>
            <el-tag v-if="pkg" size="small" :type="packageTypeTag(pkg.packageType)">
              {{ packageTypeText(pkg.packageType) }}
            </el-tag>
            <el-tag v-if="pkg" size="small" effect="plain" :type="isPatchPackage(pkg) ? 'warning' : 'success'">
              {{ humanizePatch(pkg) }}
            </el-tag>
          </div>
          <p class="text-gray-500 text-sm mt-1">
            创建于 {{ pkg ? formatDateTime(pkg.createdAt) : '-' }}
          </p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <el-button v-if="pkg" size="small" @click="copyShareLink(shareLink)">
          <el-icon class="mr-1"><Link /></el-icon>
          复制详情链接
        </el-button>
        <el-button v-if="pkg" size="small" @click="copyShareLink(downloadLink)">
          复制下载链接
        </el-button>
        <el-button v-if="pkg" size="small" @click="copyRebuildPrompt">
          复制重构提示词
        </el-button>
        <el-button v-if="pkg" size="small" type="primary" @click="downloadPackage(pkg)">
          <el-icon class="mr-1"><Download /></el-icon>
          下载
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="errorMessage"
      type="error"
      show-icon
      :closable="false"
      class="bg-red-50 border-red-200"
      :description="errorMessage"
    />

    <el-skeleton v-if="loading" :rows="8" animated />

    <div v-else-if="pkg" class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="space-y-4">
        <el-card shadow="never" class="border border-gray-100">
          <template #header>
            <div class="flex items-center gap-2">
              <el-icon><Document /></el-icon>
              <span class="font-semibold text-gray-800">基本信息</span>
            </div>
          </template>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm text-gray-700">
            <div>
              <p class="text-gray-500 mb-1">包 ID</p>
              <div class="font-mono bg-gray-50 p-2 rounded border border-gray-100 break-all">
                {{ pkg.id }}
              </div>
            </div>
            <div>
              <p class="text-gray-500 mb-1">大小</p>
              <div class="text-gray-900 font-medium">{{ formatFileSize(pkg.size) }}</div>
            </div>
            <div>
              <p class="text-gray-500 mb-1">存储路径</p>
              <div class="text-gray-900 bg-gray-50 p-2 rounded border border-gray-100 break-all">
                {{ pkg.path || '-' }}
              </div>
            </div>
            <div>
              <p class="text-gray-500 mb-1">SHA-256</p>
              <div class="text-gray-900 bg-gray-50 p-2 rounded border border-gray-100 break-all">
                {{ pkg.metadata?.sha256 || '暂无' }}
              </div>
            </div>
            <div>
              <p class="text-gray-500 mb-1">包类型</p>
              <div class="flex items-center gap-2">
                <el-tag size="small" :type="packageTypeTag(pkg.packageType)">
                  {{ packageTypeText(pkg.packageType) }}
                </el-tag>
                <el-tag size="small" effect="plain" :type="isPatchPackage(pkg) ? 'warning' : 'success'">
                  {{ humanizePatch(pkg) }}
                </el-tag>
              </div>
            </div>
          </div>
        </el-card>

        <el-card shadow="never" class="border border-gray-100">
          <template #header>
            <div class="flex items-center gap-2">
              <el-icon><PriceTag /></el-icon>
              <span class="font-semibold text-gray-800">标签</span>
            </div>
          </template>
          <div class="flex flex-wrap gap-2">
            <el-tag
              v-for="tag in normalizeTags(pkg.metadata?.tags)"
              :key="tag"
              size="small"
              effect="light"
            >
              {{ tag }}
            </el-tag>
            <span v-if="!normalizeTags(pkg.metadata?.tags).length" class="text-gray-400 text-sm">
              暂无标签
            </span>
          </div>
        </el-card>

        <el-card shadow="never" class="border border-gray-100">
          <template #header>
            <div class="flex items-center gap-2">
              <el-icon><Collection /></el-icon>
              <span class="font-semibold text-gray-800">组件</span>
            </div>
          </template>
          <div class="flex flex-wrap gap-2">
            <el-tag
              v-for="comp in normalizeComponents(pkg.metadata?.components)"
              :key="`${comp.name}-${comp.version || 'na'}`"
              size="small"
              effect="plain"
              type="success"
            >
              {{ comp.name }} <span v-if="comp.version">· {{ comp.version }}</span>
            </el-tag>
            <span v-if="!normalizeComponents(pkg.metadata?.components).length" class="text-gray-400 text-sm">
              暂无组件
            </span>
          </div>
        </el-card>
      </div>

      <div class="space-y-4">
        <el-card shadow="never" class="border border-gray-100">
          <template #header>
            <div class="flex items-center gap-2">
              <el-icon><Memo /></el-icon>
              <span class="font-semibold text-gray-800">描述</span>
            </div>
          </template>
          <div class="markdown-content text-sm text-gray-800" v-html="renderedDescription" />
        </el-card>
      </div>
    </div>
  </div>
</template>

<style scoped>
.markdown-content :deep(img) {
  max-width: 100%;
}
</style>
