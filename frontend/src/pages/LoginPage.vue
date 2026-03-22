<template>
  <div class="auth-page">
    <div class="auth-shell">
      <!-- Left: Node Selection -->
      <div class="auth-side">
        <h1 class="auth-title">GPU 集群管理</h1>
        <p class="auth-subtitle">选择目标服务器，注册或登录后即可进入管理。</p>

        <div class="section-label">
          <h2>可用服务器</h2>
          <span class="tip">{{ nodeSummaryText }}</span>
        </div>

        <div class="node-list">
          <div
            v-if="authNodes.length === 0"
            class="node-empty"
          >
            暂无可用节点
          </div>
          <button
            v-for="node in authNodes"
            :key="node.node_id"
            :class="['node-card', { selected: node.node_id === selectedNodeId, offline: !node.online }]"
            type="button"
            @click="selectNode(node.node_id)"
          >
            <div class="node-card-header">
              <div>
                <div class="node-name">{{ node.name || node.node_id }}</div>
                <div class="node-meta">{{ node.node_id }}</div>
              </div>
              <span class="node-status">
                <span :class="['dot', node.online ? 'online' : 'offline']" />
                {{ node.online ? '在线' : '离线' }}
              </span>
            </div>
            <div class="node-tags">
              <span class="tag">{{ node.allow_register ? '可注册' : '仅登录' }}</span>
              <span v-if="node.node_id === selectedNodeId" class="tag primary">当前选择</span>
            </div>
          </button>
        </div>
      </div>

      <!-- Right: Auth Form -->
      <div class="auth-main">
        <div class="tabs">
          <button
            :class="['tab', { active: mode === 'login' }]"
            type="button"
            @click="mode = 'login'"
          >
            登录
          </button>
          <button
            :class="['tab', { active: mode === 'register' }]"
            type="button"
            @click="mode = 'register'"
          >
            注册
          </button>
        </div>

        <!-- Selected node indicator -->
        <div class="selected-node-box">
          <div class="selected-node-text">
            <strong>{{ selectedNodeDisplay.name }}</strong>
            <div class="selected-node-meta-text">{{ selectedNodeDisplay.meta }}</div>
          </div>
          <span :class="['tag', { primary: selectedNodeDisplay.online }]">
            {{ selectedNodeDisplay.tag }}
          </span>
        </div>

        <!-- Login Form -->
        <form v-if="mode === 'login'" class="auth-form" @submit.prevent="doLogin">
          <div class="field">
            <label for="login-username">用户名</label>
            <input
              id="login-username"
              v-model="loginForm.username"
              type="text"
              placeholder="请输入用户名"
              autocomplete="username"
              @keydown.enter="focusPassword"
            />
          </div>
          <div class="field">
            <label for="login-password">密码</label>
            <input
              id="login-password"
              ref="loginPwdRef"
              v-model="loginForm.password"
              type="password"
              placeholder="请输入密码"
              autocomplete="current-password"
            />
          </div>
          <AppButton variant="primary" block :loading="loginLoading" type="submit">
            登录
          </AppButton>
          <div :class="['feedback', { success: false }]">{{ loginError }}</div>
        </form>

        <!-- Register Form -->
        <form v-if="mode === 'register'" class="auth-form" @submit.prevent="doRegister">
          <div class="field">
            <label for="register-username">用户名</label>
            <input
              id="register-username"
              v-model="registerForm.username"
              type="text"
              minlength="3"
              placeholder="仅支持字母、数字和下划线"
              autocomplete="username"
            />
          </div>
          <div class="field">
            <label for="register-email">邮箱</label>
            <input
              id="register-email"
              v-model="registerForm.email"
              type="email"
              placeholder="请输入邮箱"
              autocomplete="email"
            />
          </div>
          <div class="field">
            <label for="register-password">密码</label>
            <input
              id="register-password"
              v-model="registerForm.password"
              type="password"
              minlength="6"
              placeholder="至少 6 位"
              autocomplete="new-password"
            />
          </div>
          <AppButton variant="primary" block :loading="registerLoading" type="submit">
            注册并登录
          </AppButton>
          <div :class="['feedback', { success: registerSuccess }]">{{ registerError }}</div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore, type UserInfo } from '@/stores/auth'
import { useClusterStore } from '@/stores/cluster'
import { useToastStore } from '@/stores/toast'
import { api } from '@/shared/utils/api'
import AppButton from '@/components/AppButton.vue'

const router = useRouter()
const authStore = useAuthStore()
const clusterStore = useClusterStore()
const toast = useToastStore()

// Template refs
const loginPwdRef = ref<HTMLInputElement>()

function focusPassword() {
  loginPwdRef.value?.focus()
}

// ── State ──
const mode = ref<'login' | 'register'>('login')
const selectedNodeId = ref(localStorage.getItem('cluster_node_id') || '')

const loginForm = reactive({ username: '', password: '' })
const registerForm = reactive({ username: '', email: '', password: '' })

const loginLoading = ref(false)
const registerLoading = ref(false)
const loginError = ref('')
const registerError = ref('')
const registerSuccess = ref(false)

// ── Computed ──
const authNodes = computed(() => clusterStore.authNodes)

const nodeSummaryText = computed(() => {
  if (!authNodes.value.length) return '加载中...'
  const online = authNodes.value.filter((n) => n.online).length
  return `${authNodes.value.length} 个节点，在线 ${online} 个`
})

const selectedNode = computed(() =>
  authNodes.value.find((n) => n.node_id === selectedNodeId.value) || null
)

const selectedNodeDisplay = computed(() => {
  const node = selectedNode.value
  if (!node) {
    return { name: '尚未选择服务器', meta: '请先在左侧选中一个可用节点', tag: '未选择', online: false }
  }
  return {
    name: node.name || node.node_id,
    meta: node.online
      ? (node.allow_register ? '在线 · 可注册新账号' : '在线 · 仅支持已有账号登录')
      : '当前离线',
    tag: node.online ? '在线' : '离线',
    online: node.online
  }
})

// ── Methods ──
function selectNode(nodeId: string) {
  selectedNodeId.value = nodeId
  localStorage.setItem('cluster_node_id', nodeId)
}

async function doLogin() {
  loginError.value = ''
  const node = selectedNode.value
  if (!node) {
    loginError.value = '请先选择服务器'
    return
  }
  if (!loginForm.username || !loginForm.password) {
    loginError.value = '请填写用户名和密码'
    return
  }

  loginLoading.value = true
  try {
    const data = await api.post<{
      access_token: string
      username: string
      is_admin: boolean
      user: UserInfo
      node_id: string
      node_name: string
      entry_url: string
    }>('/api/auth/login', {
      node_id: node.node_id,
      username: loginForm.username,
      password: loginForm.password
    }, { skipAuth: true })

    authStore.setSession(data)
    toast.success(`已登录 ${data.node_name || node.name}`)
    router.push({ name: 'Dashboard' })
  } catch (e: unknown) {
    loginError.value = (e as Error).message || '登录失败'
  } finally {
    loginLoading.value = false
  }
}

async function doRegister() {
  registerError.value = ''
  registerSuccess.value = false
  const node = selectedNode.value
  if (!node) {
    registerError.value = '请先选择服务器'
    return
  }
  if (!registerForm.username || !registerForm.email || !registerForm.password) {
    registerError.value = '请填写完整注册信息'
    return
  }

  registerLoading.value = true
  try {
    const data = await api.post<{
      access_token: string
      username: string
      is_admin: boolean
      user: UserInfo
      node_id: string
      node_name: string
      entry_url: string
      message?: string
    }>('/api/auth/register', {
      node_id: node.node_id,
      username: registerForm.username,
      email: registerForm.email,
      password: registerForm.password
    }, { skipAuth: true })

    authStore.setSession(data)
    registerSuccess.value = true
    registerError.value = data.message || '注册成功'
    toast.success(data.message || '注册成功')
    router.push({ name: 'Dashboard' })
  } catch (e: unknown) {
    registerError.value = (e as Error).message || '注册失败'
  } finally {
    registerLoading.value = false
  }
}

// ── Lifecycle ──
onMounted(async () => {
  await clusterStore.fetchAuthNodes()
  // Auto select first node if none selected
  if (!selectedNodeId.value && authNodes.value.length) {
    selectedNodeId.value = authNodes.value[0].node_id
  }
  // Verify the selected node still exists
  const exists = authNodes.value.some((n) => n.node_id === selectedNodeId.value)
  if (!exists && authNodes.value.length) {
    selectedNodeId.value = authNodes.value[0].node_id
  }
})

</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-xl);
  background: var(--color-bg);
}

.auth-shell {
  width: min(1060px, 100%);
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-md);
}

/* ── Left side ── */
.auth-side {
  padding: 36px 32px 32px;
  background: var(--color-surface-alt);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
}

.auth-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 8px;
}

.auth-subtitle {
  color: var(--color-text-muted);
  margin-bottom: 24px;
  font-size: var(--font-size-base);
}

.section-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.section-label h2 {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.tip {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}

.node-list {
  display: grid;
  gap: 8px;
  flex: 1;
  overflow-y: auto;
  max-height: 360px;
  padding-right: 4px;
}

.node-empty {
  text-align: center;
  padding: 24px 12px;
  color: var(--color-text-muted);
}

.node-card {
  display: block;
  width: 100%;
  text-align: left;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-text);
  transition: all var(--transition-fast);
}

.node-card:hover {
  border-color: var(--color-border-subtle);
  background: var(--color-surface-alt);
}

.node-card.selected {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
  box-shadow: inset 3px 0 0 var(--color-primary);
}

.node-card.offline { opacity: 0.55; }

.node-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.node-name {
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-base);
}

.node-meta {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  margin-top: 1px;
}

.node-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
  white-space: nowrap;
  color: var(--color-text-muted);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.dot.online { background: var(--color-success); }
.dot.offline { background: #a19f9d; }

.node-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
  border: 1px solid var(--color-border);
  color: var(--color-text-muted);
  background: var(--color-surface-alt);
}

.tag.primary {
  border-color: var(--color-primary-border);
  color: var(--color-primary);
  background: var(--color-primary-light);
}

/* ── Right side ── */
.auth-main {
  padding: 36px 32px 32px;
  display: flex;
  flex-direction: column;
}

.tabs {
  display: inline-flex;
  border-bottom: 2px solid var(--color-border);
  margin-bottom: 22px;
  align-self: flex-start;
  gap: 0;
}

.tab {
  min-width: 80px;
  padding: 8px 16px;
  border-radius: 0;
  background: transparent;
  color: var(--color-text-muted);
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-base);
  transition: all var(--transition-fast);
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
}

.tab:hover { color: var(--color-text); }

.tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}

.selected-node-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-md);
  background: var(--color-primary-light);
  margin-bottom: 20px;
}

.selected-node-text strong {
  color: var(--color-text);
  font-size: var(--font-size-base);
}

.selected-node-meta-text {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  margin-top: 2px;
}

.auth-form {
  display: grid;
  gap: 14px;
}

.field label {
  display: block;
  margin-bottom: 4px;
  color: var(--color-text);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
}

.field input {
  width: 100%;
  padding: 7px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: var(--font-size-base);
  transition: border-color var(--transition-fast);
}

.field input::placeholder { color: var(--color-text-placeholder); }

.field input:focus {
  border-color: var(--color-primary);
  outline: none;
}

.feedback {
  min-height: 18px;
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}

.feedback.success { color: var(--color-success); }

/* ── Responsive ── */
@media (max-width: 960px) {
  .auth-shell { grid-template-columns: 1fr; }
  .auth-side {
    border-right: none;
    border-bottom: 1px solid var(--color-border);
  }
  .node-list { max-height: 220px; }
}

@media (max-width: 720px) {
  .selected-node-box {
    flex-direction: column;
    align-items: flex-start;
  }
  .auth-side,
  .auth-main {
    padding: 24px 20px;
  }
}
</style>
