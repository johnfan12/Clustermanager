<template>
  <div class="dashboard">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <h1 class="header-title">GPU 集群管理</h1>
        <div class="header-sub">集群总览与实例快照</div>
      </div>
      <div class="header-right">
        <span class="header-user">用户：{{ authStore.username || '-' }}</span>
        <button class="action-btn" @click="handleLogout">退出</button>
      </div>
    </header>

    <!-- Content -->
    <div class="dashboard-container">
      <!-- Loading overlay -->
      <LoadingState v-if="initialLoading" text="加载集群数据..." />

      <template v-else>
        <!-- Cluster Overview Section -->
        <ClusterOverview
          :nodes="clusterStore.nodes"
          :summary="clusterStore.summary"
          :current-node-id="authStore.currentNodeId"
          :token="authStore.token"
        />

        <!-- My Instances Section -->
        <MyInstances :instances="clusterStore.instances" />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useClusterStore } from '@/stores/cluster'
import { useToastStore } from '@/stores/toast'
import LoadingState from '@/components/LoadingState.vue'
import ClusterOverview from '@/features/ClusterOverview.vue'
import MyInstances from '@/features/MyInstances.vue'

const router = useRouter()
const authStore = useAuthStore()
const clusterStore = useClusterStore()
const toast = useToastStore()

const initialLoading = ref(true)

function handleLogout() {
  clusterStore.stopAutoRefresh()
  authStore.logout()
  router.push({ name: 'Login' })
}

onMounted(async () => {
  try {
    await clusterStore.fetchAll()
  } catch {
    toast.error('数据加载失败，请重新登录')
    handleLogout()
    return
  } finally {
    initialLoading.value = false
  }
  clusterStore.startAutoRefresh()
})

onUnmounted(() => {
  clusterStore.stopAutoRefresh()
})
</script>

<style scoped>
.dashboard {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* ── Header ── */
.app-header {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  padding: 0 24px;
  min-height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.header-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.header-sub {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  margin-top: 1px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.header-user {
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  font-size: var(--font-size-sm);
}

.action-btn {
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
  transition: all var(--transition-fast);
}

.action-btn:hover {
  border-color: var(--color-border-strong);
  background: var(--color-surface-alt);
}

/* ── Container ── */
.dashboard-container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 16px 24px;
  width: 100%;
  flex: 1;
}

@media (max-width: 720px) {
  .app-header {
    flex-direction: column;
    align-items: flex-start;
    padding: 12px 16px;
  }
  .header-right {
    justify-content: flex-start;
  }
  .dashboard-container {
    padding: 16px;
  }
}
</style>
