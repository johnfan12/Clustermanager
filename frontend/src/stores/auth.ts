/**
 * 认证状态管理 (Pinia store)
 * 管理 JWT token、用户信息，使用 localStorage 持久化
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

const STORAGE_KEY = 'simpleClusterToken'
const USER_STORAGE_KEY = 'simpleClusterUser'

export interface UserInfo {
  username: string
  is_admin: boolean
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
  const token = ref(localStorage.getItem(STORAGE_KEY) || '')
  const user = ref<UserInfo | null>(safeParse<UserInfo>(localStorage.getItem(USER_STORAGE_KEY)))

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
  }) {
    token.value = data.access_token || ''
    user.value = data.user || {
      username: data.username || '',
      is_admin: Boolean(data.is_admin)
    }
    persist()
  }

  function persist() {
    localStorage.setItem(STORAGE_KEY, token.value)
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user.value))
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(USER_STORAGE_KEY)
  }

  return {
    token,
    user,
    isAuthenticated,
    isAdmin,
    username,
    setSession,
    persist,
    logout
  }
})
