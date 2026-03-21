# Clustermanager AGENTS

## 项目定位

Clustermanager 是 VPS 聚合层，负责：

- 聚合多个 Servermanager 节点
- 统一登录/注册入口
- 集群状态与跨节点实例展示
- FRP visitor 侧每实例隧道管理

## 当前实现基线

- FastAPI + httpx 聚合
- 前端单页（注册/登录/选节点/进入节点）
- per-instance FRP visitor 服务：`frpc-visitor@<container>.service`
- 中心用户库 + 新节点首次登录自动补建账号

## 安全修复计划（Clustermanager 侧）

### 1. 代理接口收口（SSRF 防护）

- [x] `/api/proxy/{node_id}/{path:path}` 强制登录鉴权。
- [x] 仅允许代理白名单路径与白名单方法。
- [x] 过滤危险 headers 与可疑路径（编码绕过、目录穿透等）。
- [x] 目标地址仅允许来自 `NODES_JSON` 固定节点。

### 2. BOLA/IDOR 修复

- [x] 所有实例连接信息接口按 owner/admin 严格校验。
- [x] 普通用户仅能查询自己实例的 FRP 映射和连接信息。
- [x] 管理员全量查询能力与普通用户路径分离。

### 3. 用户态与管理员态令牌隔离

- [x] 禁止普通用户流程使用节点 `admin_token` 查询实例详情。
- [x] 用户实例查询透传当前用户 JWT。
- [x] 管理员汇总能力仅用于后台受控接口。

### 4. 元信息暴露控制

- [x] `cluster/status`、`node_urls` 默认需要登录。
- 若保留公开版，必须提供脱敏响应（不暴露内部 URL/实例细节）。

### 5. 生产密钥强校验

- [x] 增加 `ENV`（`dev|prod`）。
- [x] `prod` 下，缺失或默认值即拒绝启动：
  - `JWT_SECRET`
  - `INTERNAL_SERVICE_TOKEN`
  - `ADMIN_PASSWORD`
  - `FRP_TOKEN`

### 6. FRP visitor 可用性门槛

- 仅在 `frpc-visitor@<container>` active 且 bind_port 实际监听时才返回映射。
- 映射未就绪时前端显示“隧道同步中”，避免误导用户连接失败。

## 跨项目同步要求（与 Servermanager 对齐）

- `JWT_SECRET`、`INTERNAL_SERVICE_TOKEN` 必须全节点一致。
- 服务间写接口统一使用 `X-Internal-Token`。
- 日志统一记录鉴权失败、越权拒绝、代理拒绝和 FRP 就绪失败。

## 验收要点（Clustermanager）

- 匿名无法访问代理和敏感聚合接口。
- 普通用户无法读取他人实例连接信息。
- FRP 映射返回前已通过服务活性与端口监听检查。
- 默认密钥在生产环境无法启动。

## PostgreSQL 迁移路线

迁移原则：

- [x] 确认采用 PostgreSQL，且从 `Clustermanager` 先开始迁移。
- [x] 项目尚未上线，按全新 PostgreSQL 架构直接落地，不保留 SQLite 兼容路径。
- [x] 先完成中心侧数据库基础设施，再推进到各 `Servermanager` 节点。

执行步骤：

- [x] 第 1 步：为 `Clustermanager` 引入 PostgreSQL 连接配置，使用中心库连接串作为唯一数据库配置。
- [x] 第 2 步：将 `user_store.py` 从 `sqlite3` 实现改为 PostgreSQL 存储层，优先统一到 SQLAlchemy。
- [x] 第 3 步：为中心用户库补 schema migration 能力，使用 migration 管理表结构。
- [x] 第 4 步：完成 `Clustermanager` 本地联调，验证认证与聚合接口正常。
- [ ] 第 5 步：`Clustermanager` 稳定后，再启动 `Servermanager` PostgreSQL 改造。

关键验收点：

- [x] 登录、注册流程正常。
- [ ] 聚合首页、节点列表、我的实例接口正常。
- [ ] 服务可通过 PostgreSQL 正常启动并自动执行 Alembic migration。
