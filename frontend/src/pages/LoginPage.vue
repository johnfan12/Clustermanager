<template>
  <div class="auth-page">
    <div class="auth-shell">
      <div class="auth-main">
        <div class="auth-header">
          <h1 class="auth-title">{{ appDisplayName }}</h1>
          <p class="auth-subtitle">注册或登录后即可进入管理。</p>
        </div>

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
import { useClusterStore, type AuthNode } from '@/stores/cluster'
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
const appDisplayName = computed(() => clusterStore.appDisplayName || 'GPU 集群管理')

// ── Methods ──
function pickDefaultNodeId(nodes: AuthNode[], preferredNodeId: string) {
  const matchedNode = nodes.find((node) => node.node_id === preferredNodeId)
  if (matchedNode) return matchedNode.node_id

  const onlineNode = nodes.find((node) => node.online)
  if (onlineNode) return onlineNode.node_id

  return nodes[0]?.node_id || ''
}

function ensureSelectedNode() {
  const nextNodeId = pickDefaultNodeId(authNodes.value, selectedNodeId.value)
  selectedNodeId.value = nextNodeId
  if (nextNodeId) {
    localStorage.setItem('cluster_node_id', nextNodeId)
  } else {
    localStorage.removeItem('cluster_node_id')
  }

  return authNodes.value.find((node: AuthNode) => node.node_id === nextNodeId) || null
}

async function doLogin() {
  loginError.value = ''
  const node = ensureSelectedNode()
  if (!node) {
    loginError.value = '当前暂无可用节点，请联系管理员检查集群配置'
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
      node_id?: string | null
    }>('/api/auth/login', {
      node_id: node.node_id,
      username: loginForm.username,
      password: loginForm.password
    }, { skipAuth: true })

    authStore.setSession(data)
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
  const node = ensureSelectedNode()
  if (!node) {
    registerError.value = '当前暂无可用节点，请联系管理员检查集群配置'
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
      node_id?: string | null
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
  ensureSelectedNode()
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
  width: min(520px, 100%);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
}

.auth-main {
  padding: 36px 32px 32px;
  display: flex;
  flex-direction: column;
}

.auth-header {
  margin-bottom: 22px;
}

.auth-title {
  font-size: var(--font-size-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 8px;
}

.auth-subtitle {
  color: var(--color-text-muted);
  font-size: var(--font-size-base);
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

@media (max-width: 720px) {
  .auth-main {
    padding: 24px 20px;
  }
}
</style>
