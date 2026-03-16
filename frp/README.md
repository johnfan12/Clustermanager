# FRP 容器访问配置（VPS 端）

## 架构说明

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                    VPS                                      │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                           frps (7000)                                  │ │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐       │ │
│  │  │  visitor-port-1 │  │  visitor-port-2 │  │  visitor-port-3 │       │ │
│  │  │  bind_port: X   │  │  bind_port: Y   │  │  bind_port: Z   │       │ │
│  │  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘       │ │
│  │           │                    │                    │                │ │
│  │           └────────────────────┴────────────────────┘                │ │
│  │                              ▼                                       │ │
│  │                    User SSH Access                                   │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                    ▲                                        │
│                                    │ stcp (secret TCP)                     │
│              ┌─────────────────────┼─────────────────────┐                  │
│              │                     │                     │                  │
│       ┌──────┴──────┐       ┌──────┴──────┐       ┌──────┴──────┐          │
│       │   Node 1    │       │   Node 2    │       │   Node 3    │          │
│       │ frpc-client │       │ frpc-client │       │ frpc-client │          │
│       │ (containers)│       │ (containers)│       │ (containers)│          │
│       └─────────────┘       └─────────────┘       └─────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 安装步骤

```bash
# 1. 运行安装脚本
cd Clustermanager/frp
sudo bash install.sh

# 2. 配置 frps
sudo nano /etc/frp/frps.ini
# 修改 token 为你自己的值

# 3. 启动 frps
sudo systemctl enable frps
sudo systemctl start frps

# 4. 配置 frpc-visitors
sudo systemctl enable frpc-visitors
sudo systemctl start frpc-visitors

# 5. 更新 Clustermanager 配置
# 编辑 config.py，设置 FRP_TOKEN 与 frps.ini 一致

# 6. 启动 Clustermanager
python main.py
```

## 服务管理

```bash
# 查看 frps 状态
sudo systemctl status frps
sudo journalctl -u frps -f

# 查看 frpc-visitors 状态
sudo systemctl status frpc-visitors
sudo journalctl -u frpc-visitors -f

# 手动触发配置同步
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/api/frp/sync
```

## 配置说明

### frps.ini

- `bind_port`: frp 服务器监听端口（默认 7000）
- `token`: 安全令牌，必须与所有 frpc 客户端一致
- `allow_ports`: visitor 可以绑定的端口范围

### Clustermanager config.py

- `FRP_ENABLED`: 是否启用 FRP 功能
- `FRP_SERVER_ADDR`: 通常为 "localhost"（frps 运行在同一台机器）
- `FRP_SERVER_PORT`: 与 frps.ini 中的 bind_port 一致
- `FRP_TOKEN`: 与 frps.ini 中的 token 一致

## API 端点

- `GET /api/frp/containers` - 查看所有容器访问映射
- `POST /api/frp/sync` - 手动同步 FRP 配置
- `POST /api/cluster/instances/{id}/connect` - 获取实例连接信息

## 故障排查

1. **visitor 无法连接**
   - 检查 frps 是否运行: `sudo systemctl status frps`
   - 检查 token 是否一致
   - 检查端口范围: `allow_ports` 必须包含访客端口

2. **无法获取容器信息**
   - 检查节点 API 是否可达: `curl http://localhost:18881/api/instances`
   - 检查 admin_token 是否配置正确

3. **连接被拒绝**
   - 检查防火墙是否开放访客端口 (30000-39999)
   - 检查容器是否正在运行
