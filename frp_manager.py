"""FRP visitor manager - per-container isolated visitor services on VPS."""

from __future__ import annotations

import configparser
import hashlib
import logging
import socket
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
    FRP_VISITOR_CONFIG_DIR,
    INTERNAL_SERVICE_TOKEN,
    NODES,
    VPS_PUBLIC_IP,
)

LOGGER = logging.getLogger(__name__)


class FrpVisitorManager:
    """Manage per-container visitor services on VPS."""

    def __init__(self) -> None:
        self.enabled = FRP_ENABLED
        self.instance_config_dir = Path(FRP_VISITOR_CONFIG_DIR)
        self.instance_config_dir.mkdir(parents=True, exist_ok=True)
        self._allocated_ports: dict[str, int] = {}

    def fetch_container_secrets(self) -> list[dict[str, Any]]:
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
                for container in node_containers:
                    container["node_id"] = node_id
                    container["node_name"] = node_config["name"]
                containers.extend(node_containers)
            except Exception as exc:
                LOGGER.error(
                    "Failed to fetch FRP secrets from %s (%s): %s",
                    node_id,
                    api_base,
                    exc,
                )
        return containers

    def _instance_config_path(self, container_name: str) -> Path:
        return self.instance_config_dir / f"{container_name}.ini"

    def _instance_service_name(self, container_name: str) -> str:
        return f"frpc-visitor@{container_name}.service"

    def _run_systemctl(self, action: str, service_name: str, timeout: int = 10) -> bool:
        commands = [
            ["sudo", "-n", "systemctl", action, service_name],
            ["systemctl", action, service_name],
        ]
        for command in commands:
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

            if result.returncode == 0:
                LOGGER.info(
                    "Ran '%s' for %s via command: %s",
                    action,
                    service_name,
                    " ".join(command),
                )
                return True

            error_text = (result.stderr or result.stdout or "").strip()
            if error_text:
                LOGGER.warning(
                    "Failed '%s' for %s via '%s': %s",
                    action,
                    service_name,
                    " ".join(command),
                    error_text,
                )
        return False

    def _is_port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    def _load_existing_visitor_ports(self) -> dict[str, int]:
        ports: dict[str, int] = {}
        if self.instance_config_dir.exists():
            for cfg_file in sorted(self.instance_config_dir.glob("*.ini")):
                try:
                    config = configparser.ConfigParser()
                    config.read(cfg_file)
                    for section in config.sections():
                        if not section.startswith("visitor-"):
                            continue
                        name = section.removeprefix("visitor-")
                        bind_port = config.getint(section, "bind_port", fallback=0)
                        if name and bind_port:
                            ports[name] = bind_port
                            break
                except Exception as exc:
                    LOGGER.warning(
                        "Failed to parse visitor config %s: %s", cfg_file, exc
                    )

        if ports:
            return ports

        legacy_file = Path(FRP_CONFIG_FILE)
        if legacy_file.exists():
            try:
                config = configparser.ConfigParser()
                config.read(legacy_file)
                for section in config.sections():
                    if not section.startswith("visitor-"):
                        continue
                    name = section.removeprefix("visitor-")
                    bind_port = config.getint(section, "bind_port", fallback=0)
                    if name and bind_port:
                        ports[name] = bind_port
            except Exception as exc:
                LOGGER.warning(
                    "Failed to parse legacy visitor config %s: %s",
                    legacy_file,
                    exc,
                )
        return ports

    def allocate_port(
        self, container_name: str, preferred_port: int | None = None
    ) -> int:
        if container_name in self._allocated_ports:
            return self._allocated_ports[container_name]

        if preferred_port:
            self._allocated_ports[container_name] = preferred_port
            return preferred_port

        hash_value = int(hashlib.md5(container_name.encode()).hexdigest(), 16)
        start, end = FRP_CONTAINER_PORT_RANGE
        port_range = end - start
        port = start + (hash_value % port_range)
        original_port = port
        while self._is_port_in_use(port) and port < end:
            port += 1
            if port == original_port:
                raise RuntimeError(
                    f"No free ports available in range {FRP_CONTAINER_PORT_RANGE}"
                )

        self._allocated_ports[container_name] = port
        return port

    def _build_instance_config(
        self,
        container_name: str,
        secret_key: str,
        bind_port: int,
    ) -> str:
        lines = [
            "[common]",
            f"server_addr = {FRP_SERVER_ADDR}",
            f"server_port = {FRP_SERVER_PORT}",
            f"token = {FRP_TOKEN}",
            "",
            f"[visitor-{container_name}]",
            "type = stcp",
            "role = visitor",
            f"server_name = container-{container_name}",
            f"sk = {secret_key}",
            "bind_addr = 0.0.0.0",
            f"bind_port = {bind_port}",
            "",
        ]
        return "\n".join(lines)

    def _write_instance_config(
        self,
        container_name: str,
        secret_key: str,
        bind_port: int,
    ) -> bool:
        config_path = self._instance_config_path(container_name)
        rendered = self._build_instance_config(container_name, secret_key, bind_port)
        existing = config_path.read_text() if config_path.exists() else ""
        if existing == rendered:
            return False
        tmp_file = config_path.with_suffix(".tmp")
        tmp_file.write_text(rendered)
        tmp_file.replace(config_path)
        return True

    def _sync_vps_access_to_nodes(self, containers: list[dict[str, Any]]) -> None:
        for container in containers:
            name = container.get("container_name", "")
            node_id = container.get("node_id", "")
            if not name or not node_id:
                continue

            port = self._allocated_ports.get(name)
            if port is None:
                continue

            node_cfg = NODES.get(node_id, {})
            api_base = node_cfg.get("api", "")
            if not api_base:
                continue

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
                if response.status_code == 404:
                    LOGGER.warning(
                        "Instance %s not found on node %s when syncing vps_access; "
                        "triggering node FRP sync once",
                        name,
                        node_id,
                    )
                    sync_resp = httpx.post(
                        f"{api_base}/api/frp/sync",
                        headers=headers,
                        timeout=8.0,
                    )
                    if sync_resp.status_code == 200:
                        retry_resp = httpx.post(
                            f"{api_base}/api/instances/{name}/vps-access",
                            headers=headers,
                            json=vps_info,
                            timeout=5.0,
                        )
                        if retry_resp.status_code != 200:
                            LOGGER.warning(
                                "Failed to sync VPS access for %s after FRP sync: %s %s",
                                name,
                                retry_resp.status_code,
                                retry_resp.text,
                            )
                    else:
                        LOGGER.warning(
                            "Node %s FRP sync request failed: %s %s",
                            node_id,
                            sync_resp.status_code,
                            sync_resp.text,
                        )
                elif response.status_code != 200:
                    LOGGER.warning(
                        "Failed to sync VPS access for %s: %s %s",
                        name,
                        response.status_code,
                        response.text,
                    )
            except Exception as exc:
                LOGGER.warning("Failed to sync VPS access for %s: %s", name, exc)

    def _reconcile(self, containers: list[dict[str, Any]]) -> bool:
        existing_ports = self._load_existing_visitor_ports()
        self._allocated_ports = {}
        desired: dict[str, dict[str, Any]] = {}

        for container in containers:
            name = str(container.get("container_name", ""))
            secret = str(container.get("secret_key", ""))
            if not name or not secret:
                continue
            bind_port = self.allocate_port(name, existing_ports.get(name))
            desired[name] = {
                "secret": secret,
                "bind_port": bind_port,
            }

        success = True

        for name, item in sorted(desired.items()):
            changed = self._write_instance_config(
                name, item["secret"], item["bind_port"]
            )
            service_name = self._instance_service_name(name)
            if name not in existing_ports:
                success = self._run_systemctl("start", service_name) and success
                continue
            if changed:
                reloaded = self._run_systemctl("reload", service_name, timeout=5)
                if not reloaded:
                    success = self._run_systemctl("restart", service_name) and success

        stale_names = sorted(set(existing_ports.keys()) - set(desired.keys()))
        for name in stale_names:
            service_name = self._instance_service_name(name)
            self._run_systemctl("stop", service_name)
            cfg_path = self._instance_config_path(name)
            try:
                if cfg_path.exists():
                    cfg_path.unlink()
            except Exception as exc:
                success = False
                LOGGER.warning(
                    "Failed to delete stale visitor config %s: %s", cfg_path, exc
                )

        self._sync_vps_access_to_nodes(containers)
        return success

    def update_config(self) -> bool:
        if not self.enabled:
            LOGGER.info("FRP visitor is disabled")
            return True
        try:
            containers = self.fetch_container_secrets()
            LOGGER.info(
                "Reconciling per-container visitor services: %d", len(containers)
            )
            return self._reconcile(containers)
        except Exception as exc:
            LOGGER.error("Failed to reconcile visitor config: %s", exc)
            return False

    def get_container_access_url(self, container_name: str) -> str | None:
        port = self._load_existing_visitor_ports().get(container_name)
        if port is None:
            return None
        return f"ssh://root@{VPS_PUBLIC_IP}:{port}"

    def get_all_mappings(self) -> dict[str, dict[str, Any]]:
        self.update_config()
        containers = self.fetch_container_secrets()
        ports = self._load_existing_visitor_ports()
        mappings: dict[str, dict[str, Any]] = {}
        for container in containers:
            name = container.get("container_name", "")
            if not name:
                continue
            port = ports.get(name)
            if port is None:
                continue
            mappings[name] = {
                "node_id": container.get("node_id"),
                "node_name": container.get("node_name"),
                "ssh_port": container.get("ssh_port"),
                "vps_port": port,
                "access_url": f"ssh://root@{VPS_PUBLIC_IP}:{port}",
            }
        return mappings


frp_visitor_manager = FrpVisitorManager()
