"""
GPU 集群跳板机聚合管理服务 — 主入口
提供集群状态聚合、跨节点实例汇总、节点代理转发等接口。
"""

import asyncio
import logging
import os
from urllib.parse import unquote
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from auth import (
    get_current_user,
    get_current_user_info,
    get_optional_user,
    router as auth_router,
)

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


async def _is_container_owned_by_user(
    client: httpx.AsyncClient,
    container_name: str,
    user_token: str,
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
    for _, node_cfg in node_items:
        try:
            resp = await client.get(
                f"{node_cfg['api']}/api/instances",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
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


# ── 辅助函数 ───────────────────────────────────────────────────────────────


async def _fetch_node_status(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: Dict[str, Any],
    user_token: str,
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
            status_headers = {"Authorization": f"Bearer {node_cfg['admin_token']}"}
            instances_path = "/api/admin/instances"
        else:
            status_headers = {"Authorization": f"Bearer {user_token}"}
            instances_path = "/api/instances"

        # 并发请求 GPU 状态 和 实例列表
        gpu_resp, inst_resp = await asyncio.gather(
            client.get(
                f"{node_cfg['api']}/api/gpus/status",
                headers=status_headers,
                timeout=REQUEST_TIMEOUT,
            ),
            client.get(
                f"{node_cfg['api']}{instances_path}",
                headers=status_headers,
                timeout=REQUEST_TIMEOUT,
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
        resp = await client.get(
            f"{node_cfg['api']}/api/instances",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
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
            _fetch_node_status(client, nid, ncfg, user_token, user_is_admin)
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
            _fetch_node_instances(client, nid, ncfg, user_token)
            for nid, ncfg in config.NODES.items()
        ]
        results = await asyncio.gather(*tasks)

    all_instances: List[Dict[str, Any]] = []
    for inst_list in results:
        all_instances.extend(inst_list)

    return {"instances": all_instances, "total": len(all_instances)}


@app.api_route(
    "/api/proxy/{node_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy(
    node_id: str,
    path: str,
    request: Request,
    user_info: dict[str, Any] = Depends(get_current_user_info),
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
    target_url = f"{node_cfg['api']}{normalized_path}"
    headers = _sanitize_proxy_headers(request, user_token)

    body = await request.body()

    try:
        timeout_seconds = _proxy_timeout_seconds(normalized_path)
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method=method,
                url=target_url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=timeout_seconds,
            )
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
    except Exception as exc:
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

        frp_visitor_manager.update_config()
        logger.info("FRP visitor 配置已同步")
    except Exception as exc:
        logger.error("FRP visitor 配置同步失败: %s", exc)


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
                    client, container_name, user_token
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
                client, container_name, user_token
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
        headers = {
            "Authorization": (
                f"Bearer {node['admin_token']}"
                if user_is_admin
                else f"Bearer {user_token}"
            )
        }
        list_path = "/api/admin/instances" if user_is_admin else "/api/instances"
        async with httpx.AsyncClient() as client:
            # 获取实例列表
            resp = await client.get(
                f"{node['api']}{list_path}",
                headers=headers,
                timeout=5.0,
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
