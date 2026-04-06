/**
 * 认证状态管理 (Pinia store)
 * 集中管理 JWT token、用户信息、节点选择
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const STORAGE_KEYS = {
  token: 'cluster_token',
  user: 'cluster_user',
  nodeId: 'cluster_node_id'
} as const

export interface UserInfo {
  username: string
  is_admin: boolean
  email?: string
  [key: string]: unknown
}

function safeParse<T>(value: string | null): T | null {
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  // ── State ──
  const token = ref(localStorage.getItem(STORAGE_KEYS.token) || '')
  const user = ref<UserInfo | null>(safeParse<UserInfo>(localStorage.getItem(STORAGE_KEYS.user)))
  const currentNodeId = ref(localStorage.getItem(STORAGE_KEYS.nodeId) || '')

  // ── Getters ──
  const isAuthenticated = computed(() => Boolean(token.value && user.value))
  const isAdmin = computed(() => Boolean(user.value?.is_admin))
  const username = computed(() => user.value?.username || '')

  // ── Actions ──
  function setSession(data: {
    access_token: string
    user?: UserInfo
    username?: string
    is_admin?: boolean
    node_id?: string
  }) {
    token.value = data.access_token || ''
    user.value = data.user || {
      username: data.username || '',
      is_admin: Boolean(data.is_admin)
    }
    currentNodeId.value = data.node_id || ''
    persist()
  }

  function persist() {
    localStorage.setItem(STORAGE_KEYS.token, token.value)
    localStorage.setItem(STORAGE_KEYS.user, JSON.stringify(user.value))
    localStorage.setItem(STORAGE_KEYS.nodeId, currentNodeId.value)
  }

  function logout() {
    token.value = ''
    user.value = null
    currentNodeId.value = ''
    Object.values(STORAGE_KEYS).forEach((key) => localStorage.removeItem(key))
    localStorage.removeItem('cluster_node_name')
    localStorage.removeItem('cluster_entry_url')
  }

  return {
    // state
    token,
    user,
    currentNodeId,
    // getters
    isAuthenticated,
    isAdmin,
    username,
    // actions
    setSession,
    persist,
    logout
  }
})
