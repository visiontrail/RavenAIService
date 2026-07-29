<script setup lang="ts">
import type { LiveLevel } from '@/types'

defineProps<{
  level: LiveLevel
  label: string
}>()
</script>

<template>
  <span class="status-pill" :class="`status-pill--${level}`">
    <i class="status-pill__dot"></i>
    {{ label }}
  </span>
</template>

