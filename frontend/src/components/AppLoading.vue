<template>
  <div class="loading-overlay">
    <div class="loading-content">
      <el-icon class="loading-icon" size="32">
        <Loading />
      </el-icon>
      <p class="loading-text">{{ $t('common.loading') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
</script>

<style scoped>
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.loading-content {
  background-color: white;
  border-radius: 0.5rem;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
}

.loading-icon {
  color: #2563eb;
  animation: spin 1s linear infinite;
}

.loading-text {
  color: #374151;
  font-size: 0.875rem;
  font-weight: 500;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>