/**
 * Toast 通知管理 (Pinia store)
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface ToastItem {
  id: number
  message: string
  type: 'info' | 'success' | 'error' | 'warning'
}

let _nextId = 0

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])

  function show(message: string, type: ToastItem['type'] = 'info', duration = 3000) {
    const id = _nextId++
    items.value.push({ id, message, type })
    setTimeout(() => {
      remove(id)
    }, duration)
  }

  function remove(id: number) {
    items.value = items.value.filter((t) => t.id !== id)
  }

  function success(message: string) {
    show(message, 'success')
  }

  function error(message: string) {
    show(message, 'error', 5000)
  }

  function warning(message: string) {
    show(message, 'warning', 4000)
  }

  return { items, show, remove, success, error, warning }
})
