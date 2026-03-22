<template>
  <section class="section">
    <div class="section-header">
      <h2>集群总览</h2>
      <span class="section-summary">
        GPU {{ summary.total_gpu }} 张 · 空闲 {{ summary.free_gpu }} 张 · 实例 {{ summary.total_instances }} 个
      </span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>节点名称</th>
            <th>状态</th>
            <th>GPU 空闲/总数</th>
            <th>GPU 型号</th>
            <th>运行实例数</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="nodes.length === 0">
            <td colspan="6" class="empty-cell">暂无节点数据</td>
          </tr>
          <template v-for="node in nodes" :key="node.node_id">
            <!-- Main row -->
            <tr
              class="clickable-row"
              :class="{ expanded: expandedNodes.has(node.node_id) }"
              @click="toggleExpand(node.node_id)"
            >
              <td>
                <span class="expand-arrow">▶</span>
                {{ node.name || node.node_id }}
              </td>
              <td>
                <span :class="node.online ? 'status-online' : 'status-offline'">
                  {{ node.online ? '● 在线' : '○ 离线' }}
                </span>
              </td>
              <td :class="{ 'gpu-zero': node.online && node.gpu_free === 0 }">
                {{ node.gpu_free }}/{{ node.gpu_total }}
              </td>
              <td>{{ node.gpu_model || '—' }}</td>
              <td>{{ node.instance_count || 0 }}</td>
              <td>
                <a
                  v-if="buildEntryUrl(node.web_url)"
                  class="btn-primary"
                  :href="buildEntryUrl(node.web_url)"
                  target="_blank"
                  rel="noopener"
                  @click.stop
                >
                  进入管理
                </a>
                <span v-else class="muted">—</span>
              </td>
            </tr>

            <!-- Expand row: GPU details -->
            <tr v-if="expandedNodes.has(node.node_id)" class="expand-row">
              <td colspan="6" class="expand-cell">
                <div v-if="node.gpus && node.gpus.length" class="gpu-grid">
                  <span
                    v-for="gpu in node.gpus"
                    :key="gpu.index"
                    :class="['gpu-chip', gpu.status === 'free' ? 'free' : 'used']"
                  >
                    GPU {{ gpu.index }}: {{ gpu.status === 'free' ? '空闲' : (gpu.allocated_to || '占用中') }}
                  </span>
                </div>
                <span v-else class="muted">无 GPU 详情数据</span>
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
import type { NodeStatus, ClusterSummary } from '@/stores/cluster'

const props = defineProps<{
  nodes: NodeStatus[]
  summary: ClusterSummary
  currentNodeId: string
  token: string
}>()

const expandedNodes = ref(new Set<string>())

// Auto-expand current node on first load
if (props.currentNodeId) {
  expandedNodes.value.add(props.currentNodeId)
}

function toggleExpand(nodeId: string) {
  if (expandedNodes.value.has(nodeId)) {
    expandedNodes.value.delete(nodeId)
  } else {
    expandedNodes.value.add(nodeId)
  }
}

function buildEntryUrl(webUrl?: string): string {
  if (!webUrl) return ''
  const separator = webUrl.includes('?') ? '&' : '?'
  return `${webUrl}${separator}token=${encodeURIComponent(props.token)}`
}
</script>

<style scoped>
.section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  margin-bottom: 16px;
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
}

.table-wrap { overflow-x: auto; }

table { width: 100%; }

thead th {
  padding: 8px 16px;
  text-align: left;
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  background: var(--color-surface-alt);
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}

tbody td {
  padding: 8px 16px;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--font-size-sm);
  color: var(--color-text);
  vertical-align: middle;
}

tbody tr { transition: background var(--transition-fast); }
tbody tr:hover { background: #f3f2f1; }
tbody tr:last-child td { border-bottom: none; }

.empty-cell {
  text-align: center;
  padding: 40px 20px;
  color: var(--color-text-muted);
}

/* Clickable row */
.clickable-row { cursor: pointer; }

.expand-arrow {
  display: inline-block;
  font-size: 9px;
  margin-right: 8px;
  color: var(--color-text-muted);
  transition: transform 0.15s;
}

.clickable-row.expanded .expand-arrow { transform: rotate(90deg); }

/* Expand row */
.expand-row td {
  background: var(--color-surface-alt);
}

.expand-cell { padding: 8px 16px 8px 40px; }

/* GPU grid */
.gpu-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.gpu-chip {
  padding: 3px 10px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
}

.gpu-chip.used {
  background: var(--color-danger-bg);
  border-color: var(--color-danger-border);
  color: var(--color-danger);
}

.gpu-chip.free {
  background: var(--color-success-bg);
  border-color: var(--color-success-border);
  color: var(--color-success);
}

/* Status */
.status-online { color: var(--color-success); }
.status-offline { color: #a19f9d; }
.gpu-zero { color: var(--color-danger); font-weight: var(--font-weight-semibold); }

/* Button */
.btn-primary {
  display: inline-block;
  padding: 4px 12px;
  background: var(--color-primary);
  color: #fff;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  transition: background var(--transition-fast);
  text-decoration: none;
}

.btn-primary:hover { background: var(--color-primary-hover); text-decoration: none; }

.muted { color: var(--color-text-muted); }
</style>
