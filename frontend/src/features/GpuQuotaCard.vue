<template>
  <section class="gpu-quota-card">
    <div class="card-header">
      <h3>我的 GPU 卡时</h3>
      <button v-if="isAdmin" class="manage-link" @click="$emit('manage-quota')">管理额度</button>
    </div>

    <div v-if="loading" class="card-loading">加载中...</div>
    <div v-else-if="error" class="card-error">{{ error }}</div>
    <div v-else class="card-content">
      <!-- Quota summary -->
      <div class="quota-row">
        <div class="quota-item">
          <div class="quota-label">总额度</div>
          <div class="quota-value">{{ formatHours(quota.quota) }}</div>
          <div class="quota-unit">卡时</div>
        </div>
        <div class="quota-item">
          <div class="quota-label">已使用</div>
          <div class="quota-value used">{{ formatHours(quota.used) }}</div>
          <div class="quota-unit">卡时</div>
        </div>
        <div class="quota-item">
          <div class="quota-label">剩余</div>
          <div class="quota-value remaining" :class="{ insufficient: quota.remaining <= 0 }">
            {{ formatHours(quota.remaining) }}
          </div>
          <div class="quota-unit">卡时</div>
        </div>
      </div>

      <!-- Progress bar -->
      <div class="progress-container">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progressPercentage + '%' }"></div>
        </div>
        <div class="progress-label">
          使用率 {{ usagePercentage }}%
        </div>
      </div>

      <!-- Warning message -->
      <div v-if="quota.remaining <= 0" class="quota-warning">
        <strong>⚠ 卡时已用尽</strong>，无法创建或启动新实例。请联系管理员补充额度。
      </div>
      <div v-else-if="quota.remaining < 1" class="quota-warning">
        <strong>⚠ 卡时不足 1 小时</strong>，请尽快补充或释放已有实例。
      </div>

      <!-- Detail info -->
      <div class="quota-detail">
        <p>💡 卡时 = GPU 张数 × 运行小时数</p>
        <p>创建或启动实例时将扣减卡时；停止、删除或重建时进行计费结算。</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/shared/utils/api'

interface GpuHourQuota {
  quota: number
  used: number
  remaining: number
}

const props = defineProps<{
  isAdmin?: boolean
  nodeId?: string
}>()

const emit = defineEmits<{
  'manage-quota': []
}>()

const quota = ref<GpuHourQuota>({
  quota: 0,
  used: 0,
  remaining: 0,
})
const loading = ref(true)
const error = ref('')

const progressPercentage = computed(() => {
  if (quota.value.quota === 0) return 0
  return Math.min(100, Math.round((quota.value.used / quota.value.quota) * 100))
})

const usagePercentage = computed(() => progressPercentage.value)

function formatHours(hours: number): string {
  if (hours >= 1) {
    return hours.toFixed(2)
  }
  // Show minutes for fractional hours less than 1
  const minutes = Math.round(hours * 60)
  return `${minutes}min`
}

async function fetchQuota() {
  try {
    loading.value = true
    error.value = ''

    // If nodeId is provided, fetch from that node; otherwise use aggregated quota
    const endpoint = props.nodeId
      ? `/api/proxy/${props.nodeId}/api/quota/me`
      : '/api/quota/me'

    const response = await api.get<{
      gpu_hours_quota: number
      gpu_hours_used: number
      gpu_hours_remaining: number
    }>(endpoint)

    quota.value = {
      quota: response.gpu_hours_quota || 0,
      used: response.gpu_hours_used || 0,
      remaining: response.gpu_hours_remaining || 0,
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to fetch GPU quota'
    console.error('Failed to fetch GPU quota:', err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchQuota()
})

// Expose refresh method for parent to call
defineExpose({ fetchQuota })
</script>

<style scoped>
.gpu-quota-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.manage-link {
  background: none;
  border: none;
  color: #3b82f6;
  cursor: pointer;
  font-size: 14px;
  text-decoration: underline;
  padding: 0;
}

.manage-link:hover {
  color: #1d4ed8;
}

.card-loading,
.card-error {
  padding: 20px;
  text-align: center;
  color: #6b7280;
}

.card-error {
  color: #dc2626;
  background-color: #fee2e2;
  border-radius: 4px;
}

.card-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.quota-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
}

.quota-item {
  text-align: center;
  padding: 12px;
  background-color: #f9fafb;
  border-radius: 6px;
}

.quota-label {
  font-size: 12px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.quota-value {
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
}

.quota-value.used {
  color: #f59e0b;
}

.quota-value.remaining {
  color: #10b981;
}

.quota-value.remaining.insufficient {
  color: #dc2626;
}

.quota-unit {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 4px;
}

.progress-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-bar {
  width: 100%;
  height: 8px;
  background-color: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #10b981 0%, #f59e0b 70%, #dc2626 100%);
  transition: width 0.3s ease;
}

.progress-label {
  font-size: 12px;
  color: #6b7280;
  text-align: right;
}

.quota-warning {
  padding: 12px;
  background-color: #fef3c7;
  border-left: 4px solid #f59e0b;
  border-radius: 4px;
  font-size: 13px;
  color: #92400e;
}

.quota-warning strong {
  display: block;
  margin-bottom: 4px;
}

.quota-detail {
  padding: 12px;
  background-color: #eff6ff;
  border-radius: 4px;
  font-size: 12px;
  color: #1e40af;
  line-height: 1.6;
}

.quota-detail p {
  margin: 4px 0;
}
</style>
