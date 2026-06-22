<template>
  <div class="notifications-container">
    <transition-group name="notification" tag="div">
      <div
        v-for="notification in appStore.notifications"
        :key="notification.id"
        :class="getNotificationClass(notification.type)"
        class="notification"
      >
        <div class="notification-content">
          <el-icon class="notification-icon" size="20">
            <component :is="getNotificationIcon(notification.type)" />
          </el-icon>
          <div class="notification-text">
            <h4 class="notification-title">{{ notification.title }}</h4>
            <p v-if="notification.message" class="notification-message">
              {{ notification.message }}
            </p>
          </div>
        </div>
        <el-button
          type="text"
          size="small"
          class="notification-close"
          @click="appStore.removeNotification(notification.id)"
        >
          <el-icon size="16">
            <Close />
          </el-icon>
        </el-button>
      </div>
    </transition-group>
  </div>
</template>

<script setup lang="ts">
import { useAppStore } from '../stores/app'
import { 
  SuccessFilled, 
  WarningFilled, 
  InfoFilled, 
  CircleCloseFilled,
  Close 
} from '@element-plus/icons-vue'

const appStore = useAppStore()

const getNotificationIcon = (type: string) => {
  const icons: Record<string, any> = {
    success: SuccessFilled,
    warning: WarningFilled,
    info: InfoFilled,
    error: CircleCloseFilled,
  }
  return icons[type] || InfoFilled
}

const getNotificationClass = (type: string) => {
  const classes: Record<string, string> = {
    success: 'notification-success',
    warning: 'notification-warning',
    info: 'notification-info',
    error: 'notification-error',
  }
  return classes[type] || 'notification-info'
}
</script>

<style scoped>
.notifications-container {
  position: fixed;
  top: 1rem;
  right: 1rem;
  /* Above modal backdrops (z-index: 100, which apply backdrop-filter: blur)
     so toasts stay sharp and on top while a dialog is open. */
  z-index: 2000;
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.notifications-container--admin {
  top: calc(72px + 1rem);
}

.notification {
  background-color: white;
  border-radius: 0.5rem;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
  border: 1px solid #e5e7eb;
  padding: 1rem;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  animation: slideIn 0.3s ease-out;
}

.notification-success {
  border-color: #bbf7d0;
  background-color: #f0fdf4;
}

.notification-warning {
  border-color: #fde68a;
  background-color: #fffbeb;
}

.notification-info {
  border-color: #bfdbfe;
  background-color: #eff6ff;
}

.notification-error {
  border-color: #fecaca;
  background-color: #fef2f2;
}

.notification-content {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  flex: 1;
}

.notification-icon {
  flex-shrink: 0;
  margin-top: 0.125rem;
}

.notification-success .notification-icon {
  color: #059669;
}

.notification-warning .notification-icon {
  color: #d97706;
}

.notification-info .notification-icon {
  color: #2563eb;
}

.notification-error .notification-icon {
  color: #dc2626;
}

.notification-text {
  flex: 1;
}

.notification-title {
  font-size: 0.875rem;
  font-weight: 500;
  color: #111827;
  margin-bottom: 0.25rem;
}

.notification-message {
  font-size: 0.875rem;
  color: #6b7280;
}

.notification-close {
  flex-shrink: 0;
  color: #9ca3af;
}

.notification-close:hover {
  color: #6b7280;
}

/* 动画效果 */
.notification-enter-active,
.notification-leave-active {
  transition: all 0.3s ease;
}

.notification-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.notification-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateX(100%);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@media (max-width: 768px) {
  .notifications-container {
    top: 0.75rem;
    right: 0.5rem;
    left: 0.5rem;
    width: auto;
    z-index: 2000;
  }

  .notifications-container--admin {
    top: calc(72px + 0.75rem);
  }
}
</style>
