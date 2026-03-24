<template>
  <section class="section">
    <div class="section-header">
      <h2>管理员面板</h2>
      <div class="header-actions">
        <select v-model="selectedNodeId" class="node-select">
          <option value="">选择节点</option>
          <option v-for="node in nodes" :key="node.node_id" :value="node.node_id">
            {{ node.name }}
          </option>
        </select>
        <button class="refresh-btn" @click="loadAdminData">刷新</button>
      </div>
    </div>

    <!-- Users Section -->
    <div class="admin-section">
      <h3 class="section-subtitle">用户列表</h3>
      <div v-if="users.length === 0" class="empty-sub">暂无用户数据</div>
      <div v-else class="admin-list">
        <div v-for="user in users" :key="user.username" class="admin-item">
          <div class="item-header">
            <strong>{{ user.username }}</strong>
            <span v-if="user.is_admin" class="admin-badge">管理员</span>
          </div>
          <div class="item-meta">{{ user.email }}</div>
          <div class="item-stats">
            运行中 GPU {{ user.used_gpu }} ·
            内存 {{ user.used_memory_gb }}G ·
            实例 {{ user.used_instances }} ·
            卡时 {{ formatGpuHours(user.gpu_hours_used) }}/{{ formatGpuHours(user.gpu_hours_quota) }}
          </div>
          <div class="item-actions">
            <button class="action-link" @click="openQuotaModal(user)">修改卡时额度</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Instances Section -->
    <div class="admin-section">
      <h3 class="section-subtitle">节点实例</h3>
      <div v-if="!selectedNodeId" class="empty-sub">请选择要管理的节点以查看实例</div>
      <div v-else-if="allInstances.length === 0" class="empty-sub">暂无实例数据</div>
        <div v-else class="admin-list">
          <div v-for="inst in allInstances" :key="`${inst.node_id}-${String(inst.id)}`" class="admin-item">
            <div class="item-header">
              <div>
                <strong>{{ instanceLabel(inst) }}</strong>
                <div v-if="showTechnicalName(inst)" class="item-meta technical-name">
                  {{ inst.container_name }}
                </div>
              </div>
              <span :class="['status-badge', inst.status]">{{ statusText(inst.status) }}</span>
            </div>
          <div class="item-meta">
            {{ inst.username || '-' }} ·
            GPU {{ inst.gpu_indices?.length || 0 }} 张 ·
            {{ inst.memory_gb }}G 内存
          </div>
          <div class="item-actions">
            <button class="action-link danger" @click="confirmForceDelete(inst)">强制删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Quota Modal -->
    <AppModal v-model:visible="modals.quota" title="修改用户配额" size="sm">
      <form class="form" @submit.prevent="handleUpdateQuota">
        <div class="form-hint">
          修改用户 <strong>{{ selectedUser?.username }}</strong> 的配额
        </div>
        <div class="field">
          <label>卡时额度</label>
          <input v-model.number="quotaForm.gpuHours" type="number" min="0" step="0.1" required />
        </div>
        <div class="form-hint">卡时由聚合端统一结算；节点离线期间不继续计费。</div>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.quota = false">取消</AppButton>
        <AppButton variant="primary" :loading="loading.quota" @click="handleUpdateQuota">
          保存
        </AppButton>
      </template>
    </AppModal>

    <!-- Delete Modal -->
    <AppModal v-model:visible="modals.delete" title="确认强制删除" size="sm">
      <div class="danger-panel">
        <p>确认强制删除实例 <strong>{{ instanceLabel(selectedInstance) }}</strong> 吗？</p>
        <p v-if="showTechnicalName(selectedInstance)" class="hint">
          系统容器名：<code>{{ selectedInstance?.container_name }}</code>
        </p>
        <p class="hint">此操作会立即删除该实例，数据将丢失且无法恢复！</p>
      </div>
      <template #footer>
        <AppButton variant="secondary" @click="modals.delete = false">取消</AppButton>
        <AppButton variant="danger" :loading="loading.delete" @click="handleForceDelete">
          确认删除
        </AppButton>
      </template>
    </AppModal>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useClusterStore, type NodeStatus, type AdminUser, type AdminInstance } from '@/stores/cluster'
import { useToastStore } from '@/stores/toast'
import AppModal from '@/components/AppModal.vue'
import AppButton from '@/components/AppButton.vue'

const props = defineProps<{
  nodes: NodeStatus[]
  isAdmin: boolean
}>()

const clusterStore = useClusterStore()
const toast = useToastStore()

const selectedNodeId = ref('')
const users = ref<AdminUser[]>([])
const allInstances = ref<AdminInstance[]>([])

const modals = reactive({
  quota: false,
  delete: false
})

const loading = reactive({
  quota: false,
  delete: false
})

const selectedUser = ref<AdminUser | null>(null)
const selectedInstance = ref<AdminInstance | null>(null)

const quotaForm = reactive({
  gpuHours: 100
})

function formatGpuHours(value: number): string {
  return Number.isFinite(value) ? Number(value).toFixed(2) : '0.00'
}

function statusText(status: string): string {
  if (status === 'running') return '运行中'
  if (status === 'stopped') return '已停止'
  return '异常'
}

function instanceLabel(instance: AdminInstance | null): string {
  return String(instance?.display_name || instance?.container_name || '—')
}

function showTechnicalName(instance: AdminInstance | null): boolean {
  return Boolean(instance?.display_name && instance.display_name !== instance.container_name)
}

async function loadAdminData() {
  if (!props.isAdmin) return

  try {
    const [usersData, instancesData] = await Promise.all([
      clusterStore.fetchAdminUsers(),
      selectedNodeId.value
        ? clusterStore.fetchAdminInstances(selectedNodeId.value)
        : Promise.resolve([])
    ])
    users.value = usersData
    allInstances.value = instancesData
  } catch (e: any) {
    toast.error(e.message || '加载管理数据失败')
  }
}

function openQuotaModal(user: AdminUser) {
  selectedUser.value = user
  quotaForm.gpuHours = user.gpu_hours_quota ?? 100
  modals.quota = true
}

async function handleUpdateQuota() {
  if (!selectedUser.value) return

  loading.quota = true
  try {
    await clusterStore.updateUserQuota(selectedUser.value.username, {
      gpu_hours_quota: quotaForm.gpuHours
    })
    toast.success('用户配额已更新')
    modals.quota = false
    await loadAdminData()
  } catch (e: any) {
    toast.error(e.message || '配额更新失败')
  } finally {
    loading.quota = false
  }
}

function confirmForceDelete(inst: AdminInstance) {
  selectedInstance.value = inst
  modals.delete = true
}

async function handleForceDelete() {
  if (!selectedNodeId.value || !selectedInstance.value) return

  loading.delete = true
  try {
    await clusterStore.forceDeleteInstance(selectedNodeId.value, Number(selectedInstance.value.id))
    toast.success('实例已强制删除')
    modals.delete = false
    await loadAdminData()
    await clusterStore.fetchAll()
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  } finally {
    loading.delete = false
  }
}

watch(selectedNodeId, () => {
  void loadAdminData()
})

onMounted(() => {
  void loadAdminData()
})
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

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.node-select {
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  background: var(--color-surface);
}

.refresh-btn {
  padding: 6px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  background: var(--color-surface-alt);
  color: var(--color-text);
  cursor: pointer;
}

.refresh-btn:hover {
  border-color: var(--color-primary);
}

.empty-state {
  padding: 40px 20px;
  text-align: center;
  color: var(--color-text-muted);
}

.admin-section {
  padding: 16px;
  border-bottom: 1px solid var(--color-border);
}

.admin-section:last-child {
  border-bottom: none;
}

.section-subtitle {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 12px;
}

.empty-sub {
  padding: 20px;
  text-align: center;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.admin-list {
  display: grid;
  gap: 10px;
}

.admin-item {
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface-alt);
}

.item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.item-header strong {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.admin-badge {
  padding: 2px 8px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: var(--font-size-xs);
  border-radius: var(--radius-sm);
}

.item-meta {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin-bottom: 4px;
}

.technical-name {
  margin-top: 2px;
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
}

.item-stats {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-bottom: 8px;
}

.item-actions {
  display: flex;
  gap: 12px;
}

.action-link {
  padding: 0;
  background: none;
  border: none;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.action-link:hover {
  text-decoration: underline;
}

.action-link.danger {
  color: var(--color-danger);
}

.status-badge {
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.status-badge.running {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.status-badge.stopped {
  background: var(--color-surface);
  color: var(--color-text-muted);
}

.status-badge.error {
  background: var(--color-danger-bg);
  color: var(--color-danger);
}

/* Form styles */
.form {
  display: grid;
  gap: 16px;
}

.form-hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
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

.field input {
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-base);
}

.field input:focus {
  outline: none;
  border-color: var(--color-primary);
}

/* Danger panel */
.danger-panel {
  padding: 16px;
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-sm);
  background: var(--color-danger-bg);
}

.danger-panel p {
  margin: 0 0 8px;
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

.danger-panel p:last-child {
  margin-bottom: 0;
}

.danger-panel .hint {
  font-size: var(--font-size-xs);
  opacity: 0.8;
}
</style>
