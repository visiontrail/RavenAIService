<template>
  <footer class="app-footer">
    <div class="footer-main container mx-auto px-4 py-10">
      <div class="footer-grid">
        <!-- Brand column -->
        <div class="footer-brand footer-panel">
          <div class="flex items-center gap-2.5 mb-3">
            <img
              :src="ravenLogo"
              alt="Raven Logo"
              class="footer-brand-logo"
            />
            <span class="text-sm font-bold tracking-wide text-gray-900">Raven 智能测试平台</span>
          </div>
          <p class="text-xs text-gray-500 leading-relaxed max-w-[220px]">
            高效的日志分析与设备协同能力，让测试工作更智能、更简单。
          </p>
          <div class="mt-4 flex items-center gap-1">
            <router-link to="/download" class="download-badge">
              <svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
              <span>下载客户端</span>
            </router-link>
          </div>
        </div>

        <!-- Product column -->
        <div class="footer-col footer-panel">
          <h4 class="footer-col-title">产品功能</h4>
          <nav class="space-y-2">
            <router-link to="/" class="footer-link">日志列表</router-link>
            <router-link to="/upload" class="footer-link">上传日志</router-link>
            <router-link to="/devices" class="footer-link">设备列表</router-link>
            <router-link to="/raven-manager" class="footer-link">重构包管理</router-link>
            <router-link to="/ai-chat" class="footer-link">AI 对话</router-link>
          </nav>
        </div>

        <!-- Download column -->
        <div class="footer-col footer-panel">
          <h4 class="footer-col-title">下载客户端</h4>
          <nav class="space-y-2">
            <router-link to="/download" class="footer-link footer-link-platform">
              <PlatformBrandIcon platform="linux" class="footer-platform-icon" />
              <span>Linux</span>
            </router-link>
            <router-link to="/download" class="footer-link footer-link-platform">
              <PlatformBrandIcon platform="macos" class="footer-platform-icon" />
              <span>macOS</span>
            </router-link>
            <router-link to="/download" class="footer-link footer-link-platform">
              <PlatformBrandIcon platform="windows" class="footer-platform-icon" />
              <span>Windows</span>
            </router-link>
            <router-link to="/download" class="footer-link text-blue-600 font-medium mt-1">全部版本 →</router-link>
          </nav>
        </div>

        <!-- Support column -->
        <div class="footer-col footer-panel">
          <h4 class="footer-col-title">更多</h4>
          <nav class="space-y-2">
            <router-link to="/about" class="footer-link">关于 Raven</router-link>
            <router-link to="/changelog" class="footer-link">更新日志</router-link>
            <router-link to="/privacy" class="footer-link">隐私政策</router-link>
            <router-link to="/terms" class="footer-link">服务条款</router-link>
            <router-link to="/admin" class="footer-link footer-link-admin">后台管理</router-link>
          </nav>
        </div>
      </div>
    </div>

    <!-- Bottom bar -->
    <div class="footer-bottom">
      <div class="footer-bottom-inner container mx-auto px-4 py-4 flex flex-col sm:flex-row items-center justify-between gap-3">
        <p class="footer-copyright text-xs text-gray-400">
          © {{ currentYear }} RavenAIService · GalaxySpace. All rights reserved.
        </p>
        <div class="footer-bottom-links flex items-center gap-4">
          <router-link to="/privacy" class="text-xs text-gray-400 hover:text-gray-600 transition">隐私政策</router-link>
          <router-link to="/terms" class="text-xs text-gray-400 hover:text-gray-600 transition">服务条款</router-link>
          <router-link to="/download" class="text-xs text-blue-500 hover:text-blue-600 transition font-medium">下载客户端</router-link>
        </div>
      </div>
    </div>
  </footer>
</template>

<script setup lang="ts">
import PlatformBrandIcon from '@/components/icons/PlatformBrandIcon.vue'
import ravenLogo from '@/assets/raven-logo.png'

const currentYear = new Date().getFullYear()
</script>

<style scoped>
.app-footer {
  background: #ffffff;
  border-top: 1px solid #e5e7eb;
  margin-top: 2rem;
}

.footer-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr 1fr;
  gap: 2rem;
  align-items: start;
}

.footer-panel {
  min-width: 0;
}

.footer-col {
  display: flex;
  flex-direction: column;
}

.footer-col-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #111827;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  margin-bottom: 0.85rem;
}

.footer-link {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  color: #6b7280;
  text-decoration: none;
  font-size: 0.8rem;
  transition: color 0.15s ease;
  line-height: 1.5;
}

.footer-link:hover {
  color: #111827;
}

.footer-link-platform {
  gap: 0.5rem;
}

.footer-platform-icon {
  width: 0.95rem;
  height: 0.95rem;
  flex-shrink: 0;
}

.footer-link-admin {
  color: #1d4ed8;
  font-size: 0.78rem;
}

.footer-link-admin:hover {
  color: #1e40af;
}

.footer-brand-logo {
  width: 1.75rem;
  height: 1.75rem;
  flex-shrink: 0;
  object-fit: contain;
  border-radius: 0.5rem;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
  border: 1px solid #e5e7eb;
  background: #ffffff;
}

.download-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.75rem;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  color: #2563eb;
  text-decoration: none;
  font-size: 0.75rem;
  font-weight: 600;
  transition: background-color 0.15s, border-color 0.15s;
}

.download-badge:hover {
  background: #dbeafe;
  border-color: #93c5fd;
}

.footer-bottom {
  border-top: 1px solid #f3f4f6;
  background: #fafafa;
}

.footer-bottom-links {
  flex-wrap: wrap;
  justify-content: center;
}

@media (max-width: 900px) {
  .footer-grid {
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem 2rem;
  }

  .footer-brand {
    grid-column: 1 / -1;
  }
}

@media (max-width: 540px) {
  .footer-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0.85rem;
  }

  .footer-brand {
    grid-column: 1 / -1;
  }

  .footer-main {
    padding-top: 1.25rem;
    padding-bottom: 1.25rem;
  }

  .footer-panel {
    padding: 1rem;
    border: 1px solid #eef2f7;
    border-radius: 1rem;
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
    box-shadow: 0 10px 24px -20px rgba(15, 23, 42, 0.35);
  }

  .footer-brand p {
    max-width: none;
  }

  .footer-col-title {
    margin-bottom: 0.7rem;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
  }

  .footer-link {
    min-height: 1.75rem;
    font-size: 0.78rem;
    line-height: 1.45;
  }

  .download-badge {
    min-height: 2.25rem;
  }

  .footer-bottom-inner {
    gap: 0.75rem;
    padding-top: 0.9rem;
    padding-bottom: calc(5rem + env(safe-area-inset-bottom));
  }

  .footer-copyright {
    text-align: center;
    line-height: 1.6;
  }

  .footer-bottom-links {
    width: 100%;
    gap: 0.75rem 1rem;
  }
}

@media (max-width: 380px) {
  .footer-grid {
    grid-template-columns: 1fr;
  }

  .footer-brand {
    grid-column: auto;
  }
}
</style>
