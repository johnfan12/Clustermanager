#!/bin/bash
# FRP 安装脚本 — VPS (Clustermanager) 端

set -e

FRP_VERSION="0.58.1"
FRP_ARCH="linux_amd64"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install_binary_safe() {
  local src="$1"
  local dst="$2"
  local tmp_dst="${dst}.new"
  sudo install -m 0755 "$src" "$tmp_dst"
  sudo mv -f "$tmp_dst" "$dst"
}

echo "=== Installing FRP v${FRP_VERSION} ==="

# 下载并安装 frp
cd /tmp
wget -q "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz"
tar -xzf "frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz"
install_binary_safe "frp_${FRP_VERSION}_${FRP_ARCH}/frps" "/usr/local/bin/frps"
install_binary_safe "frp_${FRP_VERSION}_${FRP_ARCH}/frpc" "/usr/local/bin/frpc"
rm -rf "frp_${FRP_VERSION}_${FRP_ARCH}"

# 创建配置目录
sudo mkdir -p /etc/frp
sudo mkdir -p /etc/frp/visitors

# 安装 systemd 服务
sudo cp "${SCRIPT_DIR}/frps.service" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/frpc-visitors.service" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/frpc-visitor@.service" /etc/systemd/system/

# 复制默认配置（如果不存在）
if [ ! -f /etc/frp/frps.ini ]; then
    sudo cp "${SCRIPT_DIR}/frps.ini" /etc/frp/
    echo "Created default frps.ini. Please edit it to set your token!"
fi

# 重新加载 systemd
sudo systemctl daemon-reload

echo "=== FRP installed successfully ==="
echo ""
echo "Next steps:"
echo "1. Configure FRP_* variables in Clustermanager/.env"
echo "   (FRP_SERVER_PORT / FRP_TOKEN / FRP_CONTAINER_PORT_RANGE)"
echo "   NODES_JSON.api ports will be auto-added to frps allow_ports."
echo "   Use FRP_API_ALLOW_PORTS for extra API tunnel ports if needed."
echo ""
echo "2. Start frps:"
echo "   sudo systemctl enable frps"
echo "   sudo systemctl start frps"
echo ""
echo "3. Start frpc-visitors:"
echo "   Visitor tunnels now run in per-instance mode via"
echo "   frpc-visitor@<container>.service managed by Clustermanager."
echo "   Do NOT keep legacy frpc-visitors service running in parallel."
echo ""
echo "4. Starting Clustermanager will sync /etc/frp/frps.ini from .env"
echo "   and restart frps automatically when the token/port changes."
echo ""
echo "5. Start Clustermanager:"
echo "   python main.py"
echo ""
echo "Check status:"
echo "   sudo systemctl status frps"
echo "   sudo systemctl status 'frpc-visitor@*'"
