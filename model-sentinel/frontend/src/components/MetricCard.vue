<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  label: string
  value: string
  hint: string
  icon: Component
  tone?: 'neutral' | 'good' | 'warning' | 'danger'
}>()
</script>

<template>
  <article class="metric-card reveal-card" :class="`metric-card--${tone ?? 'neutral'}`">
    <div class="metric-card__head">
      <span>{{ label }}</span>
      <span class="metric-card__icon"><component :is="icon" :size="16" stroke-width="1.8" /></span>
    </div>
    <strong>{{ value }}</strong>
    <p>{{ hint }}</p>
  </article>
</template>

