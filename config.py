"""
配置文件 — GPU 集群跳板机聚合管理服务

配置优先级：环境变量 > .env 文件 > 默认值
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


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


def _extract_ports_from_nodes(nodes: dict) -> tuple[int, ...]:
    """从 NODES.api 中提取 FRP 需要放行的远端 API 端口."""
    ports: set[int] = set()
    for node in nodes.values():
        api = str(node.get("api") or "").strip()
        if not api:
            continue
        target = api if "://" in api else f"http://{api}"
        try:
            parsed = urlparse(target)
        except ValueError:
            continue
        if parsed.port:
            ports.add(parsed.port)
    return tuple(sorted(ports))


# ============================================================================
# JWT 配置
# 必须与所有 gpu_manager 节点的 JWT_SECRET 完全一致，用于 SSO
# ============================================================================

JWT_SECRET: str = os.environ.get("JWT_SECRET", "change-this-secret")
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS: int = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))

ENV: str = os.environ.get("ENV", "dev").lower()

# 服务间鉴权密钥 — 用于回写 Servermanager 的 VPS 访问信息
INTERNAL_SERVICE_TOKEN: str = os.environ.get(
    "INTERNAL_SERVICE_TOKEN", "change-this-internal-service-token"
)

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
        "name": "节点1 · A100 × 8",
        "api": "http://localhost:18881",
        "admin_token": "node1-admin-jwt-token",
        "gpu_count": 8,
        "gpu_model": "A100 80G",
    },
    "node2": {
        "name": "节点2 · RTX3090 × 4",
        "api": "http://localhost:18882",
        "admin_token": "node2-admin-jwt-token",
        "gpu_count": 4,
        "gpu_model": "RTX 3090 24G",
    },
}

# ============================================================================
# 跳板机自身的管理员账号（用于跳板机登录，不依赖节点）
# ============================================================================

ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "admin123")

# 中央用户库（PostgreSQL）
CLUSTER_DATABASE_URL: str = os.environ.get(
    "CLUSTER_DATABASE_URL",
    "postgresql+psycopg://cluster_user:cluster_pass@127.0.0.1:5432/cluster_manager",
)
AUTO_PROVISION_ON_NODE_LOGIN: bool = (
    os.environ.get("AUTO_PROVISION_ON_NODE_LOGIN", "true").lower() == "true"
)
# 新用户默认卡时额度由中心侧统一管理。
GPU_HOURS_DEFAULT_QUOTA: float = float(
    os.environ.get("GPU_HOURS_DEFAULT_QUOTA", "100")
)
if GPU_HOURS_DEFAULT_QUOTA < 0:
    GPU_HOURS_DEFAULT_QUOTA = 0.0
GPU_HOURS_SYNC_INTERVAL_SECONDS: float = float(
    os.environ.get("GPU_HOURS_SYNC_INTERVAL_SECONDS", "60")
)

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
FRP_SERVER_CONFIG_FILE: str = os.environ.get(
    "FRP_SERVER_CONFIG_FILE", f"{FRP_CONFIG_DIR}/frps.ini"
)
FRP_CONFIG_FILE: str = f"{FRP_CONFIG_DIR}/frpc-visitors.ini"
FRP_VISITOR_CONFIG_DIR: str = os.environ.get(
    "FRP_VISITOR_CONFIG_DIR", f"{FRP_CONFIG_DIR}/visitors"
)
FRP_API_ALLOW_PORTS: tuple[str, ...] = tuple(
    _parse_csv(os.environ.get("FRP_API_ALLOW_PORTS", ""))
)
FRP_NODE_API_PORTS: tuple[int, ...] = _extract_ports_from_nodes(NODES)

# 容器访问端口范围（在 VPS 上暴露）
_frp_port_range = os.environ.get("FRP_CONTAINER_PORT_RANGE", "30000-39999").split("-")
FRP_CONTAINER_PORT_RANGE: tuple[int, int] = (
    (int(_frp_port_range[0]), int(_frp_port_range[1]))
    if len(_frp_port_range) == 2
    else (30000, 39999)
)

# VPS 公网 IP（用于生成 SSH 访问地址）
VPS_PUBLIC_IP: str = os.environ.get("VPS_PUBLIC_IP", "your-vps-public-ip")

# 代理白名单配置
PROXY_ALLOWED_PATH_PREFIXES: tuple[str, ...] = tuple(
    _parse_csv(
        os.environ.get(
            "PROXY_ALLOWED_PATH_PREFIXES",
            "/api/instances,/api/quota/me,/api/gpus/status,/api/auth/me,/api/meta,/api/images,/api/admin",
        )
    )
)
PROXY_ALLOWED_METHODS: tuple[str, ...] = tuple(
    method.upper()
    for method in _parse_csv(
        os.environ.get("PROXY_ALLOWED_METHODS", "GET,POST,PUT,PATCH,DELETE")
    )
)

# 代理请求超时（秒）
PROXY_REQUEST_TIMEOUT_SECONDS: float = float(
    os.environ.get("PROXY_REQUEST_TIMEOUT_SECONDS", "10")
)

# 长操作（如实例重建）代理超时（秒）
PROXY_LONG_REQUEST_TIMEOUT_SECONDS: float = float(
    os.environ.get("PROXY_LONG_REQUEST_TIMEOUT_SECONDS", "180")
)


def _ensure_secure_production_config() -> None:
    if ENV != "prod":
        return

    invalid_values = {
        "JWT_SECRET": {"", "change-this-secret", "change-this-to-a-strong-secret-key"},
        "INTERNAL_SERVICE_TOKEN": {
            "",
            "change-this-internal-service-token",
        },
        "ADMIN_PASSWORD": {"", "admin123", "your-strong-admin-password"},
        "FRP_TOKEN": {"", "your-frp-secret-token"},
    }

    bad = [
        key
        for key, disallowed in invalid_values.items()
        if str(globals().get(key, "")) in disallowed
    ]
    if bad:
        raise RuntimeError(
            "Refusing to start in ENV=prod with insecure config: " + ", ".join(bad)
        )


_ensure_secure_production_config()
