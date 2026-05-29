<template>
  <button
    :class="['btn', `btn-${variant}`, `btn-${size}`, { 'btn-block': block, 'btn-loading': loading }]"
    :disabled="disabled || loading"
    v-bind="$attrs"
  >
    <span v-if="loading" class="btn-spinner" />
    <slot />
  </button>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
    size?: 'sm' | 'md' | 'lg'
    block?: boolean
    loading?: boolean
    disabled?: boolean
  }>(),
  {
    variant: 'primary',
    size: 'md',
    block: false,
    loading: false,
    disabled: false
  }
)
</script>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-weight: var(--font-weight-medium);
  border-radius: var(--radius-sm);
  transition: all var(--transition-fast);
  white-space: nowrap;
  user-select: none;
  position: relative;
}

/* Sizes */
.btn-sm { padding: 4px 12px; font-size: var(--font-size-sm); }
.btn-md { padding: 7px 16px; font-size: var(--font-size-base); }
.btn-lg { padding: 10px 24px; font-size: var(--font-size-md); }

/* Variants */
.btn-primary {
  background: var(--color-primary);
  color: #fff;
}
.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
.btn-primary:active:not(:disabled) { background: var(--color-primary-active); }

.btn-secondary {
  background: var(--color-surface);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}
.btn-secondary:hover:not(:disabled) {
  border-color: var(--color-border-strong);
  background: var(--color-surface-alt);
}

.btn-danger {
  background: var(--color-danger);
  color: #fff;
}
.btn-danger:hover:not(:disabled) {
  background: #a4262c;
}

.btn-ghost {
  background: transparent;
  color: var(--color-primary);
}
.btn-ghost:hover:not(:disabled) {
  background: var(--color-primary-light);
}

/* States */
.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-block { width: 100%; }

.btn-loading {
  color: transparent !important;
}

.btn-spinner {
  position: absolute;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: btn-spin 0.6s linear infinite;
}

@keyframes btn-spin {
  to { transform: rotate(360deg); }
}
</style>
