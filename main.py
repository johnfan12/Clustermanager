"""
GPU 集群跳板机聚合管理服务 — 主入口
提供集群状态聚合、跨节点实例汇总、节点代理转发等接口。
"""

import asyncio
from datetime import datetime
import json
import logging
import os
from urllib.parse import unquote
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
from auth import (
    get_current_user,
    get_current_user_info,
    get_optional_user,
    router as auth_router,
)
from billing import (
    activate_instance_state,
    ensure_cluster_user_record,
    ensure_gpu_hours_available,
    gpu_hours_remaining,
    request_with_node_admin_auth,
    settle_and_deactivate_instance,
    start_billing_sync,
    stop_billing_sync,
    sync_billing_once,
)
from database import get_db
from models import ClusterInstanceState, ClusterUser, ClusterUserSSHKey
from ssh_keys import (
    MAX_SSH_KEYS_PER_USER,
    compute_ssh_key_fingerprint,
    normalize_ssh_key_remark,
    validate_ssh_public_key,
)
from user_store import get_cluster_user_sync_record

# ── 日志配置 ───────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("cluster_manager")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler("logs/aggregator.log", encoding="utf-8")
file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )
)
logger.addHandler(console_handler)

# ── FastAPI 应用 ───────────────────────────────────────────────────────────

app = FastAPI(title="GPU 集群管理", version="1.0.0")
app.include_router(auth_router)

# 请求超时（秒）
REQUEST_TIMEOUT = 5.0
HOP_BY_HOP_HEADERS = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "x-internal-token",
}


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.replace("Bearer ", "", 1)
    return ""


def _is_safe_proxy_path(path: str) -> bool:
    normalized = "/" + path.lstrip("/")
    decoded = unquote(normalized).lower()
    if ".." in decoded or "\\" in decoded:
        return False
    return any(
        normalized.startswith(prefix) for prefix in config.PROXY_ALLOWED_PATH_PREFIXES
    )


def _sanitize_proxy_headers(request: Request, user_token: str) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "authorization"
    }
    headers["Authorization"] = f"Bearer {user_token}"
    return headers


def _proxy_timeout_seconds(normalized_path: str) -> float:
    """Select proxy timeout by API path.

    Rebuild is a long-running operation (backup + recreate container),
    so it needs a longer timeout than regular read/write requests.
    """
    if normalized_path.startswith("/api/instances/") and normalized_path.endswith("/rebuild"):
        return config.PROXY_LONG_REQUEST_TIMEOUT_SECONDS
    return config.PROXY_REQUEST_TIMEOUT_SECONDS


class ClusterQuotaUpdateRequest(BaseModel):
    """Update central GPU-hour quota for one user."""

    gpu_hours_quota: float = Field(ge=0)


class SSHKeyCreateRequest(BaseModel):
    """Create one cluster-level SSH public key."""

    public_key: str = Field(min_length=1, max_length=8192)
    remark: str | None = Field(default="", max_length=255)


class SSHKeyPayload(BaseModel):
    """Node sync payload for one SSH public key."""

    public_key: str
    remark: str = ""
    fingerprint: str


def _parse_proxy_instance_id(normalized_path: str) -> int | None:
    for prefix in ("/api/instances/", "/api/admin/instances/"):
        if not normalized_path.startswith(prefix):
            continue
        tail = normalized_path[len(prefix) :]
        instance_id = tail.split("/", 1)[0]
        if instance_id.isdigit():
            return int(instance_id)
    return None


def _should_force_user_sync_before_proxy(method: str, normalized_path: str) -> bool:
    """Return whether current proxy request must refresh node user snapshot first."""
    if method != "POST":
        return False
    if normalized_path == "/api/instances":
        return True
    if normalized_path.startswith("/api/instances/") and normalized_path.endswith("/rebuild"):
        return True
    return False


def _serialize_cluster_ssh_key(key: ClusterUserSSHKey) -> dict[str, Any]:
    """Serialize one central SSH key row for API responses."""
    return {
        "id": int(key.id),
        "public_key": str(key.public_key),
        "remark": str(key.remark or ""),
        "fingerprint": str(key.fingerprint),
        "created_at": key.created_at.isoformat(),
    }


def _aggregate_running_usage(instances: list[dict[str, Any]]) -> dict[str, int]:
    running_instances = [
        inst for inst in instances if str(inst.get("status") or "") == "running"
    ]
    return {
        "used_gpu": sum(len(list(inst.get("gpu_indices") or [])) for inst in running_instances),
        "used_memory_gb": sum(int(inst.get("memory_gb") or 0) for inst in running_instances),
        "used_instances": len(running_instances),
    }


async def _fetch_admin_instances(
    client: httpx.AsyncClient, node_id: str, node_cfg: Dict[str, Any]
) -> List[Dict[str, Any]]:
    resp = await request_with_node_admin_auth(
        client,
        node_id,
        node_cfg,
        "GET",
        "/api/admin/instances",
        timeout=REQUEST_TIMEOUT,
    )
    payload = resp.json()
    instances: List[Any] = payload if isinstance(payload, list) else payload.get("instances", [])
    return [inst for inst in instances if isinstance(inst, dict)]


async def _fetch_cluster_usage_by_username() -> dict[str, dict[str, int]]:
    usage_by_username: dict[str, dict[str, int]] = {}
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[
                _fetch_admin_instances(client, node_id, node_cfg)
                for node_id, node_cfg in config.NODES.items()
            ],
            return_exceptions=True,
        )

    for result in results:
        if isinstance(result, Exception):
            continue
        for instance in result:
            username = str(instance.get("username") or "")
            if not username or str(instance.get("status") or "") != "running":
                continue
            usage = usage_by_username.setdefault(
                username,
                {"used_gpu": 0, "used_memory_gb": 0, "used_instances": 0},
            )
            usage["used_gpu"] += len(list(instance.get("gpu_indices") or []))
            usage["used_memory_gb"] += int(instance.get("memory_gb") or 0)
            usage["used_instances"] += 1
    return usage_by_username


async def _precheck_central_billing(
    request: Request,
    normalized_path: str,
    username: str,
    db: Session,
) -> None:
    method = request.method.upper()
    requested_gpu_count = 0

    if method == "POST" and normalized_path == "/api/instances":
        payload = await request.json()
        requested_gpu_count = int(payload.get("num_gpus") or 0)
    elif (
        method == "POST"
        and normalized_path.startswith("/api/instances/")
        and normalized_path.endswith("/restart")
    ):
        instance_id = _parse_proxy_instance_id(normalized_path)
        if instance_id is None:
            return
        state = (
            db.query(ClusterInstanceState)
            .filter(
                ClusterInstanceState.node_id == request.path_params["node_id"],
                ClusterInstanceState.node_instance_id == instance_id,
                ClusterInstanceState.username == username,
            )
            .first()
        )
        requested_gpu_count = int(state.gpu_count) if state is not None else 0
    elif (
        method == "POST"
        and normalized_path.startswith("/api/instances/")
        and normalized_path.endswith("/rebuild")
    ):
        payload = await request.json()
        requested_gpu_count = int(payload.get("num_gpus") or 0)
        instance_id = _parse_proxy_instance_id(normalized_path)
        if instance_id is not None:
            state = (
                db.query(ClusterInstanceState)
                .filter(
                    ClusterInstanceState.node_id == request.path_params["node_id"],
                    ClusterInstanceState.node_instance_id == instance_id,
                    ClusterInstanceState.username == username,
                )
                .first()
            )
            if state is not None and requested_gpu_count == int(state.gpu_count):
                requested_gpu_count = 0

    if requested_gpu_count > 0:
        ensure_gpu_hours_available(db, username, requested_gpu_count)


def _extract_gpu_count_from_response(
    response_payload: dict[str, Any], fallback_gpu_count: int = 0
) -> int:
    gpu_indices = response_payload.get("gpu_indices")
    if isinstance(gpu_indices, list):
        return len(gpu_indices)
    return max(0, int(fallback_gpu_count))


def _handle_central_billing_after_proxy(
    *,
    normalized_path: str,
    method: str,
    node_id: str,
    username: str,
    request_payload: dict[str, Any] | None,
    response_payload: dict[str, Any] | None,
    db: Session,
) -> None:
    if method == "POST" and normalized_path == "/api/instances" and response_payload:
        instance_id = response_payload.get("id")
        if not isinstance(instance_id, int):
            return
        activate_instance_state(
            db,
            node_id=node_id,
            node_instance_id=instance_id,
            username=username,
            container_name=str(response_payload.get("container_name") or ""),
            gpu_count=_extract_gpu_count_from_response(
                response_payload, int((request_payload or {}).get("num_gpus") or 0)
            ),
            status=str(response_payload.get("status") or "running"),
        )
    elif (
        method == "POST"
        and normalized_path.startswith("/api/instances/")
        and normalized_path.endswith("/restart")
    ):
        instance_id = _parse_proxy_instance_id(normalized_path)
        if instance_id is None:
            return
        state = (
            db.query(ClusterInstanceState)
            .filter(
                ClusterInstanceState.node_id == node_id,
                ClusterInstanceState.node_instance_id == instance_id,
            )
            .first()
        )
        if state is not None:
            activate_instance_state(
                db,
                node_id=node_id,
                node_instance_id=instance_id,
                username=state.username,
                container_name=state.container_name,
                gpu_count=state.gpu_count,
                status="running",
            )
    elif (
        method == "POST"
        and normalized_path.startswith("/api/instances/")
        and normalized_path.endswith("/rebuild")
        and response_payload
    ):
        instance_id = _parse_proxy_instance_id(normalized_path)
        if instance_id is None:
            return
        state = (
            db.query(ClusterInstanceState)
            .filter(
                ClusterInstanceState.node_id == node_id,
                ClusterInstanceState.node_instance_id == instance_id,
            )
            .first()
        )
        requested_gpu_count = int((request_payload or {}).get("num_gpus") or 0)
        response_gpu_count = _extract_gpu_count_from_response(
            response_payload,
            requested_gpu_count,
        )
        if state is not None and requested_gpu_count == int(state.gpu_count):
            was_running = str(state.status) == "running"
            state.container_name = str(response_payload.get("container_name") or state.container_name)
            state.status = str(response_payload.get("status") or state.status)
            state.node_online = True
            state.last_seen_at = datetime.utcnow()
            if state.status == "running" and not was_running:
                state.last_billed_at = state.last_seen_at
            elif state.status != "running":
                state.last_billed_at = None
            return
        settle_and_deactivate_instance(
            db,
            node_id=node_id,
            node_instance_id=instance_id,
            reason="rebuild",
            status="stopped",
        )
        activate_instance_state(
            db,
            node_id=node_id,
            node_instance_id=instance_id,
            username=username,
            container_name=str(response_payload.get("container_name") or ""),
            gpu_count=response_gpu_count,
            status=str(response_payload.get("status") or "running"),
        )
    elif (
        method == "POST"
        and normalized_path.startswith("/api/instances/")
        and normalized_path.endswith("/stop")
    ):
        instance_id = _parse_proxy_instance_id(normalized_path)
        if instance_id is None:
            return
        settle_and_deactivate_instance(
            db,
            node_id=node_id,
            node_instance_id=instance_id,
            reason="stop",
            status="stopped",
        )
    elif method == "DELETE" and normalized_path.startswith("/api/instances/"):
        instance_id = _parse_proxy_instance_id(normalized_path)
        if instance_id is None:
            return
        settle_and_deactivate_instance(
            db,
            node_id=node_id,
            node_instance_id=instance_id,
            reason="delete",
            delete_state=True,
        )
    elif method == "DELETE" and normalized_path.startswith("/api/admin/instances/"):
        instance_id = _parse_proxy_instance_id(normalized_path)
        if instance_id is None:
            return
        settle_and_deactivate_instance(
            db,
            node_id=node_id,
            node_instance_id=instance_id,
            reason="admin_delete",
            delete_state=True,
        )


async def _is_container_owned_by_user(
    client: httpx.AsyncClient,
    container_name: str,
    user_token: str,
    username: str,
    node_id: Optional[str] = None,
) -> bool:
    """Check whether a container belongs to current user across allowed nodes."""
    if not user_token:
        return False

    node_items = (
        [(node_id, config.NODES[node_id])]
        if node_id and node_id in config.NODES
        else list(config.NODES.items())
    )
    headers = {"Authorization": f"Bearer {user_token}"}
    for current_node_id, node_cfg in node_items:
        try:
            resp = await _request_node_as_user(
                client,
                node_id=current_node_id,
                node_cfg=node_cfg,
                method="GET",
                path="/api/instances",
                user_token=user_token,
                username=username,
                timeout=REQUEST_TIMEOUT,
                headers=headers,
            )
            if resp.status_code >= 400:
                continue
            payload = resp.json()
            instances: List[Any] = (
                payload if isinstance(payload, list) else payload.get("instances", [])
            )
            for instance in instances:
                if instance.get("container_name") == container_name:
                    return True
        except Exception:
            continue
    return False


async def _sync_cluster_user_to_node(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: Dict[str, Any],
    username: str,
    is_admin: bool,
) -> bool:
    """Push one central user record to a node so existing sessions can continue to work."""
    user_record = get_cluster_user_sync_record(username)
    if user_record is None:
        logger.warning("中心用户不存在，跳过自动补建 user=%s node=%s", username, node_id)
        return False

    try:
        response = await client.post(
            f"{node_cfg['api']}/api/internal/users/sync",
            headers={"X-Internal-Token": config.INTERNAL_SERVICE_TOKEN},
            json={
                **user_record,
                "is_admin": is_admin,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        logger.info("已自动同步中心用户到节点 user=%s node=%s", username, node_id)
        return True
    except Exception as exc:
        logger.warning("自动同步中心用户失败 user=%s node=%s err=%s", username, node_id, exc)
        return False


async def _sync_cluster_user_to_all_nodes(
    username: str,
    is_admin: bool,
) -> list[str]:
    """Best-effort push current cluster user snapshot to every configured node."""
    failed_nodes: list[str] = []
    async with httpx.AsyncClient() as client:
        tasks = [
            _sync_cluster_user_to_node(client, node_id, node_cfg, username, is_admin)
            for node_id, node_cfg in config.NODES.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    for (node_id, _), result in zip(config.NODES.items(), results, strict=False):
        if isinstance(result, Exception) or result is not True:
            failed_nodes.append(node_id)
    return failed_nodes


async def _request_node_as_user(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: Dict[str, Any],
    method: str,
    path: str,
    user_token: str,
    username: str,
    *,
    timeout: float,
    is_admin: bool = False,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    """Send a node request as the current user and auto-sync the node account on first 401."""
    request_headers = dict(headers or {})
    request_headers["Authorization"] = f"Bearer {user_token}"
    response = await client.request(
        method=method,
        url=f"{node_cfg['api']}{path}",
        headers=request_headers,
        params=params,
        content=content,
        timeout=timeout,
    )
    if response.status_code != 401 or not username:
        return response

    synced = await _sync_cluster_user_to_node(
        client,
        node_id=node_id,
        node_cfg=node_cfg,
        username=username,
        is_admin=is_admin,
    )
    if not synced:
        return response

    return await client.request(
        method=method,
        url=f"{node_cfg['api']}{path}",
        headers=request_headers,
        params=params,
        content=content,
        timeout=timeout,
    )


# ── 辅助函数 ───────────────────────────────────────────────────────────────


async def _fetch_node_status(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: Dict[str, Any],
    user_token: str,
    username: str,
    is_admin: bool,
) -> Dict[str, Any]:
    """并发获取单个节点的 GPU 状态和实例数据。

    Args:
        client: httpx 异步客户端
        node_id: 节点 ID（如 "node1"）
        node_cfg: 节点配置字典

    Returns:
        包含节点状态的字典
    """
    result: Dict[str, Any] = {
        "node_id": node_id,
        "name": node_cfg["name"],
        "online": False,
        "gpu_model": node_cfg["gpu_model"],
        "gpu_total": node_cfg["gpu_count"],
        "gpu_free": 0,
        "gpu_used": 0,
        "instance_count": 0,
        "gpus": [],
        "web_url": config.NODE_WEB_URLS.get(node_id, ""),
    }

    try:
        if is_admin:
            gpu_resp, inst_resp = await asyncio.gather(
                request_with_node_admin_auth(
                    client,
                    node_id,
                    node_cfg,
                    "GET",
                    "/api/gpus/status",
                    timeout=REQUEST_TIMEOUT,
                ),
                request_with_node_admin_auth(
                    client,
                    node_id,
                    node_cfg,
                    "GET",
                    "/api/admin/instances",
                    timeout=REQUEST_TIMEOUT,
                ),
            )
        else:
            status_headers = {"Authorization": f"Bearer {user_token}"}
            gpu_resp, inst_resp = await asyncio.gather(
                _request_node_as_user(
                    client,
                    node_id,
                    node_cfg,
                    "GET",
                    "/api/gpus/status",
                    user_token,
                    username,
                    timeout=REQUEST_TIMEOUT,
                    is_admin=is_admin,
                    headers=status_headers,
                ),
                _request_node_as_user(
                    client,
                    node_id,
                    node_cfg,
                    "GET",
                    "/api/instances",
                    user_token,
                    username,
                    timeout=REQUEST_TIMEOUT,
                    is_admin=is_admin,
                    headers=status_headers,
                ),
            )
            inst_resp.raise_for_status()

        gpu_data: Any = []
        if gpu_resp.status_code < 400:
            gpu_data = gpu_resp.json()
        elif is_admin:
            gpu_resp.raise_for_status()

        inst_data = inst_resp.json()

        # 解析 GPU 列表
        gpus: List[Dict[str, Any]] = []
        if isinstance(gpu_data, list):
            gpus = gpu_data
        elif isinstance(gpu_data, dict) and "gpus" in gpu_data:
            gpus = gpu_data["gpus"]

        free_count = sum(1 for g in gpus if g.get("status") == "free")
        used_count = len(gpus) - free_count

        # 解析实例列表
        instances: List[Any] = []
        if isinstance(inst_data, list):
            instances = inst_data
        elif isinstance(inst_data, dict) and "instances" in inst_data:
            instances = inst_data["instances"]

        result.update(
            {
                "online": True,
                "gpu_free": free_count,
                "gpu_used": used_count,
                "gpu_total": len(gpus) if gpus else node_cfg["gpu_count"],
                "instance_count": len(instances),
                "gpus": gpus,
            }
        )

    except Exception as exc:
        logger.warning("节点 %s (%s) 请求失败: %s", node_id, node_cfg["api"], exc)

    return result


async def _fetch_node_instances(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: Dict[str, Any],
    user_token: str,
    username: str,
) -> List[Dict[str, Any]]:
    """获取单个节点上当前用户的实例列表。

    Args:
        client: httpx 异步客户端
        node_id: 节点 ID
        node_cfg: 节点配置字典
        user_token: 当前用户的 JWT token

    Returns:
        附加了 node_id / node_name 和 vps_access 的实例列表
    """
    headers = {"Authorization": f"Bearer {user_token}"}
    try:
        resp = await _request_node_as_user(
            client,
            node_id,
            node_cfg,
            "GET",
            "/api/instances",
            user_token,
            username,
            timeout=REQUEST_TIMEOUT,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        instances: List[Any] = []
        if isinstance(data, list):
            instances = data
        elif isinstance(data, dict) and "instances" in data:
            instances = data["instances"]

        # 获取 FRP 访问映射
        from frp_manager import frp_visitor_manager

        mappings = frp_visitor_manager.get_all_mappings()

        for inst in instances:
            inst["node_id"] = node_id
            inst["node_name"] = node_cfg["name"]

            # 添加 VPS 访问信息
            container_name = inst.get("container_name") or inst.get("name", "")
            if container_name and container_name in mappings:
                access_info = mappings[container_name]
                inst["vps_access"] = {
                    "ssh_cmd": f"ssh -p {access_info['vps_port']} root@{config.VPS_PUBLIC_IP}",
                    "vps_port": access_info["vps_port"],
                    "access_url": access_info["access_url"],
                }

        return instances

    except Exception as exc:
        logger.warning("节点 %s 实例请求失败: %s", node_id, exc)
        return []


# ── API 端点 ───────────────────────────────────────────────────────────────


@app.get("/api/cluster/status")
async def cluster_status(
    request: Request,
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> Dict[str, Any]:
    """集群状态接口 — 并发聚合所有节点的 GPU 和实例数据。

    Returns:
        包含 nodes 列表和 summary 汇总的字典
    """
    user_token = _extract_bearer_token(request)
    user_is_admin = bool(user_info.get("is_admin", False))

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_node_status(
                client,
                nid,
                ncfg,
                user_token,
                str(user_info.get("username") or ""),
                user_is_admin,
            )
            for nid, ncfg in config.NODES.items()
        ]
        nodes = await asyncio.gather(*tasks)

    total_gpu = sum(n["gpu_total"] for n in nodes)
    free_gpu = sum(n["gpu_free"] for n in nodes)
    total_instances = sum(n["instance_count"] for n in nodes)

    return {
        "nodes": nodes,
        "summary": {
            "total_gpu": total_gpu,
            "free_gpu": free_gpu,
            "total_instances": total_instances,
        },
    }


@app.get("/api/cluster/my_instances")
async def my_instances(
    request: Request,
    username: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """我的实例接口 — 聚合当前用户在所有节点的实例。

    Args:
        request: FastAPI Request 对象（用于提取原始 token）
        username: 当前登录用户名

    Returns:
        包含 instances 列表的字典
    """
    # 提取原始 token 转发给各节点
    user_token = _extract_bearer_token(request)

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_node_instances(client, nid, ncfg, user_token, username)
            for nid, ncfg in config.NODES.items()
        ]
        results = await asyncio.gather(*tasks)

    all_instances: List[Dict[str, Any]] = []
    for inst_list in results:
        all_instances.extend(inst_list)

    return {"instances": all_instances, "total": len(all_instances)}


@app.get("/api/quota/me")
async def my_central_quota(
    request: Request,
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return central GPU-hour quota plus current cross-node usage."""
    await sync_billing_once()
    user = ensure_cluster_user_record(db, username)
    user_token = _extract_bearer_token(request)

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *[
                _fetch_node_instances(client, node_id, node_cfg, user_token, username)
                for node_id, node_cfg in config.NODES.items()
            ]
        )

    all_instances: List[Dict[str, Any]] = []
    for inst_list in results:
        all_instances.extend(inst_list)
    usage = _aggregate_running_usage(all_instances)

    return {
        **usage,
        "gpu_hours_quota": float(user.gpu_hours_quota or 0.0),
        "gpu_hours_used": float(user.gpu_hours_used or 0.0),
        "gpu_hours_frozen": float(user.gpu_hours_frozen or 0.0),
        "gpu_hours_remaining": gpu_hours_remaining(user),
    }


@app.get("/api/ssh-keys")
async def list_ssh_keys(
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, Any]]]:
    """List current user's SSH public keys stored in cluster manager."""
    keys = (
        db.query(ClusterUserSSHKey)
        .filter(ClusterUserSSHKey.username == username)
        .order_by(ClusterUserSSHKey.created_at.asc(), ClusterUserSSHKey.id.asc())
        .all()
    )
    return {"keys": [_serialize_cluster_ssh_key(key) for key in keys]}


@app.post("/api/ssh-keys")
async def create_ssh_key(
    payload: SSHKeyCreateRequest,
    user_info: dict[str, Any] = Depends(get_current_user_info),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Store one SSH public key for the current user."""
    username = str(user_info.get("username") or "")
    normalized_key = validate_ssh_public_key(payload.public_key)
    remark = normalize_ssh_key_remark(payload.remark)
    fingerprint = compute_ssh_key_fingerprint(normalized_key)
    ensure_cluster_user_record(db, username)

    existing_count = (
        db.query(ClusterUserSSHKey)
        .filter(ClusterUserSSHKey.username == username)
        .count()
    )
    if existing_count >= MAX_SSH_KEYS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"每个用户最多只能保存 {MAX_SSH_KEYS_PER_USER} 条 SSH 公钥。",
        )

    duplicate = (
        db.query(ClusterUserSSHKey)
        .filter(
            ClusterUserSSHKey.username == username,
            ClusterUserSSHKey.fingerprint == fingerprint,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(status_code=400, detail="该 SSH 公钥已存在。")

    key = ClusterUserSSHKey(
        username=username,
        public_key=normalized_key,
        remark=remark,
        fingerprint=fingerprint,
    )
    db.add(key)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="保存 SSH 公钥失败。") from exc
    db.refresh(key)

    failed_nodes = await _sync_cluster_user_to_all_nodes(
        username=username,
        is_admin=bool(user_info.get("is_admin", False)),
    )
    if failed_nodes:
        logger.warning(
            "SSH 公钥已保存，但同步到部分节点失败 user=%s nodes=%s",
            username,
            ",".join(failed_nodes),
        )
    return _serialize_cluster_ssh_key(key)


@app.delete("/api/ssh-keys/{key_id}")
async def delete_ssh_key(
    key_id: int,
    user_info: dict[str, Any] = Depends(get_current_user_info),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete one SSH public key for the current user."""
    username = str(user_info.get("username") or "")
    key = (
        db.query(ClusterUserSSHKey)
        .filter(ClusterUserSSHKey.id == key_id, ClusterUserSSHKey.username == username)
        .first()
    )
    if key is None:
        raise HTTPException(status_code=404, detail="SSH 公钥不存在。")

    db.delete(key)
    db.commit()

    failed_nodes = await _sync_cluster_user_to_all_nodes(
        username=username,
        is_admin=bool(user_info.get("is_admin", False)),
    )
    if failed_nodes:
        logger.warning(
            "SSH 公钥已删除，但同步到部分节点失败 user=%s nodes=%s",
            username,
            ",".join(failed_nodes),
        )
    return {"message": "SSH 公钥已删除。"}


@app.get("/api/admin/users")
async def admin_list_cluster_users(
    user_info: dict[str, Any] = Depends(get_current_user_info),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return central billing users and their current cross-node usage."""
    if not user_info.get("is_admin", False):
        raise HTTPException(status_code=403, detail="仅管理员可查看用户列表")

    await sync_billing_once()
    usage_by_username = await _fetch_cluster_usage_by_username()
    users = db.query(ClusterUser).order_by(ClusterUser.created_at.asc()).all()

    result: List[Dict[str, Any]] = []
    for user in users:
        usage = usage_by_username.get(
            user.username,
            {"used_gpu": 0, "used_memory_gb": 0, "used_instances": 0},
        )
        result.append(
            {
                "username": user.username,
                "email": user.email,
                "is_admin": user.username == config.ADMIN_USERNAME,
                **usage,
                "gpu_hours_quota": float(user.gpu_hours_quota or 0.0),
                "gpu_hours_used": float(user.gpu_hours_used or 0.0),
                "gpu_hours_frozen": float(user.gpu_hours_frozen or 0.0),
                "gpu_hours_remaining": gpu_hours_remaining(user),
            }
        )
    return result


@app.put("/api/admin/users/{username}/quota")
async def admin_update_cluster_user_quota(
    username: str,
    payload: ClusterQuotaUpdateRequest,
    user_info: dict[str, Any] = Depends(get_current_user_info),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    """Update the central GPU-hour quota for one user."""
    if not user_info.get("is_admin", False):
        raise HTTPException(status_code=403, detail="仅管理员可修改用户额度")

    user = ensure_cluster_user_record(db, username)
    user.gpu_hours_quota = payload.gpu_hours_quota
    db.commit()
    return {"message": "Quota updated."}


@app.api_route(
    "/api/proxy/{node_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy(
    node_id: str,
    path: str,
    request: Request,
    user_info: dict[str, Any] = Depends(get_current_user_info),
    db: Session = Depends(get_db),
) -> Response:
    """节点直连代理接口 — 透明转发请求到对应节点。

    Args:
        node_id: 目标节点 ID
        path: 要转发的路径
        request: 原始请求

    Returns:
        来自节点的响应

    Raises:
        HTTPException: 节点不存在或请求失败时
    """
    if node_id not in config.NODES:
        raise HTTPException(status_code=404, detail=f"节点 {node_id} 不存在")

    method = request.method.upper()
    if method not in config.PROXY_ALLOWED_METHODS:
        raise HTTPException(status_code=403, detail="代理方法不允许")

    if not _is_safe_proxy_path(path):
        raise HTTPException(status_code=403, detail="代理路径不允许")

    user_token = _extract_bearer_token(request)
    if not user_token:
        raise HTTPException(status_code=401, detail="未提供有效 token")

    node_cfg = config.NODES[node_id]
    normalized_path = "/" + path.lstrip("/")
    headers = _sanitize_proxy_headers(request, user_token)

    body = await request.body()
    request_payload: dict[str, Any] | None = None
    if body:
        try:
            decoded = json.loads(body.decode("utf-8"))
            request_payload = decoded if isinstance(decoded, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            request_payload = None

    await _precheck_central_billing(
        request,
        normalized_path,
        str(user_info.get("username") or ""),
        db,
    )

    try:
        timeout_seconds = _proxy_timeout_seconds(normalized_path)
        async with httpx.AsyncClient() as client:
            if _should_force_user_sync_before_proxy(method, normalized_path):
                synced = await _sync_cluster_user_to_node(
                    client,
                    node_id,
                    node_cfg,
                    str(user_info.get("username") or ""),
                    bool(user_info.get("is_admin", False)),
                )
                if not synced:
                    raise HTTPException(
                        status_code=502,
                        detail="同步用户 SSH 公钥到节点失败，请稍后重试。",
                    )
            resp = await _request_node_as_user(
                client,
                node_id,
                node_cfg,
                method,
                normalized_path,
                user_token,
                str(user_info.get("username") or ""),
                timeout=timeout_seconds,
                is_admin=bool(user_info.get("is_admin", False)),
                headers=headers,
                params=dict(request.query_params),
                content=body,
            )
        response_payload: dict[str, Any] | None = None
        content_type = resp.headers.get("content-type", "")
        if resp.status_code < 400 and "application/json" in content_type:
            try:
                payload = resp.json()
                response_payload = payload if isinstance(payload, dict) else None
            except ValueError:
                response_payload = None
        if resp.status_code < 400:
            _handle_central_billing_after_proxy(
                normalized_path=normalized_path,
                method=method,
                node_id=node_id,
                username=str(user_info.get("username") or ""),
                request_payload=request_payload,
                response_payload=response_payload,
                db=db,
            )
            db.commit()
        response_headers = {
            key: value
            for key, value in resp.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=response_headers,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.error(
            "代理转发失败 user=%s node=%s path=%s err=%s",
            user_info.get("username", "-"),
            node_id,
            normalized_path,
            exc,
        )
        raise HTTPException(status_code=502, detail=f"节点 {node_id} 请求失败: {exc}")


# ── 节点 Web URL 接口（供前端获取跳转地址）──────────────────────────────────


@app.get("/api/cluster/node_urls")
async def node_urls(username: str = Depends(get_current_user)) -> Dict[str, str]:
    """返回各节点的 Web 访问地址（供前端跳转使用）。

    Returns:
        node_id → web_url 的映射字典
    """
    del username
    return config.NODE_WEB_URLS


# ── 静态文件 & 首页 ───────────────────────────────────────────────────────

# 保留旧版 static 目录挂载（兼容旧版资源引用）
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/legacy")
async def legacy_index():
    """旧版前端入口（迁移完成前保留）。"""
    from fastapi.responses import FileResponse

    return FileResponse("static/index.html")


# ── 新前端 (Vue SPA) ──────────────────────────────────────────────────────
# 构建产物输出到 static/dist/，由 Vite build 生成
_SPA_DIR = os.path.join(os.path.dirname(__file__), "static", "dist")

if os.path.isdir(_SPA_DIR):
    # 挂载 SPA 静态资源（JS/CSS/图片等）
    app.mount("/assets", StaticFiles(directory=os.path.join(_SPA_DIR, "assets")), name="spa-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """为 Vue Router 提供 HTML5 History 回退。"""
        from fastapi.responses import FileResponse

        # 尝试直接返回文件
        file_path = os.path.join(_SPA_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # 否则返回 index.html 让 Vue Router 处理
        return FileResponse(os.path.join(_SPA_DIR, "index.html"))
else:
    # SPA 未构建时，使用旧版首页
    @app.get("/")
    async def index():
        """将根路径重定向到前端页面（SPA 未构建时回退旧版）。"""
        from fastapi.responses import FileResponse

        return FileResponse("static/index.html")



# ── 启动日志 ───────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup_event() -> None:
    """服务启动时记录节点配置信息。"""
    logger.info("GPU 集群聚合服务启动")
    logger.info("已配置 %d 个节点:", len(config.NODES))
    for nid, ncfg in config.NODES.items():
        logger.info("  %s: %s → %s", nid, ncfg["name"], ncfg["api"])

    # 同步 FRP visitor 配置
    try:
        from frp_manager import frp_visitor_manager

        frp_visitor_manager.sync_frps_config()
        frp_visitor_manager.update_config()
        logger.info("FRP visitor 配置已同步")
    except Exception as exc:
        logger.error("FRP visitor 配置同步失败: %s", exc)

    await sync_billing_once()
    await start_billing_sync()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Stop background billing sync on shutdown."""
    await stop_billing_sync()


# ── FRP 容器访问管理 ─────────────────────────────────────────────────────────


@app.get("/api/frp/containers")
async def list_frp_containers(
    request: Request,
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    """返回所有容器的 FRP 访问映射（管理员功能）."""
    from frp_manager import frp_visitor_manager

    mappings = frp_visitor_manager.get_all_mappings()
    if not user_info.get("is_admin", False):
        user_token = _extract_bearer_token(request)
        async with httpx.AsyncClient() as client:
            allowed = []
            for container_name, mapping in mappings.items():
                if await _is_container_owned_by_user(
                    client,
                    container_name,
                    user_token,
                    str(user_info.get("username") or ""),
                ):
                    allowed.append((container_name, mapping))
            mappings = dict(allowed)

    return {
        "success": True,
        "count": len(mappings),
        "containers": mappings,
    }


@app.get("/api/frp/containers/{container_name}")
async def get_frp_container_access(
    container_name: str,
    request: Request,
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    """返回单个容器的 FRP 访问信息."""
    from frp_manager import frp_visitor_manager

    mappings = frp_visitor_manager.get_all_mappings()
    if container_name not in mappings:
        raise HTTPException(status_code=404, detail="Container not found")

    if not user_info.get("is_admin", False):
        user_token = _extract_bearer_token(request)
        async with httpx.AsyncClient() as client:
            if not await _is_container_owned_by_user(
                client,
                container_name,
                user_token,
                str(user_info.get("username") or ""),
            ):
                raise HTTPException(status_code=403, detail="无权访问该实例")

    return {
        "success": True,
        "container": mappings[container_name],
    }


@app.post("/api/frp/sync")
async def sync_frp_config(
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    """手动触发 FRP 配置同步."""
    if not user_info.get("is_admin", False):
        raise HTTPException(status_code=403, detail="仅管理员可执行该操作")

    from frp_manager import frp_visitor_manager

    success = frp_visitor_manager.update_config()
    return {
        "success": success,
        "message": "FRP config synced" if success else "Failed to sync",
    }


@app.post("/api/cluster/instances/{instance_id}/connect")
async def get_instance_connect_info(
    instance_id: str,
    request: Request,
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> dict[str, Any]:
    """获取实例的连接信息（包括 FRP 访问地址）."""
    from frp_manager import frp_visitor_manager

    # 解析 instance_id 格式: node1_gpu_user_username_xxx
    if "_" not in instance_id:
        raise HTTPException(status_code=400, detail="Invalid instance ID format")

    parts = instance_id.split("_", 1)
    node_id = parts[0]
    container_name = parts[1] if len(parts) > 1 else instance_id

    if node_id not in config.NODES:
        raise HTTPException(status_code=404, detail="Node not found")

    # 从节点获取实例详情
    node = config.NODES[node_id]
    user_token = _extract_bearer_token(request)
    user_is_admin = bool(user_info.get("is_admin", False))

    try:
        async with httpx.AsyncClient() as client:
            if user_is_admin:
                resp = await request_with_node_admin_auth(
                    client,
                    node_id,
                    node,
                    "GET",
                    "/api/admin/instances",
                    timeout=5.0,
                )
            else:
                resp = await _request_node_as_user(
                    client,
                    node_id,
                    node,
                    "GET",
                    "/api/instances",
                    user_token,
                    str(user_info.get("username") or ""),
                    timeout=5.0,
                    headers={"Authorization": f"Bearer {user_token}"},
                )
                resp.raise_for_status()
            payload = resp.json()
            instances: List[Any] = (
                payload if isinstance(payload, list) else payload.get("instances", [])
            )

            # 找到目标实例
            target = None
            for inst in instances:
                if inst.get("container_name") == container_name:
                    target = inst
                    break

            if not target:
                raise HTTPException(status_code=404, detail="Instance not found")

            # 获取 FRP 访问信息
            mappings = frp_visitor_manager.get_all_mappings()
            access_info = mappings.get(container_name, {})

            return {
                "success": True,
                "instance": target,
                "access": {
                    "frp_ssh": access_info.get("access_url"),
                    "vps_port": access_info.get("vps_port"),
                    "local_ssh": f"ssh://root@<node-local-ip>:{target.get('ssh_port', 'unknown')}",
                },
            }

    except httpx.HTTPError as exc:
        logger.error("Failed to connect to node %s: %s", node_id, exc)
        raise HTTPException(status_code=503, detail=f"Node unavailable: {exc}")
