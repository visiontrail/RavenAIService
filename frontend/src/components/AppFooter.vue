<template>
  <footer class="app-footer mt-8 border-t border-gray-200 bg-white text-gray-600">
    <div class="container mx-auto px-4 py-6 sm:py-7">
      <div class="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div class="space-y-1">
          <p class="text-sm font-semibold tracking-wide text-gray-900">Raven 智能测试平台</p>
          <p class="text-xs text-gray-500">高效的日志分析与设备协同能力</p>
        </div>

        <nav class="footer-nav flex flex-wrap items-center gap-2 sm:gap-3" aria-label="页脚导航">
          <router-link to="/" class="footer-link">日志列表</router-link>
          <router-link to="/devices" class="footer-link">设备列表</router-link>
          <router-link to="/raven-manager" class="footer-link">重构包列表</router-link>
          <router-link to="/admin" class="footer-link footer-link-admin">后台管理</router-link>
        </nav>
      </div>

      <div class="mt-5 border-t border-gray-200 pt-4 text-xs text-gray-500">
        <p>© {{ currentYear }} RavenAIService. All rights reserved.</p>
      </div>
    </div>
  </footer>
</template>

<script setup lang="ts">
const currentYear = new Date().getFullYear()
</script>

<style scoped>
.footer-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 2.1rem;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  color: #4b5563;
  text-decoration: none;
  font-size: 0.8rem;
  transition: background-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
}

.footer-link:hover {
  background: #f3f4f6;
  color: #111827;
  transform: translateY(-1px);
}

.footer-link-admin {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.footer-link-admin:hover {
  background: #dbeafe;
  color: #1e40af;
}

@media (max-width: 640px) {
  .footer-nav {
    width: 100%;
  }

  .footer-link {
    flex: 1 1 calc(50% - 0.5rem);
  }
}
</style>
