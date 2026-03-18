# GPU 集群跳板机聚合管理服务

轻量级 GPU 集群聚合管理平台，通过 frp 内网穿透访问各 GPU 节点的 `gpu_manager` API，
提供**集群总览**和**跨节点实例汇总**功能。不操作 Docker，不连接数据库，纯数据聚合与展示。

---

## 架构说明

```

## Quickstart

下面这组命令面向"1 台 VPS + 1 台 GPU 节点"，目标是命令执行完即可访问聚合页，并在节点创建实例后直接看到 VPS SSH 命令。

先在 VPS 设置变量：

```bash
export VPS_IP=YOUR_VPS_PUBLIC_IP
export JWT_SECRET=change-this-to-a-strong-secret-key
export INTERNAL_SERVICE_TOKEN=change-this-internal-service-token
export FRP_TOKEN=change-this-frp-token
export CLUSTER_ADMIN_PASSWORD=change-this-cluster-admin-password
export NODE1_ADMIN_TOKEN=PASTE_SERVERMANAGER_ADMIN_ACCESS_TOKEN_HERE
```

然后在 `Clustermanager` 目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p logs
sudo mkdir -p /etc/frp

cat > .env <<EOF
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=24
INTERNAL_SERVICE_TOKEN=${INTERNAL_SERVICE_TOKEN}
ADMIN_USERNAME=admin
ADMIN_PASSWORD=${CLUSTER_ADMIN_PASSWORD}
FRP_ENABLED=true
FRP_SERVER_ADDR=localhost
FRP_SERVER_PORT=7000
FRP_TOKEN=${FRP_TOKEN}
FRP_CONFIG_DIR=/etc/frp
FRP_CONTAINER_PORT_RANGE=30000-39999
VPS_PUBLIC_IP=${VPS_IP}
NODES_JSON={"node1":{"name":"node1","api":"http://127.0.0.1:18881","admin_token":"${NODE1_ADMIN_TOKEN}","gpu_count":1,"gpu_model":"GPU"}}
NODE_WEB_URLS_JSON={"node1":"http://${VPS_IP}:18881"}
EOF

cd frp
sudo bash install.sh
cd ..

sudo sed -i "s/^token = .*/token = ${FRP_TOKEN}/" /etc/frp/frps.ini
sudo sed -i 's/^allow_ports = .*/allow_ports = 18881,30000-39999/' /etc/frp/frps.ini

sudo systemctl enable --now frps frpc-visitors

chmod +x start.sh
nohup ./start.sh > logs/clustermanager.log 2>&1 &
sleep 5

curl http://127.0.0.1:9999/
curl http://127.0.0.1:18881/api/frp/containers -H "X-Internal-Token: ${INTERNAL_SERVICE_TOKEN}"
```

如果最后一条 `curl` 能返回节点容器列表，说明：

- VPS -> 节点 API 穿透通了
- `Clustermanager` 能读到节点容器 FRP 信息
- 后续创建实例后会自动生成 VPS SSH 命令

浏览器访问：

```text
http://YOUR_VPS_PUBLIC_IP:9999
```

登录账号：

- 用户名：`admin`
- 密码：你刚设置的 `CLUSTER_ADMIN_PASSWORD`
┌───────────────────────────────────┐
│          公网 VPS (本项目)          │
│                                   │
│  Nginx (:80/443)                  │
│    └─→ 聚合服务 (:9999)            │
│          ├─→ localhost:18881 ──┐   │
│          └─→ localhost:18882 ──┤   │
│                                │   │
│  frps (:7000)                  │   │
│    ├─ tcp :18881 ◄─────────────┤   │
│    ├─ tcp :18882 ◄─────────────┤   │
│    ├─ tcp :10021 ◄─────────────┤   │
│    └─ tcp :10022 ◄─────────────┘   │
└────────────┬──────────┬───────────┘
             │  frp 隧道  │
     ┌───────┘          └───────┐
     ▼                          ▼
┌──────────┐            ┌──────────┐
│  GPU 节点1 │            │  GPU 节点2 │
│  frpc     │            │  frpc     │
│  gpu_mgr  │            │  gpu_mgr  │
│  :8888    │            │  :8888    │
└──────────┘            └──────────┘
```

---

## 1. VPS 部署步骤

### 1.1 安装 frps（使用一键脚本）

```bash
cd frp
sudo bash install.sh
```

编辑配置：
```bash
sudo nano /etc/frp/frps.ini
# 修改 token 为你自己的值
```

启动服务：
```bash
sudo systemctl enable --now frps
sudo systemctl enable --now frpc-visitors
```

### 1.2 部署聚合服务

```bash
cd /opt/cluster_manager    # 或你选择的部署目录
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 复制并编辑 .env 配置文件
cp .env.copy .env
nano .env
```

至少修改以下配置：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `JWT_SECRET` | 与所有节点保持一致 | `your-strong-secret` |
| `ADMIN_PASSWORD` | 跳板机管理员密码 | `your-admin-password` |
| `FRP_TOKEN` | 与 frps.ini 一致 | `your-frp-token` |
| `VPS_PUBLIC_IP` | VPS 公网 IP | `1.2.3.4` |
| `NODES_JSON` | 节点列表（推荐使用 `127.0.0.1:18881`） | `{"node1": {...}}` |

启动服务：
```bash
chmod +x start.sh
./start.sh

# 或使用 nohup / systemd 后台运行
nohup ./start.sh > logs/server.log 2>&1 &
```

### 1.3 配置 Nginx

```bash
sudo cp nginx/gpu.conf /etc/nginx/sites-available/gpu.conf
sudo ln -s /etc/nginx/sites-available/gpu.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 1.4 可选：申请 HTTPS 证书

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

申请完成后取消 `nginx/gpu.conf` 中 HTTPS 部分的注释。

---

## 2. GPU 节点配置步骤

### 2.1 安装 frpc

```bash
wget https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_amd64.tar.gz
tar -xzf frp_0.52.3_linux_amd64.tar.gz
sudo cp frp_0.52.3_linux_amd64/frpc /usr/local/bin/
sudo mkdir -p /etc/frp
```

### 2.2 配置 frpc（使用一键脚本）

在 GPU 节点上：

```bash
cd Servermanager/frp   # 进入 Servermanager 的 frp 目录
sudo bash install.sh
```

编辑配置：
```bash
# 编辑 Servermanager 的 .env 文件
cd ..
nano .env
```

关键配置：
```env
FRP_ENABLED=true
FRP_SERVER_ADDR=your-vps-public-ip
FRP_SERVER_PORT=7000
FRP_TOKEN=your-frp-secret-token
```

启动服务：
```bash
sudo systemctl enable --now frpc-containers
```

> **注意**：Servermanager 和 Clustermanager 的 `JWT_SECRET`、`INTERNAL_SERVICE_TOKEN` 必须一致，这是 SSO 和服务间回写的前提。

---

## 3. 节点配置（.env 或 config.py）

### 3.1 使用 .env 文件（推荐）

编辑 `.env` 文件，使用 JSON 格式配置节点：

```env
NODES_JSON='{
    "node1": {
        "name": "节点1 · A100 × 8",
        "api": "http://localhost:18881",
        "admin_token": "从节点获取的jwt-token",
        "gpu_count": 8,
        "gpu_model": "A100 80G"
    },
    "node2": {
        "name": "节点2 · RTX3090 × 4",
        "api": "http://localhost:18882",
        "admin_token": "从节点获取的jwt-token",
        "gpu_count": 4,
        "gpu_model": "RTX 3090 24G"
    }
}'

NODE_WEB_URLS_JSON='{
    "node1": "http://your-vps-ip:18881",
    "node2": "http://your-vps-ip:18882"
}'
```

### 3.2 admin_token 的获取方法

`admin_token` 仍用于聚合节点 GPU / 管理员实例列表，需从对应节点的 Servermanager 获取：

```bash
# 在 VPS 上（frp 穿透已建立后）
curl -X POST http://127.0.0.1:18881/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"节点管理员密码"}'
```

返回的 `access_token` 即为该节点的 `admin_token`，填入 `.env` 或 `config.py` 对应节点配置中。

### 3.3 跨节点注册同步（方案1：中心用户库 + 首次登录自动补建）

当前版本支持你选择的方案 1：

- 用户在 `Clustermanager` 注册时，会同时：
  - 注册到当前所选节点
  - 写入 VPS 本地中心用户库（`CLUSTER_USER_DB_PATH`）
- 当用户后续登录到一个新节点，如果该节点还没有这个账号：
  - `Clustermanager` 会先验证中心库密码
  - 然后自动调用该节点注册接口补建账号
  - 再自动登录并返回 token

默认配置（见 `.env.copy`）：

```env
CLUSTER_USER_DB_PATH=./runtime/cluster_users.db
AUTO_PROVISION_ON_NODE_LOGIN=true
```

> 注意：中心库保存在 VPS，本机请做好备份；如果你关闭 `AUTO_PROVISION_ON_NODE_LOGIN`，则回到“每个节点手动注册一次”的行为。

---

## 4. SSO 原理说明

本项目与各 GPU 节点的 Servermanager 共享同一个 `JWT_SECRET`。

- 用户在跳板机登录后，跳板机使用共享密钥签发 JWT token
- 前端点击"进入管理"时，URL 末尾携带 `?token=xxx`
- 节点 Servermanager 使用相同密钥验证 token，无需再次登录

**关键操作**：确保所有节点的 `.env` 文件中 `JWT_SECRET` 与 Clustermanager 的 `.env` 完全一致。

---

## 5. 常见问题

### Q: frp 连接失败
- 检查 VPS 安全组/防火墙是否放行 7000 端口
- 确认 frps 和 frpc 的 `token` 一致
- 查看 frps 日志：`journalctl -u frps -f`
- 查看 frpc 日志：`journalctl -u frpc -f`

### Q: 节点显示离线
- 确认对应节点的 frpc 服务正在运行：`systemctl status frpc`
- 在 VPS 上测试连通性：`curl http://localhost:18881/api/gpus/status`
- 检查聚合服务日志：`tail -f logs/aggregator.log`
- 确认 `config.py` 中的 `api` 端口与 frpc `remote_port` 一致

### Q: 跳转到节点后需要重新登录
- 确认节点 `gpu_manager` 的 `JWT_SECRET` 与本项目一致
- 确认节点 `gpu_manager` 的 JWT 算法为 `HS256`
- 检查 token 是否包含必要的 claims（`sub`、`exp`）

### Q: 管理员 token 过期
- `admin_token` 是长期 token，但仍可能过期
- 过期后重新调用节点 `/api/auth/login` 获取新 token
- 更新 `.env` 或 `config.py` 并重启聚合服务

### Q: 如何通过 FRP 访问容器 SSH
容器创建后，Clustermanager 会自动同步 FRP visitor 配置。获取访问方式：

```bash
# 查询所有容器的访问映射
curl -H "Authorization: Bearer TOKEN" http://127.0.0.1:9999/api/frp/containers

# 查询单个实例的连接信息
curl -H "Authorization: Bearer TOKEN" \
  http://127.0.0.1:9999/api/cluster/instances/node1_gpu_user_xxx/connect
```

或通过 Web 界面查看。

### Q: 如何手动同步 FRP 配置
```bash
# 在 Servermanager 节点上
curl -H "X-Internal-Token: YOUR_INTERNAL_SERVICE_TOKEN" http://127.0.0.1:18881/api/frp/sync

# 在 VPS 上
curl -H "Authorization: Bearer TOKEN" http://127.0.0.1:9999/api/frp/sync
```
