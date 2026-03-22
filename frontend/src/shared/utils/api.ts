/**
 * 统一 HTTP 请求封装
 * 基于原生 fetch，支持 JWT 自动注入、错误统一处理
 */

import { useAuthStore } from '@/stores/auth'

const API_BASE = ''

export interface ApiError {
  status: number
  detail: string
}

class ApiRequestError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiRequestError'
    this.status = status
    this.detail = detail
  }
}

export { ApiRequestError }

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  skipAuth?: boolean
}

export async function request<T = unknown>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { body, skipAuth, headers: extraHeaders, ...rest } = options

  const headers: Record<string, string> = {
    ...(extraHeaders as Record<string, string>)
  }

  // Auto-inject auth token
  if (!skipAuth) {
    const authStore = useAuthStore()
    if (authStore.token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${authStore.token}`
    }
  }

  // JSON body
  if (body !== undefined && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined
  })

  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    const detail =
      typeof data === 'string'
        ? data
        : data?.detail || data?.message || '请求失败'
    
    // Auto-logout on 401
    if (response.status === 401 && !skipAuth) {
      const authStore = useAuthStore()
      authStore.logout()
    }

    throw new ApiRequestError(response.status, detail)
  }

  return data as T
}

// Convenience methods
export const api = {
  get: <T = unknown>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),

  post: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),

  put: <T = unknown>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PUT', body }),

  delete: <T = unknown>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' })
}
