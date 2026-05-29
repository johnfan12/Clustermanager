<template>
  <div :class="['loading-state', { 'loading-overlay': overlay }]">
    <div class="loading-spinner" />
    <span v-if="text" class="loading-text">{{ text }}</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    text?: string
    overlay?: boolean
  }>(),
  {
    text: '',
    overlay: false
  }
)
</script>

<style scoped>
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 20px;
}

.loading-overlay {
  position: fixed;
  inset: 0;
  background: var(--color-bg);
  z-index: var(--z-overlay);
}

.loading-spinner {
  width: 28px;
  height: 28px;
  border: 2.5px solid var(--color-border);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.loading-text {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
