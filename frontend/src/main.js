import "./styles.css";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const defaultConfig = {
  app_display_name: "Clustermanager",
  auth_required: true,
  auth_mode: "account",
  allow_register: true
};
let authAction = "login";
const state = {
  config: { ...defaultConfig },
  token: localStorage.getItem("simpleClusterToken") || "",
  user: null,
  nodes: [],
  tunnels: [],
  selectedNode: "all"
};

const $ = (id) => document.getElementById(id);

function applyConfig(config) {
  state.config = { ...defaultConfig, ...(config || {}) };
  const appName = state.config.app_display_name || defaultConfig.app_display_name;
  document.title = appName;
  document.querySelectorAll("[data-app-name]").forEach((element) => {
    element.textContent = appName;
  });
}

async function loadConfig() {
  try {
    applyConfig(await api("/api/config"));
  } catch (error) {
    applyConfig(defaultConfig);
    setNotice("loginNotice", error.message, true);
  }
}

function setNotice(id, message, isError = false) {
  const el = $(id);
  el.textContent = message || "";
  el.classList.toggle("error", Boolean(isError));
}

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeaders() };
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
  }
  if (!response.ok) {
    const detail = data && data.detail ? data.detail : "请求失败";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data || {};
}

function showLogin() {
  $("loginScreen").hidden = false;
  $("appScreen").hidden = true;
  renderAuthMode();
}

function showApp() {
  $("loginScreen").hidden = true;
  $("appScreen").hidden = false;
  $("logoutButton").hidden = !state.config.auth_required;
  $("currentUser").textContent = state.user
    ? `${state.user.username}${state.user.is_admin ? " · 管理员" : ""}`
    : "";
  if (state.user && !$("sshUserId").value) {
    $("sshUserId").value = state.user.username;
  }
}

function renderAuthMode() {
  const accountMode = state.config.auth_mode === "account";
  $("registerTab").hidden = !accountMode || !state.config.allow_register;
  $("loginTab").style.gridColumn = $("registerTab").hidden ? "1 / -1" : "";
  $("confirmPasswordRow").hidden = authAction !== "register";
  $("loginTab").classList.toggle("active", authAction === "login");
  $("registerTab").classList.toggle("active", authAction === "register");
  $("loginSubmit").textContent = authAction === "register" ? "注册并登录" : "登录";
  $("authHint").textContent = accountMode
    ? (authAction === "register" ? "注册后可直接登录控制台" : "")
    : "";
}

function renderNodes() {
  const nodeList = $("nodeList");
  nodeList.innerHTML = "";
  const allButton = document.createElement("button");
  allButton.type = "button";
  allButton.className = `node-button ${state.selectedNode === "all" ? "active" : ""}`;
  allButton.textContent = "全部节点";
  allButton.onclick = () => { state.selectedNode = "all"; renderNodes(); renderTunnels(); };
  nodeList.appendChild(allButton);

  const createNode = $("createNode");
  createNode.innerHTML = "";
  for (const node of state.nodes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `node-button ${state.selectedNode === node.id ? "active" : ""}`;
    button.textContent = node.name;
    button.onclick = () => { state.selectedNode = node.id; renderNodes(); renderTunnels(); };
    nodeList.appendChild(button);

    const option = document.createElement("option");
    option.value = node.id;
    option.textContent = node.name;
    createNode.appendChild(option);
  }
}

function filteredTunnels() {
  if (state.selectedNode === "all") return state.tunnels;
  return state.tunnels.filter((tunnel) => tunnel.node_id === state.selectedNode);
}

function renderTunnels() {
  const rows = $("tunnelRows");
  rows.innerHTML = "";
  const tunnels = filteredTunnels();
  $("emptyState").hidden = tunnels.length > 0;

  for (const tunnel of tunnels) {
    const tr = document.createElement("tr");
    const sshCommand = tunnel.ssh_command || `ssh -p ${tunnel.remote_port} ${tunnel.owner}@${tunnel.public_host}`;
    const statusClass = tunnel.status === "error" ? "status error" : "status";
    tr.innerHTML = `
      <td>${escapeHtml(tunnel.node_name || tunnel.node_id)}</td>
      <td>${escapeHtml(tunnel.name)}</td>
      <td class="mono">${escapeHtml(sshCommand)}</td>
      <td><span class="${statusClass}" title="${escapeHtml(tunnel.error || "")}">${escapeHtml(tunnel.status)}</span></td>
      <td>${escapeHtml(tunnel.owner || "")}</td>
      <td>
        <div class="row-actions">
          <button class="secondary" type="button" data-copy="${escapeHtml(sshCommand)}">复制</button>
          <button class="secondary" type="button" data-hide="${escapeHtml(tunnel.saved_key || accessKey(tunnel.node_id, tunnel.owner))}">隐藏</button>
        </div>
      </td>
    `;
    rows.appendChild(tr);
  }

  rows.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copy);
      setNotice("tableNotice", "已复制");
    });
  });
  rows.querySelectorAll("[data-hide]").forEach((button) => {
    button.addEventListener("click", () => {
      forgetAccess(button.dataset.hide);
      renderTunnels();
    });
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadData() {
  const nodesPayload = await api("/api/nodes");
  state.nodes = nodesPayload.nodes || [];
  renderNodes();
  await restoreSavedAccesses();
}

function accessKey(nodeId, userId) {
  return `${encodeURIComponent(nodeId)}:${encodeURIComponent(userId)}`;
}

function savedAccessStorageKey() {
  const username = state.user && state.user.username ? state.user.username : "anonymous";
  return `simpleClusterSshAccesses:${username}`;
}

function readSavedAccesses() {
  try {
    const parsed = JSON.parse(localStorage.getItem(savedAccessStorageKey()) || "[]");
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item) => item && item.node_id && item.user_id);
  } catch {
    return [];
  }
}

function writeSavedAccesses(items) {
  localStorage.setItem(savedAccessStorageKey(), JSON.stringify(items));
}

function rememberAccess(nodeId, userId) {
  const next = readSavedAccesses().filter((item) => accessKey(item.node_id, item.user_id) !== accessKey(nodeId, userId));
  next.unshift({ node_id: nodeId, user_id: userId });
  writeSavedAccesses(next.slice(0, 20));
}

function forgetAccess(key) {
  writeSavedAccesses(readSavedAccesses().filter((item) => accessKey(item.node_id, item.user_id) !== key));
  state.tunnels = state.tunnels.filter((item) => (item.saved_key || accessKey(item.node_id, item.owner)) !== key);
}

async function fetchSshAccess(nodeId, userId) {
  const payload = await api(`/api/nodes/${encodeURIComponent(nodeId)}/ssh-access`, {
    method: "POST",
    body: { user_id: userId }
  });
  if (!payload.access) {
    return null;
  }
  payload.access.saved_key = accessKey(nodeId, userId);
  payload.access.requested_user_id = userId;
  return payload.access;
}

async function restoreSavedAccesses() {
  const saved = readSavedAccesses();
  if (!saved.length) {
    state.tunnels = [];
    renderTunnels();
    return;
  }

  const validNodeIds = new Set(state.nodes.map((node) => node.id));
  const restored = [];
  const errors = [];
  for (const item of saved) {
    if (!validNodeIds.has(item.node_id)) {
      continue;
    }
    try {
      const access = await fetchSshAccess(item.node_id, item.user_id);
      if (access) {
        restored.push(access);
      }
    } catch (error) {
      errors.push(error.message);
    }
  }
  state.tunnels = restored;
  renderTunnels();
  setNotice("tableNotice", errors.length ? errors.join("；") : "", errors.length > 0);
}

async function bootstrap() {
  await loadConfig();
  if (!state.config.auth_required) {
    try {
      state.user = await api("/api/me");
      showApp();
      await loadData();
    } catch (error) {
      showApp();
      setNotice("tableNotice", error.message, true);
    }
    return;
  }
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    state.user = await api("/api/me");
    showApp();
    await loadData();
  } catch (error) {
    localStorage.removeItem("simpleClusterToken");
    state.token = "";
    showLogin();
    setNotice("loginNotice", error.message, true);
  }
}

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setNotice("loginNotice", "");
  if (authAction === "register" && $("loginPassword").value !== $("confirmPassword").value) {
    setNotice("loginNotice", "两次输入的密码不一致", true);
    return;
  }
  try {
    const payload = await api(authAction === "register" ? "/api/register" : "/api/login", {
      method: "POST",
      body: {
        username: $("loginUsername").value,
        password: $("loginPassword").value
      }
    });
    state.token = payload.access_token;
    state.user = payload.user;
    localStorage.setItem("simpleClusterToken", state.token);
    $("loginPassword").value = "";
    $("confirmPassword").value = "";
    showApp();
    await loadData();
  } catch (error) {
    setNotice("loginNotice", error.message, true);
  }
});

$("loginTab").addEventListener("click", () => {
  authAction = "login";
  setNotice("loginNotice", "");
  renderAuthMode();
});

$("registerTab").addEventListener("click", () => {
  authAction = "register";
  setNotice("loginNotice", "");
  renderAuthMode();
});

$("createForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  setNotice("formNotice", "");
  const nodeId = $("createNode").value;
  const userId = $("sshUserId").value.trim();
  try {
    const access = await fetchSshAccess(nodeId, userId);
    if (!access) {
      throw new Error("节点未返回 SSH 命令");
    }
    rememberAccess(nodeId, userId);
    await restoreSavedAccesses();
    setNotice("formNotice", "已生成 SSH 命令");
  } catch (error) {
    setNotice("formNotice", error.message, true);
  }
});

$("refreshButton").addEventListener("click", loadData);
$("logoutButton").addEventListener("click", () => {
  if (!state.config.auth_required) {
    return;
  }
  localStorage.removeItem("simpleClusterToken");
  state.token = "";
  state.user = null;
  showLogin();
});

bootstrap();
