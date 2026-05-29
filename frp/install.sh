#!/bin/bash
# FRP install helper for the simplified Clustermanager VPS.

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
rm -rf "frp_${FRP_VERSION}_${FRP_ARCH}"

sudo mkdir -p /etc/frp

sudo cp "${SCRIPT_DIR}/frps.service" /etc/systemd/system/

if [ ! -f /etc/frp/frps.ini ]; then
    sudo cp "${SCRIPT_DIR}/frps.ini" /etc/frp/
    echo "Created default frps.ini. Please edit it to set your token!"
fi

sudo systemctl daemon-reload

echo "=== FRP installed successfully ==="
echo ""
echo "Next steps:"
echo "1. Edit /etc/frp/frps.ini and set token / allow_ports"
echo ""
echo "2. Start frps:"
echo "   sudo systemctl enable frps"
echo "   sudo systemctl start frps"
echo ""
echo "3. Configure Clustermanager .env from .env.copy"
echo ""
echo "4. Start Clustermanager:"
echo "   ./start.sh"
echo ""
echo "Check status:"
echo "   sudo systemctl status frps"
