<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  listRavenPackages,
  deleteRavenPackage,
  rebuildRavenIndex,
  getRavenSearchStatus,
  intelligentSearchPackages,
  uploadRavenPackages,
  downloadRavenPackage,
  fetchRavenSuggestions,
} from '@/api/raven'
import { downloadFile, formatDateTime, formatFileSize } from '@/utils'
import { renderMarkdown } from '@/utils/markdownRenderer'
import type {
  RavenComponent,
  RavenPackage,
  RavenSearchResult,
  RavenSearchStatus,
  RavenUploadMetadata,
} from '@/types'

const router = useRouter()

const activeTab = ref('list')

const filters = reactive({
  search: '',
  type: '',
  version: '',
  tags: '',
  isPatch: '',
  page: 1,
  limit: 10,
})

const packages = ref<RavenPackage[]>([])
const pagination = reactive({
  currentPage: 1,
  totalPages: 1,
  totalItems: 0,
  itemsPerPage: 10,
})

const loadingList = ref(false)

const uploadZoneActive = ref(false)
const uploadFiles = ref<File[]>([])
const uploadMeta = reactive<RavenUploadMetadata>({
  packageType: 'lingxi-10',
  version: '',
  isPatch: false,
  description: '',
  tags: [],
  components: [],
})
const tagDraft = ref('')
const componentDraft = reactive<{ name: string; version: string }>({
  name: '',
  version: '',
})
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadStatus = ref('')
const uploadController = ref<AbortController | null>(null)

const searchQuery = ref('')
const searchLoading = ref(false)
const searchResult = ref<RavenSearchResult | null>(null)
const searchStatus = ref<RavenSearchStatus | null>(null)
const statusLoading = ref(false)
const rebuildLoading = ref(false)
const searchSuggestions = ref<string[]>([
  'LingXi-10 最新完整包',
  '查找补丁包',
  '包含 OAM 组件的版本',
  'KaTx 最新发布',
])

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

const isPatchPackage = (pkg?: RavenPackage | null) => {
  if (!pkg?.metadata) return false
  const value = pkg.metadata.isPatch
  return value === true || value === 'true'
}

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

const fetchPackages = async () => {
  loadingList.value = true
  try {
    const { data } = await listRavenPackages({
      page: filters.page,
      limit: filters.limit,
      search: filters.search || undefined,
      type: filters.type || undefined,
      tags: filters.tags || undefined,
      version: filters.version || undefined,
      isPatch: filters.isPatch || undefined,
    })

    if (data?.success && data.data) {
      packages.value = data.data.packages || []
      pagination.currentPage = data.data.pagination.currentPage
      pagination.totalPages = data.data.pagination.totalPages
      pagination.totalItems = data.data.pagination.totalItems
      pagination.itemsPerPage = data.data.pagination.itemsPerPage
    } else {
      throw new Error(data?.message || '获取包列表失败')
    }
  } catch (error: any) {
    console.error(error)
    ElMessage.error(error.message || '加载包列表失败')
  } finally {
    loadingList.value = false
  }
}

const refreshAll = async () => {
  await Promise.all([fetchPackages(), checkSearchStatus()])
}

const handlePageChange = (page: number) => {
  filters.page = page
  fetchPackages()
}

const resetFilters = () => {
  filters.search = ''
  filters.type = ''
  filters.version = ''
  filters.tags = ''
  filters.isPatch = ''
  filters.page = 1
  fetchPackages()
}

const openPackageDetail = (payload: string | RavenPackage) => {
  const id = typeof payload === 'string' ? payload : payload.id
  router.push({ name: 'RavenPackageDetail', params: { id } })
}

const downloadPackage = async (pkg: RavenPackage) => {
  try {
    const response = await downloadRavenPackage(pkg.id)
    const contentDisposition = (response.headers['content-disposition'] || '') as string
    const filenameMatch = contentDisposition.match(/filename="(.+)"/)
    const fallbackName = pkg.name ? `${pkg.name}.tgz` : 'package.tgz'
    const filename = filenameMatch ? filenameMatch[1] : fallbackName
    downloadFile(response.data, filename)
    ElMessage.success('下载开始')
  } catch (error: any) {
    console.error(error)
    ElMessage.error(error.message || '下载失败')
  }
}

const deletePackage = async (pkg: RavenPackage) => {
  try {
    await ElMessageBox.confirm(
      `确定删除包「${pkg.name || pkg.id}」吗？此操作不可恢复。`,
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      }
    )
    const { data } = await deleteRavenPackage(pkg.id)
    if (!data?.success) throw new Error(data?.message || '删除失败')
    ElMessage.success('包已删除')
    fetchPackages()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    console.error(error)
    ElMessage.error(error.message || '删除失败')
  }
}

const humanizePatch = (pkg?: RavenPackage | null) => (isPatchPackage(pkg) ? '补丁包' : '正式包')

const addFiles = (files: File[]) => {
  if (!files.length) return
  const validFiles: File[] = []

  files.forEach((file) => {
    const name = file.name.toLowerCase()
    if (name.endsWith('.tgz') || name.endsWith('.tar.gz')) {
      validFiles.push(file)
    } else {
      ElMessage.warning(`文件 ${file.name} 格式不支持，仅支持 .tgz/.tar.gz`)
    }
  })

  if (validFiles.length) {
    uploadFiles.value = [...uploadFiles.value, ...validFiles]
  }
}

const handleFileInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (target.files) {
    addFiles(Array.from(target.files))
    target.value = ''
  }
}

const handleDrop = (event: DragEvent) => {
  event.preventDefault()
  uploadZoneActive.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  addFiles(files)
}

const removeFile = (file: File) => {
  uploadFiles.value = uploadFiles.value.filter((item) => item !== file)
}

const clearUpload = () => {
  uploadFiles.value = []
  uploadMeta.description = ''
  uploadMeta.tags = []
  uploadMeta.components = []
  uploadMeta.version = ''
  uploadMeta.isPatch = false
  uploadMeta.packageType = 'lingxi-10'
  uploadProgress.value = 0
  uploadStatus.value = ''
}

const startUpload = async () => {
  if (!uploadFiles.value.length) {
    ElMessage.warning('请先选择要上传的文件')
    return
  }

  uploading.value = true
  uploadProgress.value = 0
  uploadStatus.value = '准备上传...'
  uploadController.value = new AbortController()

  try {
    await uploadRavenPackages(
      uploadFiles.value,
      uploadMeta,
      (payload) => {
        uploadProgress.value = payload.percent
        if (payload.speedText) {
          uploadStatus.value =
            payload.percent >= 100
              ? '处理中...'
              : `上传中 ${payload.speedText}${
                  payload.etaSeconds ? ` · 剩余 ${Math.max(1, Math.round(payload.etaSeconds))}s` : ''
                }`
        }
      },
      uploadController.value.signal
    )

    uploadProgress.value = 100
    uploadStatus.value = '上传完成'
    ElMessage.success('上传完成，列表正在刷新')
    clearUpload()
    await fetchPackages()
    activeTab.value = 'list'
  } catch (error: any) {
    if (error?.code === 'ERR_CANCELED') {
      ElMessage.info('上传已取消')
      return
    }
    console.error(error)
    ElMessage.error(error.message || '上传失败')
  } finally {
    uploading.value = false
    uploadController.value = null
  }
}

const cancelUpload = () => {
  if (uploadController.value) {
    uploadController.value.abort()
  }
}

const addTag = () => {
  if (!tagDraft.value.trim()) return
  uploadMeta.tags = [...(uploadMeta.tags || []), tagDraft.value.trim()]
  tagDraft.value = ''
}

const removeTag = (tag: string) => {
  uploadMeta.tags = (uploadMeta.tags || []).filter((item) => item !== tag)
}

const addComponent = () => {
  if (!componentDraft.name.trim()) return
  uploadMeta.components = [
    ...(uploadMeta.components || []),
    componentDraft.version
      ? { name: componentDraft.name.trim(), version: componentDraft.version.trim() }
      : { name: componentDraft.name.trim() },
  ]
  componentDraft.name = ''
  componentDraft.version = ''
}

const removeComponent = (component: RavenComponent) => {
  uploadMeta.components = (uploadMeta.components || []).filter(
    (item) => item.name !== component.name || item.version !== component.version
  )
}

const renderedAnswer = computed(() =>
  searchResult.value ? renderMarkdown(searchResult.value.answer || '', { cleanXml: true }) : ''
)

const performSearch = async () => {
  if (!searchQuery.value.trim()) {
    ElMessage.warning('请输入搜索内容')
    return
  }

  searchLoading.value = true
  try {
    const { data } = await intelligentSearchPackages(searchQuery.value.trim(), 6)
    if (data?.success && data.data) {
      searchResult.value = data.data
    } else {
      throw new Error(data?.message || '搜索失败')
    }
  } catch (error: any) {
    console.error(error)
    ElMessage.error(error.message || '搜索失败')
  } finally {
    searchLoading.value = false
  }
}

const checkSearchStatus = async () => {
  statusLoading.value = true
  try {
    const { data } = await getRavenSearchStatus()
    if (data?.success && data.data) {
      searchStatus.value = data.data
    }
  } catch (error) {
    console.error(error)
  } finally {
    statusLoading.value = false
  }
}

const rebuildIndex = async () => {
  rebuildLoading.value = true
  try {
    const { data } = await rebuildRavenIndex()
    if (!data?.success) throw new Error(data?.message || '重建索引失败')
    ElMessage.success(data.message || '开始重建索引')
    checkSearchStatus()
  } catch (error: any) {
    console.error(error)
    ElMessage.error(error.message || '重建失败')
  } finally {
    rebuildLoading.value = false
  }
}

const loadSuggestions = async () => {
  if (!searchQuery.value.trim()) return
  try {
    const { data } = await fetchRavenSuggestions(searchQuery.value.trim())
    if (data?.success && Array.isArray(data.data) && data.data.length) {
      searchSuggestions.value = data.data
    }
  } catch (error) {
    console.error(error)
  }
}

onMounted(() => {
  fetchPackages()
  checkSearchStatus()
})
</script>

<template>
  <div class="space-y-6 raven-page">
    <div class="flex flex-wrap justify-between items-start gap-4">
      <div>
        <p class="text-sm text-gray-500">重构包列表</p>
        <h1 class="text-2xl font-bold text-gray-900">升级包与分发中心</h1>
      </div>
      <div class="flex items-center gap-2">
        <el-button @click="refreshAll" :loading="loadingList || statusLoading">
          <el-icon class="mr-1"><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="raven-tabs">
      <el-tab-pane label="包列表" name="list">
        <section class="bg-white p-4 rounded-xl shadow-sm border border-gray-100 space-y-4">
          <div class="flex flex-wrap md:flex-nowrap items-center gap-3 w-full" style="gap: 0.75rem;">
            <el-input
              v-model="filters.search"
              placeholder="按名称、版本或描述搜索"
              clearable
              class="flex-1 min-w-[260px]"
              style="width: 280px"
              @change="fetchPackages"
              @clear="fetchPackages"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <el-select
              v-model="filters.type"
              placeholder="包类型"
              clearable
              class="w-40"
              style="width: 170px"
              @change="fetchPackages"
            >
              <el-option label="LingXi-10" value="lingxi-10" />
              <el-option label="LingXi-07A" value="lingxi-07a" />
              <el-option label="KaTx" value="ka-tx" />
              <el-option label="KaRx" value="ka-rx" />
              <el-option label="配置包" value="config" />
              <el-option label="LingXi-06-TRD" value="lingxi-06-thrid" />
            </el-select>
            <el-input
              v-model="filters.version"
              placeholder="版本号"
              clearable
              class="w-32"
              style="width: 140px"
              @change="fetchPackages"
              @clear="fetchPackages"
            />
            <el-input
              v-model="filters.tags"
              placeholder="标签包含"
              clearable
              class="w-40"
              style="width: 170px"
              @change="fetchPackages"
              @clear="fetchPackages"
            />
            <el-select
              v-model="filters.isPatch"
              placeholder="补丁/正式"
              clearable
              class="w-32"
              style="width: 140px"
              @change="fetchPackages"
            >
              <el-option label="正式包" value="false" />
              <el-option label="补丁包" value="true" />
            </el-select>
            <div class="flex gap-2 flex-shrink-0">
              <el-button type="primary" @click="fetchPackages">
                <el-icon class="mr-1"><Search /></el-icon>
                搜索
              </el-button>
              <el-button @click="resetFilters">
                <el-icon class="mr-1"><CircleClose /></el-icon>
                重置
              </el-button>
            </div>
          </div>

          <el-table
            :data="packages"
            v-loading="loadingList"
            border
            class="w-full"
            :row-class-name="() => 'cursor-pointer'"
            @row-click="openPackageDetail"
          >
            <el-table-column prop="name" label="名称 / 版本" min-width="260">
              <template #default="{ row }">
                <div class="flex items-start gap-2">
                  <div class="flex-1">
                    <div class="flex items-center gap-2">
                      <span class="font-medium text-gray-900">{{ row.name }}</span>
                      <el-tag size="small" effect="plain" :type="packageTypeTag(row.packageType)">
                        {{ packageTypeText(row.packageType) }}
                      </el-tag>
                      <el-tag size="small" effect="plain" type="info">v{{ row.version || '未知' }}</el-tag>
                      <el-tag size="small" effect="plain" :type="isPatchPackage(row) ? 'warning' : 'success'">
                        {{ humanizePatch(row) }}
                      </el-tag>
                    </div>
                    <p class="text-xs text-gray-500 mt-1 truncate" :title="row.metadata?.description">
                      {{ row.metadata?.description || '暂无描述' }}
                    </p>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="标签" min-width="180">
              <template #default="{ row }">
                <div class="flex flex-wrap gap-1">
                  <el-tag
                    v-for="tag in normalizeTags(row.metadata?.tags)"
                    :key="tag"
                    size="small"
                    effect="plain"
                    type="info"
                  >
                    {{ tag }}
                  </el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="组件" min-width="180">
              <template #default="{ row }">
                <div class="flex flex-wrap gap-1">
                  <el-tag
                    v-for="comp in normalizeComponents(row.metadata?.components)"
                    :key="`${comp.name}-${comp.version || 'na'}`"
                    size="small"
                    effect="plain"
                    type="success"
                  >
                    {{ comp.name }} <span v-if="comp.version">· {{ comp.version }}</span>
                  </el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="大小" prop="size" width="120">
              <template #default="{ row }">
                {{ formatFileSize(row.size) }}
              </template>
            </el-table-column>
            <el-table-column label="创建时间" prop="createdAt" width="180">
              <template #default="{ row }">
                <span class="text-gray-600">{{ formatDateTime(row.createdAt) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{ row }">
                <div class="flex items-center gap-2">
                  <el-button size="small" text type="primary" @click.stop="openPackageDetail(row.id)">
                    详情
                  </el-button>
                  <el-button size="small" text type="success" @click.stop="downloadPackage(row)">下载</el-button>
                  <el-button size="small" text type="danger" @click.stop="deletePackage(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div class="flex justify-between items-center text-sm text-gray-500 mt-2">
            <span>共 {{ pagination.totalItems }} 个包</span>
            <el-pagination
              background
              layout="prev, pager, next, jumper"
              :current-page="pagination.currentPage"
              :total="pagination.totalItems"
              :page-size="pagination.itemsPerPage"
              @current-change="handlePageChange"
            />
          </div>
        </section>

      </el-tab-pane>

      <el-tab-pane label="上传包" name="upload">
        <section class="bg-white p-4 rounded-xl shadow-sm border border-gray-100 space-y-4">
          <div
            class="upload-zone rounded-lg border-2 border-dashed border-gray-200 p-6 text-center transition hover:border-blue-400"
            :class="{ 'border-blue-500 bg-blue-50': uploadZoneActive }"
            @dragover.prevent="uploadZoneActive = true"
            @dragleave.prevent="uploadZoneActive = false"
            @drop="handleDrop"
          >
            <input
              type="file"
              multiple
              accept=".tgz,.tar.gz"
              class="hidden"
              id="raven-upload-input"
              @change="handleFileInput"
            />
            <el-icon class="text-4xl text-gray-400 mb-2"><UploadFilled /></el-icon>
            <p class="text-gray-700 font-medium mb-1">拖拽文件到此处，或</p>
            <el-button type="primary" plain size="small" @click="() => (document.getElementById('raven-upload-input') as HTMLInputElement)?.click()">
              选择文件
            </el-button>
            <p class="text-gray-400 text-sm mt-2">支持 .tgz/.tar.gz，单次可选多个文件</p>
          </div>

          <div v-if="uploadFiles.length" class="bg-gray-50 border border-dashed border-gray-200 p-4 rounded-lg space-y-3">
            <div class="flex justify-between items-center">
              <p class="text-sm text-gray-600">已选择 {{ uploadFiles.length }} 个文件</p>
              <el-button link type="primary" size="small" @click="uploadFiles = []">清空</el-button>
            </div>
            <div class="flex flex-wrap gap-2">
              <el-tag
                v-for="file in uploadFiles"
                :key="file.name + file.size"
                closable
                @close="removeFile(file)"
                effect="plain"
              >
                {{ file.name }}
              </el-tag>
            </div>
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <el-card shadow="never" header="元数据">
              <div class="space-y-4">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <el-select v-model="uploadMeta.packageType" placeholder="包类型">
                    <el-option label="LingXi-10" value="lingxi-10" />
                    <el-option label="LingXi-07A" value="lingxi-07a" />
                    <el-option label="KaTx" value="ka-tx" />
                    <el-option label="KaRx" value="ka-rx" />
                    <el-option label="配置包" value="config" />
                    <el-option label="LingXi-06-TRD" value="lingxi-06-thrid" />
                  </el-select>
                  <el-input v-model="uploadMeta.version" placeholder="版本号，例如 1.0.0" />
                  <el-select v-model="uploadMeta.isPatch" placeholder="包类型">
                    <el-option label="正式包" :value="false" />
                    <el-option label="补丁包" :value="true" />
                  </el-select>
                </div>

                <el-input
                  v-model="uploadMeta.description"
                  type="textarea"
                  :rows="3"
                  placeholder="为团队添加一句描述，支持 Markdown"
                />

                <div class="space-y-2">
                  <p class="text-sm text-gray-600">标签</p>
                  <div class="flex flex-wrap gap-2">
                    <el-tag
                      v-for="tag in uploadMeta.tags"
                      :key="tag"
                      closable
                      @close="removeTag(tag)"
                      effect="plain"
                      type="info"
                    >
                      {{ tag }}
                    </el-tag>
                    <el-input
                      v-model="tagDraft"
                      size="small"
                      placeholder="输入后回车添加"
                      style="width: 160px"
                      @keyup.enter="addTag"
                      @blur="addTag"
                    />
                  </div>
                </div>

                <div class="space-y-2">
                  <p class="text-sm text-gray-600">组件</p>
                  <div class="flex flex-wrap gap-2">
                    <el-tag
                      v-for="comp in uploadMeta.components"
                      :key="`${comp.name}-${comp.version || 'na'}`"
                      closable
                      @close="removeComponent(comp)"
                      effect="plain"
                      type="success"
                    >
                      {{ comp.name }} <span v-if="comp.version">· {{ comp.version }}</span>
                    </el-tag>
                  </div>
                  <div class="flex gap-2">
                    <el-input v-model="componentDraft.name" size="small" placeholder="组件名" />
                    <el-input v-model="componentDraft.version" size="small" placeholder="版本（可选）" />
                    <el-button size="small" @click="addComponent">添加</el-button>
                  </div>
                </div>
              </div>
            </el-card>

            <el-card shadow="never" header="上传进度">
              <div class="flex flex-col gap-3">
                <el-progress :percentage="uploadProgress" :indeterminate="uploading && uploadProgress === 0" />
                <p class="text-sm text-gray-600 h-5">{{ uploadStatus }}</p>
                <div class="flex gap-2">
                  <el-button type="primary" :loading="uploading" :disabled="!uploadFiles.length" @click="startUpload">
                    <el-icon class="mr-1"><UploadFilled /></el-icon>
                    {{ uploading ? '上传中' : '开始上传' }}
                  </el-button>
                  <el-button v-if="uploading" @click="cancelUpload">取消</el-button>
                  <el-button @click="clearUpload" :disabled="uploading">重置</el-button>
                </div>
                <p class="text-xs text-gray-400">
                  上传过程中会自动重建向量索引，保持智能搜索可用
                </p>
              </div>
            </el-card>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane label="智能搜索" name="search">
        <section class="bg-white p-4 rounded-xl shadow-sm border border-gray-100 space-y-4">
          <div class="flex flex-wrap items-center gap-2">
            <el-input
              v-model="searchQuery"
              placeholder="用自然语言描述需求，例如：需要最新的 LingXi-10 正式包"
              clearable
              class="flex-1 min-w-[240px]"
              @keyup.enter="performSearch"
              @change="loadSuggestions"
            >
              <template #prefix>
                <el-icon><MagicStick /></el-icon>
              </template>
            </el-input>
            <el-button type="primary" :loading="searchLoading" @click="performSearch">
              <el-icon class="mr-1"><Search /></el-icon>
              智能搜索
            </el-button>
            <el-button :loading="statusLoading" @click="checkSearchStatus">检查状态</el-button>
            <el-button type="warning" plain :loading="rebuildLoading" @click="rebuildIndex">
              重建索引
            </el-button>
          </div>

          <div class="flex flex-wrap gap-2">
            <el-tag
              v-for="item in searchSuggestions"
              :key="item"
              effect="plain"
              class="cursor-pointer hover:bg-blue-50"
              @click="searchQuery = item; performSearch()"
            >
              {{ item }}
            </el-tag>
          </div>

          <div class="flex items-center gap-2 text-sm text-gray-600">
            <el-tag size="small" :type="searchStatus?.initialized ? 'success' : 'info'" effect="plain">
              {{ searchStatus?.initialized ? '向量索引已准备' : '待初始化' }}
            </el-tag>
            <el-tag v-if="searchStatus?.rebuilding" size="small" type="warning" effect="plain">
              正在重建索引
            </el-tag>
            <span v-if="searchStatus?.totalPackages" class="text-gray-500">
              已索引 {{ searchStatus.totalPackages }} 个包
            </span>
          </div>

          <div v-if="searchResult" class="space-y-4">
            <el-card shadow="never" class="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100">
              <template #header>
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <el-icon><StarFilled /></el-icon>
                    <span class="font-semibold text-gray-800">AI 回答</span>
                  </div>
                  <span class="text-gray-500 text-sm">根据描述生成，不保证完全准确</span>
                </div>
              </template>
              <div class="markdown-content" v-html="renderedAnswer" />
            </el-card>

            <el-card shadow="never">
              <template #header>
                <div class="flex items-center justify-between">
                  <span class="font-semibold text-gray-800">匹配包</span>
                  <span class="text-gray-500 text-sm">
                    命中 {{ searchResult.relevantPackages.length }} / {{ searchResult.searchResultsCount || searchResult.relevantPackages.length }}
                  </span>
                </div>
              </template>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div
                  v-for="pkg in searchResult.relevantPackages"
                  :key="pkg.id"
                  class="border border-gray-100 rounded-lg p-3 hover:border-blue-200 transition"
                >
                  <div class="flex justify-between items-start gap-2">
                    <div>
                      <div class="flex items-center gap-2">
                        <span class="font-medium text-gray-900">{{ pkg.name }}</span>
                        <el-tag size="small" effect="plain" :type="packageTypeTag(pkg.packageType)">
                          {{ packageTypeText(pkg.packageType) }}
                        </el-tag>
                        <el-tag size="small" effect="plain" type="info">
                          v{{ pkg.version || '未知' }}
                        </el-tag>
                      </div>
                      <p
                        class="text-xs text-gray-500 mt-1 overflow-hidden text-ellipsis"
                        style="display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;"
                      >
                        {{ pkg.metadata?.description || '暂无描述' }}
                      </p>
                    </div>
                    <el-tag v-if="(pkg as any).relevanceScore" size="small" type="success" effect="plain">
                      {{ ((pkg as any).relevanceScore * 100).toFixed(0) }}%
                    </el-tag>
                  </div>
                  <div class="flex flex-wrap gap-1 mt-2">
                    <el-tag
                      v-for="tag in normalizeTags(pkg.metadata?.tags)"
                      :key="tag"
                      size="small"
                      effect="plain"
                      type="info"
                    >
                      {{ tag }}
                    </el-tag>
                  </div>
                  <div class="flex gap-2 mt-3">
                    <el-button size="small" type="primary" plain @click="openPackageDetail(pkg.id)">详情</el-button>
                    <el-button size="small" type="success" plain @click="downloadPackage(pkg)">下载</el-button>
                  </div>
                </div>
              </div>
            </el-card>
          </div>

          <div v-else class="text-center text-gray-400 text-sm py-6">
            输入需求并执行智能搜索，结果会显示在这里
          </div>
        </section>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.stat-card {
  border: 1px solid #f1f5f9;
}

.upload-zone {
  transition: all 0.25s ease;
}

.markdown-content :deep(img) {
  max-width: 100%;
}
</style>
