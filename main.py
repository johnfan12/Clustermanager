"""Simplified central console for user-owned FRP tunnels."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from auth import (
    Principal,
    _resolve_secret,
    authenticate_local_user,
    create_access_token,
    decode_access_token,
    get_current_principal,
)
from node_status_store import init_node_status_store, list_node_health, list_node_health_history, update_node_health
from user_store import (
    account_user_exists,
    account_user_is_admin,
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
INTERNAL_SERVICE_TOKEN = _resolve_secret(
    ["SIMPLE_INTERNAL_SERVICE_TOKEN", "INTERNAL_SERVICE_TOKEN"],
    "INTERNAL_SERVICE_TOKEN",
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
    for item in os.environ.get(
        "SIMPLE_CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:9999,http://127.0.0.1:9999",
    ).split(",")
    if item.strip()
]
console_security = HTTPBearer(auto_error=False)
if AUTH_MODE == "account":
    init_user_store()
init_node_status_store()


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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_nodes() -> list[dict[str, Any]]:
    raw = os.environ.get("SIMPLE_NODES_JSON") or os.environ.get("NODES_JSON") or ""
    parsed: Any = None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            LOGGER.warning("Failed to parse SIMPLE_NODES_JSON/NODES_JSON: %s", exc)

    nodes: list[dict[str, Any]] = []
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
                    "gpu_count": _as_int(config.get("gpu_count"), 0),
                    "gpu_model": str(config.get("gpu_model") or ""),
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
                    "gpu_count": _as_int(config.get("gpu_count"), 0),
                    "gpu_model": str(config.get("gpu_model") or ""),
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
            "gpu_count": _as_int(os.environ.get("SIMPLE_NODE_GPU_COUNT"), 0),
            "gpu_model": os.environ.get("SIMPLE_NODE_GPU_MODEL", ""),
        }
    ]


NODES = _load_nodes()
NODES_BY_ID = {node["id"]: node for node in NODES}
AUTH_NODE_ID = os.environ.get("SIMPLE_AUTH_NODE_ID", NODES[0]["id"] if NODES else "")


def _configured_node_health_inputs() -> list[dict[str, str]]:
    return [{"node_id": str(node["id"]), "name": str(node["name"])} for node in NODES]


def _public_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node["id"],
        "name": node["name"],
        "public_host": node.get("public_host", ""),
        "gpu_count": _as_int(node.get("gpu_count"), 0),
        "gpu_model": str(node.get("gpu_model") or ""),
    }


def _node_or_404(node_id: str) -> dict[str, Any]:
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


def _node_user_headers(principal: Principal, bearer_token: str | None = None) -> dict[str, str]:
    headers = _node_headers(principal)
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


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
    node: dict[str, Any],
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


def _extract_gpu_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [gpu for gpu in payload if isinstance(gpu, dict)]
    if isinstance(payload, dict):
        raw_gpus = payload.get("gpus")
        if isinstance(raw_gpus, list):
            return [gpu for gpu in raw_gpus if isinstance(gpu, dict)]
    return []


def _normalize_gpu_status(gpu: dict[str, Any]) -> dict[str, Any]:
    status = str(gpu.get("status") or "").strip().lower()
    is_idle = gpu.get("is_idle")
    if status not in {"free", "used"}:
        status = "free" if is_idle is True else "used" if is_idle is False else "unknown"

    raw_memory_total_mb = gpu.get("memory_total_mb")
    raw_memory_used_mb = gpu.get("memory_used_mb")
    memory_total_mb = _as_int(raw_memory_total_mb, -1)
    memory_used_mb = _as_int(raw_memory_used_mb, -1)
    memory_total_gb = gpu.get("memory_total_gb")
    if memory_total_gb is None and memory_total_mb > 0:
        memory_total_gb = round(memory_total_mb / 1024, 1)

    utilization_gpu = _as_float(
        gpu.get("utilization_gpu")
        if gpu.get("utilization_gpu") is not None
        else gpu.get("gpu_utilization")
        if gpu.get("gpu_utilization") is not None
        else gpu.get("utilization")
    )

    return {
        "index": _as_int(gpu.get("index"), 0),
        "status": status,
        "is_idle": status == "free",
        "allocated_to": gpu.get("allocated_to"),
        "name": gpu.get("name") or gpu.get("gpu_model"),
        "gpu_model": gpu.get("gpu_model") or gpu.get("name"),
        "memory_total_mb": memory_total_mb if memory_total_mb > 0 else None,
        "memory_used_mb": (
            memory_used_mb
            if raw_memory_used_mb is not None and memory_used_mb >= 0
            else None
        ),
        "memory_total_gb": memory_total_gb,
        "utilization_gpu": utilization_gpu,
        "temperature_c": _as_float(gpu.get("temperature_c")),
        "power_draw_w": _as_float(gpu.get("power_draw_w")),
        "power_limit_w": _as_float(gpu.get("power_limit_w")),
    }


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _sum_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values), 1)


async def _fetch_node_gpu_load(
    client: httpx.AsyncClient,
    node: dict[str, Any],
    principal: Principal,
    bearer_token: str | None,
) -> dict[str, Any]:
    node_id = str(node["id"])
    configured_gpu_count = _as_int(node.get("gpu_count"), 0)
    configured_gpu_model = str(node.get("gpu_model") or "")
    result: dict[str, Any] = {
        "node_id": node_id,
        "name": str(node["name"]),
        "online": False,
        "gpu_model": configured_gpu_model,
        "gpu_total": configured_gpu_count,
        "gpu_free": 0,
        "gpu_used": 0,
        "gpu_utilization_avg": None,
        "memory_used_mb": None,
        "memory_total_mb": None,
        "power_draw_w": None,
        "power_limit_w": None,
        "temperature_avg_c": None,
        "instance_count": 0,
        "gpus": [],
        "error": "",
    }

    try:
        response = await client.get(
            f"{node['api']}/api/gpus/status",
            headers=_node_user_headers(principal, bearer_token),
        )
    except httpx.RequestError as exc:
        result["error"] = f"{node['name']} is unavailable: {exc}"
        return result

    if response.status_code >= 400:
        result["error"] = f"{node['name']}: {_extract_node_error(response)}"
        return result

    try:
        payload = response.json()
    except ValueError:
        result["error"] = f"{node['name']} returned invalid GPU JSON."
        return result

    gpus = [_normalize_gpu_status(gpu) for gpu in _extract_gpu_list(payload)]
    gpu_total = len(gpus) if gpus else configured_gpu_count
    gpu_free = sum(1 for gpu in gpus if gpu.get("status") == "free")
    gpu_used = max(0, gpu_total - gpu_free)

    util_values = [
        value
        for value in (_as_float(gpu.get("utilization_gpu")) for gpu in gpus)
        if value is not None
    ]
    temp_values = [
        value
        for value in (_as_float(gpu.get("temperature_c")) for gpu in gpus)
        if value is not None
    ]
    power_draw_values = [
        value
        for value in (_as_float(gpu.get("power_draw_w")) for gpu in gpus)
        if value is not None
    ]
    power_limit_values = [
        value
        for value in (_as_float(gpu.get("power_limit_w")) for gpu in gpus)
        if value is not None
    ]
    memory_used_values = [
        value
        for value in (_as_float(gpu.get("memory_used_mb")) for gpu in gpus)
        if value is not None
    ]
    memory_total_values = [
        value
        for value in (_as_float(gpu.get("memory_total_mb")) for gpu in gpus)
        if value is not None
    ]
    gpu_model = configured_gpu_model or next(
        (str(gpu.get("name") or "") for gpu in gpus if gpu.get("name")),
        "",
    )

    result.update(
        {
            "online": True,
            "gpu_model": gpu_model,
            "gpu_total": gpu_total,
            "gpu_free": gpu_free,
            "gpu_used": gpu_used,
            "gpu_utilization_avg": _average(util_values),
            "memory_used_mb": _sum_or_none(memory_used_values),
            "memory_total_mb": _sum_or_none(memory_total_values),
            "power_draw_w": _sum_or_none(power_draw_values),
            "power_limit_w": _sum_or_none(power_limit_values),
            "temperature_avg_c": _average(temp_values),
            "gpus": gpus,
        }
    )
    return result


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
        # Re-verify is_admin from database, do not trust the JWT claim.
        return Principal(
            username=principal.username,
            is_admin=account_user_is_admin(principal.username),
        )
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


def _resolve_frontend_dist_dir() -> Path:
    configured = Path(os.environ.get("SIMPLE_FRONTEND_DIST_DIR", "frontend/dist"))
    if configured.is_absolute():
        return configured
    return BASE_DIR / configured


FRONTEND_DIST_DIR = _resolve_frontend_dist_dir()
SERVE_FRONTEND = os.environ.get("SIMPLE_SERVE_FRONTEND", "true").lower() == "true"


def _frontend_response(requested_path: str = "index.html") -> FileResponse:
    if not SERVE_FRONTEND:
        raise HTTPException(status_code=404, detail="Frontend serving is disabled.")
    if requested_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found.")

    root = FRONTEND_DIST_DIR.resolve()
    target = (root / requested_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Frontend asset not found.") from exc

    if target.is_file():
        return FileResponse(target)

    index_path = root / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)

    raise HTTPException(
        status_code=404,
        detail="Frontend build not found. Run `npm run build` in the frontend directory.",
    )


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title=APP_DISPLAY_NAME, version="0.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class CSRFHeaderMiddleware(BaseHTTPMiddleware):
    """Require X-Requested-With on state-changing requests as CSRF defense."""

    _UNSAFE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method in self._UNSAFE_METHODS:
            if not request.headers.get("x-requested-with"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Missing X-Requested-With header."},
                )
        return await call_next(request)


app.add_middleware(CSRFHeaderMiddleware)


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


@app.get("/api/config")
def frontend_config() -> dict[str, Any]:
    return {
        "app_display_name": APP_DISPLAY_NAME,
        "auth_mode": AUTH_MODE,
        "auth_required": AUTH_REQUIRED,
        "allow_register": ALLOW_REGISTER if AUTH_MODE == "account" else False,
    }


@app.post("/api/login")
@limiter.limit("5/minute")
async def login(request: Request, payload: LoginRequest) -> dict[str, Any]:
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
@limiter.limit("3/minute")
def register(request: Request, payload: RegisterRequest) -> dict[str, Any]:
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


@app.get("/api/cluster/status")
async def cluster_status(
    principal: Principal = Depends(get_console_principal),
    credentials: HTTPAuthorizationCredentials | None = Depends(console_security),
) -> dict[str, Any]:
    bearer_token = (
        credentials.credentials
        if credentials is not None and credentials.scheme.lower() == "bearer"
        else None
    )

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        nodes = await asyncio.gather(
            *[
                _fetch_node_gpu_load(client, node, principal, bearer_token)
                for node in NODES
            ]
        )

    total_gpu = sum(_as_int(node.get("gpu_total"), 0) for node in nodes)
    free_gpu = sum(_as_int(node.get("gpu_free"), 0) for node in nodes)
    used_gpu = sum(_as_int(node.get("gpu_used"), 0) for node in nodes)
    total_instances = sum(_as_int(node.get("instance_count"), 0) for node in nodes)
    utilization_values = [
        value
        for node in nodes
        for value in (
            _as_float(gpu.get("utilization_gpu"))
            for gpu in list(node.get("gpus") or [])
            if isinstance(gpu, dict)
        )
        if value is not None
    ]
    node_health = update_node_health(nodes)

    return {
        "nodes": nodes,
        "summary": {
            "total_gpu": total_gpu,
            "free_gpu": free_gpu,
            "used_gpu": used_gpu,
            "total_instances": total_instances,
            "gpu_utilization_avg": _average(utilization_values),
        },
        "node_health": node_health,
        "errors": [
            {"node_id": node["node_id"], "message": node["error"]}
            for node in nodes
            if node.get("error")
        ],
    }


@app.get("/api/nodes/status")
def node_statuses(_: Principal = Depends(get_console_principal)) -> dict[str, Any]:
    return {"nodes": list_node_health(_configured_node_health_inputs())}


@app.get("/api/nodes/status/history")
def node_status_history(_: Principal = Depends(get_console_principal)) -> dict[str, Any]:
    return {"history": list_node_health_history(_configured_node_health_inputs(), days=30)}


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


@app.get("/", include_in_schema=False)
def frontend_root() -> FileResponse:
    return _frontend_response()


@app.get("/{requested_path:path}", include_in_schema=False)
def frontend_asset_or_spa(requested_path: str) -> FileResponse:
    return _frontend_response(requested_path)
