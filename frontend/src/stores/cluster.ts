/**
 * 集群数据管理 (Pinia store)
 * 调度从 API 获取集群状态和实例数据
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/shared/utils/api'

// ── Types ──

export interface GpuInfo {
  index: number
  status: 'free' | 'used'
  allocated_to: string | null
  name?: string
  memory_total_mb?: number
  power_draw_w?: number | null
  power_limit_w?: number | null
}

export interface NodeStatus {
  node_id: string
  name: string
  online: boolean
  gpu_model: string
  gpu_total: number
  gpu_free: number
  gpu_used: number
  instance_count: number
  gpus: GpuInfo[]
}

export interface ClusterSummary {
  total_gpu: number
  free_gpu: number
  total_instances: number
}

export interface VpsAccess {
  ssh_cmd: string
  vps_port: number
  access_url: string
}

export interface Instance {
  node_id: string
  node_name: string
  container_name: string
  display_name?: string
  gpu_indices: number[]
  memory_gb: number
  image_name: string
  base_image_name?: string
  runtime_image_name?: string
  last_snapshot_image_name?: string | null
  last_snapshot_at?: string | null
  snapshot_status?: 'none' | 'creating' | 'ready' | 'failed'
  status: 'running' | 'stopped' | 'error'
  ssh_command?: string
  ssh_cmd?: string
  vps_access: VpsAccess | null
  ssh_password: string
  expire_at: string | null
  [key: string]: unknown
}

export interface Metadata {
  memory_options_gb?: number[]
  max_instance_memory_gb?: number
  node_allocatable_memory_gb?: number
  node_memory_used_gb?: number
  node_memory_free_gb?: number
}

export interface NodeImage {
  key: string
  label: string
  image_ref: string
}

export interface AuthNode {
  node_id: string
  name: string
  online: boolean
}

export interface SshKeyItem {
  id: number
  public_key: string
  remark: string
  fingerprint: string
  created_at: string
}

export interface AdminUser {
  username: string
  email: string
  is_admin: boolean
  gpu_hours_quota: number
  gpu_hours_used: number
  gpu_hours_frozen: number
  gpu_hours_remaining: number
  used_gpu: number
  used_memory_gb: number
  used_instances: number
}

export interface AdminInstance extends Instance {
  user_id: number
  username: string
}

// ── Store ──

export const useClusterStore = defineStore('cluster', () => {
  // State
  const nodes = ref<NodeStatus[]>([])
  const summary = ref<ClusterSummary>({ total_gpu: 0, free_gpu: 0, total_instances: 0 })
  const instances = ref<Instance[]>([])
  const authNodes = ref<AuthNode[]>([])
  const metadata = ref<Metadata | null>(null)

  // Auto-refresh
  let _timer: ReturnType<typeof setInterval> | null = null

  // ── Instance Actions ──

  async function createInstance(
    nodeId: string,
    payload: {
      num_gpus: number
      memory_gb: number
      image: string
      expire_hours: number
      display_name?: string
    }
  ) {
    const data = await api.post<{ id: number; container_name: string; display_name?: string }>(
      `/api/proxy/${nodeId}/api/instances`,
      payload
    )
    return data
  }

  async function stopInstance(nodeId: string, instanceId: number) {
    await api.post(`/api/proxy/${nodeId}/api/instances/${instanceId}/stop`)
  }

  async function restartInstance(nodeId: string, instanceId: number) {
    await api.post(`/api/proxy/${nodeId}/api/instances/${instanceId}/restart`)
  }

  async function deleteInstance(nodeId: string, instanceId: number) {
    await api.delete(`/api/proxy/${nodeId}/api/instances/${instanceId}`)
  }

  async function renewInstance(nodeId: string, instanceId: number, extendHours: number) {
    await api.post(`/api/proxy/${nodeId}/api/instances/${instanceId}/renew`, {
      extend_hours: extendHours
    })
  }

  async function rebuildInstance(
    nodeId: string,
    instanceId: number,
    payload: { num_gpus: number; memory_gb: number }
  ) {
    await api.post(`/api/proxy/${nodeId}/api/instances/${instanceId}/rebuild`, payload)
  }

  async function getInstanceLogs(nodeId: string, instanceId: number): Promise<string> {
    const data = await api.get<{ logs: string }>(
      `/api/proxy/${nodeId}/api/instances/${instanceId}/logs`
    )
    return data.logs || '暂无日志'
  }

  async function fetchMetadata(nodeId: string) {
    const data = await api.get<Metadata>(`/api/proxy/${nodeId}/api/meta`)
    metadata.value = data
    return data
  }

  async function fetchNodeImages(nodeId: string): Promise<NodeImage[]> {
    const data = await api.get<{ images: NodeImage[] }>(`/api/proxy/${nodeId}/api/images`)
    return Array.isArray(data.images) ? data.images : []
  }

  async function fetchSshKeys(): Promise<SshKeyItem[]> {
    const data = await api.get<{ keys: SshKeyItem[] }>('/api/ssh-keys')
    return Array.isArray(data.keys) ? data.keys : []
  }

  async function createSshKey(payload: { public_key: string; remark?: string }) {
    return api.post<SshKeyItem>('/api/ssh-keys', payload)
  }

  async function deleteSshKey(keyId: number) {
    await api.delete(`/api/ssh-keys/${keyId}`)
  }

  // ── Admin Actions ──

  async function fetchAdminUsers(): Promise<AdminUser[]> {
    const data = await api.get<AdminUser[]>('/api/admin/users')
    return data || []
  }

  async function updateUserQuota(
    username: string,
    payload: {
      gpu_hours_quota: number
    }
  ) {
    await api.put(`/api/admin/users/${encodeURIComponent(username)}/quota`, payload)
  }

  async function fetchAdminInstances(nodeId: string): Promise<AdminInstance[]> {
    const data = await api.get<AdminInstance[]>(`/api/proxy/${nodeId}/api/admin/instances`)
    return data || []
  }

  async function forceDeleteInstance(nodeId: string, instanceId: number) {
    await api.delete(`/api/proxy/${nodeId}/api/admin/instances/${instanceId}`)
  }

  // Actions
  async function fetchAuthNodes() {
    try {
      const data = await api.get<{ nodes: AuthNode[] }>('/api/auth/nodes', { skipAuth: true })
      authNodes.value = Array.isArray(data.nodes) ? data.nodes : []
    } catch (e) {
      authNodes.value = []
      console.error('节点列表加载失败', e)
    }
  }

  async function fetchClusterStatus() {
    try {
      const data = await api.get<{ nodes: NodeStatus[]; summary: ClusterSummary }>(
        '/api/cluster/status'
      )
      nodes.value = data.nodes || []
      summary.value = data.summary || { total_gpu: 0, free_gpu: 0, total_instances: 0 }
    } catch (e) {
      console.error('集群状态加载失败', e)
    }
  }

  async function fetchMyInstances() {
    try {
      const data = await api.get<{ instances: Instance[]; total: number }>(
        '/api/cluster/my_instances'
      )
      instances.value = data.instances || []
    } catch (e: unknown) {
      const err = e as { message?: string }
      if (err.message?.includes('token')) {
        throw e // let caller handle token expiry
      }
      console.error('实例加载失败', e)
    }
  }

  async function fetchAll() {
    try {
      await Promise.all([fetchClusterStatus(), fetchMyInstances()])
    } catch {
      // Callers already handle visible errors; keep auto-refresh best-effort.
    }
  }

  function startAutoRefresh(intervalMs = 30000) {
    stopAutoRefresh()
    _timer = setInterval(() => {
      fetchAll().catch(() => {})
    }, intervalMs)
  }

  function stopAutoRefresh() {
    if (_timer) {
      clearInterval(_timer)
      _timer = null
    }
  }

  return {
    // state
    nodes,
    summary,
    instances,
    authNodes,
    metadata,
    // actions
    fetchAuthNodes,
    fetchClusterStatus,
    fetchMyInstances,
    fetchAll,
    startAutoRefresh,
    stopAutoRefresh,
    // instance actions
    createInstance,
    stopInstance,
    restartInstance,
    deleteInstance,
    renewInstance,
    rebuildInstance,
    getInstanceLogs,
    // admin actions
    fetchAdminUsers,
    updateUserQuota,
    fetchAdminInstances,
    forceDeleteInstance,
    fetchMetadata,
    fetchNodeImages,
    fetchSshKeys,
    createSshKey,
    deleteSshKey
  }
})
