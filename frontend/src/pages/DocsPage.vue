<template>
  <div class="docs-page">
    <header class="docs-header">
      <div class="docs-header-left">
        <button class="back-btn" type="button" @click="goBack">
          <span class="back-arrow">←</span>
          返回控制台
        </button>
      </div>
      <h1 class="docs-title">使用文档</h1>
    </header>

    <main class="docs-body">
      <nav class="docs-nav">
        <h3 class="docs-nav-title">目录</h3>
        <ul class="docs-nav-list">
          <li v-for="section in sections" :key="section.id">
            <a
              :class="['docs-nav-link', { active: activeSection === section.id }]"
              :href="`#${section.id}`"
              @click.prevent="scrollTo(section.id)"
            >
              {{ section.title }}
            </a>
          </li>
        </ul>
      </nav>

      <article class="docs-content">
        <section id="overview" class="doc-section">
          <h2>概述</h2>
          <p>
            本平台是一个 <strong>GPU 服务器集群管理控制台</strong>，用于管理和访问多节点 GPU 服务器。
            通过本控制台，您可以：
          </p>
          <ul>
            <li>查看所有节点的在线状态与 GPU 资源使用情况</li>
            <li>生成 SSH 命令快速连接到目标节点</li>
            <li>实时监控 GPU 负载、显存、功耗和温度</li>
            <li>查看节点历史运行状态（30 天运行状况）</li>
          </ul>
        </section>

        <section id="login" class="doc-section">
          <h2>登录与注册</h2>
          <div class="doc-step">
            <div class="step-number">1</div>
            <div class="step-content">
              <h3>首次使用</h3>
              <p>访问控制台地址，在登录页面点击 <strong>「注册」</strong> 创建账号。</p>
              <div class="tip-box">
                <strong>提示：</strong>第一个注册的用户会自动成为管理员。
              </div>
            </div>
          </div>
          <div class="doc-step">
            <div class="step-number">2</div>
            <div class="step-content">
              <h3>登录</h3>
              <p>输入用户名和密码，点击 <strong>「登录」</strong> 进入控制台。</p>
            </div>
          </div>
        </section>

        <section id="dashboard" class="doc-section">
          <h2>控制台总览</h2>
          <p>登录后进入控制台主页面，主要包含以下模块：</p>
          <div class="feature-grid">
            <div class="feature-card">
              <div class="feature-icon">📊</div>
              <h4>GPU 负载</h4>
              <p>展示每个节点的 GPU 总数、空闲数量、平均负载、显存占用、功耗和温度。点击节点名展开查看每张 GPU 的详细信息。</p>
            </div>
            <div class="feature-card">
              <div class="feature-icon">🔑</div>
              <h4>SSH 命令生成</h4>
              <p>选择目标节点和用户 ID，点击「生成」即可获取 SSH 登录命令。</p>
            </div>
            <div class="feature-card">
              <div class="feature-icon">🟢</div>
              <h4>节点状态</h4>
              <p>右上角状态按钮可查看所有节点在线/离线状态，以及过去 30 天的运行状况图表。</p>
            </div>
          </div>
        </section>

        <section id="ssh" class="doc-section">
          <h2>生成 SSH 命令</h2>
          <div class="doc-step">
            <div class="step-number">1</div>
            <div class="step-content">
              <h3>选择节点</h3>
              <p>在 <strong>「生成 SSH 命令」</strong> 区域，从下拉菜单选择要连接的节点。</p>
            </div>
          </div>
          <div class="doc-step">
            <div class="step-number">2</div>
            <div class="step-content">
              <h3>输入 User ID</h3>
              <p>输入您在目标节点上的用户名（通常与登录用户名一致）。</p>
            </div>
          </div>
          <div class="doc-step">
            <div class="step-number">3</div>
            <div class="step-content">
              <h3>生成并复制</h3>
              <p>
                点击 <strong>「生成」</strong> 按钮。生成的 SSH 命令会显示在下方表格中。
                点击 <strong>📋</strong> 图标或 <strong>「复制」</strong> 按钮即可复制到剪贴板。
              </p>
              <div class="code-example">
                <code>ssh -p 30002 user@example.com</code>
              </div>
            </div>
          </div>
          <div class="doc-step">
            <div class="step-number">4</div>
            <div class="step-content">
              <h3>使用 SSH 连接</h3>
              <p>将复制的命令粘贴到终端中执行即可连接到目标服务器。</p>
            </div>
          </div>
        </section>

        <section id="gpu" class="doc-section">
          <h2>GPU 监控</h2>
          <p><strong>GPU 负载</strong> 面板展示集群整体和各节点的 GPU 资源使用情况：</p>
          <table class="doc-table">
            <thead>
              <tr>
                <th>指标</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>GPU 空闲/总数</strong></td>
                <td>当前可用的 GPU 数量 / 节点 GPU 总数</td>
              </tr>
              <tr>
                <td><strong>平均负载</strong></td>
                <td>节点所有 GPU 的平均利用率，显示进度条</td>
              </tr>
              <tr>
                <td><strong>显存</strong></td>
                <td>显存已用量 / 总量（单位 GB）</td>
              </tr>
              <tr>
                <td><strong>功耗</strong></td>
                <td>当前功耗 / 功耗上限（单位 W）</td>
              </tr>
              <tr>
                <td><strong>温度</strong></td>
                <td>GPU 平均温度（单位 °C）</td>
              </tr>
            </tbody>
          </table>
          <div class="tip-box">
            <strong>提示：</strong>点击节点名称前的 <strong>「›」</strong> 箭头可以展开查看每张 GPU 的详细信息，包括负载、显存占用和分配状态。
          </div>
        </section>

        <section id="status" class="doc-section">
          <h2>节点状态与运行历史</h2>
          <p>
            点击右上角的 <strong>「状态正常」</strong> 或 <strong>「状态 N」</strong> 按钮，
            弹出节点状态面板，查看：
          </p>
          <ul>
            <li><strong>在线状态：</strong>绿色圆点表示在线，红色圆点表示离线</li>
            <li><strong>运行时间：</strong>在线节点显示 uptime，离线节点显示 issue 持续时间</li>
            <li>
              <strong>30 天运行图：</strong>彩色方格显示过去 30 天每天的状态
              <div class="legend-inline">
                <span class="legend-item"><span class="legend-cell all-ok"></span> 全天正常</span>
                <span class="legend-item"><span class="legend-cell partial"></span> 部分异常</span>
                <span class="legend-item"><span class="legend-cell all-fail"></span> 全天异常</span>
                <span class="legend-item"><span class="legend-cell no-data"></span> 无数据</span>
              </div>
            </li>
          </ul>
        </section>

        <section id="faq" class="doc-section">
          <h2>常见问题</h2>
          <div class="faq-item">
            <h4>Q: SSH 命令生成后提示连接失败？</h4>
            <p>
              A: 请确认目标节点处于 <strong>在线</strong> 状态（查看节点状态面板）。
              如果节点离线，SSH 隧道将无法建立。
            </p>
          </div>
          <div class="faq-item">
            <h4>Q: GPU 数据显示为 "—"？</h4>
            <p>
              A: 这通常表示节点离线或 GPU 状态接口暂时不可用。
              点击 <strong>「刷新」</strong> 按钮重新获取数据。
            </p>
          </div>
          <div class="faq-item">
            <h4>Q: 如何查看其他用户的 SSH 命令？</h4>
            <p>
              A: 只有管理员可以为其他用户生成 SSH 命令。
              普通用户只能使用自己的 User ID 生成。
            </p>
          </div>
        </section>
      </article>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const activeSection = ref('overview')

const sections = [
  { id: 'overview', title: '概述' },
  { id: 'login', title: '登录与注册' },
  { id: 'dashboard', title: '控制台总览' },
  { id: 'ssh', title: '生成 SSH 命令' },
  { id: 'gpu', title: 'GPU 监控' },
  { id: 'status', title: '节点状态与运行历史' },
  { id: 'faq', title: '常见问题' },
]

function goBack() {
  router.push({ name: 'Dashboard' })
}

function scrollTo(id: string) {
  const el = document.getElementById(id)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    activeSection.value = id
  }
}

function onScroll() {
  const scrollY = window.scrollY + 120
  for (let i = sections.length - 1; i >= 0; i--) {
    const el = document.getElementById(sections[i].id)
    if (el && el.offsetTop <= scrollY) {
      activeSection.value = sections[i].id
      return
    }
  }
  activeSection.value = sections[0].id
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.docs-page {
  min-height: 100vh;
  background: var(--color-bg);
}

/* ── Header ── */
.docs-header {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  padding: 0 24px;
  min-height: 48px;
  display: flex;
  align-items: center;
  gap: 16px;
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}

.docs-header-left {
  display: flex;
  align-items: center;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.back-btn:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.back-arrow {
  font-size: 14px;
}

.docs-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

/* ── Body layout ── */
.docs-body {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 32px;
  align-items: start;
}

/* ── Sidebar nav ── */
.docs-nav {
  position: sticky;
  top: 72px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 16px;
  box-shadow: var(--shadow-sm);
}

.docs-nav-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-muted);
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.docs-nav-list {
  list-style: none;
  display: grid;
  gap: 2px;
}

.docs-nav-link {
  display: block;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
  color: var(--color-text);
  text-decoration: none;
  transition: all var(--transition-fast);
}

.docs-nav-link:hover {
  background: var(--color-surface-alt);
  color: var(--color-primary);
}

.docs-nav-link.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: var(--font-weight-semibold);
}

/* ── Content ── */
.docs-content {
  display: grid;
  gap: 0;
}

.doc-section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 24px;
  margin-bottom: 16px;
  box-shadow: var(--shadow-sm);
}

.doc-section h2 {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--color-primary-light);
}

.doc-section p {
  font-size: var(--font-size-base);
  color: var(--color-text);
  line-height: 1.7;
  margin-bottom: 8px;
}

.doc-section ul {
  padding-left: 20px;
  margin-bottom: 8px;
}

.doc-section li {
  font-size: var(--font-size-base);
  color: var(--color-text);
  line-height: 1.7;
  margin-bottom: 4px;
}

/* ── Steps ── */
.doc-step {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--color-surface-alt);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.step-number {
  flex: 0 0 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-full);
  background: var(--color-primary);
  color: #fff;
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-bold);
}

.step-content h3 {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 4px;
}

.step-content p {
  margin-bottom: 6px;
}

/* ── Tip box ── */
.tip-box {
  background: var(--color-primary-light);
  border: 1px solid var(--color-primary-border);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  font-size: var(--font-size-sm);
  color: var(--color-text);
  margin-top: 8px;
}

/* ── Code example ── */
.code-example {
  margin-top: 8px;
}

.code-example code {
  display: inline-block;
  padding: 6px 14px;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  color: var(--color-text);
}

/* ── Feature grid ── */
.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.feature-card {
  padding: 16px;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  transition: box-shadow var(--transition-fast), border-color var(--transition-fast);
}

.feature-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-md);
}

.feature-icon {
  font-size: 24px;
  margin-bottom: 8px;
}

.feature-card h4 {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
  margin-bottom: 4px;
}

.feature-card p {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  line-height: 1.5;
}

/* ── Table ── */
.doc-table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
}

.doc-table th,
.doc-table td {
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  font-size: var(--font-size-sm);
  text-align: left;
}

.doc-table th {
  background: var(--color-surface-alt);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.doc-table td {
  color: var(--color-text);
}

/* ── Legend ── */
.legend-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 6px;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.legend-cell {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
}

.legend-cell.all-ok { background: #2da44e; }
.legend-cell.partial { background: #f0883e; }
.legend-cell.all-fail { background: #cf222e; }
.legend-cell.no-data { background: #d0d7de; }

/* ── FAQ ── */
.faq-item {
  padding: 12px;
  background: var(--color-surface-alt);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  margin-bottom: 10px;
}

.faq-item h4 {
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
  margin-bottom: 4px;
}

.faq-item p {
  font-size: var(--font-size-sm);
  color: var(--color-text);
  line-height: 1.6;
  margin-bottom: 0;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .docs-body {
    grid-template-columns: 1fr;
    padding: 16px;
    gap: 16px;
  }

  .docs-nav {
    position: static;
  }

  .feature-grid {
    grid-template-columns: 1fr;
  }
}
</style>
