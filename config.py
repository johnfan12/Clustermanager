"""
配置文件 — GPU 集群跳板机聚合管理服务

配置优先级：环境变量 > .env 文件 > 默认值
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _load_nodes_from_env() -> dict:
    """从环境变量加载节点配置（JSON 格式）."""
    nodes_json = os.environ.get("NODES_JSON", "")
    if nodes_json:
        try:
            return json.loads(nodes_json)
        except json.JSONDecodeError:
            pass
    return {}


def _load_node_web_urls_from_env() -> dict:
    """从环境变量加载节点 Web URL 配置（JSON 格式）."""
    urls_json = os.environ.get("NODE_WEB_URLS_JSON", "")
    if urls_json:
        try:
            return json.loads(urls_json)
        except json.JSONDecodeError:
            pass
    return {}


# ============================================================================
# JWT 配置
# 必须与所有 gpu_manager 节点的 JWT_SECRET 完全一致，用于 SSO
# ============================================================================

JWT_SECRET: str = os.environ.get("JWT_SECRET", "change-this-secret")
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS: int = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))

# ============================================================================
# 集群节点列表
# api        — frp 穿透到 VPS 本地的地址
# admin_token — 对应节点 gpu_manager 的管理员 JWT，用于拉取全局数据
#
# 可以通过 .env 中的 NODES_JSON 覆盖，例如：
# NODES_JSON='{"node1":{"name":"节点1","api":"http://localhost:18881",...}}'
# ============================================================================

NODES: dict = _load_nodes_from_env() or {
    "node1": {
        "name":        "节点1 · A100 × 8",
        "api":         "http://localhost:18881",
        "admin_token": "node1-admin-jwt-token",
        "gpu_count":   8,
        "gpu_model":   "A100 80G",
    },
    "node2": {
        "name":        "节点2 · RTX3090 × 4",
        "api":         "http://localhost:18882",
        "admin_token": "node2-admin-jwt-token",
        "gpu_count":   4,
        "gpu_model":   "RTX 3090 24G",
    },
}

# ============================================================================
# 跳板机自身的管理员账号（用于跳板机登录，不依赖节点）
# ============================================================================

ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "admin123")

# ============================================================================
# 各节点 gpu_manager 的 Web 访问地址（前端"进入管理"按钮跳转）
# 可以通过 .env 中的 NODE_WEB_URLS_JSON 覆盖
# ============================================================================

NODE_WEB_URLS: dict = _load_node_web_urls_from_env() or {
    "node1": "http://your-vps-ip:18881",
    "node2": "http://your-vps-ip:18882",
}

# ============================================================================
# FRP 配置 — 用于访问各节点上的容器 SSH
# ============================================================================

FRP_ENABLED: bool = os.environ.get("FRP_ENABLED", "true").lower() == "true"
FRP_SERVER_ADDR: str = os.environ.get("FRP_SERVER_ADDR", "localhost")
FRP_SERVER_PORT: int = int(os.environ.get("FRP_SERVER_PORT", "7000"))
FRP_TOKEN: str = os.environ.get("FRP_TOKEN", "your-frp-secret-token")
FRP_CONFIG_DIR: str = os.environ.get("FRP_CONFIG_DIR", "/etc/frp")
FRP_CONFIG_FILE: str = f"{FRP_CONFIG_DIR}/frpc-visitors.ini"

# 容器访问端口范围（在 VPS 上暴露）
_frp_port_range = os.environ.get("FRP_CONTAINER_PORT_RANGE", "30000-39999").split("-")
FRP_CONTAINER_PORT_RANGE: tuple[int, int] = (
    (int(_frp_port_range[0]), int(_frp_port_range[1]))
    if "-" in _frp_port_range
    else (30000, 39999)
)

# VPS 公网 IP（用于生成 SSH 访问地址）
VPS_PUBLIC_IP: str = os.environ.get("VPS_PUBLIC_IP", "your-vps-public-ip")
