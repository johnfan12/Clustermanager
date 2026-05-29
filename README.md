# 简化版 Clustermanager

这个入口是轻量服务器管理控制台，只聚合节点侧内网穿透能力，不包含注册、Docker、GPU 实例、计费或配额。

## 能力范围

- 使用 VPS 本机 Linux 账号通过 PAM 登录。
- 展示一个或多个 Servermanager 节点。
- 创建 TCP 隧道并显示公网地址和端口。
- 删除自己的隧道；管理员可查看和删除所有隧道。
- 前端由 `main.py` 直接提供，不需要 Vue 构建。

## 启动

```bash
pip install -r requirements.txt
./start.sh
```

默认访问端口是 `9999`。

## 常用环境变量

```bash
SIMPLE_CLUSTERMANAGER_PORT=9999
SIMPLE_APP_DISPLAY_NAME=简化服务器管理

SIMPLE_JWT_SECRET=replace-with-a-long-random-secret
SIMPLE_INTERNAL_SERVICE_TOKEN=replace-with-a-long-random-token
SIMPLE_AUTH_MODE=local

SIMPLE_NODES_JSON='{
  "node1": {
    "name": "节点 1",
    "api": "http://127.0.0.1:18881",
    "public_host": "vps.example.com"
  }
}'

SIMPLE_ADMIN_USERS=admin
SIMPLE_ALLOWED_GROUPS=
```

`SIMPLE_INTERNAL_SERVICE_TOKEN` 必须和每个简化版 Servermanager 保持一致。

如果节点 API 通过 FRP 暴露到 VPS，例如节点侧 `SIMPLE_API_REMOTE_PORT=18881`，这里的节点地址可以直接写 `http://127.0.0.1:18881`。

## 登录模式

默认 `SIMPLE_AUTH_MODE=local`，登录用户必须是 VPS 本机账号。

如果希望登录用户必须是节点机本机账号，可以设置：

```bash
SIMPLE_AUTH_MODE=node
SIMPLE_AUTH_NODE_ID=node1
```

这种模式会把登录校验转发给指定 Servermanager 节点的 `/api/login`。

## 账号规则

默认只允许 UID 大于等于 `1000` 且 shell 不是 `nologin/false` 的 VPS 本机用户登录。可通过这些变量调整：

- `SIMPLE_ALLOWED_UID_MIN`
- `SIMPLE_ALLOW_SYSTEM_USERS`
- `SIMPLE_ALLOWED_GROUPS`
- `SIMPLE_ADMIN_USERS`
- `SIMPLE_ADMIN_GROUPS`

PAM 依赖可用 `pip install python-pam` 安装；部分系统也可以使用发行版包 `python3-pam`。
