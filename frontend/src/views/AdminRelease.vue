<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Menu, PanelLeftClose, RefreshCw, Upload } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { releasesAdminApi } from '@/api/releases'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import type { ReleaseItem } from '@/types'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = adminNavItems

const PLATFORM_LABELS: Record<string, string> = {
  linux: 'Linux',
  macos: 'macOS',
  windows: 'Windows',
}

const PLATFORM_ICONS: Record<string, string> = {
  linux: '🐧',
  macos: '🍎',
  windows: '🪟',
}

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingReleases = ref(false)
const releases = ref<ReleaseItem[]>([])
const releaseLoadError = ref('')
const deletingId = ref('')
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const selectedFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const authForm = reactive({ username: '', password: '' })

const uploadForm = reactive({
  platform: 'linux',
  version: '',
  description: '',
})

const navVisible = computed(() => appStore.adminSidebarVisible)

const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const parseErrorMessage = (err: any): string => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
}

const normalizeReleaseList = (data: unknown): ReleaseItem[] => {
  if (Array.isArray(data)) return data as ReleaseItem[]
  return []
}

const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`
}

const formatTimestamp = (value?: string | null): string => {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return value
  }
}

const groupedReleases = computed(() => {
  const groups: Record<string, ReleaseItem[]> = { linux: [], macos: [], windows: [] }
  for (const r of releases.value) {
    if (groups[r.platform]) groups[r.platform].push(r)
  }
  return groups
})

const persistToken = (token: string) => adminToken.set(token)

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const handleNavClick = (item: (typeof navItems)[number]) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => appStore.toggleAdminSidebar()

const fetchReleases = async () => {
  if (!isAuthenticated.value) return
  loadingReleases.value = true
  releaseLoadError.value = ''
  try {
    const resp = await releasesAdminApi.list()
    if (!resp?.success) throw new Error(resp?.message || '获取列表失败')
    releases.value = normalizeReleaseList(resp.data)
  } catch (err: any) {
    const message = parseErrorMessage(err)
    releaseLoadError.value = message
    releases.value = []
    appStore.showNotification({ title: '加载失败', message, type: 'error' })
  } finally {
    loadingReleases.value = false
  }
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({ title: '请输入用户名和密码', type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '登录失败')
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: '登录成功', message: `欢迎，${resp.data.username}`, type: 'success' })
    await fetchReleases()
  } catch (err: any) {
    appStore.showNotification({ title: '登录失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    isLoggingIn.value = false
  }
}

const handleLogout = async () => {
  try {
    await adminApi.logout()
  } catch {
    // ignore
  } finally {
    clearAuth()
    releases.value = []
    appStore.showNotification({ title: '已退出登录', type: 'info' })
  }
}

const openUploadDialog = () => {
  uploadForm.platform = 'linux'
  uploadForm.version = ''
  uploadForm.description = ''
  selectedFile.value = null
  uploadDialogVisible.value = true
}

const closeUploadDialog = () => {
  if (uploading.value) return
  uploadDialogVisible.value = false
}

const handleFileChange = (e: Event) => {
  const input = e.target as HTMLInputElement
  selectedFile.value = input.files?.[0] ?? null
}

const handleDrop = (e: DragEvent) => {
  e.preventDefault()
  const file = e.dataTransfer?.files?.[0]
  if (file) selectedFile.value = file
}

const submitUpload = async () => {
  if (!uploadForm.version.trim()) {
    appStore.showNotification({ title: '请填写版本号', type: 'warning' })
    return
  }
  if (!selectedFile.value) {
    appStore.showNotification({ title: '请选择文件', type: 'warning' })
    return
  }
  uploading.value = true
  try {
    const resp = await releasesAdminApi.upload({
      platform: uploadForm.platform,
      version: uploadForm.version.trim(),
      description: uploadForm.description,
      file: selectedFile.value,
    })
    if (!resp?.success) throw new Error(resp?.message || '上传失败')
    appStore.showNotification({ title: '上传成功', message: `${PLATFORM_LABELS[uploadForm.platform]} v${uploadForm.version}`, type: 'success' })
    uploadDialogVisible.value = false
    await fetchReleases()
  } catch (err: any) {
    appStore.showNotification({ title: '上传失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    uploading.value = false
  }
}

const deleteRelease = async (item: ReleaseItem) => {
  if (!window.confirm(`确认删除 ${PLATFORM_LABELS[item.platform]} v${item.version}？`)) return
  deletingId.value = item.id
  try {
    const resp = await releasesAdminApi.remove(item.id)
    if (!resp?.success) throw new Error(resp?.message || '删除失败')
    releases.value = releases.value.filter((r) => r.id !== item.id)
    appStore.showNotification({ title: '已删除', message: `${item.filename}`, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: '删除失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    deletingId.value = ''
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await fetchReleases()
    } else {
      clearAuth()
    }
  } catch {
    clearAuth()
  }
}

onMounted(() => bootstrap())
</script>

<template>
  <div class="admin-console admin-release-page">
    <header class="admin-topbar">
      <div class="admin-topbar-inner">
        <div class="admin-topbar-left">
          <button
            class="admin-icon-btn"
            :disabled="!isAuthenticated"
            @click="toggleNavVisibility"
            :title="navVisible ? '隐藏侧边栏' : '显示侧边栏'"
          >
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">后台管理</h1>
            <p class="admin-subtitle">App Release 管理</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? `共 ${releases.length} 个版本` : '未登录' }}
          </span>
          <button v-if="isAuthenticated" class="admin-logout-btn" @click="handleLogout">
            <LogOut :size="14" />
            <span>退出</span>
          </button>
        </div>
      </div>
    </header>

    <button
      v-if="isAuthenticated && navVisible"
      class="admin-sidebar-backdrop"
      @click="toggleNavVisibility"
    />

    <aside v-if="isAuthenticated" class="admin-sidebar" :class="{ 'is-hidden': !navVisible }">
      <div class="space-y-2">
        <button
          v-for="item in navItems"
          :key="item.key"
          class="admin-side-nav-item"
          :class="{ 'is-active': activeNavKey === item.key }"
          @click="handleNavClick(item)"
        >
          <div class="text-sm font-semibold">{{ item.label }}</div>
          <p v-if="item.description" class="text-xs mt-1 text-slate-400">{{ item.description }}</p>
        </button>
      </div>
    </aside>

    <main class="admin-main" :class="{ 'is-sidebar-hidden': !isAuthenticated || !navVisible }">
      <!-- Login -->
      <section v-if="!isAuthenticated" class="admin-login-wrap">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">登录后台</h2>
              <p class="text-sm text-slate-500">请输入管理员凭证继续</p>
            </div>
            <span class="text-xs text-slate-500">内部安全访问</span>
          </div>
          <form class="space-y-4 max-w-sm" @submit.prevent="handleLogin">
            <label class="block">
              <span class="text-sm text-slate-700">用户名</span>
              <input
                v-model="authForm.username"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="admin"
                autocomplete="username"
              />
            </label>
            <label class="block">
              <span class="text-sm text-slate-700">密码</span>
              <input
                v-model="authForm.password"
                type="password"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="••••••••"
                autocomplete="current-password"
              />
            </label>
            <button
              type="submit"
              class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
              :disabled="isLoggingIn"
            >
              {{ isLoggingIn ? '登录中…' : '登录' }}
            </button>
          </form>
        </div>
      </section>

      <!-- Release Management -->
      <section v-else class="space-y-5">
        <!-- Header -->
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div class="flex items-center justify-between">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">App Release 列表</h2>
              <p v-if="releaseLoadError" class="text-sm text-rose-600 mt-0.5">
                {{ releaseLoadError }}
              </p>
              <p v-else class="text-sm text-slate-500 mt-0.5">管理各平台安装包的上传与发布</p>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="text-sm text-slate-600 hover:text-slate-900 px-3 py-1.5"
                :disabled="loadingReleases"
                @click="fetchReleases"
              >
                <RefreshCw :size="15" />
                {{ loadingReleases ? '同步中…' : '刷新' }}
              </button>
              <button
                class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition"
                @click="openUploadDialog"
              >
                <Upload :size="15" />
                <span>上传 Release</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Platform Groups -->
        <div
          v-if="releaseLoadError"
          class="bg-white rounded-2xl shadow-sm border border-slate-200 p-8 text-center"
        >
          <h3 class="text-base font-semibold text-slate-900">Release 内容暂时无法加载</h3>
          <p class="text-sm text-slate-500 mt-2">{{ releaseLoadError }}</p>
          <button
            class="mt-4 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition"
            :disabled="loadingReleases"
            @click="fetchReleases"
          >
            <RefreshCw :size="15" />
            <span>{{ loadingReleases ? '同步中…' : '重新加载' }}</span>
          </button>
        </div>

        <template v-else>
          <div
            v-for="platform in ['linux', 'macos', 'windows']"
            :key="platform"
            class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden"
          >
            <div class="platform-header flex items-center gap-3 px-5 py-3 border-b border-slate-100">
              <span class="text-xl">{{ PLATFORM_ICONS[platform] }}</span>
              <div>
                <span class="font-semibold text-slate-900">{{ PLATFORM_LABELS[platform] }}</span>
                <span class="ml-2 text-xs text-slate-500">{{ groupedReleases[platform].length }} 个版本</span>
              </div>
            </div>

            <div v-if="!groupedReleases[platform].length" class="px-5 py-8 text-center text-sm text-slate-400">
              暂无 {{ PLATFORM_LABELS[platform] }} 版本，点击右上角"上传 Release"添加
            </div>

            <div v-else class="release-table-wrapper overflow-x-auto">
              <table class="min-w-full text-sm text-slate-700">
                <thead>
                  <tr class="border-b border-slate-100 bg-slate-50">
                    <th class="py-2.5 pl-5 pr-4 text-left font-semibold text-slate-600">版本</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">文件名</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">大小</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">下载数</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">上传时间</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">备注</th>
                    <th class="py-2.5 pr-5 text-left font-semibold text-slate-600">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in groupedReleases[platform]"
                    :key="item.id"
                    class="border-b border-slate-50 hover:bg-slate-50/60 transition-colors"
                  >
                    <td class="py-3 pl-5 pr-4 font-medium text-slate-900">
                      <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-cyan-50 text-cyan-700 text-xs font-semibold border border-cyan-100">
                        v{{ item.version }}
                      </span>
                    </td>
                    <td class="py-3 pr-4 text-slate-600 font-mono text-xs max-w-[200px] truncate" :title="item.filename">
                      {{ item.filename }}
                    </td>
                    <td class="py-3 pr-4 text-slate-500">{{ formatBytes(item.file_size) }}</td>
                    <td class="py-3 pr-4 text-slate-500">{{ item.download_count }}</td>
                    <td class="py-3 pr-4 text-slate-500 whitespace-nowrap">{{ formatTimestamp(item.created_at) }}</td>
                    <td class="py-3 pr-4 text-slate-400 text-xs max-w-[160px] truncate" :title="item.description || ''">
                      {{ item.description || '—' }}
                    </td>
                    <td class="py-3 pr-5">
                      <button
                        class="text-xs px-3 py-1 rounded-lg border border-rose-200 text-rose-600 hover:bg-rose-50 disabled:opacity-50 transition"
                        :disabled="deletingId === item.id"
                        @click="deleteRelease(item)"
                      >
                        {{ deletingId === item.id ? '删除中…' : '删除' }}
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </section>
    </main>

    <!-- Upload Dialog -->
    <div v-if="uploadDialogVisible" class="admin-modal-backdrop" @click="closeUploadDialog">
      <div class="admin-modal-card upload-modal" @click.stop>
        <div class="flex items-center justify-between mb-5">
          <div>
            <h3 class="text-base font-semibold text-slate-900">上传 Release</h3>
            <p class="text-sm text-slate-500 mt-0.5">选择平台、填写版本后上传安装包</p>
          </div>
          <button class="text-sm text-slate-500 hover:text-slate-800" :disabled="uploading" @click="closeUploadDialog">关闭</button>
        </div>

        <!-- Platform selector -->
        <div class="mb-5">
          <span class="text-sm font-medium text-slate-700 block mb-2">目标平台</span>
          <div class="flex gap-2">
            <button
              v-for="p in ['linux', 'macos', 'windows']"
              :key="p"
              class="platform-btn flex-1 flex flex-col items-center gap-1 py-3 rounded-xl border text-sm transition"
              :class="uploadForm.platform === p ? 'border-cyan-500 bg-cyan-50 text-cyan-700' : 'border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'"
              @click="uploadForm.platform = p"
            >
              <span class="text-lg">{{ PLATFORM_ICONS[p] }}</span>
              <span class="font-medium text-xs">{{ PLATFORM_LABELS[p] }}</span>
            </button>
          </div>
        </div>

        <!-- Version & Description -->
        <div class="grid grid-cols-2 gap-4 mb-5">
          <label class="block">
            <span class="text-sm text-slate-700">版本号 <span class="text-rose-500">*</span></span>
            <input
              v-model="uploadForm.version"
              type="text"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              placeholder="如 1.2.0"
            />
          </label>
          <label class="block">
            <span class="text-sm text-slate-700">备注描述（可选）</span>
            <input
              v-model="uploadForm.description"
              type="text"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              placeholder="如 修复了…"
            />
          </label>
        </div>

        <!-- File Drop Zone -->
        <div
          class="drop-zone rounded-xl border-2 border-dashed border-slate-200 p-8 text-center mb-5 transition cursor-pointer hover:border-cyan-400 hover:bg-cyan-50/40"
          :class="{ 'border-cyan-500 bg-cyan-50': selectedFile }"
          @click="fileInputRef?.click()"
          @dragover.prevent
          @drop="handleDrop"
        >
          <input
            ref="fileInputRef"
            type="file"
            class="hidden"
            @change="handleFileChange"
          />
          <div v-if="selectedFile" class="space-y-1">
            <p class="text-sm font-semibold text-cyan-700">{{ selectedFile.name }}</p>
            <p class="text-xs text-slate-500">{{ formatBytes(selectedFile.size) }}</p>
          </div>
          <div v-else class="space-y-1">
            <p class="text-sm text-slate-500">拖拽文件到此处，或点击选择文件</p>
            <p class="text-xs text-slate-400">支持所有格式（.exe / .dmg / .tar.gz / .deb 等）</p>
          </div>
        </div>

        <div class="flex justify-end gap-2">
          <button
            class="px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            :disabled="uploading"
            @click="closeUploadDialog"
          >
            取消
          </button>
          <button
            class="px-5 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-60"
            :disabled="uploading"
            @click="submitUpload"
          >
            {{ uploading ? '上传中…' : '确认上传' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-console {
  --admin-topbar-height: 72px;
  --admin-sidebar-width: 280px;
  min-height: 100vh;
  background: linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%);
}

.admin-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  width: 100%;
  height: var(--admin-topbar-height);
  z-index: 70;
  background: rgba(15, 23, 42, 0.96);
  border-bottom: 1px solid rgba(148, 163, 184, 0.3);
  backdrop-filter: blur(10px);
}

.admin-topbar-inner {
  height: 100%;
  padding: 0 1rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.admin-topbar-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.admin-icon-btn {
  width: 2.25rem;
  height: 2.25rem;
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 0.625rem;
  color: #f8fafc;
  background: rgba(51, 65, 85, 0.6);
}

.admin-icon-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.admin-title {
  color: #f8fafc;
  font-size: 0.95rem;
  font-weight: 700;
  line-height: 1.1;
}

.admin-subtitle {
  color: #94a3b8;
  font-size: 0.75rem;
}

.admin-topbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.admin-logout-btn {
  border: 1px solid rgba(148, 163, 184, 0.35);
  border-radius: 0.55rem;
  color: #e2e8f0;
  background: rgba(51, 65, 85, 0.45);
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.45rem 0.7rem;
}

.admin-sidebar {
  position: fixed;
  left: 0;
  top: 0;
  width: var(--admin-sidebar-width);
  height: 100vh;
  z-index: 60;
  background: #0f172a;
  border-right: 1px solid rgba(148, 163, 184, 0.25);
  padding: calc(var(--admin-topbar-height) + 1rem) 1rem 1rem;
  transition: transform 0.25s ease;
  overflow-y: auto;
}

.admin-sidebar.is-hidden {
  transform: translateX(calc(-1 * var(--admin-sidebar-width)));
}

.admin-side-nav-item {
  width: 100%;
  text-align: left;
  padding: 0.8rem;
  border-radius: 0.75rem;
  border: 1px solid rgba(100, 116, 139, 0.45);
  color: #cbd5e1;
  background: rgba(30, 41, 59, 0.45);
}

.admin-side-nav-item.is-active {
  color: #0f172a;
  background: #22d3ee;
  border-color: #22d3ee;
}

.admin-main {
  min-height: 100vh;
  padding: calc(var(--admin-topbar-height) + 1rem) 1rem 1rem calc(var(--admin-sidebar-width) + 1rem);
  transition: padding-left 0.25s ease;
}

.admin-main.is-sidebar-hidden {
  padding-left: 1rem;
}

.admin-login-wrap {
  max-width: 960px;
  margin: 1.25rem auto 0;
}

.admin-sidebar-backdrop {
  display: none;
}

.admin-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(2, 6, 23, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.admin-modal-card {
  width: min(640px, 100%);
  border-radius: 1rem;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  box-shadow: 0 20px 45px rgba(15, 23, 42, 0.25);
  padding: 1.25rem;
}

.platform-header {
  background: #f8fafc;
}

.drop-zone {
  min-height: 100px;
}

@media (max-width: 768px) {
  .admin-console {
    --admin-sidebar-width: min(84vw, 320px);
  }

  .admin-main {
    padding: calc(var(--admin-topbar-height) + 0.85rem) 0.75rem 0.75rem;
  }

  .admin-main.is-sidebar-hidden {
    padding-left: 0.75rem;
  }

  .admin-sidebar {
    box-shadow: 20px 0 45px rgba(15, 23, 42, 0.35);
  }

  .admin-sidebar-backdrop {
    display: block;
    position: fixed;
    inset: var(--admin-topbar-height) 0 0 0;
    z-index: 55;
    background: rgba(2, 6, 23, 0.4);
  }

  .admin-topbar-right {
    display: none;
  }

  .admin-subtitle {
    display: none;
  }

  .upload-modal {
    max-height: 90vh;
    overflow-y: auto;
  }

  .grid-cols-2 {
    grid-template-columns: 1fr;
  }
}
</style>
