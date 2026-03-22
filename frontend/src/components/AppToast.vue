<template>
  <Teleport to="body">
    <TransitionGroup name="toast" tag="div" class="toast-container">
      <div
        v-for="item in items"
        :key="item.id"
        :class="['toast-item', `toast-${item.type}`]"
        @click="remove(item.id)"
      >
        <span class="toast-icon">{{ iconMap[item.type] }}</span>
        <span class="toast-message">{{ item.message }}</span>
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<script setup lang="ts">
import { useToastStore } from '@/stores/toast'
import { storeToRefs } from 'pinia'

const store = useToastStore()
const { items } = storeToRefs(store)
const { remove } = store

const iconMap: Record<string, string> = {
  info: 'ℹ️',
  success: '✅',
  error: '❌',
  warning: '⚠️'
}
</script>

<style scoped>
.toast-container {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column-reverse;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}

.toast-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  box-shadow: var(--shadow-lg);
  cursor: pointer;
  pointer-events: auto;
  max-width: 480px;
  word-break: break-word;
}

.toast-info {
  background: #323130;
  color: #ffffff;
}

.toast-success {
  background: var(--color-success);
  color: #ffffff;
}

.toast-error {
  background: var(--color-danger);
  color: #ffffff;
}

.toast-warning {
  background: #7a6400;
  color: #ffffff;
}

.toast-icon {
  flex-shrink: 0;
  font-size: 14px;
}

/* Transitions */
.toast-enter-active {
  transition: all 0.3s ease;
}
.toast-leave-active {
  transition: all 0.2s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(16px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
