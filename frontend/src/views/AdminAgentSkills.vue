<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Cpu,
  FileArchive,
  Power,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'
import type { AgentSkill, AgentSkillAgentInfo } from '@/types'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = adminNavItems

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingAgents = ref(false)
const loadingSkills = ref(false)
const uploading = ref(false)
const uploadPercent = ref(0)
const togglingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)

const agents = ref<AgentSkillAgentInfo[]>([])
const selectedAgentKey = ref<string>('')
const skills = ref<AgentSkill[]>([])

const overwrite = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const dragOver = ref(false)

const authForm = reactive({
  username: '',
  password: '',
})

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const selectedAgent = computed<AgentSkillAgentInfo | undefined>(() =>
  agents.value.find((a) => a.key === selectedAgentKey.value)
)
const enabledCount = computed(() => skills.value.filter((s) => s.enabled).length)
const disabledCount = computed(() => skills.value.length - enabledCount.value)

const parseErrorMessage = (err: any): string => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
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
  agents.value = []
  skills.value = []
  authForm.password = ''
}

const handleLogin = async () => {
  if (!authForm.username.trim() || !authForm.password) {
    appStore.showNotification({ title: '请输入用户名和密码', type: 'warning' })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data?.token) throw new Error(resp?.message || '登录失败')
    adminToken.set(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({
      title: '登录成功',
      message: `欢迎，${resp.data.username}`,
      type: 'success',
    })
    await fetchAgents()
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
    appStore.showNotification({ title: '已退出登录', type: 'info' })
  }
}

const fetchAgents = async () => {
  if (!isAuthenticated.value) return
  loadingAgents.value = true
  try {
    const resp = await adminApi.listSkillAgents()
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '获取 Agent 列表失败')
    agents.value = resp.data
    if (!selectedAgentKey.value && agents.value.length) {
      selectedAgentKey.value = agents.value[0].key
    }
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingAgents.value = false
  }
}

const fetchSkills = async () => {
  if (!isAuthenticated.value || !selectedAgentKey.value) return
  loadingSkills.value = true
  try {
    const resp = await adminApi.listAgentSkills(selectedAgentKey.value)
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '获取 Skill 列表失败')
    skills.value = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: '加载失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    loadingSkills.value = false
  }
}

watch(selectedAgentKey, () => {
  skills.value = []
  if (selectedAgentKey.value) fetchSkills()
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
  if (!selectedAgentKey.value) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    appStore.showNotification({
      title: '格式不支持',
      message: '请选择 .zip 格式的 Skill 包',
      type: 'warning',
    })
    return
  }
  uploading.value = true
  uploadPercent.value = 0
  try {
    const resp = await adminApi.uploadAgentSkill(
      selectedAgentKey.value,
      file,
      overwrite.value,
      (p) => (uploadPercent.value = p)
    )
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '上传失败')
    appStore.showNotification({
      title: '上传成功',
      message: `已安装 Skill: ${resp.data.name}`,
      type: 'success',
    })
    await fetchSkills()
  } catch (err: any) {
    appStore.showNotification({ title: '上传失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    uploading.value = false
    uploadPercent.value = 0
  }
}

const toggleSkill = async (skill: AgentSkill) => {
  togglingId.value = skill.id
  try {
    const resp = await adminApi.updateAgentSkill(selectedAgentKey.value, skill.id, {
      enabled: !skill.enabled,
    })
    if (!resp?.success || !resp.data) throw new Error(resp?.message || '更新失败')
    const idx = skills.value.findIndex((s) => s.id === skill.id)
    if (idx >= 0) skills.value[idx] = resp.data
  } catch (err: any) {
    appStore.showNotification({ title: '更新失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    togglingId.value = null
  }
}

const deleteSkill = async (skill: AgentSkill) => {
  if (!window.confirm(`确认删除 Skill「${skill.name}」？`)) return
  deletingId.value = skill.id
  try {
    await adminApi.deleteAgentSkill(selectedAgentKey.value, skill.id)
    skills.value = skills.value.filter((s) => s.id !== skill.id)
    appStore.showNotification({ title: '已删除', message: skill.name, type: 'success' })
  } catch (err: any) {
    appStore.showNotification({ title: '删除失败', message: parseErrorMessage(err), type: 'error' })
  } finally {
    deletingId.value = null
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await fetchAgents()
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
  <div class="admin-console admin-agent-skills-page">
    <header class="admin-topbar">
      <div class="admin-topbar-inner">
        <div class="admin-topbar-left">
          <button
            class="admin-icon-btn"
            :disabled="!isAuthenticated"
            @click="toggleNavVisibility"
            :title="navVisible ? '隐藏侧边栏' : '显示侧边栏'"
            aria-label="切换侧边栏"
          >
            {{ navVisible ? '☰' : '▤' }}
          </button>
          <div>
            <h1 class="admin-title">后台管理</h1>
            <p class="admin-subtitle">Agent Skill 管理</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated
              ? `${enabledCount} 启用 / ${disabledCount} 停用`
              : '未登录' }}
          </span>
          <button v-if="isAuthenticated" class="admin-logout-btn" @click="handleLogout">退出</button>
        </div>
      </div>
    </header>

    <button
      v-if="isAuthenticated && navVisible"
      class="admin-sidebar-backdrop"
      @click="toggleNavVisibility"
      aria-label="关闭侧边栏"
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

      <section v-else class="space-y-4">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5">
          <div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">Agent Skill 加载</h2>
              <p class="text-sm text-slate-500 mt-0.5">
                上传 Claude 应用程序兼容的 Skill 包 (.zip)，并按 Agent 启用，使其在运行时具备调用自定义 Skill 的能力。
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <label class="inline-flex items-center gap-2">
                <span class="text-xs font-semibold uppercase tracking-wide text-slate-400">Agent</span>
                <select
                  v-model="selectedAgentKey"
                  class="rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                  :disabled="loadingAgents || !agents.length"
                >
                  <option v-for="a in agents" :key="a.key" :value="a.key">
                    {{ a.name }} · {{ a.framework }}
                  </option>
                </select>
              </label>
              <button
                class="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                :disabled="loadingSkills || !selectedAgentKey"
                @click="fetchSkills"
              >
                <RefreshCw :size="15" />
                {{ loadingSkills ? '刷新中' : '刷新' }}
              </button>
            </div>
          </div>
          <div v-if="selectedAgent" class="mt-4 rounded-xl border border-slate-100 bg-slate-50 px-4 py-3 text-sm text-slate-600 flex items-start gap-3">
            <Cpu :size="18" class="mt-0.5 text-slate-400" />
            <div>
              <p class="text-slate-700 font-medium">{{ selectedAgent.name }}</p>
              <p class="text-xs text-slate-500 mt-0.5">
                框架：<code class="rounded bg-white px-1.5 py-0.5 text-xs text-slate-600 border border-slate-200">{{ selectedAgent.framework }}</code>
                <span v-if="selectedAgent.description"> · {{ selectedAgent.description }}</span>
              </p>
            </div>
          </div>
        </div>

        <div
          class="bg-white rounded-2xl shadow-sm border border-slate-200 p-5"
        >
          <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">上传 Skill 包</h3>
              <p class="mt-1 text-xs text-slate-500">
                zip 内应包含 <code class="rounded bg-slate-100 px-1 text-[11px] text-slate-600">SKILL.md</code>（或唯一顶层目录 <code class="rounded bg-slate-100 px-1 text-[11px] text-slate-600">&lt;name&gt;/SKILL.md</code>）。frontmatter 中的 <code class="rounded bg-slate-100 px-1 text-[11px] text-slate-600">name</code> 必须存在且仅含字母/数字/下划线/连字符。
              </p>
            </div>
            <label class="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600">
              <input v-model="overwrite" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-cyan-600 focus:ring-cyan-500" />
              覆盖同名 Skill
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
              将 <span class="font-mono font-semibold">.zip</span> 文件拖到此处，或
              <button class="ml-1 text-cyan-600 underline-offset-2 hover:underline" @click="triggerFilePicker">点击选择文件</button>
            </p>
            <p class="mt-1 text-xs text-slate-400">单个文件 ≤ 50 MiB · 解压总量 ≤ 200 MiB</p>
            <div v-if="uploading" class="mt-3 w-full max-w-sm">
              <div class="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden">
                <div class="h-full bg-cyan-500 transition-all" :style="{ width: `${uploadPercent}%` }"></div>
              </div>
              <p class="mt-1 text-xs text-slate-500">上传中… {{ uploadPercent }}%</p>
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
            <p class="text-sm font-semibold text-slate-900">已安装 Skill</p>
            <p class="text-xs text-slate-400">共 {{ skills.length }} 项</p>
          </div>

          <div v-if="loadingSkills" class="px-5 py-12 text-center text-sm text-slate-400">
            正在加载…
          </div>

          <div v-else-if="!skills.length" class="px-5 py-12 text-center">
            <p class="text-sm font-medium text-slate-700">尚未上传 Skill</p>
            <p class="mt-1 text-xs text-slate-400">通过上方拖拽或选择文件，安装第一个 Skill 包。</p>
          </div>

          <div v-else class="overflow-x-auto">
            <table class="min-w-full text-sm text-slate-700">
              <thead>
                <tr class="border-b border-slate-100 bg-slate-50">
                  <th class="py-2.5 pl-5 pr-4 text-left font-semibold text-slate-600">Skill</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">来源 zip</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">大小</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">状态</th>
                  <th class="py-2.5 pr-4 text-left font-semibold text-slate-600">更新时间</th>
                  <th class="py-2.5 pr-5 text-right font-semibold text-slate-600">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="skill in skills"
                  :key="skill.id"
                  class="border-b border-slate-50 hover:bg-slate-50/70 transition-colors"
                >
                  <td class="py-3 pl-5 pr-4">
                    <div class="flex items-center gap-2">
                      <code class="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono text-slate-700">{{ skill.name }}</code>
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
                      {{ skill.enabled ? '启用' : '停用' }}
                    </span>
                  </td>
                  <td class="py-3 pr-4 whitespace-nowrap text-xs text-slate-400">{{ formatTimestamp(skill.updated_at) }}</td>
                  <td class="py-3 pr-5">
                    <div class="flex justify-end gap-2">
                      <button
                        class="admin-action-btn"
                        :disabled="togglingId === skill.id"
                        :title="skill.enabled ? '停用' : '启用'"
                        @click="toggleSkill(skill)"
                      >
                        <Power :size="15" />
                      </button>
                      <button
                        class="admin-action-btn danger"
                        :disabled="deletingId === skill.id"
                        title="删除"
                        @click="deleteSkill(skill)"
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
