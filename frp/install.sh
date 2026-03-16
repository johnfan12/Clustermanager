#!/bin/bash
# FRP 安装脚本 — VPS (Clustermanager) 端

set -e

FRP_VERSION="0.58.1"
FRP_ARCH="linux_amd64"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing FRP v${FRP_VERSION} ==="

# 下载并安装 frp
cd /tmp
wget -q "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz"
tar -xzf "frp_${FRP_VERSION}_${FRP_ARCH}.tar.gz"
sudo cp "frp_${FRP_VERSION}_${FRP_ARCH}/frps" /usr/local/bin/
sudo cp "frp_${FRP_VERSION}_${FRP_ARCH}/frpc" /usr/local/bin/
sudo chmod +x /usr/local/bin/frps /usr/local/bin/frpc
rm -rf "frp_${FRP_VERSION}_${FRP_ARCH}"

# 创建配置目录
sudo mkdir -p /etc/frp

# 安装 systemd 服务
sudo cp "${SCRIPT_DIR}/frps.service" /etc/systemd/system/
sudo cp "${SCRIPT_DIR}/frpc-visitors.service" /etc/systemd/system/

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
echo "1. Edit /etc/frp/frps.ini and set your token"
echo ""
echo "2. Start frps:"
echo "   sudo systemctl enable frps"
echo "   sudo systemctl start frps"
echo ""
echo "3. Start frpc-visitors:"
echo "   sudo systemctl enable frpc-visitors"
echo "   sudo systemctl start frpc-visitors"
echo ""
echo "4. Configure Clustermanager config.py:"
echo "   FRP_TOKEN = 'your-secret-token' (same as frps.ini)"
echo ""
echo "5. Start Clustermanager:"
echo "   python main.py"
echo ""
echo "Check status:"
echo "   sudo systemctl status frps"
echo "   sudo systemctl status frpc-visitors"
