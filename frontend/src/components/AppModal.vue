<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="visible" class="modal-backdrop" @click.self="onBackdrop">
        <div :class="['modal-panel', sizeClass]" role="dialog" aria-modal="true">
          <div class="modal-header">
            <h3 class="modal-title">{{ title }}</h3>
            <button
              v-if="showClose"
              class="modal-close"
              type="button"
              @click="onClose"
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
          <div class="modal-body">
            <slot />
          </div>
          <div v-if="$slots.footer" class="modal-footer">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    visible: boolean
    title?: string
    size?: 'sm' | 'md' | 'lg'
    closeOnBackdrop?: boolean
    showClose?: boolean
  }>(),
  {
    title: '',
    size: 'md',
    closeOnBackdrop: true,
    showClose: true
  }
)

const emit = defineEmits<{
  'update:visible': [value: boolean]
  close: []
}>()

const sizeClass = computed(() => `modal-${props.size}`)

function onClose() {
  emit('update:visible', false)
  emit('close')
}

function onBackdrop() {
  if (props.closeOnBackdrop) {
    onClose()
  }
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal-backdrop);
  padding: var(--space-lg);
}

.modal-panel {
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  max-height: 85vh;
  overflow: hidden;
  z-index: var(--z-modal);
}

.modal-sm { width: min(400px, 100%); }
.modal-md { width: min(560px, 100%); }
.modal-lg { width: min(780px, 100%); }

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
}

.modal-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.modal-close {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  font-size: 14px;
  transition: all var(--transition-fast);
}

.modal-close:hover {
  background: var(--color-bg);
  color: var(--color-text);
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--color-border);
}

/* Transition */
.modal-enter-active { transition: all 0.2s ease; }
.modal-leave-active { transition: all 0.15s ease; }
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from .modal-panel {
  transform: scale(0.96) translateY(8px);
}
</style>
