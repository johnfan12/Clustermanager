# GPU 集群跳板机聚合管理服务

轻量级 GPU 集群聚合管理平台，通过 frp 内网穿透访问各 GPU 节点的 `gpu_manager` API，
提供**集群总览**和**跨节点实例汇总**功能。不操作 Docker，不连接数据库，纯数据聚合与展示。

---

## 架构说明

```
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

### 1.1 安装 frps

```bash
# 下载 frp（以 v0.52.3 为例）
wget https://github.com/fatedier/frp/releases/download/v0.52.3/frp_0.52.3_linux_amd64.tar.gz
tar -xzf frp_0.52.3_linux_amd64.tar.gz
sudo cp frp_0.52.3_linux_amd64/frps /usr/local/bin/
sudo mkdir -p /etc/frp
sudo cp frp/frps.ini /etc/frp/frps.ini
```

创建 systemd 服务 `/etc/systemd/system/frps.service`：

```ini
[Unit]
Description=frp Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frps -c /etc/frp/frps.ini
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable frps
sudo systemctl start frps
```

### 1.2 部署聚合服务

```bash
cd /opt/cluster_manager    # 或你选择的部署目录
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 修改 config.py 中的配置项（JWT_SECRET、节点列表、admin_token 等）

# 启动服务
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

### 2.2 配置 frpc.ini

以 `frp/frpc.ini.template` 为基础，替换以下内容：

| 占位符 | 说明 |
|--------|------|
| `your-vps-public-ip` | VPS 公网 IP |
| `your-frp-secret-token` | 与 frps.ini 中相同的 token |
| `nodeX` | 节点编号，如 `node1` |
| `1888X` | API 端口，如 `18881` |
| `1002X` | SSH 端口，如 `10021` |

```bash
sudo cp frpc.ini /etc/frp/frpc.ini
```

创建 systemd 服务 `/etc/systemd/system/frpc.service`：

```ini
[Unit]
Description=frp Client
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/frpc -c /etc/frp/frpc.ini
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable frpc
sudo systemctl start frpc
```

---

## 3. admin_token 的获取方法

`config.py` 中每个节点的 `admin_token` 需要从对应节点的 `gpu_manager` 获取：

```bash
# 在 VPS 上（frp 穿透已建立后）
curl -X POST http://localhost:18881/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=节点管理员密码"
```

返回的 `access_token` 即为该节点的 `admin_token`，填入 `config.py` 对应节点配置中。

---

## 4. SSO 原理说明

本项目与各 GPU 节点的 `gpu_manager` 共享同一个 `JWT_SECRET`。

- 用户在跳板机登录后，跳板机使用共享密钥签发 JWT token
- 前端点击"进入管理"时，URL 末尾携带 `?token=xxx`
- 节点 `gpu_manager` 使用相同密钥验证 token，无需再次登录

**关键操作**：确保所有节点 `gpu_manager` 的 `JWT_SECRET` 配置与本项目 `config.py` 中的 `JWT_SECRET` 完全一致。

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
- 更新 `config.py` 并重启聚合服务
