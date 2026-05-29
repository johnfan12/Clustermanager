"""Simplified central console for user-owned FRP tunnels."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from auth import (
    Principal,
    authenticate_local_user,
    create_access_token,
    get_current_principal,
)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

LOG_DIR = BASE_DIR / os.environ.get("SIMPLE_LOG_DIR", "logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "simple-clustermanager.log"),
        logging.StreamHandler(),
    ],
)
LOGGER = logging.getLogger("simple_clustermanager")

APP_DISPLAY_NAME = os.environ.get("SIMPLE_APP_DISPLAY_NAME", "简化服务器管理")
INTERNAL_SERVICE_TOKEN = os.environ.get("SIMPLE_INTERNAL_SERVICE_TOKEN") or os.environ.get(
    "INTERNAL_SERVICE_TOKEN", "change-this-internal-service-token"
)
REQUEST_TIMEOUT = float(os.environ.get("SIMPLE_NODE_REQUEST_TIMEOUT", "12"))
AUTH_MODE = os.environ.get("SIMPLE_AUTH_MODE", "local").strip().lower()
CORS_ALLOW_ORIGINS = [
    item.strip()
    for item in os.environ.get("SIMPLE_CORS_ALLOW_ORIGINS", "http://localhost:9999").split(",")
    if item.strip()
]


class LoginRequest(BaseModel):
    """Login payload for local PAM authentication."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=4096)


class TunnelCreateRequest(BaseModel):
    """Create one tunnel on a selected node."""

    name: str | None = Field(default=None, max_length=64)
    local_host: str = Field(default="127.0.0.1", min_length=1, max_length=255)
    local_port: int = Field(ge=1, le=65535)
    remote_port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("local_host")
    @classmethod
    def normalize_local_host(cls, value: str) -> str:
        return value.strip()


def _load_nodes() -> list[dict[str, str]]:
    raw = os.environ.get("SIMPLE_NODES_JSON") or os.environ.get("NODES_JSON") or ""
    parsed: Any = None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Failed to parse SIMPLE_NODES_JSON/NODES_JSON: %s", exc)

    nodes: list[dict[str, str]] = []
    if isinstance(parsed, dict):
        for node_id, config in parsed.items():
            if not isinstance(config, dict):
                continue
            api = str(config.get("api") or config.get("api_base") or "").strip()
            if not api:
                continue
            nodes.append(
                {
                    "id": str(node_id),
                    "name": str(config.get("name") or node_id),
                    "api": api.rstrip("/"),
                    "public_host": str(config.get("public_host") or config.get("host") or ""),
                }
            )
    elif isinstance(parsed, list):
        for index, config in enumerate(parsed, start=1):
            if not isinstance(config, dict):
                continue
            api = str(config.get("api") or config.get("api_base") or "").strip()
            if not api:
                continue
            node_id = str(config.get("id") or f"node{index}")
            nodes.append(
                {
                    "id": node_id,
                    "name": str(config.get("name") or node_id),
                    "api": api.rstrip("/"),
                    "public_host": str(config.get("public_host") or config.get("host") or ""),
                }
            )

    if nodes:
        return nodes

    return [
        {
            "id": os.environ.get("SIMPLE_NODE_ID", "node1"),
            "name": os.environ.get("SIMPLE_NODE_NAME", "节点 1"),
            "api": os.environ.get("SIMPLE_NODE_API", "http://127.0.0.1:18881").rstrip("/"),
            "public_host": os.environ.get("SIMPLE_PUBLIC_HOST", ""),
        }
    ]


NODES = _load_nodes()
NODES_BY_ID = {node["id"]: node for node in NODES}
AUTH_NODE_ID = os.environ.get("SIMPLE_AUTH_NODE_ID", NODES[0]["id"] if NODES else "")


def _public_node(node: dict[str, str]) -> dict[str, str]:
    return {
        "id": node["id"],
        "name": node["name"],
        "public_host": node.get("public_host", ""),
    }


def _node_or_404(node_id: str) -> dict[str, str]:
    node = NODES_BY_ID.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found.")
    return node


def _node_headers(principal: Principal) -> dict[str, str]:
    return {
        "X-Internal-Token": INTERNAL_SERVICE_TOKEN,
        "X-User": principal.username,
        "X-User-Is-Admin": "true" if principal.is_admin else "false",
    }


def _extract_node_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message")
        if isinstance(detail, str) and detail:
            return detail
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)
    text = response.text.strip()
    return text or "Node request failed."


async def _node_request(
    node: dict[str, str],
    method: str,
    path: str,
    principal: Principal,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{node['api']}{path}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                headers=_node_headers(principal),
                json=json_body,
                params=params,
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{node['name']} is unavailable: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"{node['name']}: {_extract_node_error(response)}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"{node['name']} returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail=f"{node['name']} returned invalid payload.")
    return payload


async def _authenticate_node_user(username: str, password: str) -> Principal:
    node = _node_or_404(AUTH_NODE_ID)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{node['api']}/api/login",
                json={"username": username, "password": password},
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"{node['name']} is unavailable: {exc}",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_extract_node_error(response))

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"{node['name']} returned invalid JSON.") from exc

    user = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict):
        raise HTTPException(status_code=502, detail=f"{node['name']} returned invalid login payload.")
    return Principal(username=str(user.get("username") or username), is_admin=bool(user.get("is_admin")))


async def _authenticate_console_user(username: str, password: str) -> Principal:
    if AUTH_MODE == "node":
        return await _authenticate_node_user(username, password)
    if AUTH_MODE != "local":
        raise HTTPException(status_code=500, detail=f"Unsupported SIMPLE_AUTH_MODE: {AUTH_MODE}")
    return authenticate_local_user(username, password)


INDEX_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__APP_NAME__</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f7f8;
      color: #17202a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: #f5f7f8;
    }
    button, input, select {
      font: inherit;
    }
    button {
      border: 0;
      border-radius: 6px;
      background: #0f766e;
      color: #fff;
      min-height: 38px;
      padding: 0 14px;
      cursor: pointer;
    }
    button.secondary {
      background: #e8eef0;
      color: #1f2a37;
    }
    button.danger {
      background: #b42318;
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    input, select {
      width: 100%;
      min-height: 38px;
      border: 1px solid #cbd5dc;
      border-radius: 6px;
      background: #fff;
      padding: 0 10px;
      color: #17202a;
    }
    label {
      display: grid;
      gap: 6px;
      color: #52616b;
      font-size: 13px;
      font-weight: 600;
    }
    .login-shell {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .login-panel {
      width: min(420px, 100%);
      border: 1px solid #dbe3e8;
      border-radius: 8px;
      background: #fff;
      padding: 28px;
      box-shadow: 0 18px 42px rgba(15, 23, 42, 0.08);
    }
    .login-panel h1 {
      margin: 0 0 22px;
      font-size: 24px;
      letter-spacing: 0;
    }
    .login-panel form {
      display: grid;
      gap: 16px;
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: 58px 1fr;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 20px;
      border-bottom: 1px solid #dbe3e8;
      background: #fff;
    }
    .brand {
      font-size: 18px;
      font-weight: 750;
      letter-spacing: 0;
    }
    .userbar {
      display: flex;
      align-items: center;
      gap: 10px;
      color: #52616b;
      font-size: 14px;
    }
    .layout {
      display: grid;
      grid-template-columns: 260px minmax(0, 1fr);
      min-height: 0;
    }
    .sidebar {
      border-right: 1px solid #dbe3e8;
      background: #fff;
      padding: 18px;
      display: grid;
      align-content: start;
      gap: 14px;
    }
    .sidebar h2, .content h2 {
      margin: 0;
      font-size: 16px;
      letter-spacing: 0;
    }
    .node-list {
      display: grid;
      gap: 8px;
    }
    .node-button {
      width: 100%;
      justify-content: flex-start;
      text-align: left;
      background: #edf4f3;
      color: #1f2a37;
    }
    .node-button.active {
      background: #0f766e;
      color: #fff;
    }
    .content {
      padding: 18px 20px 28px;
      display: grid;
      gap: 18px;
      align-content: start;
      min-width: 0;
    }
    .panel {
      border: 1px solid #dbe3e8;
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
    }
    .panel-head {
      min-height: 52px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid #e5eaee;
    }
    .create-grid {
      display: grid;
      grid-template-columns: minmax(150px, 1.1fr) minmax(130px, 0.9fr) minmax(110px, 0.65fr) minmax(120px, 0.65fr) minmax(110px, 0.65fr) auto;
      align-items: end;
      gap: 12px;
      padding: 14px;
    }
    .table-wrap {
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 860px;
    }
    th, td {
      padding: 12px 14px;
      border-bottom: 1px solid #edf1f4;
      text-align: left;
      vertical-align: middle;
      font-size: 14px;
      white-space: nowrap;
    }
    th {
      color: #52616b;
      font-size: 12px;
      text-transform: uppercase;
      background: #fafbfc;
    }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    .status {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 0 8px;
      border-radius: 999px;
      background: #edf4f3;
      color: #0f766e;
      font-size: 12px;
      font-weight: 700;
    }
    .status.error {
      background: #fee4e2;
      color: #b42318;
    }
    .row-actions {
      display: flex;
      gap: 8px;
    }
    .empty {
      color: #52616b;
      padding: 28px 14px;
      text-align: center;
    }
    .notice {
      min-height: 36px;
      color: #52616b;
      font-size: 14px;
    }
    .notice.error {
      color: #b42318;
    }
    [hidden] { display: none !important; }
    @media (max-width: 860px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .sidebar {
        border-right: 0;
        border-bottom: 1px solid #dbe3e8;
      }
      .create-grid {
        grid-template-columns: 1fr 1fr;
      }
      .create-grid button {
        grid-column: 1 / -1;
      }
    }
    @media (max-width: 560px) {
      .topbar {
        align-items: flex-start;
        flex-direction: column;
        height: auto;
        padding: 14px;
      }
      .userbar {
        width: 100%;
        justify-content: space-between;
      }
      .create-grid {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <section id="loginScreen" class="login-shell">
    <div class="login-panel">
      <h1>__APP_NAME__</h1>
      <form id="loginForm">
        <label>用户名
          <input id="loginUsername" autocomplete="username" required />
        </label>
        <label>密码
          <input id="loginPassword" type="password" autocomplete="current-password" required />
        </label>
        <button type="submit">登录</button>
        <div id="loginNotice" class="notice"></div>
      </form>
    </div>
  </section>

  <section id="appScreen" class="shell" hidden>
    <header class="topbar">
      <div class="brand">__APP_NAME__</div>
      <div class="userbar">
        <span id="currentUser"></span>
        <button id="refreshButton" class="secondary" type="button">刷新</button>
        <button id="logoutButton" class="secondary" type="button">退出</button>
      </div>
    </header>

    <main class="layout">
      <aside class="sidebar">
        <h2>节点</h2>
        <div id="nodeList" class="node-list"></div>
      </aside>

      <section class="content">
        <div class="panel">
          <div class="panel-head">
            <h2>新建隧道</h2>
            <span id="formNotice" class="notice"></span>
          </div>
          <form id="createForm" class="create-grid">
            <label>节点
              <select id="createNode" required></select>
            </label>
            <label>名称
              <input id="tunnelName" maxlength="64" placeholder="web-8080" />
            </label>
            <label>本机地址
              <input id="localHost" value="127.0.0.1" required />
            </label>
            <label>本机端口
              <input id="localPort" type="number" min="1" max="65535" required />
            </label>
            <label>公网端口
              <input id="remotePort" type="number" min="1" max="65535" />
            </label>
            <button type="submit">创建</button>
          </form>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2>隧道</h2>
            <span id="tableNotice" class="notice"></span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>节点</th>
                  <th>名称</th>
                  <th>本机</th>
                  <th>公网地址</th>
                  <th>状态</th>
                  <th>用户</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody id="tunnelRows"></tbody>
            </table>
            <div id="emptyState" class="empty" hidden>暂无隧道</div>
          </div>
        </div>
      </section>
    </main>
  </section>

  <script>
    const state = {
      token: localStorage.getItem("simpleClusterToken") || "",
      user: null,
      nodes: [],
      tunnels: [],
      selectedNode: "all"
    };

    const $ = (id) => document.getElementById(id);

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
      const response = await fetch(path, { ...options, headers });
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
    }

    function showApp() {
      $("loginScreen").hidden = true;
      $("appScreen").hidden = false;
      $("currentUser").textContent = state.user
        ? `${state.user.username}${state.user.is_admin ? " · 管理员" : ""}`
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
        const address = tunnel.url || tunnel.address || `${tunnel.public_host}:${tunnel.remote_port}`;
        const statusClass = tunnel.status === "error" ? "status error" : "status";
        tr.innerHTML = `
          <td>${escapeHtml(tunnel.node_name || tunnel.node_id)}</td>
          <td>${escapeHtml(tunnel.name)}</td>
          <td class="mono">${escapeHtml(tunnel.local_host)}:${tunnel.local_port}</td>
          <td class="mono">${escapeHtml(address)}</td>
          <td><span class="${statusClass}" title="${escapeHtml(tunnel.error || "")}">${escapeHtml(tunnel.status)}</span></td>
          <td>${escapeHtml(tunnel.owner || "")}</td>
          <td>
            <div class="row-actions">
              <button class="secondary" type="button" data-copy="${escapeHtml(address)}">复制</button>
              <button class="danger" type="button" data-delete="${tunnel.id}" data-node="${escapeHtml(tunnel.node_id)}">删除</button>
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
      rows.querySelectorAll("[data-delete]").forEach((button) => {
        button.addEventListener("click", async () => {
          await deleteTunnel(button.dataset.node, button.dataset.delete);
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
      const [nodesPayload, tunnelsPayload] = await Promise.all([
        api("/api/nodes"),
        api("/api/tunnels")
      ]);
      state.nodes = nodesPayload.nodes || [];
      state.tunnels = tunnelsPayload.tunnels || [];
      renderNodes();
      renderTunnels();
      const errors = tunnelsPayload.errors || [];
      setNotice("tableNotice", errors.length ? errors.map((item) => item.message).join("；") : "", errors.length > 0);
    }

    async function bootstrap() {
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
      try {
        const payload = await api("/api/login", {
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
        showApp();
        await loadData();
      } catch (error) {
        setNotice("loginNotice", error.message, true);
      }
    });

    $("createForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      setNotice("formNotice", "");
      const nodeId = $("createNode").value;
      const body = {
        name: $("tunnelName").value || null,
        local_host: $("localHost").value || "127.0.0.1",
        local_port: Number($("localPort").value),
        remote_port: $("remotePort").value ? Number($("remotePort").value) : null
      };
      try {
        await api(`/api/nodes/${encodeURIComponent(nodeId)}/tunnels`, {
          method: "POST",
          body
        });
        $("tunnelName").value = "";
        $("localPort").value = "";
        $("remotePort").value = "";
        setNotice("formNotice", "已创建");
        await loadData();
      } catch (error) {
        setNotice("formNotice", error.message, true);
      }
    });

    async function deleteTunnel(nodeId, tunnelId) {
      setNotice("tableNotice", "");
      try {
        await api(`/api/nodes/${encodeURIComponent(nodeId)}/tunnels/${encodeURIComponent(tunnelId)}`, {
          method: "DELETE"
        });
        await loadData();
      } catch (error) {
        setNotice("tableNotice", error.message, true);
      }
    }

    $("refreshButton").addEventListener("click", loadData);
    $("logoutButton").addEventListener("click", () => {
      localStorage.removeItem("simpleClusterToken");
      state.token = "";
      state.user = null;
      showLogin();
    });

    bootstrap();
  </script>
</body>
</html>
"""


def index_html() -> str:
    return INDEX_HTML.replace("__APP_NAME__", APP_DISPLAY_NAME)


app = FastAPI(title=APP_DISPLAY_NAME, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return index_html()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "tunnel-console",
        "auth_mode": AUTH_MODE,
        "nodes": [_public_node(node) for node in NODES],
    }


@app.post("/api/login")
async def login(payload: LoginRequest) -> dict[str, Any]:
    principal = await _authenticate_console_user(payload.username, payload.password)
    return {
        "access_token": create_access_token(principal),
        "token_type": "bearer",
        "user": {
            "username": principal.username,
            "is_admin": principal.is_admin,
        },
    }


@app.get("/api/me")
def me(principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    return {"username": principal.username, "is_admin": principal.is_admin}


@app.get("/api/nodes")
def nodes(_: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    return {"nodes": [_public_node(node) for node in NODES]}


@app.get("/api/tunnels")
async def tunnels(principal: Principal = Depends(get_current_principal)) -> dict[str, Any]:
    tunnel_rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    include_all = "true" if principal.is_admin else "false"

    for node in NODES:
        try:
            payload = await _node_request(
                node,
                "GET",
                "/api/internal/tunnels",
                principal,
                params={"include_all": include_all},
            )
        except HTTPException as exc:
            errors.append({"node_id": node["id"], "message": str(exc.detail)})
            continue

        for tunnel in payload.get("tunnels", []):
            if not isinstance(tunnel, dict):
                continue
            tunnel["node_id"] = node["id"]
            tunnel["node_name"] = node["name"]
            tunnel_rows.append(tunnel)

    return {"tunnels": tunnel_rows, "errors": errors}


@app.post("/api/nodes/{node_id}/tunnels")
async def create_tunnel(
    node_id: str,
    payload: TunnelCreateRequest,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    node = _node_or_404(node_id)
    response = await _node_request(
        node,
        "POST",
        "/api/internal/tunnels",
        principal,
        json_body=payload.model_dump(),
    )
    tunnel = response.get("tunnel")
    if isinstance(tunnel, dict):
        tunnel["node_id"] = node["id"]
        tunnel["node_name"] = node["name"]
    return response


@app.delete("/api/nodes/{node_id}/tunnels/{tunnel_id}")
async def delete_tunnel(
    node_id: str,
    tunnel_id: int,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, Any]:
    node = _node_or_404(node_id)
    return await _node_request(
        node,
        "DELETE",
        f"/api/internal/tunnels/{tunnel_id}",
        principal,
    )
