"""
GPU 集群跳板机聚合管理服务 — 主入口
提供集群状态聚合、跨节点实例汇总、节点代理转发等接口。
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import config
from auth import get_current_user, get_optional_user, router as auth_router

# ── 日志配置 ───────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("cluster_manager")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler("logs/aggregator.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
))
logger.addHandler(console_handler)

# ── FastAPI 应用 ───────────────────────────────────────────────────────────

app = FastAPI(title="GPU 集群管理", version="1.0.0")
app.include_router(auth_router)

# 请求超时（秒）
REQUEST_TIMEOUT = 5.0


# ── 辅助函数 ───────────────────────────────────────────────────────────────

async def _fetch_node_status(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: Dict[str, Any],
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
        "node_id":        node_id,
        "name":           node_cfg["name"],
        "online":         False,
        "gpu_model":      node_cfg["gpu_model"],
        "gpu_total":      node_cfg["gpu_count"],
        "gpu_free":       0,
        "gpu_used":       0,
        "instance_count": 0,
        "gpus":           [],
        "web_url":        config.NODE_WEB_URLS.get(node_id, ""),
    }

    headers = {"Authorization": f"Bearer {node_cfg['admin_token']}"}

    try:
        # 并发请求 GPU 状态 和 实例列表
        gpu_resp, inst_resp = await asyncio.gather(
            client.get(f"{node_cfg['api']}/api/gpus/status", headers=headers, timeout=REQUEST_TIMEOUT),
            client.get(f"{node_cfg['api']}/api/admin/instances", headers=headers, timeout=REQUEST_TIMEOUT),
        )

        gpu_resp.raise_for_status()
        inst_resp.raise_for_status()

        gpu_data = gpu_resp.json()
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

        result.update({
            "online":         True,
            "gpu_free":       free_count,
            "gpu_used":       used_count,
            "gpu_total":      len(gpus) if gpus else node_cfg["gpu_count"],
            "instance_count": len(instances),
            "gpus":           gpus,
        })

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
        附加了 node_id / node_name 的实例列表
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

        for inst in instances:
            inst["node_id"] = node_id
            inst["node_name"] = node_cfg["name"]

        return instances

    except Exception as exc:
        logger.warning("节点 %s 实例请求失败: %s", node_id, exc)
        return []


# ── API 端点 ───────────────────────────────────────────────────────────────

@app.get("/api/cluster/status")
async def cluster_status() -> Dict[str, Any]:
    """集群状态接口 — 并发聚合所有节点的 GPU 和实例数据。

    Returns:
        包含 nodes 列表和 summary 汇总的字典
    """
    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_node_status(client, nid, ncfg)
            for nid, ncfg in config.NODES.items()
        ]
        nodes = await asyncio.gather(*tasks)

    total_gpu = sum(n["gpu_total"] for n in nodes)
    free_gpu = sum(n["gpu_free"] for n in nodes)
    total_instances = sum(n["instance_count"] for n in nodes)

    return {
        "nodes": nodes,
        "summary": {
            "total_gpu":       total_gpu,
            "free_gpu":        free_gpu,
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
    auth_header = request.headers.get("Authorization", "")
    user_token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""

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
async def proxy(node_id: str, path: str, request: Request) -> Response:
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

    node_cfg = config.NODES[node_id]
    target_url = f"{node_cfg['api']}/{path}"

    # 保留原始 headers（含 Authorization）
    headers = dict(request.headers)
    headers.pop("host", None)

    body = await request.body()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                timeout=REQUEST_TIMEOUT,
            )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )
    except Exception as exc:
        logger.error("代理转发到节点 %s 失败: %s", node_id, exc)
        raise HTTPException(status_code=502, detail=f"节点 {node_id} 请求失败: {exc}")


# ── 节点 Web URL 接口（供前端获取跳转地址）──────────────────────────────────

@app.get("/api/cluster/node_urls")
async def node_urls() -> Dict[str, str]:
    """返回各节点的 Web 访问地址（供前端跳转使用）。

    Returns:
        node_id → web_url 的映射字典
    """
    return config.NODE_WEB_URLS


# ── 静态文件 & 首页 ───────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    """将根路径重定向到前端页面。"""
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
