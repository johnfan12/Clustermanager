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
            <th>状态</th>
            <th>SSH 连接</th>
            <th>密码</th>
            <th>到期时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="instances.length === 0">
            <td colspan="10" class="empty-cell">暂无运行中的实例</td>
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
              <span :class="statusClass(inst.status)">
                <span class="status-dot" aria-hidden="true" />
                <span>{{ statusText(inst.status) }}</span>
              </span>
            </td>
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
              <div :class="{ 'expire-warning': isExpiringSoon(inst.expire_at) }">
                <div>{{ formatExpire(inst.expire_at) }}</div>
                <div class="countdown">剩余 {{ expireCountdown(inst.expire_at) }}</div>
              </div>
            </td>
            <td>
              <div class="ops">
                <button
                  class="op-btn"
                  :disabled="inst.status !== 'running'"
                  @click="handleAction('stop', inst)"
                >停止</button>
                <button
                  class="op-btn"
                  :disabled="inst.status === 'running'"
                  @click="handleAction('restart', inst)"
                >重启</button>
                <button
                  class="op-btn"
                  @click="handleAction('renew', inst)"
                >续期</button>
                <button
                  class="op-btn"
                  @click="handleAction('rebuild', inst)"
                >变更配置</button>
                <button
                  class="op-btn"
                  @click="handleAction('logs', inst)"
                >日志</button>
                <button
                  class="op-btn danger"
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
import type { Instance } from '@/stores/cluster'
import { formatExpire, expireCountdown } from '@/shared/utils/format'
import { copyToClipboard } from '@/shared/utils/clipboard'
import { useToastStore } from '@/stores/toast'

const props = defineProps<{
  instances: Instance[]
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
  return 'status-error'
}

function statusText(status: string): string {
  if (status === 'running') return '运行'
  if (status === 'stopped') return '停止'
  return '异常'
}

function togglePassword(idx: number) {
  if (passwordVisible.has(idx)) {
    passwordVisible.delete(idx)
  } else {
    passwordVisible.add(idx)
  }
}

function isExpiringSoon(expireAt?: string | null): boolean {
  if (!expireAt) return false
  const diff = new Date(expireAt).getTime() - Date.now()
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
.status-running,
.status-stopped,
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

/* SSH cell */
.ssh-cell {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  flex-wrap: wrap;
}

.ssh-cmd {
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

/* Expire warning */
.expire-warning {
  color: var(--color-danger);
}

.expire-warning .countdown {
  font-weight: var(--font-weight-medium);
}

.countdown {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: 2px;
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
