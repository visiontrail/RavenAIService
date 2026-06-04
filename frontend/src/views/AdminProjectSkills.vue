<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  File as FileIcon,
  FileArchive,
  FileText,
  Folder,
  FolderOpen,
  FolderTree,
  LogOut,
  Menu,
  PanelLeftClose,
  Power,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import { renderMarkdown } from '@/utils/markdownRenderer'
import type {
  AgentSkill,
  SkillFileContent,
  SkillFileNode,
} from '@/types'

const { t } = useI18n()
const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = adminNavItems

const projectCode = computed(() => route.params.projectCode as string)

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingSkills = ref(false)
const uploading = ref(false)
const uploadPercent = ref(0)
const togglingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)

const skills = ref<AgentSkill[]>([])

const overwrite = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

const manageSkill = ref<AgentSkill | null>(null)
const skillTreeRoot = ref<SkillFileNode | null>(null)
const skillTreeLoading = ref(false)
const expandedDirs = ref<Set<string>>(new Set())
const activeFilePath = ref<string | null>(null)
const activeFileContent = ref<SkillFileContent | null>(null)
const activeFileLoading = ref(false)
const activeFileError = ref<string | null>(null)

interface FlatTreeRow {
  node: SkillFileNode
  depth: number
}

const flatTreeRows = computed<FlatTreeRow[]>(() => {
  const root = skillTreeRoot.value
  if (!root) return []
  const rows: FlatTreeRow[] = []
  const walk = (children: SkillFileNode[] | undefined, depth: number) => {
    if (!children) return
    for (const node of children) {
      rows.push({ node, depth })
      if (node.type === 'dir' && expandedDirs.value.has(node.path)) {
        walk(node.children, depth + 1)
      }
    }
  }
  walk(root.children, 0)
  return rows
})

const authForm = reactive({
  username: '',
  password: '',
})

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const enabledCount = computed(() => skills.value.filter((s) => s.enabled).length)
const disabledCount = computed(() => skills.value.length - enabledCount.value)

const isMarkdownFile = computed<boolean>(() => {
  const path = activeFilePath.value
  if (!path) return false
  const lower = path.toLowerCase()
  return lower.endsWith('.md') || lower.endsWith('.markdown')
})

interface FrontmatterSplit {
  frontmatter: Record<string, string> | null
  body: string
}

const escapeHtml = (s: string): string =>
  s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case '&': return '&amp;'
      case '<': return '&lt;'
      case '>': return '&gt;'
      case '"': return '&quot;'
      case "'": return '&#39;'
      default: return c
    }
  })

const splitFrontmatter = (raw: string): FrontmatterSplit => {
  const text = raw.replace(/\r\n/g, '\n')
  const m = text.match(/^---\s*\n([\s\S]*?)\n---\s*(?:\n|$)/)
  if (!m) return { frontmatter: null, body: text }
  const block = m[1]
  const fm: Record<string, string> = {}
  let currentKey: string | null = null
  for (const line of block.split('\n')) {
    const kv = line.match(/^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/)
    if (kv) {
      currentKey = kv[1]
      fm[currentKey] = kv[2].trim().replace(/^['"]|['"]$/g, '')
    } else if (currentKey && line.trim()) {
      fm[currentKey] = `${fm[currentKey]} ${line.trim()}`.trim()
    }
  }
  return { frontmatter: fm, body: text.slice(m[0].length) }
}

const renderedFrontmatter = computed<string>(() => {
  if (!isMarkdownFile.value) return ''
  const content = activeFileContent.value?.content
  if (!content) return ''
  const { frontmatter } = splitFrontmatter(content)
  if (!frontmatter) return ''
  const rows = Object.entries(frontmatter).map(
    ([k, v]) =>
      `<div class="skill-fm-row"><span class="skill-fm-key">${escapeHtml(k)}</span><span class="skill-fm-val">${escapeHtml(v)}</span></div>`
  )
  return `<div class="skill-fm-card">${rows.join('')}</div>`
})

const renderedMarkdown = computed<string>(() => {
  if (!isMarkdownFile.value) return ''
  const content = activeFileContent.value?.content
  if (!content) return ''
  const { body } = splitFrontmatter(content)
  return renderMarkdown(body, { cleanXml: false, wrapperClass: 'skill-markdown' })
})

const parseErrorMessage = (err: any): string => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return t('admin.parseError')
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

const formatSize = (bytes: number): string => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  skills.value = []
  authForm.password = ''
}

const handleLogin = async () => {
  if (!authForm.username.trim() || !authForm.password) {
    appStore.showNotification({ title: t('admin.loginWarning'), type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data?.token) throw new Error(resp?.message || t('admin.loginFailFallback'))
    adminToken.set(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({
      title: t('admin.loginSuccessTitle'),
      message: t('admin.loginSuccessMsg', { username: resp.data.username }),
      type: 'success',
    })
    await fetchSkills()
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
    appStore.showNotification({ title: t('admin.logoutSuccessTitle'), type: 'info' })
  }
}

const fetchSkills = async () => {
  if (!isAuthenticated.value || !projectCode.value) return
  loadingSkills.value = true
  try {
    const resp = await adminApi.listProjectSkills(projectCode.value)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.projectSkills.loadSkillsFail'))
    skills.value = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.loadFail'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingSkills.value = false
  }
}

watch(projectCode, () => {
  skills.value = []
  if (projectCode.value) fetchSkills()
})

const handleNavClick = (item: (typeof navItems)[number]) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => appStore.toggleAdminSidebar()

const triggerFilePicker = () => {
  fileInput.value?.click()
}

const handleFileChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) await uploadSkillFile(file)
  target.value = ''
}

const handleDrop = async (event: DragEvent) => {
  event.preventDefault()
  dragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) await uploadSkillFile(file)
}

const uploadSkillFile = async (file: File) => {
  if (!projectCode.value) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    appStore.showNotification({
      title: t('admin.skills.invalidFormat'),
      message: t('admin.skills.invalidFormatMsg'),
      type: 'warning',
    })
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    const resp = await adminApi.uploadProjectSkill(
      projectCode.value,
      file,
      overwrite.value,
      (p) => (uploadPercent.value = p)
    )
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.skills.uploadFailFallback'))
    appStore.showNotification({
      title: t('admin.skills.uploadSuccess'),
      message: t('admin.skills.uploadSuccessMsg', { name: resp.data.name }),
      type: 'success',
    })
    await fetchSkills()
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.skills.uploadFailFallback'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    uploading.value = false
    uploadPercent.value = 0
  }
}

const toggleSkill = async (skill: AgentSkill) => {
  togglingId.value = skill.id
  try {
    const resp = await adminApi.updateProjectSkill(projectCode.value, skill.id, {
      enabled: !skill.enabled,
    })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.skills.updateFailFallback'))
    const idx = skills.value.findIndex((s) => s.id === skill.id)
    if (idx >= 0) skills.value[idx] = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.skills.updateFailFallback'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    togglingId.value = null
  }
}

const deleteSkill = async (skill: AgentSkill) => {
  if (!window.confirm(t('admin.skills.deleteConfirm', { name: skill.name }))) return
  deletingId.value = skill.id
  try {
    await adminApi.deleteProjectSkill(projectCode.value, skill.id)
    skills.value = skills.value.filter((s) => s.id !== skill.id)
    appStore.showNotification({ title: t('admin.skills.deleteSuccess'), message: skill.name, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: t('admin.skills.deleteFailFallback'), message: parseErrorMessage(err), type: 'error' })
  } finally {
    deletingId.value = null
  }
}

const collectInitialExpandedDirs = (root: SkillFileNode | null): Set<string> => {
  const out = new Set<string>()
  if (!root?.children) return out
  for (const c of root.children) {
    if (c.type === 'dir') out.add(c.path)
  }
  return out
}

const findFirstReadableFile = (root: SkillFileNode | null): SkillFileNode | null => {
  if (!root?.children) return null
  const stack: SkillFileNode[] = [...root.children]
  let fallback: SkillFileNode | null = null
  while (stack.length) {
    const node = stack.shift() as SkillFileNode
    if (node.type === 'file') {
      if (node.name.toLowerCase() === 'skill.md') return node
      if (!fallback) fallback = node
    } else if (node.children) {
      stack.push(...node.children)
    }
  }
  return fallback
}

const openSkillManager = async (skill: AgentSkill) => {
  manageSkill.value = skill
  skillTreeRoot.value = null
  activeFilePath.value = null
  activeFileContent.value = null
  activeFileError.value = null
  expandedDirs.value = new Set()
  skillTreeLoading.value = true
  try {
    const resp = await adminApi.listProjectSkillFiles(projectCode.value, skill.id)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.skills.loadingSkills'))
    skillTreeRoot.value = resp.data.tree
    expandedDirs.value = collectInitialExpandedDirs(resp.data.tree)
    const first = findFirstReadableFile(resp.data.tree)
    if (first) await selectSkillFile(first)
  } catch (err: any) {
    appStore.showNotification({
      title: t('admin.skills.loadFileFailTitle'),
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    skillTreeLoading.value = false
  }
}

const closeSkillManager = () => {
  manageSkill.value = null
  skillTreeRoot.value = null
  activeFilePath.value = null
  activeFileContent.value = null
  activeFileError.value = null
  expandedDirs.value = new Set()
}

const toggleDir = (node: SkillFileNode) => {
  if (node.type !== 'dir') return
  const next = new Set(expandedDirs.value)
  if (next.has(node.path)) next.delete(node.path)
  else next.add(node.path)
  expandedDirs.value = next
}

const selectSkillFile = async (node: SkillFileNode) => {
  if (node.type !== 'file' || !manageSkill.value) return
  activeFilePath.value = node.path
  activeFileContent.value = null
  activeFileError.value = null
  activeFileLoading.value = true
  try {
    const resp = await adminApi.readProjectSkillFile(
      projectCode.value,
      manageSkill.value.id,
      node.path
    )
    if (!resp?.success || !resp.data) throw new Error(resp?.message || t('admin.skills.readingFile'))
    activeFileContent.value = resp.data
  } catch (err: any) {
    activeFileError.value = parseErrorMessage(err)
  } finally {
    activeFileLoading.value = false
  }
}

const goBack = () => {
  router.push('/admin/project-repos')
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await fetchSkills()
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
  <div class="admin-console admin-project-skills-page">
    <header class="admin-topbar">
      <div class="admin-topbar-inner">
        <div class="admin-topbar-left">
          <button
            class="admin-icon-btn"
            :disabled="!isAuthenticated"
            @click="toggleNavVisibility"
            :title="navVisible ? t('admin.toggleSidebarHide') : t('admin.toggleSidebarShow')"
            :aria-label="t('admin.toggleSidebarAriaLabel')"
          >
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">{{ t('admin.title') }}</h1>
            <p class="admin-subtitle">{{ t('admin.projectSkills.subtitle') }}</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated
              ? t('admin.projectSkills.badge', { enabled: enabledCount, disabled: disabledCount })
              : t('admin.badgeNotLoggedIn') }}
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
      :aria-label="t('admin.closeSidebarAriaLabel')"
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

      <section v-else class="space-y-4">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div class="flex items-center gap-3 mb-1">
                <button
                  class="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-cyan-600 transition"
                  @click="goBack"
                >
                  <ArrowLeft :size="16" />
                  {{ t('admin.projectSkills.backToRepos') }}
                </button>
              </div>
              <h2 class="text-lg font-semibold text-slate-900">
                {{ t('admin.projectSkills.listTitle') }}
                <code class="ml-2 rounded bg-slate-100 px-2 py-0.5 text-sm font-mono text-slate-600">{{ projectCode }}</code>
              </h2>
              <p class="text-sm text-slate-500 mt-0.5">
                {{ t('admin.projectSkills.listDesc') }}
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button
                class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loadingSkills"
                @click="fetchSkills"
              >
                <RefreshCw :size="15" />
                {{ loadingSkills ? t('admin.refreshing') : t('common.refresh') }}
              </button>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">{{ t('admin.skills.uploadSkillTitle') }}</h3>
              <p class="mt-1 text-xs text-slate-500" v-html="t('admin.skills.skillRequirements')"></p>
            </div>
            <label class="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600">
              <input v-model="overwrite" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500" />
              {{ t('admin.skills.overwriteSkill') }}
            </label>
          </div>

          <div
            class="mt-4 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-8 text-center transition"
            :class="dragOver ? 'border-cyan-400 bg-cyan-50' : 'border-slate-200 bg-slate-50'"
            @dragover.prevent="dragOver = true"
            @dragleave.prevent="dragOver = false"
            @drop="handleDrop"
          >
            <FileArchive :size="36" class="text-slate-400" />
            <p class="mt-2 text-sm text-slate-600">
              {{ t('admin.skills.dropZoneHint') }}
              <button class="ml-1 text-cyan-600 underline-offset-2 hover:underline" @click="triggerFilePicker">{{ t('admin.skills.clickSelectFile') }}</button>
            </p>
            <p class="mt-1 text-xs text-slate-400">{{ t('admin.skills.fileSizeHint') }}</p>
            <div v-if="uploading" class="mt-3 w-full max-w-sm">
              <div class="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden">
                <div class="h-full bg-cyan-500 transition-all" :style="{ width: `${uploadPercent}%` }"></div>
              </div>
              <p class="mt-1 text-xs text-slate-500">{{ t('admin.skills.uploadingProgress', { percent: uploadPercent }) }}</p>
            </div>
            <input
              ref="fileInput"
              type="file"
              accept=".zip,application/zip"
              class="hidden"
              @change="handleFileChange"
            />
          </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
          <div class="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
            <p class="text-sm font-semibold text-slate-900">{{ t('admin.skills.installedTitle') }}</p>
            <p class="text-xs text-slate-400">{{ t('admin.skills.installedCount', { count: skills.length }) }}</p>
          </div>

          <div v-if="loadingSkills" class="px-5 py-12 text-center text-sm text-slate-400">
            {{ t('admin.skills.loadingSkills') }}
          </div>

          <div v-else-if="!skills.length" class="px-5 py-12 text-center">
            <p class="text-sm font-medium text-slate-700">{{ t('admin.skills.noSkillsTitle') }}</p>
            <p class="mt-1 text-xs text-slate-400">{{ t('admin.projectSkills.noSkillsHint') }}</p>
          </div>

          <div v-else class="overflow-x-auto">
            <table class="min-w-full text-sm text-slate-700">
              <thead>
                <tr class="border-b border-slate-100 bg-slate-50">
                  <th class="py-2.5 pl-5 pr-4 text-left font-semibold text-slate-600">Skill</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.skills.colSourceZip') }}</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.skills.colSize') }}</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.skills.colStatus') }}</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">{{ t('admin.skills.colUpdatedAt') }}</th>
                  <th class="py-2.5 pr-5 text-right font-semibold text-slate-600">{{ t('admin.skills.colActions') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="skill in skills"
                  :key="skill.id"
                  class="skill-row border-b border-slate-50 hover:bg-slate-50/70 transition-colors cursor-pointer"
                  :title="t('admin.skills.previewSkillTitleAttr', { name: skill.name })"
                  @click="openSkillManager(skill)"
                >
                  <td class="py-3 pl-5 pr-4">
                    <div class="flex items-center gap-2">
                      <span class="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono text-slate-700">
                        {{ skill.name }}
                      </span>
                    </div>
                    <p v-if="skill.description" class="mt-1 max-w-[420px] text-xs text-slate-500" :title="skill.description">
                      {{ skill.description }}
                    </p>
                  </td>
                  <td class="py-3 pr-4">
                    <span class="block max-w-[260px] truncate font-mono text-xs text-slate-500" :title="skill.source_filename">
                      {{ skill.source_filename || '--' }}
                    </span>
                  </td>
                  <td class="py-3 pr-4 text-xs text-slate-500">{{ formatSize(skill.size_bytes) }}</td>
                  <td class="py-3 pr-4">
                    <span
                      class="inline-flex rounded-full px-2 py-1 text-xs font-semibold"
                      :class="skill.enabled ? 'bg-cyan-50 text-cyan-700' : 'bg-slate-100 text-slate-500'"
                    >
                      {{ skill.enabled ? t('admin.skills.statusEnabled') : t('admin.skills.statusDisabled') }}
                    </span>
                  </td>
                  <td class="py-3 pr-4 whitespace-nowrap text-xs text-slate-400">{{ formatTimestamp(skill.updated_at) }}</td>
                  <td class="py-3 pr-5" @click.stop>
                    <div class="flex justify-end gap-2">
                      <button
                        class="admin-action-btn"
                        :title="t('admin.skills.fileStructure')"
                        @click.stop="openSkillManager(skill)"
                      >
                        <FolderTree :size="15" />
                      </button>
                      <button
                        class="admin-action-btn"
                        :disabled="togglingId === skill.id"
                        :title="skill.enabled ? t('admin.skills.statusDisabled') : t('admin.skills.statusEnabled')"
                        @click.stop="toggleSkill(skill)"
                      >
                        <Power :size="15" />
                      </button>
                      <button
                        class="admin-action-btn danger"
                        :disabled="deletingId === skill.id"
                        :title="t('common.delete')"
                        @click.stop="deleteSkill(skill)"
                      >
                        <Trash2 :size="15" />
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>

    <div
      v-if="manageSkill"
      class="skill-manager-overlay"
      role="dialog"
      aria-modal="true"
      @click.self="closeSkillManager"
    >
      <div class="skill-manager-panel">
        <header class="skill-manager-header">
          <div class="min-w-0">
            <p class="text-xs text-slate-400 uppercase tracking-wide">{{ t('admin.skills.previewTitle') }}</p>
            <h2 class="text-base font-semibold text-slate-900 truncate">
              {{ manageSkill.name }}
            </h2>
            <p
              v-if="manageSkill.description"
              class="mt-0.5 text-xs text-slate-500 truncate"
              :title="manageSkill.description"
            >
              {{ manageSkill.description }}
            </p>
          </div>
          <button
            class="skill-manager-close"
            :aria-label="t('admin.closeSidebarAriaLabel')"
            @click="closeSkillManager"
          >
            <X :size="18" />
          </button>
        </header>

        <div class="skill-manager-body">
          <aside class="skill-tree-pane">
            <div class="skill-tree-title">
              <FolderTree :size="14" />
              <span>{{ t('admin.skills.fileStructure') }}</span>
            </div>
            <div v-if="skillTreeLoading" class="skill-tree-empty">{{ t('admin.skills.loadingTree') }}</div>
            <div
              v-else-if="!flatTreeRows.length"
              class="skill-tree-empty"
            >
              {{ t('admin.skills.noFiles') }}
            </div>
            <ul v-else class="skill-tree-list">
              <li
                v-for="row in flatTreeRows"
                :key="row.node.path"
                class="skill-tree-row"
                :class="{
                  'is-active':
                    row.node.type === 'file' && row.node.path === activeFilePath,
                }"
                :style="{ paddingLeft: `${row.depth * 14 + 8}px` }"
                @click="row.node.type === 'dir' ? toggleDir(row.node) : selectSkillFile(row.node)"
              >
                <span class="skill-tree-icon">
                  <template v-if="row.node.type === 'dir'">
                    <ChevronDown
                      v-if="expandedDirs.has(row.node.path)"
                      :size="12"
                      class="skill-tree-chevron"
                    />
                    <ChevronRight v-else :size="12" class="skill-tree-chevron" />
                    <FolderOpen
                      v-if="expandedDirs.has(row.node.path)"
                      :size="14"
                      class="text-amber-500"
                    />
                    <Folder v-else :size="14" class="text-amber-500" />
                  </template>
                  <template v-else>
                    <span class="skill-tree-chevron-placeholder"></span>
                    <FileText
                      v-if="row.node.name.toLowerCase() === 'skill.md'"
                      :size="14"
                      class="text-cyan-600"
                    />
                    <FileIcon v-else :size="14" class="text-slate-400" />
                  </template>
                </span>
                <span class="skill-tree-name" :title="row.node.name">
                  {{ row.node.name }}
                </span>
                <span
                  v-if="row.node.type === 'file' && row.node.size != null"
                  class="skill-tree-size"
                >
                  {{ formatSize(row.node.size) }}
                </span>
              </li>
            </ul>
          </aside>

          <section class="skill-content-pane">
            <div class="skill-content-header">
              <div class="min-w-0">
                <p
                  v-if="activeFilePath"
                  class="font-mono text-xs text-slate-700 truncate"
                  :title="activeFilePath"
                >
                  {{ activeFilePath }}
                </p>
                <p v-else class="text-xs text-slate-400">
                  {{ t('admin.skills.selectFileHint') }}
                </p>
              </div>
              <div
                v-if="activeFileContent"
                class="flex items-center gap-2 text-xs text-slate-400"
              >
                <span>{{ formatSize(activeFileContent.size) }}</span>
                <span
                  v-if="activeFileContent.truncated"
                  class="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700"
                >
                  {{ t('admin.skills.truncated') }}
                </span>
              </div>
            </div>

            <div class="skill-content-body">
              <div v-if="activeFileLoading" class="skill-content-msg">
                {{ t('admin.skills.readingFile') }}
              </div>
              <div v-else-if="activeFileError" class="skill-content-msg text-rose-600">
                {{ activeFileError }}
              </div>
              <div
                v-else-if="!activeFileContent && !activeFilePath"
                class="skill-content-msg"
              >
                {{ t('admin.skills.noFileSelected') }}
              </div>
              <div
                v-else-if="activeFileContent && activeFileContent.encoding === 'binary'"
                class="skill-content-msg"
              >
                {{ t('admin.skills.binaryFile', { size: formatSize(activeFileContent.size) }) }}
              </div>
              <div
                v-else-if="activeFileContent && isMarkdownFile && renderedMarkdown"
                class="skill-content-markdown"
              >
                <div v-if="renderedFrontmatter" v-html="renderedFrontmatter"></div>
                <div v-html="renderedMarkdown"></div>
              </div>
              <pre
                v-else-if="activeFileContent && activeFileContent.content !== undefined"
                class="skill-content-pre"
              ><code>{{ activeFileContent.content }}</code></pre>
            </div>
          </section>
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

.admin-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  border: 1px solid #cbd5e1;
  color: #475569;
  background: #ffffff;
  transition: all 0.15s ease;
}

.admin-action-btn:hover:not(:disabled) {
  border-color: #22d3ee;
  color: #0891b2;
  background: #ecfeff;
}

.admin-action-btn.danger:hover:not(:disabled) {
  border-color: #fecdd3;
  color: #e11d48;
  background: #fff1f2;
}

.admin-action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Skill manager modal */

.skill-manager-overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
}

.skill-manager-panel {
  width: min(1100px, 100%);
  height: min(720px, 100%);
  background: #ffffff;
  border-radius: 1rem;
  box-shadow: 0 25px 60px rgba(15, 23, 42, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.skill-manager-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.9rem 1.1rem;
  border-bottom: 1px solid #e2e8f0;
  background: linear-gradient(180deg, #f8fafc, #ffffff);
}

.skill-manager-close {
  width: 2rem;
  height: 2rem;
  border-radius: 0.55rem;
  border: 1px solid #e2e8f0;
  color: #475569;
  background: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.skill-manager-close:hover {
  border-color: #cbd5e1;
  background: #f1f5f9;
}

.skill-manager-body {
  flex: 1;
  display: grid;
  grid-template-columns: 280px 1fr;
  min-height: 0;
}

.skill-tree-pane {
  border-right: 1px solid #e2e8f0;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.skill-tree-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.6rem 0.85rem;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #64748b;
  border-bottom: 1px solid #e2e8f0;
}

.skill-tree-empty {
  padding: 1rem 0.85rem;
  font-size: 0.78rem;
  color: #94a3b8;
}

.skill-tree-list {
  flex: 1;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 0.25rem 0;
}

.skill-tree-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.6rem 0.3rem 0.5rem;
  font-size: 0.8rem;
  color: #334155;
  cursor: pointer;
  user-select: none;
  border-radius: 0;
}

.skill-tree-row:hover {
  background: #e2e8f0;
}

.skill-tree-row.is-active {
  background: #cffafe;
  color: #0e7490;
  font-weight: 500;
}

.skill-tree-icon {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  flex-shrink: 0;
  color: #64748b;
}

.skill-tree-chevron {
  color: #94a3b8;
}

.skill-tree-chevron-placeholder {
  display: inline-block;
  width: 12px;
}

.skill-tree-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
}

.skill-tree-size {
  font-size: 0.68rem;
  color: #94a3b8;
  flex-shrink: 0;
}

.skill-content-pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.skill-content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.55rem 0.95rem;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
}

.skill-content-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #0f172a;
}

.skill-content-msg {
  padding: 2rem;
  font-size: 0.85rem;
  color: #cbd5e1;
  text-align: center;
}

.skill-content-pre {
  margin: 0;
  padding: 1rem 1.2rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  line-height: 1.55;
  color: #e2e8f0;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: visible;
}

.skill-content-markdown {
  padding: 1.25rem 1.5rem;
  background: #ffffff;
  color: #1e293b;
  font-size: 0.9rem;
  line-height: 1.7;
  min-height: 100%;
}

.skill-content-markdown :deep(.skill-markdown) {
  max-width: 880px;
  margin: 0 auto;
}

.skill-content-markdown :deep(.skill-fm-card) {
  max-width: 880px;
  margin: 0 auto 1.2em;
  padding: 0.85rem 1rem;
  background: linear-gradient(135deg, #ecfeff 0%, #f0f9ff 100%);
  border: 1px solid #bae6fd;
  border-radius: 0.6rem;
  display: grid;
  gap: 0.45rem;
}

.skill-content-markdown :deep(.skill-fm-row) {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 0.75rem;
  align-items: start;
  font-size: 0.85rem;
  line-height: 1.55;
}

.skill-content-markdown :deep(.skill-fm-key) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: #0e7490;
  padding-top: 0.12em;
}

.skill-content-markdown :deep(.skill-fm-val) {
  color: #0f172a;
  word-break: break-word;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.skill-content-markdown :deep(h1),
.skill-content-markdown :deep(h2),
.skill-content-markdown :deep(h3),
.skill-content-markdown :deep(h4) {
  font-weight: 700;
  color: #0f172a;
  margin: 1.4em 0 0.6em;
  line-height: 1.3;
}

.skill-content-markdown :deep(h1) { font-size: 1.5rem; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.3em; }
.skill-content-markdown :deep(h2) { font-size: 1.25rem; border-bottom: 1px solid #f1f5f9; padding-bottom: 0.2em; }
.skill-content-markdown :deep(h3) { font-size: 1.08rem; }
.skill-content-markdown :deep(h4) { font-size: 0.98rem; }

.skill-content-markdown :deep(p) {
  margin: 0.7em 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.skill-content-markdown :deep(ul),
.skill-content-markdown :deep(ol) {
  padding-left: 1.5em;
  margin: 0.7em 0;
}

.skill-content-markdown :deep(li) {
  margin: 0.25em 0;
}

.skill-content-markdown :deep(a) {
  color: #0891b2;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.skill-content-markdown :deep(code) {
  background: #f1f5f9;
  color: #334155;
  padding: 0.12em 0.4em;
  border-radius: 0.3em;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85em;
}

.skill-content-markdown :deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
  padding: 0.9em 1.1em;
  border-radius: 0.6em;
  overflow-x: auto;
  font-size: 0.82em;
  line-height: 1.55;
  margin: 0.9em 0;
}

.skill-content-markdown :deep(pre code) {
  background: transparent;
  color: inherit;
  padding: 0;
  font-size: inherit;
  border-radius: 0;
}

.skill-content-markdown :deep(blockquote) {
  border-left: 3px solid #cbd5e1;
  background: #f8fafc;
  color: #475569;
  padding: 0.4em 1em;
  margin: 0.9em 0;
  border-radius: 0 0.4em 0.4em 0;
}

.skill-content-markdown :deep(.table-wrapper) {
  overflow-x: auto;
  margin: 0.9em 0;
}

.skill-content-markdown :deep(.markdown-table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.85em;
}

.skill-content-markdown :deep(.markdown-table th),
.skill-content-markdown :deep(.markdown-table td) {
  border: 1px solid #e2e8f0;
  padding: 0.5em 0.75em;
  text-align: left;
}

.skill-content-markdown :deep(.markdown-table th) {
  background: #f1f5f9;
  font-weight: 600;
  color: #0f172a;
}

.skill-content-markdown :deep(hr) {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 1.4em 0;
}

.skill-content-markdown :deep(img) {
  max-width: 100%;
  border-radius: 0.4em;
}

.skill-row:hover {
  background: rgba(241, 245, 249, 0.7);
}

@media (max-width: 768px) {
  .skill-manager-overlay {
    padding: 0;
  }

  .skill-manager-panel {
    width: 100%;
    height: 100%;
    border-radius: 0;
  }

  .skill-manager-body {
    grid-template-columns: 200px 1fr;
  }
}

@media (max-width: 1024px) {
  .admin-topbar-inner {
    padding: 0 0.75rem;
  }

  .admin-topbar-right span {
    display: none;
  }
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
}
</style>
