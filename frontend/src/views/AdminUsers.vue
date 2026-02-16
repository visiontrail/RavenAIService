<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { adminApi, adminToken } from '@/api/admin'
import { useAppStore } from '@/stores/app'
import type { UserProfile } from '@/types'

const appStore = useAppStore()
const route = useRoute()
const router = useRouter()

const navItems = [
  {
    key: 'prompts',
    label: 'Prompt 配置',
    path: '/admin/prompts',
    description: '编辑 prompts_config.yaml 并刷新缓存',
  },
  {
    key: 'users',
    label: '用户管理',
    path: '/admin/users',
    description: '管理对话用户、重置密码',
  },
]

const isAuthenticated = ref(false)
const isLoggingIn = ref(false)
const loadingUsers = ref(false)
const creatingUser = ref(false)
const users = ref<UserProfile[]>([])

const authForm = reactive({
  username: '',
  password: '',
})

const newUserForm = reactive({
  username: '',
  display_name: '',
  email: '',
  password: '',
})

const activeNavKey = computed(() => {
  if (route.path.startsWith('/admin/users')) return 'users'
  if (route.path.startsWith('/admin')) return 'prompts'
  return ''
})

const formatTimestamp = (value?: string | null) => {
  if (!value) return '--'
  try {
    return new Date(value).toLocaleString('zh-CN', {
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return value
  }
}

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
  if (item.path && route.path !== item.path) {
    router.push(item.path)
  }
}

const fetchUsers = async () => {
  if (!isAuthenticated.value) return
  loadingUsers.value = true
  try {
    const resp = await adminApi.listUsers()
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '无法获取用户列表')
    }
    users.value = resp.data
  } catch (err: any) {
    appStore.showNotification({
      title: '加载失败',
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    loadingUsers.value = false
  }
}

const handleLogin = async () => {
  if (!authForm.username || !authForm.password) {
    appStore.showNotification({
      title: '请输入用户名和密码',
      type: 'warning',
    })
    return
  }
  isLoggingIn.value = true
  try {
    const resp = await adminApi.login(authForm.username.trim(), authForm.password)
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '登录失败')
    }
    persistToken(resp.data.token)
    isAuthenticated.value = true
    appStore.showNotification({
      title: '登录成功',
      message: `欢迎，${resp.data.username}`,
      type: 'success',
    })
    await fetchUsers()
  } catch (err: any) {
    appStore.showNotification({
      title: '登录失败',
      message: parseErrorMessage(err),
      type: 'error',
    })
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
    users.value = []
    appStore.showNotification({
      title: '已退出登录',
      type: 'info',
    })
  }
}

const handleCreateUser = async () => {
  if (!newUserForm.username || !newUserForm.password) {
    appStore.showNotification({
      title: '请输入用户名和密码',
      type: 'warning',
    })
    return
  }
  creatingUser.value = true
  try {
    const resp = await adminApi.createUser({
      username: newUserForm.username.trim(),
      password: newUserForm.password,
      display_name: newUserForm.display_name || undefined,
      email: newUserForm.email || undefined,
    })
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '创建失败')
    }
    appStore.showNotification({
      title: '创建成功',
      message: `已创建用户 ${resp.data.username}`,
      type: 'success',
    })
    newUserForm.username = ''
    newUserForm.password = ''
    newUserForm.display_name = ''
    newUserForm.email = ''
    await fetchUsers()
  } catch (err: any) {
    appStore.showNotification({
      title: '创建失败',
      message: parseErrorMessage(err),
      type: 'error',
    })
  } finally {
    creatingUser.value = false
  }
}

const toggleActive = async (user: UserProfile) => {
  const nextStatus = !user.is_active
  try {
    const resp = await adminApi.updateUser(user.id, { is_active: nextStatus })
    if (!resp?.success || !resp.data) {
      throw new Error(resp?.message || '更新失败')
    }
    users.value = users.value.map((u) => (u.id === user.id ? resp.data as UserProfile : u))
    appStore.showNotification({
      title: nextStatus ? '已启用' : '已禁用',
      message: resp.data.username,
      type: 'success',
    })
  } catch (err: any) {
    appStore.showNotification({
      title: '状态更新失败',
      message: parseErrorMessage(err),
      type: 'error',
    })
  }
}

const resetPassword = async (user: UserProfile) => {
  const password = window.prompt(`为用户 ${user.username} 设置新密码：`)
  if (!password) return
  try {
    const resp = await adminApi.updateUser(user.id, { password })
    if (!resp?.success) {
      throw new Error(resp?.message || '重置失败')
    }
    appStore.showNotification({
      title: '密码已重置',
      message: user.username,
      type: 'success',
    })
  } catch (err: any) {
    appStore.showNotification({
      title: '重置失败',
      message: parseErrorMessage(err),
      type: 'error',
    })
  }
}

const bootstrap = async () => {
  const token = adminToken.get()
  if (!token) return
  try {
    const resp = await adminApi.me()
    if (resp?.success) {
      isAuthenticated.value = true
      await fetchUsers()
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
  <div class="space-y-6 admin-users-page">
    <section
      class="rounded-2xl bg-gradient-to-r from-slate-900 via-slate-800 to-cyan-800 text-white shadow-xl"
    >
      <div class="p-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div class="space-y-2">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-300">Raven Admin</p>
          <h1 class="text-2xl font-semibold">用户管理</h1>
        </div>
        <div class="flex items-center gap-3">
          <span
            class="px-3 py-1 text-xs font-semibold rounded-full inline-flex items-center gap-2 ring-1"
            :class="isAuthenticated ? 'bg-emerald-100 text-emerald-900 ring-emerald-200' : 'bg-slate-600/70 text-slate-100 ring-1 ring-white/10'"
          >
            <span class="h-2 w-2 rounded-full bg-current/60"></span>
            {{ isAuthenticated ? '已登录' : '未登录' }}
          </span>
        </div>
      </div>
      <div
        v-if="isAuthenticated"
        class="px-6 pb-6 grid gap-3 md:grid-cols-3 text-sm text-slate-200"
      >
        <div class="flex items-center gap-2">
          <span class="text-slate-400">用户总数</span>
          <span class="font-semibold">{{ users.length }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-slate-400">状态</span>
          <span>用户数据仅对管理员可见</span>
        </div>
      </div>
    </section>

    <section v-if="!isAuthenticated" class="max-w-3xl mx-auto">
      <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-lg font-semibold text-slate-900">登录后台</h2>
            <p class="text-sm text-slate-500">请输入管理员凭证继续</p>
          </div>
          <span class="text-xs text-slate-500">内部安全访问</span>
        </div>
        <div class="grid gap-4 md:grid-cols-2">
          <div class="space-y-4">
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
            <div class="login-actions flex items-center gap-3">
              <button
                class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-50"
                :disabled="isLoggingIn"
                @click="handleLogin"
              >
                {{ isLoggingIn ? '登录中…' : '登录' }}
              </button>
              <p class="text-xs text-slate-500">
                凭证在 admin_auth.yaml 配置，建议登录后立即更改
              </p>
            </div>
          </div>
          <div class="bg-slate-50 rounded-lg p-4 space-y-3 text-sm text-slate-700">
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full bg-emerald-400"></span>
              <span>仅限内部管理访问，凭证按需分发</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full bg-cyan-400"></span>
              <span>登录后可管理用户与对话数据</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full bg-amber-400"></span>
              <span>会话基于 Bearer Token，关闭标签后自动清除</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-else class="admin-layout grid gap-6 grid-cols-1 lg:grid-cols-[240px,1fr] items-start">
      <aside class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4 space-y-4">
        <div>
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">管理导航</p>
          <h2 class="text-lg font-semibold text-slate-900">后台</h2>
        </div>
        <nav class="space-y-2">
          <button
            v-for="item in navItems"
            :key="item.key"
            class="w-full text-left px-3 py-2 rounded-lg border transition"
            :class="
              activeNavKey === item.key
                ? 'border-cyan-200 bg-cyan-50 text-cyan-800 shadow-[0_6px_30px_-16px_rgba(14,165,233,0.5)]'
                : 'border-slate-200 hover:bg-slate-50 text-slate-700'
            "
            @click="handleNavClick(item)"
          >
            <div class="flex items-center justify-between">
              <span class="text-sm font-semibold">{{ item.label }}</span>
              <span
                v-if="activeNavKey === item.key"
                class="text-[11px] font-medium text-cyan-700"
              >
                当前
              </span>
            </div>
            <p v-if="item.description" class="text-xs text-slate-500 mt-1">
              {{ item.description }}
            </p>
          </button>
        </nav>
        <div class="pt-3 border-t border-slate-100">
          <div class="flex items-center justify-between">
            <span class="text-xs text-slate-500">已登录</span>
            <button class="text-xs text-slate-600 hover:text-slate-900" @click="handleLogout">
              退出
            </button>
          </div>
        </div>
      </aside>

      <div class="space-y-6">
        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4">
          <div class="flex items-center justify-between mb-3">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">创建新用户</h2>
              <p class="text-sm text-slate-500">用于同步和管理聊天会话</p>
            </div>
          </div>
          <div class="grid md:grid-cols-2 gap-4">
            <label class="text-sm text-slate-700">
              用户名
              <input
                v-model="newUserForm.username"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="username"
              />
            </label>
            <label class="text-sm text-slate-700">
              展示名
              <input
                v-model="newUserForm.display_name"
                type="text"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="可选"
              />
            </label>
            <label class="text-sm text-slate-700">
              邮箱
              <input
                v-model="newUserForm.email"
                type="email"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="email@example.com"
              />
            </label>
            <label class="text-sm text-slate-700">
              初始密码
              <input
                v-model="newUserForm.password"
                type="password"
                class="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-cyan-500 focus:ring-2 focus:ring-cyan-100 outline-none"
                placeholder="至少 6 位"
              />
            </label>
          </div>
          <div class="user-create-actions mt-3 flex items-center justify-end gap-2">
            <button
              class="px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 hover:bg-slate-50"
              @click="fetchUsers"
              :disabled="loadingUsers"
            >
              刷新列表
            </button>
            <button
              class="px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-semibold hover:bg-cyan-700 transition disabled:opacity-60"
              :disabled="creatingUser"
              @click="handleCreateUser"
            >
              {{ creatingUser ? '创建中…' : '创建用户' }}
            </button>
          </div>
        </div>

        <div class="bg-white rounded-2xl shadow-sm border border-slate-200 p-4">
          <div class="user-list-header flex items-center justify-between mb-4">
            <div>
              <h2 class="text-lg font-semibold text-slate-900">用户列表</h2>
              <p class="text-sm text-slate-500">启用/禁用用户，或重置密码</p>
            </div>
            <button
              class="text-sm text-slate-600 hover:text-slate-900"
              @click="fetchUsers"
              :disabled="loadingUsers"
            >
              {{ loadingUsers ? '同步中…' : '刷新' }}
            </button>
          </div>

          <div v-if="loadingUsers" class="text-sm text-slate-500">正在加载用户...</div>
          <div v-else-if="!users.length" class="text-sm text-slate-500">暂无用户</div>
          <div v-else class="users-table-wrapper overflow-x-auto touch-scroll">
            <table class="min-w-full text-left text-sm text-slate-700 users-table">
              <thead>
                <tr class="border-b border-slate-200">
                  <th class="py-2 pr-4 font-semibold">用户名</th>
                  <th class="py-2 pr-4 font-semibold">展示名</th>
                  <th class="py-2 pr-4 font-semibold">邮箱</th>
                  <th class="py-2 pr-4 font-semibold">状态</th>
                  <th class="py-2 pr-4 font-semibold">最近登录</th>
                  <th class="py-2 pr-4 font-semibold">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="user in users" :key="user.id" class="border-b border-slate-100">
                  <td class="py-2 pr-4 font-medium text-slate-900">{{ user.username }}</td>
                  <td class="py-2 pr-4">{{ user.display_name || '-' }}</td>
                  <td class="py-2 pr-4">{{ user.email || '-' }}</td>
                  <td class="py-2 pr-4">
                    <span
                      class="px-2 py-1 rounded-full text-xs font-semibold"
                      :class="user.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                    >
                      {{ user.is_active ? '启用' : '禁用' }}
                    </span>
                  </td>
                  <td class="py-2 pr-4 text-slate-500">{{ formatTimestamp(user.last_login_at) }}</td>
                  <td class="py-2 pr-4 space-x-2">
                    <button
                      class="text-xs px-3 py-1 rounded-lg border border-slate-200 hover:bg-slate-50"
                      @click="toggleActive(user)"
                    >
                      {{ user.is_active ? '禁用' : '启用' }}
                    </button>
                    <button
                      class="text-xs px-3 py-1 rounded-lg border border-amber-200 text-amber-700 hover:bg-amber-50"
                      @click="resetPassword(user)"
                    >
                      重置密码
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
@media (max-width: 768px) {
  .admin-layout {
    gap: 1rem;
  }

  .login-actions {
    flex-direction: column;
    align-items: flex-start;
  }

  .user-create-actions {
    justify-content: stretch;
    flex-direction: column;
  }

  .user-create-actions button {
    width: 100%;
  }

  .user-list-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }

  .users-table {
    min-width: 720px;
  }
}
</style>
