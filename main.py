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
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from auth import (
    Principal,
    authenticate_local_user,
    create_access_token,
    decode_access_token,
    get_current_principal,
)
from user_store import (
    account_user_exists,
    authenticate_account_user,
    create_account_user,
    init_user_store,
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
AUTH_MODE = os.environ.get("SIMPLE_AUTH_MODE", "account").strip().lower()
AUTH_REQUIRED = AUTH_MODE != "none"
ALLOW_REGISTER = os.environ.get("SIMPLE_ALLOW_REGISTER", "true").lower() == "true"
FIRST_USER_ADMIN = os.environ.get("SIMPLE_FIRST_USER_ADMIN", "true").lower() == "true"
NO_AUTH_USERNAME = (
    os.environ.get("SIMPLE_NO_AUTH_USERNAME")
    or os.environ.get("SIMPLE_DEFAULT_USERNAME")
    or os.environ.get("USER")
    or "tunnel"
).strip()
NO_AUTH_IS_ADMIN = os.environ.get("SIMPLE_NO_AUTH_IS_ADMIN", "true").lower() == "true"
CORS_ALLOW_ORIGINS = [
    item.strip()
    for item in os.environ.get("SIMPLE_CORS_ALLOW_ORIGINS", "http://localhost:9999").split(",")
    if item.strip()
]
console_security = HTTPBearer(auto_error=False)
if AUTH_MODE == "account":
    init_user_store()


class LoginRequest(BaseModel):
    """Login payload for local PAM authentication."""

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=4096)


class RegisterRequest(BaseModel):
    """Register a console account."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=4096)


class TunnelCreateRequest(BaseModel):
    """Create one SSH tunnel on a selected node."""

    user_id: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=64)
    remote_port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("user_id")
    @classmethod
    def normalize_user_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("User ID is required.")
        if any(ord(char) < 32 for char in normalized):
            raise ValueError("User ID contains control characters.")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


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
    if AUTH_MODE == "none":
        return _no_auth_principal()
    if AUTH_MODE == "account":
        return authenticate_account_user(username, password)
    if AUTH_MODE == "node":
        return await _authenticate_node_user(username, password)
    if AUTH_MODE != "local":
        raise HTTPException(status_code=500, detail=f"Unsupported SIMPLE_AUTH_MODE: {AUTH_MODE}")
    return authenticate_local_user(username, password)


def _no_auth_principal() -> Principal:
    if not NO_AUTH_USERNAME:
        raise HTTPException(status_code=500, detail="SIMPLE_NO_AUTH_USERNAME is empty.")
    return Principal(username=NO_AUTH_USERNAME, is_admin=NO_AUTH_IS_ADMIN)


def get_console_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(console_security),
) -> Principal:
    if AUTH_MODE == "none":
        return _no_auth_principal()
    if AUTH_MODE == "account":
        principal = decode_access_token(credentials, require_local_user=False)
        if not account_user_exists(principal.username):
            raise HTTPException(status_code=401, detail="Account no longer exists.")
        return principal
    if AUTH_MODE == "node":
        return decode_access_token(credentials, require_local_user=False)
    return get_current_principal(credentials)


def _tunnel_principal(current: Principal, user_id: str) -> Principal:
    if AUTH_REQUIRED and not current.is_admin and user_id != current.username:
        raise HTTPException(status_code=403, detail="Only admins can create SSH access for another user.")
    return Principal(username=user_id, is_admin=current.is_admin)


def _ssh_access_principal(current: Principal, user_id: str) -> Principal:
    del current
    return Principal(username=user_id, is_admin=False)


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
      --color-primary: #0078d4;
      --color-primary-hover: #106ebe;
      --color-primary-active: #005a9e;
      --color-primary-light: #eff6fc;
      --color-primary-border: #c7e0f4;
      --color-bg: #f3f2f1;
      --color-surface: #ffffff;
      --color-surface-alt: #faf9f8;
      --color-border: #edebe9;
      --color-border-strong: #8a8886;
      --color-border-subtle: #c8c6c4;
      --color-text: #323130;
      --color-text-muted: #605e5c;
      --color-text-placeholder: #a19f9d;
      --color-success: #107c10;
      --color-success-bg: #dff6dd;
      --color-success-border: #9ad29a;
      --color-danger: #d13438;
      --color-danger-bg: #fde7e9;
      --color-danger-border: #f1bbbc;
      --radius-sm: 2px;
      --radius-md: 4px;
      --radius-lg: 8px;
      --radius-full: 9999px;
      --shadow-sm: 0 1.6px 3.6px rgba(0, 0, 0, 0.13), 0 0.3px 0.9px rgba(0, 0, 0, 0.1);
      --shadow-md: 0 3.2px 7.2px rgba(0, 0, 0, 0.13), 0 0.6px 1.8px rgba(0, 0, 0, 0.1);
      --transition-fast: 0.12s ease;
      --font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
      --font-mono: "SF Mono", "Cascadia Code", Consolas, "Liberation Mono", monospace;
      --font-size-xs: 11px;
      --font-size-sm: 12px;
      --font-size-base: 14px;
      --font-size-md: 16px;
      --font-size-xl: 24px;
      background: var(--color-bg);
      color: var(--color-text);
      font-family: var(--font-family);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--color-bg);
      color: var(--color-text);
      font-family: var(--font-family);
      font-size: var(--font-size-base);
    }
    button, input, select {
      font: inherit;
    }
    button {
      min-height: 32px;
      border: 1px solid transparent;
      border-radius: var(--radius-sm);
      background: var(--color-primary);
      color: #fff;
      padding: 0 14px;
      cursor: pointer;
      font-weight: 600;
      transition: background var(--transition-fast), border-color var(--transition-fast), color var(--transition-fast), box-shadow var(--transition-fast);
    }
    button:hover:not(:disabled) {
      background: var(--color-primary-hover);
    }
    button:active:not(:disabled) {
      background: var(--color-primary-active);
    }
    button.secondary {
      background: var(--color-surface);
      border-color: var(--color-border-subtle);
      color: var(--color-text);
    }
    button.secondary:hover:not(:disabled) {
      background: var(--color-surface-alt);
      border-color: var(--color-border-strong);
    }
    button.secondary:active:not(:disabled) {
      background: var(--color-border);
    }
    button.danger {
      background: var(--color-danger);
      color: #fff;
    }
    button.danger:hover:not(:disabled) {
      background: #a4262c;
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .auth-tabs {
      display: flex;
      border-bottom: 1px solid var(--color-border);
      margin-bottom: 24px;
    }
    .auth-tabs button {
      flex: 1;
      min-height: 38px;
      border: 0;
      border-bottom: 2px solid transparent;
      border-radius: 0;
      background: transparent;
      color: var(--color-text-muted);
    }
    .auth-tabs button:hover:not(:disabled) {
      background: var(--color-surface-alt);
      color: var(--color-text);
    }
    .auth-tabs button.active,
    .auth-tabs button.active:hover:not(:disabled) {
      background: transparent;
      border-bottom-color: var(--color-primary);
      color: var(--color-primary);
    }
    input, select {
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--color-border-strong);
      border-radius: var(--radius-sm);
      background: var(--color-surface);
      padding: 6px 10px;
      color: var(--color-text);
    }
    input::placeholder {
      color: var(--color-text-placeholder);
    }
    input:focus, select:focus {
      outline: 2px solid transparent;
      border-color: var(--color-primary);
      box-shadow: 0 0 0 1px var(--color-primary);
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--color-text);
      font-size: var(--font-size-base);
      font-weight: 600;
    }
    .login-shell {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .login-panel {
      width: min(520px, 100%);
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      background: var(--color-surface);
      padding: 36px 32px 32px;
      box-shadow: var(--shadow-md);
    }
    .login-panel h1 {
      margin: 0 0 22px;
      color: var(--color-text);
      font-size: var(--font-size-xl);
      font-weight: 600;
      letter-spacing: 0;
    }
    .login-panel form {
      display: grid;
      gap: 16px;
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 200;
      min-height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 0 24px;
      border-bottom: 1px solid var(--color-border);
      background: var(--color-surface);
    }
    .brand {
      color: var(--color-text);
      font-size: var(--font-size-md);
      font-weight: 600;
      letter-spacing: 0;
    }
    .userbar {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--color-text-muted);
      font-size: var(--font-size-sm);
    }
    .layout {
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
      min-height: 0;
    }
    .sidebar {
      border-right: 1px solid var(--color-border);
      background: var(--color-surface);
      padding: 16px;
      display: grid;
      align-content: start;
      gap: 14px;
    }
    .sidebar h2, .content h2 {
      margin: 0;
      color: var(--color-text);
      font-size: var(--font-size-md);
      font-weight: 600;
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
      background: var(--color-surface);
      border-color: var(--color-border-subtle);
      color: var(--color-text);
    }
    .node-button.active,
    .node-button.active:hover:not(:disabled) {
      background: var(--color-primary);
      border-color: var(--color-primary);
      color: #fff;
    }
    .content {
      width: 100%;
      max-width: 1280px;
      margin: 0 auto;
      padding: 16px 24px 32px;
      display: grid;
      gap: 16px;
      align-content: start;
      min-width: 0;
    }
    .panel {
      border: 1px solid var(--color-border);
      border-radius: var(--radius-md);
      background: var(--color-surface);
      box-shadow: var(--shadow-sm);
      overflow: hidden;
    }
    .panel-head {
      min-height: 50px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--color-border);
      background: var(--color-surface);
    }
    .create-grid {
      display: grid;
      grid-template-columns: minmax(150px, 1fr) minmax(180px, 1.15fr) auto;
      align-items: end;
      gap: 12px;
      padding: 16px;
    }
    .table-wrap {
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 820px;
    }
    th, td {
      padding: 12px 16px;
      border-bottom: 1px solid var(--color-border);
      text-align: left;
      vertical-align: middle;
      font-size: var(--font-size-base);
      white-space: nowrap;
    }
    th {
      background: var(--color-surface-alt);
      color: var(--color-text-muted);
      font-size: var(--font-size-sm);
      font-weight: 600;
    }
    .mono {
      font-family: var(--font-mono);
    }
    .status {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 0 8px;
      border: 1px solid var(--color-success-border);
      border-radius: var(--radius-full);
      background: var(--color-success-bg);
      color: var(--color-success);
      font-size: var(--font-size-xs);
      font-weight: 700;
    }
    .status.error {
      border-color: var(--color-danger-border);
      background: var(--color-danger-bg);
      color: var(--color-danger);
    }
    .row-actions {
      display: flex;
      gap: 8px;
    }
    .empty {
      color: var(--color-text-muted);
      padding: 28px 16px;
      text-align: center;
    }
    .notice {
      min-height: 32px;
      color: var(--color-text-muted);
      font-size: var(--font-size-base);
    }
    .notice.error {
      color: var(--color-danger);
    }
    .muted {
      color: var(--color-text-muted);
      font-size: var(--font-size-sm);
    }
    [hidden] { display: none !important; }
    @media (max-width: 860px) {
      .layout {
        grid-template-columns: 1fr;
      }
      .sidebar {
        border-right: 0;
        border-bottom: 1px solid var(--color-border);
      }
      .content {
        padding: 16px;
      }
      .create-grid {
        grid-template-columns: 1fr 1fr;
      }
      .create-grid button {
        grid-column: 1 / -1;
      }
    }
    @media (max-width: 560px) {
      .login-panel {
        padding: 28px 20px 24px;
      }
      .topbar {
        align-items: flex-start;
        flex-direction: column;
        height: auto;
        padding: 14px 16px;
      }
      .userbar {
        width: 100%;
        justify-content: space-between;
        flex-wrap: wrap;
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
      <div class="auth-tabs">
        <button id="loginTab" class="active" type="button">登录</button>
        <button id="registerTab" type="button">注册</button>
      </div>
      <form id="loginForm">
        <label>用户名
          <input id="loginUsername" autocomplete="username" required />
        </label>
        <label>密码
          <input id="loginPassword" type="password" autocomplete="current-password" required />
        </label>
        <label id="confirmPasswordRow" hidden>确认密码
          <input id="confirmPassword" type="password" autocomplete="new-password" />
        </label>
        <button id="loginSubmit" type="submit">登录</button>
        <div id="authHint" class="muted"></div>
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
            <h2>生成 SSH 命令</h2>
            <span id="formNotice" class="notice"></span>
          </div>
          <form id="createForm" class="create-grid">
            <label>节点
              <select id="createNode" required></select>
            </label>
            <label>userid
              <input id="sshUserId" maxlength="64" required />
            </label>
            <button type="submit">生成</button>
          </form>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2>SSH 命令</h2>
            <span id="tableNotice" class="notice"></span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>节点</th>
                  <th>名称</th>
                  <th>SSH 命令</th>
                  <th>状态</th>
                  <th>用户</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody id="tunnelRows"></tbody>
            </table>
            <div id="emptyState" class="empty" hidden>输入 userid 后生成 SSH 命令</div>
          </div>
        </div>
      </section>
    </main>
  </section>

  <script>
    const AUTH_REQUIRED = __AUTH_REQUIRED__;
    const AUTH_MODE = "__AUTH_MODE__";
    const ALLOW_REGISTER = __ALLOW_REGISTER__;
    let authAction = "login";
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
      renderAuthMode();
    }

    function showApp() {
      $("loginScreen").hidden = true;
      $("appScreen").hidden = false;
      $("logoutButton").hidden = !AUTH_REQUIRED;
      $("currentUser").textContent = state.user
        ? `${state.user.username}${state.user.is_admin ? " · 管理员" : ""}`
        : "";
      if (state.user && !$("sshUserId").value) {
        $("sshUserId").value = state.user.username;
      }
    }

    function renderAuthMode() {
      const accountMode = AUTH_MODE === "account";
      $("registerTab").hidden = !accountMode || !ALLOW_REGISTER;
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
      if (!AUTH_REQUIRED) {
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
      const body = {
        user_id: userId
      };
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
      if (!AUTH_REQUIRED) {
        return;
      }
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
    return (
        INDEX_HTML.replace("__APP_NAME__", APP_DISPLAY_NAME)
        .replace("__AUTH_REQUIRED__", "true" if AUTH_REQUIRED else "false")
        .replace("__AUTH_MODE__", AUTH_MODE)
        .replace("__ALLOW_REGISTER__", "true" if ALLOW_REGISTER else "false")
    )


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
        "auth_required": AUTH_REQUIRED,
        "allow_register": ALLOW_REGISTER if AUTH_MODE == "account" else False,
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


@app.post("/api/register")
def register(payload: RegisterRequest) -> dict[str, Any]:
    if AUTH_MODE != "account":
        raise HTTPException(status_code=400, detail="Registration is only available in account auth mode.")
    if not ALLOW_REGISTER:
        raise HTTPException(status_code=403, detail="Registration is disabled.")
    account = create_account_user(
        payload.username,
        payload.password,
        first_user_admin=FIRST_USER_ADMIN,
    )
    principal = Principal(username=account.username, is_admin=account.is_admin)
    return {
        "access_token": create_access_token(principal),
        "token_type": "bearer",
        "user": {
            "username": principal.username,
            "is_admin": principal.is_admin,
        },
    }


@app.get("/api/me")
def me(principal: Principal = Depends(get_console_principal)) -> dict[str, Any]:
    return {"username": principal.username, "is_admin": principal.is_admin}


@app.get("/api/nodes")
def nodes(_: Principal = Depends(get_console_principal)) -> dict[str, Any]:
    return {"nodes": [_public_node(node) for node in NODES]}


@app.get("/api/tunnels")
async def tunnels(principal: Principal = Depends(get_console_principal)) -> dict[str, Any]:
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
    principal: Principal = Depends(get_console_principal),
) -> dict[str, Any]:
    node = _node_or_404(node_id)
    tunnel_principal = _tunnel_principal(principal, payload.user_id)
    node_payload = payload.model_dump(exclude_none=True, exclude={"user_id"})
    if "name" not in node_payload:
        node_payload["name"] = f"ssh-{tunnel_principal.username}"
    response = await _node_request(
        node,
        "POST",
        "/api/internal/tunnels",
        tunnel_principal,
        json_body=node_payload,
    )
    tunnel = response.get("tunnel")
    if isinstance(tunnel, dict):
        tunnel["node_id"] = node["id"]
        tunnel["node_name"] = node["name"]
    return response


@app.post("/api/nodes/{node_id}/ssh-access")
async def node_ssh_access(
    node_id: str,
    payload: TunnelCreateRequest,
    principal: Principal = Depends(get_console_principal),
) -> dict[str, Any]:
    node = _node_or_404(node_id)
    ssh_principal = _ssh_access_principal(principal, payload.user_id)
    response = await _node_request(
        node,
        "GET",
        "/api/internal/ssh-access",
        ssh_principal,
    )
    access = response.get("access")
    if isinstance(access, dict):
        access["node_id"] = node["id"]
        access["node_name"] = node["name"]
    return response


@app.delete("/api/nodes/{node_id}/tunnels/{tunnel_id}")
async def delete_tunnel(
    node_id: str,
    tunnel_id: int,
    principal: Principal = Depends(get_console_principal),
) -> dict[str, Any]:
    node = _node_or_404(node_id)
    return await _node_request(
        node,
        "DELETE",
        f"/api/internal/tunnels/{tunnel_id}",
        principal,
    )
