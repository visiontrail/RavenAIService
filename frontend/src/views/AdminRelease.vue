<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { LogOut, Menu, PanelLeftClose, RefreshCw, Upload } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { releasesAdminApi } from '@/api/releases'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import type { ReleaseItem } from '@/types'

const { t } = useI18n()
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
  return t('admin.parseError')
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
    if (!resp?.success) throw new Error(resp?.message || t('admin.release.loadFailFallback'))
    releases.value = normalizeReleaseList(resp.data)
  } catch (err: any) {
    const message = parseErrorMessage(err)
    releaseLoadError.value = message
    releases.value = []
    appStore.showNotification({ title: t('admin.loadFail'), message, type: 'error' })
  } finally {
    loadingReleases.value = false
  }
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({ title: t('admin.loginWarning'), type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.loginFailFallback'))
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({ title: t('admin.loginSuccessTitle'), message: t('admin.loginSuccessMsg', { username: resp.data.username }), type: 'success' })
    await fetchReleases()
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.loginFailFallback'), message: parseErrorMessage(err), type: 'error' })
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
    appStore.showNotification({ title: t('admin.logoutSuccessTitle'), type: 'info' })
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
    appStore.showNotification({ title: t('admin.release.versionRequired'), type: 'warning' })
    return
  }
  if (!selectedFile.value) {
    appStore.showNotification({ title: t('admin.release.fileRequired'), type: 'warning' })
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
    if (!resp?.success) throw new Error(resp?.message || t('admin.release.uploadFailFallback'))
    appStore.showNotification({ title: t('admin.release.uploadSuccess'), message: `${PLATFORM_LABELS[uploadForm.platform]} v${uploadForm.version}`, type: 'success' })
    uploadDialogVisible.value = false
    await fetchReleases()
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.release.uploadFailFallback'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    uploading.value = false
  }
}

const deleteRelease = async (item: ReleaseItem) => {
  if (!window.confirm(t('admin.release.deleteConfirm', { platform: PLATFORM_LABELS[item.platform], version: item.version }))) return
  deletingId.value = item.id
  try {
    const resp = await releasesAdminApi.remove(item.id)
    if (!resp?.success) throw new Error(resp?.message || t('admin.release.deleteFailFallback'))
    releases.value = releases.value.filter((r) => r.id !== item.id)
    appStore.showNotification({ title: t('admin.release.deleteSuccess'), message: `${item.filename}`, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.release.deleteFailFallback'), message: parseErrorMessage(err), type: 'error' })
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
            :title="navVisible ? t('admin.toggleSidebarHide') : t('admin.toggleSidebarShow')"
          >
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">{{ t('admin.title') }}</h1>
            <p class="admin-subtitle">{{ t('admin.release.subtitle') }}</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? t('admin.release.badge', { count: releases.length }) : t('admin.badgeNotLoggedIn') }}
          </span>
          <button v-if="isAuthenticated" class="admin-logout-btn" @click="handleLogout">
            <LogOut :size="14" />
            <span>{{ t('admin.logoutBtn') }}</span>
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
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.loginCardTitle') }}</h2>
              <p class="text-sm text-slate-500">{{ t('admin.loginCardDesc') }}</p>
            </div>
            <span class="text-xs text-slate-500">{{ t('admin.secureAccess') }}</span>
          </div>
          <form class="space-y-4 max-w-sm" @submit.prevent="handleLogin">
            <label class="block">
              <span class="text-sm text-slate-700">{{ t('admin.usernameLabel') }}</span>
              <input
                v-model="authForm.username"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="admin"
                autocomplete="username"
              />
            </label>
            <label class="block">
              <span class="text-sm text-slate-700">{{ t('admin.passwordLabel') }}</span>
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
              {{ isLoggingIn ? t('admin.loginBtnLoading') : t('admin.loginBtn') }}
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
              <h2 class="text-lg font-semibold text-slate-900">{{ t('admin.release.listTitle') }}</h2>
              <p v-if="releaseLoadError" class="text-sm text-rose-600 mt-0.5">
                {{ releaseLoadError }}
              </p>
              <p v-else class="text-sm text-slate-500 mt-0.5">{{ t('admin.release.listDesc') }}</p>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="text-sm text-slate-600 hover:text-slate-900 px-3 py-1.5"
                :disabled="loadingReleases"
                @click="fetchReleases"
              >
                <RefreshCw :size="15" />
                {{ loadingReleases ? t('admin.release.syncingBtn') : t('common.refresh') }}
              </button>
              <button
                class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition"
                @click="openUploadDialog"
              >
                <Upload :size="15" />
                <span>{{ t('admin.release.uploadBtn') }}</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Platform Groups -->
        <div
          v-if="releaseLoadError"
          class="bg-white rounded-2xl shadow-sm border border-slate-200 p-8 text-center"
        >
          <h3 class="text-base font-semibold text-slate-900">{{ t('admin.release.loadErrorTitle') }}</h3>
          <p class="text-sm text-slate-500 mt-2">{{ releaseLoadError }}</p>
          <button
            class="mt-4 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition"
            :disabled="loadingReleases"
            @click="fetchReleases"
          >
            <RefreshCw :size="15" />
            <span>{{ loadingReleases ? t('admin.release.syncingBtn') : t('admin.release.reloadBtn') }}</span>
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
                <span class="ml-2 text-xs text-slate-500">{{ t('admin.release.versionCount', { count: groupedReleases[platform].length }) }}</span>
              </div>
            </div>

            <div v-if="!groupedReleases[platform].length" class="px-5 py-8 text-center text-sm text-slate-400">
              {{ t('admin.release.noVersions', { platform: PLATFORM_LABELS[platform] }) }}
            </div>

            <div v-else class="release-table-wrapper overflow-x-auto">
              <table class="min-w-full text-sm text-slate-700">
                <thead>
                  <tr class="border-b border-slate-100 bg-slate-50">
                    <th class="py-2.5 pl-5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.release.colVersion') }}</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.release.colFilename') }}</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.release.colSize') }}</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.release.colDownloads') }}</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.release.colUploadTime') }}</th>
                    <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.release.colNotes') }}</th>
                    <th class="py-2.5 pr-5 text-left font-semibold text-slate-600">{{ t('admin.release.colActions') }}</th>
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
                        {{ deletingId === item.id ? t('admin.release.deletingBtn') : t('admin.release.deleteBtn') }}
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
            <h3 class="text-base font-semibold text-slate-900">{{ t('admin.release.uploadDialogTitle') }}</h3>
            <p class="text-sm text-slate-500 mt-0.5">{{ t('admin.release.uploadDialogDesc') }}</p>
          </div>
          <button class="text-sm text-slate-500 hover:text-slate-800" :disabled="uploading" @click="closeUploadDialog">{{ t('admin.release.closeBtn') }}</button>
        </div>

        <!-- Platform selector -->
        <div class="mb-5">
          <span class="text-sm font-medium text-slate-700 block mb-2">{{ t('admin.release.platformLabel') }}</span>
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
            <span class="text-sm text-slate-700">{{ t('admin.release.versionLabel') }} <span class="text-rose-500">*</span></span>
            <input
              v-model="uploadForm.version"
              type="text"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              :placeholder="t('admin.release.versionPlaceholder')"
            />
          </label>
          <label class="block">
            <span class="text-sm text-slate-700">{{ t('admin.release.notesLabel') }}</span>
            <input
              v-model="uploadForm.description"
              type="text"
              class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
              :placeholder="t('admin.release.notesPlaceholder')"
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
            <p class="text-sm text-slate-500">{{ t('admin.release.dropZoneHint') }}</p>
            <p class="text-xs text-slate-400">{{ t('admin.release.dropZoneFormats') }}</p>
          </div>
        </div>

        <div class="flex justify-end gap-2">
          <button
            class="px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            :disabled="uploading"
            @click="closeUploadDialog"
          >
            {{ t('admin.release.cancelBtn') }}
          </button>
          <button
            class="px-5 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-60"
            :disabled="uploading"
            @click="submitUpload"
          >
            {{ uploading ? t('admin.release.uploadingBtn') : t('admin.release.confirmUploadBtn') }}
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
