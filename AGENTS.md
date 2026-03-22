# Clustermanager AGENTS

已核对并移除所有已落地的勾选项，以下仅保留未完成事项。

## 待处理问题

### FRP visitor 可用性门槛

- [ ] 映射未就绪时前端显示“隧道同步中”，避免误导用户连接失败。

### 跨项目同步要求

- [ ] `JWT_SECRET`、`INTERNAL_SERVICE_TOKEN` 必须全节点一致。
- [ ] 服务间写接口统一使用 `X-Internal-Token`。
- [ ] 日志统一记录鉴权失败、越权拒绝、代理拒绝和 FRP 就绪失败。

### PostgreSQL 迁移

- [ ] 第 5 步：`Clustermanager` 稳定后，再启动 `Servermanager` PostgreSQL 改造。

## 待验收

- [ ] 聚合首页、节点列表、我的实例接口正常。
- [ ] 服务可通过 PostgreSQL 正常启动并自动执行 Alembic migration。
