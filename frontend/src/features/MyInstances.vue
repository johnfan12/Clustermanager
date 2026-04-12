<template>
  <section class="section">
    <div class="section-header">
      <h2>我的实例</h2>
      <span class="section-summary">共 {{ runningCount }} 个运行中</span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>节点</th>
            <th>实例名</th>
            <th>GPU 数</th>
            <th>内存</th>
            <th>镜像</th>
            <th>SSH 连接</th>
            <th>密码</th>
            <th>
              <span class="auto-stop-heading">
                状态
                <span
                  class="auto-stop-help"
                  data-tooltip="运行中的实例会显示自动停止剩余时间；手动停止后计时器立即结束，实例不会被删除。"
                  aria-label="运行中的实例会显示自动停止剩余时间；手动停止后计时器立即结束，实例不会被删除。"
                  tabindex="0"
                >!</span>
              </span>
            </th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="instances.length === 0">
            <td colspan="9" class="empty-cell">暂无运行中的实例</td>
          </tr>
          <tr v-for="(inst, idx) in instances" :key="inst.container_name + '-' + idx">
            <td>{{ inst.node_name || inst.node_id || '—' }}</td>
            <td class="name-cell">
              <div class="instance-label">{{ instanceLabel(inst) }}</div>
              <div v-if="showTechnicalName(inst)" class="instance-technical">
                {{ inst.container_name }}
              </div>
            </td>
            <td>{{ gpuCount(inst) }}</td>
            <td>{{ inst.memory_gb != null ? inst.memory_gb + 'G' : '—' }}</td>
            <td>{{ inst.image_name || '—' }}</td>
            <td>
              <div v-if="sshCommand(inst) !== '—'" class="ssh-cell">
                <code class="ssh-cmd">{{ sshCommand(inst) }}</code>
                <button class="copy-btn" @click="handleCopy(sshCommand(inst), $event)">📋</button>
              </div>
              <span v-else-if="isPendingSsh(inst)" class="ssh-pending">
                <span class="pending-spinner" /> SSH 隧道创建中...
              </span>
              <span v-else>—</span>
            </td>
            <td>
              <div v-if="inst.ssh_password" class="pwd-cell">
                <span>{{ passwordVisible.has(idx) ? inst.ssh_password : '****' }}</span>
                <button class="copy-btn" @click="handleCopy(inst.ssh_password, $event)">📋</button>
                <button class="pwd-toggle" @click="togglePassword(idx)">
                  {{ passwordVisible.has(idx) ? '🙈' : '👁' }}
                </button>
              </div>
              <span v-else>—</span>
            </td>
            <td>
              <div class="status-cell" :class="{ 'auto-stop-warning': isAutoStopSoon(inst) }">
                <div class="status-summary">
                  <span :class="statusClass(inst.status)">
                    <span class="status-dot" aria-hidden="true" />
                    <span>{{ statusText(inst.status) }}</span>
                  </span>
                  <div
                    v-if="inst.status === 'running'"
                    class="countdown"
                  >
                    {{ autoStopCountdownText(inst) }}
                  </div>
                  <div
                    v-else-if="inst.status === 'stopped'"
                    :class="powerHintClass(inst)"
                  >
                    {{ powerHintText(inst) }}
                  </div>
                </div>
                <div
                  v-if="inst.status === 'rebuilding'"
                  class="power-hint rebuilding-hint"
                >
                  等待节点完成重建
                </div>
              </div>
            </td>
            <td>
              <div class="ops">
                <button
                  class="op-btn"
                  :disabled="inst.status !== 'running' || isOperationLocked(inst)"
                  @click="handleAction('stop', inst)"
                >停止</button>
                <button
                  class="op-btn"
                  :disabled="inst.status === 'running' || isOperationLocked(inst)"
                  @click="handleAction('restart', inst)"
                >重启</button>
                <button
                  class="op-btn"
                  :disabled="inst.status !== 'running' || isOperationLocked(inst)"
                  @click="handleAction('renew', inst)"
                >定时</button>
                <button
                  class="op-btn"
                  :disabled="isOperationLocked(inst)"
                  @click="handleAction('rebuild', inst)"
                >变更配置</button>
                <button
                  class="op-btn"
                  :disabled="isOperationLocked(inst)"
                  @click="handleAction('logs', inst)"
                >日志</button>
                <button
                  class="op-btn danger"
                  :disabled="isOperationLocked(inst)"
                  @click="handleAction('delete', inst)"
                >删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { Instance, NodeStatus } from '@/stores/cluster'
import { autoStopCountdown } from '@/shared/utils/format'
import { copyToClipboard } from '@/shared/utils/clipboard'
import { useToastStore } from '@/stores/toast'

const props = defineProps<{
  instances: Instance[]
  nodes: NodeStatus[]
  pendingSshInstances?: Set<string>
}>()

const emit = defineEmits<{
  action: [action: string, instance: Instance]
  refresh: []
}>()

const toast = useToastStore()
const passwordVisible = reactive(new Set<number>())

const runningCount = computed(() =>
  props.instances.filter((i) => i.status === 'running').length
)

const nodeMap = computed(() =>
  new Map(props.nodes.map((node) => [node.node_id, node]))
)

function gpuCount(inst: Instance): number {
  return Array.isArray(inst.gpu_indices) ? inst.gpu_indices.length : 0
}

function instanceLabel(inst: Instance): string {
  return String(inst.display_name || inst.container_name || '—')
}

function showTechnicalName(inst: Instance): boolean {
  return Boolean(inst.display_name && inst.display_name !== inst.container_name)
}

function sshCommand(inst: Instance): string {
  if (inst.vps_access?.ssh_cmd) return inst.vps_access.ssh_cmd
  if (inst.ssh_command) return inst.ssh_command
  if (inst.ssh_cmd) return inst.ssh_cmd
  return '—'
}

function statusClass(status: string): string {
  if (status === 'running') return 'status-running'
  if (status === 'stopped') return 'status-stopped'
  if (status === 'rebuilding') return 'status-rebuilding'
  return 'status-error'
}

function statusText(status: string): string {
  if (status === 'running') return '运行'
  if (status === 'stopped') return '停止'
  if (status === 'rebuilding') return '重建中'
  return '异常'
}

function isOperationLocked(inst: Instance): boolean {
  return inst.status === 'rebuilding'
}

function canStartInstance(inst: Instance): boolean {
  const node = nodeMap.value.get(inst.node_id)
  if (!node || !node.online) return false

  const requiredGpuCount = gpuCount(inst)
  if (requiredGpuCount <= 0) return true
  return requiredGpuCount <= node.gpu_free
}

function powerHintText(inst: Instance): string {
  return canStartInstance(inst) ? '可开机' : '不可开机'
}

function powerHintClass(inst: Instance): string {
  return canStartInstance(inst) ? 'power-hint can-start' : 'power-hint cannot-start'
}

function togglePassword(idx: number) {
  if (passwordVisible.has(idx)) {
    passwordVisible.delete(idx)
  } else {
    passwordVisible.add(idx)
  }
}

function autoStopAt(inst: Instance): string | null {
  return String(inst.auto_stop_at || inst.expire_at || '') || null
}

function autoStopTimestamp(value: string): number {
  const hasTimezone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value)
  return new Date(hasTimezone ? value : `${value}Z`).getTime()
}

function autoStopCountdownText(inst: Instance): string {
  const countdown = autoStopCountdown(autoStopAt(inst))
  return countdown ? `剩余 ${countdown}` : '计时中'
}

function isAutoStopSoon(inst: Instance): boolean {
  const value = autoStopAt(inst)
  if (inst.status !== 'running' || !value) return false
  const diff = autoStopTimestamp(value) - Date.now()
  return diff > 0 && diff < 24 * 3600 * 1000 // less than 24h
}

async function handleCopy(text: string, event: MouseEvent) {
  const btn = event.currentTarget as HTMLButtonElement
  const success = await copyToClipboard(text)
  if (success) {
    const original = btn.textContent
    btn.textContent = '✓'
    toast.success('已复制到剪贴板')
    setTimeout(() => { btn.textContent = original }, 1500)
  }
}

function handleAction(action: string, instance: Instance) {
  emit('action', action, instance)
}

function isPendingSsh(instance: Instance): boolean {
  if (!props.pendingSshInstances) return false
  const key = `${instance.node_id}:${instance.id}`
  return props.pendingSshInstances.has(key)
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

.name-cell {
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  min-width: 200px;
  max-width: 300px;
  white-space: normal;
  word-break: break-all;
  overflow-wrap: anywhere;
  line-height: 1.4;
}

.instance-label {
  font-family: var(--font-mono);
}

.instance-technical {
  margin-top: 2px;
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  font-family: var(--font-mono);
}

/* Status */
.status-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.status-summary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.status-running,
.status-stopped,
.status-rebuilding,
.status-error {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  font-weight: var(--font-weight-medium);
}

.status-running {
  color: var(--color-success);
}

.status-stopped {
  color: var(--color-danger);
}

.status-rebuilding {
  color: var(--color-warning, #9a6b00);
}

.status-error {
  color: var(--color-danger);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex: 0 0 auto;
  background: currentColor;
}

.power-hint {
  font-size: var(--font-size-xs);
  line-height: 1.3;
  white-space: nowrap;
}

.power-hint.can-start {
  color: var(--color-success);
}

.power-hint.cannot-start {
  color: var(--color-danger);
}

.rebuilding-hint {
  color: var(--color-warning, #9a6b00);
}

/* SSH cell */
.ssh-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  max-width: 100%;
}

.ssh-cmd {
  flex: 1 1 auto;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  background: var(--color-surface-alt);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  color: var(--color-text);
  white-space: normal;
  word-break: break-all;
  overflow-wrap: anywhere;
  border: 1px solid var(--color-border);
}

.copy-btn {
  flex: 0 0 auto;
  padding: 2px 8px;
  font-size: var(--font-size-xs);
  background: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  transition: all var(--transition-fast);
  cursor: pointer;
}

.copy-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* SSH pending */
.ssh-pending {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.pending-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Password cell */
.pwd-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pwd-toggle {
  background: none;
  border: none;
  font-size: 14px;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0 4px;
}

.pwd-toggle:hover { color: var(--color-primary); }

/* Auto-stop warning */
.auto-stop-warning {
  color: var(--color-danger);
}

.auto-stop-warning .countdown {
  font-weight: var(--font-weight-medium);
}

.countdown {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: 2px;
}

.status-summary .countdown,
.status-summary .power-hint {
  margin-top: 0;
}

.auto-stop-heading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.auto-stop-help {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  width: 13px;
  height: 13px;
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  color: var(--color-text-muted);
  font-size: 9px;
  font-weight: var(--font-weight-semibold);
  line-height: 1;
  cursor: default;
}

.auto-stop-help::before,
.auto-stop-help::after {
  position: absolute;
  left: 50%;
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--transition-fast), transform var(--transition-fast);
  z-index: 10;
}

.auto-stop-help::before {
  content: '';
  top: calc(100% + 3px);
  transform: translateX(-50%) translateY(-2px);
  border: 5px solid transparent;
  border-bottom-color: var(--color-text);
}

.auto-stop-help::after {
  content: attr(data-tooltip);
  top: calc(100% + 12px);
  width: max-content;
  max-width: 240px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  background: var(--color-text);
  box-shadow: var(--shadow-md);
  color: #fff;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-normal);
  line-height: 1.5;
  white-space: normal;
  transform: translateX(-50%) translateY(-2px);
}

.auto-stop-help:hover,
.auto-stop-help:focus-visible {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.auto-stop-help:hover::before,
.auto-stop-help:hover::after,
.auto-stop-help:focus-visible::before,
.auto-stop-help:focus-visible::after {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

/* Operations */
.ops {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  white-space: normal;
}

.op-btn {
  padding: 3px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-primary);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.op-btn:hover:not(:disabled) {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.op-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
  color: var(--color-text-muted);
}

.op-btn.danger {
  color: var(--color-danger);
  border-color: var(--color-danger-border);
}

.op-btn.danger:hover:not(:disabled) {
  background: var(--color-danger-bg);
  border-color: var(--color-danger);
}</style>
