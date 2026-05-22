<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Menu, PanelLeftClose } from 'lucide-vue-next'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import { adminNavItems, resolveAdminNavKey } from '@/utils/adminNav'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = adminNavItems

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)

const authForm = reactive({ username: '', password: '' })

const navVisible = computed(() => appStore.adminSidebarVisible)
const activeNavKey = computed(() => resolveAdminNavKey(route.path))

const parseErrorMessage = (err: any) => {
  if (err?.response?.data?.detail) return err.response.data.detail
  if (err?.response?.data?.message) return err.response.data.message
  if (err?.message) return err.message
  return '操作失败'
}

const persistToken = (token: string) => {
  adminToken.set(token)
}

const clearAuth = () => {
  adminToken.clear()
  isAuthenticated.value = false
  authForm.password = ''
}

const handleNavClick = (item: (typeof navItems)[number]) => {
  if (item.path && route.path !== item.path) router.push(item.path)
}

const toggleNavVisibility = () => {
  appStore.toggleAdminSidebar()
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

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
    } else {
      clearAuth()
    }
  } catch {
    clearAuth()
  }
}

onMounted(() => {
  bootstrap()
})
</script>

<template>
  <div class="admin-console admin-users-page">
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
            <PanelLeftClose v-if="navVisible" :size="18" />
            <Menu v-else :size="18" />
          </button>
          <div>
            <h1 class="admin-title">后台管理</h1>
            <p class="admin-subtitle">模型设置</p>
          </div>
        </div>
        <div class="admin-topbar-right">
          <span class="px-3 py-1 text-xs font-semibold rounded-full bg-slate-700 text-slate-100">
            {{ isAuthenticated ? '运行期配置' : '未登录' }}
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
      aria-label="关闭侧边栏"
    ></button>

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
          </div>
          <form class="space-y-4 max-w-md" @submit.prevent="handleLogin">
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
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">Anthropic 模型配置</h2>
              <p class="text-sm text-slate-500">
                DeviceAgent 与 LogAnalysisAgent 统一通过 Claude Agent SDK 调用 Anthropic 兼容端点。
                所有模型相关参数仅由环境变量 / <code>app/config.py</code> 控制，运行期不可覆盖。
              </p>
            </div>
          </div>

          <div class="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">
            <div class="text-sm font-semibold text-slate-800 mb-2">必需环境变量</div>
            <ul class="space-y-1 text-sm text-slate-700">
              <li><code>ANTHROPIC_PROVIDER</code> — Provider 选择（如 <code>anthropic</code> / <code>deepseek</code>），DeviceAgent 需要支持 MCP 工具的 provider</li>
              <li><code>ANTHROPIC_API_KEY</code> — Anthropic 兼容端点的 API Key</li>
            </ul>
          </div>

          <div class="bg-slate-50 border border-slate-200 rounded-lg px-4 py-3 mt-3">
            <div class="text-sm font-semibold text-slate-800 mb-2">可选环境变量</div>
            <ul class="space-y-1 text-sm text-slate-700">
              <li><code>ANTHROPIC_BASE_URL</code> — 自定义端点，未设置时走 provider profile 默认值</li>
              <li><code>ANTHROPIC_MODEL</code> — 主力模型 id；未设置时使用 provider profile 默认值</li>
              <li><code>ANTHROPIC_SMALL_FAST_MODEL</code> — 标题生成等轻量任务用的小/快模型；未设置时使用 provider profile 默认值</li>
              <li><code>ANTHROPIC_MAX_HISTORY_TURNS</code> — 对话历史最大保留轮数，默认 <code>10</code></li>
              <li><code>ANTHROPIC_SMALL_FAST_MAX_TOKENS</code> — 轻量任务最大输出 tokens，默认 <code>1024</code></li>
              <li><code>ANTHROPIC_SMALL_FAST_REQUEST_TIMEOUT_SECONDS</code> — 轻量任务请求超时（秒），默认 <code>30</code></li>
              <li><code>DEVICE_AGENT_PERMISSION_TIMEOUT_SECONDS</code> — HITL 用户确认超时（秒），默认 <code>120</code></li>
              <li><code>DEVICE_AGENT_RESULT_EXCERPT_BYTES</code> — 单条 evidence 截断阈值，默认 <code>16384</code></li>
              <li><code>DEVICE_AGENT_RESULT_MAX_BYTES</code> — 工具回包整体上限，超过替换为 <code>result_too_large</code>，默认 <code>262144</code></li>
              <li><code>DEVICE_AGENT_MAX_REMOTE_TOOLS</code> — 单会话最多映射的设备 MCP 工具数，默认 <code>64</code></li>
            </ul>
          </div>

          <div class="text-sm text-slate-500 mt-3 space-y-1">
            <p>· 修改环境变量后需要重启服务才能生效。</p>
            <p>· DeepSeek profile 暂不支持 MCP server 工具，DeviceAgent 在该 provider 下会直接返回 <code>provider_no_mcp_support</code> 错误。</p>
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
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
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
  max-width: 720px;
  margin: 1.25rem auto 0;
}

.admin-sidebar-backdrop {
  display: none;
}

@media (max-width: 768px) {
  .admin-console {
    --admin-sidebar-width: min(84vw, 320px);
  }
  .admin-main.is-sidebar-hidden {
    padding-left: 1rem;
  }
  .admin-sidebar-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 55;
    background: rgba(15, 23, 42, 0.45);
    border: 0;
  }
}
</style>
