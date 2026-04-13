"""认证模块 - 中心认证、节点影子用户同步与 JWT 验证。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from database import get_db
from models import ClusterUser
from user_store import (
    create_cluster_user,
    get_cluster_user,
    init_user_store,
    get_cluster_user_sync_record,
    verify_cluster_user_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
AUTH_REQUEST_TIMEOUT = 8.0


# ── Pydantic 模型 ──────────────────────────────────────────────────────────


class TokenResponse(BaseModel):
    """登录成功返回的 token 响应体。"""

    access_token: str
    token_type: str = "bearer"
    username: str
    is_admin: bool
    user: dict[str, Any] | None = None
    node_id: str | None = None
    message: str | None = None


class RegisterResponse(TokenResponse):
    """Register response which may defer login until admin approval."""

    access_token: str | None = None
    pending_approval: bool = False


class NodeLoginRequest(BaseModel):
    """用户登录到聚合层；可选指定登录后的首选节点。"""

    node_id: str | None = Field(default=None, max_length=64)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class NodeRegisterRequest(BaseModel):
    """用户注册聚合层账号；可选指定注册后的首选节点。"""

    node_id: str | None = Field(default=None, max_length=64)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    email: str
    password: str = Field(min_length=6, max_length=128)


# ── JWT 工具函数 ───────────────────────────────────────────────────────────


def create_token(username: str, is_admin: bool = False, email: str | None = None) -> str:
    """生成 JWT token。

    Args:
        username: 用户名
        is_admin: 是否管理员

    Returns:
        编码后的 JWT 字符串
    """
    expire = datetime.utcnow() + timedelta(hours=config.JWT_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "is_admin": is_admin,
        "exp": expire,
    }
    if email:
        payload["email"] = email
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def _get_node_config(node_id: str) -> dict[str, Any]:
    """返回指定节点配置，不存在时抛出 404。"""
    node_cfg = config.NODES.get(node_id)
    if node_cfg is None:
        raise HTTPException(status_code=404, detail="节点不存在")
    return node_cfg


def _build_token_response(
    username: str,
    email: str | None,
    is_admin: bool,
    *,
    node_id: str | None = None,
    message: str | None = None,
) -> TokenResponse:
    """统一组装聚合层登录/注册响应。"""
    user_payload = {
        "username": username,
        "email": email,
        "is_admin": is_admin,
    }
    cluster_token = create_token(username=username, is_admin=is_admin, email=email)
    return TokenResponse(
        access_token=cluster_token,
        username=username,
        is_admin=is_admin,
        user=user_payload,
        node_id=node_id,
        message=message,
    )


def _build_pending_register_response(
    username: str,
    email: str,
    *,
    message: str,
) -> RegisterResponse:
    """Return a register response for accounts waiting for admin approval."""
    return RegisterResponse(
        access_token=None,
        username=username,
        is_admin=False,
        user={
            "username": username,
            "email": email,
            "is_admin": False,
            "register_status": "pending",
        },
        message=message,
        pending_approval=True,
    )


def _resolve_target_node_id(node_id: str | None) -> str | None:
    """Resolve the preferred node for post-login sync without making auth depend on it."""
    normalized = (node_id or "").strip()
    if normalized:
        _get_node_config(normalized)
        return normalized
    if not config.NODES:
        return None
    return next(iter(config.NODES))


async def _sync_cluster_user_to_node(
    node_id: str | None,
    username: str,
    *,
    is_admin: bool,
) -> bool:
    """Best-effort push one central/shadow user snapshot to the selected node."""
    if not node_id:
        return False

    node_cfg = _get_node_config(node_id)
    user_record = get_cluster_user_sync_record(username)
    if user_record is None:
        if not is_admin or username != config.ADMIN_USERNAME:
            return False
        user_record = {
            "username": username,
            "email": f"{username}@local",
            "ssh_public_keys": [],
        }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{node_cfg['api']}/api/internal/users/sync",
                headers={"X-Internal-Token": config.INTERNAL_SERVICE_TOKEN},
                json={
                    **user_record,
                    "is_admin": is_admin,
                },
                timeout=AUTH_REQUEST_TIMEOUT,
            )
        response.raise_for_status()
        return True
    except Exception:
        return False


def _build_login_message(synced: bool, node_id: str | None, action: str) -> str | None:
    """Return one user-facing login/register message based on sync result."""
    if not node_id:
        return None
    if synced:
        return f"{action}成功，目标节点账号已同步"
    return f"{action}成功；目标节点暂不可达，稍后会自动补建账号"


async def _fetch_node_auth_meta(
    client: httpx.AsyncClient,
    node_id: str,
    node_cfg: dict[str, Any],
) -> dict[str, Any]:
    """查询节点在线状态，供认证页展示。"""
    result = {
        "node_id": node_id,
        "name": node_cfg.get("name", node_id),
        "online": False,
    }
    try:
        response = await client.get(
            f"{node_cfg['api']}/api/meta",
            timeout=3.0,
        )
        response.raise_for_status()
        result["online"] = True
    except Exception:
        pass
    return result


def get_current_user_info(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """从 JWT token 中验证并提取用户信息。"""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或 token 已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM]
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token 或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    username: Optional[str] = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
        )
    is_admin = bool(payload.get("is_admin", username == config.ADMIN_USERNAME))
    if is_admin and username == config.ADMIN_USERNAME:
        return {
            "username": username,
            "is_admin": True,
            "email": payload.get("email"),
        }

    user = db.get(ClusterUser, username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号不存在或已被删除",
        )
    if str(user.register_status or "approved") != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号待管理员审批",
        )
    return {
        "username": str(user.username),
        "is_admin": is_admin,
        "email": str(user.email),
    }


def get_current_user(
    user_info: dict[str, Any] = Depends(get_current_user_info),
) -> str:
    """Return the authenticated username after active-user validation."""
    return str(user_info["username"])


def get_optional_user(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    """尝试从 token 中提取用户名，失败时返回 None（不抛异常）。

    Args:
        token: Bearer token

    Returns:
        用户名字符串或 None
    """
    if token is None:
        return None
    try:
        payload = jwt.decode(
            token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM]
        )
        return payload.get("sub")
    except JWTError:
        return None


# ── 登录端点 ───────────────────────────────────────────────────────────────


@router.get("/nodes")
async def list_auth_nodes() -> dict[str, Any]:
    """返回可登录/注册的节点列表。"""
    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_node_auth_meta(client, node_id, node_cfg)
            for node_id, node_cfg in config.NODES.items()
        ]
        nodes = await asyncio.gather(*tasks)
    return {
        "nodes": nodes,
        "app_display_name": config.APP_DISPLAY_NAME,
        "allow_register": config.ALLOW_REGISTER,
        "allow_register_mode": config.ALLOW_REGISTER_MODE,
    }


@router.post("/login", response_model=TokenResponse)
async def login(payload: NodeLoginRequest) -> TokenResponse:
    """Authenticate against the central store and optionally sync a shadow user to one node."""
    target_node_id = _resolve_target_node_id(payload.node_id)

    if (
        payload.username == config.ADMIN_USERNAME
        and payload.password == config.ADMIN_PASSWORD
    ):
        synced = await _sync_cluster_user_to_node(
            target_node_id,
            payload.username,
            is_admin=True,
        )
        return _build_token_response(
            username=payload.username,
            email=f"{payload.username}@local",
            is_admin=True,
            node_id=target_node_id,
            message=_build_login_message(synced, target_node_id, "登录"),
        )

    central_user = get_cluster_user(payload.username)
    if central_user is None or not verify_cluster_user_password(
        payload.username, payload.password
    ):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if str(central_user.get("register_status") or "approved") != "approved":
        raise HTTPException(status_code=403, detail="账号待管理员审批")

    synced = await _sync_cluster_user_to_node(
        target_node_id,
        payload.username,
        is_admin=False,
    )
    return _build_token_response(
        username=payload.username,
        email=str(central_user["email"]),
        is_admin=False,
        node_id=target_node_id,
        message=_build_login_message(synced, target_node_id, "登录"),
    )


@router.post("/register", response_model=RegisterResponse)
async def register(payload: NodeRegisterRequest) -> RegisterResponse:
    """Register centrally and best-effort sync a shadow user to the preferred node."""
    if payload.username == config.ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="该用户名为保留管理员账号")
    if config.ALLOW_REGISTER_MODE == "false":
        raise HTTPException(status_code=403, detail="当前未开放公开注册")

    register_status = (
        "pending"
        if config.ALLOW_REGISTER_MODE == "allow_with_permission"
        else "approved"
    )

    try:
        create_cluster_user(
            payload.username,
            payload.email,
            payload.password,
            register_status=register_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if register_status == "pending":
        return _build_pending_register_response(
            payload.username,
            payload.email,
            message="注册申请已提交，等待管理员审批后方可登录",
        )

    target_node_id = _resolve_target_node_id(payload.node_id)
    synced = await _sync_cluster_user_to_node(
        target_node_id,
        payload.username,
        is_admin=False,
    )
    return _build_token_response(
        username=payload.username,
        email=payload.email,
        is_admin=False,
        node_id=target_node_id,
        message=_build_login_message(synced, target_node_id, "注册"),
    )


@router.get("/me")
async def me(username: str = Depends(get_current_user)) -> dict[str, Any]:
    """返回当前聚合层登录用户名。"""
    return {"username": username}


@router.on_event("startup")
async def _auth_startup() -> None:
    """Initialize central user store for node auto-provision."""
    init_user_store()
