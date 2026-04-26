# GPU 集群跳板机聚合管理服务

聚合多个 Servermanager 节点，提供统一登录、节点总览、实例汇总与一键进入节点。

## 核心功能

- 统一认证入口：注册/登录 -> 进入控制台 -> 按需进入节点
- 集群总览：节点在线状态、GPU 空闲数、实例数
- 我的实例：跨节点汇总并展示 SSH 信息
- 自动 FRP visitor 管理（每实例独立 `frpc-visitor@<container>.service`）
- 服务间回写 `vps_access` 到节点实例
- 中心用户库 + 节点影子用户自动补建（新增节点或节点缺少用户快照时自动同步）

## 快速启动

### 新部署（推荐流程）

适用于首次在新机器部署，按顺序执行：

#### 1. 安装 FRP

执行 FRP 安装脚本：

```bash
cd frp
sudo bash install.sh
cd ..
```

安装完成后，确认以下服务配置正确：
- VPS 端 frps 服务已启动并监听配置端口
- 节点 API 隧道：配合节点侧的 `frpc-api.service`
- Visitor 隧道：由后端自动维护 per-instance 配置到 `/etc/frp/visitors/*.ini`

#### 2. 安装并初始化 PostgreSQL

安装 PostgreSQL（如未安装）：

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install postgresql postgresql-contrib

# 启动 PostgreSQL 服务
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

创建数据库和账号：

```sql
sudo -u postgres psql
CREATE USER cluster_user WITH PASSWORD 'cluster_pass';
CREATE DATABASE cluster_manager OWNER cluster_user;
\q
```

#### 3. 配置环境变量

进入项目目录并安装 Python 依赖：

```bash
cd Clustermanager

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.copy .env
mkdir -p logs
```

编辑 `.env`，至少确认以下配置：

```env
APP_DISPLAY_NAME=GPU 集群管理
CLUSTER_DATABASE_URL=postgresql+psycopg://cluster_user:cluster_pass@127.0.0.1:5432/cluster_manager
GPU_HOURS_DEFAULT_QUOTA=100
GPU_HOURS_RESET_TIMEZONE=Asia/Shanghai
JWT_SECRET=your-jwt-secret
JWT_EXPIRE_HOURS=168
INTERNAL_SERVICE_TOKEN=your-internal-token
FRP_TOKEN=your-frp-token
```

初始化数据库：

```bash
alembic current
alembic upgrade head
alembic current
```

如果系统找不到 `alembic` 命令，可替代为：

```bash
python3 -m alembic -c alembic.ini current
python3 -m alembic -c alembic.ini upgrade head
python3 -m alembic -c alembic.ini current
```

确认 `current` 显示最新 revision 后，启动服务：

```bash
chmod +x start.sh
./start.sh
```

默认地址：`http://127.0.0.1:9999`

`start.sh` 会先执行 `alembic upgrade head`，然后再启动 `uvicorn`。

## 前端配置

### 方式一：独立开发模式（推荐开发时使用）

前端使用 Vue 3 + TypeScript + Vite 构建。

```bash
cd frontend
npm install
npm run dev
```

开发服务器默认在 `http://localhost:5173`，会自动代理到后端 `http://127.0.0.1:9999`。

### 方式二：集成到后端（生产部署）

```bash
cd frontend
npm install
npm run build
```

构建后的文件位于 `frontend/dist/`，会被后端自动挂载为静态文件服务。

`start.sh` 会先执行：

```bash
alembic upgrade head
```

然后再启动 `uvicorn`。

如果你只想手动初始化数据库，也可以执行：

```bash
alembic upgrade head
```

## 关键配置

- `APP_DISPLAY_NAME`：登录页顶部展示名称，可替换为你的组织名或平台名
- `JWT_SECRET`：需与所有 Servermanager 保持一致
- `JWT_EXPIRE_HOURS`：登录会话有效期，默认 `168` 小时（7 天）；修改后需重启 Clustermanager 并重新登录才会签发新时长 token
- `INTERNAL_SERVICE_TOKEN`：需与所有 Servermanager 保持一致
- `NODES_JSON`：节点 API 地址与展示信息
- `FRP_TOKEN`：与 frps 一致
- `FRP_VISITOR_CONFIG_DIR`：默认 `/etc/frp/visitors`
- `CLUSTER_DATABASE_URL`、`AUTO_PROVISION_ON_NODE_LOGIN`
- `GPU_HOURS_DEFAULT_QUOTA`：新用户默认卡时额度，由 Clustermanager 统一管理
- `GPU_HOURS_RESET_TIMEZONE`：每月 1 号自动重置卡时所使用的时区
- Alembic 配置：`alembic.ini`

## 常见问题（QA）

### Q0: 服务启动时报数据库连接失败
- 先确认 PostgreSQL 已启动，且 `CLUSTER_DATABASE_URL` 中的库、用户、密码正确。
- 再手动执行：`alembic upgrade head`
- 若连接串可达但 migration 失败，先检查数据库权限是否允许建表和建索引。

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
- 用户首次访问新节点时，会从中心用户库自动补建节点影子账号。

## 相关文件

- 配置：`config.py`、`.env.copy`
- 数据库：`database.py`、`models.py`、`alembic.ini`、`alembic/`
- 聚合入口：`main.py`、`auth.py`
- FRP：`frp_manager.py`、`frp/install.sh`
