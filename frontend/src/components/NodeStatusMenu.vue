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
        <span>{{ healthyCount }}/{{ nodes.length }} 在线</span>
      </div>

      <div class="status-list">
        <div v-if="nodes.length === 0" class="status-empty">暂无节点状态</div>
        <article
          v-for="node in nodes"
          :key="node.node_id"
          :class="['status-item', node.online ? 'online' : 'offline']"
        >
          <div class="status-item-main">
            <span class="item-dot" />
            <strong>{{ node.name || node.node_id }}</strong>
          </div>
          <div class="status-item-detail">
            <template v-if="node.online">
              uptime {{ formatDuration(node.uptime_seconds) }}
            </template>
            <template v-else>
              issue {{ formatDuration(node.issue_seconds) }}
            </template>
          </div>
          <div v-if="!node.online" class="issue-text">{{ node.issue || 'Node is offline.' }}</div>
        </article>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { NodeHealth } from '@/stores/tunnel'

const props = defineProps<{
  nodes: NodeHealth[]
}>()

const open = ref(false)

const healthyCount = computed(() => props.nodes.filter((node) => node.online).length)
const issueCount = computed(() => props.nodes.filter((node) => !node.online).length)
const hasIssues = computed(() => issueCount.value > 0)
const triggerText = computed(() => {
  if (!props.nodes.length) return '状态'
  return hasIssues.value ? `状态 ${issueCount.value}` : '状态正常'
})

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
  width: min(420px, calc(100vw - 32px));
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
  max-height: 340px;
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
}

.status-item.online .item-dot {
  color: var(--color-success);
}

.status-item.offline .item-dot {
  color: var(--color-danger);
}

.status-item-detail {
  padding-left: 16px;
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.issue-text {
  padding-left: 16px;
  color: var(--color-danger);
  font-size: var(--font-size-xs);
  line-height: 1.4;
  word-break: break-word;
}
</style>
