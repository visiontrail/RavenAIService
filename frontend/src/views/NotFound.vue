<template>
  <div class="not-found-page">
    <el-result
      icon="error"
      title="404"
      sub-title="抱歉，您访问的页面不存在"
    >
      <template #extra>
        <div class="flex flex-col sm:flex-row gap-3 sm:gap-4 justify-center">
          <el-button @click="$router.back()">
            返回上页
          </el-button>
          <el-button type="primary" @click="goHome">
            回到首页
          </el-button>
        </div>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
const goHome = () => {
  window.location.href = '/'
}
</script>

<style scoped>
@reference "tailwindcss";

.not-found-page {
  @apply flex items-center justify-center min-h-96;
}
</style>
