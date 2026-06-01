<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { releasesPublicApi } from '@/api/releases'
import PlatformBrandIcon from '@/components/icons/PlatformBrandIcon.vue'
import type { ReleaseItem } from '@/types'
import WorkbenchTopbar from '@/layouts/WorkbenchTopbar.vue'

const loading = ref(true)
const releases = ref<ReleaseItem[]>([])
const error = ref('')

const PLATFORM_CONFIG = {
  linux: {
    label: 'Linux',
    gradient: 'from-orange-50 to-amber-50',
    border: 'border-orange-200',
    accent: 'text-orange-600',
    badge: 'bg-orange-100 text-orange-700',
    btn: 'bg-orange-500 hover:bg-orange-600',
    btnLight: 'border-orange-200 text-orange-600 hover:bg-orange-50',
    description: '适用于主流 Linux 发行版（Ubuntu、Debian、CentOS、Arch 等）',
    fileHint: '.tar.gz / .deb / .rpm',
  },
  macos: {
    label: 'macOS',
    gradient: 'from-blue-50 to-sky-50',
    border: 'border-blue-200',
    accent: 'text-blue-600',
    badge: 'bg-blue-100 text-blue-700',
    btn: 'bg-blue-500 hover:bg-blue-600',
    btnLight: 'border-blue-200 text-blue-600 hover:bg-blue-50',
    description: '适用于 macOS 10.14 (Mojave) 及更高版本，支持 Intel 与 Apple Silicon',
    fileHint: '.dmg / .pkg',
  },
  windows: {
    label: 'Windows',
    gradient: 'from-sky-50 to-cyan-50',
    border: 'border-sky-200',
    accent: 'text-sky-600',
    badge: 'bg-sky-100 text-sky-700',
    btn: 'bg-sky-500 hover:bg-sky-600',
    btnLight: 'border-sky-200 text-sky-600 hover:bg-sky-50',
    description: '适用于 Windows 10 及更高版本，64 位系统',
    fileHint: '.exe / .msi',
  },
} as const

type Platform = keyof typeof PLATFORM_CONFIG

const groupedReleases = computed(() => {
  const groups: Record<Platform, ReleaseItem[]> = { linux: [], macos: [], windows: [] }
  for (const r of releases.value) {
    const p = r.platform as Platform
    if (groups[p]) groups[p].push(r)
  }
  return groups
})

const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

const formatDate = (value: string): string => {
  try {
    return new Date(value).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return value
  }
}

const handleDownload = (item: ReleaseItem) => {
  const url = releasesPublicApi.getDownloadUrl(item.id)
  const a = document.createElement('a')
  a.href = url
  a.download = item.filename
  a.click()
}

const fetchReleases = async () => {
  loading.value = true
  error.value = ''
  try {
    const resp = await releasesPublicApi.list()
    if (resp?.success) {
      releases.value = resp.data || []
    }
  } catch (err: any) {
    error.value = '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const hasAnyRelease = computed(() => releases.value.length > 0)
const selectedPlatform = ref<Platform | null>(null)
const detailGroups = computed(() => groupedReleases.value)

const toggleHistory = (platform: Platform) => {
  selectedPlatform.value = selectedPlatform.value === platform ? null : platform
}

onMounted(() => fetchReleases())
</script>

<template>
  <div class="rw-page">
    <WorkbenchTopbar title="下载客户端" :meta="hasAnyRelease ? `${releases.length} 个发布物` : 'Release Center'">
      <template #actions>
        <button type="button" class="rw-btn-secondary" :disabled="loading" @click="fetchReleases">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 12a9 9 0 0 1 15.5-6.4L21 8" />
            <path d="M21 3v5h-5" />
            <path d="M21 12a9 9 0 0 1-15.5 6.4L3 16" />
            <path d="M3 21v-5h5" />
          </svg>
          <span>{{ loading ? '同步中…' : '刷新' }}</span>
        </button>
      </template>
    </WorkbenchTopbar>

    <div class="rw-page-scroll">
      <div class="download-page">
        <!-- Hero -->
        <section class="hero-section">
          <div class="container mx-auto px-4 py-16 text-center">
            <div class="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-50 border border-blue-100 text-blue-600 text-xs font-semibold mb-6">
              <span class="h-1.5 w-1.5 rounded-full bg-blue-500 animate-pulse"></span>
              正式发布版
            </div>
            <h1 class="text-4xl sm:text-5xl font-bold text-slate-900 mb-4 leading-tight">
              下载 Raven
              <span class="bg-gradient-to-r from-blue-600 to-cyan-500 bg-clip-text text-transparent">客户端</span>
            </h1>
            <p class="text-lg text-slate-500 max-w-lg mx-auto mb-8">
              智能测试平台桌面客户端，支持 Linux、macOS 和 Windows，随时随地进行日志分析与设备协同。
            </p>
            <div v-if="loading" class="flex items-center justify-center gap-2 text-slate-400 text-sm">
              <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2.5" stroke-dasharray="15 45" />
              </svg>
              正在获取最新版本…
            </div>
          </div>
        </section>

        <!-- Platform Cards -->
        <section class="container mx-auto px-4 pb-16 max-w-5xl">
          <div v-if="error" class="text-center py-16 text-slate-400">
            <p class="text-base">{{ error }}</p>
            <button class="mt-4 text-sm text-blue-600 hover:underline" @click="fetchReleases">重试</button>
          </div>

          <div v-else-if="!loading && !hasAnyRelease" class="text-center py-20">
            <div class="inline-flex items-center justify-center w-16 h-16 rounded-full bg-slate-100 mb-4">
              <svg class="h-8 w-8 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
              </svg>
            </div>
            <h3 class="text-lg font-semibold text-slate-700 mb-1">暂无发布版本</h3>
            <p class="text-sm text-slate-400">请关注官方渠道获取最新版本信息</p>
          </div>

          <div v-else class="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div
              v-for="platform in (['linux', 'macos', 'windows'] as Platform[])"
              :key="platform"
              class="platform-card rounded-2xl border p-6 flex flex-col"
              :class="[`bg-gradient-to-br ${PLATFORM_CONFIG[platform].gradient}`, PLATFORM_CONFIG[platform].border]"
            >
              <!-- Platform Icon & Label -->
              <div class="flex items-start justify-between mb-5">
                <div class="flex items-center gap-3">
                  <div class="platform-icon">
                    <PlatformBrandIcon :platform="platform" />
                  </div>
                  <div>
                    <h2 class="text-lg font-bold text-slate-900">{{ PLATFORM_CONFIG[platform].label }}</h2>
                    <p class="text-xs text-slate-500 mt-0.5">{{ PLATFORM_CONFIG[platform].fileHint }}</p>
                  </div>
                </div>
                <span
                  v-if="detailGroups[platform].length"
                  class="text-xs font-semibold px-2 py-0.5 rounded-full"
                  :class="PLATFORM_CONFIG[platform].badge"
                >
                  v{{ detailGroups[platform][0].version }}
                </span>
              </div>

              <!-- Description -->
              <p class="text-xs text-slate-500 leading-relaxed mb-5">
                {{ PLATFORM_CONFIG[platform].description }}
              </p>

              <!-- No release state -->
              <div v-if="!detailGroups[platform].length" class="mt-auto text-center py-4">
                <p class="text-sm text-slate-400">暂未发布</p>
              </div>

              <!-- Latest release -->
              <template v-else>
                <div class="release-meta flex items-center gap-3 text-xs text-slate-500 mb-5 py-3 border-t border-black/5">
                  <span>{{ formatDate(detailGroups[platform][0].created_at) }}</span>
                  <span class="h-1 w-1 rounded-full bg-slate-300"></span>
                  <span>{{ formatBytes(detailGroups[platform][0].file_size) }}</span>
                  <span class="h-1 w-1 rounded-full bg-slate-300"></span>
                  <span>↓ {{ detailGroups[platform][0].download_count }}</span>
                </div>

                <div class="mt-auto space-y-2">
                  <button
                    class="w-full py-2.5 rounded-xl text-sm font-semibold text-white transition shadow-sm"
                    :class="PLATFORM_CONFIG[platform].btn"
                    @click="handleDownload(detailGroups[platform][0])"
                  >
                    立即下载
                  </button>
                  <button
                    v-if="detailGroups[platform].length > 1"
                    class="w-full py-2 rounded-xl text-xs font-medium border bg-white/50 transition"
                    :class="PLATFORM_CONFIG[platform].btnLight"
                    @click="toggleHistory(platform)"
                  >
                    {{ selectedPlatform === platform ? '收起' : `查看历史版本 (${detailGroups[platform].length - 1})` }}
                  </button>
                </div>

                <!-- History list -->
                <div
                  v-if="selectedPlatform === platform && detailGroups[platform].length > 1"
                  class="history-list mt-4 space-y-2"
                >
                  <div
                    v-for="item in detailGroups[platform].slice(1)"
                    :key="item.id"
                    class="flex items-center justify-between py-2 px-3 rounded-lg bg-white/60 border border-black/5"
                  >
                    <div>
                      <span class="text-xs font-semibold text-slate-700">v{{ item.version }}</span>
                      <span class="ml-2 text-xs text-slate-400">{{ formatBytes(item.file_size) }}</span>
                    </div>
                    <button
                      class="text-xs px-2.5 py-1 rounded-lg border bg-white transition"
                      :class="PLATFORM_CONFIG[platform].btnLight"
                      @click="handleDownload(item)"
                    >
                      下载
                    </button>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- Info strip -->
          <div v-if="hasAnyRelease && !loading" class="mt-10 grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div class="info-strip-item flex items-start gap-3 p-4 rounded-xl bg-white border border-slate-100 shadow-sm">
              <div class="flex-shrink-0 w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
                <svg class="h-4 w-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <div>
                <p class="text-sm font-semibold text-slate-800">安全可信</p>
                <p class="text-xs text-slate-500 mt-0.5">所有安装包由内部构建系统统一发布</p>
              </div>
            </div>
            <div class="info-strip-item flex items-start gap-3 p-4 rounded-xl bg-white border border-slate-100 shadow-sm">
              <div class="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
                <svg class="h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              </div>
              <div>
                <p class="text-sm font-semibold text-slate-800">持续更新</p>
                <p class="text-xs text-slate-500 mt-0.5">功能迭代与 Bug 修复定期跟进</p>
              </div>
            </div>
            <div class="info-strip-item flex items-start gap-3 p-4 rounded-xl bg-white border border-slate-100 shadow-sm">
              <div class="flex-shrink-0 w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
                <svg class="h-4 w-4 text-purple-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
              </div>
              <div>
                <p class="text-sm font-semibold text-slate-800">技术支持</p>
                <p class="text-xs text-slate-500 mt-0.5">遇到问题可联系内部技术团队</p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

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
  background: #f8fafc;
}

.rw-btn-secondary {
  height: 34px;
  border-radius: 8px;
  padding: 0 12px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--rw-hairline-strong, #dcdee0);
  background: var(--rw-canvas, #ffffff);
  color: var(--rw-ink, #171717);
  font-size: 13px;
  font-weight: 600;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.rw-btn-secondary:hover:not(:disabled) {
  background: var(--rw-surface-strong, #f0f0f3);
}

.rw-btn-secondary:disabled {
  opacity: 0.6;
  cursor: default;
}

.download-page {
  min-height: 100%;
  background: #f8fafc;
}

.hero-section {
  background: linear-gradient(160deg, #ffffff 0%, #f0f9ff 50%, #e0f2fe 100%);
  border-bottom: 1px solid #e2e8f0;
}

.platform-card {
  border-radius: 8px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.platform-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}

.platform-icon {
  width: 2.75rem;
  height: 2.75rem;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.95rem;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.16);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.65),
    0 8px 18px rgba(15, 23, 42, 0.06);
}

.history-list {
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 640px) {
  .hero-section {
    padding-top: 2rem;
  }
}
</style>
