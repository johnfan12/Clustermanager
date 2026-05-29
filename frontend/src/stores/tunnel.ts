/**
 * 隧道/SSH Access 数据管理 (Pinia store)
 * 管理节点列表、SSH 访问记录、已保存的访问凭据
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/shared/utils/api'
import { useAuthStore } from '@/stores/auth'

// ── Types ──

export interface NodeInfo {
  id: string
  name: string
  public_host: string
  gpu_count?: number
  gpu_model?: string
}

export interface SshAccess {
  node_id: string
  node_name: string
  name: string
  ssh_command: string
  status: string
  owner: string
  error?: string
  remote_port?: number
  public_host?: string
  saved_key?: string
  requested_user_id?: string
}

export interface AppConfig {
  app_display_name: string
  auth_mode: string
  auth_required: boolean
  allow_register: boolean
}

export interface GpuInfo {
  index: number
  status: 'free' | 'used' | 'unknown'
  is_idle?: boolean
  allocated_to?: string | null
  name?: string | null
  gpu_model?: string | null
  memory_total_mb?: number | null
  memory_used_mb?: number | null
  memory_total_gb?: number | null
  utilization_gpu?: number | null
  temperature_c?: number | null
  power_draw_w?: number | null
  power_limit_w?: number | null
}

export interface NodeGpuStatus {
  node_id: string
  name: string
  online: boolean
  gpu_model: string
  gpu_total: number
  gpu_free: number
  gpu_used: number
  gpu_utilization_avg: number | null
  memory_used_mb: number | null
  memory_total_mb: number | null
  power_draw_w: number | null
  power_limit_w: number | null
  temperature_avg_c: number | null
  instance_count: number
  gpus: GpuInfo[]
  error?: string
}

export interface GpuSummary {
  total_gpu: number
  free_gpu: number
  used_gpu: number
  total_instances: number
  gpu_utilization_avg: number | null
}

// ── Store ──

export const useTunnelStore = defineStore('tunnel', () => {
  const nodes = ref<NodeInfo[]>([])
  const tunnels = ref<SshAccess[]>([])
  const gpuNodes = ref<NodeGpuStatus[]>([])
  const gpuSummary = ref<GpuSummary>({
    total_gpu: 0,
    free_gpu: 0,
    used_gpu: 0,
    total_instances: 0,
    gpu_utilization_avg: null
  })
  const gpuErrors = ref<string[]>([])
  const selectedNode = ref<string>('all')
  const config = ref<AppConfig>({
    app_display_name: 'Clustermanager',
    auth_required: true,
    auth_mode: 'account',
    allow_register: true
  })

  // ── Getters ──
  const filteredTunnels = computed(() => {
    if (selectedNode.value === 'all') return tunnels.value
    return tunnels.value.filter((t) => t.node_id === selectedNode.value)
  })

  // ── Actions ──

  async function fetchConfig() {
    try {
      const data = await api.get<AppConfig>('/api/config')
      config.value = {
        app_display_name: data.app_display_name || 'Clustermanager',
        auth_mode: data.auth_mode || 'account',
        auth_required: data.auth_required !== false,
        allow_register: data.allow_register !== false
      }
      document.title = config.value.app_display_name
    } catch {
      // Keep defaults
    }
  }

  async function fetchNodes() {
    const data = await api.get<{ nodes: NodeInfo[] }>('/api/nodes')
    nodes.value = data.nodes || []
  }

  async function fetchGpuStatus() {
    const data = await api.get<{
      nodes: NodeGpuStatus[]
      summary: GpuSummary
      errors?: Array<{ node_id: string; message: string }>
    }>('/api/cluster/status')
    gpuNodes.value = data.nodes || []
    gpuSummary.value = data.summary || {
      total_gpu: 0,
      free_gpu: 0,
      used_gpu: 0,
      total_instances: 0,
      gpu_utilization_avg: null
    }
    gpuErrors.value = (data.errors || []).map((item) => item.message).filter(Boolean)
  }

  function accessKey(nodeId: string, userId: string): string {
    return `${encodeURIComponent(nodeId)}:${encodeURIComponent(userId)}`
  }

  function savedAccessStorageKey(): string {
    const authStore = useAuthStore()
    const username = authStore.username || 'anonymous'
    return `simpleClusterSshAccesses:${username}`
  }

  function readSavedAccesses(): Array<{ node_id: string; user_id: string }> {
    try {
      const parsed = JSON.parse(localStorage.getItem(savedAccessStorageKey()) || '[]')
      if (!Array.isArray(parsed)) return []
      return parsed.filter(
        (item: { node_id?: string; user_id?: string }) => item && item.node_id && item.user_id
      )
    } catch {
      return []
    }
  }

  function writeSavedAccesses(items: Array<{ node_id: string; user_id: string }>) {
    localStorage.setItem(savedAccessStorageKey(), JSON.stringify(items))
  }

  function rememberAccess(nodeId: string, userId: string) {
    const next = readSavedAccesses().filter(
      (item) => accessKey(item.node_id, item.user_id) !== accessKey(nodeId, userId)
    )
    next.unshift({ node_id: nodeId, user_id: userId })
    writeSavedAccesses(next.slice(0, 20))
  }

  function forgetAccess(key: string) {
    writeSavedAccesses(
      readSavedAccesses().filter(
        (item) => accessKey(item.node_id, item.user_id) !== key
      )
    )
    tunnels.value = tunnels.value.filter(
      (t) => (t.saved_key || accessKey(t.node_id, t.owner)) !== key
    )
  }

  async function fetchSshAccess(nodeId: string, userId: string): Promise<SshAccess | null> {
    const payload = await api.post<{ access?: SshAccess }>(
      `/api/nodes/${encodeURIComponent(nodeId)}/ssh-access`,
      { user_id: userId }
    )
    if (!payload.access) return null
    const access = payload.access
    access.saved_key = accessKey(nodeId, userId)
    access.requested_user_id = userId
    return access
  }

  async function restoreSavedAccesses(): Promise<string[]> {
    const saved = readSavedAccesses()
    if (!saved.length) {
      tunnels.value = []
      return []
    }

    const validNodeIds = new Set(nodes.value.map((n) => n.id))
    const restored: SshAccess[] = []
    const errors: string[] = []

    for (const item of saved) {
      if (!validNodeIds.has(item.node_id)) continue
      try {
        const access = await fetchSshAccess(item.node_id, item.user_id)
        if (access) restored.push(access)
      } catch (e: unknown) {
        errors.push((e as Error).message)
      }
    }

    tunnels.value = restored
    return errors
  }

  function selectNode(nodeId: string) {
    selectedNode.value = nodeId
  }

  return {
    // state
    nodes,
    tunnels,
    gpuNodes,
    gpuSummary,
    gpuErrors,
    selectedNode,
    config,
    // getters
    filteredTunnels,
    // actions
    fetchConfig,
    fetchNodes,
    fetchGpuStatus,
    fetchSshAccess,
    restoreSavedAccesses,
    rememberAccess,
    forgetAccess,
    selectNode,
    accessKey
  }
})
