"""FRP Visitor 管理模块 — 在 VPS 上为各节点容器创建访问隧道."""

from __future__ import annotations

import configparser
import hashlib
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from config import (
    FRP_CONFIG_FILE,
    FRP_CONTAINER_PORT_RANGE,
    FRP_ENABLED,
    INTERNAL_SERVICE_TOKEN,
    FRP_SERVER_ADDR,
    FRP_SERVER_PORT,
    FRP_TOKEN,
    NODES,
    VPS_PUBLIC_IP,
)

LOGGER = logging.getLogger(__name__)


class FrpVisitorManager:
    """管理 frpc visitor 配置，为每个容器创建访问隧道."""

    def __init__(self) -> None:
        """初始化 Visitor 管理器."""
        self.enabled = FRP_ENABLED
        self.config_file = Path(FRP_CONFIG_FILE)
        self._allocated_ports: dict[str, int] = {}  # container_name -> port
        self._last_sync_signature: str | None = None
        self._last_sync_at: float = 0.0

    def fetch_container_secrets(self) -> list[dict[str, Any]]:
        """从所有节点获取容器的 FRP 连接信息."""
        containers = []

        for node_id, node_config in NODES.items():
            api_base = node_config["api"]

            try:
                headers = {"X-Internal-Token": INTERNAL_SERVICE_TOKEN}
                response = httpx.get(
                    f"{api_base}/api/frp/containers",
                    headers=headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                node_containers = response.json()

                for c in node_containers:
                    c["node_id"] = node_id
                    c["node_name"] = node_config["name"]
                containers.extend(node_containers)

            except Exception as exc:
                LOGGER.error(
                    "Failed to fetch FRP secrets from %s (%s): %s",
                    node_id,
                    api_base,
                    exc,
                )

        return containers

    def allocate_port(
        self, container_name: str, preferred_port: int | None = None
    ) -> int:
        """为容器分配 VPS 上的访问端口.

        Args:
            container_name: 容器名称（用于哈希计算确定性端口）
            preferred_port: 优先使用的端口（从现有配置读取），用于保持重启后端口一致
        """
        # 如果已经分配，返回已分配的端口
        if container_name in self._allocated_ports:
            return self._allocated_ports[container_name]

        # 如果有首选端口（从配置文件读取），且未被其他容器占用，优先使用
        if preferred_port and not self._is_port_in_use(preferred_port):
            self._allocated_ports[container_name] = preferred_port
            return preferred_port

        # 计算一个确定的端口（基于容器名哈希）
        hash_value = int(hashlib.md5(container_name.encode()).hexdigest(), 16)
        port_range = FRP_CONTAINER_PORT_RANGE[1] - FRP_CONTAINER_PORT_RANGE[0]
        port = FRP_CONTAINER_PORT_RANGE[0] + (hash_value % port_range)

        # 检查端口是否已被占用（避免哈希碰撞）
        original_port = port
        while self._is_port_in_use(port) and port < FRP_CONTAINER_PORT_RANGE[1]:
            port += 1
            if port == original_port:  # 绕了一圈，端口用尽
                raise RuntimeError(
                    f"No free ports available in range {FRP_CONTAINER_PORT_RANGE}"
                )

        self._allocated_ports[container_name] = port
        LOGGER.debug(
            "Allocated port %d for container %s (hash base: %d)",
            port,
            container_name,
            original_port,
        )
        return port

    def _is_port_in_use(self, port: int) -> bool:
        """检查端口是否已被占用."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def _load_existing_visitor_ports(self) -> dict[str, int]:
        """从当前 visitor 配置文件读取容器到 VPS 端口的映射."""
        if not self.config_file.exists():
            return {}

        config = configparser.ConfigParser()
        config.read(self.config_file)

        ports: dict[str, int] = {}
        for section in config.sections():
            if not section.startswith("visitor-"):
                continue

            container_name = section.removeprefix("visitor-")
            bind_port = config.getint(section, "bind_port", fallback=0)
            if container_name and bind_port:
                ports[container_name] = bind_port

        return ports

    def build_visitor_config(
        self,
        containers: list[dict[str, Any]],
        existing_ports: dict[str, int] | None = None,
    ) -> configparser.ConfigParser:
        """构建 visitor 配置."""
        config = configparser.ConfigParser()
        setattr(config, "optionxform", str)
        existing_ports = existing_ports or {}

        # 基础配置
        config["common"] = {
            "server_addr": FRP_SERVER_ADDR,
            "server_port": str(FRP_SERVER_PORT),
            "token": FRP_TOKEN,
        }

        # 为每个容器创建 visitor
        for container in containers:
            name = container.get("container_name", "")
            secret = container.get("secret_key", "")
            node_id = container.get("node_id", "unknown")

            if not name or not secret:
                continue

            # 分配端口
            port = self.allocate_port(name, preferred_port=existing_ports.get(name))

            section_name = f"visitor-{name}"
            config[section_name] = {
                "type": "stcp",
                "role": "visitor",
                "server_name": f"container-{name}",
                "sk": secret,
                "bind_addr": "0.0.0.0",
                "bind_port": str(port),
            }

            LOGGER.debug(
                "Added visitor for %s on port %s (node: %s)", name, port, node_id
            )

        return config

    def update_config(self) -> bool:
        """更新 visitor 配置."""
        if not self.enabled:
            LOGGER.info("FRP visitor is disabled")
            return True

        try:
            # 获取所有容器的 secret
            containers = self.fetch_container_secrets()
            LOGGER.info("Fetched %d containers from nodes", len(containers))

            signature = self._build_sync_signature(containers)
            existing_ports = self._load_existing_visitor_ports()

            if (
                signature == self._last_sync_signature
                and existing_ports
                and time.time() - self._last_sync_at < 10
            ):
                self._allocated_ports = dict(existing_ports)
                return True

            self._allocated_ports = {}

            # 构建配置
            config = self.build_visitor_config(containers, existing_ports)

            # 确保目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            # 写入临时文件，然后原子替换
            temp_file = self.config_file.with_suffix(".tmp")
            with open(temp_file, "w") as f:
                config.write(f)
            temp_file.replace(self.config_file)

            LOGGER.info("Updated frpc visitor config with %d visitors", len(containers))

            # 重载配置
            self._reload_frpc()

            # 同步 VPS 访问信息到各节点
            self._sync_vps_access_to_nodes(containers)
            self._last_sync_signature = signature
            self._last_sync_at = time.time()

            return True

        except Exception as exc:
            LOGGER.error("Failed to update visitor config: %s", exc)
            return False

    def _sync_vps_access_to_nodes(self, containers: list[dict[str, Any]]) -> None:
        """将 VPS 访问信息同步到各个 Servermanager 节点."""
        import httpx

        for container in containers:
            name = container.get("container_name", "")
            node_id = container.get("node_id", "")

            if not name or not node_id:
                continue

            # 获取分配的端口
            port = self._allocated_ports.get(name)
            if port is None:
                continue

            # 获取节点配置
            node_cfg = NODES.get(node_id, {})
            api_base = node_cfg.get("api", "")
            if not api_base:
                continue

            # 构建 VPS 访问信息
            vps_info = {
                "vps_port": port,
                "vps_ip": VPS_PUBLIC_IP,
                "ssh_cmd": f"ssh -p {port} root@{VPS_PUBLIC_IP}",
            }

            try:
                headers = {"X-Internal-Token": INTERNAL_SERVICE_TOKEN}
                response = httpx.post(
                    f"{api_base}/api/instances/{name}/vps-access",
                    headers=headers,
                    json=vps_info,
                    timeout=5.0,
                )
                if response.status_code == 200:
                    LOGGER.debug(
                        "Synced VPS access info for %s to node %s", name, node_id
                    )
                else:
                    LOGGER.warning(
                        "Failed to sync VPS access for %s: %s %s",
                        name,
                        response.status_code,
                        response.text,
                    )
            except Exception as exc:
                LOGGER.warning("Failed to sync VPS access for %s: %s", name, exc)

    def _reload_frpc(self) -> None:
        """热重载 frpc."""
        try:
            result = subprocess.run(
                ["systemctl", "reload", "frpc-visitors"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                LOGGER.debug("Reloaded frpc-visitors via systemctl")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        try:
            result = subprocess.run(
                ["systemctl", "restart", "frpc-visitors"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                LOGGER.info("Reload unsupported; restarted frpc-visitors instead")
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        LOGGER.warning(
            "Could not reload or restart frpc-visitors automatically. "
            "Please ensure the service can be managed via systemctl."
        )

    def _build_sync_signature(self, containers: list[dict[str, Any]]) -> str:
        """构建容器列表签名，用于避免重复刷新相同 visitor 配置."""
        normalized = sorted(
            (
                str(c.get("container_name", "")),
                str(c.get("secret_key", "")),
                str(c.get("node_id", "")),
            )
            for c in containers
            if c.get("container_name") and c.get("secret_key")
        )
        payload = "|".join(":".join(item) for item in normalized)
        return hashlib.sha256(payload.encode()).hexdigest()

    def get_container_access_url(self, container_name: str) -> str | None:
        """获取容器的访问地址."""
        port = self._load_existing_visitor_ports().get(container_name)
        if port is None:
            return None

        return f"ssh://root@{VPS_PUBLIC_IP}:{port}"

    def get_all_mappings(self) -> dict[str, dict[str, Any]]:
        """获取所有容器的访问映射."""
        self.update_config()

        containers = self.fetch_container_secrets()
        visitor_ports = self._load_existing_visitor_ports()

        mappings = {}
        for c in containers:
            name = c.get("container_name", "")
            if not name:
                continue

            port = visitor_ports.get(name)
            if port is None:
                LOGGER.warning("Visitor port not ready for container %s", name)
                continue

            mappings[name] = {
                "node_id": c.get("node_id"),
                "node_name": c.get("node_name"),
                "ssh_port": c.get("ssh_port"),
                "vps_port": port,
                "access_url": f"ssh://root@{VPS_PUBLIC_IP}:{port}",
            }

        return mappings


# 全局实例
frp_visitor_manager = FrpVisitorManager()
