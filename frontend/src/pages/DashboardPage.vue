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
        <button class="action-btn" @click="openSshKeysModal">SSH 公钥</button>
        <span class="header-user">用户：{{ authStore.username || '-' }}</span>
        <span class="header-quota">额度：{{ gpuHoursText }}</span>
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
        />

        <!-- My Instances Section -->
        <MyInstances
          :instances="displayInstances"
          :nodes="clusterStore.nodes"
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

    <AppModal
      :visible="createTransitionVisible"
      title="实例创建中"
      size="sm"
      :close-on-backdrop="false"
      :show-close="false"
    >
      <div class="create-transition-window">
        <div class="create-transition-spinner" aria-hidden="true" />
        <div class="create-transition-title">实例创建成功</div>
        <div class="create-transition-text">
          正在准备 SSH 连接，大约需要 10 秒左右。
        </div>
      </div>
    </AppModal>

    <!-- Create Instance Modal -->
    <AppModal
      v-model:visible="modals.create"
      title="创建实例"
      size="md"
    >
      <form class="form" @submit.prevent="createStep === 1 ? handleCreateNext() : handleCreate()">
        <div class="wizard-step">
          步骤 {{ createStep }} / 2
        </div>

        <template v-if="createStep === 1">
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
            <label>镜像</label>
            <select v-model="createForm.image" required>
              <option value="" disabled>选择镜像</option>
              <option
                v-for="(label, key) in availableImages"
                :key="key"
                :value="key"
              >
                {{ label }}
              </option>
            </select>
            <div v-if="!createForm.nodeId" class="field-hint">请先选择节点加载可用镜像</div>
            <div v-else-if="createImagesLoading" class="field-hint">正在加载节点镜像配置...</div>
            <div
              v-else-if="createForm.nodeId && Object.keys(availableImages).length === 0"
              class="field-hint warning-text"
            >
              当前节点未返回可用镜像，请检查该节点 Servermanager 的 IMAGE_* 配置。
            </div>
          </div>
          <div class="field">
            <label>实例名</label>
            <input
              v-model.trim="createForm.displayName"
              type="text"
              maxlength="64"
              placeholder="可选，留空则自动生成系统名"
            />
            <div class="field-hint">
              推荐填写一个易识别的名字；系统容器名仍会由后端自动生成。
            </div>
          </div>
          <div v-if="selectedCreateNode" class="form-hint">
            当前节点：{{ selectedCreateNode.name }}，空闲 GPU {{ selectedCreateNode.gpu_free }} / 总数 {{ selectedCreateNode.gpu_total }}。
          </div>
        </template>

        <template v-else>
          <div class="field">
            <label>GPU 数量</label>
            <select v-model="createForm.numGpus" required>
              <option
                v-for="count in availableGpuOptions"
                :key="count"
                :value="count"
              >
                {{ count === 0 ? '0 (纯 CPU)' : `${count} 张` }}
              </option>
            </select>
          </div>
          <div class="field">
            <label>内存 (GB)</label>
            <select v-model="createForm.memoryGb" required>
              <option
                v-for="size in availableMemoryOptions"
                :key="size"
                :value="size"
              >
                {{ size }} GB
              </option>
            </select>
            <div v-if="clusterStore.metadata?.max_instance_memory_gb" class="field-hint">
              单实例内存上限：{{ clusterStore.metadata.max_instance_memory_gb }} GB
            </div>
            <div
              v-if="clusterStore.metadata?.node_allocatable_memory_gb != null && clusterStore.metadata?.node_memory_used_gb != null"
              class="field-hint"
            >
              节点全局可分配内存：{{ clusterStore.metadata.node_allocatable_memory_gb }} GB，
              已分配：{{ clusterStore.metadata.node_memory_used_gb }} GB，
              剩余：{{ clusterStore.metadata.node_memory_free_gb ?? 0 }} GB
            </div>
            <div v-if="availableMemoryOptions.length === 0" class="field-hint warning-text">
              该节点当前剩余可分配内存不足最小档位（8 GB），请稍后重试或释放资源。
            </div>
          </div>
          <div class="field">
            <label>到期时间（小时）</label>
            <input
              v-model.number="createForm.expireHours"
              type="number"
              min="1"
              max="168"
              step="1"
              required
              placeholder="例如：36"
            />
            <div class="field-hint">
              请输入 1-168 小时；到期后自动关机，实例不会被删除。
            </div>
          </div>
          <div class="form-hint">
            已按节点空闲 GPU 与后端内存配置自动筛选可选项。
          </div>
        </template>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.create = false">取消</AppButton>
        <AppButton
          v-if="createStep === 1"
          variant="primary"
          :disabled="!canProceedCreateStep1"
          @click="handleCreateNext"
        >
          下一步
        </AppButton>
        <AppButton
          v-else
          variant="secondary"
          @click="handleCreatePrev"
        >
          上一步
        </AppButton>
        <AppButton
          v-if="createStep === 2"
          variant="primary"
          :loading="loading.create"
          :disabled="!canSubmitCreate"
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
          为实例 <strong>{{ instanceDisplayName(selectedInstance) }}</strong> 续期
          <span v-if="showTechnicalName(selectedInstance)">（系统名：{{ selectedInstance?.container_name }}）</span>
        </div>
        <div class="field">
          <label>续期时长（小时）</label>
          <input
            v-model.number="renewForm.hours"
            type="number"
            min="1"
            max="168"
            step="1"
            required
            placeholder="例如：12"
          />
        </div>
        <div class="form-hint">
          可续期 1-168 小时；仅在实例剩余时间少于 7 天时可续期。
        </div>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.renew = false">取消</AppButton>
        <AppButton
          variant="primary"
          :loading="loading.renew"
          :disabled="!canSubmitRenew"
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
          修改实例 <strong>{{ instanceDisplayName(selectedInstance) }}</strong> 配置
          <span v-if="showTechnicalName(selectedInstance)">（系统名：{{ selectedInstance?.container_name }}）</span>
        </div>
        <div class="field">
          <label>GPU 数量</label>
          <select v-model="rebuildForm.numGpus" required>
            <option
              v-for="count in rebuildGpuOptions"
              :key="count"
              :value="count"
            >
              {{ count === 0 ? '0 (纯 CPU)' : `${count} 张` }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>内存 (GB)</label>
          <select v-model="rebuildForm.memoryGb" required>
            <option
              v-for="size in rebuildMemoryOptions"
              :key="size"
              :value="size"
            >
              {{ size }} GB
            </option>
          </select>
          <div v-if="rebuildMetadata?.max_instance_memory_gb" class="field-hint">
            单实例内存上限：{{ rebuildMetadata.max_instance_memory_gb }} GB
          </div>
          <div
            v-if="rebuildMetadata?.node_allocatable_memory_gb != null && rebuildMetadata?.node_memory_used_gb != null"
            class="field-hint"
          >
            节点全局可分配内存：{{ rebuildMetadata.node_allocatable_memory_gb }} GB，
            已分配：{{ rebuildMetadata.node_memory_used_gb }} GB，
            剩余：{{ rebuildMetadata.node_memory_free_gb ?? 0 }} GB
          </div>
          <div v-if="rebuildMemoryOptions.length === 0" class="field-hint warning-text">
            该节点当前剩余可分配内存不足最小档位（8 GB），请稍后重试或释放资源。
          </div>
        </div>
        <div class="form-hint warning">
          仅修改内存会原地生效；修改 GPU 会先保存当前环境快照，再按新配置重建实例，完成后默认停机。
        </div>
        <div class="form-hint">
          修改 GPU 时，大多数系统包、npm 包、pip 包和 CLI 状态会跟随快照保留；
          运行中的进程状态不会保留。
        </div>
      </form>
      <template #footer>
        <AppButton variant="secondary" @click="modals.rebuild = false">取消</AppButton>
        <AppButton
          variant="primary"
          :loading="loading.rebuild"
          :disabled="!canSubmitRebuild"
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
          <code class="instance-name">{{ instanceDisplayName(selectedInstance) }}</code>
          <div v-if="showTechnicalName(selectedInstance)" class="field-hint">
            系统容器名：{{ selectedInstance?.container_name }}
          </div>
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
          :disabled="deleteConfirmName !== instanceDisplayName(selectedInstance)"
          @click="handleDelete"
        >
          确认删除
        </AppButton>
      </template>
    </AppModal>

    <!-- Logs Modal -->
    <AppModal
      v-model:visible="modals.logs"
      :title="`日志 - ${instanceDisplayName(selectedInstance)}`"
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

    <AppModal
      v-model:visible="modals.sshKeys"
      title="SSH 公钥管理"
      size="lg"
    >
      <div class="ssh-key-layout">
        <section class="ssh-key-panel">
          <h4>免密登录说明</h4>
          <p>
            1. 先在你的电脑上执行 <code>ssh-keygen -t rsa</code> 生成密钥对。2. 打开生成的
            <code>.pub</code> 公钥文件，例如 <code>~/.ssh/id_rsa.pub</code>。3. 将该文件里的
            <strong>全部内容完整复制</strong> 到下方“公钥”输入框，不要只复制一部分，也不要复制私钥文件。
            4. 保存后，后续新建或重建的实例会自动写入 <code>/root/.ssh/authorized_keys</code>，
            之后即可使用本地私钥免密连接。
          </p>
        </section>

        <section class="ssh-key-panel">
          <h4>生成公钥</h4>
          <div class="ssh-key-help">
            <div>
              <strong>Linux / Mac</strong>
              <pre class="ssh-key-command">ssh-keygen -t rsa</pre>
            </div>
            <div>
              <strong>Windows PowerShell</strong>
              <pre class="ssh-key-command">ssh-keygen -t rsa</pre>
            </div>
          </div>
          <p class="ssh-key-help-text">
            生成后的公钥通常位于 Linux/Mac 的 <code>~/.ssh/id_rsa.pub</code> 或 Windows 的
            <code>C:\Users\用户名\.ssh\id_rsa.pub</code>。
          </p>
        </section>

        <section class="ssh-key-panel">
          <div class="ssh-key-panel-head">
            <h4>添加公钥</h4>
            <span class="ssh-key-count">已配置 {{ sshKeys.length }} / 10 条</span>
          </div>
          <form class="form" @submit.prevent="handleCreateSshKey">
            <div class="field">
              <label>公钥</label>
              <textarea
                v-model.trim="sshKeyForm.publicKey"
                class="ssh-key-textarea"
                rows="4"
                placeholder="请粘贴 ssh-rsa / ssh-ed25519 / ecdsa-sha2-* 公钥"
              />
            </div>
            <div class="field">
              <label>备注</label>
              <input
                v-model.trim="sshKeyForm.remark"
                type="text"
                maxlength="255"
                placeholder="例如：MacBook Pro / 办公网关"
              />
            </div>
            <div class="ssh-key-actions">
              <AppButton
                variant="primary"
                type="submit"
                :loading="loading.sshKeyCreate"
                :disabled="!sshKeyForm.publicKey"
              >
                保存公钥
              </AppButton>
            </div>
          </form>
        </section>

        <section class="ssh-key-panel">
          <div class="ssh-key-panel-head">
            <h4>当前公钥</h4>
            <AppButton variant="secondary" size="sm" :loading="loading.sshKeys" @click="loadSshKeys">
              刷新
            </AppButton>
          </div>
          <div v-if="sshKeys.length === 0" class="ssh-key-empty">
            还没有配置 SSH 公钥。保存后，新建或重建实例即可使用免密登录。
          </div>
          <div v-else class="ssh-key-list">
            <article v-for="key in sshKeys" :key="key.id" class="ssh-key-card">
              <div class="ssh-key-meta">
                <div class="ssh-key-remark">{{ key.remark || '未填写备注' }}</div>
                <div class="ssh-key-fingerprint">{{ key.fingerprint }}</div>
                <div class="ssh-key-created">创建于 {{ formatDateTime(key.created_at) }}</div>
              </div>
              <pre class="ssh-key-preview">{{ key.public_key }}</pre>
              <div class="ssh-key-actions">
                <AppButton
                  variant="danger"
                  size="sm"
                  :loading="loading.sshKeyDeleteId === key.id"
                  @click="handleDeleteSshKey(key.id)"
                >
                  删除
                </AppButton>
              </div>
            </article>
          </div>
        </section>
      </div>
      <template #footer>
        <AppButton variant="secondary" @click="modals.sshKeys = false">关闭</AppButton>
      </template>
    </AppModal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  useClusterStore,
  type Instance,
  type NodeStatus,
  type Metadata,
  type NodeImage,
  type SshKeyItem
} from '@/stores/cluster'
import { useToastStore } from '@/stores/toast'
import { api } from '@/shared/utils/api'
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
const gpuHoursRemaining = ref<number | null>(null)
const createTransitionVisible = ref(false)

const gpuHoursText = computed(() => {
  if (gpuHoursRemaining.value === null) return '加载中...'
  return `${gpuHoursRemaining.value.toFixed(1)} 卡时`
})

// Modal states
const modals = reactive({
  create: false,
  renew: false,
  rebuild: false,
  delete: false,
  logs: false,
  sshKeys: false
})

// Loading states
const loading = reactive({
  create: false,
  renew: false,
  rebuild: false,
  delete: false,
  logs: false,
  sshKeys: false,
  sshKeyCreate: false,
  sshKeyDeleteId: null as number | null
})

// Selected instance for operations
const selectedInstance = ref<Instance | null>(null)

// Form data
const createForm = reactive({
  nodeId: '',
  displayName: '',
  numGpus: 1,
  memoryGb: 16,
  image: '',
  expireHours: 168
})
const createImages = ref<NodeImage[]>([])
const createImagesLoading = ref(false)

const createStep = ref(1)

const renewForm = reactive({
  hours: 24
})

const rebuildForm = reactive({
  numGpus: 1,
  memoryGb: 32
})
const rebuildMetadata = ref<Metadata | null>(null)

const deleteConfirmName = ref('')
const logsContent = ref('')
const sshKeys = ref<SshKeyItem[]>([])
const sshKeyForm = reactive({
  publicKey: '',
  remark: ''
})

// SSH polling state
const pendingSshInstances = ref<Set<string>>(new Set())
const pendingRebuildInstances = ref<Set<string>>(new Set())
let sshPollTimer: ReturnType<typeof setInterval> | null = null
let createTransitionTimer: ReturnType<typeof setTimeout> | null = null
let createNodeLoadToken = 0
const CPU_ONLY_GPU_COUNT = 0

function memoryOptionsForMetadata(metadata: Metadata | null | undefined): number[] {
  const options = metadata?.memory_options_gb
  if (Array.isArray(options) && options.length > 0) {
    return [...options].sort((a, b) => a - b)
  }

  const maxMemory = metadata?.max_instance_memory_gb ?? 128
  return [8, 16, 32, 64, 128].filter((v) => v <= maxMemory)
}

function gpuMemoryLimitForSelection(
  numGpus: number,
  metadata: Metadata | null | undefined,
  gpuTotal: number | undefined
): number | undefined {
  const nodeMemory = metadata?.node_allocatable_memory_gb
  if (numGpus <= CPU_ONLY_GPU_COUNT || typeof nodeMemory !== 'number') return undefined
  if (typeof gpuTotal !== 'number' || gpuTotal <= 0) return undefined
  return (nodeMemory * numGpus) / gpuTotal
}

// Computed
const availableNodes = computed(() => {
  return clusterStore.nodes.filter((n: NodeStatus) => n.online)
})

const selectedCreateNode = computed(() => {
  return clusterStore.nodes.find((n: NodeStatus) => n.node_id === createForm.nodeId) || null
})

const displayInstances = computed(() => {
  return clusterStore.instances.map((instance) => {
    if (!isInstanceRebuilding(instance)) return instance
    return {
      ...instance,
      status: 'rebuilding' as const
    }
  })
})

const serverRebuildingInstanceKeys = computed(() => {
  const keys = new Set<string>()
  clusterStore.instances.forEach((instance) => {
    if (instance.status !== 'rebuilding') return
    const key = instanceOperationKey(instance)
    if (key) {
      keys.add(key)
    }
  })
  return keys
})

function instanceDisplayName(instance: Instance | null | undefined): string {
  return String(instance?.display_name || instance?.container_name || '')
}

function showTechnicalName(instance: Instance | null | undefined): boolean {
  return Boolean(instance?.display_name && instance.display_name !== instance.container_name)
}

function instanceOperationKey(instance: Instance | null | undefined): string {
  if (!instance?.node_id || instance.id == null) return ''
  return `${instance.node_id}:${String(instance.id)}`
}

function isInstanceRebuilding(instance: Instance | null | undefined): boolean {
  if (!instance) return false
  if (instance.status === 'rebuilding') return true
  const key = instanceOperationKey(instance)
  return key !== '' && (
    pendingRebuildInstances.value.has(key)
    || serverRebuildingInstanceKeys.value.has(key)
  )
}

const availableGpuOptions = computed(() => {
  const maxFree = Math.max(0, selectedCreateNode.value?.gpu_free ?? 0)
  return [0, 1, 2, 4, 8].filter((count) => count === 0 || count <= maxFree)
})

const selectedRebuildNode = computed(() => {
  const nodeId = selectedInstance.value?.node_id
  if (!nodeId) return null
  return clusterStore.nodes.find((n: NodeStatus) => n.node_id === nodeId) || null
})

const rebuildGpuOptions = computed(() => {
  const currentGpu = selectedInstance.value?.gpu_indices?.length ?? 0
  const nodeTotal = Math.max(0, selectedRebuildNode.value?.gpu_total ?? 0)
  const maxByFreeAndCurrent = Math.max(0, (selectedRebuildNode.value?.gpu_free ?? 0) + currentGpu)
  const maxByNode = Math.min(nodeTotal, maxByFreeAndCurrent)
  return [0, 1, 2, 4, 8].filter((count) => count === 0 || count <= maxByNode)
})

const availableMemoryOptions = computed(() => {
  const sorted = memoryOptionsForMetadata(clusterStore.metadata)
  const nodeFreeMemory = clusterStore.metadata?.node_memory_free_gb
  if (createForm.numGpus === CPU_ONLY_GPU_COUNT) {
    return sorted.length > 0 ? [sorted[0]] : []
  }
  const gpuMemoryLimit = gpuMemoryLimitForSelection(
    createForm.numGpus,
    clusterStore.metadata,
    selectedCreateNode.value?.gpu_total
  )
  const gpuLimited = typeof gpuMemoryLimit === 'number'
    ? sorted.filter((v) => v <= gpuMemoryLimit)
    : sorted
  if (typeof nodeFreeMemory === 'number') {
    return gpuLimited.filter((v) => v <= nodeFreeMemory)
  }
  return gpuLimited
})

const rebuildMemoryOptions = computed(() => {
  const sorted = memoryOptionsForMetadata(rebuildMetadata.value)
  const nodeFreeMemory = rebuildMetadata.value?.node_memory_free_gb
  const currentMemory = selectedInstance.value?.memory_gb ?? 0
  const effectiveFree = typeof nodeFreeMemory === 'number' ? nodeFreeMemory + currentMemory : undefined

  if (rebuildForm.numGpus === CPU_ONLY_GPU_COUNT) {
    return sorted.length > 0 ? [sorted[0]] : []
  }
  const gpuMemoryLimit = gpuMemoryLimitForSelection(
    rebuildForm.numGpus,
    rebuildMetadata.value,
    selectedRebuildNode.value?.gpu_total
  )
  const gpuLimited = typeof gpuMemoryLimit === 'number'
    ? sorted.filter((v) => v <= gpuMemoryLimit)
    : sorted
  if (typeof effectiveFree === 'number') {
    return gpuLimited.filter((v) => v <= effectiveFree)
  }
  return gpuLimited
})

const canProceedCreateStep1 = computed(() => {
  return Boolean(createForm.nodeId && createForm.image && createImages.value.length > 0)
})

const canSubmitCreate = computed(() => {
  return Boolean(
    createForm.nodeId
      && createForm.image
      && availableGpuOptions.value.includes(createForm.numGpus)
      && availableMemoryOptions.value.includes(createForm.memoryGb)
      && isValidHourValue(createForm.expireHours)
  )
})

const canSubmitRenew = computed(() => {
  return Boolean(selectedInstance.value && isValidHourValue(renewForm.hours))
})

const canSubmitRebuild = computed(() => {
  return Boolean(
    selectedInstance.value
      && rebuildGpuOptions.value.includes(rebuildForm.numGpus)
      && rebuildMemoryOptions.value.includes(rebuildForm.memoryGb)
  )
})

const availableImages = computed(() => {
  return createImages.value.reduce<Record<string, string>>((acc, item) => {
    acc[item.key] = item.label
    return acc
  }, {})
})

async function refreshGpuHours() {
  try {
    const data = await api.get<{ gpu_hours_remaining?: number }>('/api/quota/me')
    gpuHoursRemaining.value = Number(data.gpu_hours_remaining ?? 0)
  } catch {
    gpuHoursRemaining.value = null
  }
}

async function loadCreateNodeResources(nodeId: string) {
  const loadToken = ++createNodeLoadToken
  createForm.image = ''
  createImages.value = []

  if (!nodeId) {
    createImagesLoading.value = false
    return
  }

  createImagesLoading.value = true
  try {
    const [, images] = await Promise.all([
      clusterStore.fetchMetadata(nodeId),
      clusterStore.fetchNodeImages(nodeId)
    ])

    if (loadToken !== createNodeLoadToken || createForm.nodeId !== nodeId) return

    createImages.value = images

    if (images.length > 0) {
      createForm.image = images[0].key
    }

    const memoryOptions = availableMemoryOptions.value
    if (memoryOptions.length > 0 && !memoryOptions.includes(createForm.memoryGb)) {
      createForm.memoryGb = memoryOptions[0]
    }
  } catch (e) {
    if (loadToken === createNodeLoadToken && createForm.nodeId === nodeId) {
      createImages.value = []
    }
    console.error('Failed to fetch metadata:', e)
  } finally {
    if (loadToken === createNodeLoadToken && createForm.nodeId === nodeId) {
      createImagesLoading.value = false
    }
  }
}

// Watch for node selection to load metadata
watch(() => createForm.nodeId, (nodeId) => {
  void loadCreateNodeResources(nodeId)
})

watch(availableGpuOptions, (options) => {
  if (options.length > 0 && !options.includes(createForm.numGpus)) {
    createForm.numGpus = options[options.length - 1]
  }
})

watch(availableMemoryOptions, (options) => {
  if (options.length > 0 && !options.includes(createForm.memoryGb)) {
    createForm.memoryGb = options[0]
  }
})

watch(rebuildGpuOptions, (options) => {
  if (options.length > 0 && !options.includes(rebuildForm.numGpus)) {
    rebuildForm.numGpus = options[options.length - 1]
  }
})

watch(rebuildMemoryOptions, (options) => {
  if (options.length > 0 && !options.includes(rebuildForm.memoryGb)) {
    rebuildForm.memoryGb = options[0]
  }
})

watch(() => modals.create, (visible) => {
  if (!visible) {
    createNodeLoadToken += 1
    createStep.value = 1
    createForm.displayName = ''
    createForm.image = ''
    createImages.value = []
    createImagesLoading.value = false
  }
})

watch(() => modals.rebuild, (visible) => {
  if (!visible) {
    rebuildMetadata.value = null
  }
})

watch(() => modals.sshKeys, (visible) => {
  if (!visible) {
    sshKeyForm.publicKey = ''
    sshKeyForm.remark = ''
    loading.sshKeyDeleteId = null
  }
})

// Actions
function handleLogout() {
  clusterStore.stopAutoRefresh()
  authStore.logout()
  router.push({ name: 'Login' })
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function isValidHourValue(value: unknown): boolean {
  const hours = Number(value)
  return Number.isInteger(hours) && hours >= 1 && hours <= 168
}

function openCreateModal() {
  if (availableNodes.value.length === 0) {
    toast.error('当前没有可用的节点')
    return
  }
  createStep.value = 1
  createForm.displayName = ''
  const nextNodeId = availableNodes.value[0]?.node_id || ''
  const shouldReloadNodeResources = createForm.nodeId === nextNodeId
  createForm.nodeId = nextNodeId
  modals.create = true
  if (shouldReloadNodeResources) {
    void loadCreateNodeResources(nextNodeId)
  }
}

async function loadSshKeys() {
  loading.sshKeys = true
  try {
    sshKeys.value = await clusterStore.fetchSshKeys()
  } catch (e: any) {
    toast.error(e.message || 'SSH 公钥加载失败')
  } finally {
    loading.sshKeys = false
  }
}

async function openSshKeysModal() {
  modals.sshKeys = true
  await loadSshKeys()
}

function handleCreateNext() {
  if (!canProceedCreateStep1.value) {
    toast.error('请先选择节点和镜像')
    return
  }
  if (availableMemoryOptions.value.length === 0) {
    toast.error('该节点当前可分配内存不足，无法创建实例')
    return
  }
  createStep.value = 2
}

function handleCreatePrev() {
  createStep.value = 1
}

function handleInstanceAction(action: string, instance: Instance) {
  if (isInstanceRebuilding(instance)) {
    toast.warning('实例正在重建中，请等待节点完成后再操作')
    return
  }
  selectedInstance.value = instance

  switch (action) {
    case 'stop':
      handleStop(instance)
      break
    case 'restart':
      handleRestart(instance)
      break
    case 'renew':
      renewForm.hours = 24
      modals.renew = true
      break
    case 'rebuild':
      void openRebuildModal(instance)
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

async function openRebuildModal(instance: Instance) {
  if (isInstanceRebuilding(instance)) {
    toast.warning('实例正在重建中，请等待节点完成后再试')
    return
  }
  selectedInstance.value = instance
  rebuildForm.numGpus = instance.gpu_indices?.length ?? 0
  rebuildForm.memoryGb = instance.memory_gb || 32

  try {
    rebuildMetadata.value = await clusterStore.fetchMetadata(instance.node_id)
  } catch (e) {
    rebuildMetadata.value = null
    console.error('Failed to fetch rebuild metadata:', e)
  }

  if (!rebuildGpuOptions.value.includes(rebuildForm.numGpus)) {
    rebuildForm.numGpus = rebuildGpuOptions.value[rebuildGpuOptions.value.length - 1] ?? 0
  }
  if (!rebuildMemoryOptions.value.includes(rebuildForm.memoryGb)) {
    rebuildForm.memoryGb = rebuildMemoryOptions.value[0] ?? 8
  }

  modals.rebuild = true
}

async function handleCreate() {
  if (!canSubmitCreate.value) {
    toast.error('请先完成实例参数选择')
    return
  }

  loading.create = true
  try {
    const expireHours = Number(createForm.expireHours)
    const result = await clusterStore.createInstance(createForm.nodeId, {
      display_name: createForm.displayName.trim() || undefined,
      num_gpus: createForm.numGpus,
      memory_gb: createForm.memoryGb,
      image: createForm.image,
      expire_hours: expireHours
    })
    toast.success('实例创建成功')
    modals.create = false
    await clusterStore.fetchAll()
    await refreshGpuHours()
    // Start SSH polling for new instance
    if (result.id) {
      const instanceKey = `${createForm.nodeId}:${result.id}`
      pendingSshInstances.value.add(instanceKey)
      startSshPolling()
    }
    startCreateTransition()
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
    await refreshGpuHours()
  } catch (e: any) {
    toast.error(e.message || '停止失败')
  }
}

async function handleRestart(instance: Instance) {
  try {
    await clusterStore.restartInstance(instance.node_id, Number(instance.id))
    toast.success('实例已重启')
    await clusterStore.fetchAll()
    await refreshGpuHours()
  } catch (e: any) {
    toast.error(e.message || '重启失败')
  }
}

async function handleRenew() {
  if (!selectedInstance.value) return
  if (!canSubmitRenew.value) {
    toast.error('请输入 1-168 小时的续期时长')
    return
  }

  loading.renew = true
  try {
    const extendHours = Number(renewForm.hours)
    await clusterStore.renewInstance(
      selectedInstance.value.node_id,
      Number(selectedInstance.value.id),
      extendHours
    )
    toast.success(`实例已续期 ${extendHours} 小时`)
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
  if (isInstanceRebuilding(selectedInstance.value)) {
    toast.warning('实例正在重建中，请等待节点完成后再试')
    return
  }
  if (!canSubmitRebuild.value) {
    toast.error('当前节点资源限制下，该配置不可用')
    return
  }

  loading.rebuild = true
  const rebuildKey = instanceOperationKey(selectedInstance.value)
  try {
    if (rebuildKey) {
      pendingRebuildInstances.value.add(rebuildKey)
    }
    modals.rebuild = false
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
    await refreshGpuHours()
  } catch (e: any) {
    toast.error(e.message || '配置变更失败')
  } finally {
    loading.rebuild = false
    if (rebuildKey) {
      pendingRebuildInstances.value.delete(rebuildKey)
    }
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
    await refreshGpuHours()
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  } finally {
    loading.delete = false
  }
}

async function handleCreateSshKey() {
  if (!sshKeyForm.publicKey.trim()) {
    toast.error('请先粘贴 SSH 公钥')
    return
  }

  loading.sshKeyCreate = true
  try {
    await clusterStore.createSshKey({
      public_key: sshKeyForm.publicKey.trim(),
      remark: sshKeyForm.remark.trim() || undefined
    })
    toast.success('SSH 公钥已保存')
    sshKeyForm.publicKey = ''
    sshKeyForm.remark = ''
    await loadSshKeys()
  } catch (e: any) {
    toast.error(e.message || 'SSH 公钥保存失败')
  } finally {
    loading.sshKeyCreate = false
  }
}

async function handleDeleteSshKey(keyId: number) {
  loading.sshKeyDeleteId = keyId
  try {
    await clusterStore.deleteSshKey(keyId)
    toast.success('SSH 公钥已删除')
    await loadSshKeys()
  } catch (e: any) {
    toast.error(e.message || 'SSH 公钥删除失败')
  } finally {
    loading.sshKeyDeleteId = null
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
    await refreshGpuHours()
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
    await refreshGpuHours()
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

function startCreateTransition(durationMs = 10000) {
  stopCreateTransition()
  createTransitionVisible.value = true
  createTransitionTimer = setTimeout(() => {
    createTransitionVisible.value = false
    createTransitionTimer = null
  }, durationMs)
}

function stopCreateTransition() {
  if (createTransitionTimer) {
    clearTimeout(createTransitionTimer)
    createTransitionTimer = null
  }
  createTransitionVisible.value = false
}

onUnmounted(() => {
  clusterStore.stopAutoRefresh()
  stopSshPolling()
  stopCreateTransition()
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

.header-quota {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
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

.create-transition-window {
  display: grid;
  justify-items: center;
  gap: 12px;
  padding: 8px 0;
  text-align: center;
}

.create-transition-spinner {
  width: 44px;
  height: 44px;
  border-radius: 999px;
  border: 4px solid var(--color-border);
  border-top-color: var(--color-primary);
  animation: create-transition-spin 0.9s linear infinite;
}

.create-transition-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.create-transition-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  line-height: 1.6;
}

@keyframes create-transition-spin {
  from {
    transform: rotate(0deg);
  }

  to {
    transform: rotate(360deg);
  }
}

/* ── Forms ── */
.form {
  display: grid;
  gap: 16px;
}

.wizard-step {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
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
.field select,
.field textarea {
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-base);
  background: var(--color-surface);
  color: var(--color-text);
}

.field input:focus,
.field select:focus,
.field textarea:focus {
  outline: none;
  border-color: var(--color-primary);
}

.field-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: 2px;
}

.field-hint.warning-text {
  color: var(--color-warning);
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

/* ── SSH Keys ── */
.ssh-key-layout {
  display: grid;
  gap: 16px;
}

.ssh-key-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 16px;
  background: var(--color-surface);
}

.ssh-key-panel h4 {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 10px;
}

.ssh-key-panel p {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  line-height: 1.6;
}

.ssh-key-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.ssh-key-count {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.ssh-key-help {
  display: grid;
  gap: 12px;
}

.ssh-key-command,
.ssh-key-preview {
  margin: 8px 0 0;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  color: var(--color-text);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  white-space: pre-wrap;
  word-break: break-word;
}

.ssh-key-help-text {
  margin-top: 10px;
}

.ssh-key-textarea {
  min-height: 110px;
  resize: vertical;
  font-family: var(--font-mono);
}

.ssh-key-list {
  display: grid;
  gap: 12px;
}

.ssh-key-card {
  display: grid;
  gap: 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 12px;
  background: var(--color-surface-alt);
}

.ssh-key-meta {
  display: grid;
  gap: 4px;
}

.ssh-key-remark {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.ssh-key-fingerprint,
.ssh-key-created,
.ssh-key-empty {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.ssh-key-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
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
  .ssh-key-panel-head {
    align-items: flex-start;
    flex-direction: column;
  }
  .ssh-key-actions {
    justify-content: stretch;
  }
}
</style>
