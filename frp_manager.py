"""FRP Visitor 管理模块 — 在 VPS 上为各节点容器创建访问隧道."""

from __future__ import annotations

import configparser
import logging
import subprocess
from pathlib import Path
from typing import Any

import httpx

from config import (
    FRP_CONFIG_FILE,
    FRP_CONTAINER_PORT_RANGE,
    FRP_ENABLED,
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

    def fetch_container_secrets(self) -> list[dict[str, Any]]:
        """从所有节点获取容器的 FRP 连接信息."""
        containers = []

        for node_id, node_config in NODES.items():
            api_base = node_config["api"]
            token = node_config["admin_token"]

            try:
                headers = {"Authorization": f"Bearer {token}"}
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
                    node_id, api_base, exc
                )

        return containers

    def allocate_port(self, container_name: str) -> int:
        """为容器分配 VPS 上的访问端口."""
        # 如果已经分配，返回已分配的端口
        if container_name in self._allocated_ports:
            return self._allocated_ports[container_name]

        # 计算一个确定的端口（基于容器名哈希）
        import hashlib

        hash_value = int(hashlib.md5(container_name.encode()).hexdigest(), 16)
        port_range = FRP_CONTAINER_PORT_RANGE[1] - FRP_CONTAINER_PORT_RANGE[0]
        port = FRP_CONTAINER_PORT_RANGE[0] + (hash_value % port_range)

        # 检查端口是否已被占用
        while self._is_port_in_use(port) and port < FRP_CONTAINER_PORT_RANGE[1]:
            port += 1

        self._allocated_ports[container_name] = port
        return port

    def _is_port_in_use(self, port: int) -> bool:
        """检查端口是否已被占用."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def build_visitor_config(self, containers: list[dict[str, Any]]) -> configparser.ConfigParser:
        """构建 visitor 配置."""
        config = configparser.ConfigParser()
        config.optionxform = str

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
            port = self.allocate_port(name)

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
                "Added visitor for %s on port %s (node: %s)",
                name, port, node_id
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

            # 构建配置
            config = self.build_visitor_config(containers)

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

            return True

        except Exception as exc:
            LOGGER.error("Failed to update visitor config: %s", exc)
            return False

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

        LOGGER.warning(
            "Could not reload frpc-visitors automatically. "
            "Please ensure 'systemctl reload frpc-visitors' works."
        )

    def get_container_access_url(self, container_name: str) -> str | None:
        """获取容器的访问地址."""
        if container_name not in self._allocated_ports:
            return None

        port = self._allocated_ports[container_name]
        return f"ssh://root@{VPS_PUBLIC_IP}:{port}"

    def get_all_mappings(self) -> dict[str, dict[str, Any]]:
        """获取所有容器的访问映射."""
        # 刷新配置
        containers = self.fetch_container_secrets()

        mappings = {}
        for c in containers:
            name = c.get("container_name", "")
            if name:
                port = self.allocate_port(name)
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
