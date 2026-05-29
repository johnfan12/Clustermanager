<template>
  <div class="dashboard">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <h1 class="header-title">{{ tunnelStore.config.app_display_name }}</h1>
        <div class="header-sub">SSH 隧道管理控制台</div>
      </div>
      <div class="header-right">
        <span class="header-user">{{ authStore.username || '-' }}{{ authStore.isAdmin ? ' · 管理员' : '' }}</span>
        <button class="action-btn" @click="handleRefresh">刷新</button>
        <button class="action-btn" @click="handleLogout">退出</button>
      </div>
    </header>

    <!-- Content -->
    <div class="dashboard-body">
      <!-- Loading overlay -->
      <LoadingState v-if="initialLoading" text="加载节点数据..." />
      <template v-else>
        <!-- Node selector -->
        <section class="section">
          <div class="section-header">
            <h2>节点</h2>
            <span class="section-summary">{{ tunnelStore.nodes.length }} 个节点</span>
          </div>
          <div class="node-list">
            <button
              :class="['node-btn', { active: tunnelStore.selectedNode === 'all' }]"
              type="button"
              @click="tunnelStore.selectNode('all')"
            >
              全部节点
            </button>
            <button
              v-for="node in tunnelStore.nodes"
              :key="node.id"
              :class="['node-btn', { active: tunnelStore.selectedNode === node.id }]"
              type="button"
              @click="tunnelStore.selectNode(node.id)"
            >
              {{ node.name }}
            </button>
          </div>
        </section>

        <!-- SSH Access Form -->
        <section class="section">
          <div class="section-header">
            <h2>生成 SSH 命令</h2>
            <span v-if="formNotice" :class="['notice', { error: formNoticeIsError }]">{{ formNotice }}</span>
          </div>
          <form class="create-grid" @submit.prevent="handleCreateAccess">
            <div class="field">
              <label for="create-node">节点</label>
              <select id="create-node" v-model="createNodeId" required>
                <option value="" disabled>选择节点</option>
                <option
                  v-for="node in tunnelStore.nodes"
                  :key="node.id"
                  :value="node.id"
                >
                  {{ node.name }}
                </option>
              </select>
            </div>
            <div class="field">
              <label for="ssh-userid">User ID</label>
              <input
                id="ssh-userid"
                v-model.trim="sshUserId"
                type="text"
                maxlength="64"
                required
                placeholder="输入用户名"
              />
            </div>
            <div class="field field-btn">
              <AppButton variant="primary" type="submit" :loading="createLoading">
                生成
              </AppButton>
            </div>
          </form>
        </section>

        <!-- SSH Commands Table -->
        <section class="section">
          <div class="section-header">
            <h2>SSH 命令</h2>
            <span v-if="tableNotice" :class="['notice', { error: tableNoticeIsError }]">{{ tableNotice }}</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>节点</th>
                  <th>名称</th>
                  <th>SSH 命令</th>
                  <th>状态</th>
                  <th>用户</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="tunnelStore.filteredTunnels.length === 0">
                  <td colspan="6" class="empty-cell">输入 User ID 后生成 SSH 命令</td>
                </tr>
                <tr
                  v-for="tunnel in tunnelStore.filteredTunnels"
                  :key="tunnel.saved_key || `${tunnel.node_id}-${tunnel.owner}`"
                >
                  <td>{{ tunnel.node_name || tunnel.node_id }}</td>
                  <td>{{ tunnel.name }}</td>
                  <td>
                    <div class="ssh-cell">
                      <code class="ssh-cmd">{{ sshCommand(tunnel) }}</code>
                      <button class="copy-btn" @click="handleCopy(sshCommand(tunnel))">📋</button>
                    </div>
                  </td>
                  <td>
                    <span
                      :class="['status-badge', tunnel.status === 'error' ? 'error' : 'running']"
                      :title="tunnel.error || ''"
                    >
                      {{ tunnel.status }}
                    </span>
                  </td>
                  <td>{{ tunnel.owner || '' }}</td>
                  <td>
                    <div class="ops">
                      <button
                        class="op-btn"
                        @click="handleCopy(sshCommand(tunnel))"
                      >
                        复制
                      </button>
                      <button
                        class="op-btn danger"
                        @click="handleHide(tunnel)"
                      >
                        隐藏
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useTunnelStore, type SshAccess } from '@/stores/tunnel'
import { useToastStore } from '@/stores/toast'
import { copyToClipboard } from '@/shared/utils/clipboard'
import LoadingState from '@/components/LoadingState.vue'
import AppButton from '@/components/AppButton.vue'

const router = useRouter()
const authStore = useAuthStore()
const tunnelStore = useTunnelStore()
const toast = useToastStore()

const initialLoading = ref(true)
const createLoading = ref(false)
const createNodeId = ref('')
const sshUserId = ref('')

const formNotice = ref('')
const formNoticeIsError = ref(false)
const tableNotice = ref('')
const tableNoticeIsError = ref(false)

function sshCommand(tunnel: SshAccess): string {
  return tunnel.ssh_command || `ssh -p ${tunnel.remote_port} ${tunnel.owner}@${tunnel.public_host}`
}

async function handleCopy(text: string) {
  const ok = await copyToClipboard(text)
  if (ok) {
    toast.success('已复制')
  } else {
    toast.error('复制失败')
  }
}

function handleHide(tunnel: SshAccess) {
  const key = tunnel.saved_key || tunnelStore.accessKey(tunnel.node_id, tunnel.owner)
  tunnelStore.forgetAccess(key)
}

async function handleCreateAccess() {
  formNotice.value = ''
  formNoticeIsError.value = false

  if (!createNodeId.value || !sshUserId.value) {
    formNotice.value = '请选择节点并输入用户名'
    formNoticeIsError.value = true
    return
  }

  createLoading.value = true
  try {
    const access = await tunnelStore.fetchSshAccess(createNodeId.value, sshUserId.value)
    if (!access) {
      throw new Error('节点未返回 SSH 命令')
    }
    tunnelStore.rememberAccess(createNodeId.value, sshUserId.value)
    const errors = await tunnelStore.restoreSavedAccesses()
    if (errors.length) {
      tableNotice.value = errors.join('；')
      tableNoticeIsError.value = true
    } else {
      tableNotice.value = ''
      tableNoticeIsError.value = false
    }
    formNotice.value = '已生成 SSH 命令'
    formNoticeIsError.value = false
  } catch (e: unknown) {
    formNotice.value = (e as Error).message
    formNoticeIsError.value = true
  } finally {
    createLoading.value = false
  }
}

async function handleRefresh() {
  try {
    await loadData()
    toast.success('已刷新')
  } catch (e: unknown) {
    toast.error((e as Error).message || '刷新失败')
  }
}

function handleLogout() {
  authStore.logout()
  router.push({ name: 'Login' })
}

async function loadData() {
  await tunnelStore.fetchNodes()
  const errors = await tunnelStore.restoreSavedAccesses()
  tableNotice.value = errors.length ? errors.join('；') : ''
  tableNoticeIsError.value = errors.length > 0

  // Set default selected node for create form
  if (!createNodeId.value && tunnelStore.nodes.length > 0) {
    createNodeId.value = tunnelStore.nodes[0].id
  }
  // Set default userId if not set
  if (!sshUserId.value && authStore.username) {
    sshUserId.value = authStore.username
  }
}

onMounted(async () => {
  try {
    await tunnelStore.fetchConfig()
    await loadData()
  } catch (e: unknown) {
    toast.error((e as Error).message || '数据加载失败')
  } finally {
    initialLoading.value = false
  }
})
</script>

<style scoped>
.dashboard {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* ── Header ── */
.app-header {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  padding: 0 24px;
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.header-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.header-sub {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  margin-top: 1px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.header-user {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  font-size: var(--font-size-sm);
}

.action-btn {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  transition: all var(--transition-fast);
  cursor: pointer;
}

.action-btn:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-alt);
}

/* ── Body ── */
.dashboard-body {
  max-width: 1280px;
  margin: 0 auto;
  padding: 16px 24px;
  width: 100%;
  flex: 1;
  display: grid;
  gap: 16px;
  align-content: start;
}

/* ── Sections ── */
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
}

/* ── Node List ── */
.node-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 16px;
}

.node-btn {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border: 1px solid var(--color-border-subtle);
  background: var(--color-surface);
  color: var(--color-text);
  transition: all var(--transition-fast);
  cursor: pointer;
}

.node-btn:hover:not(.active) {
  border-color: var(--color-border-strong);
  background: var(--color-surface-alt);
}

.node-btn.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: #fff;
}

/* ── Create Form ── */
.create-grid {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) minmax(180px, 1.15fr) auto;
  align-items: end;
  gap: 12px;
  padding: 16px;
}

.field label {
  display: block;
  margin-bottom: 4px;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
}

.field input,
.field select {
  width: 100%;
  padding: 7px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: var(--font-size-base);
  transition: border-color var(--transition-fast);
}

.field input::placeholder { color: var(--color-text-placeholder); }

.field input:focus,
.field select:focus {
  border-color: var(--color-primary);
  outline: none;
}

.field-btn {
  display: flex;
  align-items: flex-end;
}

/* ── Table ── */
.table-wrap { overflow-x: auto; }

table { width: 100%; min-width: 820px; }

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

/* ── SSH Cell ── */
.ssh-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
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

/* ── Status Badge ── */
.status-badge {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
}

.status-badge.running {
  border: 1px solid var(--color-success-border);
  background: var(--color-success-bg);
  color: var(--color-success);
}

.status-badge.error {
  border: 1px solid var(--color-danger-border);
  background: var(--color-danger-bg);
  color: var(--color-danger);
}

/* ── Operations ── */
.ops {
  display: flex;
  align-items: center;
  gap: 8px;
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

.op-btn:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.op-btn.danger {
  color: var(--color-danger);
  border-color: var(--color-danger-border);
}

.op-btn.danger:hover {
  background: var(--color-danger-bg);
  border-color: var(--color-danger);
}

/* ── Notice ── */
.notice {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.notice.error {
  color: var(--color-danger);
}

/* ── Responsive ── */
@media (max-width: 860px) {
  .create-grid {
    grid-template-columns: 1fr 1fr;
  }
  .create-grid .field-btn {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .app-header {
    flex-direction: column;
    align-items: flex-start;
    padding: 12px 16px;
  }
  .header-right {
    justify-content: flex-start;
  }
  .dashboard-body {
    padding: 16px;
  }
  .create-grid {
    grid-template-columns: 1fr;
  }
}
</style>
