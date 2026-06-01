<template>
  <div class="status-menu">
    <button
      :class="['status-trigger', hasIssues ? 'issue' : 'ok']"
      type="button"
      @click="open = !open"
    >
      <span class="status-dot" />
      {{ triggerText }}
    </button>

    <div v-if="open" class="status-popover">
      <div class="status-popover-head">
        <strong>节点状态</strong>
        <span>{{ apiHealthyCount }}/{{ nodes.length }} API · {{ sshSummaryText }}</span>
      </div>

      <div class="status-list">
        <div v-if="nodes.length === 0" class="status-empty">暂无节点状态</div>
        <article
          v-for="node in nodes"
          :key="node.node_id"
          :class="['status-item', nodeHasIssue(node) ? 'offline' : 'online']"
        >
          <div class="status-item-main">
            <span class="item-dot" />
            <strong>{{ node.name || node.node_id }}</strong>
            <div class="service-pills">
              <span :class="['service-pill', node.online ? 'ok' : 'bad']">
                API {{ node.online ? '在线' : '离线' }}
              </span>
              <span :class="['service-pill', sshStatusClass(node)]">
                {{ sshLabel(node) }}
              </span>
            </div>
          </div>
          <div class="status-item-detail">
            <span>API {{ apiDetail(node) }}</span>
            <span>SSH {{ sshDetail(node) }}</span>
          </div>
          <div v-if="sshTarget(node)" class="ssh-target">SSH {{ sshTarget(node) }}</div>
          <div v-if="!node.online" class="issue-text">API: {{ node.issue || 'Node is offline.' }}</div>
          <div v-if="node.ssh_checked && !node.ssh_online" class="issue-text">
            SSH: {{ node.ssh_issue || 'SSH is offline.' }}
          </div>

          <!-- 30-day uptime grid -->
          <div class="uptime-grid-wrap">
            <div class="uptime-grid-label">API 过去 30 天</div>
            <div class="uptime-grid">
              <div
                v-for="(day, idx) in getNodeHistory(node.node_id)"
                :key="idx"
                :class="['uptime-cell', dayClass(day)]"
                :title="dayTooltip(day)"
              />
            </div>
            <div class="uptime-grid-legend">
              <span>30 天前</span>
              <span>今天</span>
            </div>
          </div>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { NodeHealth, DailyNodeStatus } from '@/stores/tunnel'

const props = defineProps<{
  nodes: NodeHealth[]
  history: Record<string, DailyNodeStatus[]>
}>()

const open = ref(false)

const apiHealthyCount = computed(() => props.nodes.filter((node) => node.online).length)
const sshCheckedCount = computed(() => props.nodes.filter((node) => node.ssh_checked).length)
const sshHealthyCount = computed(
  () => props.nodes.filter((node) => node.ssh_checked && node.ssh_online).length
)
const issueCount = computed(() => props.nodes.filter((node) => nodeHasIssue(node)).length)
const hasIssues = computed(() => issueCount.value > 0)
const sshSummaryText = computed(() => {
  if (!props.nodes.length) return 'SSH —'
  if (!sshCheckedCount.value) return 'SSH 未检查'
  return `${sshHealthyCount.value}/${sshCheckedCount.value} SSH`
})
const triggerText = computed(() => {
  if (!props.nodes.length) return '状态'
  return hasIssues.value ? `状态 ${issueCount.value}` : '状态正常'
})

function getNodeHistory(nodeId: string): DailyNodeStatus[] {
  return props.history[nodeId] || []
}

function dayClass(day: DailyNodeStatus): string {
  if (day.checks_total === 0) return 'no-data'
  if (day.checks_ok === day.checks_total) return 'all-ok'
  if (day.checks_ok === 0) return 'all-fail'
  return 'partial'
}

function dayTooltip(day: DailyNodeStatus): string {
  if (day.checks_total === 0) return `${day.date}\n暂无数据`
  const pct = Math.round((day.checks_ok / day.checks_total) * 100)
  if (pct === 100) return `${day.date}\n全天正常`
  if (pct === 0) return `${day.date}\n全天异常`
  return `${day.date}\n正常率 ${pct}% (${day.checks_ok}/${day.checks_total})`
}

function nodeHasIssue(node: NodeHealth): boolean {
  return !node.online || Boolean(node.ssh_checked && !node.ssh_online)
}

function apiDetail(node: NodeHealth): string {
  if (node.online) return `uptime ${formatDuration(node.uptime_seconds)}`
  return `issue ${formatDuration(node.issue_seconds)}`
}

function sshStatusClass(node: NodeHealth): string {
  if (!node.ssh_checked) return 'unknown'
  return node.ssh_online ? 'ok' : 'bad'
}

function sshLabel(node: NodeHealth): string {
  if (!node.ssh_checked) return 'SSH 未检查'
  return node.ssh_online ? 'SSH 在线' : 'SSH 离线'
}

function sshDetail(node: NodeHealth): string {
  if (!node.ssh_checked) return '未检查'
  if (node.ssh_online) return `uptime ${formatDuration(node.ssh_uptime_seconds)}`
  return `issue ${formatDuration(node.ssh_issue_seconds)}`
}

function sshTarget(node: NodeHealth): string {
  if (!node.ssh_host || !node.ssh_port) return ''
  return `${node.ssh_host}:${node.ssh_port}`
}

function formatDuration(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || Number.isNaN(seconds)) return '—'
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60
  if (hours < 24) return restMinutes ? `${hours}h ${restMinutes}m` : `${hours}h`
  const days = Math.floor(hours / 24)
  const restHours = hours % 24
  return restHours ? `${days}d ${restHours}h` : `${days}d`
}
</script>

<style scoped>
.status-menu {
  position: relative;
}

.status-trigger {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  cursor: pointer;
}

.status-trigger.ok {
  border-color: var(--color-success-border);
  color: var(--color-success);
}

.status-trigger.issue {
  border-color: var(--color-danger-border);
  color: var(--color-danger);
}

.status-dot,
.item-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: currentColor;
}

.status-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: var(--z-dropdown);
  width: min(460px, calc(100vw - 32px));
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}

.status-popover-head {
  min-height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-alt);
  font-size: var(--font-size-sm);
}

.status-popover-head span {
  color: var(--color-text-muted);
}

.status-list {
  max-height: 480px;
  overflow: auto;
}

.status-empty {
  padding: 18px 12px;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.status-item {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
}

.status-item:last-child {
  border-bottom: 0;
}

.status-item-main {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--font-size-sm);
  flex-wrap: wrap;
}

.status-item.online .item-dot {
  color: var(--color-success);
}

.status-item.offline .item-dot {
  color: var(--color-danger);
}

.status-item-detail {
  padding-left: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.service-pills {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.service-pill {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 7px;
  border-radius: var(--radius-full);
  border: 1px solid var(--color-border);
  background: var(--color-surface-alt);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
}

.service-pill.ok {
  border-color: var(--color-success-border);
  background: var(--color-success-bg);
  color: var(--color-success);
}

.service-pill.bad {
  border-color: var(--color-danger-border);
  background: var(--color-danger-bg);
  color: var(--color-danger);
}

.service-pill.unknown {
  border-color: var(--color-border-subtle);
  color: var(--color-text-muted);
}

.ssh-target {
  padding-left: 16px;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
}

.issue-text {
  padding-left: 16px;
  color: var(--color-danger);
  font-size: var(--font-size-xs);
  line-height: 1.4;
  word-break: break-word;
}

/* ── 30-day uptime grid ── */
.uptime-grid-wrap {
  margin-top: 6px;
  padding-left: 16px;
}

.uptime-grid-label {
  font-size: 10px;
  color: var(--color-text-muted);
  margin-bottom: 3px;
}

.uptime-grid {
  display: flex;
  gap: 2px;
}

.uptime-cell {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
  transition: transform var(--transition-fast), box-shadow var(--transition-fast);
  cursor: default;
}

.uptime-cell:hover {
  transform: scale(1.6);
  box-shadow: 0 0 0 1px rgba(0,0,0,0.15);
  z-index: 1;
  position: relative;
}

.uptime-cell.all-ok {
  background: #2da44e;
}

.uptime-cell.partial {
  background: #f0883e;
}

.uptime-cell.all-fail {
  background: #cf222e;
}

.uptime-cell.no-data {
  background: #d0d7de;
}

.uptime-grid-legend {
  display: flex;
  justify-content: space-between;
  font-size: 9px;
  color: var(--color-text-placeholder);
  margin-top: 2px;
}
</style>
