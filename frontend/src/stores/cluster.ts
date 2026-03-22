/**
 * 集群数据管理 (Pinia store)
 * 调度从 API 获取集群状态和实例数据
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/shared/utils/api'

// ── Types ──

export interface GpuInfo {
  index: number
  status: 'free' | 'used'
  allocated_to: string | null
  name?: string
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
  web_url: string
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
  gpu_indices: number[]
  memory_gb: number
  image_name: string
  status: 'running' | 'stopped' | 'error'
  ssh_command?: string
  ssh_cmd?: string
  vps_access: VpsAccess | null
  ssh_password: string
  expire_at: string | null
  [key: string]: unknown
}

export interface AuthNode {
  node_id: string
  name: string
  web_url: string
  online: boolean
  allow_register: boolean
}

// ── Store ──

export const useClusterStore = defineStore('cluster', () => {
  // State
  const nodes = ref<NodeStatus[]>([])
  const summary = ref<ClusterSummary>({ total_gpu: 0, free_gpu: 0, total_instances: 0 })
  const instances = ref<Instance[]>([])
  const authNodes = ref<AuthNode[]>([])
  const loading = ref(false)
  const error = ref('')

  // Derived
  const runningInstances = computed(() =>
    instances.value.filter((i) => i.status === 'running')
  )

  // Auto-refresh
  let _timer: ReturnType<typeof setInterval> | null = null

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
    loading.value = true
    error.value = ''
    try {
      await Promise.all([fetchClusterStatus(), fetchMyInstances()])
    } catch (e) {
      error.value = String(e)
    } finally {
      loading.value = false
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
    loading,
    error,
    // getters
    runningInstances,
    // actions
    fetchAuthNodes,
    fetchClusterStatus,
    fetchMyInstances,
    fetchAll,
    startAutoRefresh,
    stopAutoRefresh
  }
})
