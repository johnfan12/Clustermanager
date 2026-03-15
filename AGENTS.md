# 任务：构建 GPU 集群跳板机聚合管理服务

## 项目背景
已有多台 GPU 服务器，每台都运行了独立的 gpu_manager 管理系统（FastAPI，端口8888）。
现需要在一台公网 VPS 上部署一个轻量聚合服务，通过 frp 内网穿透访问各节点 API，
提供集群总览和跨节点实例汇总功能。本项目不操作 Docker，不连接数据库，只做数据聚合和展示。

## 技术栈
- 后端：Python 3.10+ / FastAPI
- 前端：单文件 HTML（内嵌 CSS/JS）
- 认证：JWT（与各节点 gpu_manager 共享同一个 JWT_SECRET，实现 SSO）
- 内网穿透：frp
- 反向代理：Nginx

---

## 目录结构

cluster_manager/
├── main.py
├── config.py
├── auth.py
├── static/
│   └── index.html
├── frp/
│   ├── frps.ini
│   └── frpc.ini.template
├── nginx/
│   └── gpu.conf
├── requirements.txt
├── start.sh
└── README.md

---

## 各文件详细说明

### 1. config.py
```python
# JWT 必须与所有 gpu_manager 节点的 JWT_SECRET 完全一致，用于 SSO
JWT_SECRET = "change-this-secret"
JWT_EXPIRE_HOURS = 24

# 集群节点列表
# api 地址填 VPS 本地地址（frp 穿透后的端口）
# admin_token 填对应节点 gpu_manager 的管理员 JWT token，用于聚合服务拉取全局数据
NODES = {
    "node1": {
        "name":      "节点1 · A100 × 8",
        "api":       "http://localhost:18881",   # frp 穿透到 VPS 的本地端口
        "admin_token": "node1-admin-jwt-token",
        "gpu_count": 8,
        "gpu_model": "A100 80G",
    },
    "node2": {
        "name":      "节点2 · RTX3090 × 4",
        "api":       "http://localhost:18882",
        "admin_token": "node2-admin-jwt-token",
        "gpu_count": 4,
        "gpu_model": "RTX 3090 24G",
    },
}

# 跳板机自身的管理员账号（用于跳板机登录，不依赖节点）
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# 各节点 gpu_manager 的 Web 访问地址（用于前端"进入"按钮跳转）
# 填 VPS 公网 IP + frp 穿透的 HTTP 端口，或独立域名
NODE_WEB_URLS = {
    "node1": "http://your-vps-ip:18881",
    "node2": "http://your-vps-ip:18882",
}
```

### 2. auth.py

实现以下功能：
- `create_token(username, is_admin)` → 生成 JWT，使用 config.JWT_SECRET 签名
- `get_current_user(token)` → 验证 JWT，返回 username
- POST `/api/auth/login` 端点：验证用户名密码（暂时只支持 config 里的 ADMIN 账号，
  后续可对接各节点的用户体系），登录成功返回 JWT token
- 由于与各节点共享 JWT_SECRET，跳板机签发的 token 在各节点同样有效，
  前端跳转时携带 token 即可免登录

### 3. main.py

#### 集群状态接口
GET `/api/cluster/status`
- 并发请求所有节点的 `/api/gpus/status` 和 `/api/admin/instances`
- 每个节点请求超时设为 5 秒，失败时该节点标记为 offline，不影响其他节点
- 返回结构：
```json
  {
    "nodes": [
      {
        "node_id":        "node1",
        "name":           "节点1 · A100 × 8",
        "online":         true,
        "gpu_model":      "A100 80G",
        "gpu_total":      8,
        "gpu_free":       5,
        "gpu_used":       3,
        "instance_count": 3,
        "gpus": [
          {"index": 0, "status": "used", "allocated_to": "alice"},
          {"index": 1, "status": "free"}
        ]
      }
    ],
    "summary": {
      "total_gpu":    12,
      "free_gpu":     7,
      "total_instances": 5
    }
  }
```

#### 我的实例接口
GET `/api/cluster/my_instances`（需登录）
- 并发请求所有节点的 `/api/instances`，携带当前用户的 token
- 每条实例附加 `node_id` 和 `node_name` 字段
- 离线节点跳过，不报错
- 返回该用户在所有节点的实例列表合并结果

#### 节点直连代理接口（可选）
GET `/api/proxy/{node_id}/{path:path}`
- 将请求透明转发到对应节点，保留 Authorization header
- 用于前端不跳转页面、直接在总览界面操作实例（停止/重启）

### 4. static/index.html（单文件前端）

风格与 gpu_manager 的前端保持一致：白色背景，紧凑布局，#409eff 主色蓝。

#### 登录页
- 居中卡片，用户名+密码输入框，登录按钮
- 登录成功后 token 存入 localStorage，切换到主界面

#### 主界面布局
- 顶部 header：左侧"GPU 集群管理"，右侧显示当前用户名和退出按钮
- 主体单列，从上到下分为两个区块

#### 区块一：集群总览
- 标题行："集群总览"，右侧显示汇总数据：
  总 GPU X 张 · 空闲 X 张 · 运行实例 X 个
- 节点列表以表格展示，列：
  节点名称 | 状态 | GPU空闲/总数 | GPU型号 | 运行实例数 | 操作
  - 状态列：● 在线（绿）/ ○ 离线（灰）
  - GPU空闲列：用 X/Y 格式，空闲数为0时标红
  - 操作列："进入管理"按钮，点击在新标签页打开对应节点 Web 地址，
    URL 末尾携带 `?token=xxx` 实现免登录跳转
- 展开行：点击节点行可展开，显示该节点每张 GPU 的状态（序号+占用者用户名/空闲）

#### 区块二：我的实例
- 标题行："我的实例"，右侧显示"共 X 个运行中"
- 实例以表格展示，列：
  节点 | 实例名 | GPU数 | 内存 | 镜像 | 状态 | SSH连接 | 密码 | 到期时间
  - SSH连接列：显示完整命令，旁边复制按钮
  - 密码列：默认 `****`，眼睛图标点击显示明文
  - 状态列：绿色"运行中" / 灰色"已停止"
- 无实例时显示"暂无运行中的实例"

#### 自动刷新
- 集群总览每 30 秒自动刷新一次
- 刷新时不闪烁，静默更新数据
- 右上角显示"上次更新: HH:MM:SS"

#### 样式要求
- 与 gpu_manager 前端完全一致：背景 #ffffff，侧边栏 #f7f8fa，边框 #e4e7ed，主色 #409eff
- 纯 CSS，不引入任何框架，unicode 字符代替图标
- 表格行 hover 浅蓝背景

### 5. frp/frps.ini（VPS 端）
```ini
[common]
bind_port = 7000
token = your-frp-secret-token
# 可选：dashboard 监控 frp 连接状态
dashboard_port = 7500
dashboard_user = admin
dashboard_pwd  = admin123
```

### 6. frp/frpc.ini.template（GPU 节点端模板）
```ini
[common]
server_addr = your-vps-public-ip
server_port = 7000
token = your-frp-secret-token

# 节点管理 API（供聚合服务调用）
[gpu-nodeX-api]
type = tcp
local_ip   = 127.0.0.1
local_port = 8888
remote_port = 1888X          # 节点1用18881，节点2用18882，以此类推

# 节点 SSH（方便运维直连）
[gpu-nodeX-ssh]
type = tcp
local_ip   = 127.0.0.1
local_port = 22
remote_port = 1002X          # 节点1用10021，节点2用10022，以此类推
```

### 7. nginx/gpu.conf
```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 强制跳转 HTTPS（申请证书后启用）
    # return 301 https://$host$request_uri;

    location / {
        proxy_pass         http://localhost:9999;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 30s;
    }
}

# HTTPS 配置（使用 certbot 申请证书后启用）
# server {
#     listen 443 ssl;
#     server_name your-domain.com;
#     ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
#     ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
#     location / {
#         proxy_pass http://localhost:9999;
#     }
# }
```

### 8. requirements.txt

包含：fastapi, uvicorn, httpx, python-jose[cryptography], passlib[bcrypt]

### 9. start.sh
```bash
#!/bin/bash
uvicorn main:app --host 0.0.0.0 --port 9999
```

### 10. README.md

包含以下章节：
1. 架构说明（一张文字拓扑图）
2. VPS 部署步骤：
   - 安装 frps 并配置开机自启（systemd service）
   - 部署聚合服务
   - 配置 Nginx
   - 可选：certbot 申请 HTTPS 证书
3. 每台 GPU 节点配置步骤：
   - 安装 frpc 并配置开机自启
   - 修改 frpc.ini 中的节点编号和端口
4. config.py 中 admin_token 的获取方法
   （调用对应节点的 /api/auth/login 接口获取管理员 token 填入）
5. SSO 原理说明：确保所有节点 gpu_manager 的 JWT_SECRET 与本项目一致
6. 常见问题：frp 连接失败排查、节点显示离线排查

---

## 代码要求

1. 所有对节点的请求必须有 try/except，单个节点异常不影响整体返回
2. 并发请求使用 asyncio.gather，不允许串行请求节点（影响响应速度）
3. 每个函数写 docstring 和类型注解
4. 使用 Python logging 记录节点请求失败的详细错误到 logs/aggregator.log