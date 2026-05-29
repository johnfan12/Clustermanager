# 简化版 Clustermanager

这个入口是轻量服务器管理控制台，只聚合节点侧 SSH 内网穿透能力，不包含 Docker、GPU 实例、计费或配额。

项目现在采用前后端分离结构：

- 后端：`main.py`，只提供 `/api/*` 接口和可选的前端构建产物托管。
- 前端：`frontend/`，Vite 管理的独立静态应用。

## 能力范围

- 支持控制台账号自助注册和登录。
- 展示一个或多个 Servermanager 节点。
- 输入节点 Linux userid，生成固定节点 SSH 端口的连接命令。
- 每个节点使用一个固定公网 SSH 端口，所有用户通过自己的 Linux userid 登录同一入口。
- 前端通过 `/api/config` 读取后端运行时配置，不再依赖 `main.py` 内联 HTML。

## 开发启动

```bash
pip install -r requirements.txt
./start.sh
```

后端默认监听 `9999`。

另开一个终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

开发访问地址默认是 `http://localhost:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:9999`。

## 生产部署

可以把前端静态产物交给后端同进程托管：

```bash
cd frontend
npm install
npm run build
cd ..
./start.sh
```

后端默认读取 `frontend/dist`。也可以让 Nginx/Caddy 单独托管 `frontend/dist`，并把 `/api` 反代到后端 `9999`。

## 常用环境变量

```bash
SIMPLE_CLUSTERMANAGER_PORT=9999
SIMPLE_APP_DISPLAY_NAME=简化服务器管理

SIMPLE_JWT_SECRET=replace-with-a-long-random-secret
SIMPLE_INTERNAL_SERVICE_TOKEN=replace-with-a-long-random-token
SIMPLE_AUTH_MODE=account
SIMPLE_ALLOW_REGISTER=true
SIMPLE_FIRST_USER_ADMIN=true
SIMPLE_USERS_DB=runtime/simple-cluster-users.db
SIMPLE_NO_AUTH_USERNAME=

SIMPLE_NODES_JSON='{
  "node1": {
    "name": "节点 1",
    "api": "http://127.0.0.1:18881",
    "public_host": "vps.example.com"
  }
}'

SIMPLE_ADMIN_USERS=admin
SIMPLE_ALLOWED_GROUPS=
SIMPLE_CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:9999,http://127.0.0.1:9999
SIMPLE_SERVE_FRONTEND=true
SIMPLE_FRONTEND_DIST_DIR=frontend/dist
```

`SIMPLE_INTERNAL_SERVICE_TOKEN` 必须和每个简化版 Servermanager 保持一致。

如果节点 API 通过 FRP 暴露到 VPS，例如节点侧 `SIMPLE_API_REMOTE_PORT=18881`，这里的节点地址可以直接写 `http://127.0.0.1:18881`。

## 登录模式

默认 `SIMPLE_AUTH_MODE=account`，用户可在登录页自助注册控制台账号，然后登录。第一个注册用户默认是管理员。

注册账号只用于进入控制台。生成 SSH 命令时填写的 `userid` 仍然必须是节点机上已经存在的 Linux 用户名。

如果要关闭自助注册：

```bash
SIMPLE_ALLOW_REGISTER=false
```

旧的本机账号模式仍然可用：

```bash
SIMPLE_AUTH_MODE=local
```

此时登录用户必须是 VPS 本机账号。

如果希望登录用户必须是节点机本机账号，可以设置：

```bash
SIMPLE_AUTH_MODE=node
SIMPLE_AUTH_NODE_ID=node1
```

这种模式会把登录校验转发给指定 Servermanager 节点的 `/api/login`。

如果只是本机或内网自用，不想要登录页，可以设置：

```bash
SIMPLE_AUTH_MODE=none
SIMPLE_NO_AUTH_USERNAME=fan
SIMPLE_NO_AUTH_IS_ADMIN=true
```

`SIMPLE_NO_AUTH_USERNAME` 要填节点机上已经存在的 Linux 用户名，因为 Clustermanager 会用这个用户名调用节点 API。`none` 模式没有登录保护，不要直接暴露到公网。

## 账号规则

默认只允许 UID 大于等于 `1000` 且 shell 不是 `nologin/false` 的 VPS 本机用户登录。可通过这些变量调整：

- `SIMPLE_ALLOWED_UID_MIN`
- `SIMPLE_ALLOW_SYSTEM_USERS`
- `SIMPLE_ALLOWED_GROUPS`
- `SIMPLE_ADMIN_USERS`
- `SIMPLE_ADMIN_GROUPS`

PAM 依赖可用 `pip install python-pam` 安装；部分系统也可以使用发行版包 `python3-pam`。

## 前端环境变量

前端开发配置可参考 `frontend/.env.example`：

```bash
VITE_API_BASE_URL=
VITE_PROXY_API_TARGET=http://127.0.0.1:9999
```

如果前端和后端不是同源部署，构建前设置 `VITE_API_BASE_URL` 为后端 API 地址，例如 `https://api.example.com`。
