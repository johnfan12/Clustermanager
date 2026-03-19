# GPU 集群跳板机聚合管理服务

聚合多个 Servermanager 节点，提供统一登录、节点总览、实例汇总与一键进入节点。

## 核心功能

- 统一认证入口：注册/登录 -> 选择节点 -> 进入节点
- 集群总览：节点在线状态、GPU 空闲数、实例数
- 我的实例：跨节点汇总并展示 SSH 信息
- 自动 FRP visitor 管理（每实例独立 `frpc-visitor@<container>.service`）
- 服务间回写 `vps_access` 到节点实例
- 中心用户库 + 自动补建（新增节点后首次登录自动同步账号）

## 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.copy .env
mkdir -p logs

cd frp
sudo bash install.sh
cd ..

chmod +x start.sh
./start.sh
```

默认地址：`http://127.0.0.1:9999`

## 关键配置

- `JWT_SECRET`：需与所有 Servermanager 保持一致
- `INTERNAL_SERVICE_TOKEN`：需与所有 Servermanager 保持一致
- `NODES_JSON`：节点 API 地址与 admin_token
- `NODE_WEB_URLS_JSON`：前端“进入服务器”跳转地址
- `FRP_TOKEN`：与 frps 一致
- `FRP_VISITOR_CONFIG_DIR`：默认 `/etc/frp/visitors`
- `CLUSTER_USER_DB_PATH`、`AUTO_PROVISION_ON_NODE_LOGIN`

## 常见问题（QA）

### Q1: 登录后看不到节点信息 / 节点离线
- 检查 `NODES_JSON.api` 是否可从 VPS 访问。
- 在 VPS 上测试：`curl http://127.0.0.1:18881/api/meta`
- 常见原因是节点 `frpc-api` 未启动或 frps 端口未放行。

### Q2: 页面显示本地 SSH 端口，不是 VPS 端口
- 先查 `Clustermanager` 日志是否有 `vps-access` 回写失败（404/401）。
- 再查节点 `/api/frp/containers` 和 VPS visitor 映射是否一致。
- 如有旧实例，确认已完成 per-instance 配置迁移。

### Q3: SSH 命令端口正确，但连接仍 `Connection closed`
- 检查 VPS visitor 服务：`systemctl status "frpc-visitor@<container>.service"`
- 检查节点 container 服务：`systemctl status "frpc-container@<container>.service"`
- 两侧都 active 且 VPS bind_port 在监听后再测试 SSH。

### Q4: 日志出现 `Interactive authentication required`
- 运行用户缺少管理 `frpc-visitor@*`（VPS）或 `frpc-container@*`（节点）的 sudo 权限。
- 配置免密 sudo 后重启服务。

### Q5: 新增节点后，用户需要重新注册吗？
- 默认不需要（`AUTO_PROVISION_ON_NODE_LOGIN=true`）。
- 用户首次登录新节点时，会从中心用户库校验并自动补建账号。

## 相关文件

- 配置：`config.py`、`.env.copy`
- 聚合入口：`main.py`、`auth.py`
- FRP：`frp_manager.py`、`frp/install.sh`
