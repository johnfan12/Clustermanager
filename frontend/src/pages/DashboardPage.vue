<template>
  <div class="dashboard">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <h1 class="header-title">GPU 集群管理</h1>
        <div class="header-sub">集群总览与实例快照</div>
      </div>
      <div class="header-right">
        <button class="action-btn primary" @click="openCreateModal">创建实例</button>
        <span class="header-user">用户：{{ authStore.username || '-' }}</span>
        <button class="action-btn" @click="handleLogout">退出</button>
      </div>
    </header>

    <!-- Content -->
    <div class="dashboard-container">
      <!-- Loading overlay -->
      <LoadingState v-if="initialLoading" text="加载集群数据..." />

      <template v-else>
        <!-- Cluster Overview Section -->
        <ClusterOverview
          :nodes="clusterStore.nodes"
          :summary="clusterStore.summary"
          :current-node-id="authStore.currentNodeId"
          :token="authStore.token"
        />

        <!-- My Instances Section -->
        <MyInstances
          :instances="clusterStore.instances"
          :pending-ssh-instances="pendingSshInstances"
          @action="handleInstanceAction"
        />

        <!-- Admin Panel (admin only) -->
        <AdminPanel
          v-if="authStore.user?.is_admin"
          :nodes="clusterStore.nodes"
          :is-admin="true"
        />
      </template>
    </div>

    <!-- Create Instance Modal -->
    <AppModal
      v-model:visible="modals.create"
      title="创建实例"
      size="md"
    >
      <form class="form" @submit.prevent="handleCreate">
        <div class="field">
          <label>目标节点</label>
          <select v-model="createForm.nodeId" required>
            <option value="" disabled>选择节点</option>
            <option
              v-for="node in availableNodes"
              :key="node.node_id"
              :value="node.node_id"
            >
              {{ node.name }} (空闲 GPU: {{ node.gpu_free }})
            </option>
          </select>
        </div>
        <div class="field">
          <label>GPU 数量</label>
          <select v-model="createForm.numGpus" required>
            <option :value="0">0 (纯 CPU)</option>
            <option :value="1">1 张</option>
            <option :value="2">2 张</option>
            <option :value="4">4 张</option>
            <option :value="8">8 张</option>
          </select>
        </div>
        <div class="field">
          <label>内存 (GB)</label>
          <select v-model="createForm.memoryGb" required>
            <option :value="8">8 GB</option>
            <option :value="16">16 GB</option>
            <option :value="32">32 GB</option>
            <option :value="64">64 GB</option>
            <option :value="128">128 GB</option>
          </select>
        </div>
        <div class="field">
          <label>镜像</label>
          <select v-model="createForm.image" required>
            <option value="pytorch">PyTorch 2.3 (CUDA 12.1)</option>
            <option value="pytorch_old">PyTorch 2.1 (CUDA 11.8)</option>
            <option value="tensorflow">TensorFlow 2.15</option>
            <option value="base">Ubuntu 22.04 Base</option>
          </select>
        </div>
        <div class="field">
          <label>到期时间</label>
          <select v-model="createForm.expireHours" required>
            <option :value="24">1 天</option>
            <option :value="48">2 天</option>
            <option :value="72">3 天</option>
            <option :value="96">4 天</option>
            <option :value="120">5 天</option>
            <option :value="144">6 天</option>
            <option :value="168" selected>7 天</option>
          </select>
        </div>
        <div class="form-hint">
          到期时间按天选择（1-7天）。实例到期后会自动停止；临近到期可续期。
        </div>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.create = false">取消</AppButton>
        <AppButton
          variant="primary"
          :loading="loading.create"
          @click="handleCreate"
        >
          创建实例
        </AppButton>
      </template>
    </AppModal>

    <!-- Renew Modal -->
    <AppModal
      v-model:visible="modals.renew"
      title="实例续期"
      size="sm"
    >
      <form class="form" @submit.prevent="handleRenew">
        <div class="form-hint">
          为实例 <strong>{{ selectedInstance?.container_name }}</strong> 续期
        </div>
        <div class="field">
          <label>续期天数</label>
          <select v-model="renewForm.days" required>
            <option :value="1">1 天</option>
            <option :value="2">2 天</option>
            <option :value="3">3 天</option>
            <option :value="4">4 天</option>
            <option :value="5">5 天</option>
            <option :value="6">6 天</option>
            <option :value="7">7 天</option>
          </select>
        </div>
        <div class="form-hint">
          可续期 1-7 天；仅在实例剩余时间少于 7 天时可续期。
        </div>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.renew = false">取消</AppButton>
        <AppButton
          variant="primary"
          :loading="loading.renew"
          @click="handleRenew"
        >
          确认续期
        </AppButton>
      </template>
    </AppModal>

    <!-- Rebuild Modal -->
    <AppModal
      v-model:visible="modals.rebuild"
      title="变更配置"
      size="md"
    >
      <form class="form" @submit.prevent="handleRebuild">
        <div class="form-hint">
          修改实例 <strong>{{ selectedInstance?.container_name }}</strong> 配置
        </div>
        <div class="field">
          <label>GPU 数量</label>
          <select v-model="rebuildForm.numGpus" required>
            <option :value="0">0 (纯 CPU)</option>
            <option :value="1">1 张</option>
            <option :value="2">2 张</option>
            <option :value="4">4 张</option>
            <option :value="8">8 张</option>
          </select>
        </div>
        <div class="field">
          <label>内存 (GB)</label>
          <select v-model="rebuildForm.memoryGb" required>
            <option :value="8">8 GB</option>
            <option :value="16">16 GB</option>
            <option :value="32">32 GB</option>
            <option :value="64">64 GB</option>
            <option :value="128">128 GB</option>
          </select>
        </div>
        <div class="form-hint warning">
          修改后会先备份数据，再按新配置重建实例。请确保已保存重要数据。
        </div>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.rebuild = false">取消</AppButton>
        <AppButton
          variant="primary"
          :loading="loading.rebuild"
          @click="handleRebuild"
        >
          保存并重建
        </AppButton>
      </template>
    </AppModal>

    <!-- Delete Modal -->
    <AppModal
      v-model:visible="modals.delete"
      title="确认删除实例"
      size="sm"
    >
      <form class="form" @submit.prevent="handleDelete">
        <div class="danger-panel">
          此操作会删除实例、容器及其关联记录。请输入实例名称以确认删除。
        </div>
        <div class="field">
          <label>实例名称</label>
          <code class="instance-name">{{ selectedInstance?.container_name }}</code>
        </div>
        <div class="field">
          <label>确认输入</label>
          <input
            v-model="deleteConfirmName"
            type="text"
            placeholder="请输入上方实例名称"
            autocomplete="off"
          />
        </div>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.delete = false">取消</AppButton>
        <AppButton
          variant="danger"
          :loading="loading.delete"
          :disabled="deleteConfirmName !== selectedInstance?.container_name"
          @click="handleDelete"
        >
          确认删除
        </AppButton>
      </template>
    </AppModal>

    <!-- Logs Modal -->
    <AppModal
      v-model:visible="modals.logs"
      :title="`日志 - ${selectedInstance?.container_name || ''}`"
      size="lg"
    >
      <div class="terminal">
        <pre>{{ logsContent }}</pre>
      </div>
      <template #footer>
        <AppButton variant="secondary" @click="modals.logs = false">关闭</AppButton>
        <AppButton variant="primary" @click="refreshLogs">刷新</AppButton>
      </template>
    </AppModal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useClusterStore, type Instance, type NodeStatus } from '@/stores/cluster'
import { useToastStore } from '@/stores/toast'
import LoadingState from '@/components/LoadingState.vue'
import AppModal from '@/components/AppModal.vue'
import AppButton from '@/components/AppButton.vue'
import ClusterOverview from '@/features/ClusterOverview.vue'
import MyInstances from '@/features/MyInstances.vue'
import AdminPanel from '@/features/AdminPanel.vue'

const router = useRouter()
const authStore = useAuthStore()
const clusterStore = useClusterStore()
const toast = useToastStore()

const initialLoading = ref(true)

// Modal states
const modals = reactive({
  create: false,
  renew: false,
  rebuild: false,
  delete: false,
  logs: false
})

// Loading states
const loading = reactive({
  create: false,
  renew: false,
  rebuild: false,
  delete: false,
  logs: false
})

// Selected instance for operations
const selectedInstance = ref<Instance | null>(null)

// Form data
const createForm = reactive({
  nodeId: '',
  numGpus: 1,
  memoryGb: 32,
  image: 'pytorch',
  expireHours: 168
})

const renewForm = reactive({
  days: 1
})

const rebuildForm = reactive({
  numGpus: 1,
  memoryGb: 32
})

const deleteConfirmName = ref('')
const logsContent = ref('')

// SSH polling state
const pendingSshInstances = ref<Set<string>>(new Set())
let sshPollTimer: ReturnType<typeof setInterval> | null = null

// Computed
const availableNodes = computed(() => {
  return clusterStore.nodes.filter((n: NodeStatus) => n.online && n.gpu_free > 0)
})

// Actions
function handleLogout() {
  clusterStore.stopAutoRefresh()
  authStore.logout()
  router.push({ name: 'Login' })
}

function openCreateModal() {
  if (availableNodes.value.length === 0) {
    toast.error('当前没有可用的节点')
    return
  }
  createForm.nodeId = availableNodes.value[0]?.node_id || ''
  modals.create = true
}

function handleInstanceAction(action: string, instance: Instance) {
  selectedInstance.value = instance

  switch (action) {
    case 'stop':
      handleStop(instance)
      break
    case 'restart':
      handleRestart(instance)
      break
    case 'renew':
      renewForm.days = 1
      modals.renew = true
      break
    case 'rebuild':
      rebuildForm.numGpus = instance.gpu_indices?.length || 1
      rebuildForm.memoryGb = instance.memory_gb || 32
      modals.rebuild = true
      break
    case 'delete':
      deleteConfirmName.value = ''
      modals.delete = true
      break
    case 'logs':
      openLogs(instance)
      break
  }
}

async function handleCreate() {
  if (!createForm.nodeId) {
    toast.error('请选择目标节点')
    return
  }

  loading.create = true
  try {
    const result = await clusterStore.createInstance(createForm.nodeId, {
      num_gpus: createForm.numGpus,
      memory_gb: createForm.memoryGb,
      image: createForm.image,
      expire_hours: createForm.expireHours
    })
    toast.success('实例创建成功')
    modals.create = false
    await clusterStore.fetchAll()
    // Start SSH polling for new instance
    if (result.id) {
      const instanceKey = `${createForm.nodeId}:${result.id}`
      pendingSshInstances.value.add(instanceKey)
      startSshPolling()
    }
  } catch (e: any) {
    toast.error(e.message || '实例创建失败')
  } finally {
    loading.create = false
  }
}

async function handleStop(instance: Instance) {
  try {
    await clusterStore.stopInstance(instance.node_id, Number(instance.id))
    toast.success('实例已停止')
    await clusterStore.fetchAll()
  } catch (e: any) {
    toast.error(e.message || '停止失败')
  }
}

async function handleRestart(instance: Instance) {
  try {
    await clusterStore.restartInstance(instance.node_id, Number(instance.id))
    toast.success('实例已重启')
    await clusterStore.fetchAll()
  } catch (e: any) {
    toast.error(e.message || '重启失败')
  }
}

async function handleRenew() {
  if (!selectedInstance.value) return

  loading.renew = true
  try {
    await clusterStore.renewInstance(
      selectedInstance.value.node_id,
      Number(selectedInstance.value.id),
      renewForm.days
    )
    toast.success(`实例已续期 ${renewForm.days} 天`)
    modals.renew = false
    await clusterStore.fetchAll()
  } catch (e: any) {
    toast.error(e.message || '续期失败')
  } finally {
    loading.renew = false
  }
}

async function handleRebuild() {
  if (!selectedInstance.value) return

  loading.rebuild = true
  try {
    await clusterStore.rebuildInstance(
      selectedInstance.value.node_id,
      Number(selectedInstance.value.id),
      {
        num_gpus: rebuildForm.numGpus,
        memory_gb: rebuildForm.memoryGb
      }
    )
    toast.success('实例已按新配置重建')
    modals.rebuild = false
    await clusterStore.fetchAll()
  } catch (e: any) {
    toast.error(e.message || '配置变更失败')
  } finally {
    loading.rebuild = false
  }
}

async function handleDelete() {
  if (!selectedInstance.value) return

  loading.delete = true
  try {
    await clusterStore.deleteInstance(
      selectedInstance.value.node_id,
      Number(selectedInstance.value.id)
    )
    toast.success('实例已删除')
    modals.delete = false
    await clusterStore.fetchAll()
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  } finally {
    loading.delete = false
  }
}

async function openLogs(instance: Instance) {
  selectedInstance.value = instance
  modals.logs = true
  await refreshLogs()
}

async function refreshLogs() {
  if (!selectedInstance.value) return

  loading.logs = true
  try {
    const logs = await clusterStore.getInstanceLogs(
      selectedInstance.value.node_id,
      Number(selectedInstance.value.id)
    )
    logsContent.value = logs
  } catch (e: any) {
    toast.error(e.message || '获取日志失败')
    logsContent.value = '无法获取日志'
  } finally {
    loading.logs = false
  }
}

onMounted(async () => {
  try {
    await clusterStore.fetchAll()
  } catch {
    toast.error('数据加载失败，请重新登录')
    handleLogout()
    return
  } finally {
    initialLoading.value = false
  }
  clusterStore.startAutoRefresh()
})

function startSshPolling() {
  if (sshPollTimer) return
  sshPollTimer = setInterval(async () => {
    if (pendingSshInstances.value.size === 0) {
      stopSshPolling()
      return
    }
    await clusterStore.fetchAll()
    // Check if any pending instances now have SSH access
    const readyInstances: string[] = []
    pendingSshInstances.value.forEach((key) => {
      const [nodeId, instanceId] = key.split(':')
      const instance = clusterStore.instances.find(
        (i) => i.node_id === nodeId && String(i.id) === instanceId
      )
      if (instance?.vps_access?.ssh_cmd) {
        readyInstances.push(instance.container_name)
        pendingSshInstances.value.delete(key)
      }
    })
    if (readyInstances.length > 0) {
      toast.success(`实例 ${readyInstances.join(', ')} 的 SSH 已就绪`)
    }
  }, 5000) // Poll every 5 seconds
}

function stopSshPolling() {
  if (sshPollTimer) {
    clearInterval(sshPollTimer)
    sshPollTimer = null
  }
}

onUnmounted(() => {
  clusterStore.stopAutoRefresh()
  stopSshPolling()
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
}

.action-btn:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-alt);
}

.action-btn.primary {
  background: var(--color-primary);
  color: #fff;
  border-color: var(--color-primary);
}

.action-btn.primary:hover {
  background: var(--color-primary-hover);
}

/* ── Container ── */
.dashboard-container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 16px 24px;
  width: 100%;
  flex: 1;
}

/* ── Forms ── */
.form {
  display: grid;
  gap: 16px;
}

.field {
  display: grid;
  gap: 6px;
}

.field label {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
}

.field input,
.field select {
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-base);
  background: var(--color-surface);
  color: var(--color-text);
}

.field input:focus,
.field select:focus {
  outline: none;
  border-color: var(--color-primary);
}

.form-hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.form-hint.warning {
  color: var(--color-warning);
  background: var(--color-warning-bg);
  padding: 10px 12px;
  border-radius: var(--radius-sm);
}

/* ── Danger Panel ── */
.danger-panel {
  padding: 12px;
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-sm);
  background: var(--color-danger-bg);
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

.instance-name {
  display: block;
  padding: 8px 12px;
  background: var(--color-surface-alt);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
}

/* ── Terminal ── */
.terminal {
  background: #0d1117;
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.terminal pre {
  padding: 16px;
  margin: 0;
  color: #3fb950;
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
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
  .dashboard-container {
    padding: 16px;
  }
}
</style>
