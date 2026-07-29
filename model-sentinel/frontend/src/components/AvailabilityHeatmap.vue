<script setup lang="ts">
import { computed } from 'vue'
import type { HeatmapPoint } from '@/types'

const props = defineProps<{
  points: HeatmapPoint[]
}>()

const rows = computed(() => {
  const grouped = new Map<string, HeatmapPoint[]>()
  props.points.forEach((point) => {
    if (!grouped.has(point.date)) grouped.set(point.date, [])
    grouped.get(point.date)?.push(point)
  })
  return Array.from(grouped.entries()).map(([date, points]) => ({
    date,
    label: points[0]?.date_label ?? date,
    points,
  }))
})

function level(point: HeatmapPoint) {
  if (!point.calls || point.uptime_pct == null) return 'empty'
  if (point.uptime_pct >= 99) return 'excellent'
  if (point.uptime_pct >= 95) return 'good'
  if (point.uptime_pct >= 80) return 'warning'
  return 'bad'
}

function description(point: HeatmapPoint) {
  if (!point.calls) return `${point.date} ${point.hour}:00：暂无样本`
  const latency = point.p95_latency_ms
    ? `，P95 ${(point.p95_latency_ms / 1000).toFixed(1)} 秒`
    : ''
  return `${point.date} ${point.hour}:00：${point.calls} 次调用，可用率 ${point.uptime_pct}%${latency}`
}
</script>

<template>
  <div class="heatmap-wrap">
    <div class="heatmap-hours" aria-hidden="true">
      <span></span>
      <span v-for="hour in 24" :key="hour">{{ (hour - 1) % 4 === 0 ? `${hour - 1}` : '' }}</span>
    </div>
    <div class="heatmap-grid">
      <template v-for="row in rows" :key="row.date">
        <span class="heatmap-date">{{ row.label }}</span>
        <span
          v-for="point in row.points"
          :key="`${point.date}-${point.hour}`"
          class="heatmap-cell"
          :class="`heatmap-cell--${level(point)}`"
          :title="description(point)"
          :aria-label="description(point)"
        ></span>
      </template>
    </div>
    <div class="heatmap-legend">
      <span>低</span>
      <i class="heatmap-cell--bad"></i>
      <i class="heatmap-cell--warning"></i>
      <i class="heatmap-cell--good"></i>
      <i class="heatmap-cell--excellent"></i>
      <span>高可用</span>
      <em>灰色为暂无样本</em>
    </div>
  </div>
</template>

