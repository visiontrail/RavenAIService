<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SeriesPoint } from '@/types'

const props = defineProps<{
  points: SeriesPoint[]
  latencyThreshold: number
}>()

const hovered = ref<number | null>(null)
const width = 820
const height = 250
const pad = { left: 44, right: 20, top: 22, bottom: 38 }
const innerWidth = width - pad.left - pad.right
const innerHeight = height - pad.top - pad.bottom
const baselineY = height - pad.bottom
// 数值标签之间需要的最小水平间距，密集区间按步长抽稀，避免糊成一片
const labelMinGap = 28

const maxLatency = computed(() => {
  const values = props.points.map((point) => point.p95_latency_ms ?? 0)
  return Math.max(props.latencyThreshold, ...values, 1000) * 1.15
})

const plotted = computed(() => {
  const denominator = Math.max(1, props.points.length - 1)
  return props.points.map((point, index) => ({
    ...point,
    x: pad.left + (index / denominator) * innerWidth,
    latencyY:
      pad.top +
      innerHeight -
      ((point.p95_latency_ms ?? 0) / maxLatency.value) * innerHeight,
    uptimeY:
      pad.top + innerHeight - ((point.uptime_pct ?? 0) / 100) * innerHeight,
  }))
})

const latencyPath = computed(() => {
  let path = ''
  let drawing = false
  plotted.value.forEach((point) => {
    if (point.p95_latency_ms == null) {
      drawing = false
      return
    }
    path += `${drawing ? ' L' : 'M'} ${point.x.toFixed(1)} ${point.latencyY.toFixed(1)}`
    drawing = true
  })
  return path
})

const thresholdY = computed(() => {
  return (
    pad.top +
    innerHeight -
    (props.latencyThreshold / maxLatency.value) * innerHeight
  )
})

const valueLabels = computed(() => {
  const points = plotted.value
  const step = points.length > 1 ? innerWidth / (points.length - 1) : innerWidth
  const stride = Math.max(1, Math.ceil(labelMinGap / Math.max(step, 1)))
  const topLimit = pad.top + 8
  const bottomLimit = baselineY - 2

  return points
    .filter((_, index) => index % stride === 0)
    .map((point) => {
      // 可用率写在柱子顶部内侧；柱子太矮时改写到柱子上方
      const uptimeY =
        point.uptime_pct == null
          ? null
          : baselineY - point.uptimeY >= 18
            ? point.uptimeY + 11
            : point.uptimeY - 5

      let latencyY: number | null = null
      if (point.p95_latency_ms != null) {
        const above = point.latencyY - 9
        const below = point.latencyY + 16
        latencyY = above < topLimit ? below : above
        if (uptimeY != null && Math.abs(latencyY - uptimeY) < 11) {
          const alt = latencyY === above ? below : above
          if (alt > topLimit && alt < bottomLimit) latencyY = alt
        }
      }

      return {
        key: point.key,
        x: point.x,
        uptimeText: point.uptime_pct == null ? null : `${point.uptime_pct}%`,
        uptimeY,
        latencyText: point.p95_latency_ms == null ? null : ms(point.p95_latency_ms),
        latencyY,
      }
    })
})

const labelIndexes = computed(() => {
  if (props.points.length <= 8) return props.points.map((_, index) => index)
  const stride = Math.ceil(props.points.length / 6)
  return props.points
    .map((_, index) => index)
    .filter((index) => index % stride === 0 || index === props.points.length - 1)
})

function ms(value: number | null) {
  if (value == null) return '暂无'
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`
}
</script>

<template>
  <div class="trend-chart">
    <div v-if="!points.length" class="chart-empty">暂无趋势数据</div>
    <svg
      v-else
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      aria-label="模型可用率与 P95 延迟趋势"
    >
      <defs>
        <linearGradient id="latencyArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--accent)" stop-opacity=".22" />
          <stop offset="100%" stop-color="var(--accent)" stop-opacity="0" />
        </linearGradient>
      </defs>

      <g class="chart-grid">
        <line v-for="step in 5" :key="step" :x1="pad.left" :x2="width - pad.right"
          :y1="pad.top + ((step - 1) / 4) * (height - pad.top - pad.bottom)"
          :y2="pad.top + ((step - 1) / 4) * (height - pad.top - pad.bottom)" />
      </g>

      <line class="chart-threshold" :x1="pad.left" :x2="width - pad.right"
        :y1="thresholdY" :y2="thresholdY" />
      <text class="chart-threshold-label" :x="width - pad.right" :y="thresholdY - 6">
        延迟阈值 {{ ms(latencyThreshold) }}
      </text>

      <g class="chart-bars">
        <rect
          v-for="(point, index) in plotted"
          :key="`bar-${point.key}`"
          :x="point.x - Math.max(2, 280 / Math.max(points.length, 1)) / 2"
          :y="point.uptimeY"
          :width="Math.max(2, 280 / Math.max(points.length, 1))"
          :height="height - pad.bottom - point.uptimeY"
          :class="{ 'is-empty': point.uptime_pct == null }"
          rx="2"
        />
      </g>

      <path
        v-if="latencyPath"
        class="chart-latency-line"
        :d="latencyPath"
        fill="none"
      />

      <g class="chart-points">
        <g v-for="(point, index) in plotted" :key="`point-${point.key}`">
          <circle
            v-if="point.p95_latency_ms != null"
            :cx="point.x"
            :cy="point.latencyY"
            r="4"
          />
          <rect
            class="chart-hit"
            :x="point.x - Math.max(8, 360 / Math.max(points.length, 1)) / 2"
            :y="pad.top"
            :width="Math.max(8, 360 / Math.max(points.length, 1))"
            :height="height - pad.top - pad.bottom"
            @mouseenter="hovered = index"
            @mouseleave="hovered = null"
          />
        </g>
      </g>

      <g class="chart-values">
        <template v-for="label in valueLabels" :key="`value-${label.key}`">
          <text
            v-if="label.uptimeText"
            class="chart-value-bar"
            :x="label.x"
            :y="label.uptimeY ?? undefined"
            text-anchor="middle"
          >
            {{ label.uptimeText }}
          </text>
          <text
            v-if="label.latencyText"
            class="chart-value-point"
            :x="label.x"
            :y="label.latencyY ?? undefined"
            text-anchor="middle"
          >
            {{ label.latencyText }}
          </text>
        </template>
      </g>

      <g class="chart-axis-labels">
        <text :x="pad.left - 8" :y="pad.top + 4" text-anchor="end">{{ ms(maxLatency) }}</text>
        <text :x="pad.left - 8" :y="height - pad.bottom + 4" text-anchor="end">0</text>
        <text
          v-for="index in labelIndexes"
          :key="`label-${index}`"
          :x="plotted[index]?.x"
          :y="height - 12"
          text-anchor="middle"
        >
          {{ points[index]?.label }}
        </text>
      </g>

      <g v-if="hovered != null && plotted[hovered]" class="chart-tooltip">
        <line
          :x1="plotted[hovered].x"
          :x2="plotted[hovered].x"
          :y1="pad.top"
          :y2="height - pad.bottom"
        />
        <rect
          :x="Math.min(width - 182, Math.max(8, plotted[hovered].x - 82))"
          y="6"
          width="174"
          height="58"
          rx="8"
        />
        <text
          :x="Math.min(width - 170, Math.max(20, plotted[hovered].x - 70))"
          y="29"
        >
          可用率 {{ plotted[hovered].uptime_pct == null ? '暂无' : `${plotted[hovered].uptime_pct}%` }}
        </text>
        <text
          :x="Math.min(width - 170, Math.max(20, plotted[hovered].x - 70))"
          y="50"
        >
          P95 {{ ms(plotted[hovered].p95_latency_ms) }} · {{ plotted[hovered].calls }} 次
        </text>
      </g>
    </svg>
    <div class="chart-legend">
      <span><i class="legend-line"></i>模型总延迟（P95）</span>
      <span><i class="legend-bar"></i>调用可用率</span>
    </div>
  </div>
</template>
