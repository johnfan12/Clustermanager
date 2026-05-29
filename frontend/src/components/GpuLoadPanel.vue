<template>
  <section class="section">
    <div class="section-header">
      <h2>GPU 负载</h2>
      <span class="section-summary">
        GPU {{ summary.total_gpu }} 张 · 空闲 {{ summary.free_gpu }} 张 · 使用中 {{ summary.used_gpu }} 张
        <span v-if="summary.gpu_utilization_avg !== null">
          · 平均负载 {{ formatPercent(summary.gpu_utilization_avg) }}
        </span>
      </span>
    </div>

    <div v-if="errors.length" class="gpu-errors">
      {{ errors.join('；') }}
    </div>

    <div class="table-wrap">
      <table class="gpu-table">
        <thead>
          <tr>
            <th>节点</th>
            <th>状态</th>
            <th>GPU 空闲/总数</th>
            <th>平均负载</th>
            <th>显存</th>
            <th>功耗</th>
            <th>温度</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="nodes.length === 0">
            <td colspan="7" class="empty-cell">暂无 GPU 数据</td>
          </tr>
          <template v-for="node in nodes" :key="node.node_id">
            <tr class="gpu-row">
              <td>
                <button
                  class="expand-toggle"
                  type="button"
                  :aria-expanded="isExpanded(node.node_id)"
                  @click="toggleNode(node.node_id)"
                >
                  <span :class="['expand-arrow', { expanded: isExpanded(node.node_id) }]">›</span>
                  {{ node.name || node.node_id }}
                </button>
              </td>
              <td>
                <span :class="['node-status', node.online ? 'online' : 'offline']">
                  {{ node.online ? '在线' : '离线' }}
                </span>
              </td>
              <td :class="{ 'gpu-zero': node.online && node.gpu_free === 0 && node.gpu_total > 0 }">
                {{ node.gpu_free }}/{{ node.gpu_total }}
              </td>
              <td>
                <div class="metric-cell">
                  <span>{{ formatPercent(node.gpu_utilization_avg) }}</span>
                  <div class="meter">
                    <span
                      :class="['meter-fill', loadLevel(node.gpu_utilization_avg)]"
                      :style="{ width: `${percentWidth(node.gpu_utilization_avg)}%` }"
                    />
                  </div>
                </div>
              </td>
              <td>{{ formatMemory(node.memory_used_mb, node.memory_total_mb) }}</td>
              <td>{{ formatPower(node.power_draw_w, node.power_limit_w) }}</td>
              <td>{{ formatTemperature(node.temperature_avg_c) }}</td>
            </tr>

            <tr v-if="isExpanded(node.node_id)" class="gpu-detail-row">
              <td colspan="7">
                <div v-if="node.gpus.length" class="gpu-grid">
                  <article
                    v-for="gpu in node.gpus"
                    :key="`${node.node_id}-${gpu.index}`"
                    :class="['gpu-chip', gpu.status]"
                  >
                    <div class="gpu-chip-head">
                      <strong>GPU {{ gpu.index }}</strong>
                      <span>{{ gpu.status === 'free' ? '空闲' : gpu.allocated_to || '占用中' }}</span>
                    </div>
                    <div class="gpu-model">{{ gpu.name || gpu.gpu_model || node.gpu_model || '—' }}</div>
                    <div class="chip-line">
                      <span>负载</span>
                      <strong>{{ formatPercent(gpu.utilization_gpu) }}</strong>
                    </div>
                    <div class="meter">
                      <span
                        :class="['meter-fill', loadLevel(gpu.utilization_gpu)]"
                        :style="{ width: `${percentWidth(gpu.utilization_gpu)}%` }"
                      />
                    </div>
                    <div class="chip-line">
                      <span>显存</span>
                      <strong>{{ formatMemory(gpu.memory_used_mb, gpu.memory_total_mb) }}</strong>
                    </div>
                    <div class="chip-line">
                      <span>功耗</span>
                      <strong>{{ formatPower(gpu.power_draw_w, gpu.power_limit_w) }}</strong>
                    </div>
                    <div class="chip-line">
                      <span>温度</span>
                      <strong>{{ formatTemperature(gpu.temperature_c) }}</strong>
                    </div>
                  </article>
                </div>
                <span v-else class="muted">{{ node.error || '无 GPU 详情数据' }}</span>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { GpuInfo, GpuSummary, NodeGpuStatus } from '@/stores/tunnel'

defineProps<{
  nodes: NodeGpuStatus[]
  summary: GpuSummary
  errors: string[]
}>()

const expandedNodes = ref(new Set<string>())

function isExpanded(nodeId: string) {
  return expandedNodes.value.has(nodeId)
}

function toggleNode(nodeId: string) {
  const next = new Set(expandedNodes.value)
  if (next.has(nodeId)) {
    next.delete(nodeId)
  } else {
    next.add(nodeId)
  }
  expandedNodes.value = next
}

function percentWidth(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0
  return Math.max(0, Math.min(100, Math.round(value)))
}

function loadLevel(value: number | null | undefined) {
  const width = percentWidth(value)
  if (width >= 85) return 'high'
  if (width >= 60) return 'medium'
  return 'low'
}

function formatPercent(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return `${Math.round(value)}%`
}

function formatGb(valueMb: number | null | undefined) {
  if (typeof valueMb !== 'number' || Number.isNaN(valueMb) || valueMb < 0) return null
  if (valueMb === 0) return '0 GB'
  return `${(valueMb / 1024).toFixed(valueMb >= 10240 ? 0 : 1)} GB`
}

function formatMemory(usedMb: number | null | undefined, totalMb: number | null | undefined) {
  const used = formatGb(usedMb)
  const total = formatGb(totalMb)
  if (!used && !total) return '—'
  if (!used) return `— / ${total}`
  if (!total) return used
  return `${used} / ${total}`
}

function formatPower(draw: number | null | undefined, limit: number | null | undefined) {
  if (typeof draw !== 'number' || Number.isNaN(draw)) return '—'
  const drawText = `${Math.round(draw)} W`
  if (typeof limit !== 'number' || Number.isNaN(limit) || limit <= 0) return drawText
  return `${drawText} / ${Math.round(limit)} W`
}

function formatTemperature(value: GpuInfo['temperature_c']) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return `${Math.round(value)} C`
}
</script>

<style scoped>
.section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.section-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: var(--color-surface);
}

.section-header h2 {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.section-summary {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  text-align: right;
}

.gpu-errors {
  padding: 8px 16px;
  border-bottom: 1px solid var(--color-danger-border);
  background: var(--color-danger-bg);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

.table-wrap {
  overflow-x: auto;
}

.gpu-table,
.gpu-table table {
  width: 100%;
}

.gpu-table {
  min-width: 960px;
  border-collapse: collapse;
}

.gpu-table th,
.gpu-table td {
  padding: 8px 16px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: middle;
  font-size: var(--font-size-sm);
}

.gpu-table th {
  background: var(--color-surface-alt);
  color: var(--color-text-muted);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.gpu-table tbody tr {
  transition: background var(--transition-fast);
}

.gpu-row:hover {
  background: #f3f2f1;
}

.gpu-row td {
  white-space: nowrap;
}

.empty-cell {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-text-muted);
}

.expand-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 0;
  background: transparent;
  color: var(--color-text);
  font: inherit;
  padding: 0;
  cursor: pointer;
}

.expand-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 12px;
  height: 12px;
  color: var(--color-text-muted);
  font-size: 16px;
  line-height: 1;
  transition: transform var(--transition-fast);
}

.expand-arrow.expanded {
  transform: rotate(90deg);
}

.node-status {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
}

.node-status.online {
  border: 1px solid var(--color-success-border);
  background: var(--color-success-bg);
  color: var(--color-success);
}

.node-status.offline {
  border: 1px solid var(--color-border);
  background: var(--color-surface-alt);
  color: var(--color-text-muted);
}

.metric-cell {
  display: grid;
  gap: 4px;
  min-width: 120px;
}

.meter {
  width: 100%;
  height: 6px;
  border-radius: var(--radius-full);
  overflow: hidden;
  background: var(--color-border);
}

.meter-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.meter-fill.low { background: var(--color-success); }
.meter-fill.medium { background: var(--color-warning); }
.meter-fill.high { background: var(--color-danger); }

.gpu-detail-row td {
  background: var(--color-surface-alt);
  padding: 12px 16px;
}

.gpu-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.gpu-chip {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.gpu-chip.used {
  border-color: var(--color-danger-border);
}

.gpu-chip.free {
  border-color: var(--color-success-border);
}

.gpu-chip-head,
.chip-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.gpu-chip-head {
  font-size: var(--font-size-sm);
}

.gpu-chip-head span,
.chip-line span {
  color: var(--color-text-muted);
}

.gpu-model {
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  min-height: 16px;
}

.chip-line {
  font-size: var(--font-size-xs);
}

.gpu-zero {
  color: var(--color-danger);
  font-weight: var(--font-weight-semibold);
}

.muted {
  color: var(--color-text-muted);
}
</style>
